"""Settings API router."""

import os

from fastapi import APIRouter, Depends

from ..dependencies import get_current_user
from ..models import ModelInfo, SettingsResponse

router = APIRouter(prefix="/api/settings", tags=["settings"])

# Known models and their pricing
MODELS = [
    ModelInfo(
        name="Gemini 2.5 Pro",
        model_id="gemini-2.5-pro-preview-05-06",
        provider="google",
        input_price_per_m=1.25,
        output_price_per_m=10.0,
        available=False,
    ),
    ModelInfo(
        name="Claude Sonnet 4",
        model_id="claude-sonnet-4-20250514",
        provider="anthropic",
        input_price_per_m=3.0,
        output_price_per_m=15.0,
        available=False,
    ),
    ModelInfo(
        name="Claude Opus 4",
        model_id="claude-opus-4-0-20250514",
        provider="anthropic",
        input_price_per_m=15.0,
        output_price_per_m=75.0,
        available=False,
    ),
    ModelInfo(
        name="GPT-4o",
        model_id="gpt-4o",
        provider="openai",
        input_price_per_m=2.5,
        output_price_per_m=10.0,
        available=False,
    ),
]


def _check_key(provider: str) -> bool:
    """Check if an API key is configured for a provider."""
    env_map = {
        "google": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    key = env_map.get(provider, "")
    return bool(os.environ.get(key))


@router.get("")
async def get_settings(_=Depends(get_current_user)) -> SettingsResponse:
    """Get API key status and available models. Never returns actual key values."""
    api_keys = {
        "google": _check_key("google"),
        "anthropic": _check_key("anthropic"),
        "openai": _check_key("openai"),
    }

    models = []
    for m in MODELS:
        models.append(m.model_copy(update={"available": _check_key(m.provider)}))

    return SettingsResponse(
        api_keys=api_keys,
        models=models,
        rate_limits={"max_concurrent_runs": 1},
    )
