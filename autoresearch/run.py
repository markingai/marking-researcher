"""Autoresearch experiment runner — handles git commit/revert and results tracking.

Usage:
    python -m autoresearch.run --description "describe what you changed"
    python -m autoresearch.run --description "quick test" --sample-size 30
    python -m autoresearch.run --description "validate winner" --split test
"""

from __future__ import annotations
import sys
import os
import argparse
import subprocess
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from autoresearch.harness import (
    run_evaluation,
    append_results_tsv,
    get_best_result,
    get_session_spend,
)
from eval_agent import config


def git_cmd(*args: str) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_commit(description: str) -> str:
    """Stage experiment.py and commit. Returns commit SHA."""
    git_cmd("add", "autoresearch/experiment.py")
    git_cmd("commit", "-m", f"exp: {description}")
    return git_cmd("rev-parse", "--short", "HEAD")


def git_revert_experiment():
    """Revert experiment.py to previous commit's version."""
    git_cmd("checkout", "HEAD~1", "--", "autoresearch/experiment.py")
    git_cmd("commit", "-m", "revert: experiment did not improve")


def main():
    parser = argparse.ArgumentParser(description="Autoresearch Experiment Runner")
    parser.add_argument(
        "--description", "-d",
        required=True,
        help="Brief description of the experiment (what was changed).",
    )
    parser.add_argument(
        "--sample-size", "-n",
        type=int,
        default=None,
        help="Number of rows to evaluate (default: full dev split).",
    )
    parser.add_argument(
        "--split",
        choices=["dev", "test"],
        default="dev",
        help="Data split to evaluate on (default: dev).",
    )
    parser.add_argument(
        "--no-git",
        action="store_true",
        help="Skip git commit/revert (for testing).",
    )
    args = parser.parse_args()

    # Session budget check
    spent = get_session_spend()
    remaining = config.SESSION_BUDGET_USD - spent
    if remaining <= 0:
        print(f"\n  SESSION BUDGET EXHAUSTED: ${spent:.2f} / ${config.SESSION_BUDGET_USD:.2f}")
        print(f"  Review results.tsv and report back with recommendations.")
        sys.exit(1)
    print(f"\nSession budget: ${spent:.2f} spent, ${remaining:.2f} remaining")

    # Get current best for comparison
    best = get_best_result()
    if best:
        print(f"Current best: exact={best['exact_match']:.1f}% mae={best['mae']:.2f} ({best['description']})")
    else:
        print("No previous results — this will be the baseline.")

    # Commit experiment changes
    commit_sha = "none"
    if not args.no_git:
        # Check if there are changes to commit
        status = git_cmd("diff", "--name-only", "autoresearch/experiment.py")
        staged = git_cmd("diff", "--cached", "--name-only", "autoresearch/experiment.py")
        if status or staged:
            commit_sha = git_commit(args.description)
            print(f"Committed: {commit_sha}")
        else:
            commit_sha = git_cmd("rev-parse", "--short", "HEAD")
            print(f"No changes to commit (current: {commit_sha})")

    # Run evaluation
    print(f"\nRunning experiment: {args.description}")
    print("=" * 60)
    result = run_evaluation(
        sample_size=args.sample_size,
        split=args.split,
        verbose=True,
    )

    if result.get("aborted"):
        print("\n  Experiment aborted. Reverting.")
        if not args.no_git and status:
            git_revert_experiment()
        sys.exit(1)

    # Determine if improved
    improved = False
    if best is None:
        # First experiment — always keep
        improved = True
        print("\n  BASELINE ESTABLISHED")
    else:
        exact_delta = result["exact_match"] - best["exact_match"]
        mae_delta = result["mae"] - best["mae"]

        if exact_delta > 0:
            improved = True
            print(f"\n  IMPROVED: exact_match +{exact_delta:.1f}%")
        elif exact_delta == 0 and mae_delta < 0:
            improved = True
            print(f"\n  IMPROVED: same exact_match, MAE {mae_delta:.2f}")
        else:
            print(f"\n  NO IMPROVEMENT: exact_match {exact_delta:+.1f}%, MAE {mae_delta:+.2f}")

    # Record results
    append_results_tsv(result, args.description, commit_sha, kept=improved)

    # Revert if not improved
    if not improved and not args.no_git:
        # Only revert if we actually committed changes
        if status or staged:
            git_revert_experiment()
            print("  Reverted experiment.py to previous version.")

    # Summary
    print(f"\n{'=' * 60}")
    if improved:
        print(f"  KEPT: {args.description}")
    else:
        print(f"  DISCARDED: {args.description}")
    print(f"  Results appended to results.tsv")
    print(f"  Session spend: ${spent + result.get('cost_usd', 0):.2f} / ${config.SESSION_BUDGET_USD:.2f}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
