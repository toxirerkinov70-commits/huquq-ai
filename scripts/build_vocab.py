"""Collect what the corpus contains, word by word.

The agentic path needs to tell a question it can answer from one it cannot, and the
retrieval scores do not carry that: RRF ranks candidates against each other, so the
best of six wrong chunks scores like the best of six right ones. What does separate
them is vocabulary. If no chunk in the corpus contains a word the question is built
around, the answer is not in the base, whatever the ranking says.

What is written is how many chunks each stem occurs in, which answers both questions
the check asks. Zero means the corpus does not have the word. A small number means the
word is distinctive — it is what the question is about ("mikroqarz", in 273 chunks)
rather than a word every second article uses ("hisob", in 6409). A long question is
mostly the second kind, so when the results miss the first kind the search has drifted
off the subject.

Stems rather than whole words: Uzbek is agglutinative, so a question saying
"taqsimlanadi" must still match a corpus that says "taqsimlash".

Rerun after indexing new documents, otherwise a term the corpus has just gained
still looks missing.
"""

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.sparse import tokenize  # noqa: E402

logger = logging.getLogger("build_vocab")

CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"
VOCAB_PATH = ROOT / "data" / "corpus_vocab.json"
# A query stem is looked up at both lengths. The longer one decides what a word means
# here; the shorter one is the second opinion on whether the corpus knows the word at
# all, which is what keeps an unusual verb ending apart from an unknown subject.
PREFIX_LENGTHS = (4, 5)
FIELDS = ("text", "doc_title", "article_title")


def build(chunks_path: Path) -> dict:
    frequencies: dict[int, Counter] = {length: Counter() for length in PREFIX_LENGTHS}
    tokens: set[str] = set()
    chunks = 0

    with chunks_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            chunks += 1
            chunk = json.loads(line)
            present: set[str] = set()
            for field in FIELDS:
                value = chunk.get(field)
                if value:
                    present.update(tokenize(value))
            tokens.update(present)
            for length in PREFIX_LENGTHS:
                # counted once per chunk, so a word repeated inside one article does
                # not look more widespread than one used across the whole corpus
                frequencies[length].update(
                    {token[:length] for token in present if len(token) >= length}
                )

    vocab = {
        "chunks": chunks,
        "df": {
            str(length): dict(sorted(counter.items()))
            for length, counter in frequencies.items()
        },
    }
    logger.info("%s chunks, %s distinct tokens", chunks, len(tokens))
    for length in PREFIX_LENGTHS:
        logger.info("  %s-char stems: %s", length, len(frequencies[length]))
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
