"""Build the private held-out decision split. Its output never enters git.

    python build_heldout.py QUESTIONS.json RUN_DIR --after 2026-11-20 [--n 200]

QUESTIONS.json is in benchmark format (id, query, date, reddit_id, ...);
RUN_DIR holds the pools.jsonl of one run over those questions. Kept: only
questions dated after the freeze date, and none whose reddit post or
normalised text appears in any public data/benchmark_*.json. The sheet has
the same rows as data/decision_benchmark_200.jsonl, so annotate.py,
compute_kappa.py and scripts/head_to_head.py read it unchanged.

Run the comparison on it once, report once. A change to decide.py or graph.py
made after seeing these scores voids them.
"""
import argparse
import glob
import json
import os
import sys

from build_decision_benchmark import build, file_hash, load_pools

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "data", "heldout", "decision_heldout.jsonl")


def public_questions() -> list:
    """Every question in a public benchmark file, found from the repo root."""
    paths = [p for p in glob.glob(os.path.join(ROOT, "data", "benchmark_*.json"))
             if not p.endswith(".manifest.json")]
    return [q for p in paths for q in json.load(open(p))]


def _norm(q: str) -> str:
    return " ".join((q or "").lower().split())


def fresh(records: list, public: list, after: str) -> list:
    """Questions strictly after `after` (ISO date) that no public file holds. Undated ones are dropped."""
    seen_posts = {p.get("reddit_id") for p in public if p.get("reddit_id")}
    seen_text = {_norm(p.get("query")) for p in public}
    return [r for r in records
            if (r.get("date") or "") > after
            and r.get("reddit_id") not in seen_posts
            and _norm(r.get("query")) not in seen_text]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("questions")
    ap.add_argument("run_dir")
    ap.add_argument("--after", required=True, help="freeze date, YYYY-MM-DD")
    ap.add_argument("--n", type=int, default=200)
    a = ap.parse_args()
    public = public_questions()
    if not public:
        sys.exit("no public benchmark found: refusing to build a split that excludes nothing")
    records = fresh(json.load(open(a.questions)), public, a.after)
    rows = build(records, load_pools(a.run_dir), n=a.n)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(json.dumps({"n": len(rows), "after": a.after, "kept_before_sampling": len(records),
                      "questions_sha1": file_hash(a.questions), "output": OUT}, indent=2))


if __name__ == "__main__":
    main()
