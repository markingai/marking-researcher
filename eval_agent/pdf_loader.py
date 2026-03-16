"""PDF loading and page rendering for multimodal marking.

Uses PyMuPDF (fitz) to render PDF pages as JPEG images and extract text.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PDFPage:
    """A single rendered page from a PDF."""
    page_num: int          # 1-based
    image_bytes: bytes     # JPEG bytes
    image_b64: str         # base64-encoded JPEG for API calls
    text: str              # extracted text (may be empty for handwritten/scanned)
    width: int = 0
    height: int = 0


@dataclass
class PDFDocument:
    """A loaded PDF with all pages rendered."""
    path: Path
    pages: list[PDFPage] = field(default_factory=list)
    total_pages: int = 0

    @property
    def name(self) -> str:
        return self.path.stem


def load_pdf(
    path: Path | str,
    dpi: int = 150,
    jpeg_quality: int = 85,
) -> PDFDocument:
    """Load a PDF and render all pages as JPEG images.

    Args:
        path: Path to the PDF file.
        dpi: Resolution for rendering (150 = good balance of quality vs size).
        jpeg_quality: JPEG compression quality (85 = visually lossless).

    Returns:
        PDFDocument with all pages rendered.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {path}")

    doc = fitz.open(str(path))
    pages = []

    zoom = dpi / 72.0  # 72 DPI is the PDF default
    matrix = fitz.Matrix(zoom, zoom)

    for i in range(len(doc)):
        page = doc[i]

        # Render page to pixmap (image)
        pix = page.get_pixmap(matrix=matrix)
        image_bytes = pix.tobytes("jpeg", jpg_quality=jpeg_quality)
        image_b64 = base64.b64encode(image_bytes).decode("ascii")

        # Extract text
        text = page.get_text("text").strip()

        pages.append(PDFPage(
            page_num=i + 1,
            image_bytes=image_bytes,
            image_b64=image_b64,
            text=text,
            width=pix.width,
            height=pix.height,
        ))

    doc.close()

    return PDFDocument(
        path=path,
        pages=pages,
        total_pages=len(pages),
    )


def load_submission_pdfs(directory: Path | str) -> dict[str, PDFDocument]:
    """Load all submission PDFs from a directory.

    Returns a dict mapping student_id (extracted from filename) to PDFDocument.
    Filenames are expected to contain the student/case ID, e.g.:
        326540_submission.pdf → student_id = "326540"
        626662_sub.pdf → student_id = "626662"
    """
    directory = Path(directory)
    submissions = {}

    for pdf_path in sorted(directory.glob("*.pdf")):
        # Skip rubric files
        if "rubric" in pdf_path.stem.lower():
            continue

        # Extract student ID: take the numeric prefix before underscore
        stem = pdf_path.stem
        parts = stem.split("_")
        student_id = parts[0] if parts else stem

        # Only use if the ID looks numeric (submission files)
        if student_id.isdigit():
            print(f"  Loading PDF: {pdf_path.name} (student_id={student_id})")
            submissions[student_id] = load_pdf(pdf_path)

    return submissions
