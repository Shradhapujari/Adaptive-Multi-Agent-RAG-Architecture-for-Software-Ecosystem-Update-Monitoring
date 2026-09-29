#!/usr/bin/env python3
"""Relabel a finished run's pools with a second judge. No pipeline, no corpus.

The first attempt at threat T2 replayed the whole pipeline with a different
judge. That was the wrong shape twice over: it spent hours on retrieval and
generation whose only job was to reproduce what the run already stored, and it
died at question 67 of 100 on a CorpusMiss, because vendor extraction now
resolves a vendor the frozen snapshot never recorded -- the vendor catalog is
live and has drifted since 2026-09-22.

A judge comparison needs labels over the SAME pools, and the run already has
them: pools.jsonl carries every document's id, title, text and source. So ask
the second judge about those documents directly. The pools are identical by
construction rather than by reproduction, there is no corpus to miss, and the
work is one model call per (question, document).

Resumable: it writes after every judgment and skips what it has. A sleeping
laptop costs time, not progress.

    python scripts/rejudge_pools.py [run_dir] --judge ollama:mistral --limit 100
"""
import argparse, json, os, sys, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval_harness.judge import Judge                    # noqa: E402
from eval_harness.run_eval import qrels_key             # noqa: E402

DEFAULT_RUN = ROOT / "results" / "run_1790126271_8fda4edb2d21"


def pool_docs(run_dir, limit):
    """(query, doc) pairs the run judged, with the document text it judged."""
    qrels = json.load(open(os.path.join(run_dir, "qrels.json")))
    keep = set(list(qrels)[:limit]) if limit else set(qrels)
    seen, out = set(), []
    for line in open(os.path.join(run_dir, "pools.jsonl")):
        row = json.loads(line)
        qid = str(row["query_id"])
        if qid not in keep:
            continue
        for d in row.get("docs", []):
            did = d.get("doc_id")
            if did in qrels.get(qid, {}) and (qid, did) not in seen:
                seen.add((qid, did))
                out.append((row["query"], d))
    return out


def main(a):
    pairs = pool_docs(a.run_dir, a.limit)
    cache = json.load(open(a.out)) if os.path.exists(a.out) else {}
    todo = [(q, d) for q, d in pairs if qrels_key(q, d["doc_id"]) not in cache]
    print(f"{len(pairs):,} (question, document) pairs in scope; "
          f"{len(cache):,} already judged; {len(todo):,} to do")
    if not todo:
        print("nothing to do"); return 0

    judge = Judge(a.judge)
    if not judge.available():
        sys.exit(f"judge {a.judge} is not reachable")
    t0 = time.time()
    for i, (q, d) in enumerate(todo, 1):
        cache[qrels_key(q, d["doc_id"])] = judge.relevance_label(q, d)
        json.dump(cache, open(a.out, "w"))          # resumable after every call
        if i % 25 == 0 or i == len(todo):
            rate = i / (time.time() - t0)
            print(f"  {i}/{len(todo)}  {rate*60:.1f}/min  "
                  f"eta {(len(todo)-i)/rate/60:.0f} min", flush=True)
    print(f"wrote {len(cache):,} labels to {a.out}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", default=str(DEFAULT_RUN))
    p.add_argument("--judge", default="ollama:mistral")
    p.add_argument("--limit", type=int, default=0, help="first N questions, 0 = all")
    p.add_argument("--out", default=str(ROOT / "results" / "qrels_mistral.json"))
    sys.exit(main(p.parse_args()))
