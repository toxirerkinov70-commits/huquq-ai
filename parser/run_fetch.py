import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from parser.lex.client import LexClient  # noqa: E402
from parser.lex.fetch import fetch_document, is_fetched  # noqa: E402

logger = logging.getLogger("run_fetch")

REGISTRY_PATH = ROOT / "data" / "registry.jsonl"
RAW_DIR = ROOT / "data" / "raw"
CACHE_DIR = ROOT / "data" / "cache"
FAILED_PATH = ROOT / "data" / "failed.jsonl"

# codes and court practice carry the most answer value per document, so they go first
GROUP_PRIORITY = [1, 2, 9, 6, 3, 4, 5, 7, 8]


def load_registry(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def select_records(records: list[dict], group: int | None) -> list[dict]:
    if group is not None:
        records = [rec for rec in records if rec.get("group") == group]
    order = {number: index for index, number in enumerate(GROUP_PRIORITY)}
    return sorted(records, key=lambda rec: order.get(rec.get("group"), 99))


def write_failed(path: Path, failures: list[dict]) -> None:
    if not failures:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for failure in failures:
            handle.write(json.dumps(failure, ensure_ascii=False) + "\n")


def fetch_all(
    client: LexClient, records: list[dict], concurrency: int, label: str
) -> list[dict]:
    failures: list[dict] = []

    def worker(record: dict) -> dict | None:
        try:
            fetch_document(client, record, RAW_DIR)
        except Exception as exc:
            logger.warning("failed %s: %s", record["doc_id"], exc)
            return {
                "doc_id": record["doc_id"],
                "url": record.get("url"),
                "group": record.get("group"),
                "error": str(exc),
                "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        return None

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for failure in tqdm(
            pool.map(worker, records), total=len(records), desc=label, unit="doc"
        ):
            if failure is not None:
                failures.append(failure)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Download lex.uz document pages")
    parser.add_argument("--group", type=int, default=None, choices=GROUP_PRIORITY)
    parser.add_argument("--limit", type=int, default=None, help="fetch at most N documents")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        choices=(1, 2, 3),
        help="parallel requests; values above 1 exceed the rate declared in robots.txt",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    records = select_records(load_registry(REGISTRY_PATH), args.group)
    if not records:
        logger.error("registry is empty for this selection, run run_discover.py first")
        return 1

    pending = [rec for rec in records if not is_fetched(RAW_DIR, rec["doc_id"])]
    logger.info(
        "%s documents selected, %s already on disk, %s to fetch",
        len(records),
        len(records) - len(pending),
        len(pending),
    )
    if args.limit is not None:
        pending = pending[: args.limit]

    if not pending:
        logger.info("nothing to do")
        return 0

    with LexClient(
        settings.lex_base_url,
        settings.lex_request_delay,
        CACHE_DIR,
        concurrency=args.concurrency,
    ) as client:
        logger.info(
            "effective request spacing: %.2fs, estimated %.1f hours",
            client.delay,
            len(pending) * client.delay / 3600,
        )
        failures = fetch_all(client, pending, args.concurrency, "fetch")

        if failures:
            logger.info("retrying %s failed documents", len(failures))
            retry_records = [{"doc_id": item["doc_id"], "url": item["url"]} for item in failures]
            failures = fetch_all(client, retry_records, args.concurrency, "retry")

    write_failed(FAILED_PATH, failures)
    fetched = sum(1 for rec in records if is_fetched(RAW_DIR, rec["doc_id"]))
    logger.info(
        "done: %s/%s documents on disk, %s failed", fetched, len(records), len(failures)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
