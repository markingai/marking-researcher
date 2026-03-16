"""Subjects API router — manage built-in + custom subjects."""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from ..config import UPLOADS_DIR, MAX_UPLOAD_SIZE
from ..database import get_db
from ..dependencies import get_current_user

router = APIRouter(prefix="/api/subjects", tags=["subjects"])

# Required CSV columns (must have all of these)
REQUIRED_COLUMNS = {
    "case_id",
    "question_number",
    "question_text",
    "total_marks",
    "marking_guide",
    "student_answer",
    "human_mark",
}

# Optional columns that are recognized
OPTIONAL_COLUMNS = {
    "source_text",
    "image_url",
    "submission_file_name",
    "ai_mark",
}


def _slugify(name: str) -> str:
    """Convert display name to a valid slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug or "subject"


def _validate_csv(content: bytes) -> tuple[list[str], int, int]:
    """Validate CSV structure. Returns (columns, row_count, question_count)."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except UnicodeDecodeError:
            raise HTTPException(400, "Could not decode CSV file (try UTF-8 encoding)")

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise HTTPException(400, "CSV file appears to be empty or has no header row")

    columns = [c.strip() for c in reader.fieldnames]
    missing = REQUIRED_COLUMNS - set(columns)
    if missing:
        raise HTTPException(
            400,
            f"CSV is missing required columns: {', '.join(sorted(missing))}. "
            f"Required: {', '.join(sorted(REQUIRED_COLUMNS))}",
        )

    # Count rows and questions
    questions = set()
    row_count = 0
    valid_rows = 0
    for row in reader:
        row_count += 1
        hm = (row.get("human_mark") or "").strip()
        if hm:
            valid_rows += 1
            questions.add(row.get("question_number", "").strip())

    if valid_rows == 0:
        raise HTTPException(400, "CSV has no rows with a human_mark value")

    return columns, valid_rows, len(questions)


@router.get("")
async def list_subjects(_=Depends(get_current_user)):
    """List all subjects (built-in + custom)."""
    # Built-in subjects
    builtin = [
        {
            "slug": "maths",
            "display_name": "Maths",
            "is_builtin": True,
            "total_rows": None,  # will be filled by frontend from datasets
            "question_count": None,
            "created_at": None,
        },
        {
            "slug": "english",
            "display_name": "English",
            "is_builtin": True,
            "total_rows": None,
            "question_count": None,
            "created_at": None,
        },
    ]

    # Custom subjects from DB
    with get_db() as db:
        rows = db.execute(
            "SELECT slug, display_name, total_rows, question_count, created_at "
            "FROM subjects WHERE is_builtin = 0 ORDER BY created_at DESC"
        ).fetchall()

    custom = [
        {
            "slug": r["slug"],
            "display_name": r["display_name"],
            "is_builtin": False,
            "total_rows": r["total_rows"],
            "question_count": r["question_count"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    return {"subjects": builtin + custom}


@router.post("")
async def create_subject(
    file: UploadFile = File(...),
    display_name: str = Form(...),
    _=Depends(get_current_user),
):
    """Upload a CSV and register a new subject."""
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext != ".csv":
        raise HTTPException(400, "Only CSV files are accepted for subject data")

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(400, f"File too large ({len(content)} bytes)")

    # Validate CSV structure
    columns, row_count, question_count = _validate_csv(content)

    # Generate slug
    slug = _slugify(display_name)

    # Check for duplicate slug
    with get_db() as db:
        existing = db.execute(
            "SELECT slug FROM subjects WHERE slug = ?", (slug,)
        ).fetchone()

    if existing or slug in ("maths", "english", "all"):
        slug = f"{slug}_{uuid.uuid4().hex[:6]}"

    # Save CSV to uploads dir
    csv_filename = f"subject_{slug}.csv"
    csv_path = UPLOADS_DIR / csv_filename
    csv_path.write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()

    with get_db() as db:
        db.execute(
            """INSERT INTO subjects (slug, display_name, csv_path, total_rows, question_count, is_builtin, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (slug, display_name, str(csv_path), row_count, question_count, now),
        )

    # Register generic strategies for the new subject
    from ..services.strategy_service import refresh_dynamic_strategies
    refresh_dynamic_strategies()

    return {
        "slug": slug,
        "display_name": display_name,
        "total_rows": row_count,
        "question_count": question_count,
        "columns": columns,
    }


@router.delete("/{slug}")
async def delete_subject(slug: str, _=Depends(get_current_user)):
    """Delete a custom subject."""
    if slug in ("maths", "english"):
        raise HTTPException(400, "Cannot delete built-in subjects")

    with get_db() as db:
        row = db.execute(
            "SELECT csv_path FROM subjects WHERE slug = ? AND is_builtin = 0", (slug,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Subject '{slug}' not found")

        # Remove CSV file
        csv_path = Path(row["csv_path"])
        if csv_path.exists():
            csv_path.unlink()

        db.execute("DELETE FROM subjects WHERE slug = ?", (slug,))

    # Clear cached data and refresh strategies
    from ..services.dataset_service import clear_subject_cache
    from ..services.strategy_service import refresh_dynamic_strategies
    clear_subject_cache(slug)
    refresh_dynamic_strategies()

    return {"status": "deleted", "slug": slug}


@router.post("/{slug}/reimport")
async def reimport_subject(
    slug: str,
    file: UploadFile = File(...),
    _=Depends(get_current_user),
):
    """Re-import CSV data for an existing custom subject."""
    if slug in ("maths", "english"):
        raise HTTPException(400, "Cannot re-import built-in subjects")

    with get_db() as db:
        row = db.execute(
            "SELECT csv_path FROM subjects WHERE slug = ? AND is_builtin = 0", (slug,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Subject '{slug}' not found")

    content = await file.read()
    columns, row_count, question_count = _validate_csv(content)

    # Overwrite CSV
    csv_path = Path(row["csv_path"])
    csv_path.write_bytes(content)

    with get_db() as db:
        db.execute(
            "UPDATE subjects SET total_rows = ?, question_count = ? WHERE slug = ?",
            (row_count, question_count, slug),
        )

    # Clear cached data
    from ..services.dataset_service import clear_subject_cache
    clear_subject_cache(slug)

    return {
        "slug": slug,
        "total_rows": row_count,
        "question_count": question_count,
        "columns": columns,
    }
