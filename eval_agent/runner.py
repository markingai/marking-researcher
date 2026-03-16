"""Evaluation runner - orchestrates API calls across strategies and samples."""

from __future__ import annotations
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import config
from .data_loader import MarkingRow, get_few_shot_examples, get_english_full_exemplars
from .strategies import Strategy, parse_simple, parse_verify, parse_english_criterion
from .base_client import BaseClient
from .gemini_client import GeminiClient


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0
    model: str = ""

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
            model=self.model or other.model,
        )

    def cost_usd(self) -> float:
        """Compute estimated cost using pricing from config."""
        from . import config as _cfg
        pricing = _cfg.MODEL_PRICING.get(self.model, {})
        input_rate = pricing.get("input", 0) / 1_000_000
        output_rate = pricing.get("output", 0) / 1_000_000
        # Thinking tokens are billed at output rate for most providers
        thinking_rate = pricing.get("thinking", output_rate)
        return (
            self.prompt_tokens * input_rate
            + self.output_tokens * output_rate
            + self.thinking_tokens * thinking_rate
        )


@dataclass
class EvalResult:
    strategy_name: str
    row_id: str
    subject: str
    question_number: str
    total_marks: int
    human_mark: float
    ai_mark: float  # int for maths, float for half-mark English strategies
    justification: str
    error: bool = False
    criteria_breakdown: list | None = None
    second_pass_changed: bool | None = None
    usage: TokenUsage = field(default_factory=TokenUsage)
    debate_rounds: int | None = None
    debate_outcome: str | None = None  # agreed/conceded/compromise/deadlock/unanimous/majority/median


class EvalRunner:
    def __init__(
        self,
        strategies: list[Strategy],
        maths_sample: list[MarkingRow],
        english_sample: list[MarkingRow],
        all_maths: list[MarkingRow] | None = None,
        all_english: list[MarkingRow] | None = None,
        custom_samples: dict[str, list[MarkingRow]] | None = None,
    ):
        self.strategies = strategies
        self.maths_sample = maths_sample
        self.english_sample = english_sample
        self.all_maths = all_maths or []
        self.all_english = all_english or []
        self.custom_samples = custom_samples or {}
        self.results: list[EvalResult] = []
        self._results_lock = threading.Lock()
        self._clients: dict[str, BaseClient] = {}

        # Pre-compute sample IDs for few-shot exclusion
        self._maths_sample_ids = {r.row_id for r in maths_sample}
        self._english_sample_ids = {r.row_id for r in english_sample}

        # Cache few-shot examples per question number
        self._few_shot_cache: dict[str, list[MarkingRow]] = {}
        self._cache_lock = threading.Lock()

    def _get_client(self, model: str, provider: str = "gemini") -> BaseClient:
        key = f"{provider}:{model}"
        if key not in self._clients:
            if provider == "gemini":
                self._clients[key] = GeminiClient(model=model)
            elif provider == "anthropic":
                from .anthropic_client import AnthropicClient
                self._clients[key] = AnthropicClient(model=model)
            elif provider == "openai":
                from .openai_client import OpenAIClient
                self._clients[key] = OpenAIClient(model=model)
            else:
                raise ValueError(f"Unknown provider: {provider}")
        return self._clients[key]

    def _get_few_shot(self, question_number: str) -> list[MarkingRow]:
        with self._cache_lock:
            if question_number not in self._few_shot_cache:
                self._few_shot_cache[question_number] = get_few_shot_examples(
                    self.all_maths, self._maths_sample_ids, question_number
                )
            return self._few_shot_cache[question_number]

    def _get_english_examples(self) -> list[MarkingRow]:
        """Get calibration examples for English: one low, one mid, one high score."""
        key = "_english_examples"
        with self._cache_lock:
            if key not in self._few_shot_cache:
                pool = [
                    r for r in self.all_english
                    if r.row_id not in self._english_sample_ids
                ]
                # Pick one from each range: low (0-2), mid (3-4), high (5-6)
                low = [r for r in pool if r.human_mark <= 2.5]
                mid = [r for r in pool if 3.0 <= r.human_mark <= 4.0]
                high = [r for r in pool if r.human_mark >= 4.5]
                examples = []
                for group in [low, mid, high]:
                    if group:
                        examples.append(group[0])
                self._few_shot_cache[key] = examples
            return self._few_shot_cache[key]

    def _get_english_full_exemplars(self) -> list[MarkingRow]:
        """Get full exemplar essays at scores 2, 3, 4, 5 for calibration."""
        key = "_english_full_exemplars"
        with self._cache_lock:
            if key not in self._few_shot_cache:
                self._few_shot_cache[key] = get_english_full_exemplars(
                    self.all_english, self._english_sample_ids,
                    target_levels=[2.0, 3.0, 4.0, 5.0],
                )
            return self._few_shot_cache[key]

    def _get_comparative_anchors(self) -> tuple[MarkingRow | None, MarkingRow | None]:
        """Get score-3 and score-4 exemplar essays for comparative strategy."""
        key = "_comparative_anchors"
        with self._cache_lock:
            if key not in self._few_shot_cache:
                anchors = get_english_full_exemplars(
                    self.all_english, self._english_sample_ids,
                    target_levels=[3.0, 4.0],
                )
                anchor_3 = next((a for a in anchors if round(a.human_mark) == 3), None)
                anchor_4 = next((a for a in anchors if round(a.human_mark) == 4), None)
                self._few_shot_cache[key] = (anchor_3, anchor_4)
            return self._few_shot_cache[key]

    def run(
        self,
        strategy_names: list[str] | None = None,
        on_result: callable | None = None,
        on_strategy_start: callable | None = None,
        on_strategy_complete: callable | None = None,
    ):
        """Run all (or specified) strategies with parallel execution per strategy.

        Optional callbacks for progress tracking (used by the web API):
          on_result(result, strategy_name, completed, total)
          on_strategy_start(strategy_name, total_rows)
          on_strategy_complete(strategy_name, results_list)
        """
        strategies_to_run = self.strategies
        if strategy_names:
            strategies_to_run = [s for s in self.strategies if s.name in strategy_names]

        total_strategies = len(strategies_to_run)
        for si, strategy in enumerate(strategies_to_run, 1):
            if strategy.subject == "maths":
                sample = self.maths_sample
            elif strategy.subject == "english":
                sample = self.english_sample
            else:
                sample = self.custom_samples.get(strategy.subject, [])
            total_rows = len(sample)
            print(f"\n{'='*60}")
            print(f"[{si}/{total_strategies}] Strategy: {strategy.name}")
            print(f"  {strategy.description}")
            print(f"  Model: {strategy.model} | Temp: {strategy.temperature} | Thinking: {strategy.thinking}")
            print(f"  Rows to process: {total_rows} (parallel={config.MAX_CONCURRENT})")
            print(f"{'='*60}")

            if on_strategy_start:
                on_strategy_start(strategy.name, total_rows)

            errors = 0
            completed = 0
            start_time = time.time()
            strategy_results: list[EvalResult] = []
            results_lock = threading.Lock()

            def _process_row(row: MarkingRow) -> EvalResult:
                return self._run_single(strategy, row)

            with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT) as executor:
                futures = {
                    executor.submit(_process_row, row): row
                    for row in sample
                }

                for future in as_completed(futures):
                    result = future.result()
                    with results_lock:
                        strategy_results.append(result)
                        if result.error:
                            errors += 1
                        completed += 1

                        if on_result:
                            on_result(result, strategy.name, completed, total_rows)

                        # Progress every 10 rows or at end
                        if completed % 10 == 0 or completed == total_rows:
                            elapsed = time.time() - start_time
                            rate = completed / elapsed * 60 if elapsed > 0 else 0
                            print(
                                f"  [{completed}/{total_rows}] "
                                f"errors={errors} | "
                                f"rate={rate:.1f}/min | "
                                f"elapsed={elapsed:.0f}s"
                            )

            # Sort results by row_id to maintain deterministic order
            strategy_results.sort(key=lambda r: r.row_id)
            self.results.extend(strategy_results)

            if on_strategy_complete:
                on_strategy_complete(strategy.name, strategy_results)

            elapsed = time.time() - start_time

            # Aggregate token usage for this strategy
            strat_usage = TokenUsage()
            for r in strategy_results:
                strat_usage = strat_usage + r.usage
            cost = strat_usage.cost_usd()
            print(
                f"  Completed in {elapsed:.0f}s ({errors} errors) | "
                f"Tokens: {strat_usage.prompt_tokens:,} in / "
                f"{strat_usage.output_tokens:,} out / "
                f"{strat_usage.thinking_tokens:,} think | "
                f"Cost: ${cost:.4f}"
            )

    @staticmethod
    def _extract_usage(resp: dict) -> TokenUsage:
        """Extract token usage from an API response."""
        u = resp.pop("_usage", None)
        if u:
            return TokenUsage(
                prompt_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("output_tokens", 0),
                thinking_tokens=u.get("thinking_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
                model=u.get("model", ""),
            )
        return TokenUsage()

    def _run_single(self, strategy: Strategy, row: MarkingRow) -> EvalResult:
        """Execute one strategy on one row."""
        client = self._get_client(strategy.model, strategy.provider)
        total_usage = TokenUsage()

        try:
            # Debate strategies: multi-marker with custom orchestration
            if strategy.debate_config:
                return self._run_debate(strategy, row)

            # Build prompt - handle strategies that need extra args
            if strategy.name == "maths_few_shot":
                examples = self._get_few_shot(row.question_number)
                from .prompts.maths_prompts import few_shot_calibrated
                system, user_parts, schema = few_shot_calibrated(row, examples)
            elif strategy.name in ("english_anchor_examples", "english_halfmark_exemplar"):
                examples = self._get_english_examples()
                if strategy.name == "english_halfmark_exemplar":
                    from .prompts.english_prompts import english_halfmark_exemplar
                    system, user_parts, schema = english_halfmark_exemplar(row, examples)
                else:
                    from .prompts.english_prompts import english_anchor_examples
                    system, user_parts, schema = english_anchor_examples(row, examples)
            elif strategy.name == "english_full_exemplars":
                examples = self._get_english_full_exemplars()
                from .prompts.english_prompts import english_full_exemplars
                system, user_parts, schema = english_full_exemplars(row, examples)
            elif strategy.name.startswith("english_comparative_anchor") or strategy.name == "english_moderated":
                anchor_3, anchor_4 = self._get_comparative_anchors()
                from .prompts.english_prompts import english_comparative_anchor
                system, user_parts, schema = english_comparative_anchor(row, anchor_3, anchor_4)
            else:
                system, user_parts, schema = strategy.prompt_fn(row)

            # Handle ensemble: run N times and average
            if strategy.ensemble_runs > 1:
                marks = []
                justifications = []
                for run_idx in range(strategy.ensemble_runs):
                    resp = client.generate(
                        system_instruction=system,
                        user_parts=user_parts,
                        temperature=strategy.temperature,
                        thinking=strategy.thinking,
                        thinking_budget=strategy.thinking_budget,
                        response_schema=schema,
                        thinking_level=strategy.thinking_level,
                    )
                    total_usage = total_usage + self._extract_usage(resp)
                    p = strategy.parse_fn(resp)
                    if not p.get("error"):
                        marks.append(p.get("mark", 0))
                        justifications.append(f"Run{run_idx+1}: {p.get('mark', '?')}")
                if marks:
                    avg_mark = sum(marks) / len(marks)
                    # Round to nearest integer
                    final_mark = round(avg_mark)
                    parsed = {
                        "mark": final_mark,
                        "justification": f"Ensemble avg={avg_mark:.2f} → {final_mark}. " + "; ".join(justifications),
                    }
                else:
                    parsed = {"mark": -1, "justification": "All ensemble runs failed", "error": True}
            else:
                # Single run (normal path)
                resp = client.generate(
                    system_instruction=system,
                    user_parts=user_parts,
                    temperature=strategy.temperature,
                    thinking=strategy.thinking,
                    thinking_budget=strategy.thinking_budget,
                    response_schema=schema,
                    thinking_level=strategy.thinking_level,
                )
                total_usage = total_usage + self._extract_usage(resp)
                parsed = strategy.parse_fn(resp)

            # Second pass for two-pass strategies
            second_changed = None
            if strategy.is_two_pass and strategy.name == "english_cascade":
                # Cascade: pass 1 gives band, pass 2 gives exact score
                band_resp = parsed  # raw parsed response from pass 1
                band = str(band_resp.get("mark", "MID"))  # parse_simple puts band in "mark"
                # Actually we need the raw response — parse_simple converted it
                # Re-extract from the raw resp
                band = str(resp.get("band", "MID")).upper().strip()
                band_reasoning = str(resp.get("band_reasoning", ""))
                fewer_sources = resp.get("fewer_than_3_sources", False)

                from .prompts.english_prompts import english_cascade_pass2
                system2, user_parts2, schema2 = english_cascade_pass2(
                    row, band, band_reasoning
                )
                resp2 = client.generate(
                    system_instruction=system2,
                    user_parts=user_parts2,
                    temperature=strategy.temperature,
                    thinking=strategy.thinking,
                    thinking_budget=strategy.thinking_budget,
                    response_schema=schema2,
                    thinking_level=strategy.thinking_level,
                )
                total_usage = total_usage + self._extract_usage(resp2)
                parsed2 = parse_english_criterion(resp2)
                final_mark = parsed2.get("mark", 3)

                # Validate score within band
                band_ranges = {"LOW": (1, 2), "MID": (3, 4), "HIGH": (5, 6)}
                lo, hi = band_ranges.get(band, (1, 6))
                final_mark = max(lo, min(hi, final_mark))

                # Source cap
                if fewer_sources and final_mark > 3:
                    final_mark = 3

                # Handle blank/0 essays
                if band == "LOW" and final_mark <= 1:
                    # Check if it should be 0 (blank)
                    if row.student_answer.strip() == "" or len(row.student_answer.strip()) < 20:
                        final_mark = 0

                parsed["mark"] = final_mark
                parsed["justification"] = (
                    f"Band: {band} ({band_reasoning}) | "
                    f"Exact: {parsed2.get('justification', '')}"
                )
                second_changed = True

            elif strategy.is_two_pass and strategy.second_pass_fn:
                first_mark = parsed.get("mark", 0)
                first_just = parsed.get("justification", "")

                system2, user_parts2, schema2 = strategy.second_pass_fn(
                    row, first_mark, first_just
                )
                resp2 = client.generate(
                    system_instruction=system2,
                    user_parts=user_parts2,
                    temperature=strategy.temperature,
                    thinking=strategy.thinking,
                    thinking_budget=strategy.thinking_budget,
                    response_schema=schema2,
                    thinking_level=strategy.thinking_level,
                )
                total_usage = total_usage + self._extract_usage(resp2)
                parsed2 = parse_verify(resp2)
                second_changed = parsed2.get("changed", False)
                parsed["mark"] = parsed2.get("mark", first_mark)
                parsed["justification"] = (
                    f"Pass 1: {first_mark} - {first_just} | "
                    f"Pass 2: {parsed2.get('mark', '?')} - {parsed2.get('justification', '')}"
                )

            # Validate mark range
            mark = parsed.get("mark", -1)
            if mark < 0 or mark > row.total_marks:
                mark = max(0, min(mark, row.total_marks))

            return EvalResult(
                strategy_name=strategy.name,
                row_id=row.row_id,
                subject=row.subject,
                question_number=row.question_number,
                total_marks=row.total_marks,
                human_mark=row.human_mark,
                ai_mark=mark,
                justification=parsed.get("justification", ""),
                error=parsed.get("error", False),
                criteria_breakdown=parsed.get("criteria"),
                second_pass_changed=second_changed,
                usage=total_usage,
            )

        except Exception as e:
            return EvalResult(
                strategy_name=strategy.name,
                row_id=row.row_id,
                subject=row.subject,
                question_number=row.question_number,
                total_marks=row.total_marks,
                human_mark=row.human_mark,
                ai_mark=-1,
                justification=f"Exception: {e}",
                error=True,
                usage=total_usage,
            )

    def _build_prompt(self, strategy: Strategy, row: MarkingRow, prompt_fn=None):
        """Build prompt for a strategy, handling strategies with special args."""
        fn = prompt_fn or strategy.prompt_fn
        # Check if this prompt needs comparative anchors
        from .prompts.english_prompts import english_comparative_anchor
        if fn is english_comparative_anchor:
            anchor_3, anchor_4 = self._get_comparative_anchors()
            return fn(row, anchor_3, anchor_4)
        # Few-shot needs examples
        from .prompts.maths_prompts import few_shot_calibrated
        if fn is few_shot_calibrated:
            examples = self._get_few_shot(row.question_number)
            return fn(row, examples)
        # Full exemplars
        from .prompts.english_prompts import english_full_exemplars
        if fn is english_full_exemplars:
            examples = self._get_english_full_exemplars()
            return fn(row, examples)
        return fn(row)

    def _generate(self, strategy: Strategy, system, user_parts, schema):
        """Run a single LLM generation with the strategy's config."""
        client = self._get_client(strategy.model, strategy.provider)
        return client.generate(
            system_instruction=system,
            user_parts=user_parts,
            temperature=strategy.temperature,
            thinking=strategy.thinking,
            thinking_budget=strategy.thinking_budget,
            response_schema=schema,
            thinking_level=strategy.thinking_level,
        )

    def _run_debate(self, strategy: Strategy, row: MarkingRow) -> EvalResult:
        """Dispatch to the appropriate debate mode."""
        dc = strategy.debate_config
        if dc.mode == "panel":
            return self._run_panel(strategy, row)
        elif dc.mode == "dual_adjudicate":
            return self._run_dual_adjudicate(strategy, row)
        elif dc.mode == "multi_round":
            return self._run_multi_round(strategy, row)
        else:
            raise ValueError(f"Unknown debate mode: {dc.mode}")

    def _run_panel(self, strategy: Strategy, row: MarkingRow) -> EvalResult:
        """Run expert panel: 3 markers vote, majority/median resolution."""
        dc = strategy.debate_config
        total_usage = TokenUsage()
        marks = []
        justifications = []

        for i, (pfn, parsefn) in enumerate(
            zip(dc.panel_prompt_fns, dc.panel_parse_fns)
        ):
            system, user_parts, schema = self._build_prompt(strategy, row, pfn)
            resp = self._generate(strategy, system, user_parts, schema)
            total_usage = total_usage + self._extract_usage(resp)
            parsed = parsefn(resp)
            if parsed.get("error"):
                marks.append(-1)
                justifications.append(f"P{i+1}: error")
            else:
                m = parsed.get("mark", -1)
                marks.append(m)
                justifications.append(f"P{i+1}={m}")

        # Filter out errors
        valid = [m for m in marks if m >= 0]
        if not valid:
            return EvalResult(
                strategy_name=strategy.name, row_id=row.row_id,
                subject=row.subject, question_number=row.question_number,
                total_marks=row.total_marks, human_mark=row.human_mark,
                ai_mark=-1, justification="All panel members errored",
                error=True, usage=total_usage,
                debate_rounds=0, debate_outcome="error",
            )

        # Resolution
        if len(set(valid)) == 1:
            final_mark = valid[0]
            outcome = "unanimous"
        else:
            from collections import Counter
            counts = Counter(valid)
            most_common = counts.most_common(1)[0]
            if most_common[1] >= 2:
                final_mark = most_common[0]
                outcome = "majority"
            else:
                final_mark = sorted(valid)[len(valid) // 2]
                outcome = "median"

        final_mark = max(0, min(final_mark, row.total_marks))

        return EvalResult(
            strategy_name=strategy.name, row_id=row.row_id,
            subject=row.subject, question_number=row.question_number,
            total_marks=row.total_marks, human_mark=row.human_mark,
            ai_mark=final_mark,
            justification=f"Panel ({outcome}): {'; '.join(justifications)} -> {final_mark}",
            usage=total_usage,
            debate_rounds=0, debate_outcome=outcome,
        )

    def _run_dual_adjudicate(self, strategy: Strategy, row: MarkingRow) -> EvalResult:
        """Two independent markers + optional adjudicator if they disagree."""
        dc = strategy.debate_config
        total_usage = TokenUsage()

        # Marker A (primary prompt)
        sys_a, parts_a, schema_a = self._build_prompt(strategy, row)
        resp_a = self._generate(strategy, sys_a, parts_a, schema_a)
        total_usage = total_usage + self._extract_usage(resp_a)
        parsed_a = strategy.parse_fn(resp_a)
        mark_a = parsed_a.get("mark", -1)
        just_a = parsed_a.get("justification", "")

        # Marker B (secondary prompt)
        sys_b, parts_b, schema_b = self._build_prompt(strategy, row, dc.marker_b_prompt_fn)
        resp_b = self._generate(strategy, sys_b, parts_b, schema_b)
        total_usage = total_usage + self._extract_usage(resp_b)
        parsed_b = dc.marker_b_parse_fn(resp_b)
        mark_b = parsed_b.get("mark", -1)
        just_b = parsed_b.get("justification", "")

        # Check agreement
        if abs(mark_a - mark_b) <= dc.agreement_threshold:
            # Agree: use average (rounded)
            final_mark = round((mark_a + mark_b) / 2)
            outcome = "agreed"
            justification = f"A={mark_a} ({just_a}) | B={mark_b} ({just_b}) -> agreed={final_mark}"
        else:
            # Disagree: call adjudicator
            if dc.adjudicator_fn:
                sys_c, parts_c, schema_c = dc.adjudicator_fn(
                    row, mark_a, just_a, mark_b, just_b
                )
                resp_c = self._generate(strategy, sys_c, parts_c, schema_c)
                total_usage = total_usage + self._extract_usage(resp_c)
                parsed_c = dc.adjudicator_parse_fn(resp_c) if dc.adjudicator_parse_fn else parse_simple(resp_c)
                final_mark = parsed_c.get("mark", round((mark_a + mark_b) / 2))
                adj_reason = parsed_c.get("justification", parsed_c.get("reasoning", ""))
                outcome = "adjudicated"
                justification = (
                    f"A={mark_a} | B={mark_b} | Adj={final_mark} ({adj_reason})"
                )
            else:
                # No adjudicator: use deadlock strategy
                if dc.deadlock_strategy == "conservative":
                    final_mark = min(mark_a, mark_b)
                else:
                    final_mark = round((mark_a + mark_b) / 2)
                outcome = f"deadlock_{dc.deadlock_strategy}"
                justification = f"A={mark_a} | B={mark_b} -> {outcome}={final_mark}"

        final_mark = max(0, min(final_mark, row.total_marks))

        return EvalResult(
            strategy_name=strategy.name, row_id=row.row_id,
            subject=row.subject, question_number=row.question_number,
            total_marks=row.total_marks, human_mark=row.human_mark,
            ai_mark=final_mark, justification=justification,
            usage=total_usage,
            debate_rounds=1, debate_outcome=outcome,
        )

    def _run_multi_round(self, strategy: Strategy, row: MarkingRow) -> EvalResult:
        """Multi-round debate: two markers argue until consensus or deadlock."""
        dc = strategy.debate_config
        total_usage = TokenUsage()

        # Round 0: independent marks
        sys_a, parts_a, schema_a = self._build_prompt(strategy, row)
        resp_a = self._generate(strategy, sys_a, parts_a, schema_a)
        total_usage = total_usage + self._extract_usage(resp_a)
        parsed_a = strategy.parse_fn(resp_a)
        mark_a = parsed_a.get("mark", -1)
        just_a = parsed_a.get("justification", "")

        sys_b, parts_b, schema_b = self._build_prompt(strategy, row, dc.marker_b_prompt_fn)
        resp_b = self._generate(strategy, sys_b, parts_b, schema_b)
        total_usage = total_usage + self._extract_usage(resp_b)
        parsed_b = dc.marker_b_parse_fn(resp_b)
        mark_b = parsed_b.get("mark", -1)
        just_b = parsed_b.get("justification", "")

        history = [f"R0: A={mark_a}, B={mark_b}"]

        if mark_a == mark_b:
            return EvalResult(
                strategy_name=strategy.name, row_id=row.row_id,
                subject=row.subject, question_number=row.question_number,
                total_marks=row.total_marks, human_mark=row.human_mark,
                ai_mark=mark_a,
                justification=f"Agreed R0: A={mark_a} B={mark_b}. A: {just_a}",
                usage=total_usage,
                debate_rounds=0, debate_outcome="agreed",
            )

        # Debate rounds
        for round_num in range(1, dc.max_debate_rounds + 1):
            if not dc.rebuttal_fn:
                break

            # A sees B's mark and argues
            sys_ra, parts_ra, schema_ra = dc.rebuttal_fn(
                row, mark_a, just_a, mark_b, just_b, round_num
            )
            resp_ra = self._generate(strategy, sys_ra, parts_ra, schema_ra)
            total_usage = total_usage + self._extract_usage(resp_ra)
            reb_a = resp_ra
            mark_a = int(reb_a.get("revised_mark", mark_a))
            action_a = str(reb_a.get("action", "HOLD")).upper()
            just_a = reb_a.get("argument", just_a)

            # B sees A's rebuttal and argues
            sys_rb, parts_rb, schema_rb = dc.rebuttal_fn(
                row, mark_b, just_b, mark_a, just_a, round_num
            )
            resp_rb = self._generate(strategy, sys_rb, parts_rb, schema_rb)
            total_usage = total_usage + self._extract_usage(resp_rb)
            reb_b = resp_rb
            mark_b = int(reb_b.get("revised_mark", mark_b))
            action_b = str(reb_b.get("action", "HOLD")).upper()
            just_b = reb_b.get("argument", just_b)

            history.append(f"R{round_num}: A={mark_a}({action_a}), B={mark_b}({action_b})")

            if mark_a == mark_b:
                outcome = "conceded" if "CONCEDE" in (action_a, action_b) else "compromise"
                final_mark = max(0, min(mark_a, row.total_marks))
                return EvalResult(
                    strategy_name=strategy.name, row_id=row.row_id,
                    subject=row.subject, question_number=row.question_number,
                    total_marks=row.total_marks, human_mark=row.human_mark,
                    ai_mark=final_mark,
                    justification=f"{outcome} R{round_num}: {'; '.join(history)}",
                    usage=total_usage,
                    debate_rounds=round_num, debate_outcome=outcome,
                )

        # Deadlock: resolve
        if dc.deadlock_strategy == "conservative":
            final_mark = min(mark_a, mark_b)
        else:
            final_mark = round((mark_a + mark_b) / 2)
        final_mark = max(0, min(final_mark, row.total_marks))
        outcome = f"deadlock_{dc.deadlock_strategy}"

        return EvalResult(
            strategy_name=strategy.name, row_id=row.row_id,
            subject=row.subject, question_number=row.question_number,
            total_marks=row.total_marks, human_mark=row.human_mark,
            ai_mark=final_mark,
            justification=f"{outcome}: {'; '.join(history)} -> {final_mark}",
            usage=total_usage,
            debate_rounds=dc.max_debate_rounds, debate_outcome=outcome,
        )
