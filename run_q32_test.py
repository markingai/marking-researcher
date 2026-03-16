"""Run Q32 visual question test: baseline vs visual_rigorous vs visual_v2."""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env
from pathlib import Path
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

from eval_agent import config
from eval_agent.pdf_data_loader import load_pdf_maths
from eval_agent.strategies import build_strategies
from eval_agent.runner import EvalRunner

# Load Q32 data from q32_test directory
pdf_dir = Path(__file__).parent / "Maths" / "q32_test"
q32_data = load_pdf_maths(pdf_dir, questions={"32"})
print(f"\nQ32 test set: {len(q32_data)} submissions")

# Show human mark distribution
from collections import Counter
mark_dist = Counter(r.human_mark for r in q32_data)
print(f"Human mark distribution: {dict(sorted(mark_dist.items()))}")

# Get just the strategies we want to compare
all_strategies = build_strategies()
target_names = {"maths_pdf_visual_v2"}
strategies = [s for s in all_strategies if s.name in target_names]
print(f"\nStrategies: {[s.name for s in strategies]}")

# Run
runner = EvalRunner(
    strategies=strategies,
    maths_sample=q32_data,
    english_sample=[],
    all_maths=q32_data,
    all_english=[],
)

start = time.time()
runner.run()
elapsed = time.time() - start
print(f"\nRuntime: {elapsed:.0f}s ({elapsed/60:.1f} min)")

# Previous results for comparison
prev_results = {
    "maths_pdf_baseline": {
        "exact": 14, "within1": 23, "n": 31, "bias": 0.90, "mae": 0.97,
        "cases": {
            "195293": (0, 4), "195333": (0, 2), "195337": (0, 0), "195365": (2, 4),
            "195377": (1, 4), "195399": (1, 2), "195400": (0, 1), "195406": (2, 3),
            "195411": (1, 2), "195412": (0, 2), "195441": (1, 1), "195446": (0, 0),
            "195460": (1, 4), "195475": (0, 2), "195486": (0, 0), "195488": (2, 3),
            "195494": (4, 4), "195495": (4, 4), "195678": (2, 2), "195761": (3, 3),
            "195798": (4, 4), "195816": (4, 4), "195819": (3, 3), "195825": (4, 4),
            "195840": (1, 2), "195877": (4, 4), "195894": (4, 4), "195897": (4, 3),
            "195921": (3, 4), "195952": (2, 3), "195967": (1, 4),
        },
    },
    "maths_pdf_visual_rigorous": {
        "exact": 14, "within1": 24, "n": 31, "bias": 0.77, "mae": 0.84,
        "cases": {
            "195293": (0, 2), "195333": (0, 1), "195337": (0, 0), "195365": (2, 4),
            "195377": (1, 4), "195399": (1, 2), "195400": (0, 1), "195406": (2, 2),
            "195411": (1, 2), "195412": (0, 2), "195441": (1, 2), "195446": (0, 0),
            "195460": (1, 3), "195475": (0, 2), "195486": (0, 1), "195488": (2, 3),
            "195494": (4, 4), "195495": (4, 4), "195678": (2, 2), "195761": (3, 3),
            "195798": (4, 4), "195816": (4, 4), "195819": (3, 3), "195825": (4, 4),
            "195840": (1, 1), "195877": (4, 4), "195894": (4, 4), "195897": (4, 3),
            "195921": (3, 4), "195952": (2, 3), "195967": (1, 4),
        },
    },
}

# Analyze current results
for strat_name in target_names:
    results = [r for r in runner.results if r.strategy_name == strat_name]
    if not results:
        continue

    print(f"\n{'='*60}")
    print(f"  {strat_name}")
    print(f"{'='*60}")

    exact = sum(1 for r in results if r.ai_mark == r.human_mark)
    within_1 = sum(1 for r in results if abs(r.ai_mark - r.human_mark) <= 1)
    errors = [r for r in results if r.error]
    valid = [r for r in results if not r.error]

    if valid:
        bias = sum(r.ai_mark - r.human_mark for r in valid) / len(valid)
        mae = sum(abs(r.ai_mark - r.human_mark) for r in valid) / len(valid)
    else:
        bias = mae = 0

    print(f"  Total: {len(results)}, Errors: {len(errors)}, Valid: {len(valid)}")
    print(f"  Exact match: {exact}/{len(valid)} ({100*exact/len(valid):.1f}%)")
    print(f"  Within 1: {within_1}/{len(valid)} ({100*within_1/len(valid):.1f}%)")
    print(f"  Bias: {bias:+.2f}")
    print(f"  MAE: {mae:.2f}")

    # Per-case details
    print(f"\n  {'Case':<12} {'Human':>5} {'AI':>5} {'Diff':>5}")
    print(f"  {'-'*32}")
    for r in sorted(valid, key=lambda x: x.row_id):
        diff = r.ai_mark - r.human_mark
        flag = " <<<" if abs(diff) > 1 else ""
        print(f"  {r.row_id:<12} {r.human_mark:>5.0f} {r.ai_mark:>5.0f} {diff:>+5.0f}{flag}")

# Comparison table
print(f"\n\n{'='*60}")
print("  Q32 STRATEGY COMPARISON (31 submissions)")
print(f"{'='*60}")
print(f"  {'Strategy':<30} {'Exact':>8} {'W/in 1':>8} {'Bias':>8} {'MAE':>8}")
print(f"  {'-'*62}")
for name, data in prev_results.items():
    pct = 100 * data["exact"] / data["n"]
    w1pct = 100 * data["within1"] / data["n"]
    print(f"  {name:<30} {pct:>7.1f}% {w1pct:>7.1f}% {data['bias']:>+7.2f} {data['mae']:>7.2f}")

# Add current results
for strat_name in target_names:
    results = [r for r in runner.results if r.strategy_name == strat_name]
    valid = [r for r in results if not r.error]
    if valid:
        exact = sum(1 for r in valid if r.ai_mark == r.human_mark)
        within_1 = sum(1 for r in valid if abs(r.ai_mark - r.human_mark) <= 1)
        bias = sum(r.ai_mark - r.human_mark for r in valid) / len(valid)
        mae = sum(abs(r.ai_mark - r.human_mark) for r in valid) / len(valid)
        pct = 100 * exact / len(valid)
        w1pct = 100 * within_1 / len(valid)
        print(f"  {strat_name:<30} {pct:>7.1f}% {w1pct:>7.1f}% {bias:>+7.2f} {mae:>7.2f}")
