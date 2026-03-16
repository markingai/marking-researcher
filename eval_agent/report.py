"""Report generation - console tables and CSV export."""

from __future__ import annotations
import csv
import os
from datetime import datetime
from pathlib import Path

from . import config
from .runner import EvalResult
from .metrics import (
    MetricSet,
    compute_metrics,
    compute_grouped_metrics,
    compute_confusion_matrix,
    compute_per_question_metrics,
)


def _fmt_pct(val: float) -> str:
    return f"{val:.1f}%"


def _fmt_f(val: float, decimals: int = 2) -> str:
    return f"{val:+.{decimals}f}" if val != 0 else f"{val:.{decimals}f}"


def _pad(s: str, width: int) -> str:
    return s.ljust(width)


def print_strategy_table(
    title: str,
    results: list[EvalResult],
    subject: str,
):
    """Print a formatted comparison table for all strategies in a subject."""
    filtered = [r for r in results if r.subject == subject]
    if not filtered:
        print(f"\n  No results for {subject}.")
        return

    by_strategy = compute_grouped_metrics(filtered, "strategy_name")

    print(f"\n{'='*90}")
    print(f"  {title}")
    print(f"{'='*90}")

    # Header
    cols = ["Strategy", "N", "Exact%", "ExRnd%", "W/in1%", "MAE", "Bias", "Over%", "Under%", "Errs"]
    widths = [28, 4, 7, 7, 7, 6, 7, 7, 7, 4]
    header = "  ".join(_pad(c, w) for c, w in zip(cols, widths))
    print(f"  {header}")
    print(f"  {'-' * len(header)}")

    for name, m in by_strategy.items():
        row = [
            _pad(name, widths[0]),
            _pad(str(m.n), widths[1]),
            _pad(_fmt_pct(m.exact_match), widths[2]),
            _pad(_fmt_pct(m.exact_match_rounded), widths[3]),
            _pad(_fmt_pct(m.within_1), widths[4]),
            _pad(f"{m.mae:.2f}", widths[5]),
            _pad(_fmt_f(m.mean_signed_error), widths[6]),
            _pad(_fmt_pct(m.over_mark_pct), widths[7]),
            _pad(_fmt_pct(m.under_mark_pct), widths[8]),
            _pad(str(m.errors), widths[9]),
        ]
        print(f"  {'  '.join(row)}")


def print_question_breakdown(
    results: list[EvalResult],
    strategy_name: str,
):
    """Print per-question metrics for a strategy."""
    per_q = compute_per_question_metrics(results, strategy_name)
    if not per_q:
        return

    print(f"\n  Per-Question Breakdown ({strategy_name}):")
    cols = ["Q#", "Max", "N", "Exact%", "MAE", "Bias"]
    widths = [6, 4, 4, 7, 6, 7]
    header = "  ".join(_pad(c, w) for c, w in zip(cols, widths))
    print(f"  {header}")
    print(f"  {'-' * len(header)}")

    # Sort question numbers numerically
    for qn in sorted(per_q.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        m = per_q[qn]
        # Get total_marks from first result with this question
        total = 0
        for r in results:
            if r.strategy_name == strategy_name and r.question_number == qn:
                total = r.total_marks
                break
        row = [
            _pad(f"q{qn}", widths[0]),
            _pad(str(total), widths[1]),
            _pad(str(m.n), widths[2]),
            _pad(_fmt_pct(m.exact_match), widths[3]),
            _pad(f"{m.mae:.2f}", widths[4]),
            _pad(_fmt_f(m.mean_signed_error), widths[5]),
        ]
        print(f"  {'  '.join(row)}")


def print_confusion_matrix(
    results: list[EvalResult],
    strategy_name: str,
    max_mark: int = 6,
):
    """Print confusion matrix for a strategy."""
    filtered = [r for r in results if r.strategy_name == strategy_name]
    if not filtered:
        return

    matrix = compute_confusion_matrix(filtered)
    actual_marks = sorted(set(k[0] for k in matrix.keys()))
    predicted_marks = sorted(set(k[1] for k in matrix.keys()))

    print(f"\n  Confusion Matrix ({strategy_name}):")
    # Header row - handle both int and float predicted marks
    has_halves = any(p != int(p) for p in predicted_marks)
    if has_halves:
        header = "  H\\AI  " + "".join(f" {p:>4.1f}" for p in predicted_marks)
    else:
        header = "  H\\AI  " + "".join(f"  {int(p):>2}" for p in predicted_marks)
    print(f"  {header}")
    print(f"  {'-' * len(header)}")

    for h in actual_marks:
        row_str = f"  {h:>5.1f} "
        for p in predicted_marks:
            count = matrix.get((h, p), 0)
            if has_halves:
                row_str += f" {count:>4}" if count > 0 else "    ."
            else:
                row_str += f"  {count:>2}" if count > 0 else "   ."
        print(row_str)


def print_full_report(results: list[EvalResult]):
    """Print the complete evaluation report."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    total = len(results)
    errors = sum(1 for r in results if r.error)

    print(f"\n{'#'*90}")
    print(f"  MARKING EVAL REPORT - {timestamp}")
    print(f"  Total evaluations: {total} | Errors: {errors}")
    print(f"{'#'*90}")

    # Maths results
    maths_results = [r for r in results if r.subject == "maths"]
    if maths_results:
        print_strategy_table("MATHS RESULTS", results, "maths")

        # Find best maths strategy by exact match
        by_strat = compute_grouped_metrics(maths_results, "strategy_name")
        best = max(by_strat.items(), key=lambda x: x[1].exact_match_rounded)
        print(f"\n  Best maths strategy: {best[0]} ({_fmt_pct(best[1].exact_match_rounded)} exact rounded)")

        # Per-question for best
        print_question_breakdown(results, best[0])
        print_confusion_matrix(results, best[0])

    # English results
    english_results = [r for r in results if r.subject == "english"]
    if english_results:
        print_strategy_table("ENGLISH RESULTS", results, "english")

        by_strat = compute_grouped_metrics(english_results, "strategy_name")
        best = max(by_strat.items(), key=lambda x: x[1].exact_match_rounded)
        print(f"\n  Best English strategy: {best[0]} ({_fmt_pct(best[1].exact_match_rounded)} exact rounded)")
        print_confusion_matrix(results, best[0])


def export_csv(results: list[EvalResult], output_dir: Path | None = None):
    """Export detailed results and summary to CSV."""
    output_dir = output_dir or config.RESULTS_DIR
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Detailed results
    detail_path = output_dir / f"eval_results_{timestamp}.csv"
    with open(detail_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "strategy_name", "subject", "question_number", "row_id",
            "total_marks", "human_mark", "ai_mark", "error",
            "abs_error", "signed_error", "exact_match", "within_1",
            "justification",
            "prompt_tokens", "output_tokens", "thinking_tokens", "cost_usd",
        ])
        for r in results:
            if r.error or r.ai_mark < 0:
                ae = se = ""
                exact = within = ""
            else:
                se = r.ai_mark - r.human_mark
                ae = abs(se)
                exact = "1" if r.ai_mark == r.human_mark else "0"
                within = "1" if abs(se) <= 1 else "0"
            writer.writerow([
                r.strategy_name, r.subject, r.question_number, r.row_id,
                r.total_marks, r.human_mark, r.ai_mark, r.error,
                ae, se, exact, within,
                r.justification[:500],  # truncate long justifications
                r.usage.prompt_tokens, r.usage.output_tokens,
                r.usage.thinking_tokens, f"{r.usage.cost_usd():.6f}",
            ])

    # Summary
    summary_path = output_dir / f"eval_summary_{timestamp}.csv"
    all_grouped = compute_grouped_metrics(results, "strategy_name")

    # Aggregate cost per strategy
    from .runner import TokenUsage
    cost_by_strategy: dict[str, float] = {}
    for r in results:
        if r.strategy_name not in cost_by_strategy:
            cost_by_strategy[r.strategy_name] = 0.0
        cost_by_strategy[r.strategy_name] += r.usage.cost_usd()

    with open(summary_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "strategy_name", "n", "exact_match_pct", "exact_match_rounded_pct",
            "within_1_pct", "mae", "mean_signed_error",
            "over_mark_pct", "under_mark_pct", "errors", "cost_usd",
        ])
        for name, m in all_grouped.items():
            writer.writerow([
                name, m.n, f"{m.exact_match:.1f}", f"{m.exact_match_rounded:.1f}",
                f"{m.within_1:.1f}", f"{m.mae:.3f}", f"{m.mean_signed_error:.3f}",
                f"{m.over_mark_pct:.1f}", f"{m.under_mark_pct:.1f}", m.errors,
                f"{cost_by_strategy.get(name, 0.0):.4f}",
            ])

    print(f"\n  Results exported:")
    print(f"    Detail: {detail_path}")
    print(f"    Summary: {summary_path}")

    return detail_path, summary_path
