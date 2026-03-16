"""Uploads API router."""

from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from ..config import UPLOADS_DIR, MAX_UPLOAD_SIZE, ALLOWED_UPLOAD_TYPES
from ..database import get_db
from ..dependencies import get_current_user

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    subject: str | None = None,
    _=Depends(get_current_user),
):
    """Upload a PDF or CSV file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File type {ext} not allowed. Allowed: {ALLOWED_UPLOAD_TYPES}",
        )

    # Read and check size
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(content)} bytes). Max: {MAX_UPLOAD_SIZE}",
        )

    # Save
    upload_id = str(uuid.uuid4())
    storage_name = f"{upload_id}{ext}"
    storage_path = UPLOADS_DIR / storage_name
    storage_path.write_bytes(content)

    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        db.execute(
            """INSERT INTO uploads (id, filename, file_type, subject, mime_type, file_size, storage_path, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (upload_id, file.filename, ext.lstrip("."), subject,
             file.content_type, len(content), str(storage_path), now),
        )

    return {
        "id": upload_id,
        "filename": file.filename,
        "file_type": ext.lstrip("."),
        "size": len(content),
    }


@router.get("")
async def list_uploads(_=Depends(get_current_user)):
    """List uploaded files."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, filename, file_type, subject, file_size, uploaded_at FROM uploads ORDER BY uploaded_at DESC"
        ).fetchall()

    return {
        "uploads": [
            {
                "id": r["id"],
                "filename": r["filename"],
                "file_type": r["file_type"],
                "subject": r["subject"],
                "file_size": r["file_size"],
                "uploaded_at": r["uploaded_at"],
            }
            for r in rows
        ]
    }
