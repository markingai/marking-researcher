"""Results service — metrics computation and historical data loading."""

from __future__ import annotations

import json
from collections import defaultdict

from ..database import get_db
from ..models import MetricSetResponse


def get_run_results_summary(run_id: str) -> dict:
    """Get aggregated strategy metrics for a run."""
    with get_db() as db:
        results = db.execute(
            "SELECT * FROM eval_results WHERE run_id=?", (run_id,)
        ).fetchall()

    if not results:
        return {"strategies": [], "total_evaluated": 0, "total_errors": 0, "total_cost_usd": 0}

    by_strategy: dict[str, list] = defaultdict(list)
    for r in results:
        by_strategy[r["strategy_name"]].append(r)

    strategies = []
    total_cost = 0.0
    total_errors = 0

    for strategy_name, rows in sorted(by_strategy.items()):
        metrics = _compute_metrics_from_rows(rows)
        cost = sum(r["cost_usd"] for r in rows)
        total_cost += cost
        total_errors += metrics["errors"]

        strategies.append({
            "name": strategy_name,
            "metrics": metrics,
            "cost_usd": round(cost, 4),
        })

    # Find best strategy by exact match
    best = max(strategies, key=lambda s: s["metrics"]["exact_match_pct"]) if strategies else None

    return {
        "strategies": strategies,
        "total_evaluated": len(results),
        "total_errors": total_errors,
        "total_cost_usd": round(total_cost, 4),
        "best_strategy": best["name"] if best else None,
    }


def get_run_results_detail(
    run_id: str,
    strategy: str | None = None,
    question: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """Get detailed per-answer results for a run."""
    with get_db() as db:
        where = "WHERE run_id=?"
        params: list = [run_id]

        if strategy:
            where += " AND strategy_name=?"
            params.append(strategy)
        if question:
            where += " AND question_number=?"
            params.append(question)

        total = db.execute(
            f"SELECT COUNT(*) FROM eval_results {where}", params
        ).fetchone()[0]

        rows = db.execute(
            f"""SELECT * FROM eval_results {where}
                ORDER BY strategy_name, question_number, row_id
                LIMIT ? OFFSET ?""",
            params + [per_page, (page - 1) * per_page],
        ).fetchall()

        # Get all results for confusion matrix + per-question metrics (without pagination)
        all_rows = db.execute(
            f"SELECT * FROM eval_results {where}",
            params,
        ).fetchall()

    # Build confusion matrix
    confusion: dict[tuple, int] = defaultdict(int)
    for r in all_rows:
        if r["ai_mark"] >= 0:
            confusion[(r["human_mark"], r["ai_mark"])] += 1

    # Per-question metrics
    by_q: dict[str, list] = defaultdict(list)
    for r in all_rows:
        by_q[r["question_number"]].append(r)

    return {
        "results": [
            {
                "row_id": r["row_id"],
                "question_number": r["question_number"],
                "total_marks": r["total_marks"],
                "human_mark": r["human_mark"],
                "ai_mark": r["ai_mark"],
                "signed_error": r["ai_mark"] - r["human_mark"],
                "exact_match": r["ai_mark"] == r["human_mark"],
                "justification": r["justification"],
                "criteria_breakdown": r["criteria_breakdown"],
                "cost_usd": r["cost_usd"],
            }
            for r in rows
        ],
        "total": total,
        "confusion_matrix": [
            {"human_mark": hm, "ai_mark": am, "count": c}
            for (hm, am), c in sorted(confusion.items())
        ],
        "per_question_metrics": [
            {"question_number": qn, "metrics": _compute_metrics_from_rows(qrows)}
            for qn, qrows in sorted(by_q.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 0)
        ],
    }


def _compute_metrics_from_rows(rows: list) -> dict:
    """Compute MetricSet from DB rows."""
    valid = [r for r in rows if not r["error"] and r["ai_mark"] >= 0]
    n = len(valid)
    if n == 0:
        return MetricSetResponse(
            n=0, exact_match_pct=0, exact_match_rounded_pct=0,
            within_half_pct=0, within_1_pct=0, mae=0,
            mean_signed_error=0, over_mark_pct=0, under_mark_pct=0,
            errors=len(rows),
        ).model_dump()

    exact = sum(1 for r in valid if r["ai_mark"] == r["human_mark"])
    exact_rounded = sum(1 for r in valid if r["ai_mark"] == round(r["human_mark"]))
    within_half = sum(1 for r in valid if abs(r["ai_mark"] - r["human_mark"]) <= 0.5)
    within_1 = sum(1 for r in valid if abs(r["ai_mark"] - r["human_mark"]) <= 1)

    errors_list = [r["ai_mark"] - r["human_mark"] for r in valid]
    over = sum(1 for e in errors_list if e > 0)
    under = sum(1 for e in errors_list if e < 0)

    return MetricSetResponse(
        n=n,
        exact_match_pct=round(exact / n * 100, 1),
        exact_match_rounded_pct=round(exact_rounded / n * 100, 1),
        within_half_pct=round(within_half / n * 100, 1),
        within_1_pct=round(within_1 / n * 100, 1),
        mae=round(sum(abs(e) for e in errors_list) / n, 3),
        mean_signed_error=round(sum(errors_list) / n, 3),
        over_mark_pct=round(over / n * 100, 1),
        under_mark_pct=round(under / n * 100, 1),
        errors=len(rows) - n,
    ).model_dump()
