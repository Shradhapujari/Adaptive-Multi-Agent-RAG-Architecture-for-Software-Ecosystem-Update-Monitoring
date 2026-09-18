#!/usr/bin/env python3
"""Own-post leakage: how much of a run's retrieval score is the question's own
Reddit post being retrieved and judged relevant.

Benchmark questions mined from Reddit titles have a `url`; the live Reddit
endpoints return that very post, and its doc_id is sha1(url). Retrieving the
post that the question was lifted from is not retrieval, it is a lookup of the
answer key. This script recomputes the IR metrics with the own post struck
from both the ranking and the qrels, per system, and reports both views.

    scripts/leak_report.py data/benchmark_300.json results/run_1788302755_7cdc5685d75a
"""
import hashlib, json, statistics as st, sys
from collections import defaultdict
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from eval_harness.metrics import ndcg_at_k, recall_at_k, mrr
from eval_harness.compare import paired_bootstrap, win_tie_loss, holm


def own_ids(url):
    if not url:
        return set()
    v = {url, url.rstrip("/"), url.replace("https://reddit.com", "https://www.reddit.com")}
    return {hashlib.sha1(u.strip().encode()).hexdigest()[:12] for u in v}


def main(bench, run):
    recs = {r["query"]: r for r in json.load(open(bench))}
    qrels = json.load(open(f"{run}/qrels.json"))
    rows = [json.loads(l) for l in open(f"{run}/per_query.jsonl")]
    out = defaultdict(lambda: defaultdict(list))
    leak = {"reddit_qs": 0, "own_in_pool": 0, "own_relevant": 0, "only_own_relevant": 0}
    seen = set()
    for x in rows:
        r = recs[x["query"]]; q = qrels.get(str(r["id"]), {}); own = own_ids(r.get("url"))
        ranked = x["doc_ids"]
        rel = {d for d, v in q.items() if v > 0}
        if x["system"] == "single_agent" and r.get("url") and x["query"] not in seen:
            seen.add(x["query"]); leak["reddit_qs"] += 1
            pool = set(x["pool_doc_ids"]) | set(ranked)
            if own & pool:
                leak["own_in_pool"] += 1
                if own & rel:
                    leak["own_relevant"] += 1
                    if rel <= own: leak["only_own_relevant"] += 1
        q2 = {d: v for d, v in q.items() if d not in own}
        ranked2 = [d for d in ranked if d not in own]
        s = out[x["system"]]
        s["ndcg@3"].append(ndcg_at_k(ranked, q, 3)); s["ndcg@3 (no own post)"].append(ndcg_at_k(ranked2, q2, 3))
        s["recall@5"].append(recall_at_k(ranked, q, 5)); s["recall@5 (no own post)"].append(recall_at_k(ranked2, q2, 5))
        s["mrr"].append(mrr(ranked, q)); s["mrr (no own post)"].append(mrr(ranked2, q2))
        s["own post in top-k"].append(float(bool(own & set(ranked))))
    print(f"{run}: {leak}")
    for sysname, m in out.items():
        print(f"  {sysname:13s} " + "  ".join(f"{k}={st.mean(v):.3f}" for k, v in m.items()))
    # Paired vs single_agent on the leak-free metrics; rows are in question
    # order with all systems present, so index i is the same question.
    base = out["single_agent"]; tests = []
    for sysname in [k for k in out if k != "single_agent"]:
        for k in ("ndcg@3 (no own post)", "recall@5 (no own post)", "mrr (no own post)"):
            a, b = out[sysname][k], base[k]
            bs = paired_bootstrap(a, b, iters=5000, seed=42)
            tests.append((sysname, k, st.mean(a) - st.mean(b), win_tie_loss(a, b), bs["p"]))
    ps = holm([t[4] for t in tests])
    print("  paired vs single_agent (leak-free), Holm across", len(tests))
    for (sysname, k, d, wtl, p), ph in zip(tests, ps):
        print(f"    {sysname:10s} {k:24s} delta={d:+.3f}  W/T/L={wtl}  p_holm={ph:.3f}")


if __name__ == "__main__":
    # Self-check: a redirected www URL and its bare form hash to the same set.
    assert own_ids("https://reddit.com/r/x/1/") & own_ids("https://www.reddit.com/r/x/1/")
    main(sys.argv[1], sys.argv[2])
