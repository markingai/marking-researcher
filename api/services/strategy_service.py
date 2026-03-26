"""Strategy listing service — wraps eval_agent strategy registry."""

from __future__ import annotations

import json
import sys
import os

# Ensure eval_agent is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval_agent.strategies import build_strategies, build_generic_strategies, Strategy, parse_simple
from eval_agent.prompts.english_prompts import SIMPLE_SCHEMA
from eval_agent.report_html import PHASE_MAP, STRATEGY_DESCRIPTIONS, STRATEGY_DEEP_DIVE

_cached_strategies: list[Strategy] | None = None
_dynamic_strategies: list[Strategy] = []
_custom_strategies: list[Strategy] = []


def _build_custom_prompt_fn(prompt_text: str):
    """Build a prompt_fn from stored system prompt text."""
    def prompt_fn(row):
        user_parts = [
            f"Rubric:\n{row.marking_guide}",
        ]
        if row.source_text:
            user_parts.append(f"Source texts:\n{row.source_text[:8000]}")
        user_parts.extend([
            f"Student response:\n{row.student_answer}",
            (
                f"Mark this response out of {row.total_marks} using the rubric above. "
                f"Return JSON with 'mark' (integer 0 to {row.total_marks}) "
                "and 'justification' (brief explanation referencing rubric criteria)."
            ),
        ])
        return prompt_text, user_parts, SIMPLE_SCHEMA
    return prompt_fn


def get_all_strategies() -> list[Strategy]:
    """Get all registered strategies (cached), including dynamic and custom ones."""
    global _cached_strategies
    if _cached_strategies is None:
        _cached_strategies = build_strategies()
    return _cached_strategies + _dynamic_strategies + _custom_strategies


def reload_custom_strategies():
    """Load custom strategies from the database."""
    global _custom_strategies
    from ..database import get_db
    strategies = []
    with get_db() as db:
        rows = db.execute("SELECT * FROM custom_strategies ORDER BY created_at").fetchall()
    for row in rows:
        strategies.append(Strategy(
            name=row["name"],
            description=row["description"],
            subject=row["subject"],
            model=row["model"],
            temperature=row["temperature"],
            thinking=True,
            thinking_budget=row["thinking_budget"],
            prompt_fn=_build_custom_prompt_fn(row["prompt_text"]),
            parse_fn=parse_simple,
            provider="gemini",
        ))
    _custom_strategies = strategies


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
    if not _custom_strategies:
        reload_custom_strategies()


def get_strategy_info(strategy: Strategy) -> dict:
    """Build a strategy info dict with metadata from report_html."""
    is_custom = any(s.name == strategy.name for s in _custom_strategies)
    phase = "autoresearch" if is_custom else PHASE_MAP.get(strategy.name)
    desc = STRATEGY_DESCRIPTIONS.get(strategy.name, strategy.description)
    deep_dive = STRATEGY_DEEP_DIVE.get(strategy.name, {})

    tags = deep_dive.get("tags", [])
    if is_custom and "autoresearch" not in tags:
        tags = ["autoresearch"] + tags

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
        "tags": tags,
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
