"""Restore a corpus archive onto a fresh machine.

The counterpart of ``export_corpus.py``. It refuses an archive whose embedding model or
dimension does not match the one this deployment is configured with: the vectors would
load without complaint and every search would then be quietly wrong.
"""

import argparse
import json
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.config import settings  # noqa: E402

DATA = ROOT / "data"


def _upload_snapshot(path: Path) -> None:
    """Multipart upload, hand-built so the script needs nothing but the stdlib."""
    url = (
        f"{settings.qdrant_url}/collections/{settings.qdrant_collection}/snapshots/upload"
        "?priority=snapshot"
    )
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="snapshot"; filename="corpus.snapshot"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    body = head + path.read_bytes() + tail

    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    if settings.qdrant_api_key:
        request.add_header("api-key", settings.qdrant_api_key)
    with urllib.request.urlopen(request, timeout=1800) as response:
        response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description="Korpus arxivini tiklash")
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--force", action="store_true", help="model mos kelmasa ham davom etsin"
    )
    args = parser.parse_args()

    if not args.archive.exists():
        print(f"arxiv topilmadi: {args.archive}", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(args.archive, "r:gz") as archive:
            archive.extractall(tmp)
        staging = Path(tmp) / "corpus"

        manifest = json.loads((staging / "manifest.json").read_text(encoding="utf-8"))
        print(
            f"arxiv: {manifest['documents']} hujjat, {manifest['chunks']} chunk, "
            f"{manifest['created_at']}"
        )

        mismatch = (
            manifest.get("embed_model") != settings.local_embed_model
            or manifest.get("embed_dim") != settings.embed_dim
        )
        if mismatch and not args.force:
            print(
                "Embedding modeli mos kelmadi:\n"
                f"  arxivda: {manifest.get('embed_model')} / {manifest.get('embed_dim')}\n"
                f"  sozlamada: {settings.local_embed_model} / {settings.embed_dim}\n"
                "Vektorlar mos kelmasa qidiruv jimgina noto'g'ri ishlaydi. "
                "Baribir davom etish uchun --force.",
                file=sys.stderr,
            )
            return 2

        DATA.mkdir(parents=True, exist_ok=True)
        for name in ("registry.jsonl", "chunks.jsonl", "corpus_vocab.json"):
            source = staging / name
            if source.exists():
                shutil.copy2(source, DATA / name)
                print(f"  {name}")

        markdown = staging / "markdown"
        if markdown.exists():
            target = DATA / "markdown"
            target.mkdir(parents=True, exist_ok=True)
            for item in markdown.iterdir():
                shutil.copy2(item, target / item.name)
            print("  markdown/")

        print("Qdrant snapshot yuklanmoqda (bu bir necha daqiqa olishi mumkin)...")
        try:
            _upload_snapshot(staging / "qdrant.snapshot")
        except urllib.error.URLError as exc:
            print(f"snapshot yuklanmadi: {exc}", file=sys.stderr)
            return 3

    print(f"tayyor: {settings.qdrant_collection} kolleksiyasi tiklandi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
