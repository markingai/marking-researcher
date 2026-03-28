"""Autoresearch session manager — runs strategy variation experiments."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections import defaultdict

from eval_agent import config as eval_config
from eval_agent.data_loader import load_exampro, MarkingRow, stratified_sample
from eval_agent.strategies import Strategy
from eval_agent.runner import EvalRunner, EvalResult, TokenUsage
from eval_agent.metrics import compute_metrics, compute_per_question_metrics

from .. import database


def _row_get(row, key, default=None):
    """Safely get a column from a sqlite3.Row (which lacks .get())."""
    try:
        if key in row.keys():
            val = row[key]
            return val if val is not None else default
    except (AttributeError, IndexError):
        pass
    return default


# ---------------------------------------------------------------------------
# Strategy recipes — each returns a (name, description, Strategy) tuple
# ---------------------------------------------------------------------------

def _parse_simple(resp: dict) -> dict:
    if "error" in resp and "mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}
    return {"mark": int(resp.get("mark", -1)), "justification": resp.get("justification", "")}


def _parse_criterion(resp: dict) -> dict:
    if "error" in resp and "total_mark" not in resp:
        return {"mark": -1, "justification": resp.get("error", ""), "error": True}
    criteria = resp.get("criteria", [])
    total = int(resp.get("total_mark", -1))
    breakdown = "; ".join(
        f"{c.get('criterion', '?')}: {c.get('marks_awarded', '?')}/{c.get('max_marks', '?')}"
        for c in criteria
    )
    return {"mark": total, "justification": breakdown}


SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}

CRITERION_SCHEMA = {
    "type": "object",
    "required": ["criteria", "total_mark"],
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["criterion", "marks_awarded", "max_marks", "reason"],
                "properties": {
                    "criterion": {"type": "string"},
                    "marks_awarded": {"type": "integer"},
                    "max_marks": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            },
        },
        "total_mark": {"type": "integer"},
    },
}


def _make_prompt_fn(system_text: str, extra_instructions: str = ""):
    """Factory for prompt functions with different system instructions."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        user_parts = [f"## Mark Scheme\n\n{row.marking_guide}"]
        if row.source_text:
            user_parts.append(f"## Source Text\n\n{row.source_text}")
        user_parts.append(f"## Question\n\n{row.question_text}")
        user_parts.append(f"## Student Response\n\n{row.student_answer}")
        instruction = (
            f"Mark this response out of {row.total_marks} using the mark scheme above. "
            f"{extra_instructions}"
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) and "
            "'justification' (concise explanation referencing mark scheme descriptors)."
        )
        user_parts.append(instruction)
        return system_text, user_parts, SIMPLE_SCHEMA
    return prompt_fn


def _make_criterion_prompt_fn(system_text: str):
    """Factory for criterion-decomposed prompt functions."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        user_parts = [f"## Mark Scheme\n\n{row.marking_guide}"]
        if row.source_text:
            user_parts.append(f"## Source Text\n\n{row.source_text}")
        user_parts.append(f"## Question\n\n{row.question_text}")
        user_parts.append(f"## Student Response\n\n{row.student_answer}")
        user_parts.append(
            f"Evaluate this response out of {row.total_marks}. "
            "First, identify each criterion/level descriptor in the mark scheme. "
            "Then assess the student against each criterion separately. "
            "Finally, determine the total mark based on your criterion assessments. "
            "Return JSON with 'criteria' array and 'total_mark'."
        )
        return system_text, user_parts, CRITERION_SCHEMA
    return prompt_fn


def _make_level_matching_prompt_fn(bias_instruction: str = ""):
    """Prompt that explicitly asks the model to identify the level first, then place within it."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        system = (
            "You are an expert examiner. You mark using the "
            "levels-based assessment approach:\n"
            "1. Read the full response\n"
            "2. Match the response to the best-fit level descriptor\n"
            "3. Determine whether the response sits at the top, middle, or bottom of that level\n"
            "4. Award the corresponding mark\n"
            f"Mark only what is clearly evidenced. {bias_instruction}"
        )
        user_parts = [f"## Mark Scheme\n\n{row.marking_guide}"]
        if row.source_text:
            user_parts.append(f"## Source Text\n\n{row.source_text}")
        user_parts.append(f"## Question\n\n{row.question_text}")
        user_parts.append(f"## Student Response\n\n{row.student_answer}")
        user_parts.append(
            f"Mark this response out of {row.total_marks}. "
            "First state which level the response best matches and why. "
            "Then state where within that level (top/middle/bottom). "
            "Return JSON with 'mark' (integer 0 to " + str(row.total_marks) + ") and "
            "'justification' (include level identification and placement reasoning)."
        )
        return system, user_parts, SIMPLE_SCHEMA
    return prompt_fn


def _make_reading_specialist_prompt_fn(bias_instruction: str = ""):
    """Optimized for questions where students analyse source material."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        system = (
            "You are an expert examiner specializing in analytical assessment. "
            "You evaluate student responses for:\n"
            "- Quality and specificity of references to the source material\n"
            "- Depth of analysis and interpretation\n"
            "- Understanding of techniques and their effects\n"
            "- Use of appropriate subject terminology\n"
            "Award marks strictly based on the level descriptors in the mark scheme. "
            f"Do not reward paraphrasing or retelling without analysis. {bias_instruction}"
        )
        user_parts = [f"## Mark Scheme\n\n{row.marking_guide}"]
        if row.source_text:
            user_parts.append(f"## Source Text\n\n{row.source_text}")
        user_parts.append(f"## Question\n\n{row.question_text}")
        user_parts.append(f"## Student Response\n\n{row.student_answer}")
        user_parts.append(
            f"Mark this reading response out of {row.total_marks}. "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) and "
            "'justification' referencing specific level descriptors matched."
        )
        return system, user_parts, SIMPLE_SCHEMA
    return prompt_fn


def _make_writing_specialist_prompt_fn(bias_instruction: str = ""):
    """Optimized for extended writing / high-mark questions."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        system = (
            "You are an expert examiner specializing in extended writing assessment. "
            "If the mark scheme has multiple assessment objectives or criteria, "
            "evaluate against each one separately using their level descriptors. "
            "Reward ambition alongside accuracy. "
            f"Mark only what is clearly evidenced. {bias_instruction}"
        )
        user_parts = [f"## Mark Scheme\n\n{row.marking_guide}"]
        user_parts.append(f"## Question\n\n{row.question_text}")
        user_parts.append(f"## Student Response\n\n{row.student_answer}")
        user_parts.append(
            f"Mark this writing response out of {row.total_marks}. "
            "Consider both AO5 and AO6 against the mark scheme. "
            f"Return JSON with 'mark' (integer 0 to {row.total_marks}) and "
            "'justification' (reference both AO5 and AO6 level descriptors)."
        )
        return system, user_parts, SIMPLE_SCHEMA
    return prompt_fn


BIAS_INSTRUCTIONS = {
    "conservative": "When in doubt, award the lower mark. It is better to under-mark slightly than over-mark.",
    "neutral": "Award marks fairly based on the evidence. Neither inflate nor deflate.",
    "generous": "Give the student the benefit of the doubt. If their response could reasonably merit the higher mark, award it.",
}


def build_recipe_strategies(model: str, bias_mode: str = "neutral") -> list[tuple[str, str, Strategy, str, dict]]:
    """Build all strategy variation recipes.

    Returns (name, description, Strategy, system_prompt_text, config_dict) tuples.
    """
    bias = BIAS_INSTRUCTIONS.get(bias_mode, BIAS_INSTRUCTIONS["neutral"])

    recipes = []

    # 1. Baseline
    _sys_baseline = (
        "You are an expert examiner. "
        "Mark student responses strictly according to the mark scheme provided. "
        f"Award only what is clearly evidenced. {bias}"
    )
    recipes.append((
        "baseline",
        "Simple mark scheme prompt with baseline framing",
        Strategy(
            name="ar_baseline",
            description="Baseline — simple prompt",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(_sys_baseline),
            parse_fn=_parse_simple,
        ),
        _sys_baseline,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET},
    ))

    # 2. Conservative
    _sys_conservative = (
        "You are an expert examiner known for strict, rigorous marking. "
        "Every mark must be fully justified by clear evidence in the response. "
        "If you are uncertain whether a descriptor is met, do NOT award the marks. "
        "Err on the side of under-marking rather than over-marking."
    )
    recipes.append((
        "conservative",
        "Extra conservative framing — penalizes over-marking",
        Strategy(
            name="ar_conservative",
            description="Conservative — strict marking",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(
                _sys_conservative,
                "Be strict. Only award marks where evidence clearly matches descriptors. "
            ),
            parse_fn=_parse_simple,
        ),
        _sys_conservative,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET, "extra": "penalize over-marking"},
    ))

    # 3. Criterion decomposed
    _sys_criterion = (
        "You are an expert examiner. "
        "Decompose the mark scheme into individual criteria and assess "
        f"each one independently before determining the total mark. {bias}"
    )
    recipes.append((
        "criterion_decomposed",
        "Break mark scheme into criteria, score each independently",
        Strategy(
            name="ar_criterion",
            description="Criterion decomposed — score each criterion",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_criterion_prompt_fn(_sys_criterion),
            parse_fn=_parse_criterion,
        ),
        _sys_criterion,
        {"schema": "criterion", "thinking_budget": eval_config.THINKING_BUDGET},
    ))

    # 4. Level matching
    _sys_level_match = (
        "You are an expert examiner. You mark using the "
        "levels-based assessment approach:\n"
        "1. Read the full response\n"
        "2. Match the response to the best-fit level descriptor\n"
        "3. Determine whether the response sits at the top, middle, or bottom of that level\n"
        "4. Award the corresponding mark\n"
        f"Mark only what is clearly evidenced. {bias}"
    )
    recipes.append((
        "level_matching",
        "Explicit level identification then placement within level",
        Strategy(
            name="ar_level_match",
            description="Level matching — identify level first",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_level_matching_prompt_fn(),
            parse_fn=_parse_simple,
        ),
        _sys_level_match,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET},
    ))

    # 5. Reading / analytical specialist
    _sys_reading = (
        "You are an expert examiner specializing in analytical assessment. "
        "You evaluate student responses for:\n"
        "- Quality and specificity of references to the source material\n"
        "- Depth of analysis and interpretation\n"
        "- Understanding of techniques and their effects\n"
        "- Use of appropriate subject terminology\n"
        "Award marks strictly based on the level descriptors in the mark scheme. "
        f"Do not reward paraphrasing or retelling without analysis. {bias}"
    )
    recipes.append((
        "reading_specialist",
        "Prompt optimized for analytical / source-based questions",
        Strategy(
            name="ar_reading",
            description="Analytical specialist — source-based assessment",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_reading_specialist_prompt_fn(),
            parse_fn=_parse_simple,
        ),
        _sys_reading,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET, "focus": "reading Q2-Q4"},
    ))

    # 6. Writing / extended response specialist
    _sys_writing = (
        "You are an expert examiner specializing in extended writing assessment. "
        "If the mark scheme has multiple assessment objectives or criteria, "
        "evaluate against each one separately using their level descriptors. "
        f"Reward ambition alongside accuracy. {bias}"
    )
    recipes.append((
        "writing_specialist",
        "Prompt optimized for extended writing / high-mark questions",
        Strategy(
            name="ar_writing",
            description="Extended writing specialist — multi-criteria",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_writing_specialist_prompt_fn(),
            parse_fn=_parse_simple,
        ),
        _sys_writing,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET, "focus": "writing Q5"},
    ))

    # 7. Higher thinking budget
    _sys_high_think = (
        "You are an expert examiner. "
        "Mark student responses strictly according to the mark scheme provided. "
        "Take your time to think carefully. "
        f"Award only what is clearly evidenced. {bias}"
    )
    recipes.append((
        "high_thinking",
        "Baseline with 2x thinking budget (8192 tokens)",
        Strategy(
            name="ar_high_think",
            description="Baseline with extended thinking",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=8192,
            prompt_fn=_make_prompt_fn(_sys_high_think),
            parse_fn=_parse_simple,
        ),
        _sys_high_think,
        {"schema": "simple", "thinking_budget": 8192},
    ))

    # 8. Flash model (cheap, fast)
    _sys_flash = _sys_baseline  # same prompt, different model
    recipes.append((
        "flash_model",
        "Gemini 2.5 Flash — 8x cheaper, test quality tradeoff",
        Strategy(
            name="ar_flash",
            description="Baseline on Flash model",
            subject="english",
            model=eval_config.MODEL_FLASH,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(_sys_flash),
            parse_fn=_parse_simple,
        ),
        _sys_flash,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET, "model_override": eval_config.MODEL_FLASH},
    ))

    # 9. Detailed instructions
    _sys_detailed = (
        "You are an expert examiner. Follow this exact marking procedure:\n\n"
        "1. Read the entire student response carefully\n"
        "2. Re-read the mark scheme level descriptors from highest to lowest\n"
        "3. Identify which level best describes the student's work\n"
        "4. Within that level, determine if the response is at the top, "
        "middle, or bottom\n"
        "5. Award the corresponding mark\n\n"
        "Key principles:\n"
        "- Best fit: match to the level that most closely describes the work\n"
        f"- Evidence: only credit what is actually present in the response\n"
        f"- Consistency: apply the same standard to every response\n"
        f"- {bias}"
    )
    recipes.append((
        "detailed_instructions",
        "Verbose prompt with step-by-step marking instructions",
        Strategy(
            name="ar_detailed",
            description="Detailed step-by-step instructions",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(_sys_detailed),
            parse_fn=_parse_simple,
        ),
        _sys_detailed,
        {"schema": "simple", "thinking_budget": eval_config.THINKING_BUDGET},
    ))

    # 10. Criterion + conservative combo
    _sys_crit_conservative = (
        "You are an expert examiner known for strict, rigorous marking. "
        "Decompose the mark scheme into criteria. "
        "For each criterion, only award marks where clear evidence exists. "
        "When in doubt, award the lower mark. "
        "Be particularly careful not to over-mark."
    )
    recipes.append((
        "criterion_conservative",
        "Criterion decomposition with conservative framing",
        Strategy(
            name="ar_crit_conservative",
            description="Criterion + conservative combo",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_criterion_prompt_fn(_sys_crit_conservative),
            parse_fn=_parse_criterion,
        ),
        _sys_crit_conservative,
        {"schema": "criterion", "thinking_budget": eval_config.THINKING_BUDGET},
    ))

    return recipes


# ---------------------------------------------------------------------------
# Data splitting (reuse from harness)
# ---------------------------------------------------------------------------

import random

SPLIT_SEED = 99

def _create_splits(rows: list[MarkingRow]) -> tuple[list[MarkingRow], list[MarkingRow], list[MarkingRow]]:
    rng = random.Random(SPLIT_SEED)
    groups: dict[str, list[MarkingRow]] = defaultdict(list)
    for row in rows:
        groups[row.question_number].append(row)

    train, dev, test = [], [], []
    for qn in sorted(groups.keys()):
        pool = groups[qn]
        rng.shuffle(pool)
        n = len(pool)
        n_train = int(n * 0.60)
        n_dev = int(n * 0.20)
        train.extend(pool[:n_train])
        dev.extend(pool[n_train:n_train + n_dev])
        test.extend(pool[n_train + n_dev:])

    return train, dev, test


# ---------------------------------------------------------------------------
# Session context (same pattern as RunContext)
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    session_id: str
    event_queues: list[asyncio.Queue] = field(default_factory=list)
    cancelled: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def add_queue(self) -> asyncio.Queue:
        q = asyncio.Queue()
        with self._lock:
            self.event_queues.append(q)
        return q

    def remove_queue(self, q: asyncio.Queue):
        with self._lock:
            if q in self.event_queues:
                self.event_queues.remove(q)

    def push_event(self, event_type: str, data: dict):
        with self._lock:
            for q in self.event_queues:
                try:
                    q.put_nowait({"event": event_type, "data": data})
                except asyncio.QueueFull:
                    pass


# ---------------------------------------------------------------------------
# Session manager
# ---------------------------------------------------------------------------

class AutoresearchManager:
    def __init__(self):
        self._active: dict[str, SessionContext] = {}
        self._lock = threading.Lock()

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return any(ctx for ctx in self._active.values() if not ctx.cancelled)

    def get_context(self, session_id: str) -> SessionContext | None:
        return self._active.get(session_id)

    def start_session(
        self,
        session_id: str,
        budget_usd: float,
        sample_size: int,
        model: str,
        bias_mode: str = "neutral",
    ):
        ctx = SessionContext(session_id=session_id)
        with self._lock:
            self._active[session_id] = ctx

        thread = threading.Thread(
            target=self._execute_session,
            args=(ctx, budget_usd, sample_size, model, bias_mode),
            daemon=True,
        )
        thread.start()

    def stop_session(self, session_id: str):
        ctx = self._active.get(session_id)
        if ctx:
            ctx.cancelled = True

    def _generate_report(self, session_id: str) -> str:
        """Generate an LLM-written research report, with template fallback."""
        # Gather data
        with database.get_db() as db:
            session = db.execute(
                "SELECT * FROM autoresearch_sessions WHERE id=?", (session_id,)
            ).fetchone()
            exps = db.execute(
                "SELECT * FROM autoresearch_experiments WHERE session_id=? ORDER BY created_at",
                (session_id,),
            ).fetchall()

        if not exps:
            return "No experiments completed."

        # Sort by composite score (within_10_pct primary, exact_match secondary)
        ranked = sorted(
            exps,
            key=lambda e: (_row_get(e, "within_10_pct", 0), e["exact_match"] or 0),
            reverse=True,
        )
        best = ranked[0]

        # Generate next-session recommendations (always template-based)
        recs = self._generate_recommendations(session_id)

        # Try LLM report first, fall back to template
        try:
            llm_report = self._generate_llm_report(session, exps, ranked, best, recs)
            if llm_report and len(llm_report) > 200:
                return llm_report
        except Exception as e:
            print(f"LLM report generation failed: {e}")

        return self._generate_template_report(session, exps, ranked, best, recs)

    def _generate_llm_report(self, session, exps, ranked, best, recs) -> str:
        """Use Gemini to write a proper research report from experiment data."""
        from eval_agent.gemini_client import GeminiClient

        # Build structured context for the LLM
        context_parts = []
        context_parts.append("# Autoresearch Session Data\n")
        context_parts.append(f"Date: {session['created_at'][:10]}")
        context_parts.append(f"Model: {session['model']}")
        context_parts.append(f"Sample size: {session['sample_size']} rows (stratified by question)")
        context_parts.append(f"Total cost: ${session['spent_usd']:.2f}")
        context_parts.append(f"Experiments run: {session['experiments_run']}")
        sn = session['session_number'] if 'session_number' in session.keys() else None
        if sn and sn > 1:
            context_parts.append(f"Session number: {sn} (learning from {sn - 1} prior session(s))")
        context_parts.append("")

        context_parts.append("## Experiment Results (ranked by within-10% score)\n")
        for i, e in enumerate(ranked, 1):
            w10_val = _row_get(e, "within_10_pct")
            w10 = f"{w10_val:.1f}%" if w10_val is not None else "N/A"
            context_parts.append(
                f"{i}. **{e['description']}** (`{e['strategy_name']}`)\n"
                f"   Within 10%: {w10} | Exact: {e['exact_match']:.1f}% | "
                f"Within 1: {e['within_1']:.1f}% | MAE: {e['mae']:.2f} | "
                f"Bias: {e['bias']:+.2f} | Cost: ${e['cost_usd']:.2f}"
            )
            # Add prompt summary (first 200 chars)
            prompt_text = _row_get(e, "prompt_text")
            if prompt_text:
                prompt_preview = prompt_text[:300].replace("\n", " ")
                context_parts.append(f"   Prompt approach: {prompt_preview}...")
        context_parts.append("")

        # Per-question data for top 3 strategies
        context_parts.append("## Per-Question Breakdown (Top 3 Strategies)\n")
        for e in ranked[:3]:
            if _row_get(e, "per_question_json"):
                per_q = json.loads(e["per_question_json"])
                context_parts.append(f"### {e['description']} (`{e['strategy_name']}`)")
                for qn in sorted(per_q.keys()):
                    m = per_q[qn]
                    w10 = f"{m.get('within_10_pct', 0):.0f}%" if m.get("within_10_pct") is not None else "N/A"
                    context_parts.append(
                        f"  {qn}: W/10%={w10}, Exact={m['exact_match']:.0f}%, "
                        f"W/1={m.get('within_1', 0):.0f}%, MAE={m['mae']:.2f}, n={m['n']}"
                    )
                context_parts.append("")

        # Prior sessions context
        with database.get_db() as db:
            prior_best = db.execute(
                "SELECT strategy_name, MAX(exact_match) as best_exact, "
                "MAX(within_10_pct) as best_w10 "
                "FROM autoresearch_experiments WHERE session_id != ? AND exact_match IS NOT NULL "
                "GROUP BY strategy_name ORDER BY MAX(within_10_pct) DESC LIMIT 5",
                (session['id'],),
            ).fetchall()
        if prior_best:
            context_parts.append("## Prior Session Best Strategies (for context)\n")
            for p in prior_best:
                w10 = f"{p['best_w10']:.1f}%" if p['best_w10'] else "N/A"
                context_parts.append(f"- {p['strategy_name']}: W/10%={w10}, Exact={p['best_exact']:.1f}%")
            context_parts.append("")

        context_str = "\n".join(context_parts)

        system_prompt = """You are a research analyst writing a report on AI marking strategy experiments.

Write a structured Markdown research report. Be specific with numbers, reference strategy names, and explain WHY certain approaches worked or didn't based on what the strategy does.

Use ONLY these Markdown elements (the renderer only supports these):
- # for main title, ## for section headers (no ### or deeper)
- **bold** for emphasis
- Bullet lists with -
- Numbered lists with 1. 2. 3.
- Tables with | header | ... | format
- `backtick` for code/strategy names

Required sections:
1. **# Research Report** — title
2. **## Executive Summary** — 2-3 sentences: what was tested, key finding, top recommendation
3. **## Methodology** — model, sample size, how strategies were selected, budget, any learning from prior sessions
4. **## Results & Analysis** — NARRATIVE PARAGRAPHS (not just tables). Compare strategies, explain why some worked better. Include a comparison table but surround it with analysis. Discuss the within-10% metric as the primary success measure.
5. **## Per-Question Analysis** — Which questions are easy/hard for AI and why. Narrative + table.
6. **## Cost-Effectiveness** — Cost per percentage point improvement. Which strategies give best value.
7. **## Statistical Considerations** — Sample size limitations. Whether differences between top strategies are meaningful or could be noise.
8. **## Recommendations** — Top 3 actionable next steps with rationale. Be specific about what to try next and why.

Keep the report concise but insightful — aim for 600-1000 words of actual analysis."""

        client = GeminiClient(
            api_key=eval_config.GEMINI_API_KEY,
            model=session['model'],
        )
        resp = client.generate(
            system_instruction=system_prompt,
            user_parts=[context_str],
            temperature=0.3,
            thinking=True,
            thinking_budget=4096,
        )

        # Extract text — no response_schema so it comes back as raw text or parsed
        if "error" in resp and "raw" not in resp:
            raise ValueError(f"LLM report failed: {resp.get('error')}")

        report_text = resp.get("raw", "") or resp.get("text", "")
        if not report_text:
            # Try to extract from any text-like field
            for key in resp:
                if key.startswith("_"):
                    continue
                val = resp[key]
                if isinstance(val, str) and len(val) > 100:
                    report_text = val
                    break

        if not report_text:
            raise ValueError("Empty LLM response")

        # Append template-based next-session recommendations
        if recs:
            report_text += "\n\n## Recommendations for Next Session\n\n"
            report_text += "These recommendations will be automatically used by the next research session.\n\n"
            report_text += "| Priority | Type | Strategy | Rationale |\n"
            report_text += "|----------|------|----------|----------|\n"
            for rec in recs[:10]:
                report_text += (
                    f"| {rec['priority']} | {rec['type']} | "
                    f"`{rec['strategy_name']}` | {rec['description']} |\n"
                )

        return report_text

    def _generate_template_report(self, session, exps, ranked, best, recs) -> str:
        """Fallback template-based report generation."""
        baseline = next((e for e in exps if e["strategy_name"] == "ar_baseline"), None)

        lines = []
        lines.append("# Autoresearch Session Report\n")
        lines.append(f"**Date:** {session['created_at'][:10]}  ")
        lines.append(f"**Model:** {session['model']}  ")
        lines.append(f"**Sample size:** {session['sample_size']} rows  ")
        lines.append(f"**Total cost:** ${session['spent_usd']:.2f}  ")
        lines.append(f"**Experiments run:** {session['experiments_run']}\n")

        # Winner
        lines.append("## Best Strategy\n")
        lines.append(f"**{best['description']}** (`{best['strategy_name']}`)\n")
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        best_w10 = _row_get(best, "within_10_pct")
        w10 = f"{best_w10:.1f}%" if best_w10 is not None else "N/A"
        lines.append(f"| Within 10% | {w10} |")
        lines.append(f"| Exact Match | {best['exact_match']:.1f}% |")
        lines.append(f"| Within 1 Mark | {best['within_1']:.1f}% |")
        lines.append(f"| MAE | {best['mae']:.2f} |")
        lines.append(f"| Bias | {best['bias']:+.2f} |")
        lines.append(f"| Cost | ${best['cost_usd']:.2f} |\n")

        # Comparison table (no Kept/Discarded — just ranking)
        lines.append("## Strategy Comparison\n")
        lines.append("| Rank | Strategy | W/10% | Exact % | W/in 1 % | MAE | Bias | Cost |")
        lines.append("|------|----------|-------|---------|----------|-----|------|------|")
        for i, e in enumerate(ranked, 1):
            e_w10 = _row_get(e, "within_10_pct")
            w10 = f"{e_w10:.1f}%" if e_w10 is not None else "N/A"
            lines.append(
                f"| {i} | {e['description']} | {w10} | {e['exact_match']:.1f}% | "
                f"{e['within_1']:.1f}% | {e['mae']:.2f} | {e['bias']:+.2f} | "
                f"${e['cost_usd']:.2f} |"
            )
        lines.append("")

        # Key findings
        lines.append("## Key Findings\n")

        if baseline:
            bl_exact = baseline["exact_match"] or 0
            beat_baseline = [e for e in exps if (e["exact_match"] or 0) > bl_exact and e["id"] != baseline["id"]]
            if beat_baseline:
                names = ", ".join(e["description"] for e in beat_baseline)
                lines.append(f"- **{len(beat_baseline)} strategies beat the baseline** ({bl_exact:.1f}%): {names}")
            else:
                lines.append(f"- **No strategy beat the baseline** ({bl_exact:.1f}%) — the simple prompt performed best")

        high_think = next((e for e in exps if e["strategy_name"] == "ar_high_think"), None)
        if high_think and baseline:
            diff = (high_think["exact_match"] or 0) - (baseline["exact_match"] or 0)
            direction = "improved" if diff > 0 else "decreased" if diff < 0 else "unchanged"
            lines.append(f"- **Extended thinking (8192 tokens):** {direction} exact match by {abs(diff):.1f}pp vs baseline")

        flash = next((e for e in exps if e["strategy_name"] == "ar_flash"), None)
        if flash and baseline:
            diff = (flash["exact_match"] or 0) - (baseline["exact_match"] or 0)
            cost_ratio = (baseline["cost_usd"] / flash["cost_usd"]) if flash["cost_usd"] > 0 else 0
            lines.append(f"- **Flash model:** {diff:+.1f}pp exact match vs Pro, {cost_ratio:.1f}x cheaper")

        criterion = next((e for e in exps if e["strategy_name"] == "ar_criterion"), None)
        if criterion and baseline:
            diff = (criterion["exact_match"] or 0) - (baseline["exact_match"] or 0)
            lines.append(f"- **Criterion decomposition:** {diff:+.1f}pp exact match vs simple prompt")

        lines.append("")

        # Per-question analysis
        if best["per_question_json"]:
            per_q = json.loads(best["per_question_json"])
            lines.append("## Per-Question Analysis (Best Strategy)\n")
            lines.append("| Question | W/10% | Exact % | W/in 1 % | MAE | n |")
            lines.append("|----------|-------|---------|----------|-----|---|")
            for qn in sorted(per_q.keys()):
                m = per_q[qn]
                w10 = f"{m.get('within_10_pct', 0):.0f}%" if m.get("within_10_pct") is not None else "N/A"
                w1 = f"{m.get('within_1', 0):.0f}%" if m.get("within_1") is not None else "N/A"
                lines.append(f"| {qn} | {w10} | {m['exact_match']:.0f}% | {w1} | {m['mae']:.2f} | {m['n']} |")

            weakest = min(per_q.items(), key=lambda x: x[1]["exact_match"])
            strongest = max(per_q.items(), key=lambda x: x[1]["exact_match"])
            lines.append(f"\n- **Strongest:** {strongest[0]} ({strongest[1]['exact_match']:.0f}% exact)")
            lines.append(f"- **Weakest:** {weakest[0]} ({weakest[1]['exact_match']:.0f}% exact)")
            lines.append("")

        # Recommendations
        lines.append("## Recommendations\n")
        lines.append(f"1. **Deploy `{best['strategy_name']}`** as the production marking strategy")
        if best["bias"] and abs(best["bias"]) > 0.3:
            direction = "over-marking" if best["bias"] > 0 else "under-marking"
            lines.append(f"2. **Address {direction} bias** ({best['bias']:+.2f}) — consider adjusting prompt framing")
        if best["per_question_json"]:
            per_q = json.loads(best["per_question_json"])
            weak_qs = [qn for qn, m in per_q.items() if m["exact_match"] < 20]
            if weak_qs:
                lines.append(f"3. **Investigate weak questions** ({', '.join(weak_qs)}) — may benefit from question-specific prompts")
        lines.append(f"4. **Run validation** on the held-out test set ({session['sample_size']} rows) to confirm results generalize")

        if recs:
            lines.append("\n## Recommendations for Next Session\n")
            lines.append("These recommendations will be automatically used by the next research session.\n")
            lines.append("| Priority | Type | Strategy | Rationale |")
            lines.append("|----------|------|----------|-----------|")
            for rec in recs[:10]:
                lines.append(
                    f"| {rec['priority']} | {rec['type']} | "
                    f"`{rec['strategy_name']}` | {rec['description']} |"
                )

        return "\n".join(lines)

    def _generate_recommendations(self, session_id: str) -> list[dict]:
        """Generate concrete recommendations for the next session and save to DB."""
        with database.get_db() as db:
            # All experiments ever run
            all_exps = db.execute(
                "SELECT strategy_name, exact_match, bias, per_question_json, config_json "
                "FROM autoresearch_experiments WHERE exact_match IS NOT NULL"
            ).fetchall()

            # This session's experiments
            session_exps = db.execute(
                "SELECT strategy_name, exact_match, within_1, bias, per_question_json, config_json "
                "FROM autoresearch_experiments WHERE session_id=? AND exact_match IS NOT NULL "
                "ORDER BY exact_match DESC",
                (session_id,),
            ).fetchall()

        if not session_exps:
            return []

        all_tested_names = {e["strategy_name"] for e in all_exps}
        best = session_exps[0]
        recs = []
        now = datetime.now(timezone.utc).isoformat()

        # Known strategies from codebase
        CODEBASE_STRATEGIES = {
            "english_scorecard": "Signal extraction removes LLM scoring bias — deterministic scoring",
            "english_cascade": "Two-pass band→exact constrains scoring range",
            "english_comparative_anchor": "Relative judgment vs exemplars reduces absolute scoring drift",
            "english_forced_independence": "Anti-criterion-collapse guards improve scoring diversity",
            "english_full_exemplars": "Full calibration essays anchor model expectations",
            "english_level_descriptors": "Explicit rubric-level matching per criterion",
            "english_halfmark_criterion": "Half-mark granularity for finer differentiation",
            "english_moderated": "Two-pass with independent moderator reduces errors",
            "english_panel": "3-marker voting reduces individual marker variance",
            "english_dual_adjudicate": "Dual marking with adjudicator on disagreement",
            "english_debate": "Multi-round debate converges on consensus mark",
            "english_strict_range": "Score distribution calibration prevents range compression",
        }

        # 1. Untested strategies from codebase
        for name, rationale in CODEBASE_STRATEGIES.items():
            if name not in all_tested_names:
                recs.append({
                    "type": "untested",
                    "strategy_name": name,
                    "description": rationale,
                    "priority": 20,
                    "config_json": json.dumps({"source": "codebase"}),
                })

        # 2. Variations of top performers
        for exp in session_exps[:3]:
            config = {}
            if exp["config_json"]:
                try:
                    config = json.loads(exp["config_json"])
                except (json.JSONDecodeError, TypeError):
                    pass

            tb = config.get("thinking_budget", 4096)
            name = exp["strategy_name"]

            # Higher thinking budget
            high_think_name = f"{name}_high_think"
            if tb < 8192 and high_think_name not in all_tested_names:
                recs.append({
                    "type": "variation",
                    "strategy_name": high_think_name,
                    "description": f"Run {name} with 8192 thinking budget (was {tb})",
                    "priority": 30,
                    "config_json": json.dumps({"parent": name, "thinking_budget": 8192}),
                })

            # Gemini 3.1 variant
            g31_name = f"{name}_g31"
            if g31_name not in all_tested_names:
                recs.append({
                    "type": "variation",
                    "strategy_name": g31_name,
                    "description": f"Run {name} on Gemini 3.1 Pro",
                    "priority": 35,
                    "config_json": json.dumps({"parent": name, "model": "gemini-3.1-pro-preview"}),
                })

        # 3. Bias correction
        if best["bias"] is not None and abs(best["bias"]) > 0.3:
            direction = "over-marks" if best["bias"] > 0 else "under-marks"
            bc_name = f"{best['strategy_name']}_bias_corrected"
            if bc_name not in all_tested_names:
                recs.append({
                    "type": "hybrid",
                    "strategy_name": bc_name,
                    "description": f"Best strategy {direction} by {abs(best['bias']):.2f} — add bias correction",
                    "priority": 25,
                    "config_json": json.dumps({"parent": best["strategy_name"], "bias": best["bias"]}),
                })

        # 4. Hybrid combinations
        hybrids = [
            ("cascade_conservative", "Cascade band classification + conservative exact scoring"),
            ("criterion_forced_independence", "Criterion decomposition with anti-collapse guards"),
            ("level_match_high_think", "Level matching with extended thinking (8192)"),
            ("flash_ensemble_3x", "3x Flash ensemble for reduced variance"),
        ]
        for h_name, h_desc in hybrids:
            if h_name not in all_tested_names:
                recs.append({
                    "type": "hybrid",
                    "strategy_name": h_name,
                    "description": h_desc,
                    "priority": 40,
                    "config_json": json.dumps({"hybrid": True}),
                })

        # 5. Question-specific analysis
        if best["per_question_json"]:
            try:
                per_q = json.loads(best["per_question_json"])
                weak_qs = [qn for qn, m in per_q.items() if m["exact_match"] < 15]
                if weak_qs:
                    recs.append({
                        "type": "novel",
                        "strategy_name": "question_router",
                        "description": f"Route weak questions ({', '.join(weak_qs)}) to specialist prompts",
                        "priority": 35,
                        "config_json": json.dumps({"weak_questions": weak_qs}),
                    })
            except (json.JSONDecodeError, TypeError):
                pass

        # Save to DB
        with database.get_db() as db:
            for rec in recs:
                rec_id = str(uuid.uuid4())
                db.execute(
                    """INSERT INTO autoresearch_recommendations
                    (id, source_session_id, recommendation_type, strategy_name,
                     description, config_json, priority, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (rec_id, session_id, rec["type"], rec["strategy_name"],
                     rec["description"], rec["config_json"], rec["priority"], now),
                )

        return recs

    def _execute_session(
        self,
        ctx: SessionContext,
        budget_usd: float,
        sample_size: int,
        model: str,
        bias_mode: str = "neutral",
    ):
        try:
            # Load and split data
            all_rows = load_exampro()
            train_rows, dev_rows, _ = _create_splits(all_rows)

            # Sample dev set
            if sample_size < len(dev_rows):
                eval_rows = stratified_sample(dev_rows, sample_size, seed=SPLIT_SEED + 1)
            else:
                eval_rows = dev_rows

            # Build recipes — adaptive if prior data exists, else fixed
            from .autoresearch_recipe_engine import build_adaptive_recipes
            with database.get_db() as db:
                recipes = build_adaptive_recipes(model, sample_size, budget_usd, db, bias_mode=bias_mode)
            if not recipes:
                recipes = build_recipe_strategies(model, bias_mode=bias_mode)

            total_spent = 0.0
            best_exact = 0.0
            best_w10 = 0.0
            best_w1 = 0.0
            best_exp_id = None
            best_score = (0.0, 0.0, 0.0)  # (within_10_pct, exact_match, within_1)

            for recipe_idx, (recipe_name, recipe_desc, strategy, sys_prompt, config_dict) in enumerate(recipes):
                if ctx.cancelled:
                    break

                # Budget guard: estimate upcoming cost and skip if over budget
                if recipe_idx > 0 and total_spent > 0:
                    avg_cost_per_exp = total_spent / recipe_idx
                    estimated_cost = avg_cost_per_exp * 1.5  # 1.5x buffer
                elif recipe_idx == 0:
                    estimated_cost = budget_usd / max(len(recipes), 1)
                else:
                    estimated_cost = 0

                if total_spent + estimated_cost > budget_usd * 1.1:  # 10% grace
                    ctx.push_event("experiment_skipped", {
                        "description": recipe_desc,
                        "reason": f"Budget limit reached (${total_spent:.2f} / ${budget_usd:.2f})",
                    })
                    continue

                exp_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()
                total_rows = len(eval_rows)

                # Push experiment_start event
                ctx.push_event("experiment_start", {
                    "experiment_id": exp_id,
                    "description": recipe_desc,
                    "strategy_name": strategy.name,
                    "rows_total": total_rows,
                })

                # Progress callback for per-row updates
                _progress_count = [0]
                def _on_result(result, strategy_name, completed, total):
                    _progress_count[0] = completed
                    # Emit progress every 5 rows or at completion
                    if completed % 5 == 0 or completed == total:
                        ctx.push_event("experiment_progress", {
                            "experiment_id": exp_id,
                            "rows_completed": completed,
                            "rows_total": total,
                        })

                # Run evaluation
                runner = EvalRunner(
                    strategies=[strategy],
                    maths_sample=[],
                    english_sample=eval_rows,
                    all_maths=[],
                    all_english=train_rows,
                )

                runner.run(on_result=_on_result)

                if ctx.cancelled:
                    break

                # Compute metrics
                metrics = compute_metrics(runner.results)
                per_q = compute_per_question_metrics(runner.results, strategy.name)

                # Compute cost
                total_usage = TokenUsage()
                for r in runner.results:
                    total_usage = total_usage + r.usage
                cost = total_usage.cost_usd()
                total_spent += cost

                # Determine best by composite score (within_10_pct > exact > within_1)
                score = (metrics.within_10_pct, metrics.exact_match, metrics.within_1)
                kept = True  # All experiments are kept — ranking replaces keep/discard
                if score > best_score or best_exp_id is None:
                    best_score = score
                    best_exact = metrics.exact_match
                    best_exp_id = exp_id
                best_w10 = max(best_w10, metrics.within_10_pct)
                best_w1 = max(best_w1, metrics.within_1)

                # Build question characteristics lookup from sample rows
                from .autoresearch_recipe_engine import extract_question_characteristics
                q_chars: dict[str, dict] = {}
                for row in eval_rows:
                    if row.question_number not in q_chars:
                        q_chars[row.question_number] = extract_question_characteristics(
                            row.marking_guide,
                            row.total_marks,
                            getattr(row, "mark_type", None),
                            bool(row.source_text),
                        )

                per_q_data = {
                    qn: {
                        "n": m.n,
                        "exact_match": m.exact_match,
                        "within_10_pct": m.within_10_pct,
                        "within_1": m.within_1,
                        "mae": m.mae,
                        "bias": m.mean_signed_error,
                        **q_chars.get(qn, {}),
                    }
                    for qn, m in per_q.items()
                }

                config_dict_full = {
                    "model": strategy.model,
                    "temperature": strategy.temperature,
                    "thinking_budget": strategy.thinking_budget,
                    **config_dict,
                }

                # Save experiment to DB
                with database.get_db() as db:
                    db.execute(
                        """INSERT INTO autoresearch_experiments
                        (id, session_id, description, strategy_name, exact_match,
                         within_10_pct, within_1, mae, bias, cost_usd, n, model, kept,
                         per_question_json, prompt_text, config_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (exp_id, ctx.session_id, recipe_desc, strategy.name,
                         metrics.exact_match, metrics.within_10_pct,
                         metrics.within_1, metrics.mae,
                         metrics.mean_signed_error, cost, metrics.n,
                         strategy.model, 1, json.dumps(per_q_data),
                         sys_prompt, json.dumps(config_dict_full), now),
                    )
                    db.execute(
                        """UPDATE autoresearch_sessions
                        SET spent_usd=?, experiments_run=experiments_run+1,
                            best_exact_match=?, best_within_10_pct=?, best_within_1=?,
                            best_experiment_id=?
                        WHERE id=?""",
                        (total_spent, best_exact, best_w10, best_w1, best_exp_id, ctx.session_id),
                    )

                # Push experiment_complete event
                ctx.push_event("experiment_complete", {
                    "experiment_id": exp_id,
                    "description": recipe_desc,
                    "strategy_name": strategy.name,
                    "exact_match": round(metrics.exact_match, 1),
                    "within_10_pct": round(metrics.within_10_pct, 1),
                    "within_1": round(metrics.within_1, 1),
                    "mae": round(metrics.mae, 3),
                    "bias": round(metrics.mean_signed_error, 3),
                    "cost_usd": round(cost, 4),
                    "n": metrics.n,
                    "kept": True,
                    "per_question": per_q_data,
                    "prompt_text": sys_prompt,
                    "config_json": json.dumps(config_dict_full),
                    "spent_so_far": round(total_spent, 4),
                    "budget_usd": budget_usd,
                })

            # Mark consumed recommendations (if this session used adaptive recipes)
            with database.get_db() as db:
                db.execute(
                    """UPDATE autoresearch_recommendations
                    SET consumed_by_session_id=?
                    WHERE consumed_by_session_id IS NULL""",
                    (ctx.session_id,),
                )

            # Generate report (includes recommendation generation)
            status = "stopped" if ctx.cancelled else "completed"
            report_md = self._generate_report(ctx.session_id)

            now_done = datetime.now(timezone.utc).isoformat()
            with database.get_db() as db:
                db.execute(
                    "UPDATE autoresearch_sessions SET status=?, completed_at=?, report_md=? WHERE id=?",
                    (status, now_done, report_md, ctx.session_id),
                )

            ctx.push_event("session_complete", {
                "session_id": ctx.session_id,
                "status": status,
                "total_spent": round(total_spent, 4),
                "experiments_run": len([r for r in recipes if total_spent <= budget_usd]),
                "best_exact_match": round(best_exact, 1),
                "report_md": report_md,
            })

        except Exception as e:
            now_err = datetime.now(timezone.utc).isoformat()
            with database.get_db() as db:
                db.execute(
                    "UPDATE autoresearch_sessions SET status='failed', completed_at=? WHERE id=?",
                    (now_err, ctx.session_id),
                )
            ctx.push_event("error", {"message": str(e)})

        finally:
            with self._lock:
                self._active.pop(ctx.session_id, None)


# Singleton
autoresearch_manager = AutoresearchManager()
