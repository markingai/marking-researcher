"""Dataset service — wraps eval_agent data loaders."""

from __future__ import annotations

import csv
import sys
import os
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from eval_agent.data_loader import load_maths, load_english, MarkingRow
from eval_agent import config as eval_config

_maths_cache: list[MarkingRow] | None = None
_maths_all_cache: list[MarkingRow] | None = None  # includes Q32
_english_cache: list[MarkingRow] | None = None
_custom_cache: dict[str, list[MarkingRow]] = {}  # slug -> rows


def get_maths_data() -> list[MarkingRow]:
    global _maths_cache
    if _maths_cache is None:
        _maths_cache = load_maths()
    return _maths_cache


def get_maths_data_all_questions() -> list[MarkingRow]:
    """Load maths data WITHOUT excluding Q32 — for PDF mode."""
    global _maths_all_cache
    if _maths_all_cache is None:
        saved = eval_config.EXCLUDED_QUESTIONS
        eval_config.EXCLUDED_QUESTIONS = set()
        _maths_all_cache = load_maths()
        eval_config.EXCLUDED_QUESTIONS = saved
    return _maths_all_cache


def get_english_data() -> list[MarkingRow]:
    global _english_cache
    if _english_cache is None:
        _english_cache = load_english()
    return _english_cache


def load_custom_subject(slug: str, csv_path: str) -> list[MarkingRow]:
    """Load a custom subject CSV into MarkingRow objects."""
    rows = []
    path = Path(csv_path)
    encoding = "utf-8"
    try:
        path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        encoding = "latin-1"

    with open(path, "r", encoding=encoding) as f:
        reader = csv.DictReader(f)
        for r in reader:
            hm = (r.get("human_mark") or "").strip()
            if not hm:
                continue
            ai = (r.get("ai_mark") or "").strip()
            rows.append(MarkingRow(
                row_id=r["case_id"],
                subject=slug,
                question_number=r["question_number"],
                question_text=r.get("question_text", ""),
                total_marks=int(r["total_marks"]),
                marking_guide=r["marking_guide"],
                student_answer=r["student_answer"],
                human_mark=float(hm),
                existing_ai_mark=float(ai) if ai else None,
                source_text=r.get("source_text", "") or None,
                image_url=r.get("image_url", "").strip() or None,
            ))
    return rows


def get_custom_subject_data(slug: str) -> list[MarkingRow] | None:
    """Get data for a custom subject (cached)."""
    if slug in _custom_cache:
        return _custom_cache[slug]

    # Look up the subject in the DB
    from ..database import get_db
    with get_db() as db:
        row = db.execute(
            "SELECT csv_path FROM subjects WHERE slug = ? AND is_builtin = 0",
            (slug,),
        ).fetchone()

    if not row:
        return None

    csv_path = row["csv_path"]
    if not Path(csv_path).exists():
        return None

    data = load_custom_subject(slug, csv_path)
    _custom_cache[slug] = data
    return data


def clear_subject_cache(slug: str):
    """Clear cached data for a custom subject (after re-import)."""
    _custom_cache.pop(slug, None)


def get_custom_subjects() -> list[dict]:
    """Get list of custom subjects from DB."""
    from ..database import get_db
    with get_db() as db:
        rows = db.execute(
            "SELECT slug, display_name, csv_path, total_rows, question_count "
            "FROM subjects WHERE is_builtin = 0 ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_dataset_info(subject: str, input_mode: str = "csv") -> dict:
    """Get dataset info for a subject.

    When input_mode is 'pdf', includes Q32 for maths (PDFs can handle visual content).
    """
    if subject == "maths":
        rows = get_maths_data_all_questions() if input_mode == "pdf" else get_maths_data()
    elif subject == "english":
        rows = get_english_data()
    else:
        # Custom subject
        rows = get_custom_subject_data(subject)
        if rows is None:
            return {
                "subject": subject,
                "source": "csv",
                "total_rows": 0,
                "questions": [],
            }

    questions = _build_question_info(rows)
    return {
        "subject": subject,
        "source": input_mode if subject == "maths" else "csv",
        "total_rows": len(rows),
        "questions": questions,
    }


def get_questions(subject: str, input_mode: str = "csv") -> list[dict]:
    """Get available questions for a subject."""
    if subject == "maths":
        rows = get_maths_data_all_questions() if input_mode == "pdf" else get_maths_data()
    elif subject == "english":
        rows = get_english_data()
    else:
        rows = get_custom_subject_data(subject) or []
    return _build_question_info(rows)


def _build_question_info(rows: list[MarkingRow]) -> list[dict]:
    """Build question info list from rows."""
    by_q: dict[str, list[MarkingRow]] = {}
    for r in rows:
        by_q.setdefault(r.question_number, []).append(r)

    questions = []
    for qn in sorted(by_q.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        qrows = by_q[qn]
        preview = qrows[0].question_text[:150] if qrows[0].question_text else ""
        questions.append({
            "number": qn,
            "total_marks": qrows[0].total_marks,
            "sample_count": len(qrows),
            "question_text_preview": preview,
        })
    return questions


def check_pdf_availability() -> tuple[bool, int]:
    """Check if PDF submissions are available."""
    pdf_dir = eval_config.PROJECT_ROOT / "Maths"
    if not pdf_dir.exists():
        return False, 0
    pdfs = list(pdf_dir.glob("*_submission*.pdf")) + list(pdf_dir.glob("*_sub.pdf"))
    return len(pdfs) > 0, len(pdfs)
