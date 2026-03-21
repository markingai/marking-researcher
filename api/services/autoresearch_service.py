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


def _make_level_matching_prompt_fn():
    """Prompt that explicitly asks the model to identify the level first, then place within it."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        system = (
            "You are a senior GCSE English Language examiner. You mark using the "
            "levels-based assessment approach:\n"
            "1. Read the full response\n"
            "2. Match the response to the best-fit level descriptor\n"
            "3. Determine whether the response sits at the top, middle, or bottom of that level\n"
            "4. Award the corresponding mark\n"
            "When borderline between levels, award the lower level. "
            "Mark only what is clearly evidenced."
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


def _make_reading_specialist_prompt_fn():
    """Optimized for reading comprehension questions (Q2-Q4)."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        system = (
            "You are a senior GCSE English Language examiner specializing in reading "
            "comprehension assessment. You evaluate student responses for:\n"
            "- Quality and specificity of textual references\n"
            "- Depth of analysis of language/structural methods\n"
            "- Understanding of writer's effects and purpose\n"
            "- Use of subject terminology\n"
            "Award marks strictly based on the level descriptors. "
            "Do not reward paraphrasing or retelling without analysis."
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


def _make_writing_specialist_prompt_fn():
    """Optimized for extended writing questions (Q5)."""
    def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
        system = (
            "You are a senior GCSE English Language examiner specializing in "
            "extended writing assessment. Evaluate against two Assessment Objectives:\n"
            "- AO5 (Content & Organisation): Ideas, perspective, structure, paragraphing, "
            "cohesion, register, vocabulary\n"
            "- AO6 (Technical Accuracy): Sentence structures, punctuation, spelling, "
            "Standard English, vocabulary range\n"
            "Mark each AO against its level descriptors. "
            "Reward ambition alongside accuracy. "
            "When borderline, award the lower level."
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


def build_recipe_strategies(model: str) -> list[tuple[str, str, Strategy]]:
    """Build all strategy variation recipes. Returns (name, description, Strategy) tuples."""

    recipes = []

    # 1. Baseline
    recipes.append((
        "baseline",
        "Simple mark scheme prompt with conservative framing",
        Strategy(
            name="ar_baseline",
            description="GCSE baseline — simple prompt",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(
                "You are a senior GCSE English Language examiner. "
                "Mark student responses strictly according to the mark scheme. "
                "Award only what is clearly evidenced. "
                "When in doubt between two levels, award the lower level."
            ),
            parse_fn=_parse_simple,
        ),
    ))

    # 2. Conservative
    recipes.append((
        "conservative",
        "Extra conservative framing — penalizes over-marking",
        Strategy(
            name="ar_conservative",
            description="GCSE conservative — strict marking",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(
                "You are a senior GCSE English Language examiner known for strict, "
                "rigorous marking. You never award marks generously. "
                "Every mark must be fully justified by clear evidence in the response. "
                "If you are uncertain whether a descriptor is met, do NOT award the marks. "
                "Err on the side of under-marking rather than over-marking.",
                "Be strict. Only award marks where evidence clearly matches descriptors. "
            ),
            parse_fn=_parse_simple,
        ),
    ))

    # 3. Criterion decomposed
    recipes.append((
        "criterion_decomposed",
        "Break mark scheme into criteria, score each independently",
        Strategy(
            name="ar_criterion",
            description="GCSE criterion decomposed — score each criterion",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_criterion_prompt_fn(
                "You are a senior GCSE English Language examiner. "
                "Decompose the mark scheme into individual criteria and assess "
                "each one independently before determining the total mark."
            ),
            parse_fn=_parse_criterion,
        ),
    ))

    # 4. Level matching
    recipes.append((
        "level_matching",
        "Explicit level identification then placement within level",
        Strategy(
            name="ar_level_match",
            description="GCSE level matching — identify level first",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_level_matching_prompt_fn(),
            parse_fn=_parse_simple,
        ),
    ))

    # 5. Reading specialist
    recipes.append((
        "reading_specialist",
        "Prompt optimized for reading questions (Q2-Q4)",
        Strategy(
            name="ar_reading",
            description="GCSE reading specialist — textual analysis focus",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_reading_specialist_prompt_fn(),
            parse_fn=_parse_simple,
        ),
    ))

    # 6. Writing specialist
    recipes.append((
        "writing_specialist",
        "Prompt optimized for writing questions (Q5)",
        Strategy(
            name="ar_writing",
            description="GCSE writing specialist — AO5/AO6 focus",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_writing_specialist_prompt_fn(),
            parse_fn=_parse_simple,
        ),
    ))

    # 7. Higher thinking budget
    recipes.append((
        "high_thinking",
        "Baseline with 2x thinking budget (8192 tokens)",
        Strategy(
            name="ar_high_think",
            description="GCSE baseline with extended thinking",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=8192,
            prompt_fn=_make_prompt_fn(
                "You are a senior GCSE English Language examiner. "
                "Mark student responses strictly according to the mark scheme. "
                "Take your time to think carefully. "
                "Award only what is clearly evidenced. "
                "When in doubt between two levels, award the lower level."
            ),
            parse_fn=_parse_simple,
        ),
    ))

    # 8. Flash model (cheap, fast)
    recipes.append((
        "flash_model",
        "Gemini 2.5 Flash — 8x cheaper, test quality tradeoff",
        Strategy(
            name="ar_flash",
            description="GCSE baseline on Flash model",
            subject="english",
            model=eval_config.MODEL_FLASH,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(
                "You are a senior GCSE English Language examiner. "
                "Mark student responses strictly according to the mark scheme. "
                "Award only what is clearly evidenced. "
                "When in doubt between two levels, award the lower level."
            ),
            parse_fn=_parse_simple,
        ),
    ))

    # 9. Detailed instructions
    recipes.append((
        "detailed_instructions",
        "Verbose prompt with step-by-step marking instructions",
        Strategy(
            name="ar_detailed",
            description="GCSE detailed step-by-step instructions",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_prompt_fn(
                "You are a senior GCSE English Language examiner with 15 years of "
                "experience. Follow this exact marking procedure:\n\n"
                "1. Read the entire student response carefully\n"
                "2. Re-read the mark scheme level descriptors from highest to lowest\n"
                "3. Identify which level best describes the student's work\n"
                "4. Within that level, determine if the response is at the top, "
                "middle, or bottom\n"
                "5. Award the corresponding mark\n\n"
                "Key principles:\n"
                "- Best fit: match to the level that most closely describes the work\n"
                "- Borderline: when between levels, award the lower level\n"
                "- Evidence: only credit what is actually present in the response\n"
                "- Consistency: apply the same standard to every response",
            ),
            parse_fn=_parse_simple,
        ),
    ))

    # 10. Criterion + conservative combo
    recipes.append((
        "criterion_conservative",
        "Criterion decomposition with conservative framing",
        Strategy(
            name="ar_crit_conservative",
            description="GCSE criterion + conservative combo",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=eval_config.THINKING_BUDGET,
            prompt_fn=_make_criterion_prompt_fn(
                "You are a senior GCSE English Language examiner known for strict, "
                "rigorous marking. Decompose the mark scheme into criteria. "
                "For each criterion, only award marks where clear evidence exists. "
                "When in doubt, award the lower mark. "
                "Be particularly careful not to over-mark."
            ),
            parse_fn=_parse_criterion,
        ),
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
    ):
        ctx = SessionContext(session_id=session_id)
        with self._lock:
            self._active[session_id] = ctx

        thread = threading.Thread(
            target=self._execute_session,
            args=(ctx, budget_usd, sample_size, model),
            daemon=True,
        )
        thread.start()

    def stop_session(self, session_id: str):
        ctx = self._active.get(session_id)
        if ctx:
            ctx.cancelled = True

    def _execute_session(
        self,
        ctx: SessionContext,
        budget_usd: float,
        sample_size: int,
        model: str,
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

            # Build all recipe strategies
            recipes = build_recipe_strategies(model)

            total_spent = 0.0
            best_exact = 0.0
            best_exp_id = None

            for recipe_name, recipe_desc, strategy in recipes:
                if ctx.cancelled:
                    break
                if total_spent >= budget_usd:
                    break

                exp_id = str(uuid.uuid4())
                now = datetime.now(timezone.utc).isoformat()

                # Push experiment_start event
                ctx.push_event("experiment_start", {
                    "experiment_id": exp_id,
                    "description": recipe_desc,
                    "strategy_name": strategy.name,
                })

                # Run evaluation
                runner = EvalRunner(
                    strategies=[strategy],
                    maths_sample=[],
                    english_sample=eval_rows,
                    all_maths=[],
                    all_english=train_rows,
                )

                runner.run()

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

                # Determine if kept (improved over best)
                kept = metrics.exact_match > best_exact or (
                    metrics.exact_match == best_exact and best_exp_id is None
                )
                if kept:
                    best_exact = metrics.exact_match
                    best_exp_id = exp_id

                per_q_data = {
                    qn: {"n": m.n, "exact_match": m.exact_match, "mae": m.mae}
                    for qn, m in per_q.items()
                }

                # Save experiment to DB
                with database.get_db() as db:
                    db.execute(
                        """INSERT INTO autoresearch_experiments
                        (id, session_id, description, strategy_name, exact_match,
                         within_1, mae, bias, cost_usd, n, model, kept,
                         per_question_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (exp_id, ctx.session_id, recipe_desc, strategy.name,
                         metrics.exact_match, metrics.within_1, metrics.mae,
                         metrics.mean_signed_error, cost, metrics.n,
                         strategy.model, int(kept), json.dumps(per_q_data), now),
                    )
                    db.execute(
                        """UPDATE autoresearch_sessions
                        SET spent_usd=?, experiments_run=experiments_run+1,
                            best_exact_match=?, best_experiment_id=?
                        WHERE id=?""",
                        (total_spent, best_exact, best_exp_id, ctx.session_id),
                    )

                # Push experiment_complete event
                ctx.push_event("experiment_complete", {
                    "experiment_id": exp_id,
                    "description": recipe_desc,
                    "strategy_name": strategy.name,
                    "exact_match": round(metrics.exact_match, 1),
                    "within_1": round(metrics.within_1, 1),
                    "mae": round(metrics.mae, 3),
                    "bias": round(metrics.mean_signed_error, 3),
                    "cost_usd": round(cost, 4),
                    "n": metrics.n,
                    "kept": kept,
                    "per_question": per_q_data,
                    "spent_so_far": round(total_spent, 4),
                    "budget_usd": budget_usd,
                })

            # Mark session complete
            status = "stopped" if ctx.cancelled else "completed"
            now_done = datetime.now(timezone.utc).isoformat()
            with database.get_db() as db:
                db.execute(
                    "UPDATE autoresearch_sessions SET status=?, completed_at=? WHERE id=?",
                    (status, now_done, ctx.session_id),
                )

            ctx.push_event("session_complete", {
                "session_id": ctx.session_id,
                "status": status,
                "total_spent": round(total_spent, 4),
                "experiments_run": len([r for r in recipes if total_spent <= budget_usd]),
                "best_exact_match": round(best_exact, 1),
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
