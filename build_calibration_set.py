"""Build the human-judge calibration set: 100 (question, document) pairs.

    python build_calibration_set.py

The relevance judge (Qwen 2.5 7B, 0/1/2) agreed with a second judge at
kappa 0.370, and part of that is a fetch bug (empty-body rows disagreed 43%
against 21%). Before the judge's labels carry weight in any metric, two
humans label 100 pairs blind and we report human-human and human-judge
kappa per stratum. Where the judge falls short of the humans' own agreement,
that stratum gets human labels or is excluded and said so.

Pairs come from run_1790126271 (frozen corpus, all three arms, pools
dumped), the same run the decision sheet draws its evidence from. Strata are
the four attributes the state machine's gate reads (graph.asks: version /
date / stance / cve) by three source tiers (tier1 vendor + advisory feeds,
community, news). Twelve cells, filled round-robin in (query_id, doc_id)
order -- deterministic, no RNG -- so a cell with few pairs (cve questions
are rare) simply contributes what it has, and the manifest says so.

The judge's label for each pair is written to a separate key file so the
sheet itself is blind; compute_kappa.py joins them back.
"""
import hashlib
import json
import os
import sys
from collections import Counter, OrderedDict

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from graph import asks  # noqa: E402

RUN = "results/run_1790126271_8fda4edb2d21"
OUT = "data/calibration_100.jsonl"
KEY = "data/calibration_100.judge.json"
N = 100
ATTRS = ("version", "date", "stance", "cve")
TIER = {"vendor_releases": "tier1", "releases": "tier1", "llm_releases": "tier1",
        "apple_rss": "tier1", "cisa_kev": "tier1", "circl_cve": "tier1", "nvd": "tier1",
        "cve": "tier1", "vendor_reddit": "community", "reddit_live": "community",
        "reddit_search": "community", "google_news": "news"}
SCALE = {2: "answers the question directly", 1: "related: same product/area, not a direct answer",
         0: "irrelevant"}


def load_pairs(run_dir: str) -> list:
    """Every judged (question, document) pair with its document text."""
    qrels = json.load(open(os.path.join(run_dir, "qrels.json")))
    docs, queries = {}, {}
    with open(os.path.join(run_dir, "pools.jsonl")) as f:
        for line in f:
            r = json.loads(line)
            queries[str(r["query_id"])] = r["query"]
            for d in r["docs"] + r.get("pool", []):
                if isinstance(d, dict) and d.get("doc_id"):
                    docs.setdefault(d["doc_id"], d)
    pairs = []
    for qid, labels in qrels.items():
        q = queries.get(qid)
        for did, lab in labels.items():
            d = docs.get(did)
            if q is None or d is None or TIER.get(d.get("source")) is None:
                continue
            pairs.append({"query_id": int(qid), "query": q, "asks": asks(q),
                          "tier": TIER[d["source"]], "judge": int(lab),
                          "doc": {k: d.get(k, "") for k in ("doc_id", "source", "title", "url", "date")}
                          | {"text": (d.get("text") or "")[:600]}})
    return sorted(pairs, key=lambda p: (p["query_id"], p["doc"]["doc_id"]))


def select(pairs: list, n: int = N) -> list:
    """Round-robin over attribute x tier cells; at most one pair per question
    per cell so a long pool does not fill a cell with one question."""
    cells: "OrderedDict[tuple, list]" = OrderedDict(((a, t), []) for a in ATTRS
                                                    for t in ("tier1", "community", "news"))
    seen_q: dict = {}
    for p in pairs:
        key = (p["asks"], p["tier"])
        if key in cells and p["query_id"] not in seen_q.setdefault(key, set()):
            cells[key].append(p); seen_q[key].add(p["query_id"])
    out: list = []
    while len(out) < n and any(cells.values()):
        for key in cells:
            if cells[key] and len(out) < n:
                out.append(cells[key].pop(0))
    return out


def main() -> None:
    os.chdir(ROOT)
    picked = select(load_pairs(RUN))
    slot = {"relevance": None, "note": ""}
    with open(OUT, "w") as f:
        for i, p in enumerate(picked, 1):
            row = {"id": i, "query_id": p["query_id"], "query": p["query"], "asks": p["asks"],
                   "tier": p["tier"], "doc": p["doc"], "scale": SCALE,
                   "a1": dict(slot), "a2": dict(slot)}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    json.dump({str(i): p["judge"] for i, p in enumerate(picked, 1)}, open(KEY, "w"), indent=0)
    sha = lambda f: hashlib.sha1(open(f, "rb").read()).hexdigest()[:12]
    manifest = {"n": len(picked), "run": RUN, "run_config_sha1": sha(os.path.join(RUN, "config.json")),
                "cells": {f"{a}/{t}": c for (a, t), c in
                          sorted(Counter((p["asks"], p["tier"]) for p in picked).items())},
                "judge_label_dist": dict(sorted(Counter(p["judge"] for p in picked).items())),
                "questions": len({p["query_id"] for p in picked}),
                "output_sha1": sha(OUT), "judge_key_sha1": sha(KEY)}
    json.dump(manifest, open(OUT.replace(".jsonl", ".manifest.json"), "w"), indent=2)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
