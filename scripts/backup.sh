#!/usr/bin/env bash
# Qdrant snapshot and SQLite dump. Run this before indexing or an update pass:
# a broken run can then be rolled back instead of re-embedding the whole corpus.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

QDRANT_URL=${QDRANT_URL:-http://localhost:6333}
QDRANT_COLLECTION=${QDRANT_COLLECTION:-uz_legal}
SQLITE_PATH=${SQLITE_PATH:-./data/app.db}
KEEP=${BACKUP_KEEP:-5}

PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "python topilmadi" >&2
    exit 1
fi

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="data/backups/$STAMP"
mkdir -p "$DEST"

echo "Qdrant snapshot: $QDRANT_COLLECTION"
SNAPSHOT=$(curl -sf -X POST "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots" |
    "$PYTHON" -c 'import json,sys; print(json.load(sys.stdin)["result"]["name"])')
curl -sf "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots/$SNAPSHOT" -o "$DEST/$SNAPSHOT"
# the downloaded file is the backup, so the server copy is dropped to save disk
curl -sf -X DELETE "$QDRANT_URL/collections/$QDRANT_COLLECTION/snapshots/$SNAPSHOT" >/dev/null

if [ -f "$SQLITE_PATH" ]; then
    echo "SQLite dump: $SQLITE_PATH"
    "$PYTHON" - "$SQLITE_PATH" "$DEST/app.sql" <<'PY'
import sqlite3
import sys

source, dest = sys.argv[1], sys.argv[2]
# read-only so a running backend is never blocked by the backup
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as conn:
    with open(dest, "w", encoding="utf-8") as handle:
        for line in conn.iterdump():
            handle.write(line + "\n")
PY
else
    echo "SQLite fayli yo'q, o'tkazib yuborildi: $SQLITE_PATH"
fi

if [ -f data/registry.jsonl ]; then
    cp data/registry.jsonl "$DEST/"
fi

find data/backups -mindepth 1 -maxdepth 1 -type d | sort | head -n "-$KEEP" | while read -r old; do
    echo "eski nusxa o'chirildi: $old"
    rm -rf "$old"
done

echo "tayyor: $DEST ($(du -sh "$DEST" | cut -f1))"
