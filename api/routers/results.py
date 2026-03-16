"""Results API router."""

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_current_user
from ..services import results_service

router = APIRouter(prefix="/api/results", tags=["results"])


@router.get("/{run_id}")
async def get_results_summary(run_id: str, _=Depends(get_current_user)):
    """Get aggregated strategy metrics for a run."""
    return results_service.get_run_results_summary(run_id)


@router.get("/{run_id}/detail")
async def get_results_detail(
    run_id: str,
    strategy: str | None = Query(None),
    question: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    _=Depends(get_current_user),
):
    """Get detailed per-answer results for a run."""
    return results_service.get_run_results_detail(
        run_id, strategy=strategy, question=question,
        page=page, per_page=per_page,
    )
