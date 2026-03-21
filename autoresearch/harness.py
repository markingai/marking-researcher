"""Fixed evaluation harness for autoresearch.

DO NOT MODIFY THIS FILE — the agent modifies experiment.py only.
This harness loads data, runs a strategy, computes metrics, and reports results.
"""

from __future__ import annotations
import sys
import os
import argparse
import time
import random
import csv
from pathlib import Path
from collections import defaultdict
from datetime import datetime

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Load .env
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

from eval_agent import config
from eval_agent.data_loader import load_exampro, MarkingRow, stratified_sample
from eval_agent.runner import EvalRunner, TokenUsage
from eval_agent.metrics import compute_metrics, compute_per_question_metrics

RESULTS_TSV = Path(__file__).parent / "results.tsv"
RUN_RESULTS_DIR = Path(__file__).parent / "run_results"

# Deterministic split seeds (different from main project seed=42)
SPLIT_SEED = 99


def create_splits(
    rows: list[MarkingRow],
    train_frac: float = 0.60,
    dev_frac: float = 0.20,
) -> tuple[list[MarkingRow], list[MarkingRow], list[MarkingRow]]:
    """Split rows into train/dev/test with deterministic seed, stratified by question."""
    rng = random.Random(SPLIT_SEED)

    groups: dict[str, list[MarkingRow]] = defaultdict(list)
    for row in rows:
        groups[row.question_number].append(row)

    train, dev, test = [], [], []
    for qn in sorted(groups.keys()):
        pool = groups[qn]
        rng.shuffle(pool)
        n = len(pool)
        n_train = int(n * train_frac)
        n_dev = int(n * dev_frac)
        train.extend(pool[:n_train])
        dev.extend(pool[n_train : n_train + n_dev])
        test.extend(pool[n_train + n_dev :])

    return train, dev, test


def estimate_cost(n_rows: int, model: str) -> float:
    """Rough cost estimate for a single-pass strategy."""
    pricing = config.MODEL_PRICING.get(model, {})
    # Assume ~2000 input tokens and ~500 output tokens per call (conservative)
    input_rate = pricing.get("input", 2.0) / 1_000_000
    output_rate = pricing.get("output", 10.0) / 1_000_000
    per_call = 2000 * input_rate + 500 * output_rate
    return per_call * n_rows


def run_evaluation(
    sample_size: int | None = None,
    split: str = "dev",
    verbose: bool = True,
) -> dict:
    """Run the current experiment strategy on the specified data split.

    Returns dict with metrics, cost, and per-question breakdown.
    """
    # Import strategy from experiment.py
    from autoresearch.experiment import get_strategy

    strategy = get_strategy()

    # Load and split data
    all_rows = load_exampro()
    train_rows, dev_rows, test_rows = create_splits(all_rows)

    if split == "dev":
        eval_rows = dev_rows
    elif split == "test":
        eval_rows = test_rows
    elif split == "train":
        eval_rows = train_rows
    else:
        raise ValueError(f"Unknown split: {split}")

    if verbose:
        print(f"\nDataset: {len(all_rows)} total rows")
        print(f"  Train: {len(train_rows)}, Dev: {len(dev_rows)}, Test: {len(test_rows)}")

    # Subsample if requested
    if sample_size and sample_size < len(eval_rows):
        eval_rows = stratified_sample(eval_rows, sample_size, seed=SPLIT_SEED + 1)

    # Cost check
    est_cost = estimate_cost(len(eval_rows), strategy.model)
    if est_cost > config.EXPERIMENT_BUDGET_USD:
        print(f"\n  ABORT: Estimated cost ${est_cost:.2f} exceeds cap ${config.EXPERIMENT_BUDGET_USD:.2f}")
        print(f"  Try a smaller sample size (--sample-size) or cheaper model.")
        return {"aborted": True, "reason": "cost_cap", "estimated_cost": est_cost}

    if verbose:
        print(f"\nStrategy: {strategy.name}")
        print(f"  Model: {strategy.model}")
        print(f"  Eval split: {split} ({len(eval_rows)} rows)")
        print(f"  Estimated cost: ${est_cost:.2f}")

    # Run evaluation
    runner = EvalRunner(
        strategies=[strategy],
        maths_sample=[],
        english_sample=eval_rows,
        all_maths=[],
        all_english=train_rows,  # training rows available for few-shot
    )

    start = time.time()
    runner.run()
    elapsed = time.time() - start

    # Compute metrics
    metrics = compute_metrics(runner.results)
    per_q = compute_per_question_metrics(runner.results, strategy.name)

    # Compute actual cost
    total_usage = TokenUsage()
    for r in runner.results:
        total_usage = total_usage + r.usage
    actual_cost = total_usage.cost_usd()

    result = {
        "strategy_name": strategy.name,
        "model": strategy.model,
        "split": split,
        "n": metrics.n,
        "exact_match": metrics.exact_match,
        "within_half": metrics.within_half,
        "within_1": metrics.within_1,
        "mae": metrics.mae,
        "mean_signed_error": metrics.mean_signed_error,
        "over_mark_pct": metrics.over_mark_pct,
        "under_mark_pct": metrics.under_mark_pct,
        "errors": metrics.errors,
        "cost_usd": actual_cost,
        "elapsed_s": elapsed,
        "per_question": {
            qn: {
                "n": m.n,
                "exact_match": m.exact_match,
                "mae": m.mae,
            }
            for qn, m in per_q.items()
        },
    }

    # Print results
    if verbose:
        print(f"\n{'=' * 60}")
        print(f"  RESULTS: {strategy.name}")
        print(f"{'=' * 60}")
        print(f"  Exact match:    {metrics.exact_match:5.1f}%  ({metrics.exact_match_count}/{metrics.n})")
        print(f"  Within 0.5:     {metrics.within_half:5.1f}%")
        print(f"  Within 1:       {metrics.within_1:5.1f}%")
        print(f"  MAE:            {metrics.mae:5.2f}")
        print(f"  Bias:           {metrics.mean_signed_error:+5.2f}  (over:{metrics.over_mark_pct:.0f}% under:{metrics.under_mark_pct:.0f}%)")
        print(f"  Errors:         {metrics.errors}")
        print(f"  Cost:           ${actual_cost:.4f}")
        print(f"  Time:           {elapsed:.0f}s")
        print()
        print(f"  Per-question breakdown:")
        for qn, m in sorted(per_q.items()):
            print(f"    {qn:6s}: exact={m.exact_match:5.1f}%  mae={m.mae:.2f}  n={m.n}")

        # Machine-readable output for run.py to parse
        print(f"\nexact_match: {metrics.exact_match:.2f}")
        print(f"within_1: {metrics.within_1:.2f}")
        print(f"mae: {metrics.mae:.4f}")
        print(f"cost_usd: {actual_cost:.4f}")

    # Save per-row results
    RUN_RESULTS_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    row_file = RUN_RESULTS_DIR / f"{strategy.name}_{ts}.csv"
    with open(row_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row_id", "question_number", "human_mark", "ai_mark", "justification", "error"])
        for r in runner.results:
            writer.writerow([r.row_id, r.question_number, r.human_mark, r.ai_mark, r.justification, r.error])
    if verbose:
        print(f"\n  Per-row results: {row_file}")

    return result


def append_results_tsv(result: dict, description: str, commit_sha: str, kept: bool):
    """Append a row to results.tsv."""
    header = "experiment_id\ttimestamp\tdescription\texact_match\twithin_1\tmae\tbias\tcost_usd\tmodel\tn\tcommit_sha\tkept\n"
    if not RESULTS_TSV.exists():
        RESULTS_TSV.write_text(header)

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    exp_id = f"exp_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    row = (
        f"{exp_id}\t{ts}\t{description}\t"
        f"{result.get('exact_match', 0):.2f}\t{result.get('within_1', 0):.2f}\t"
        f"{result.get('mae', 0):.4f}\t{result.get('mean_signed_error', 0):+.2f}\t"
        f"{result.get('cost_usd', 0):.4f}\t{result.get('model', 'unknown')}\t"
        f"{result.get('n', 0)}\t{commit_sha}\t{'yes' if kept else 'no'}\n"
    )
    with open(RESULTS_TSV, "a") as f:
        f.write(row)


def get_best_result() -> dict | None:
    """Read results.tsv and return the best kept result."""
    if not RESULTS_TSV.exists():
        return None

    best = None
    with open(RESULTS_TSV, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("kept") != "yes":
                continue
            exact = float(row.get("exact_match", 0))
            if best is None or exact > best["exact_match"]:
                best = {
                    "exact_match": exact,
                    "within_1": float(row.get("within_1", 0)),
                    "mae": float(row.get("mae", 99)),
                    "description": row.get("description", ""),
                }
    return best


def get_session_spend() -> float:
    """Sum up cost_usd from all results in the current session (today)."""
    if not RESULTS_TSV.exists():
        return 0.0

    today = datetime.now().strftime("%Y-%m-%d")
    total = 0.0
    with open(RESULTS_TSV, "r") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("timestamp", "").startswith(today):
                total += float(row.get("cost_usd", 0))
    return total


def main():
    parser = argparse.ArgumentParser(description="Autoresearch Evaluation Harness")
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=None,
        help="Number of rows to evaluate (default: full split).",
    )
    parser.add_argument(
        "--split",
        choices=["dev", "test", "train"],
        default="dev",
        help="Which data split to evaluate on (default: dev).",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Minimal output (machine-readable metrics only).",
    )
    args = parser.parse_args()

    # Session budget check
    spent = get_session_spend()
    if spent >= config.SESSION_BUDGET_USD:
        print(f"\n  SESSION BUDGET EXHAUSTED: ${spent:.2f} / ${config.SESSION_BUDGET_USD:.2f}")
        print(f"  Review results.tsv and come back with recommendations.")
        sys.exit(1)

    print(f"Session spend so far: ${spent:.2f} / ${config.SESSION_BUDGET_USD:.2f}")

    result = run_evaluation(
        sample_size=args.sample_size,
        split=args.split,
        verbose=not args.quiet,
    )

    if result.get("aborted"):
        sys.exit(1)


if __name__ == "__main__":
    main()
