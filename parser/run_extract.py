import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from parser.lex.chunk import chunk_document  # noqa: E402
from parser.lex.extract import extract_document, to_markdown  # noqa: E402

logger = logging.getLogger("run_extract")

REGISTRY_PATH = ROOT / "data" / "registry.jsonl"
RAW_DIR = ROOT / "data" / "raw"
MARKDOWN_DIR = ROOT / "data" / "markdown"
CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"


def load_registry() -> list[dict]:
    if not REGISTRY_PATH.exists():
        return []
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def save_registry(records_by_id: dict[str, dict]) -> None:
    tmp = REGISTRY_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in records_by_id.values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(REGISTRY_PATH)


def enrich_record(record: dict, document) -> bool:
    """Fill registry fields that only the document page carries."""
    updates = {
        "okoz": document.okoz_categories,
        "tsz": document.tsz,
        "adopted_date": record.get("adopted_date") or document.adopted_date,
        "effective_date": record.get("effective_date") or document.effective_date,
        "script": document.script,
        "articles": len(document.articles),
    }
    changed = False
    for key, value in updates.items():
        if value and record.get(key) != value:
            record[key] = value
            changed = True
    return changed


def load_chunks() -> dict[str, list[dict]]:
    """Existing chunks grouped by doc_id so a re-run only replaces what it re-extracts."""
    if not CHUNKS_PATH.exists():
        return {}
    by_doc: dict[str, list[dict]] = {}
    with CHUNKS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunk = json.loads(line)
                by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    return by_doc


def save_chunks(by_doc: dict[str, list[dict]]) -> int:
    CHUNKS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHUNKS_PATH.with_suffix(".jsonl.tmp")
    total = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for chunks in by_doc.values():
            for chunk in chunks:
                handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                total += 1
    tmp.replace(CHUNKS_PATH)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract markdown and chunks from raw pages")
    parser.add_argument("--group", type=int, default=None)
    parser.add_argument("--doc-id", default=None, help="process a single document")
    args = parser.parse_args()

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    all_records = {rec["doc_id"]: rec for rec in load_registry()}
    records = list(all_records.values())
    if args.group is not None:
        records = [rec for rec in records if rec.get("group") == args.group]
    if args.doc_id is not None:
        records = [rec for rec in records if rec["doc_id"] == args.doc_id]
    records = [rec for rec in records if (RAW_DIR / f"{rec['doc_id']}.html").exists()]
    if not records:
        logger.error("no fetched documents match this selection")
        return 1

    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    by_doc = load_chunks()
    articles_total = 0
    failures = 0
    enriched = 0

    for record in tqdm(records, desc="extract", unit="doc"):
        doc_id = record["doc_id"]
        html = (RAW_DIR / f"{doc_id}.html").read_text(encoding="utf-8")
        meta = dict(record)
        meta["fetched_at"] = datetime.fromtimestamp(
            (RAW_DIR / f"{doc_id}.html").stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
        try:
            document = extract_document(doc_id, html)
        except ValueError as exc:
            logger.error("extraction failed: %s", exc)
            failures += 1
            continue

        if not document.articles:
            logger.warning("%s: no articles found (%s)", doc_id, record.get("title", "")[:60])

        if enrich_record(all_records[doc_id], document):
            enriched += 1
            meta = dict(all_records[doc_id]) | {"fetched_at": meta["fetched_at"]}

        (MARKDOWN_DIR / f"{doc_id}.md").write_text(to_markdown(document, meta), encoding="utf-8")
        by_doc[doc_id] = chunk_document(document, meta)
        articles_total += len(document.articles)

    total_chunks = save_chunks(by_doc)
    save_registry(all_records)
    logger.info(
        "processed %s documents, %s articles, %s chunks in %s (%s failed, %s registry records enriched)",
        len(records),
        articles_total,
        total_chunks,
        CHUNKS_PATH.name,
        failures,
        enriched,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
