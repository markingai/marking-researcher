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
        report_md=row["report_md"] if "report_md" in row.keys() else None,
        session_number=row["session_number"] if "session_number" in row.keys() else None,
        parent_session_id=row["parent_session_id"] if "parent_session_id" in row.keys() else None,
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
        prompt_text=row["prompt_text"] if "prompt_text" in row.keys() else None,
        config_json=row["config_json"] if "config_json" in row.keys() else None,
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
        # Auto-increment session number
        row = db.execute("SELECT MAX(session_number) as max_num FROM autoresearch_sessions").fetchone()
        session_number = (row["max_num"] or 0) + 1 if row and row["max_num"] is not None else 1

        # Find parent session (most recent completed session with recommendations)
        parent_row = db.execute(
            """SELECT s.id FROM autoresearch_sessions s
            JOIN autoresearch_recommendations r ON r.source_session_id = s.id
            WHERE r.consumed_by_session_id IS NULL
            ORDER BY s.created_at DESC LIMIT 1"""
        ).fetchone()
        parent_id = parent_row["id"] if parent_row else None

        db.execute(
            """INSERT INTO autoresearch_sessions
            (id, status, budget_usd, model, sample_size, session_number, parent_session_id, created_at)
            VALUES (?, 'running', ?, ?, ?, ?, ?, ?)""",
            (session_id, req.budget_usd, req.model, req.sample_size, session_number, parent_id, now),
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


@router.get("/leaderboard")
async def get_leaderboard(
    _user: dict = Depends(get_current_user),
):
    """All-time strategy rankings aggregated across sessions."""
    with get_db() as db:
        rows = db.execute("""
            SELECT strategy_name,
                   MAX(description) as description,
                   COUNT(*) as times_tested,
                   AVG(exact_match) as avg_exact_match,
                   AVG(within_1) as avg_within_1,
                   AVG(mae) as avg_mae,
                   AVG(bias) as avg_bias,
                   AVG(cost_usd) as avg_cost_usd,
                   MAX(exact_match) as best_exact_match,
                   MIN(created_at) as first_tested,
                   MAX(created_at) as last_tested
            FROM autoresearch_experiments
            WHERE exact_match IS NOT NULL
            GROUP BY strategy_name
            ORDER BY MAX(exact_match) DESC
        """).fetchall()
    return [dict(r) for r in rows]


@router.get("/leaderboard/timeline")
async def get_timeline(
    _user: dict = Depends(get_current_user),
):
    """Best exact_match achieved over time (per session)."""
    with get_db() as db:
        rows = db.execute("""
            SELECT s.id as session_id,
                   s.created_at,
                   s.best_exact_match,
                   s.experiments_run,
                   s.spent_usd,
                   s.session_number
            FROM autoresearch_sessions s
            WHERE s.status IN ('completed', 'stopped')
            ORDER BY s.created_at
        """).fetchall()
    return [dict(r) for r in rows]
