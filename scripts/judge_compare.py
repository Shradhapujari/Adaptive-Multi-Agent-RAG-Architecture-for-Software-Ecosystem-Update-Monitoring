#!/usr/bin/env python3
"""Two judges over one run: does the ordering survive, and do they agree?

Threat T2 is that llama3.1 judges a pipeline it also generates for. The test is
`scripts/phase_judge.sh`, which replays a frozen run with gpt-4o and changes
nothing else. This reads the result.

Two questions, and they are not the same question:

  1. Does the ORDERING survive? That is the claim the paper rests on, and the
     agreement literature it cites says run-level ordering is what LLM labels
     are usable for (Kendall's tau 0.77-0.94).
  2. Do the judges agree per label? Expected to be poor -- published kappa is
     0.26-0.37 -- and Section 5.5 already says so. A low kappa here is not a
     finding, it is the literature. A changed ordering is a finding.

Metrics come from eval_harness.metrics, the same functions the run used, so a
number here is comparable with a number in the paper. Per question, each judge
scores the SAME pool: the doc_ids the run judged. A question either judge has
not labelled in full is dropped from both, so the two columns always describe
one question set.

    python scripts/judge_compare.py [run_dir] [--b <gpt4o qrels_cache.json>]
    python scripts/judge_compare.py --selfcheck
"""
import argparse, json, os, sys, collections, pathlib, tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from eval_harness.metrics import ndcg_at_k, recall_at_k, mrr, mean_ci   # noqa: E402
from eval_harness.run_eval import qrels_key                             # noqa: E402

DEFAULT_RUN = ROOT / "results" / "run_1790126271_8fda4edb2d21"
DEFAULT_B = ROOT.parent / "marag-judge-wt" / "results" / "qrels_cache.json"

# Below this, a paired difference is a tie rather than a lead. The paper's own
# smallest reported difference is 0.006 and it calls that indistinguishable.
EPS = 0.002


def kappa(pairs):
    """Cohen's kappa over (label_a, label_b) pairs."""
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in pairs) / n
    ra = collections.Counter(a for a, _ in pairs)
    rb = collections.Counter(b for _, b in pairs)
    pe = sum(ra[k] * rb[k] for k in set(ra) | set(rb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def load(run_dir, cache_b_path):
    rows = [json.loads(l) for l in open(os.path.join(run_dir, "per_query.jsonl"))]
    pools = json.load(open(os.path.join(run_dir, "qrels.json")))      # judge A, as run
    cache_b = json.load(open(cache_b_path))
    text = {str(r["query_id"]): r["query"] for r in rows}
    ranked = {(str(r["query_id"]), r["system"]): r["doc_ids"] for r in rows}
    return rows, pools, cache_b, text, ranked


def compare(pools, cache_b, text, ranked, systems):
    # a question counts only when judge B labelled every document A judged
    covered, labels = [], []
    qrels_b = {}
    for qid, pool in pools.items():
        if qid not in text:
            continue
        b = {}
        for doc, ga in pool.items():
            gb = cache_b.get(qrels_key(text[qid], doc))
            if gb is None:
                b = None
                break
            b[doc] = int(gb)
            labels.append((int(ga), int(gb)))
        if b is not None and pool:
            covered.append(qid)
            qrels_b[qid] = b
    # the per-label pairs of dropped questions are not evidence about agreement
    labels = [p for qid in covered for p in
              zip((int(g) for g in pools[qid].values()),
                  (qrels_b[qid][d] for d in pools[qid]))]

    out = {"covered": covered, "n_pool": len(pools), "labels": labels}
    for name, qrels in (("A", pools), ("B", qrels_b)):
        per_system = {}
        for s in systems:
            vals = collections.defaultdict(list)
            for qid in covered:
                r = ranked.get((qid, s))
                if r is None:
                    continue
                q = {d: int(g) for d, g in qrels[qid].items()}
                vals["nDCG@3"].append(ndcg_at_k(r, q, 3))
                vals["nDCG@5"].append(ndcg_at_k(r, q, 5))
                vals["Recall@5"].append(recall_at_k(r, q, 5))
                vals["MRR"].append(mrr(r, q))
            per_system[s] = {m: mean_ci(v)[0] for m, v in vals.items()}
        out[name] = per_system
    return out


def report(res, systems, baseline):
    cov, pool_n = len(res["covered"]), res["n_pool"]
    print(f"questions both judges labelled in full: {cov} of {pool_n}")
    if not cov:
        print("nothing to compare -- has the gpt-4o run been done?")
        return 1
    lab = res["labels"]
    print(f"labels compared: {len(lab):,}")
    print(f"  Cohen's kappa, graded (0/1/2): {kappa(lab):.3f}")
    print(f"  Cohen's kappa, binary (>=1)  : "
          f"{kappa([(a >= 1, b >= 1) for a, b in lab]):.3f}")
    print(f"  exact agreement              : {sum(a == b for a, b in lab)/len(lab):.1%}")
    print("\n  (low per-label kappa is the literature, not a finding; the "
          "ordering below is the finding)\n")

    metrics = [m for m in ("nDCG@3", "nDCG@5", "Recall@5", "MRR")
               if m in next(iter(res["A"].values()))]
    print(f"{'metric':<10} {'system':<28} {'judge A':>9} {'judge B':>9}   ordering")
    changed = []
    for m in metrics:
        base_a = res["A"][baseline][m]
        base_b = res["B"][baseline][m]
        for s in systems:
            if s == baseline:
                continue
            a, b = res["A"][s][m], res["B"][s][m]
            da, db = a - base_a, b - base_b
            # A tie is not a reversed ordering. The first version of this called
            # +0.006 -> +0.000 a CHANGE, which would have reported a finding out
            # of a lead shrinking into a tie under a judge that scored every arm
            # identically. A flip is a sign change with both sides off zero.
            flip = ("CHANGED" if (da > EPS and db < -EPS) or (da < -EPS and db > EPS)
                    else "tie" if abs(da) <= EPS and abs(db) <= EPS else "same")
            if flip == "CHANGED":
                changed.append((m, s, da, db))
            print(f"{m:<10} {s:<28} {a:>9.3f} {b:>9.3f}   "
                  f"{da:+.3f} vs {db:+.3f}  {flip}")
        print(f"{'':<10} {baseline + ' (baseline)':<28} {base_a:>9.3f} {base_b:>9.3f}")
    print()
    if changed:
        print("ORDERING CHANGED under the independent judge:")
        for m, s, da, db in changed:
            print(f"  {m}: {s} was {da:+.3f} under A, {db:+.3f} under B")
        print("That is a finding. Section 5.5 currently states the threat; it "
              "would have to state a result instead.")
    else:
        print("Every ordering survives the independent judge. That is what "
              "Section 5.5 needs, and it is reportable whatever kappa says.")
    return 0


def selfcheck():
    """Synthetic run + synthetic second judge, with a known answer."""
    with tempfile.TemporaryDirectory() as d:
        rows, pools, cache_b = [], {}, {}
        for i in range(10):
            qid, q = str(i), f"question {i}"
            good, bad = f"g{i}", f"b{i}"
            pools[qid] = {good: 2, bad: 0}
            # judge B agrees on every label except one question's bad doc
            cache_b[qrels_key(q, good)] = 2
            cache_b[qrels_key(q, bad)] = 2 if i == 0 else 0
            for s, order in (("sys_good", [good, bad]), ("sys_bad", [bad, good])):
                rows.append({"query_id": qid, "query": q, "system": s,
                             "doc_ids": order})
        open(os.path.join(d, "per_query.jsonl"), "w").write(
            "\n".join(json.dumps(r) for r in rows))
        json.dump(pools, open(os.path.join(d, "qrels.json"), "w"))
        cb = os.path.join(d, "cache_b.json")
        json.dump(cache_b, open(cb, "w"))

        _, pools, cache_b, text, ranked = load(d, cb)
        res = compare(pools, cache_b, text, ranked, ["sys_good", "sys_bad"])
        assert len(res["covered"]) == 10, res["covered"]
        assert len(res["labels"]) == 20, len(res["labels"])
        k = kappa(res["labels"])
        assert 0.85 < k < 1.0, f"one disagreement in twenty should dent kappa, got {k}"
        # sys_good ranks the relevant document first under either judge
        assert res["A"]["sys_good"]["nDCG@3"] > res["A"]["sys_bad"]["nDCG@3"]
        assert res["B"]["sys_good"]["nDCG@3"] > res["B"]["sys_bad"]["nDCG@3"]
        # a judge that inverts every label must flip the ordering
        flipped = {k2: (2 - v) for k2, v in json.load(open(cb)).items()}
        json.dump(flipped, open(cb, "w"))
        _, pools, cache_b, text, ranked = load(d, cb)
        res2 = compare(pools, cache_b, text, ranked, ["sys_good", "sys_bad"])
        assert res2["B"]["sys_good"]["nDCG@3"] < res2["B"]["sys_bad"]["nDCG@3"], \
            "an inverting judge must change the ordering, or this script is blind"

    # a lead shrinking to a tie is NOT a flip -- the false alarm this script
    # raised on its first real data, before EPS existed
    fake = {"A": {"x": {"nDCG@3": 0.508}, "base": {"nDCG@3": 0.502}},
            "B": {"x": {"nDCG@3": 0.190}, "base": {"nDCG@3": 0.190}},
            "covered": ["1"], "n_pool": 1, "labels": [(1, 1)]}
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(fake, ["x", "base"], "base")
    assert "nDCG@3" in buf.getvalue(), "no rows printed -- this test would pass vacuously"
    assert "CHANGED" not in buf.getvalue(), "a lead going to a tie is not a flip"

    # a genuine reversal must still be caught
    real = {"A": {"x": {"nDCG@3": 0.520}, "base": {"nDCG@3": 0.500}},
            "B": {"x": {"nDCG@3": 0.480}, "base": {"nDCG@3": 0.500}},
            "covered": ["1"], "n_pool": 1, "labels": [(1, 1)]}
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        report(real, ["x", "base"], "base")
    assert "CHANGED" in buf2.getvalue(), "a real sign reversal must be reported"
    print("selfcheck ok")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("run_dir", nargs="?", default=str(DEFAULT_RUN))
    p.add_argument("--b", default=str(DEFAULT_B), help="the independent judge's qrels cache")
    p.add_argument("--baseline", default="single_agent")
    p.add_argument("--selfcheck", action="store_true")
    a = p.parse_args()
    if a.selfcheck:
        selfcheck(); sys.exit(0)
    if not os.path.exists(a.b):
        sys.exit(f"no independent-judge cache at {a.b} -- run scripts/phase_judge.sh first")
    rows, pools, cache_b, text, ranked = load(a.run_dir, a.b)
    systems = sorted({r["system"] for r in rows})
    sys.exit(report(compare(pools, cache_b, text, ranked, systems), systems, a.baseline))
