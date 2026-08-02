import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

import httpx

from ..config import settings
from . import usage

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
RETRY_DELAY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)
MAX_BACKOFF = 60.0
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(RuntimeError):
    """Carries the provider's status code so the caller can say something useful.

    Without it every failure reaches the user as one word. A spent daily quota, a
    misconfigured key and a slow network need three different sentences.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        self.status = status
        super().__init__(message)

    @property
    def reason(self) -> str:
        if self.status in (401, 403):
            return "auth"
        if self.status == 429:
            return "quota"
        if self.status and self.status >= 500:
            return "provider"
        if self.status is None:
            return "network"
        return "unknown"


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
        self._downgraded_at: float | None = None
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
        self,
        prompt: str,
        system: str | None,
        temperature: float,
        json_output: bool,
        extra_parts: list[dict] | None = None,
    ) -> dict:
        # media parts (inline files) go before the text, as the API docs recommend
        parts = (extra_parts or []) + [{"text": prompt}]
        payload: dict = {
            "contents": [{"role": "user", "parts": parts}],
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
        if self._downgraded_at is None:
            self._downgraded_at = time.monotonic()
        logger.warning("daily quota spent, switching to %s", self.model)
        return True

    def _maybe_restore_primary(self) -> None:
        """A daily quota clears at midnight, so a downgrade must not be permanent.

        The client is shared by the whole process: without this, one user exhausting
        the primary model leaves every later question on the weakest model in the
        chain until the service is restarted.
        """
        if self._model_index == 0 or self._downgraded_at is None:
            return
        elapsed = time.monotonic() - self._downgraded_at
        if elapsed < settings.llm_primary_retry_minutes * 60:
            return
        self._model_index = 0
        self.model = self._models[0]
        self._downgraded_at = None
        logger.info("retrying primary model %s after backoff", self.model)

    def _record_usage(self, data: dict) -> None:
        self._apply_usage(data.get("usageMetadata") or {})

    def _apply_usage(self, metadata: dict) -> None:
        prompt_tokens = metadata.get("promptTokenCount", 0)
        output_tokens = metadata.get("candidatesTokenCount", 0)
        self.prompt_tokens += prompt_tokens
        self.output_tokens += output_tokens
        # attributes the spend to whoever is being served right now
        usage.record(self.model, prompt_tokens, output_tokens)

    async def _send(self, payload: dict) -> dict:
        """One request, with the retry and model-swap policy applied."""
        self._maybe_restore_primary()
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
                return data

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
            raise LLMError(
                f"generate failed {response.status_code}: {last_error}", response.status_code
            )

        raise LLMError(f"generate failed after {self.max_retries} attempts: {last_error}")

    async def generate(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        json_output: bool = False,
        extra_parts: list[dict] | None = None,
    ) -> str:
        return _first_text(
            await self._send(self._payload(prompt, system, temperature, json_output, extra_parts))
        )

    async def generate_with_tools(
        self,
        prompt: str,
        declarations: list[dict],
        executor,
        system: str | None = None,
        temperature: float = 0.2,
        max_calls: int = 5,
        extra_parts: list[dict] | None = None,
    ) -> str:
        """Let the model call tools, feed the results back, and return its final answer.

        The call budget is a hard stop rather than a suggestion: a model that keeps
        reaching for the live site would hammer lex.uz and leave the user waiting.
        """
        parts = (extra_parts or []) + [{"text": prompt}]
        contents: list[dict] = [{"role": "user", "parts": parts}]
        payload: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
            "tools": [{"functionDeclarations": declarations}],
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        for _ in range(max_calls + 1):
            data = await self._send(payload)
            calls = _function_calls(data)
            if not calls:
                return _first_text(data)

            contents.append(_model_content(data))
            responses = []
            for call in calls:
                result = await executor(call["name"], call.get("args") or {})
                responses.append(
                    {"functionResponse": {"name": call["name"], "response": result}}
                )
            contents.append({"role": "user", "parts": responses})

        logger.warning("tool call budget of %s exhausted, answering without more calls", max_calls)
        payload.pop("tools", None)
        return _first_text(await self._send(payload))

    async def stream(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.2,
        extra_parts: list[dict] | None = None,
    ) -> AsyncIterator[str]:
        payload = self._payload(prompt, system, temperature, json_output=False, extra_parts=extra_parts)
        self._maybe_restore_primary()
        last_error = ""
        for attempt in range(self.max_retries):
            async with self._client.stream(
                "POST",
                f"{BASE_URL}/models/{self.model}:streamGenerateContent",
                params={"alt": "sse"},
                json=payload,
            ) as response:
                if response.status_code == 200:
                    # every streamed chunk repeats usageMetadata, and the counts inside
                    # it are cumulative for the whole call. Adding each one up charged a
                    # single answer as if it had been generated dozens of times over, so
                    # only the last report is applied, once the stream has finished
                    final_usage: dict = {}
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        chunk = line[5:].strip()
                        if not chunk or chunk == "[DONE]":
                            continue
                        data = json.loads(chunk)
                        if data.get("usageMetadata"):
                            final_usage = data["usageMetadata"]
                        text = _first_text(data)
                        if text:
                            yield text
                    self._apply_usage(final_usage)
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
            raise LLMError(
                f"stream failed {response.status_code}: {last_error}", response.status_code
            )

        raise LLMError(f"stream failed after {self.max_retries} attempts: {last_error}")

    async def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        temperature: float = 0.0,
        extra_parts: list[dict] | None = None,
    ) -> object:
        raw = await self.generate(prompt, system, temperature, json_output=True, extra_parts=extra_parts)
        return parse_json(raw)


def _function_calls(data: dict) -> list[dict]:
    calls = []
    for candidate in data.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            call = part.get("functionCall")
            if call:
                calls.append(call)
    return calls


def _model_content(data: dict) -> dict:
    """The model's turn has to go back verbatim, or the tool results have nothing to attach to."""
    for candidate in data.get("candidates") or []:
        content = candidate.get("content")
        if content:
            return {"role": "model", "parts": content.get("parts") or []}
    return {"role": "model", "parts": []}


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
