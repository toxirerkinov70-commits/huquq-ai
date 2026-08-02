"""Package the corpus so a server does not have to crawl lex.uz to get one.

Rebuilding from scratch is roughly seven hours of fetching (robots.txt asks twenty
seconds between requests) plus three hours of embedding. That is not a deployment step.
This writes a single archive holding the Qdrant snapshot, the registry, the chunks and
the vocabulary; ``import_corpus.py`` puts it back on the other side.

The markdown is included only with --with-markdown: it is the diff baseline for the
update pipeline, useful on a machine that will keep refreshing the corpus and dead
weight on one that only answers questions.
"""

import argparse
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402

DATA = ROOT / "data"
RELEASE_DIR = DATA / "releases"


def _request(url: str, method: str = "GET") -> bytes:
    request = urllib.request.Request(url, method=method)
    if settings.qdrant_api_key:
        request.add_header("api-key", settings.qdrant_api_key)
    with urllib.request.urlopen(request, timeout=600) as response:
        return response.read()


def _snapshot(into: Path) -> str:
    base = f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/snapshots"
    created = json.loads(_request(base, method="POST"))
    name = created["result"]["name"]
    (into / "qdrant.snapshot").write_bytes(_request(f"{base}/{name}"))
    try:
        _request(f"{base}/{name}", method="DELETE")
    except urllib.error.URLError:
        pass
    return name


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def main() -> int:
    parser = argparse.ArgumentParser(description="Korpusni arxivga yig'ish")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--with-markdown", action="store_true")
    args = parser.parse_args()

    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    output = args.output or RELEASE_DIR / f"corpus-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / "corpus"
        staging.mkdir()

        print("Qdrant snapshot olinmoqda...")
        snapshot_name = _snapshot(staging)

        for name in ("registry.jsonl", "chunks.jsonl", "corpus_vocab.json"):
            source = DATA / name
            if source.exists():
                shutil.copy2(source, staging / name)
                print(f"  {name}")

        if args.with_markdown and (DATA / "markdown").exists():
            print("  markdown/ (diff uchun)")
            shutil.copytree(DATA / "markdown", staging / "markdown")

        manifest = {
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "collection": settings.qdrant_collection,
            "snapshot": snapshot_name,
            "embed_model": settings.local_embed_model,
            "embed_dim": settings.embed_dim,
            "documents": _count_lines(DATA / "registry.jsonl"),
            "chunks": _count_lines(DATA / "chunks.jsonl"),
            "includes_markdown": args.with_markdown,
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        print(f"arxivlanmoqda -> {output}")
        with tarfile.open(output, "w:gz") as archive:
            archive.add(staging, arcname="corpus")

    size = output.stat().st_size / 1_048_576
    print(f"tayyor: {output} ({size:.1f} MB)")
    print(f"  {manifest['documents']} hujjat, {manifest['chunks']} chunk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
