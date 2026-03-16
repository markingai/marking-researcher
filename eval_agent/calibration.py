"""Post-hoc calibration for systematic bias correction.

Fits a mapping from AI scores to calibrated scores using training data,
then applies the mapping to new predictions.
"""

from __future__ import annotations
import csv
from collections import defaultdict
from pathlib import Path

from . import config


def fit_linear_calibration(
    results_csv: Path,
    strategy_name: str,
) -> tuple[float, float]:
    """Fit a simple linear calibration: calibrated = slope * raw + intercept.

    Returns (slope, intercept).
    """
    with open(results_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["strategy_name"] == strategy_name and r["error"] != "True"]

    if len(rows) < 5:
        return 1.0, 0.0  # Not enough data, return identity

    ai_marks = [float(r["ai_mark"]) for r in rows]
    human_marks = [float(r["human_mark"]) for r in rows]

    n = len(ai_marks)
    mean_ai = sum(ai_marks) / n
    mean_human = sum(human_marks) / n

    # Linear regression: human = slope * ai + intercept
    numerator = sum((a - mean_ai) * (h - mean_human) for a, h in zip(ai_marks, human_marks))
    denominator = sum((a - mean_ai) ** 2 for a in ai_marks)

    if denominator == 0:
        return 1.0, mean_human - mean_ai  # All AI marks the same, just shift

    slope = numerator / denominator
    intercept = mean_human - slope * mean_ai

    return slope, intercept


def fit_bucket_calibration(
    results_csv: Path,
    strategy_name: str,
) -> dict[int, float]:
    """Fit a bucket-based calibration: for each AI score, compute the average human score.

    Returns {ai_score: avg_human_score}.
    """
    with open(results_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = [r for r in reader if r["strategy_name"] == strategy_name and r["error"] != "True"]

    by_ai: dict[int, list[float]] = defaultdict(list)
    for r in rows:
        ai = round(float(r["ai_mark"]))
        human = float(r["human_mark"])
        by_ai[ai].append(human)

    calibration = {}
    for ai_score, human_scores in sorted(by_ai.items()):
        avg = sum(human_scores) / len(human_scores)
        calibration[ai_score] = round(avg * 2) / 2  # Round to nearest 0.5
        print(f"  Calibration: AI={ai_score} → avg_human={avg:.2f} → calibrated={calibration[ai_score]}")

    return calibration


def apply_linear(mark: float, slope: float, intercept: float, max_mark: int = 6) -> int:
    """Apply linear calibration and round to nearest integer."""
    calibrated = slope * mark + intercept
    return max(0, min(max_mark, round(calibrated)))


def apply_bucket(mark: float, calibration: dict[int, float], max_mark: int = 6) -> float:
    """Apply bucket calibration."""
    rounded = round(mark)
    if rounded in calibration:
        return calibration[rounded]
    return mark  # No calibration data for this score, return as-is
