import json
import time
import threading
import requests

from . import config
from .base_client import BaseClient


class GeminiClient(BaseClient):
    # Class-level rate limiter shared across all instances and threads
    _rate_lock = threading.Lock()
    _last_call_time = 0.0

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = model or config.MODEL_DEFAULT
        self._min_interval = 60.0 / config.CALLS_PER_MINUTE
        # Thread-local session for connection pooling
        self._local = threading.local()

    def _get_session(self) -> requests.Session:
        if not hasattr(self._local, "session"):
            self._local.session = requests.Session()
        return self._local.session

    def _rate_limit(self):
        with GeminiClient._rate_lock:
            elapsed = time.time() - GeminiClient._last_call_time
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            GeminiClient._last_call_time = time.time()

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
        """Call Gemini generateContent and return the parsed response."""
        url = (
            f"{config.GEMINI_BASE_URL}/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )

        # Gemini 3.x: Google recommends not setting temperature/top_p/top_k —
        # reasoning is optimised for defaults. Only send it for 2.x models.
        is_gemini_3x = self.model.startswith("gemini-3")
        generation_config: dict = {} if is_gemini_3x else {"temperature": temperature}

        if response_schema:
            generation_config["response_mime_type"] = "application/json"
            generation_config["response_schema"] = response_schema

        if thinking:
            # Gemini 3.x uses thinkingLevel instead of thinkingBudget
            if is_gemini_3x:
                level = thinking_level or "high"
                generation_config["thinkingConfig"] = {
                    "thinkingLevel": level,
                    "includeThoughts": False,
                }
            else:
                budget = thinking_budget if thinking_budget is not None else config.THINKING_BUDGET
                generation_config["thinkingConfig"] = {
                    "thinkingBudget": budget,
                    "includeThoughts": False,
                }

        # Build parts list: text strings become {"text": ...},
        # dicts with mime_type+data become {"inlineData": ...}
        content_parts = []
        for part in user_parts:
            if isinstance(part, str):
                content_parts.append({"text": part})
            elif isinstance(part, dict) and "data" in part:
                content_parts.append({
                    "inlineData": {
                        "mimeType": part.get("mime_type", "image/jpeg"),
                        "data": part["data"],
                    }
                })

        body = {
            "system_instruction": {"parts": [{"text": system_instruction}]},
            "contents": [
                {
                    "role": "user",
                    "parts": content_parts,
                }
            ],
            "generationConfig": generation_config,
        }

        session = self._get_session()

        for attempt in range(config.RETRY_MAX):
            self._rate_limit()
            try:
                resp = session.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                    timeout=config.REQUEST_TIMEOUT,
                )

                if resp.status_code == 429:
                    wait = config.RETRY_BACKOFF ** (attempt + 1) * 10
                    print(f"  Rate limited. Waiting {wait:.0f}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code >= 500:
                    wait = config.RETRY_BACKOFF ** (attempt + 1) * 5
                    print(f"  Server error {resp.status_code}. Retrying in {wait:.0f}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()
                parsed = self._parse_response(data)
                # Attach usage metadata
                usage = data.get("usageMetadata", {})
                parsed["_usage"] = {
                    "prompt_tokens": usage.get("promptTokenCount", 0),
                    "output_tokens": usage.get("candidatesTokenCount", 0),
                    "thinking_tokens": usage.get("thoughtsTokenCount", 0),
                    "total_tokens": usage.get("totalTokenCount", 0),
                    "model": self.model,
                }
                return parsed

            except requests.exceptions.Timeout:
                wait = config.RETRY_BACKOFF ** (attempt + 1) * 5
                print(f"  Timeout. Retrying in {wait:.0f}s...")
                time.sleep(wait)
                continue
            except requests.exceptions.RequestException as e:
                if attempt == config.RETRY_MAX - 1:
                    return {"error": str(e), "raw": ""}
                wait = config.RETRY_BACKOFF ** (attempt + 1) * 3
                time.sleep(wait)

        return {"error": "Max retries exceeded", "raw": ""}

    def _parse_response(self, data: dict) -> dict:
        """Extract text from Gemini response, parse JSON if structured."""
        candidates = data.get("candidates", [])
        if not candidates:
            block_reason = data.get("promptFeedback", {}).get("blockReason", "unknown")
            return {"error": f"No candidates. Block reason: {block_reason}", "raw": ""}

        parts = candidates[0].get("content", {}).get("parts", [])
        # Find the non-thought part
        text_part = None
        for p in parts:
            if not p.get("thought"):
                text_part = p
                break
        if not text_part:
            text_part = parts[0] if parts else {}

        text = text_part.get("text", "")

        # Try to parse as JSON
        cleaned = text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            parsed["_raw"] = text
            return parsed
        except json.JSONDecodeError:
            return {"error": "JSON parse failed", "raw": text}
