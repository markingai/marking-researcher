"""Adaptive recipe engine — builds strategy queue that learns from prior sessions.

On session 1 (no prior data): returns the 10 fixed baseline recipes.
On session 2+: queries all prior experiments, skips tested strategies,
imports untested strategies from the main codebase, generates variations
of winners, and creates hybrid combinations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass

from eval_agent import config as eval_config
from eval_agent.strategies import (
    Strategy,
    DebateConfig,
    parse_simple,
    parse_english_criterion,
    parse_english_halfmark_criterion,
    parse_scorecard,
    parse_comparative,
    parse_halfmark,
)
from eval_agent.prompts import english_prompts

# Type alias for recipe tuples (same as autoresearch_service)
RecipeTuple = tuple[str, str, Strategy, str, dict]


def _recipe_key(name: str, model: str, thinking_budget: int | None, temperature: float) -> str:
    """Create a dedup key for a recipe config."""
    raw = f"{name}|{model}|{thinking_budget}|{temperature}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


@dataclass
class _PriorResult:
    """Aggregated stats for a previously-tested strategy."""
    strategy_name: str
    best_exact: float
    avg_exact: float
    times_tested: int
    avg_cost: float
    best_config: dict | None


def _query_prior_results(db: sqlite3.Connection) -> dict[str, _PriorResult]:
    """Query all prior experiment results, grouped by strategy_name."""
    rows = db.execute("""
        SELECT strategy_name,
               MAX(exact_match) as best_exact,
               AVG(exact_match) as avg_exact,
               COUNT(*) as times_tested,
               AVG(cost_usd) as avg_cost,
               config_json
        FROM autoresearch_experiments
        WHERE exact_match IS NOT NULL
        GROUP BY strategy_name
        ORDER BY MAX(exact_match) DESC
    """).fetchall()

    results = {}
    for r in rows:
        config = None
        if r["config_json"]:
            try:
                config = json.loads(r["config_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        results[r["strategy_name"]] = _PriorResult(
            strategy_name=r["strategy_name"],
            best_exact=r["best_exact"] or 0,
            avg_exact=r["avg_exact"] or 0,
            times_tested=r["times_tested"],
            avg_cost=r["avg_cost"] or 0,
            best_config=config,
        )
    return results


def _query_recommendations(db: sqlite3.Connection) -> list[dict]:
    """Get unconsumed recommendations from prior sessions."""
    rows = db.execute("""
        SELECT * FROM autoresearch_recommendations
        WHERE consumed_by_session_id IS NULL
        ORDER BY priority ASC
    """).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Codebase strategy catalog — existing strategies we can import directly
# ---------------------------------------------------------------------------

def _build_codebase_strategies(model: str) -> list[RecipeTuple]:
    """Import existing English strategies from eval_agent that the autoresearch
    fixed recipes don't include. These are mature, production-quality strategies."""

    tb = eval_config.THINKING_BUDGET

    strategies: list[RecipeTuple] = []

    # Scorecard — signal-based deterministic scoring
    strategies.append((
        "scorecard",
        "Signal extraction + deterministic scoring (no LLM scoring)",
        Strategy(
            name="english_scorecard",
            description="Binary/ordinal signal extraction -> deterministic scoring",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_scorecard,
            parse_fn=parse_scorecard,
        ),
        "Extract 15 factual signals from the response, then compute mark deterministically. No LLM scoring.",
        {"schema": "scorecard", "thinking_budget": tb},
    ))

    # Cascade — two-pass band then exact
    strategies.append((
        "cascade",
        "Two-pass: band classification (LOW/MID/HIGH) then exact score",
        Strategy(
            name="english_cascade",
            description="Cascade: coarse band then fine exact score",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_cascade_pass1,
            parse_fn=parse_simple,
            is_two_pass=True,
        ),
        "Two-pass cascade: first classify into LOW/MID/HIGH band, then determine exact score within band.",
        {"schema": "cascade_two_pass", "thinking_budget": tb},
    ))

    # Comparative anchor — relative judgment vs exemplars
    strategies.append((
        "comparative_anchor",
        "Compare essay to score-3 and score-4 exemplars (relative judgment)",
        Strategy(
            name="english_comparative_anchor",
            description="Relative comparison to anchor essays",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
        ),
        "Compare essay against score-3 and score-4 anchor exemplars using WORSE/EQUAL/BETTER judgments per criterion.",
        {"schema": "comparative", "thinking_budget": tb},
    ))

    # Forced independence — anti-criterion-collapse
    strategies.append((
        "forced_independence",
        "Criterion scoring with anti-collapse guards",
        Strategy(
            name="english_forced_independence",
            description="Forces independent scoring per criterion",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
        ),
        "Score each criterion independently with explicit warnings against score collapse (identical scores = red flag).",
        {"schema": "english_criterion", "thinking_budget": tb},
    ))

    # Full exemplars — calibration essays at multiple levels
    strategies.append((
        "full_exemplars",
        "Full calibration essays at score 2, 3, 4, 5 + criterion scoring",
        Strategy(
            name="english_full_exemplars",
            description="Full exemplar essays for calibration",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_full_exemplars,
            parse_fn=parse_english_criterion,
        ),
        "Provide full essays at each score level (2, 3, 4, 5) as calibration anchors before marking.",
        {"schema": "english_criterion", "thinking_budget": tb},
    ))

    # Level descriptors — rubric-level matching
    strategies.append((
        "level_descriptors",
        "Match essay to specific rubric level descriptors per criterion",
        Strategy(
            name="english_level_descriptors",
            description="Rubric-level matching per criterion",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_level_descriptors,
            parse_fn=parse_english_criterion,
        ),
        "For each criterion, read all level descriptors (1-6) and match the response to the best-fit level.",
        {"schema": "english_criterion", "thinking_budget": tb},
    ))

    # Halfmark criterion — finer granularity
    strategies.append((
        "halfmark_criterion",
        "Criterion decomposed with 0.5-mark increments",
        Strategy(
            name="english_halfmark_criterion",
            description="Half-mark increments for finer scoring",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_halfmark_criterion,
            parse_fn=parse_english_halfmark_criterion,
        ),
        "Score each criterion with 0.5-mark increments (1.0, 1.5, 2.0, ..., 6.0) for finer granularity.",
        {"schema": "halfmark_criterion", "thinking_budget": tb},
    ))

    # Strict range — score distribution calibration
    strategies.append((
        "strict_range",
        "Baseline with score distribution calibration (3-4.5 is normal)",
        Strategy(
            name="english_strict_range",
            description="Score distribution calibrated marking",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_strict_range,
            parse_fn=parse_simple,
        ),
        "Emphasizes score distribution: 3-4.5 is normal range, 5-6 only for exceptional work.",
        {"schema": "simple", "thinking_budget": tb},
    ))

    # Moderated — comparative anchor + moderator review
    strategies.append((
        "moderated",
        "Two-pass: comparative anchor then independent moderator review",
        Strategy(
            name="english_moderated",
            description="Comparative anchor + moderation pass",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_comparative_anchor,
            parse_fn=parse_comparative,
            is_two_pass=True,
            second_pass_fn=english_prompts.english_moderation_pass2,
        ),
        "First pass: comparative anchor relative judgment. Second pass: independent moderator reviews and may adjust.",
        {"schema": "comparative+moderation", "thinking_budget": tb},
    ))

    # Panel — 3 independent markers vote
    strategies.append((
        "panel",
        "3 independent markers vote (forced_independence, level_descriptors, comparative)",
        Strategy(
            name="english_panel",
            description="Expert panel: 3 markers vote with majority/median",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            debate_config=DebateConfig(
                mode="panel",
                panel_prompt_fns=[
                    english_prompts.english_forced_independence,
                    english_prompts.english_level_descriptors,
                    english_prompts.english_comparative_anchor,
                ],
                panel_parse_fns=[
                    parse_english_criterion,
                    parse_english_criterion,
                    parse_comparative,
                ],
            ),
        ),
        "Three independent markers each score the essay using different methods. Result determined by majority vote or median.",
        {"schema": "panel_3_markers", "thinking_budget": tb, "cost_multiplier": 3},
    ))

    # Dual adjudicate — 2 markers + adjudicator on disagreement
    strategies.append((
        "dual_adjudicate",
        "Two markers + chief examiner adjudicator on disagreement",
        Strategy(
            name="english_dual_adjudicate",
            description="Dual marking with adjudicator",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            debate_config=DebateConfig(
                mode="dual_adjudicate",
                marker_b_prompt_fn=english_prompts.english_comparative_anchor,
                marker_b_parse_fn=parse_comparative,
                adjudicator_fn=english_prompts.english_adjudicator,
                adjudicator_parse_fn=parse_simple,
                agreement_threshold=0,
            ),
        ),
        "Two markers (forced_independence + comparative_anchor). If they disagree, a chief examiner adjudicates.",
        {"schema": "dual_adjudicate", "thinking_budget": tb, "cost_multiplier": 2.5},
    ))

    # Debate — multi-round rebuttal
    strategies.append((
        "debate",
        "Two markers debate with rebuttals (max 2 rounds)",
        Strategy(
            name="english_debate",
            description="Multi-round debate between markers",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            debate_config=DebateConfig(
                mode="multi_round",
                marker_b_prompt_fn=english_prompts.english_comparative_anchor,
                marker_b_parse_fn=parse_comparative,
                rebuttal_fn=english_prompts.english_debate_rebuttal,
                max_debate_rounds=2,
                deadlock_strategy="conservative",
            ),
        ),
        "Two markers independently score, then debate via rebuttals. Max 2 rounds. Conservative on deadlock.",
        {"schema": "debate_multi_round", "thinking_budget": tb, "cost_multiplier": 4},
    ))

    return strategies


def _build_variations(
    prior: dict[str, _PriorResult],
    model: str,
) -> list[RecipeTuple]:
    """Generate parameter variations of top-performing strategies."""
    from .autoresearch_service import build_recipe_strategies, _make_prompt_fn, _parse_simple

    variations: list[RecipeTuple] = []
    tb = eval_config.THINKING_BUDGET

    # Get top 3 strategies by best exact match
    ranked = sorted(prior.values(), key=lambda p: p.best_exact, reverse=True)[:3]

    for pr in ranked:
        # Higher thinking budget variation
        if pr.best_config and pr.best_config.get("thinking_budget", tb) < 8192:
            # Re-create the strategy with higher thinking
            sys_text = f"You are a senior GCSE English Language examiner. Mark strictly according to the mark scheme. Award only what is clearly evidenced. When in doubt, award the lower level. (Variant of {pr.strategy_name} with extended thinking)"
            variations.append((
                f"{pr.strategy_name}_high_think",
                f"{pr.strategy_name} with 8192 thinking budget",
                Strategy(
                    name=f"{pr.strategy_name}_high_think",
                    description=f"Extended thinking variant of {pr.strategy_name}",
                    subject="english",
                    model=model,
                    temperature=0.0,
                    thinking=True,
                    thinking_budget=8192,
                    prompt_fn=_make_prompt_fn(sys_text),
                    parse_fn=_parse_simple,
                ),
                sys_text,
                {"schema": "simple", "thinking_budget": 8192, "parent": pr.strategy_name},
            ))

        # Gemini 3.1 variant (if not already tested on 3.1)
        g31_name = f"{pr.strategy_name}_g31"
        if g31_name not in prior:
            sys_text = f"You are a senior GCSE English Language examiner. Mark strictly according to the mark scheme. Award only what is clearly evidenced. (Variant of {pr.strategy_name} on Gemini 3.1)"
            variations.append((
                g31_name,
                f"{pr.strategy_name} on Gemini 3.1 Pro",
                Strategy(
                    name=g31_name,
                    description=f"Gemini 3.1 variant of {pr.strategy_name}",
                    subject="english",
                    model=eval_config.MODEL_GEMINI_31,
                    temperature=0.0,
                    thinking=True,
                    thinking_budget=tb,
                    prompt_fn=_make_prompt_fn(sys_text),
                    parse_fn=_parse_simple,
                    thinking_level="low",
                ),
                sys_text,
                {"schema": "simple", "thinking_budget": tb, "model_override": eval_config.MODEL_GEMINI_31, "parent": pr.strategy_name},
            ))

    return variations


def _build_hybrids(prior: dict[str, _PriorResult], model: str) -> list[RecipeTuple]:
    """Generate hybrid combinations based on what worked."""
    from .autoresearch_service import _make_prompt_fn, _make_criterion_prompt_fn, _parse_simple, _parse_criterion

    hybrids: list[RecipeTuple] = []
    tb = eval_config.THINKING_BUDGET

    # Cascade + conservative: conservative framing in pass 2
    sys_text = (
        "You are a senior GCSE English Language examiner known for strict, rigorous marking. "
        "You are scoring within a predetermined band. Only award marks where clear evidence exists. "
        "Err on the side of under-marking."
    )
    hybrids.append((
        "cascade_conservative",
        "Cascade band classification + conservative exact scoring",
        Strategy(
            name="cascade_conservative",
            description="Cascade with conservative pass 2",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_cascade_pass1,
            parse_fn=parse_simple,
            is_two_pass=True,
        ),
        sys_text,
        {"schema": "cascade_conservative", "thinking_budget": tb},
    ))

    # Criterion + forced independence (anti-collapse criterion scoring)
    sys_text = (
        "You are a senior GCSE English Language examiner. "
        "Decompose the mark scheme into criteria and assess each INDEPENDENTLY. "
        "CRITICAL: Each criterion must be scored on its own merits. "
        "If you find yourself giving the same score for every criterion, stop — this is a red flag. "
        "Students typically have different strengths across criteria."
    )
    hybrids.append((
        "criterion_forced_independence",
        "Criterion decomposition with anti-collapse independence guards",
        Strategy(
            name="criterion_forced_independence",
            description="Criterion + independence guards",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=_make_criterion_prompt_fn(sys_text),
            parse_fn=_parse_criterion,
        ),
        sys_text,
        {"schema": "criterion", "thinking_budget": tb, "hybrid": "criterion+independence"},
    ))

    # Level matching + high thinking
    sys_text = (
        "You are a senior GCSE English Language examiner. Take extra time to think carefully. "
        "Use levels-based assessment:\n"
        "1. Read the full response thoroughly\n"
        "2. Match to the best-fit level descriptor\n"
        "3. Place within that level (top/middle/bottom)\n"
        "4. Award the mark\n"
        "When borderline, award the lower level."
    )
    hybrids.append((
        "level_match_high_think",
        "Level matching with extended thinking (8192)",
        Strategy(
            name="level_match_high_think",
            description="Level matching with 8192 thinking budget",
            subject="english",
            model=model,
            temperature=0.0,
            thinking=True,
            thinking_budget=8192,
            prompt_fn=_make_prompt_fn(sys_text),
            parse_fn=_parse_simple,
        ),
        sys_text,
        {"schema": "simple", "thinking_budget": 8192, "hybrid": "level_match+high_think"},
    ))

    # Bias-corrected variant (if best strategy has significant bias)
    if prior:
        best = max(prior.values(), key=lambda p: p.best_exact)
        if best.best_config:
            # Check if we can detect bias from the config/name pattern
            # We'll generate a generic bias-correction prompt
            sys_text = (
                "You are a senior GCSE English Language examiner. "
                "Research shows AI markers tend to over-mark by 0.3-0.5 marks on average. "
                "Compensate for this: be slightly stricter than your initial instinct. "
                "Mark only what is clearly evidenced. "
                "When in doubt between levels, always award the lower level."
            )
            hybrids.append((
                "bias_corrected",
                "Baseline with explicit bias correction instruction",
                Strategy(
                    name="bias_corrected",
                    description="Bias-corrected marking",
                    subject="english",
                    model=model,
                    temperature=0.0,
                    thinking=True,
                    thinking_budget=tb,
                    prompt_fn=_make_prompt_fn(sys_text),
                    parse_fn=_parse_simple,
                ),
                sys_text,
                {"schema": "simple", "thinking_budget": tb, "hybrid": "bias_correction"},
            ))

    # Flash ensemble — 3x Flash averaged
    sys_text = (
        "You are a senior GCSE English Language examiner. "
        "Score each criterion independently. Forces independent scoring per criterion. "
        "When in doubt, award the lower level."
    )
    hybrids.append((
        "flash_ensemble_3x",
        "3x Gemini Flash runs averaged (cheap ensemble, reduced variance)",
        Strategy(
            name="flash_ensemble_3x",
            description="Flash ensemble 3x averaged",
            subject="english",
            model=eval_config.MODEL_FLASH,
            temperature=0.3,
            thinking=True,
            thinking_budget=tb,
            prompt_fn=english_prompts.english_forced_independence,
            parse_fn=parse_english_criterion,
            ensemble_runs=3,
        ),
        sys_text,
        {"schema": "english_criterion", "thinking_budget": tb, "ensemble_runs": 3, "model_override": eval_config.MODEL_FLASH},
    ))

    return hybrids


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_adaptive_recipes(
    model: str,
    sample_size: int,
    budget_usd: float,
    db: sqlite3.Connection,
) -> list[RecipeTuple]:
    """Build a priority-ordered recipe queue that learns from prior sessions.

    Returns empty list if no prior data exists (caller should fallback to fixed recipes).
    """

    prior = _query_prior_results(db)
    if not prior:
        return []  # No prior data — caller uses fixed recipes

    recommendations = _query_recommendations(db)
    tested_names = set(prior.keys())

    recipes: list[tuple[int, RecipeTuple]] = []  # (priority, recipe)
    seen_keys: set[str] = set()

    def _add(priority: int, recipe: RecipeTuple):
        strategy = recipe[2]
        key = _recipe_key(
            strategy.name, strategy.model,
            strategy.thinking_budget, strategy.temperature,
        )
        if key in seen_keys:
            return
        # Skip if already tested (by strategy name)
        if strategy.name in tested_names:
            return
        seen_keys.add(key)
        recipes.append((priority, recipe))

    # Priority 10: Unconsumed recommendations
    # (These are concrete suggestions from prior session reports)
    # For now, we track them but the actual strategy objects come from
    # the sources below. The recommendations guide what to prioritize.
    recommended_names = {r["strategy_name"] for r in recommendations}

    # Priority 20: Untested strategies from codebase
    codebase_strategies = _build_codebase_strategies(model)
    for recipe in codebase_strategies:
        strategy = recipe[2]
        priority = 15 if strategy.name in recommended_names else 20
        _add(priority, recipe)

    # Priority 30: Variations of top performers
    variations = _build_variations(prior, model)
    for recipe in variations:
        strategy = recipe[2]
        priority = 25 if strategy.name in recommended_names else 30
        _add(priority, recipe)

    # Priority 40: Hybrid combinations
    hybrids = _build_hybrids(prior, model)
    for recipe in hybrids:
        strategy = recipe[2]
        priority = 35 if strategy.name in recommended_names else 40
        _add(priority, recipe)

    # Sort by priority (lower = run first)
    recipes.sort(key=lambda x: x[0])

    # Estimate costs and trim to budget
    default_cost = sample_size * 0.025  # ~$0.025 per row
    trimmed: list[RecipeTuple] = []
    estimated_total = 0.0

    for priority, recipe in recipes:
        strategy = recipe[2]
        config = recipe[4]

        # Estimate cost from prior data or defaults
        if strategy.name in prior:
            est_cost = prior[strategy.name].avg_cost
        else:
            multiplier = config.get("cost_multiplier", 1)
            est_cost = default_cost * multiplier

        if estimated_total + est_cost > budget_usd:
            continue  # Skip expensive recipes that don't fit

        estimated_total += est_cost
        trimmed.append(recipe)

    return trimmed
