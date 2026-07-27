import asyncio
import json
import logging
import re
from typing import AsyncIterator

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRY_DELAY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)
MAX_BACKOFF = 60.0
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 5,
        fallbacks: list[str] | None = None,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_llm_model
        self.max_retries = max_retries
        if fallbacks is None:
            fallbacks = [
                name.strip() for name in settings.gemini_llm_fallbacks.split(",") if name.strip()
            ]
        self._models = [self.model] + [name for name in fallbacks if name != self.model]
        self._model_index = 0
        self._client = httpx.AsyncClient(
            timeout=180, headers={"x-goog-api-key": self.api_key}
        )
        self.prompt_tokens = 0
        self.output_tokens = 0

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    def _payload(
        self, prompt: str, system: str | None, temperature: float, json_output: bool
    ) -> dict:
        payload: dict = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if json_output:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        return payload

    def _next_model(self) -> bool:
        """Move to the next model after the current one runs out of daily quota."""
        if self._model_index + 1 >= len(self._models):
            return False
        self._model_index += 1
        self.model = self._models[self._model_index]
        logger.warning("daily quota spent, switching to %s", self.model)
        return True

    def _record_usage(self, data: dict) -> None:
        usage = data.get("usageMetadata") or {}
        self.prompt_tokens += usage.get("promptTokenCount", 0)
        self.output_tokens += usage.get("candidatesTokenCount", 0)

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        json_output: bool = False,
    ) -> str:
        payload = self._payload(prompt, system, temperature, json_output)
        last_error = ""
        for attempt in range(self.max_retries):
            try:
                response = await self._client.post(
                    f"{BASE_URL}/models/{self.model}:generateContent", json=payload
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                await asyncio.sleep(min(2**attempt, MAX_BACKOFF))
                continue

            if response.status_code == 200:
                data = response.json()
                self._record_usage(data)
                return _first_text(data)

            last_error = response.text[:300]
            if response.status_code == 429:
                if _is_daily_quota(response.text) and self._next_model():
                    continue
                delay = min(_retry_delay(response.text) or 2**attempt * 2, MAX_BACKOFF)
                logger.warning("llm 429, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code in (500, 502, 503, 504):
                delay = min(2**attempt * 2, MAX_BACKOFF)
                logger.warning("llm %s, retrying in %.1fs", response.status_code, delay)
                await asyncio.sleep(delay)
                continue
            raise LLMError(f"generate failed {response.status_code}: {last_error}")

        raise LLMError(f"generate failed after {self.max_retries} attempts: {last_error}")

    async def stream(
        self, prompt: str, system: str | None = None, temperature: float = 0.2
    ) -> AsyncIterator[str]:
        payload = self._payload(prompt, system, temperature, json_output=False)
        last_error = ""
        for attempt in range(self.max_retries):
            async with self._client.stream(
                "POST",
                f"{BASE_URL}/models/{self.model}:streamGenerateContent",
                params={"alt": "sse"},
                json=payload,
            ) as response:
                if response.status_code == 200:
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk or chunk == "[DONE]":
                            continue
                        data = json.loads(chunk)
                        self._record_usage(data)
                        text = _first_text(data)
                        if text:
                            yield text
                    return

                body = (await response.aread()).decode("utf-8", "replace")
                last_error = body[:300]

            if response.status_code == 429:
                if _is_daily_quota(body) and self._next_model():
                    continue
                delay = min(_retry_delay(body) or 2**attempt * 2, MAX_BACKOFF)
                logger.warning("stream 429, retrying in %.1fs", delay)
                await asyncio.sleep(delay)
                continue
            if response.status_code in (500, 502, 503, 504):
                await asyncio.sleep(min(2**attempt * 2, MAX_BACKOFF))
                continue
            raise LLMError(f"stream failed {response.status_code}: {last_error}")

        raise LLMError(f"stream failed after {self.max_retries} attempts: {last_error}")

    async def generate_json(
        self, prompt: str, system: str | None = None, temperature: float = 0.0
    ) -> object:
        raw = await self.generate(prompt, system, temperature, json_output=True)
        return parse_json(raw)


def _first_text(data: dict) -> str:
    for candidate in data.get("candidates") or []:
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts)
        if text:
            return text
    return ""


def _retry_delay(body: str) -> float | None:
    match = RETRY_DELAY_RE.search(body)
    return float(match.group(1)) + 1 if match else None


def _is_daily_quota(body: str) -> bool:
    """A per-day rejection will not clear by waiting, so the model must be swapped."""
    return "PerDay" in body


def parse_json(raw: str) -> object:
    """Models sometimes wrap JSON in a code fence even when asked not to."""
    text = raw.strip()
    match = JSON_BLOCK_RE.search(text)
    if match is not None:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMError(f"model did not return valid JSON: {raw[:200]}") from exc
