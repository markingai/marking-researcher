"""Generic marking prompts for any subject.

These prompts work with the standard MarkingRow fields (question_text,
marking_guide, student_answer, total_marks) and require no subject-specific
knowledge. They are auto-attached to dynamically uploaded subjects.
"""

from __future__ import annotations
from ..data_loader import MarkingRow


# --- Shared schemas ---

SIMPLE_SCHEMA = {
    "type": "object",
    "required": ["mark", "justification"],
    "properties": {
        "mark": {"type": "integer"},
        "justification": {"type": "string"},
    },
}

CRITERION_SCHEMA = {
    "type": "object",
    "required": ["criteria", "total_mark"],
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["criterion", "marks_awarded", "max_marks", "reason"],
                "properties": {
                    "criterion": {"type": "string"},
                    "marks_awarded": {"type": "integer"},
                    "max_marks": {"type": "integer"},
                    "reason": {"type": "string"},
                },
            },
        },
        "total_mark": {"type": "integer"},
    },
}


# --- Strategy 1: Generic Baseline ---

def generic_baseline(row: MarkingRow) -> tuple[str, list[str], dict]:
    """Universal baseline prompt for any subject."""
    system = (
        "You are an expert examiner. Mark strictly and only against the provided "
        "marking guide. Do not infer criteria beyond the guide. Award marks "
        "conservatively and never above the question total. "
        "If the student answer is blank or not attempted, give 0 marks."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"Mark this answer out of {row.total_marks}. "
            "Compare the student answer directly against the marking guide. "
            "Return a JSON object with 'mark' (integer 0 to "
            f"{row.total_marks}) and 'justification' (brief explanation)."
        ),
    ]
    return system, user_parts, SIMPLE_SCHEMA


# --- Strategy 2: Generic Criterion Decomposed ---

def generic_criterion_decomposed(row: MarkingRow) -> tuple[str, list[str], dict]:
    """Universal criterion-decomposed prompt for any subject."""
    system = (
        "You are an expert examiner. You must mark each criterion from the "
        "marking guide independently before summing for a total. "
        "Be strict — only award marks for criteria the student clearly meets. "
        "Never exceed the total marks for the question."
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks total):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"Break the marking guide into individual criteria. "
            f"For each criterion, state the criterion name, the maximum marks "
            f"available, the marks you award, and a brief reason.\n\n"
            f"Then sum the criteria marks for the total (0 to {row.total_marks}).\n\n"
            "Return a JSON object with:\n"
            "- 'criteria': array of {criterion, marks_awarded, max_marks, reason}\n"
            "- 'total_mark': integer (sum of marks_awarded, capped at "
            f"{row.total_marks})"
        ),
    ]
    return system, user_parts, CRITERION_SCHEMA


# --- Strategy 3: Generic Conservative ---

def generic_conservative(row: MarkingRow) -> tuple[str, list[str], dict]:
    """Universal conservative-bias prompt for any subject."""
    system = (
        "You are a strict, conservative examiner. Your priority is accuracy "
        "and avoiding over-marking. When in doubt, do NOT award the mark. "
        "Only award marks when the student's answer clearly and unambiguously "
        "meets the criterion specified in the marking guide.\n\n"
        "Rules:\n"
        "- Partial answers get partial marks only if the marking guide allows it\n"
        "- Implied understanding does NOT count — the student must demonstrate it explicitly\n"
        "- If the student answer is blank or not attempted, give 0 marks\n"
        "- Never exceed the question total"
    )
    user_parts = [
        f"Question {row.question_number} ({row.total_marks} marks):\n{row.question_text}",
        f"Marking guide:\n{row.marking_guide}",
        f"Student answer:\n{row.student_answer}",
        (
            f"Mark this answer out of {row.total_marks}. "
            "Apply a conservative approach — when in doubt, withhold the mark. "
            "Return a JSON object with 'mark' (integer 0 to "
            f"{row.total_marks}) and 'justification' (brief explanation)."
        ),
    ]
    return system, user_parts, SIMPLE_SCHEMA
