import logging
from pathlib import Path

from .client import LexClient

logger = logging.getLogger(__name__)

# lex.uz renders the act body inside these containers; their absence means we got an
# error page or an interstitial rather than the document itself
BODY_MARKERS = ("divCont", "ACT_TEXT")
MIN_DOCUMENT_BYTES = 5000


class FetchError(RuntimeError):
    pass


def raw_path(raw_dir: Path, doc_id: str) -> Path:
    return Path(raw_dir) / f"{doc_id}.html"


def is_fetched(raw_dir: Path, doc_id: str) -> bool:
    path = raw_path(raw_dir, doc_id)
    return path.exists() and path.stat().st_size >= MIN_DOCUMENT_BYTES


def looks_like_document(html: str) -> bool:
    return len(html) >= MIN_DOCUMENT_BYTES and any(marker in html for marker in BODY_MARKERS)


def fetch_document(client: LexClient, record: dict, raw_dir: Path) -> Path:
    """Download one document page and store it verbatim under data/raw/."""
    doc_id = record["doc_id"]
    path = raw_path(raw_dir, doc_id)
    # the raw file is the archive of record, so the shared response cache is bypassed
    html = client.get(f"/uz/docs/{doc_id}", use_cache=False)
    if not looks_like_document(html):
        raise FetchError(f"{doc_id}: response is not a document page ({len(html)} bytes)")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".html.tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(path)
    return path
