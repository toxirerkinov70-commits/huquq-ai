"""Collect the stems the corpus actually contains.

The agentic path needs to tell a question it can answer from one it cannot, and the
retrieval scores do not carry that: RRF ranks candidates against each other, so the
best of six wrong chunks scores like the best of six right ones. What does separate
them is vocabulary. If no chunk in the corpus contains a word the question is built
around, the answer is not in the base, whatever the ranking says.

Stems rather than whole words: Uzbek is agglutinative, so a question saying
"taqsimlanadi" must still match a corpus that says "taqsimlash".

Rerun after indexing new documents, otherwise a term the corpus has just gained
still looks missing.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.sparse import tokenize  # noqa: E402

logger = logging.getLogger("build_vocab")

CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"
VOCAB_PATH = ROOT / "data" / "corpus_vocab.json"
# a query stem is looked up at its own length, so every length a lookup can ask for
# has to be stored; 5 is where the check tops out
PREFIX_LENGTHS = (3, 4, 5)
FIELDS = ("text", "doc_title", "article_title")


def build(chunks_path: Path) -> dict:
    tokens: set[str] = set()
    lines = 0
    with chunks_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            lines += 1
            chunk = json.loads(line)
            for field in FIELDS:
                value = chunk.get(field)
                if value:
                    tokens.update(tokenize(value))

    vocab = {
        str(length): sorted({token[:length] for token in tokens if len(token) >= length})
        for length in PREFIX_LENGTHS
    }
    logger.info("%s chunks, %s distinct tokens", lines, len(tokens))
    for length in PREFIX_LENGTHS:
        logger.info("  %s-char stems: %s", length, len(vocab[str(length)]))
    return vocab


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, default=CHUNKS_PATH)
    parser.add_argument("--out", type=Path, default=VOCAB_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if not args.chunks.exists():
        logger.error("%s not found", args.chunks)
        return 1

    vocab = build(args.chunks)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(vocab, ensure_ascii=False), encoding="utf-8")
    logger.info("wrote %s (%.2f MB)", args.out, args.out.stat().st_size / 1e6)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
