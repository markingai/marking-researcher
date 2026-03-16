"""Strategy listing service — wraps eval_agent strategy registry."""

from __future__ import annotations

import sys
import os

# Ensure eval_agent is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval_agent.strategies import build_strategies, build_generic_strategies, Strategy
from eval_agent.report_html import PHASE_MAP, STRATEGY_DESCRIPTIONS, STRATEGY_DEEP_DIVE

_cached_strategies: list[Strategy] | None = None
_dynamic_strategies: list[Strategy] = []


def get_all_strategies() -> list[Strategy]:
    """Get all registered strategies (cached), including dynamic custom-subject ones."""
    global _cached_strategies
    if _cached_strategies is None:
        _cached_strategies = build_strategies()
    return _cached_strategies + _dynamic_strategies


def refresh_dynamic_strategies():
    """Rebuild dynamic strategies from custom subjects in the DB."""
    global _dynamic_strategies
    from .dataset_service import get_custom_subjects
    new_strategies = []
    for subj in get_custom_subjects():
        new_strategies.extend(
            build_generic_strategies(subj["slug"], subj["display_name"])
        )
    _dynamic_strategies = new_strategies


def ensure_dynamic_strategies_loaded():
    """Load dynamic strategies if not already loaded."""
    if not _dynamic_strategies:
        refresh_dynamic_strategies()


def get_strategy_info(strategy: Strategy) -> dict:
    """Build a strategy info dict with metadata from report_html."""
    phase = PHASE_MAP.get(strategy.name)
    desc = STRATEGY_DESCRIPTIONS.get(strategy.name, strategy.description)
    deep_dive = STRATEGY_DEEP_DIVE.get(strategy.name, {})

    return {
        "name": strategy.name,
        "description": desc,
        "long_description": deep_dive.get("concept"),
        "concept": deep_dive.get("concept"),
        "methodology": deep_dive.get("methodology"),
        "recommendations": deep_dive.get("recommendations"),
        "subject": strategy.subject,
        "model": strategy.model,
        "provider": strategy.provider,
        "phase": phase,
        "tags": deep_dive.get("tags", []),
        "is_two_pass": strategy.is_two_pass,
        "has_debate": strategy.debate_config is not None,
        "ensemble_runs": strategy.ensemble_runs,
    }


def get_strategy_by_name(name: str) -> Strategy | None:
    """Find a strategy by name."""
    for s in get_all_strategies():
        if s.name == name:
            return s
    return None
