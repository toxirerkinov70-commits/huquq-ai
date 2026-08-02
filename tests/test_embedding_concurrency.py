"""The local embedder has to survive being called from several searches at once.

A described situation fans out into a handful of searches that run together, and each
one embeds its own query. The model object is shared, and the tokenizer under it is not
re-entrant, so without serialisation the second thread in raises "Already borrowed" and
the whole answer fails with a 500.
"""

import asyncio
import threading

import pytest

from backend.app.services.embedding import TASK_QUERY, LocalEmbeddingClient


class BorrowCheckingModel:
    """Stands in for SentenceTransformer and objects to being used concurrently."""

    def __init__(self) -> None:
        self.inside = 0
        self.overlaps = 0
        self._guard = threading.Lock()

    def encode(self, texts, **kwargs):
        with self._guard:
            self.inside += 1
            if self.inside > 1:
                self.overlaps += 1
        try:
            # long enough that unsynchronised callers would certainly overlap
            threading.Event().wait(0.02)
            return [_Vector() for _ in texts]
        finally:
            with self._guard:
                self.inside -= 1


class _Vector:
    def tolist(self):
        return [0.0, 1.0]


@pytest.mark.asyncio
async def test_parallel_searches_never_enter_the_model_together(monkeypatch):
    client = LocalEmbeddingClient(concurrency=4)
    model = BorrowCheckingModel()
    monkeypatch.setattr(client, "_load", lambda: model)

    await asyncio.gather(*(client.embed_query(f"savol {i}") for i in range(6)))

    assert model.overlaps == 0
    assert client.request_count == 6
