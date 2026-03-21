"""Autoresearch router — start, monitor, and review strategy research sessions."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..dependencies import get_current_user
from ..models import (
    StartAutoresearchRequest,
    AutoresearchSessionResponse,
    AutoresearchExperimentResponse,
    AutoresearchSessionDetailResponse,
)
from ..database import get_db
from ..services.autoresearch_service import autoresearch_manager

router = APIRouter(prefix="/api/autoresearch", tags=["autoresearch"])


def _row_to_session(row) -> AutoresearchSessionResponse:
    return AutoresearchSessionResponse(
        id=row["id"],
        status=row["status"],
        budget_usd=row["budget_usd"],
        spent_usd=row["spent_usd"],
        model=row["model"],
        sample_size=row["sample_size"],
        experiments_run=row["experiments_run"],
        best_exact_match=row["best_exact_match"],
        best_experiment_id=row["best_experiment_id"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
    )


def _row_to_experiment(row) -> AutoresearchExperimentResponse:
    per_q = None
    if row["per_question_json"]:
        try:
            per_q = json.loads(row["per_question_json"])
        except (json.JSONDecodeError, TypeError):
            pass

    return AutoresearchExperimentResponse(
        id=row["id"],
        session_id=row["session_id"],
        description=row["description"],
        strategy_name=row["strategy_name"],
        exact_match=row["exact_match"],
        within_1=row["within_1"],
        mae=row["mae"],
        bias=row["bias"],
        cost_usd=row["cost_usd"],
        n=row["n"],
        model=row["model"],
        kept=bool(row["kept"]),
        per_question=per_q,
        created_at=row["created_at"],
    )


@router.post("/sessions")
async def start_session(
    req: StartAutoresearchRequest,
    _user: dict = Depends(get_current_user),
):
    if autoresearch_manager.is_busy:
        raise HTTPException(status_code=409, detail="A research session is already running")

    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_db() as db:
        db.execute(
            """INSERT INTO autoresearch_sessions
            (id, status, budget_usd, model, sample_size, created_at)
            VALUES (?, 'running', ?, ?, ?, ?)""",
            (session_id, req.budget_usd, req.model, req.sample_size, now),
        )

    autoresearch_manager.start_session(
        session_id=session_id,
        budget_usd=req.budget_usd,
        sample_size=req.sample_size,
        model=req.model,
    )

    return {"session_id": session_id, "status": "running"}


@router.get("/sessions")
async def list_sessions(
    _user: dict = Depends(get_current_user),
):
    with get_db() as db:
        rows = db.execute(
            "SELECT * FROM autoresearch_sessions ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_session(r) for r in rows]


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    _user: dict = Depends(get_current_user),
):
    with get_db() as db:
        session_row = db.execute(
            "SELECT * FROM autoresearch_sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not session_row:
            raise HTTPException(status_code=404, detail="Session not found")

        exp_rows = db.execute(
            "SELECT * FROM autoresearch_experiments WHERE session_id=? ORDER BY created_at",
            (session_id,),
        ).fetchall()

    return AutoresearchSessionDetailResponse(
        session=_row_to_session(session_row),
        experiments=[_row_to_experiment(r) for r in exp_rows],
    )


@router.post("/sessions/{session_id}/stop")
async def stop_session(
    session_id: str,
    _user: dict = Depends(get_current_user),
):
    ctx = autoresearch_manager.get_context(session_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Session not active")
    autoresearch_manager.stop_session(session_id)
    return {"status": "stopping"}


@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    token: str = Query(...),
):
    """SSE endpoint for live session progress."""
    from ..auth import verify_token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")

    ctx = autoresearch_manager.get_context(session_id)
    if not ctx:
        # Session already finished
        with get_db() as db:
            row = db.execute(
                "SELECT status FROM autoresearch_sessions WHERE id=?", (session_id,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Session not found")

        async def done_stream():
            yield f"data: {json.dumps({'event': 'session_complete', 'data': {'session_id': session_id, 'status': row['status']}})}\n\n"

        return StreamingResponse(done_stream(), media_type="text/event-stream")

    queue = ctx.add_queue()

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event["event"] in ("session_complete", "error"):
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'keepalive', 'data': {}})}\n\n"
        finally:
            ctx.remove_queue(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
