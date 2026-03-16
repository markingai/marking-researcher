"""CLI entry point for the marking eval agent."""

from __future__ import annotations
import sys
import os
import argparse
import time

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env
from pathlib import Path
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

from eval_agent import config
from eval_agent.data_loader import load_maths, load_english, stratified_sample
from eval_agent.strategies import build_strategies
from eval_agent.runner import EvalRunner
from eval_agent.report import print_full_report, export_csv


def main():
    parser = argparse.ArgumentParser(description="Marking.ai Strategy Eval Agent")
    parser.add_argument(
        "--strategies", "-s",
        nargs="*",
        help="Run only these strategies (by name). Default: all.",
    )
    parser.add_argument(
        "--subject",
        choices=["maths", "english", "all"],
        default="all",
        help="Which subject to evaluate. Default: all.",
    )
    parser.add_argument(
        "--maths-sample", "-m",
        type=int,
        default=config.MATHS_SAMPLE_SIZE,
        help=f"Maths sample size. Default: {config.MATHS_SAMPLE_SIZE}",
    )
    parser.add_argument(
        "--english-sample", "-e",
        type=int,
        default=config.ENGLISH_SAMPLE_SIZE,
        help=f"English sample size. Default: {config.ENGLISH_SAMPLE_SIZE}",
    )
    parser.add_argument(
        "--no-export",
        action="store_true",
        help="Skip CSV export.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load data and show what would run without making API calls.",
    )
    parser.add_argument(
        "--html-report",
        action="store_true",
        help="Generate a comprehensive HTML report from all historical results.",
    )
    parser.add_argument(
        "--deploy",
        action="store_true",
        help="Deploy the HTML report to Cloudflare Pages (requires API token in .env).",
    )
    parser.add_argument(
        "--input-mode",
        choices=["csv", "pdf"],
        default="csv",
        help="Input mode: 'csv' (default) uses pre-extracted text, 'pdf' uses submission PDFs.",
    )
    parser.add_argument(
        "--pdf-dir",
        type=str,
        default=None,
        help="Directory containing submission PDFs (for --input-mode pdf). Default: Maths/",
    )
    args = parser.parse_args()

    # Validate API keys
    if not config.GEMINI_API_KEY:
        print("ERROR: GEMINI_API_KEY not set. Add it to .env or set as environment variable.")
        sys.exit(1)

    # Check if non-Gemini providers are needed (skip on dry-run)
    if not args.dry_run:
        all_strategies_check = build_strategies()
        if args.strategies:
            all_strategies_check = [s for s in all_strategies_check if s.name in args.strategies]
        if args.subject != "all":
            all_strategies_check = [s for s in all_strategies_check if s.subject == args.subject]
        providers_needed = {s.provider for s in all_strategies_check}
        if "anthropic" in providers_needed and not config.ANTHROPIC_API_KEY:
            print("ERROR: ANTHROPIC_API_KEY not set. Add it to .env or set as environment variable.")
            sys.exit(1)
        if "openai" in providers_needed and not config.OPENAI_API_KEY:
            print("ERROR: OPENAI_API_KEY not set. Add it to .env or set as environment variable.")
            sys.exit(1)

    print("=" * 60)
    print("  Marking.ai Strategy Evaluation Agent")
    print("=" * 60)

    # Load data
    print("\nLoading data...")

    if args.input_mode == "pdf":
        # PDF mode: load submission PDFs and match to CSV ground truth
        from eval_agent.pdf_data_loader import load_pdf_maths
        pdf_dir = Path(args.pdf_dir) if args.pdf_dir else config.PROJECT_ROOT / "Maths"
        all_maths = load_pdf_maths(pdf_dir) if args.subject in ("maths", "all") else []
        all_english = []  # PDF mode only supports maths for now
        if args.subject == "english":
            print("  WARNING: PDF mode only supports maths currently. No English data loaded.")
        print(f"  Maths (PDF): {len(all_maths)} rows loaded")
    else:
        # CSV mode (default)
        all_maths = load_maths() if args.subject in ("maths", "all") else []
        all_english = load_english() if args.subject in ("english", "all") else []
        print(f"  Maths: {len(all_maths)} rows loaded")
        print(f"  English: {len(all_english)} rows loaded")

    # Sample
    maths_sample = stratified_sample(all_maths, args.maths_sample) if all_maths else []
    english_sample = stratified_sample(all_english, args.english_sample) if all_english else []
    print(f"\nSampled:")
    print(f"  Maths: {len(maths_sample)} rows (stratified by question)")
    print(f"  English: {len(english_sample)} rows")

    if maths_sample:
        from collections import Counter
        q_dist = Counter(r.question_number for r in maths_sample)
        print(f"  Maths Q distribution: {dict(sorted(q_dist.items(), key=lambda x: int(x[0])))}")

    # Build strategies
    all_strategies = build_strategies()

    # Filter by subject
    if args.subject != "all":
        all_strategies = [s for s in all_strategies if s.subject == args.subject]

    # Filter by name
    strategy_names = args.strategies
    if strategy_names:
        all_strategies = [s for s in all_strategies if s.name in strategy_names]

    def _est_calls(s, rows):
        """Estimate API calls per sample for a strategy."""
        if s.debate_config:
            dc = s.debate_config
            if dc.mode == "panel":
                return rows * len(dc.panel_prompt_fns or [3])
            elif dc.mode == "dual_adjudicate":
                return rows * 3  # worst case: all disagree
            elif dc.mode == "multi_round":
                return rows * (2 + 2 * dc.max_debate_rounds)  # worst case
        if s.is_two_pass:
            return rows * 2
        return rows * s.ensemble_runs

    print(f"\nStrategies to run ({len(all_strategies)}):")
    for s in all_strategies:
        rows = len(maths_sample) if s.subject == "maths" else len(english_sample)
        calls = _est_calls(s, rows)
        print(f"  - {s.name} ({s.subject}, ~{calls} API calls)")

    total_calls = sum(
        _est_calls(s, len(maths_sample) if s.subject == "maths" else len(english_sample))
        for s in all_strategies
    )
    est_minutes = total_calls / config.CALLS_PER_MINUTE
    print(f"\nEstimated: ~{total_calls} API calls, ~{est_minutes:.0f} minutes")

    if args.dry_run:
        print("\n[DRY RUN] Exiting without making API calls.")
        return

    # Run
    runner = EvalRunner(
        strategies=all_strategies,
        maths_sample=maths_sample,
        english_sample=english_sample,
        all_maths=all_maths,
        all_english=all_english,
    )

    start = time.time()
    runner.run(strategy_names=strategy_names)
    elapsed = time.time() - start

    print(f"\nTotal runtime: {elapsed:.0f}s ({elapsed/60:.1f} min)")

    # Cost summary
    from eval_agent.runner import TokenUsage
    from collections import defaultdict
    cost_by_strategy: dict[str, TokenUsage] = defaultdict(TokenUsage)
    for r in runner.results:
        cost_by_strategy[r.strategy_name] = cost_by_strategy[r.strategy_name] + r.usage
    total_cost = 0.0
    print(f"\n{'='*60}")
    print("  TOKEN USAGE & COST")
    print(f"{'='*60}")
    for sname, usage in sorted(cost_by_strategy.items()):
        cost = usage.cost_usd()
        total_cost += cost
        print(
            f"  {sname:45s} "
            f"{usage.prompt_tokens:>8,} in / "
            f"{usage.output_tokens:>6,} out / "
            f"{usage.thinking_tokens:>8,} think  "
            f"${cost:.4f}"
        )
    print(f"  {'':45s} {'TOTAL':>30s}  ${total_cost:.4f}")

    # Report
    print_full_report(runner.results)

    # Export
    if not args.no_export:
        export_csv(runner.results)

    # HTML report
    report_path = None
    if args.html_report or args.deploy:
        from eval_agent.report_html import generate_html_report
        historical = sorted(config.RESULTS_DIR.glob("eval_results_*.csv"))
        report_path = generate_html_report(runner.results, historical)
        print(f"\n  HTML report: {report_path}")

    # Deploy to Cloudflare Pages
    if args.deploy:
        from eval_agent.deploy import deploy_report
        if report_path:
            deploy_report(report_path)


if __name__ == "__main__":
    main()
