"""Runs router — create, list, monitor, cancel eval runs."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..dependencies import get_current_user
from ..models import (
    CreateRunRequest, RunSummary, RunDetail, RunStrategyStatus,
    RunsListResponse,
)
from ..database import get_db
from ..services.run_manager import run_manager
from ..services.strategy_service import get_all_strategies

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("")
async def create_run(
    req: CreateRunRequest,
    _user: dict = Depends(get_current_user),
):
    if run_manager.is_busy:
        raise HTTPException(status_code=409, detail="A run is already in progress")

    # Validate strategies exist
    all_strategy_names = {s.name for s in get_all_strategies()}
    invalid = [s for s in req.strategies if s not in all_strategy_names]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Unknown strategies: {invalid}")

    run_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    with get_db() as db:
        db.execute(
            """INSERT INTO runs
            (id, name, status, subject, input_mode, model_override,
             sample_size_maths, sample_size_english, random_seed, created_at,
             total_strategies)
            VALUES (?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)""",
            (run_id, req.name, req.subject, req.input_mode, req.model_override,
             req.sample_size if req.subject in ("maths", "all") else 0,
             req.sample_size if req.subject in ("english", "all") else 0,
             req.random_seed, now, len(req.strategies)),
        )
        for s_name in req.strategies:
            db.execute(
                "INSERT INTO run_strategies (run_id, strategy_name) VALUES (?, ?)",
                (run_id, s_name),
            )
        if req.questions:
            for qn in req.questions:
                db.execute(
                    "INSERT INTO run_questions (run_id, question_number) VALUES (?, ?)",
                    (run_id, qn),
                )

    # Start background execution
    run_manager.start_run(
        run_id=run_id,
        subject=req.subject,
        input_mode=req.input_mode,
        strategy_names=req.strategies,
        questions=req.questions,
        sample_size=req.sample_size,
        random_seed=req.random_seed,
        model_override=req.model_override,
    )

    return {"run_id": run_id, "status": "pending"}


@router.get("")
async def list_runs(
    status: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
):
    with get_db() as db:
        where = ""
        params: list = []
        if status:
            where = "WHERE status=?"
            params.append(status)

        rows = db.execute(
            f"SELECT * FROM runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

        total = db.execute(
            f"SELECT COUNT(*) FROM runs {where}", params
        ).fetchone()[0]

    return RunsListResponse(
        runs=[_row_to_summary(r) for r in rows],
        total=total,
    )


@router.get("/{run_id}")
async def get_run(
    run_id: str,
    _user: dict = Depends(get_current_user),
):
    with get_db() as db:
        row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")

        strategies = db.execute(
            "SELECT * FROM run_strategies WHERE run_id=? ORDER BY strategy_name",
            (run_id,),
        ).fetchall()

        questions = db.execute(
            "SELECT question_number FROM run_questions WHERE run_id=?",
            (run_id,),
        ).fetchall()

    summary = _row_to_summary(row)
    return RunDetail(
        **summary.model_dump(),
        strategies=[
            RunStrategyStatus(
                strategy_name=s["strategy_name"],
                status=s["status"],
                rows_total=s["rows_total"],
                rows_completed=s["rows_completed"],
                errors=s["errors"],
                cost_usd=s["cost_usd"],
            )
            for s in strategies
        ],
        questions=[q["question_number"] for q in questions],
    )


@router.get("/{run_id}/events")
async def run_events(
    run_id: str,
    token: str = Query(...),
):
    """SSE endpoint for live run progress. Accepts JWT via ?token= query param."""
    from ..auth import verify_token
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Invalid token")
    ctx = run_manager.get_context(run_id)
    if not ctx:
        # Run already finished — send a single complete event
        with get_db() as db:
            row = db.execute("SELECT status FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Run not found")

        async def done_stream():
            import json
            yield f"data: {json.dumps({'event': 'run_complete', 'data': {'run_id': run_id, 'status': row['status']}})}\n\n"

        return StreamingResponse(done_stream(), media_type="text/event-stream")

    queue = ctx.add_queue()

    async def event_stream():
        import json
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event["event"] in ("run_complete", "error"):
                        break
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'event': 'keepalive', 'data': {}})}\n\n"
        finally:
            ctx.remove_queue(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    _user: dict = Depends(get_current_user),
):
    ctx = run_manager.get_context(run_id)
    if not ctx:
        raise HTTPException(status_code=404, detail="Run not active")
    run_manager.cancel_run(run_id)
    return {"status": "cancelling"}


def _row_to_summary(row) -> RunSummary:
    return RunSummary(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        subject=row["subject"],
        input_mode=row["input_mode"],
        model_override=row["model_override"],
        strategies_count=row["total_strategies"],
        total_rows=row["total_rows"],
        completed_rows=row["completed_rows"],
        total_cost_usd=row["total_cost_usd"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error_message=row["error_message"],
    )
