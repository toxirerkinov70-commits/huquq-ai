"""Reading the registry and the chunk file, without going stale and without a full scan.

Two problems with the previous ``lru_cache`` approach. The cache never expired, so a
document added by the nightly refresh stayed invisible until somebody restarted the API —
the corpus updated itself and the service kept serving the old answer to "which documents
do you have". And ``_document_chunks`` walked all 22 513 lines for every document asked
for, which is a file scan on a user-facing path.

Here the files are watched by modification time and size, and the chunk file is indexed by
byte offset: looking up one document seeks straight to its lines instead of reading the
rest.
"""

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
REGISTRY_PATH = DATA_DIR / "registry.jsonl"
CHUNKS_PATH = DATA_DIR / "chunks.jsonl"


def _stamp(path: Path) -> tuple[float, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime, stat.st_size)


class Registry:
    """The document list, reloaded whenever the file behind it changes."""

    def __init__(self, path: Path = REGISTRY_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[float, int] | None = None
        self._records: list[dict] = []
        self._by_id: dict[str, dict] = {}

    def _refresh(self) -> None:
        stamp = _stamp(self.path)
        if stamp == self._stamp and (stamp is not None or self._records):
            return
        with self._lock:
            stamp = _stamp(self.path)
            if stamp == self._stamp:
                return
            records: list[dict] = []
            if stamp is not None:
                with self.path.open(encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            records.append(json.loads(line))
            self._records = records
            self._by_id = {record["doc_id"]: record for record in records}
            self._stamp = stamp
            logger.info("registry loaded: %s document(s)", len(records))

    def all(self) -> list[dict]:
        self._refresh()
        return self._records

    def get(self, doc_id: str) -> dict | None:
        self._refresh()
        return self._by_id.get(doc_id)

    def as_map(self) -> dict[str, dict]:
        self._refresh()
        return self._by_id


class ChunkStore:
    """Byte offsets per document, so one document's chunks are read directly."""

    def __init__(self, path: Path = CHUNKS_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[float, int] | None = None
        self._offsets: dict[str, list[int]] = {}

    def _refresh(self) -> None:
        stamp = _stamp(self.path)
        if stamp == self._stamp and (stamp is not None or self._offsets):
            return
        with self._lock:
            stamp = _stamp(self.path)
            if stamp == self._stamp:
                return
            offsets: dict[str, list[int]] = {}
            if stamp is not None:
                # binary mode: the offsets have to be byte positions for seek() to work
                with self.path.open("rb") as handle:
                    position = 0
                    for raw in handle:
                        length = len(raw)
                        stripped = raw.strip()
                        if stripped:
                            try:
                                doc_id = json.loads(stripped)["doc_id"]
                            except (json.JSONDecodeError, KeyError):
                                logger.warning("unreadable chunk line at byte %s", position)
                            else:
                                offsets.setdefault(str(doc_id), []).append(position)
                        position += length
            self._offsets = offsets
            self._stamp = stamp
            logger.info("chunk index built: %s document(s)", len(offsets))

    def chunks(self, doc_id: str) -> list[dict]:
        self._refresh()
        positions = self._offsets.get(str(doc_id))
        if not positions:
            return []
        chunks = []
        with self.path.open("rb") as handle:
            for position in positions:
                handle.seek(position)
                line = handle.readline()
                if line.strip():
                    chunks.append(json.loads(line))
        return chunks

    def article_count(self, doc_id: str) -> int:
        return len(self._offsets.get(str(doc_id), []))


registry = Registry()
chunks = ChunkStore()


def document_articles(doc_id: str) -> list[dict]:
    """One entry per article, in file order, first part only."""
    seen: set[str] = set()
    articles = []
    for chunk in chunks.chunks(doc_id):
        if chunk.get("part") != 0:
            continue
        key = str(chunk.get("article_no"))
        if key in seen:
            continue
        seen.add(key)
        articles.append(chunk)
    return articles
