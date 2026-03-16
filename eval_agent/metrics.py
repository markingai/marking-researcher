"""Metric calculations for eval results."""

from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass

from .runner import EvalResult


@dataclass
class MetricSet:
    n: int = 0
    exact_match: float = 0.0
    exact_match_rounded: float = 0.0  # round(human) == ai
    within_half: float = 0.0
    within_1: float = 0.0
    mae: float = 0.0
    mse: float = 0.0
    mean_signed_error: float = 0.0  # positive = over-marking
    over_mark_pct: float = 0.0
    under_mark_pct: float = 0.0
    exact_match_count: int = 0
    errors: int = 0


def compute_metrics(results: list[EvalResult]) -> MetricSet:
    """Compute all metrics for a list of results."""
    valid = [r for r in results if not r.error and r.ai_mark >= 0]
    n = len(valid)
    if n == 0:
        m = MetricSet(n=0, errors=len(results))
        return m

    exact = sum(1 for r in valid if r.ai_mark == r.human_mark)
    exact_rounded = sum(1 for r in valid if r.ai_mark == round(r.human_mark))
    within_half = sum(1 for r in valid if abs(r.ai_mark - r.human_mark) <= 0.5)
    within_1 = sum(1 for r in valid if abs(r.ai_mark - r.human_mark) <= 1)

    errors_list = [r.ai_mark - r.human_mark for r in valid]
    abs_errors = [abs(e) for e in errors_list]
    sq_errors = [e * e for e in errors_list]

    over = sum(1 for e in errors_list if e > 0)
    under = sum(1 for e in errors_list if e < 0)

    return MetricSet(
        n=n,
        exact_match=exact / n * 100,
        exact_match_rounded=exact_rounded / n * 100,
        within_half=within_half / n * 100,
        within_1=within_1 / n * 100,
        mae=sum(abs_errors) / n,
        mse=sum(sq_errors) / n,
        mean_signed_error=sum(errors_list) / n,
        over_mark_pct=over / n * 100,
        under_mark_pct=under / n * 100,
        exact_match_count=exact,
        errors=len(results) - n,
    )


def compute_grouped_metrics(
    results: list[EvalResult],
    group_by: str = "strategy_name",
) -> dict[str, MetricSet]:
    """Compute metrics grouped by a field."""
    groups: dict[str, list[EvalResult]] = defaultdict(list)
    for r in results:
        key = getattr(r, group_by)
        groups[key].append(r)

    return {key: compute_metrics(group) for key, group in sorted(groups.items())}


def compute_confusion_matrix(
    results: list[EvalResult],
) -> dict[tuple[float, float], int]:
    """Build confusion matrix: {(human_mark, ai_mark): count}."""
    matrix: dict[tuple[float, float], int] = defaultdict(int)
    for r in results:
        if not r.error and r.ai_mark >= 0:
            matrix[(r.human_mark, r.ai_mark)] += 1
    return dict(matrix)


def compute_per_question_metrics(
    results: list[EvalResult],
    strategy_name: str,
) -> dict[str, MetricSet]:
    """Metrics broken down by question number for a specific strategy."""
    filtered = [r for r in results if r.strategy_name == strategy_name]
    return compute_grouped_metrics(filtered, group_by="question_number")
