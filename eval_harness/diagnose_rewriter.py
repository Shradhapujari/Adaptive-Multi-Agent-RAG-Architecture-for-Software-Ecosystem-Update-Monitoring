"""
Diagnose the Query Rewriter's effect on retrieval.
==================================================
The head-to-head eval showed the multi-agent system (uses the *rewritten*
query) underperforming the single-agent baseline (uses the *raw* query) on the
same retriever. This isolates the cause: it compares retrieval from the raw vs
rewritten query, scored against the same cached relevance judgments (qrels),
and prints what the rewriter actually produced.

Usage:
    venv311/bin/python -m eval_harness.diagnose_rewriter [run_dir]
(defaults to the most recent results/run_*)
"""

from __future__ import annotations

import glob
import json
import os
import sys

from .config import ROOT
from .metrics import ndcg_at_k, mrr


def latest_run() -> str:
    runs = sorted(glob.glob(os.path.join(ROOT, "results", "run_*")), key=os.path.getmtime)
    if not runs:
        raise SystemExit("no results/run_* found")
    return runs[-1]


def main():
    run_dir = sys.argv[1] if len(sys.argv) > 1 else latest_run()
    rows = [json.loads(l) for l in open(os.path.join(run_dir, "per_query.jsonl"))]
    qrels_flat = json.load(open(os.path.join(run_dir, "qrels.json")))

    # index per-query docs by system
    by_q = {}
    for r in rows:
        by_q.setdefault(r["query_id"], {})[r["system"]] = r

    # re-run the rewriter to display what it produced (silenced)
    from .generators import _silenced
    import multiagent_rag_v3 as marag
    rewriter = marag.QueryRewriterAgent()

    def qrels_for(qid):
        pref = f"{qid}:"
        return {k[len(pref):]: v for k, v in qrels_flat.items() if k.startswith(pref)}

    print(f"\nRun: {run_dir}\n")
    print(f"{'#':>2}  {'raw nDCG@3':>10} {'rw nDCG@3':>10}  effect   query → rewrite")
    print("-" * 100)
    raw_scores, rw_scores = [], []
    helped = hurt = tie = 0
    for qid in sorted(by_q):
        sa = by_q[qid].get("single_agent")   # raw query retrieval
        # multi-agent system (label is 'marag'; older runs used 'amara')
        ma = by_q[qid].get("marag") or by_q[qid].get("amara")
        if not sa or not ma:
            continue
        q = qrels_for(qid)
        raw_nd = ndcg_at_k(sa["doc_ids"], q, 3)
        rw_nd = ndcg_at_k(ma["doc_ids"], q, 3)
        raw_scores.append(raw_nd)
        rw_scores.append(rw_nd)
        if rw_nd > raw_nd + 1e-9:
            eff, h = "BETTER", 0; helped += 1
        elif rw_nd < raw_nd - 1e-9:
            eff, h = "WORSE ", 0; hurt += 1
        else:
            eff = "  =   "; tie += 1
        with _silenced(marag):
            rw = rewriter.run(sa["query"])["rewritten"]
        qshort = sa["query"][:42]
        rwshort = rw[:42]
        print(f"{qid:>2}  {raw_nd:>10.3f} {rw_nd:>10.3f}  {eff}  {qshort!r}\n"
              f"{'':>38}→ {rwshort!r}")

    n = len(raw_scores)
    print("-" * 100)
    print(f"\nMean nDCG@3   raw(single_agent) = {sum(raw_scores)/n:.3f}   "
          f"rewritten(marag) = {sum(rw_scores)/n:.3f}   (n={n})")
    print(f"Rewrite helped: {helped}   hurt: {hurt}   tie: {tie}")
    print("\nInterpretation: if 'hurt' >> 'helped' and raw mean > rewritten mean,")
    print("the Query Rewriter is degrading retrieval — a fixable, publishable finding.")


if __name__ == "__main__":
    main()
