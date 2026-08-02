"""Qdrant snapshot and SQLite dump, before indexing or an update pass.

Replaces the shell version: the scheduler calls this from inside a container on Linux and
from the development machine on Windows, and one of those has no bash.
"""

import argparse
import json
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402

BACKUP_DIR = ROOT / "data" / "backups"


def _request(url: str, method: str = "GET") -> bytes:
    request = urllib.request.Request(url, method=method)
    if settings.qdrant_api_key:
        request.add_header("api-key", settings.qdrant_api_key)
    with urllib.request.urlopen(request, timeout=300) as response:
        return response.read()


def snapshot_qdrant(destination: Path) -> str | None:
    base = f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/snapshots"
    try:
        created = json.loads(_request(base, method="POST"))
        name = created["result"]["name"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError) as exc:
        print(f"Qdrant snapshot olinmadi: {exc}", file=sys.stderr)
        return None

    payload = _request(f"{base}/{name}")
    (destination / name).write_bytes(payload)
    # the downloaded file is the backup, so the server copy is dropped to save disk
    try:
        _request(f"{base}/{name}", method="DELETE")
    except urllib.error.URLError:
        pass
    print(f"Qdrant snapshot: {name} ({len(payload) / 1_048_576:.1f} MB)")
    return name


def dump_sqlite(destination: Path) -> bool:
    source = Path(settings.sqlite_path)
    if not source.exists():
        print(f"SQLite fayli yo'q, o'tkazib yuborildi: {source}")
        return False
    # read-only so a running backend is never blocked by the backup
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as connection:
        with (destination / "app.sql").open("w", encoding="utf-8") as handle:
            for line in connection.iterdump():
                handle.write(line + "\n")
    print(f"SQLite dump: {source}")
    return True


def prune(keep: int) -> None:
    existing = sorted(path for path in BACKUP_DIR.iterdir() if path.is_dir())
    for old in existing[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
        print(f"eski nusxa o'chirildi: {old.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Qdrant snapshot va SQLite dump")
    parser.add_argument("--keep", type=int, default=5, help="nechta nusxa saqlansin")
    args = parser.parse_args()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = BACKUP_DIR / stamp
    destination.mkdir(parents=True, exist_ok=True)

    ok = snapshot_qdrant(destination) is not None
    dump_sqlite(destination)

    registry = ROOT / "data" / "registry.jsonl"
    if registry.exists():
        shutil.copy2(registry, destination / registry.name)

    prune(args.keep)
    total = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    print(f"tayyor: {destination} ({total / 1_048_576:.1f} MB)")
    # a missing snapshot is a failure the caller must see: the scheduler runs an update
    # right after this and there would be nothing to roll back to
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
