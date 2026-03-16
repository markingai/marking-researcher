"""Abstract base class for LLM API clients."""

from __future__ import annotations
from abc import ABC, abstractmethod


class BaseClient(ABC):
    @abstractmethod
    def generate(
        self,
        system_instruction: str,
        user_parts: list[str | dict],
        temperature: float = 0.0,
        thinking: bool = True,
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
        thinking_level: str | None = None,
    ) -> dict:
        """Call the model and return a parsed JSON dict.

        user_parts can contain:
          - str: text content
          - dict: image data with keys {"mime_type": str, "data": str (base64)}

        On success: returns the parsed JSON with optional "_raw" key.
        On failure: returns {"error": "<message>", "raw": "<text>"}.
        """
        ...
