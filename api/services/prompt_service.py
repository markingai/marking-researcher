"""Prompt text extraction and override management."""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, timezone

from ..database import get_db
from ..models import PromptField, PromptResponse
from .strategy_service import get_strategy_by_name


def get_prompt_fields(strategy_name: str) -> PromptResponse | None:
    """Extract prompt text fields from a strategy's prompt function."""
    info = get_strategy_by_name(strategy_name)
    if info is None:
        return None

    from eval_agent.strategies import build_strategies

    strategy = None
    for s in build_strategies():
        if s.name == strategy_name:
            strategy = s
            break

    if strategy is None or strategy.prompt_fn is None:
        return None

    # Extract source and parse
    fields = _extract_fields_from_source(strategy.prompt_fn)

    # Check for overrides
    overrides = _get_overrides(strategy_name)
    for f in fields:
        if f.field_path in overrides:
            f.is_overridden = True
            f.original_text = f.text
            f.text = overrides[f.field_path]

    # Get schema
    schema = None
    try:
        from eval_agent.data_loader import MarkingRow
        dummy = MarkingRow(
            row_id="PREVIEW", question_number="1", total_marks=4,
            question_text="[question text]", marking_guide="[marking guide]",
            student_answer="[student answer]", human_mark=0, subject="maths",
        )
        _, _, schema = strategy.prompt_fn(dummy)
    except Exception:
        pass

    return PromptResponse(
        strategy_name=strategy_name,
        prompt_fn_name=strategy.prompt_fn.__name__,
        module=strategy.prompt_fn.__module__,
        fields=fields,
        response_schema=schema,
    )


def _extract_fields_from_source(prompt_fn) -> list[PromptField]:
    """Use AST parsing to extract string literals from the prompt function."""
    fields: list[PromptField] = []

    try:
        source = inspect.getsource(prompt_fn)
        source = textwrap.dedent(source)
        tree = ast.parse(source)
    except Exception:
        return fields

    func_def = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_def = node
            break

    if func_def is None:
        return fields

    for node in ast.walk(func_def):
        # Find: system = "..." or system = ("..." "...")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "system":
                    text = _extract_string_value(node.value)
                    if text:
                        fields.append(PromptField(
                            field_path="system",
                            label="System Instruction",
                            text=text,
                            is_template="{row." in text or "{row[" in text,
                        ))

        # Find list construction for user_parts
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "user_parts":
                    if isinstance(node.value, ast.List):
                        for i, elt in enumerate(node.value.elts):
                            text = _extract_string_value(elt)
                            if text:
                                fields.append(PromptField(
                                    field_path=f"user_parts[{i}]",
                                    label=f"User Part {i + 1}",
                                    text=text,
                                    is_template=any(
                                        t in text for t in ["{row.", "row.", "{row["]
                                    ),
                                ))

        # Find user_parts.extend([...])
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr == "extend"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "user_parts"):
                if call.args and isinstance(call.args[0], ast.List):
                    base = len([f for f in fields if f.field_path.startswith("user_parts[")])
                    for i, elt in enumerate(call.args[0].elts):
                        text = _extract_string_value(elt)
                        if text:
                            idx = base + i
                            fields.append(PromptField(
                                field_path=f"user_parts[{idx}]",
                                label=f"User Part {idx + 1}",
                                text=text,
                                is_template=any(
                                    t in text for t in ["{row.", "row.", "{row["]
                                ),
                            ))

        # Find user_parts.append(...)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr == "append"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "user_parts"):
                if call.args:
                    text = _extract_string_value(call.args[0])
                    if text:
                        idx = len([f for f in fields if f.field_path.startswith("user_parts[")])
                        fields.append(PromptField(
                            field_path=f"user_parts[{idx}]",
                            label=f"User Part {idx + 1}",
                            text=text,
                            is_template=any(
                                t in text for t in ["{row.", "row.", "{row["]
                            ),
                        ))

    return fields


def _extract_string_value(node) -> str | None:
    """Extract a string value from an AST node (handles constants, f-strings, joins)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value

    if isinstance(node, ast.JoinedStr):
        # f-string: reconstruct with placeholders
        parts = []
        for val in node.values:
            if isinstance(val, ast.Constant):
                parts.append(str(val.value))
            elif isinstance(val, ast.FormattedValue):
                parts.append(_format_value_to_placeholder(val))
        return "".join(parts)

    # Parenthesized string concatenation: ("a" "b" "c")
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _extract_string_value(node.left)
        right = _extract_string_value(node.right)
        if left is not None and right is not None:
            return left + right

    return None


def _format_value_to_placeholder(node: ast.FormattedValue) -> str:
    """Convert an f-string FormattedValue to a readable placeholder."""
    try:
        return "{" + ast.unparse(node.value) + "}"
    except Exception:
        return "{...}"


def _get_overrides(strategy_name: str) -> dict[str, str]:
    """Get all prompt overrides for a strategy."""
    with get_db() as db:
        rows = db.execute(
            "SELECT field_path, override_text FROM prompt_overrides WHERE strategy_name=?",
            (strategy_name,),
        ).fetchall()
    return {r["field_path"]: r["override_text"] for r in rows}


def save_overrides(strategy_name: str, overrides: list[dict]) -> bool:
    """Save prompt text overrides."""
    now = datetime.now(timezone.utc).isoformat()

    # Verify strategy exists
    if get_strategy_by_name(strategy_name) is None:
        return False

    # Get current fields to capture originals
    response = get_prompt_fields(strategy_name)
    if response is None:
        return False

    originals = {f.field_path: f.original_text or f.text for f in response.fields}

    with get_db() as db:
        for override in overrides:
            fp = override.get("field_path")
            text = override.get("text")
            if not fp or text is None:
                continue
            original = originals.get(fp, "")
            db.execute(
                """INSERT INTO prompt_overrides (strategy_name, field_path, original_text, override_text, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(strategy_name, field_path)
                   DO UPDATE SET override_text=?, updated_at=?""",
                (strategy_name, fp, original, text, now, now, text, now),
            )
    return True


def delete_overrides(strategy_name: str) -> bool:
    """Delete all overrides for a strategy, resetting to defaults."""
    with get_db() as db:
        db.execute(
            "DELETE FROM prompt_overrides WHERE strategy_name=?",
            (strategy_name,),
        )
    return True
