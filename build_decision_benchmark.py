"""Build the decision-labelled benchmark: 200 questions, an evidence pool each,
and empty verdict slots for two annotators.

    python build_decision_benchmark.py

Retrieval metrics cannot separate the arms (nDCG@3 0.30 for every arm at
n=500 and n=1000), so the output type moves to a decision. That needs gold
*verdicts*, which no existing file carries (72 of 500 questions have any
ground_truth at all). This writes the sheet the annotators fill in.

Questions: data/benchmark_500.json, 200 taken by the harness's own
`stratified_limit` over category then ecosystem -- deterministic, no RNG, and
the same balance the benchmark was built for. Each question is also tagged
with the attribute it asks for (version / date / stance / cve / other) by
`graph.asks`, the same gate the state machine routes on, so kappa can be reported per stratum later.

Evidence: every document any arm retrieved or pooled for that question in
run_1790126271 (frozen corpus, flat ranking, exclude_own_post, all three
arms), deduplicated by doc_id. Annotators label from this pool and cite
doc_ids, which makes the evidence obligation rule-checkable: a verdict other
than insufficient_evidence must cite at least one doc_id from the pool.

Labels (three, agreed 2026-10-09): act / hold / insufficient_evidence.
See docs/decision_annotation_guide.md.
"""
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from eval_harness.benchmarks import stratified_limit  # noqa: E402
from graph import asks  # noqa: E402

BENCHMARK = "data/benchmark_500.json"
POOL_RUN = "results/run_1790126271_8fda4edb2d21"
OUT = "data/decision_benchmark_200.jsonl"
N = 200
VERDICTS = ("act", "hold", "insufficient_evidence")

def load_pools(run_dir: str) -> dict:
    """query_id -> [doc, ...], every arm's retrieved + pooled docs, deduped."""
    pools: dict = {}
    with open(os.path.join(run_dir, "pools.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            seen = pools.setdefault(r["query_id"], {})
            for d in r["docs"] + r.get("pool", []):
                if isinstance(d, dict) and d.get("doc_id") and d["doc_id"] not in seen:
                    seen[d["doc_id"]] = {k: d.get(k, "") for k in
                                         ("doc_id", "source", "title", "url", "date")} | {
                        "text": (d.get("text") or "")[:400]}
    return {q: list(v.values()) for q, v in pools.items()}


def file_hash(path: str) -> str:
    return hashlib.sha1(open(path, "rb").read()).hexdigest()[:12]


def build(records: list, pools: dict, n: int = N) -> list:
    picked = stratified_limit(records, n, key="category,ecosystem")
    slot = {"verdict": None, "evidence_doc_ids": [], "note": ""}
    rows = []
    for r in sorted(picked, key=lambda r: r["id"]):
        rows.append({
            "id": r["id"], "query": r["query"], "category": r["category"],
            "ecosystem": r["ecosystem"], "vendor": r.get("vendor", ""),
            "asks": asks(r["query"]), "context": (r.get("context") or "")[:400],
            "evidence": pools.get(r["id"], []),
            "a1": dict(slot, evidence_doc_ids=[]), "a2": dict(slot, evidence_doc_ids=[]),
        })
    return rows


def main() -> None:
    os.chdir(ROOT)
    records = json.load(open(BENCHMARK))
    pools = load_pools(POOL_RUN)
    rows = build(records, pools)
    with open(OUT, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    manifest = {
        "n": len(rows), "verdicts": VERDICTS,
        "benchmark": BENCHMARK, "benchmark_sha1": file_hash(BENCHMARK),
        "pool_run": POOL_RUN, "pool_run_config_sha1": file_hash(os.path.join(POOL_RUN, "config.json")),
        "stratify": "category,ecosystem",
        "categories": dict(Counter(r["category"] for r in rows)),
        "asks": dict(Counter(r["asks"] for r in rows)),
        "ecosystems": len({r["ecosystem"] for r in rows}),
        "empty_pool": sum(1 for r in rows if not r["evidence"]),
        "median_pool": sorted(len(r["evidence"]) for r in rows)[len(rows) // 2],
        "output_sha1": file_hash(OUT),
    }
    json.dump(manifest, open(OUT.replace(".jsonl", ".manifest.json"), "w"), indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
