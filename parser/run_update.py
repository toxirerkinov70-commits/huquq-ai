"""Refresh the corpus from lex.uz: new documents, amended articles, repealed acts.

An out-of-date legal answer is worse than no answer, so this runs on a schedule rather
than by hand. It re-embeds only the articles whose text actually moved, and it stops
instead of guessing when the numbers look like a parser failure.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qdrant_client import QdrantClient, models  # noqa: E402

from backend.app.config import settings  # noqa: E402
from parser.lex.chunk import chunk_document  # noqa: E402
from parser.lex.client import LexClient  # noqa: E402
from parser.lex.diff import compare, frontmatter  # noqa: E402
from parser.lex.extract import extract_document, to_markdown  # noqa: E402
from parser.lex.watch import WINDOWS, spot_new  # noqa: E402

logger = logging.getLogger("run_update")

REGISTRY_PATH = ROOT / "data" / "registry.jsonl"
RAW_DIR = ROOT / "data" / "raw"
MARKDOWN_DIR = ROOT / "data" / "markdown"
HISTORY_DIR = MARKDOWN_DIR / "history"
CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"
CACHE_DIR = ROOT / "data" / "cache"
UPDATES_DIR = ROOT / "data" / "updates"
QUEUE_PATH = ROOT / "data" / "update_queue.jsonl"
TOUCHED_PATH = ROOT / "data" / "update_chunks.txt"

# one parser regression can rewrite the whole corpus, so a run this large is treated as a
# fault and left for a human to look at
MAX_CHANGED_DOCS = 50
INDEXED_GROUPS = (1, 2, 3)


def load_registry() -> dict[str, dict]:
    if not REGISTRY_PATH.exists():
        return {}
    with REGISTRY_PATH.open(encoding="utf-8") as handle:
        return {json.loads(l)["doc_id"]: json.loads(l) for l in handle if l.strip()}


def save_registry(registry: dict[str, dict]) -> None:
    tmp = REGISTRY_PATH.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in registry.values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(REGISTRY_PATH)


def load_chunks_by_doc() -> dict[str, list[dict]]:
    by_doc: dict[str, list[dict]] = {}
    if not CHUNKS_PATH.exists():
        return by_doc
    with CHUNKS_PATH.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                chunk = json.loads(line)
                by_doc.setdefault(chunk["doc_id"], []).append(chunk)
    return by_doc


def save_chunks(by_doc: dict[str, list[dict]]) -> int:
    tmp = CHUNKS_PATH.with_suffix(".jsonl.tmp")
    total = 0
    with tmp.open("w", encoding="utf-8") as handle:
        for chunks in by_doc.values():
            for chunk in chunks:
                handle.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                total += 1
    tmp.replace(CHUNKS_PATH)
    return total


def archive_markdown(doc_id: str, today: str) -> Path | None:
    """Keep the version being replaced so the diff stays reproducible."""
    current = MARKDOWN_DIR / f"{doc_id}.md"
    if not current.exists():
        return None
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    archived = HISTORY_DIR / f"{doc_id}_{today}.md"
    shutil.copy2(current, archived)
    return archived


def refresh(client: LexClient, record: dict) -> tuple[object, str]:
    """Download the document again and rebuild its Markdown."""
    doc_id = record["doc_id"]
    html = client.get(f"/uz/docs/{doc_id}", use_cache=False)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{doc_id}.html").write_text(html, encoding="utf-8")
    document = extract_document(doc_id, html)
    meta = dict(record) | {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    return document, to_markdown(document, meta)


def mark_repealed(
    qdrant: QdrantClient, doc_id: str, article_nos: list[str] | None, when: str
) -> None:
    """Repealed text is flagged, never removed: 'what did it say before?' stays answerable."""
    must: list[models.Condition] = [
        models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))
    ]
    if article_nos:
        must.append(
            models.FieldCondition(key="article_no", match=models.MatchAny(any=article_nos))
        )
    qdrant.set_payload(
        collection_name=settings.qdrant_collection,
        payload={"status": "R", "valid_to": when},
        points=models.Filter(must=must),
    )


def queue_document(record: dict, reason: str) -> None:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with QUEUE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "doc_id": record["doc_id"],
                    "title": record.get("title"),
                    "reason": reason,
                    "queued_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def select_candidates(args: argparse.Namespace, registry: dict[str, dict]) -> list[dict]:
    """Which documents this run re-checks, cheapest signal first."""
    if args.doc_id:
        return [registry[args.doc_id]] if args.doc_id in registry else []
    if args.check_all:
        return [r for r in registry.values() if r.get("group") in INDEXED_GROUPS]
    if args.check_codes:
        return [r for r in registry.values() if r.get("group") in (1, 2)]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh the corpus from lex.uz")
    parser.add_argument("--window", choices=WINDOWS, default=None, help="read the official feed")
    parser.add_argument("--check-codes", action="store_true", help="re-hash the codes")
    parser.add_argument("--check-all", action="store_true", help="re-hash every indexed document")
    parser.add_argument("--doc-id", default=None, help="re-check a single document")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="report without writing or indexing")
    args = parser.parse_args()

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    if not (args.window or args.check_codes or args.check_all or args.doc_id):
        logger.error("nothing to do: pass --window, --check-codes, --check-all or --doc-id")
        return 1

    today = date.today().isoformat()
    registry = load_registry()
    by_doc = load_chunks_by_doc()
    qdrant = QdrantClient(url=settings.qdrant_url, timeout=120)

    report = {
        "new": [],
        "changed": [],
        "repealed": [],
        "skipped": [],
        "errors": [],
        "out_of_scope": 0,
    }
    touched_chunk_ids: list[str] = []
    # a document reaches the report from two directions, the feed and the re-check loop,
    # so membership is tracked by id rather than by comparing dicts of different shapes
    new_ids: set[str] = set()

    with LexClient(settings.lex_base_url, settings.lex_request_delay, CACHE_DIR) as client:
        candidates = select_candidates(args, registry)

        if args.window:
            for spotted in spot_new(client, args.window):
                if not spotted.in_scope:
                    report["out_of_scope"] += 1
                    continue
                record = spotted.record
                existing = registry.get(record["doc_id"])
                if existing is None:
                    registry[record["doc_id"]] = record
                    report["new"].append(record)
                    new_ids.add(record["doc_id"])
                    candidates.append(record)
                else:
                    existing["status"] = record.get("status", existing.get("status"))
                    candidates.append(existing)

        seen: set[str] = set()
        candidates = [c for c in candidates if not (c["doc_id"] in seen or seen.add(c["doc_id"]))]
        if args.limit is not None:
            candidates = candidates[: args.limit]
        logger.info("%s documents to re-check", len(candidates))

        for record in candidates:
            doc_id = record["doc_id"]
            old_markdown_path = MARKDOWN_DIR / f"{doc_id}.md"
            old_markdown = (
                old_markdown_path.read_text(encoding="utf-8")
                if old_markdown_path.exists()
                else ""
            )

            try:
                document, new_markdown = refresh(client, record)
            except Exception as exc:
                logger.warning("%s: refresh failed: %s", doc_id, exc)
                report["errors"].append({"doc_id": doc_id, "error": str(exc)})
                continue

            old_hash = frontmatter(old_markdown).get("content_hash")
            new_hash = frontmatter(new_markdown).get("content_hash")
            if old_markdown and old_hash == new_hash:
                logger.debug("%s unchanged", doc_id)
                continue

            changes = compare(old_markdown, new_markdown)
            if old_markdown and changes.suspicious:
                logger.error("%s shrank %.0f%%, skipping", doc_id, changes.shrink * 100)
                report["skipped"].append(
                    {"doc_id": doc_id, "reason": f"matn {changes.shrink:.0%} qisqardi"}
                )
                queue_document(record, "suspicious_shrink")
                continue

            entry = {
                "doc_id": doc_id,
                "title": record.get("title", ""),
                "added": changes.added,
                "removed": changes.removed,
                "modified": changes.modified,
            }
            if old_markdown:
                report["changed"].append(entry)
            elif doc_id not in new_ids:
                report["new"].append(record)
                new_ids.add(doc_id)

            if args.dry_run:
                continue

            archive_markdown(doc_id, today)
            MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
            old_version = int(frontmatter(old_markdown).get("version", 1) or 1)
            meta = dict(record) | {
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "version": old_version + 1 if old_markdown else 1,
            }
            old_markdown_path.write_text(to_markdown(document, meta), encoding="utf-8")
            by_doc[doc_id] = chunk_document(document, meta)

            wanted = set(changes.touched)
            for chunk in by_doc[doc_id]:
                if not old_markdown or chunk["article_no"] in wanted or chunk["article_no"] is None:
                    touched_chunk_ids.append(chunk["chunk_id"])

            if changes.removed:
                mark_repealed(qdrant, doc_id, changes.removed, today)
                report["repealed"].append({"doc_id": doc_id, "articles": changes.removed})

            if record.get("status") == "R":
                mark_repealed(qdrant, doc_id, None, today)
                report["repealed"].append({"doc_id": doc_id, "articles": ["butun hujjat"]})

    if len(report["changed"]) > MAX_CHANGED_DOCS:
        logger.error(
            "%s documents changed in one run, above the limit of %s; "
            "this looks like a parser fault, nothing was indexed",
            len(report["changed"]),
            MAX_CHANGED_DOCS,
        )
        write_report(today, report, indexed=0, halted=True)
        return 2

    if args.dry_run:
        write_report(today, report, indexed=0, halted=False, dry_run=True)
        logger.info("dry run: %s new, %s changed", len(report["new"]), len(report["changed"]))
        return 0

    save_registry(registry)
    save_chunks(by_doc)

    indexed = 0
    if touched_chunk_ids:
        TOUCHED_PATH.write_text("\n".join(touched_chunk_ids) + "\n", encoding="utf-8")
        logger.info("re-indexing %s chunks", len(touched_chunk_ids))
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "index.py"), "--chunk-ids", str(TOUCHED_PATH)],
            cwd=ROOT,
        )
        if result.returncode != 0:
            report["errors"].append({"doc_id": "-", "error": "indexatsiya xato bilan tugadi"})
        else:
            indexed = len(touched_chunk_ids)

    write_report(today, report, indexed=indexed, halted=False)
    logger.info(
        "done: %s new, %s changed, %s repealed, %s chunks re-indexed",
        len(report["new"]),
        len(report["changed"]),
        len(report["repealed"]),
        indexed,
    )
    return 0


def write_report(
    today: str, report: dict, indexed: int, halted: bool, dry_run: bool = False
) -> Path:
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    path = UPDATES_DIR / f"{today}.md"

    lines = [f"# Yangilanish hisoboti — {today}", ""]
    if halted:
        lines += [
            f"**TO'XTATILDI.** Bir kunda {len(report['changed'])} hujjat o'zgargan, "
            f"chegara {MAX_CHANGED_DOCS}. Bu parser xatosiga o'xshaydi, "
            "indexatsiya bajarilmadi.",
            "",
        ]
    if dry_run:
        lines += ["_Sinov rejimi: hech narsa yozilmadi._", ""]

    lines += [
        "| Ko'rsatkich | Soni |",
        "|---|---:|",
        f"| Yangi hujjat | {len(report['new'])} |",
        f"| O'zgargan hujjat | {len(report['changed'])} |",
        f"| Kuchini yo'qotgan | {len(report['repealed'])} |",
        f"| O'tkazib yuborilgan | {len(report['skipped'])} |",
        f"| Xato | {len(report['errors'])} |",
        f"| Qamrovdan tashqari | {report['out_of_scope']} |",
        f"| Qayta indexlangan chunk | {indexed} |",
        "",
    ]

    if report["new"]:
        lines += ["## Yangi hujjatlar", ""]
        lines += [f"- `{r['doc_id']}` {r.get('title', '')[:90]}" for r in report["new"]]
        lines.append("")

    if report["changed"]:
        lines += ["## O'zgargan moddalar", ""]
        for entry in report["changed"]:
            lines.append(f"### `{entry['doc_id']}` {entry['title'][:80]}")
            for label, key in (("yangi", "added"), ("tahrirlangan", "modified"), ("olib tashlangan", "removed")):
                if entry[key]:
                    lines.append(f"- {label}: {', '.join(entry[key][:40])}")
            lines.append("")

    if report["repealed"]:
        lines += ["## Kuchini yo'qotganlar", ""]
        lines += [
            f"- `{r['doc_id']}`: {', '.join(r['articles'][:20])}" for r in report["repealed"]
        ]
        lines.append("")

    if report["skipped"]:
        lines += ["## O'tkazib yuborilgan", ""]
        lines += [f"- `{r['doc_id']}`: {r['reason']}" for r in report["skipped"]]
        lines.append("")

    if report["errors"]:
        lines += ["## Xatolar", ""]
        lines += [f"- `{r['doc_id']}`: {r['error'][:120]}" for r in report["errors"]]
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    # the API serves the counts, so it should not have to parse the prose back out
    path.with_suffix(".json").write_text(
        json.dumps(
            {
                "date": today,
                "halted": halted,
                "dry_run": dry_run,
                "new": len(report["new"]),
                "changed": len(report["changed"]),
                "repealed": len(report["repealed"]),
                "skipped": len(report["skipped"]),
                "errors": len(report["errors"]),
                "out_of_scope": report["out_of_scope"],
                "indexed_chunks": indexed,
                "documents": [
                    {"doc_id": e["doc_id"], "title": e["title"], "articles": e["modified"] + e["added"]}
                    for e in report["changed"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    logger.info("report written to %s", path)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
