import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402
from parser.lex.client import LexClient  # noqa: E402
from parser.lex.discover import GROUPS, discover_group  # noqa: E402

logger = logging.getLogger("run_discover")

REGISTRY_PATH = ROOT / "data" / "registry.jsonl"
CACHE_DIR = ROOT / "data" / "cache"


def load_registry(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    registry = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                record = json.loads(line)
                registry[record["doc_id"]] = record
    return registry


def save_registry(path: Path, registry: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for record in registry.values():
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    tmp.replace(path)


def merge(registry: dict[str, dict], record: dict) -> str:
    existing = registry.get(record["doc_id"])
    if existing is None:
        registry[record["doc_id"]] = record
        return "new"
    merged = dict(existing)
    # discover only refreshes listing-level fields; okoz/organ are filled during extraction
    for key in ("url", "title", "act_type", "group", "form", "doc_number", "adopted_date", "status", "lang"):
        merged[key] = record[key]
    registry[record["doc_id"]] = merged
    return "updated" if merged != existing else "unchanged"


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect lex.uz document registry")
    parser.add_argument("--group", type=int, required=True, choices=sorted(GROUPS))
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    spec = GROUPS[args.group]
    registry = load_registry(REGISTRY_PATH)
    logger.info("registry loaded: %s documents", len(registry))

    counts = {"new": 0, "updated": 0, "unchanged": 0}
    with LexClient(settings.lex_base_url, settings.lex_request_delay, CACHE_DIR) as client:
        logger.info("effective request delay: %ss", client.delay)
        for record in discover_group(client, spec, max_pages=args.max_pages):
            counts[merge(registry, record)] += 1

    save_registry(REGISTRY_PATH, registry)
    logger.info(
        "group %s done: %s new, %s updated, %s unchanged; registry now %s documents",
        spec.number,
        counts["new"],
        counts["updated"],
        counts["unchanged"],
        len(registry),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
