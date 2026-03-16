"""Prompts API router."""

from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import get_current_user
from ..models import PromptOverrideRequest
from ..services import prompt_service

router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("/{strategy_name}")
async def get_prompt(strategy_name: str, _=Depends(get_current_user)):
    """Get extracted prompt text fields for a strategy."""
    result = prompt_service.get_prompt_fields(strategy_name)
    if result is None:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return result


@router.put("/{strategy_name}")
async def save_prompt_overrides(
    strategy_name: str,
    req: PromptOverrideRequest,
    _=Depends(get_current_user),
):
    """Save prompt text overrides."""
    ok = prompt_service.save_overrides(strategy_name, req.overrides)
    if not ok:
        raise HTTPException(status_code=404, detail="Strategy not found")
    return {"status": "saved"}


@router.delete("/{strategy_name}/overrides")
async def delete_prompt_overrides(strategy_name: str, _=Depends(get_current_user)):
    """Reset prompt to code defaults."""
    prompt_service.delete_overrides(strategy_name)
    return {"status": "reset"}
