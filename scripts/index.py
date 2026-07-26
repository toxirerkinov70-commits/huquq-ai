import argparse
import asyncio
import hashlib
import json
import logging
import struct
import sys
import uuid
from pathlib import Path

from qdrant_client import QdrantClient, models
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from backend.app.services.embedding import (  # noqa: E402
    DEFAULT_BATCH,
    TASK_DOCUMENT,
    EmbeddingClient,
    EmbeddingError,
)
from backend.app.services.sparse import encode_document  # noqa: E402

logger = logging.getLogger("index")

CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"
EMBED_CACHE_DIR = ROOT / "data" / "embeddings"
FAILED_PATH = ROOT / "data" / "index_failed.txt"
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"
UPSERT_BATCH = 128
MAX_CONSECUTIVE_FAILURES = 3
# gemini-embedding-001 pricing, used only to report what a run cost
USD_PER_MILLION_TOKENS = 0.15
PAYLOAD_INDEXES = {
    "doc_id": models.PayloadSchemaType.KEYWORD,
    "doc_type": models.PayloadSchemaType.KEYWORD,
    "doc_title": models.PayloadSchemaType.KEYWORD,
    "act_type": models.PayloadSchemaType.INTEGER,
    "article_no": models.PayloadSchemaType.KEYWORD,
    "okoz": models.PayloadSchemaType.KEYWORD,
    "tsz": models.PayloadSchemaType.KEYWORD,
    "status": models.PayloadSchemaType.KEYWORD,
    "group": models.PayloadSchemaType.INTEGER,
}


def load_chunks(group: int | None, doc_id: str | None) -> list[dict]:
    if not CHUNKS_PATH.exists():
        return []
    chunks = []
    with CHUNKS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunk = json.loads(line)
            if group is not None and chunk.get("group") != group:
                continue
            if doc_id is not None and chunk.get("doc_id") != doc_id:
                continue
            chunks.append(chunk)
    return chunks


def point_id(chunk_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, chunk_id))


def cache_path(text: str, model: str, dim: int) -> Path:
    digest = hashlib.sha256(f"{model}:{dim}:{text}".encode("utf-8")).hexdigest()
    return EMBED_CACHE_DIR / digest[:2] / f"{digest}.vec"


def read_cached(path: Path, dim: int) -> list[float] | None:
    if not path.exists():
        return None
    raw = path.read_bytes()
    if len(raw) != dim * 4:
        return None
    return list(struct.unpack(f"{dim}f", raw))


def write_cached(path: Path, vector: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack(f"{len(vector)}f", *vector))


def ensure_collection(client: QdrantClient, name: str, dim: int, recreate: bool) -> None:
    exists = client.collection_exists(name)
    if exists and recreate:
        logger.warning("deleting existing collection %s", name)
        client.delete_collection(name)
        exists = False
    if not exists:
        client.create_collection(
            collection_name=name,
            # on_disk everywhere: the whole point is to survive on 8 GB of RAM
            vectors_config={
                DENSE_VECTOR: models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                    hnsw_config=models.HnswConfigDiff(on_disk=True),
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR: models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=True),
                    modifier=models.Modifier.IDF,
                )
            },
            on_disk_payload=True,
        )
        logger.info("created collection %s (dim=%s)", name, dim)

    for field, schema in PAYLOAD_INDEXES.items():
        try:
            client.create_payload_index(name, field_name=field, field_schema=schema)
        except Exception as exc:  # index already present
            logger.debug("payload index %s: %s", field, exc)


def upsert(client: QdrantClient, name: str, chunks: list[dict], vectors: list[list[float]]) -> None:
    points = []
    for chunk, vector in zip(chunks, vectors):
        indices, values = encode_document(chunk["text_for_embedding"])
        payload = {key: value for key, value in chunk.items() if key != "text_for_embedding"}
        points.append(
            models.PointStruct(
                id=point_id(chunk["chunk_id"]),
                vector={
                    DENSE_VECTOR: vector,
                    SPARSE_VECTOR: models.SparseVector(indices=indices, values=values),
                },
                payload=payload,
            )
        )

    for start in range(0, len(points), UPSERT_BATCH):
        client.upsert(collection_name=name, points=points[start : start + UPSERT_BATCH], wait=True)


async def index_chunks(
    qdrant: QdrantClient,
    name: str,
    chunks: list[dict],
    client: EmbeddingClient,
    batch_size: int,
) -> tuple[int, int, list[str]]:
    """Embed and upsert window by window so Qdrant fills up as the run progresses."""
    cached_total = 0
    embedded_chars = 0
    failed: list[str] = []
    consecutive_failures = 0

    with tqdm(total=len(chunks), desc="index", unit="chunk") as bar:
        for start in range(0, len(chunks), batch_size):
            window = chunks[start : start + batch_size]
            vectors: list[list[float] | None] = []
            missing: list[int] = []

            for position, chunk in enumerate(window):
                path = cache_path(chunk["text_for_embedding"], client.model, client.dim)
                vector = read_cached(path, client.dim)
                vectors.append(vector)
                if vector is None:
                    missing.append(position)
                else:
                    cached_total += 1

            if missing:
                texts = [window[position]["text_for_embedding"] for position in missing]
                try:
                    fresh = await client.embed(texts, TASK_DOCUMENT)
                except EmbeddingError as exc:
                    # one bad window must not throw away hours of work; a rerun picks
                    # these up and every other chunk is already cached by then
                    logger.error("window at %s failed, skipping: %s", start, exc)
                    failed.extend(chunk["chunk_id"] for chunk in window)
                    consecutive_failures += 1
                    bar.update(len(window))
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error(
                            "%s windows failed in a row, the quota is spent; "
                            "stopping so the run can resume later",
                            consecutive_failures,
                        )
                        failed.extend(
                            chunk["chunk_id"] for chunk in chunks[start + batch_size :]
                        )
                        return cached_total, embedded_chars, failed
                    continue
                consecutive_failures = 0
                for position, vector, text in zip(missing, fresh, texts):
                    vectors[position] = vector
                    write_cached(cache_path(text, client.model, client.dim), vector)
                    embedded_chars += len(text)

            upsert(qdrant, name, window, [v for v in vectors if v is not None])
            bar.update(len(window))

    return cached_total, embedded_chars, failed


async def main_async(args: argparse.Namespace) -> int:
    chunks = load_chunks(args.group, args.doc_id)
    if not chunks:
        logger.error("no chunks match this selection, run run_extract.py first")
        return 1
    if args.limit is not None:
        chunks = chunks[: args.limit]
    logger.info("indexing %s chunks", len(chunks))

    qdrant = QdrantClient(url=settings.qdrant_url, timeout=120)
    ensure_collection(qdrant, settings.qdrant_collection, settings.embed_dim, args.recreate)

    async with EmbeddingClient() as embedder:
        cached, embedded_chars, failed = await index_chunks(
            qdrant, settings.qdrant_collection, chunks, embedder, args.batch_size
        )

    info = qdrant.get_collection(settings.qdrant_collection)
    approx_tokens = int(embedded_chars / 3.5)
    logger.info(
        "done: %s chunks selected, %s from cache, %s failed, %s API calls, "
        "~%s tokens, ~$%.4f; collection now holds %s points",
        len(chunks),
        cached,
        len(failed),
        embedder.request_count,
        approx_tokens,
        approx_tokens / 1_000_000 * USD_PER_MILLION_TOKENS,
        info.points_count,
    )
    if failed:
        FAILED_PATH.write_text("\n".join(failed), encoding="utf-8")
        logger.warning("%s chunk ids written to %s, rerun to retry", len(failed), FAILED_PATH.name)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Index chunks into Qdrant")
    parser.add_argument("--group", type=int, default=None)
    parser.add_argument("--doc-id", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH, choices=range(1, 101))
    parser.add_argument("--recreate", action="store_true", help="drop the collection first")
    args = parser.parse_args()

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
