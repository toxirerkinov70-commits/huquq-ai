"""How a streamed answer is charged.

The counts inside ``usageMetadata`` are cumulative and repeated on every chunk, so
summing them charges one answer many times over. Before the fix a single answer reported
roughly ten times its real token count, which put every cost figure out by an order of
magnitude.
"""

import asyncio
import json

import httpx
import pytest

from backend.app.services import usage
from backend.app.services.llm import LLMClient

PROMPT_TOKENS = 3000
CHUNKS = 6


def _sse_body() -> bytes:
    """Six chunks, each repeating the prompt count and growing the output count."""
    lines = []
    for index in range(1, CHUNKS + 1):
        payload = {
            "candidates": [{"content": {"parts": [{"text": f"bo'lak{index} "}]}}],
            "usageMetadata": {
                "promptTokenCount": PROMPT_TOKENS,
                "candidatesTokenCount": index * 100,
            },
        }
        lines.append(f"data: {json.dumps(payload)}\n\n")
    return "".join(lines).encode()


def _client() -> LLMClient:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=_sse_body())
    )
    client = LLMClient(api_key="test", model="stub-model", fallbacks=[])
    client._client = httpx.AsyncClient(transport=transport)
    return client


async def _collect() -> tuple[str, usage.Meter, LLMClient]:
    client = _client()
    meter = usage.new_meter("u", "/api/chat", "question")
    text = "".join([piece async for piece in client.stream("savol")])
    await client.close()
    return text, meter, client


def test_streamed_answer_is_charged_once():
    text, meter, client = asyncio.run(_collect())

    assert text.startswith("bo'lak1")
    # the prompt is sent once, so it is charged once — not once per chunk
    assert meter.prompt_tokens == PROMPT_TOKENS
    assert meter.output_tokens == CHUNKS * 100
    assert meter.llm_calls == 1
    assert client.prompt_tokens == PROMPT_TOKENS
    usage.bind(None)


def test_naive_summing_would_have_been_much_higher():
    """Guards the intent, not just the number: the bug was a factor, not an offset."""
    _, meter, _ = asyncio.run(_collect())
    naive = PROMPT_TOKENS * CHUNKS
    assert meter.prompt_tokens * CHUNKS == naive
    assert meter.cost_usd < 0.05
    usage.bind(None)


@pytest.mark.parametrize("metadata", [{}, {"promptTokenCount": 0}])
def test_a_response_without_usage_is_not_a_crash(metadata):
    meter = usage.new_meter("u", "/api/chat", "question")
    client = _client()
    client._apply_usage(metadata)
    assert meter.prompt_tokens == metadata.get("promptTokenCount", 0)
    usage.bind(None)
