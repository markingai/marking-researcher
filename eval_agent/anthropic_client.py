"""Anthropic (Claude) API client.

Uses the Messages API with tool_use for structured JSON output.
"""

import json
import time
import threading
import requests

from . import config
from .base_client import BaseClient


class AnthropicClient(BaseClient):
    # Class-level rate limiter (shared across all Claude instances)
    _rate_lock = threading.Lock()
    _last_call_time = 0.0

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        self.model = model or config.MODEL_CLAUDE
        self._min_interval = 60.0 / config.ANTHROPIC_CALLS_PER_MINUTE
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _rate_limit(self):
        with AnthropicClient._rate_lock:
            elapsed = time.time() - AnthropicClient._last_call_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            AnthropicClient._last_call_time = time.time()

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
        """Call Claude Messages API and return parsed JSON dict."""
        url = f"{config.ANTHROPIC_BASE_URL}/messages"

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        # Build content blocks: text strings and image dicts
        has_images = any(isinstance(p, dict) for p in user_parts)
        if has_images:
            content_blocks = []
            for part in user_parts:
                if isinstance(part, str):
                    content_blocks.append({"type": "text", "text": part})
                elif isinstance(part, dict) and "data" in part:
                    content_blocks.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": part.get("mime_type", "image/jpeg"),
                            "data": part["data"],
                        },
                    })
            user_content = content_blocks
        else:
            user_content = "\n\n".join(user_parts)

        body: dict = {
            "model": self.model,
            "max_tokens": 8192,
            "system": system_instruction,
            "messages": [
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
        }

        # Use tool_use for structured output if schema provided
        if response_schema:
            tool_def = {
                "name": "mark_response",
                "description": "Return the structured marking result",
                "input_schema": response_schema,
            }
            body["tools"] = [tool_def]
            body["tool_choice"] = {"type": "tool", "name": "mark_response"}

        # Extended thinking
        if thinking:
            budget = thinking_budget if thinking_budget is not None else config.THINKING_BUDGET
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
            # Extended thinking requires temperature = 1 for Claude
            body["temperature"] = 1.0

        session = self._get_session()

        for attempt in range(config.RETRY_MAX):
            self._rate_limit()
            try:
                resp = session.post(
                    url,
                    json=body,
                    headers=headers,
                    timeout=config.REQUEST_TIMEOUT,
                )

                if resp.status_code == 429:
                    wait = config.RETRY_BACKOFF ** (attempt + 1) * 10
                    print(f"  [Claude] Rate limited. Waiting {wait:.0f}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = config.RETRY_BACKOFF ** (attempt + 1) * 5
                    print(f"  [Claude] Server error {resp.status_code}. Retrying in {wait:.0f}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code == 400:
                    error_data = resp.json()
                    error_msg = error_data.get("error", {}).get("message", resp.text)
                    return {"error": f"Bad request: {error_msg}", "raw": resp.text}

                resp.raise_for_status()
                data = resp.json()
                parsed = self._parse_response(data)
                # Attach usage metadata
                usage = data.get("usage", {})
                parsed["_usage"] = {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "thinking_tokens": 0,  # Claude doesn't separate thinking tokens
                    "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
                    "model": self.model,
                }
                return parsed

            except requests.exceptions.Timeout:
                wait = config.RETRY_BACKOFF ** (attempt + 1) * 5
                print(f"  [Claude] Timeout. Retrying in {wait:.0f}s...")
                time.sleep(wait)
                continue
            except requests.exceptions.RequestException as e:
                if attempt == config.RETRY_MAX - 1:
                    return {"error": str(e), "raw": ""}
                wait = config.RETRY_BACKOFF ** (attempt + 1) * 3
                time.sleep(wait)

        return {"error": "Max retries exceeded", "raw": ""}

    def _parse_response(self, data: dict) -> dict:
        """Extract tool_use result from Claude response."""
        content = data.get("content", [])

        # Find the tool_use block
        for block in content:
            if block.get("type") == "tool_use":
                result = block.get("input", {})
                result["_raw"] = json.dumps(result)
                return result

        # Fallback: try to find text content and parse as JSON
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "")
                try:
                    parsed = json.loads(text)
                    parsed["_raw"] = text
                    return parsed
                except json.JSONDecodeError:
                    return {"error": f"No tool_use block, text not JSON: {text[:200]}", "raw": text}

        stop_reason = data.get("stop_reason", "unknown")
        return {"error": f"No usable content. stop_reason={stop_reason}", "raw": str(data)}
