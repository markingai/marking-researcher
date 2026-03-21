"""Autoresearch experiment — AGENT-MODIFIABLE FILE.

This file defines the current strategy under test. The autoresearch agent
modifies this file each iteration to try different approaches.

The get_strategy() function must return a single Strategy instance.
"""

from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval_agent.strategies import Strategy, parse_simple
from eval_agent import config
from eval_agent.data_loader import MarkingRow


# ============================================================================
# SCHEMA — structured output format the model must return
# ============================================================================

SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}


# ============================================================================
# PROMPT — the core marking prompt
# ============================================================================

def prompt_fn(row: MarkingRow) -> tuple[str, list[str], dict]:
    """Build the prompt for marking a single student response."""

    system = (
        "You are a senior GCSE English Language examiner for AQA/Pearson. "
        "You mark student responses strictly according to the mark scheme provided. "
        "Apply the mark scheme levels and descriptors precisely. "
        "Award only what is clearly evidenced in the student's response. "
        "When in doubt between two levels, award the lower level."
    )

    user_parts = []

    # Include the mark scheme
    user_parts.append(f"## Mark Scheme\n\n{row.marking_guide}")

    # Include source text if available (for reading questions)
    if row.source_text:
        user_parts.append(f"## Source Text\n\n{row.source_text}")

    # Include the question
    user_parts.append(f"## Question\n\n{row.question_text}")

    # Include the student response
    user_parts.append(f"## Student Response\n\n{row.student_answer}")

    # Instruction
    user_parts.append(
        f"Mark this response out of {row.total_marks} using the mark scheme above. "
        f"Return JSON with 'mark' (integer 0 to {row.total_marks}) and "
        "'justification' (a concise explanation referencing specific mark scheme descriptors)."
    )

    return system, user_parts, SCHEMA


# ============================================================================
# PARSE — extract marks from model response
# ============================================================================

def parse_fn(resp: dict) -> dict:
    """Parse the model response into {mark, justification}."""
    return parse_simple(resp)


# ============================================================================
# STRATEGY — the strategy definition returned to the harness
# ============================================================================

def get_strategy() -> Strategy:
    """Return the current experiment strategy."""
    return Strategy(
        name="autoresearch_baseline",
        description="GCSE English baseline — simple mark scheme prompt",
        subject="english",
        model=config.MODEL_DEFAULT,  # gemini-2.5-pro
        temperature=0.0,
        thinking=True,
        thinking_budget=config.THINKING_BUDGET,
        prompt_fn=prompt_fn,
        parse_fn=parse_fn,
    )
