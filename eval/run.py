import argparse
import asyncio
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.retrieval import Retriever, SearchFilters  # noqa: E402

QUESTIONS_PATH = ROOT / "eval" / "questions.jsonl"


def load_questions() -> list[dict]:
    with QUESTIONS_PATH.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def rank_of(hits: list, doc_id: str, article_no: str) -> int | None:
    for position, hit in enumerate(hits, start=1):
        payload = hit.payload
        if payload.get("doc_id") == doc_id and payload.get("article_no") == article_no:
            return position
    return None


async def main_async(mode: str, k: int, verbose: bool) -> int:
    questions = load_questions()
    retriever = Retriever()
    rows = []

    try:
        for question in questions:
            if mode == "dense":
                hits = await retriever.dense_search(question["question"], k=k)
            elif mode == "sparse":
                hits = await retriever.sparse_search(question["question"], k=k)
            else:
                hits = await retriever.hybrid_search(
                    question["question"], k=k, filters=SearchFilters()
                )
            rank = rank_of(hits, question["doc_id"], question["article_no"])
            rows.append((question, rank, hits))
            if verbose:
                mark = f"#{rank}" if rank else "topilmadi"
                print(f"\n[{question['kind']}] {question['question']}")
                print(f"   kutilgan: {question['doc_id']} {question['article_no']}-modda -> {mark}")
                for hit in hits[:3]:
                    print(
                        f"     {hit.payload['doc_title'][:34]:<36} "
                        f"{str(hit.payload['article_no']):>6}-modda  ({hit.source})"
                    )
    finally:
        await retriever.close()

    by_kind: dict[str, list[int | None]] = defaultdict(list)
    for question, rank, _ in rows:
        by_kind[question["kind"]].append(rank)
    ranks = [rank for _, rank, _ in rows]

    def report(label: str, values: list[int | None]) -> None:
        total = len(values)
        r5 = sum(1 for r in values if r and r <= 5) / total
        r10 = sum(1 for r in values if r and r <= 10) / total
        mrr = sum(1 / r for r in values if r) / total
        print(f"{label:<12} n={total:<3} recall@5={r5:.2f}  recall@10={r10:.2f}  MRR={mrr:.3f}")

    print(f"\n=== {mode} ===")
    for kind, values in sorted(by_kind.items()):
        report(kind, values)
    report("JAMI", ranks)

    missed = [(q["id"], q["question"]) for q, r, _ in rows if r is None or r > 5]
    if missed:
        print("\ntop-5 ga tushmagan savollar:")
        for qid, text in missed:
            print(f"  {qid}. {text}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval quality")
    parser.add_argument("--mode", choices=("hybrid", "dense", "sparse"), default="hybrid")
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level="WARNING")
    return asyncio.run(main_async(args.mode, args.k, args.verbose))


if __name__ == "__main__":
    raise SystemExit(main())
