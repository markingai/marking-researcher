"""Background eval run manager with progress tracking."""

from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from eval_agent import config as eval_config
from eval_agent.data_loader import load_maths, load_english, stratified_sample, MarkingRow
from eval_agent.strategies import build_strategies, build_generic_strategies, Strategy
from eval_agent.runner import EvalRunner, EvalResult, TokenUsage
from eval_agent.metrics import compute_metrics

from .. import database


@dataclass
class RunContext:
    run_id: str
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


class RunManager:
    def __init__(self):
        self._active: dict[str, RunContext] = {}
        self._lock = threading.Lock()

    @property
    def is_busy(self) -> bool:
        with self._lock:
            return any(
                ctx for ctx in self._active.values()
                if not ctx.cancelled
            )

    def get_context(self, run_id: str) -> RunContext | None:
        return self._active.get(run_id)

    def start_run(
        self,
        run_id: str,
        subject: str,
        input_mode: str,
        strategy_names: list[str],
        questions: list[str] | None,
        sample_size: int,
        random_seed: int,
        model_override: str | None = None,
    ):
        ctx = RunContext(run_id=run_id)
        with self._lock:
            self._active[run_id] = ctx

        thread = threading.Thread(
            target=self._execute_run,
            args=(ctx, subject, input_mode, strategy_names, questions,
                  sample_size, random_seed, model_override),
            daemon=True,
        )
        thread.start()

    def cancel_run(self, run_id: str):
        ctx = self._active.get(run_id)
        if ctx:
            ctx.cancelled = True

    def _execute_run(
        self,
        ctx: RunContext,
        subject: str,
        input_mode: str,
        strategy_names: list[str],
        questions: list[str] | None,
        sample_size: int,
        random_seed: int,
        model_override: str | None,
    ):
        now = datetime.now(timezone.utc).isoformat()

        try:
            with database.get_db() as db:
                db.execute(
                    "UPDATE runs SET status='running', started_at=? WHERE id=?",
                    (now, ctx.run_id),
                )

            # Load data
            custom_samples: dict[str, list[MarkingRow]] = {}

            if input_mode == "pdf":
                from eval_agent.pdf_data_loader import load_pdf_maths
                from pathlib import Path
                pdf_dir = eval_config.PROJECT_ROOT / "Maths"
                all_maths = load_pdf_maths(pdf_dir, questions=set(questions) if questions else None)
                all_english = []
            elif subject in ("maths", "english", "all"):
                all_maths = load_maths() if subject in ("maths", "all") else []
                all_english = load_english() if subject in ("english", "all") else []
            else:
                # Custom subject
                all_maths = []
                all_english = []
                from .dataset_service import get_custom_subject_data
                custom_data = get_custom_subject_data(subject) or []
                if questions and custom_data:
                    custom_data = [r for r in custom_data if r.question_number in questions]
                custom_samples[subject] = custom_data

            # Filter by questions if specified
            if questions and all_maths:
                all_maths = [r for r in all_maths if r.question_number in questions]
            if questions and all_english:
                all_english = [r for r in all_english if r.question_number in questions]

            # Sample
            eval_config.RANDOM_SEED = random_seed
            maths_sample = stratified_sample(all_maths, sample_size) if all_maths else []
            english_sample = stratified_sample(all_english, sample_size) if all_english else []
            for slug in custom_samples:
                if custom_samples[slug]:
                    custom_samples[slug] = stratified_sample(custom_samples[slug], sample_size)

            # Build strategies
            all_strategies = build_strategies()
            # Add generic strategies for custom subjects
            if subject not in ("maths", "english", "all"):
                from .dataset_service import get_custom_subjects
                for subj in get_custom_subjects():
                    if subj["slug"] == subject:
                        all_strategies.extend(
                            build_generic_strategies(subj["slug"], subj["display_name"])
                        )
                        break

            # Filter to selected strategies
            strategies = [s for s in all_strategies if s.name in strategy_names]
            if subject != "all":
                strategies = [s for s in strategies if s.subject == subject]

            # Apply model override
            if model_override:
                for s in strategies:
                    s.model = model_override

            def _sample_len(subj_name: str) -> int:
                if subj_name == "maths":
                    return len(maths_sample)
                elif subj_name == "english":
                    return len(english_sample)
                else:
                    return len(custom_samples.get(subj_name, []))

            total_rows = sum(_sample_len(s.subject) for s in strategies)

            with database.get_db() as db:
                db.execute(
                    "UPDATE runs SET total_strategies=?, total_rows=? WHERE id=?",
                    (len(strategies), total_rows, ctx.run_id),
                )
                for s in strategies:
                    rows = _sample_len(s.subject)
                    db.execute(
                        "UPDATE run_strategies SET rows_total=? WHERE run_id=? AND strategy_name=?",
                        (rows, ctx.run_id, s.name),
                    )

            # Create runner
            runner = EvalRunner(
                strategies=strategies,
                maths_sample=maths_sample,
                english_sample=english_sample,
                custom_samples=custom_samples,
                all_maths=all_maths,
                all_english=all_english,
            )

            # Run with callbacks
            completed_overall = 0

            def on_result(result: EvalResult, strategy_name: str, completed: int, total: int):
                nonlocal completed_overall
                if ctx.cancelled:
                    return

                completed_overall += 1

                # Store result
                now_r = datetime.now(timezone.utc).isoformat()
                with database.get_db() as db:
                    db.execute(
                        """INSERT INTO eval_results
                        (run_id, strategy_name, row_id, subject, question_number,
                         total_marks, human_mark, ai_mark, error, justification,
                         criteria_breakdown, prompt_tokens, output_tokens,
                         thinking_tokens, cost_usd, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (ctx.run_id, strategy_name, result.row_id, result.subject,
                         result.question_number, result.total_marks, result.human_mark,
                         result.ai_mark, int(result.error), result.justification,
                         json.dumps(result.criteria_breakdown) if result.criteria_breakdown else None,
                         result.usage.prompt_tokens, result.usage.output_tokens,
                         result.usage.thinking_tokens, result.usage.cost_usd(),
                         now_r),
                    )
                    db.execute(
                        """UPDATE run_strategies SET rows_completed=?,
                           errors=errors+?, cost_usd=cost_usd+?
                           WHERE run_id=? AND strategy_name=?""",
                        (completed, int(result.error), result.usage.cost_usd(),
                         ctx.run_id, strategy_name),
                    )
                    db.execute(
                        "UPDATE runs SET completed_rows=?, total_cost_usd=total_cost_usd+? WHERE id=?",
                        (completed_overall, result.usage.cost_usd(), ctx.run_id),
                    )

                # Push SSE event
                ctx.push_event("progress", {
                    "strategy": strategy_name,
                    "completed": completed,
                    "total": total,
                    "completed_overall": completed_overall,
                    "total_overall": total_rows,
                    "error": result.error,
                })

            def on_strategy_start(strategy_name: str, total: int):
                if ctx.cancelled:
                    return

                now_s = datetime.now(timezone.utc).isoformat()
                with database.get_db() as db:
                    db.execute(
                        "UPDATE run_strategies SET status='running', started_at=? WHERE run_id=? AND strategy_name=?",
                        (now_s, ctx.run_id, strategy_name),
                    )
                ctx.push_event("strategy_start", {
                    "strategy": strategy_name,
                    "total_rows": total,
                })

            def on_strategy_complete(strategy_name: str, results: list[EvalResult]):
                if ctx.cancelled:
                    return

                now_c = datetime.now(timezone.utc).isoformat()
                metrics = compute_metrics(results)
                with database.get_db() as db:
                    db.execute(
                        """UPDATE run_strategies SET status='completed', completed_at=?
                           WHERE run_id=? AND strategy_name=?""",
                        (now_c, ctx.run_id, strategy_name),
                    )
                    db.execute(
                        "UPDATE runs SET completed_strategies=completed_strategies+1 WHERE id=?",
                        (ctx.run_id,),
                    )

                ctx.push_event("strategy_complete", {
                    "strategy": strategy_name,
                    "metrics": {
                        "n": metrics.n,
                        "exact_match_pct": round(metrics.exact_match, 1),
                        "within_1_pct": round(metrics.within_1, 1),
                        "mae": round(metrics.mae, 3),
                        "mean_signed_error": round(metrics.mean_signed_error, 3),
                    },
                })

            # Execute
            runner.run(
                strategy_names=strategy_names,
                on_result=on_result,
                on_strategy_start=on_strategy_start,
                on_strategy_complete=on_strategy_complete,
            )

            # Mark completed
            now_done = datetime.now(timezone.utc).isoformat()
            status = "cancelled" if ctx.cancelled else "completed"
            with database.get_db() as db:
                db.execute(
                    "UPDATE runs SET status=?, completed_at=? WHERE id=?",
                    (status, now_done, ctx.run_id),
                )

            ctx.push_event("run_complete", {
                "run_id": ctx.run_id,
                "status": status,
            })

        except Exception as e:
            now_err = datetime.now(timezone.utc).isoformat()
            with database.get_db() as db:
                db.execute(
                    "UPDATE runs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                    (str(e), now_err, ctx.run_id),
                )
            ctx.push_event("error", {"message": str(e)})

        finally:
            with self._lock:
                self._active.pop(ctx.run_id, None)


# Singleton
run_manager = RunManager()
