#!/usr/bin/env python3
"""Compare arms that ran in *different* runs, against one pooled qrels set.

`eval_harness/compare.py` pairs arms inside a single run, where every arm
shares that run's per-question judged pool. An arm measured on its own -- a
control run with one generator -- carries a narrower pool, so its nDCG is
computed against a smaller IDCG and is not on the same scale as an arm from a
three-arm run. Comparing the two as printed would read a pooling difference as
an effect.

This merges the `qrels.json` of every run named, takes the union per question
(a document judged in either run keeps its label; a document no run judged
counts 0, as in TREC pooling), and re-scores every arm's own ranked list
against that union. All arms then share one denominator.

    python scripts/cross_run_compare.py \
        --arm run_A:marag_llm --arm run_B:single_agent --baseline single_agent

Arms are named <run dir>:<system>. Metrics are recomputed from `doc_ids` in
per_query.jsonl, not read from the `ir` block the run wrote.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_harness.compare import paired_bootstrap, win_tie_loss, holm  # noqa: E402
from eval_harness.metrics import retrieval_metrics  # noqa: E402

KS = (1, 3, 5)
METRICS = ("ndcg@1", "ndcg@3", "ndcg@5", "recall@5", "mrr")


def load_run(run_dir: str):
    qrels = json.load(open(os.path.join(run_dir, "qrels.json")))
    rows = [json.loads(l) for l in open(os.path.join(run_dir, "per_query.jsonl"))]
    return qrels, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True,
                    help="<run dir>:<system name>, repeatable")
    ap.add_argument("--baseline", required=True,
                    help="system name of the arm to compare the others against")
    ap.add_argument("--label", action="append", default=[],
                    help="display name per --arm, in the same order")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--bootstrap", type=int, default=10000)
    args = ap.parse_args()

    specs = [a.rsplit(":", 1) for a in args.arm]
    labels = args.label or [f"{os.path.basename(d)}:{s}" for d, s in specs]
    if len(labels) != len(specs):
        ap.error("--label must be given once per --arm")

    # pooled qrels: union over every run named, per question id
    pooled: dict = {}
    caches = {}
    for run_dir, _ in specs:
        if run_dir in caches:
            continue
        caches[run_dir] = load_run(run_dir)
        for qid, labs in caches[run_dir][0].items():
            # max, not last-wins: the same judge can label one document
            # differently in two runs, and the pool must not depend on the
            # order the runs were named in.
            q = pooled.setdefault(str(qid), {})
            for d, g in labs.items():
                q[d] = max(q.get(d, 0), g)

    # re-score each arm against the pooled set
    scored: dict = {}
    for (run_dir, sysname), label in zip(specs, labels):
        _, rows = caches[run_dir]
        per_q = {}
        for r in rows:
            if r["system"] != sysname:
                continue
            qid = str(r["query_id"])
            qrels = pooled.get(qid, {})
            per_q[qid] = retrieval_metrics(r.get("doc_ids") or [], qrels, KS)
        scored[label] = per_q
        print(f"[pooled] {label}: {len(per_q)} questions", file=sys.stderr)

    base_label = next((l for (d, s), l in zip(specs, labels) if s == args.baseline
                       and l.endswith(args.baseline)), None)
    if base_label is None:
        base_label = [l for (d, s), l in zip(specs, labels) if s == args.baseline][0]

    common = set.intersection(*(set(v) for v in scored.values()))
    qids = sorted(common, key=lambda x: (len(x), x))
    print(f"\nPooled over {len(pooled)} questions; "
          f"{len(qids)} answered by every arm. Baseline: {base_label}\n")

    rows_out = []
    for metric in METRICS:
        for label, per_q in scored.items():
            if label == base_label:
                continue
            a = [scored[label][q][metric] for q in qids]
            b = [scored[base_label][q][metric] for q in qids]
            bs = paired_bootstrap(a, b, iters=args.bootstrap, seed=args.seed)
            w, t, l = win_tie_loss(a, b)
            rows_out.append({"metric": metric, "arm": label,
                             "mean": sum(a) / len(a), "base": sum(b) / len(b),
                             "d": bs["mean_diff"], "lo": bs["ci_low"],
                             "hi": bs["ci_high"], "p": bs["p"], "wtl": (w, t, l)})
    for p_adj, r in zip(holm([r["p"] for r in rows_out]), rows_out):
        r["p_holm"] = p_adj

    print(f"| {'metric':9} | {'arm':34} | {'mean':>6} | {'base':>6} | "
          f"{'delta':>7} | {'95% CI':>18} | {'p_holm':>8} | W/T/L |")
    print("|" + "-" * 11 + "|" + "-" * 36 + "|" + "-" * 8 + "|" + "-" * 8
          + "|" + "-" * 9 + "|" + "-" * 20 + "|" + "-" * 10 + "|-------|")
    for r in rows_out:
        ci = f"[{r['lo']:+.3f}, {r['hi']:+.3f}]"
        w, t, l = r["wtl"]
        print(f"| {r['metric']:9} | {r['arm']:34} | {r['mean']:6.3f} | "
              f"{r['base']:6.3f} | {r['d']:+7.3f} | {ci:>18} | "
              f"{r['p_holm']:8.3f} | {w}/{t}/{l} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
