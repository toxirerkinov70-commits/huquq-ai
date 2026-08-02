import asyncio
import logging
import re
import threading
import time

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_BATCH = 100
# Free tier allows 100 embed requests per minute and counts every item in a batch,
# so pacing sits below that: a batch sized exactly at the quota fails whenever any
# other request shares the window.
DEFAULT_RATE_LIMIT = 60
DEFAULT_BATCH = 30
MAX_BACKOFF = 60.0
# floor of roughly 12 requests/minute before we conclude the key is unusable
MAX_SECONDS_PER_ITEM = 5.0
RETRY_DELAY_RE = re.compile(r"retry in ([\d.]+)s", re.IGNORECASE)

TASK_DOCUMENT = "RETRIEVAL_DOCUMENT"
TASK_QUERY = "RETRIEVAL_QUERY"


class EmbeddingError(RuntimeError):
    pass


class RateLimiter:
    """Paces requests evenly and adapts to whatever the API actually allows.

    A sliding window would let a whole minute's allowance go out in one burst, and
    the API answers bursts with 429 even when the per-minute average is legal.
    Charging each item a fixed slice of time keeps the stream smooth. Because a
    rejected request still seems to consume quota, sustained 429s mean the true
    ceiling is lower than advertised, so the pace slows down until they stop and
    then creeps back up.
    """

    RECOVER_AFTER = 20

    def __init__(self, limit_per_minute: int) -> None:
        self._floor = 60 / limit_per_minute
        self.seconds_per_item = self._floor
        self._next_slot = 0.0
        self._successes = 0
        self._lock = asyncio.Lock()

    @property
    def rate_per_minute(self) -> float:
        return 60 / self.seconds_per_item

    async def acquire(self, count: int) -> None:
        async with self._lock:
            now = time.monotonic()
            start = max(now, self._next_slot)
            self._next_slot = start + count * self.seconds_per_item
            delay = start - now
        if delay > 0:
            await asyncio.sleep(delay)

    async def penalise(self, seconds: float) -> None:
        """Back off and slow the steady-state pace after a rejection."""
        async with self._lock:
            self._successes = 0
            self.seconds_per_item = min(self.seconds_per_item * 1.4, MAX_SECONDS_PER_ITEM)
            self._next_slot = max(self._next_slot, time.monotonic()) + seconds
            rate = 60 / self.seconds_per_item
        logger.info("slowing to ~%.0f requests/minute", rate)

    async def on_success(self, count: int) -> None:
        async with self._lock:
            self._successes += count
            if self._successes >= self.RECOVER_AFTER and self.seconds_per_item > self._floor:
                self._successes = 0
                self.seconds_per_item = max(self.seconds_per_item * 0.9, self._floor)


class EmbeddingClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dim: int | None = None,
        rate_limit: int = DEFAULT_RATE_LIMIT,
        max_retries: int = 8,
    ) -> None:
        self.api_key = api_key or settings.gemini_api_key
        self.model = model or settings.gemini_embed_model
        self.dim = dim or settings.embed_dim
        self.max_retries = max_retries
        self._limiter = RateLimiter(rate_limit)
        # the key goes in a header, never a query string, so it stays out of logs
        self._client = httpx.AsyncClient(
            timeout=180, headers={"x-goog-api-key": self.api_key}
        )
        self.request_count = 0

    async def __aenter__(self) -> "EmbeddingClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        """Embed a list of texts, splitting into API-sized batches."""
        vectors: list[list[float]] = []
        for start in range(0, len(texts), MAX_BATCH):
            batch = texts[start : start + MAX_BATCH]
            vectors.extend(await self._embed_batch(batch, task_type))
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed([text], TASK_QUERY)
        return vectors[0]

    async def _embed_batch(self, texts: list[str], task_type: str) -> list[list[float]]:
        payload = {
            "requests": [
                {
                    "model": f"models/{self.model}",
                    "content": {"parts": [{"text": text}]},
                    "taskType": task_type,
                    "outputDimensionality": self.dim,
                }
                for text in texts
            ]
        }

        last_error = ""
        for attempt in range(self.max_retries):
            await self._limiter.acquire(len(texts))
            try:
                response = await self._client.post(
                    f"{BASE_URL}/models/{self.model}:batchEmbedContents", json=payload
                )
            except httpx.HTTPError as exc:
                last_error = str(exc)
                logger.warning("embed request failed (%s), attempt %s", exc, attempt + 1)
                await asyncio.sleep(2**attempt)
                continue

            if response.status_code == 200:
                self.request_count += len(texts)
                await self._limiter.on_success(len(texts))
                return [item["values"] for item in response.json()["embeddings"]]

            last_error = response.text[:300]
            if response.status_code == 429:
                delay = min(self._retry_delay(response.text) or 2**attempt * 5, MAX_BACKOFF)
                logger.warning(
                    "quota exceeded, backing off %.1fs (attempt %s)", delay, attempt + 1
                )
                await self._limiter.penalise(delay)
                continue
            if response.status_code >= 500:
                await asyncio.sleep(2**attempt)
                continue
            raise EmbeddingError(f"embed failed {response.status_code}: {last_error}")

        raise EmbeddingError(f"embed failed after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def _retry_delay(body: str) -> float | None:
        match = RETRY_DELAY_RE.search(body)
        return float(match.group(1)) + 1 if match else None


class LocalEmbeddingClient:
    """Runs a sentence-transformers model on this machine: no keys, no quota.

    e5 models are trained with asymmetric prefixes, so documents and queries must
    be marked differently or retrieval quality drops sharply.
    """

    def __init__(
        self, model_name: str | None = None, dim: int | None = None, concurrency: int | None = None
    ) -> None:
        self.model = model_name or settings.local_embed_model
        self.dim = dim or settings.embed_dim
        self._model = None
        # The semaphore bounds how many requests may be waiting on the model; the lock
        # is what actually protects it. Letting two threads into model.encode looked
        # like parallelism — torch does release the GIL for the matmul — but the
        # tokenizer underneath is Rust and not re-entrant, so the second thread died
        # with "Already borrowed" and took the answer with it. It surfaced on exactly
        # the questions that matter most: a described situation fans out into several
        # searches at once.
        self._gate = asyncio.Semaphore(max(1, concurrency or settings.embed_concurrency))
        self._encode_lock = threading.Lock()
        self._load_lock = threading.Lock()
        self.request_count = 0

    async def __aenter__(self) -> "LocalEmbeddingClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        self._model = None

    def _load(self):
        # two encodes can now start at once, and both would otherwise load the model
        if self._model is None:
            with self._load_lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    logger.info("loading local embedding model %s", self.model)
                    model = SentenceTransformer(self.model)
                    actual = model.get_sentence_embedding_dimension()
                    if actual != self.dim:
                        raise ValueError(
                            f"{self.model} produces {actual} dimensions but EMBED_DIM is {self.dim}"
                        )
                    self._model = model
        return self._model

    def _prefix(self, task_type: str) -> str:
        if "e5" not in self.model:
            return ""
        return "query: " if task_type == TASK_QUERY else "passage: "

    def _encode(self, texts: list[str], task_type: str) -> list[list[float]]:
        model = self._load()
        prefix = self._prefix(task_type)
        with self._encode_lock:
            vectors = model.encode(
                [prefix + text for text in texts],
                batch_size=8,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return [vector.tolist() for vector in vectors]

    async def embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        # encoding is CPU bound, so it must not block the event loop
        async with self._gate:
            vectors = await asyncio.to_thread(self._encode, texts, task_type)
        self.request_count += len(texts)
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed([text], TASK_QUERY)
        return vectors[0]


def get_embedding_client():
    """Pick the embedding backend named in the settings."""
    if settings.embed_provider == "gemini":
        return EmbeddingClient()
    return LocalEmbeddingClient()
