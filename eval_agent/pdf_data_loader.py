"""PDF data loader — maps PDF submissions to CSV ground truth.

Loads student submission PDFs, matches them to the CSV dataset via
submission_file_name, and enriches MarkingRow with PDF page images.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .data_loader import MarkingRow
from .pdf_loader import PDFDocument, PDFPage, load_pdf, load_submission_pdfs


@dataclass
class PDFMarkingRow(MarkingRow):
    """MarkingRow enriched with PDF page images for multimodal marking."""
    submission_pdf: PDFDocument | None = None
    submission_file_name: str = ""


def load_pdf_maths(
    pdf_dir: Path | str,
    csv_path: Path | str | None = None,
    questions: set[str] | None = None,
) -> list[PDFMarkingRow]:
    """Load maths data by matching PDFs to CSV ground truth.

    Args:
        pdf_dir: Directory containing submission PDFs.
        csv_path: Path to the maths CSV. Defaults to config.MATHS_CSV.
        questions: Optional set of question numbers to include.
                   If None, includes ALL questions (including Q32).

    Returns:
        List of PDFMarkingRow with PDF pages attached.
    """
    csv_path = Path(csv_path) if csv_path else config.MATHS_CSV
    pdf_dir = Path(pdf_dir)

    # Load all submission PDFs from the directory
    print(f"\nLoading submission PDFs from {pdf_dir}...")
    submissions = load_submission_pdfs(pdf_dir)
    print(f"  Found {len(submissions)} submissions: {list(submissions.keys())}")

    # Load rubric if available
    rubric_path = pdf_dir / "Algebra_Rubric.pdf"
    rubric_pdf = None
    if rubric_path.exists():
        print(f"  Loading rubric: {rubric_path.name}")
        rubric_pdf = load_pdf(rubric_path)

    # Read CSV and match to loaded PDFs
    rows = []
    matched = 0
    skipped = 0

    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            sub_name = r.get("submission_file_name", "").strip()
            if sub_name not in submissions:
                continue

            qn = r["question_number"]
            if questions is not None and qn not in questions:
                continue

            hm = r.get("human_mark", "").strip()
            if not hm:
                skipped += 1
                continue

            ai = r.get("ai_mark", "").strip()

            row = PDFMarkingRow(
                row_id=r["case_id"],
                subject="maths",
                question_number=qn,
                question_text=r.get("question_text", ""),
                total_marks=int(r["total_marks"]),
                marking_guide=r["marking_guide"],
                student_answer=r["student_answer"],
                human_mark=float(hm),
                existing_ai_mark=float(ai) if ai else None,
                image_url=r.get("image_url", "").strip() or None,
                submission_pdf=submissions[sub_name],
                submission_file_name=sub_name,
            )
            rows.append(row)
            matched += 1

    print(f"  Matched {matched} rows across {len(submissions)} students")
    if skipped:
        print(f"  Skipped {skipped} rows (no human_mark)")

    return rows
