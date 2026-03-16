"""OpenAI (GPT) API client.

Uses Chat Completions API with structured JSON output (strict mode).
"""

import json
import time
import threading
import requests

from . import config
from .base_client import BaseClient


def _openai_strict_schema(schema: dict) -> dict:
    """Recursively add additionalProperties: false to all object types.

    OpenAI's strict mode requires this on every object in the schema.
    """
    schema = dict(schema)  # shallow copy

    if schema.get("type") == "object":
        schema["additionalProperties"] = False
        if "properties" in schema:
            schema["properties"] = {
                k: _openai_strict_schema(v)
                for k, v in schema["properties"].items()
            }

    if schema.get("type") == "array" and "items" in schema:
        schema["items"] = _openai_strict_schema(schema["items"])

    return schema


class OpenAIClient(BaseClient):
    # Class-level rate limiter (shared across all OpenAI instances)
    _rate_lock = threading.Lock()
    _last_call_time = 0.0

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.OPENAI_API_KEY
        self.model = model or config.MODEL_GPT
        self._min_interval = 60.0 / config.OPENAI_CALLS_PER_MINUTE
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _rate_limit(self):
        with OpenAIClient._rate_lock:
            elapsed = time.time() - OpenAIClient._last_call_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            OpenAIClient._last_call_time = time.time()

    def generate(
        self,
        system_instruction: str,
        user_parts: list[str],
        temperature: float = 0.0,
        thinking: bool = True,
        thinking_budget: int | None = None,
        response_schema: dict | None = None,
        thinking_level: str | None = None,
    ) -> dict:
        """Call OpenAI Chat Completions API and return parsed JSON dict."""
        url = f"{config.OPENAI_BASE_URL}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Join user parts into a single message
        user_content = "\n\n".join(user_parts)

        # Build system message with optional thinking instruction
        system_content = system_instruction
        if thinking:
            system_content += (
                "\n\nBefore answering, think step by step through your reasoning. "
                "Then provide your final structured response."
            )

        body: dict = {
            "model": self.model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
        }

        # Structured JSON output
        if response_schema:
            strict_schema = _openai_strict_schema(response_schema)
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "mark_response",
                    "strict": True,
                    "schema": strict_schema,
                },
            }

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
                    print(f"  [GPT] Rate limited. Waiting {wait:.0f}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = config.RETRY_BACKOFF ** (attempt + 1) * 5
                    print(f"  [GPT] Server error {resp.status_code}. Retrying in {wait:.0f}s...")
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
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "output_tokens": usage.get("completion_tokens", 0),
                    "thinking_tokens": 0,
                    "total_tokens": usage.get("total_tokens", 0),
                    "model": self.model,
                }
                return parsed

            except requests.exceptions.Timeout:
                wait = config.RETRY_BACKOFF ** (attempt + 1) * 5
                print(f"  [GPT] Timeout. Retrying in {wait:.0f}s...")
                time.sleep(wait)
                continue
            except requests.exceptions.RequestException as e:
                if attempt == config.RETRY_MAX - 1:
                    return {"error": str(e), "raw": ""}
                wait = config.RETRY_BACKOFF ** (attempt + 1) * 3
                time.sleep(wait)

        return {"error": "Max retries exceeded", "raw": ""}

    def _parse_response(self, data: dict) -> dict:
        """Extract JSON from OpenAI response."""
        choices = data.get("choices", [])
        if not choices:
            return {"error": "No choices in response", "raw": str(data)}

        message = choices[0].get("message", {})
        content = message.get("content", "")
        finish_reason = choices[0].get("finish_reason", "unknown")

        if finish_reason == "length":
            return {"error": "Response truncated (hit max_tokens)", "raw": content}

        # Parse JSON from content
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            parsed["_raw"] = content
            return parsed
        except json.JSONDecodeError:
            return {"error": "JSON parse failed", "raw": content}
