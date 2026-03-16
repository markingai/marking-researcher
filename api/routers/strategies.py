"""Strategies router."""

from fastapi import APIRouter, Depends, Query

from ..dependencies import get_current_user
from ..models import StrategiesResponse, StrategyInfo
from ..services.strategy_service import get_all_strategies, get_strategy_info

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("", response_model=StrategiesResponse)
async def list_strategies(
    subject: str | None = Query(None),
    phase: int | None = Query(None),
    _user: dict = Depends(get_current_user),
):
    strategies = get_all_strategies()
    infos = [get_strategy_info(s) for s in strategies]

    if subject:
        infos = [i for i in infos if i["subject"] == subject]
    if phase is not None:
        infos = [i for i in infos if i["phase"] == phase]

    return StrategiesResponse(
        strategies=[StrategyInfo(**i) for i in infos]
    )
