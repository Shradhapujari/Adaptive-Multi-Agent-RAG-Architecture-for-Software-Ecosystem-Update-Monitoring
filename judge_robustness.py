#!/usr/bin/env python3
"""
Does the finding survive a different judge?
===========================================
Every answer number in this project comes from one LLM judge, `ollama:llama3.1`,
which is also the model driving the Query Rewriter inside the system under
test. That is the standing caveat on the results. This script measures how much
it matters, rather than arguing about it.

Two questions, both answered by re-judging a run's own stored answers with a
second model:

  1. Agreement. On the same (question, answer) pairs, how close are the two
     judges? Reported as mean absolute difference and exact-agreement rate, per
     metric, so a reader can see whether the judges merely differ in calibration
     (a constant offset, harmless to a paired comparison) or in ordering (fatal
     to it).

  2. Robustness of the conclusion. The headline result is a paired difference
     between two arms -- e.g. faithfulness(marag_llm) - faithfulness(marag),
     which isolates answer format because the two arms retrieve identically.
     The script recomputes that difference under the second judge and reports
     whether its sign and significance survive. A finding that flips under a
     different judge is a finding about the judge.

Nothing is re-generated: the answers are read from per_query.jsonl exactly as
the run produced them, so this isolates the judge and changes nothing else.

Usage:
    python judge_robustness.py results/run_<id> --judge ollama:qwen2.5:7b-instruct
    python judge_robustness.py results/run_<id> --judge ollama:qwen2.5:7b-instruct \
        --arms marag_llm,marag --metric faithfulness --sample 40
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import random
import statistics as st
from typing import Dict, List, Optional, Tuple

from eval_harness.judge import Judge
from eval_harness.compare import paired_t_test, win_tie_loss

METRICS = ["faithfulness", "answer_relevance"]


def load_rows(run_dir: str, extra_runs: Optional[List[str]] = None) -> List[dict]:
    """Rows from a run, plus any arms that landed in their own directories."""
    def _read(d):
        with open(os.path.join(d, "per_query.jsonl")) as f:
            return [json.loads(l) for l in f if l.strip()]
    rows = _read(run_dir)
    for extra in (extra_runs or []):
        rows.extend(_read(extra))
    return rows


def load_doc_index(pattern: str) -> Dict[str, dict]:
    """doc_id -> doc, from every pools.jsonl matching `pattern` (first seen wins)."""
    idx: Dict[str, dict] = {}
    for path in sorted(glob.glob(pattern)):
        with open(path) as f:
            for line in f:
                r = json.loads(line)
                for d in (r.get("docs") or []) + (r.get("pool") or []):
                    idx.setdefault(d["doc_id"], d)
    return idx


def contexts_of(row: dict, index: Optional[Dict[str, dict]] = None) -> Optional[List[str]]:
    """What the original judge saw as retrieved context, or None if it cannot
    be rebuilt.

    per_query.jsonl keeps doc_ids, not text. Until 2026-10-25 this fell back to
    "doc:<id>" strings, so the second judge scored faithfulness against ids
    while the first had read the documents -- the judge *and* the evidence
    changed. A row is now judged only when every document's text is found,
    in the row itself or in `index` (pools dumped by other runs)."""
    docs = row.get("docs") or [(index or {}).get(i) for i in row.get("doc_ids", [])]
    if not docs or any(d is None for d in docs):
        return None
    return [f"{d.get('title','')}: {d.get('text','')}" for d in docs]


def rejudge(rows: List[dict], judge: Judge, arms: List[str],
            sample: int, seed: int, gt_by_qid: Optional[dict] = None,
            index: Optional[Dict[str, dict]] = None) -> Dict:
    """Re-score each arm's stored answer with a second judge."""
    by_q: Dict[object, Dict[str, dict]] = collections.defaultdict(dict)
    for r in rows:
        by_q[r["query_id"]][r["system"]] = r

    qids = [q for q, d in by_q.items() if all(a in d for a in arms)]
    unbuilt = [q for q in qids if any(contexts_of(by_q[q][a], index) is None for a in arms)]
    if unbuilt:
        print(f"[contexts] dropping {len(unbuilt)} of {len(qids)} question(s): "
              f"document text not recoverable for at least one arm")
    qids = sorted(set(qids) - set(unbuilt), key=str)
    if sample and sample < len(qids):
        random.Random(seed).shuffle(qids)
        qids = sorted(qids[:sample], key=str)

    out: Dict[object, Dict[str, dict]] = {}
    for i, qid in enumerate(qids, 1):
        out[qid] = {}
        for arm in arms:
            row = by_q[qid][arm]
            gt = (gt_by_qid or {}).get(qid)
            scores = judge.score_answer(row["query"], row["answer"],
                                        contexts_of(row, index), gt)
            out[qid][arm] = scores
        print(f"  [{i}/{len(qids)}] q{qid}", flush=True)
    return {"rejudged": out, "original": by_q, "qids": qids}


def agreement(res: Dict, arms: List[str], metric: str) -> Dict:
    """How close the two judges are on the same answers."""
    pairs = []
    for qid in res["qids"]:
        for arm in arms:
            a = (res["original"][qid][arm].get("answer_scores") or {}).get(metric)
            b = res["rejudged"][qid][arm].get(metric)
            if a is not None and b is not None:
                pairs.append((a, b))
    if not pairs:
        return {"n": 0}
    diffs = [b - a for a, b in pairs]
    return {
        "n": len(pairs),
        "mean_original": st.mean(a for a, _ in pairs),
        "mean_second": st.mean(b for _, b in pairs),
        "mean_signed_diff": st.mean(diffs),
        "mean_abs_diff": st.mean(abs(d) for d in diffs),
        "exact_agreement": sum(1 for d in diffs if d == 0) / len(diffs),
        # Tolerance on the tolerance: 0.4 - 0.3 is 0.10000000000000003 in
        # binary floating point, and a judge-agreement band that excludes it
        # would be reporting an artefact of the representation.
        "within_0.1": sum(1 for d in diffs if abs(d) <= 0.1 + 1e-9) / len(diffs),
    }


def paired_under(res: Dict, arms: List[str], metric: str, which: str) -> Dict:
    """The arms[0] - arms[1] paired difference under one judge."""
    a_vals, b_vals = [], []
    for qid in res["qids"]:
        if which == "original":
            va = (res["original"][qid][arms[0]].get("answer_scores") or {}).get(metric)
            vb = (res["original"][qid][arms[1]].get("answer_scores") or {}).get(metric)
        else:
            va = res["rejudged"][qid][arms[0]].get(metric)
            vb = res["rejudged"][qid][arms[1]].get(metric)
        if va is None or vb is None:
            continue
        a_vals.append(va)
        b_vals.append(vb)
    if len(a_vals) < 2:
        return {"n": len(a_vals)}
    t = paired_t_test(a_vals, b_vals)
    w, tie, l = win_tie_loss(a_vals, b_vals)
    return {"n": len(a_vals), "delta": st.mean(a_vals) - st.mean(b_vals),
            "p": t.get("p"), "wins": w, "ties": tie, "losses": l}


def verdict(orig: Dict, second: Dict, alpha: float = 0.05) -> str:
    """Does the conclusion survive the judge swap?"""
    if not orig.get("n") or not second.get("n"):
        return "not enough paired observations to say"
    same_sign = (orig["delta"] > 0) == (second["delta"] > 0)
    o_sig = (orig.get("p") is not None and orig["p"] < alpha)
    s_sig = (second.get("p") is not None and second["p"] < alpha)
    if same_sign and o_sig and s_sig:
        return "SURVIVES — same direction, significant under both judges"
    if same_sign and o_sig and not s_sig:
        return ("WEAKENS — same direction, but significant only under the "
                "original judge")
    if same_sign:
        return "same direction under both judges; not significant under either"
    return "FLIPS — the two judges disagree on the direction; this is a judge effect"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir")
    ap.add_argument("--judge", required=True, help="second judge spec")
    ap.add_argument("--arms", default="marag_llm,marag",
                    help="the paired comparison to re-test, 'a,b' for a - b")
    ap.add_argument("--metric", default="faithfulness")
    ap.add_argument("--sample", type=int, default=40,
                    help="questions to re-judge (0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="judge_robustness.md")
    ap.add_argument("--extra-run", action="append", default=[], metavar="RUN_DIR",
                    help="fold in arms measured in another run directory")
    ap.add_argument("--pools-from", default="",
                    help="glob of pools.jsonl files to recover document text from "
                         "when the run did not dump its own")
    ap.add_argument("--identical-retrieval", action="store_true",
                    help="restrict to questions where the two arms retrieved "
                         "the identical ranked documents")
    a = ap.parse_args()

    arms = [x.strip() for x in a.arms.split(",")]
    if len(arms) < 2:
        raise SystemExit("--arms takes two or more systems: 'a,b[,c...]'; "
                         "the paired test is the first two")

    judge = Judge(a.judge)
    if not judge.available():
        raise SystemExit(f"judge {judge.spec} is not available "
                         f"(is it pulled? `ollama pull {a.judge.split(':',1)[1]}`)")

    rows = load_rows(a.run_dir, a.extra_run)
    if a.identical_retrieval:
        seen: Dict[object, Dict[str, dict]] = collections.defaultdict(dict)
        for r in rows:
            seen[r["query_id"]][r["system"]] = r
        bad = {q for q, d in seen.items()
               if all(x in d for x in arms) and
               d[arms[0]]["doc_ids"] != d[arms[1]]["doc_ids"]}
        if bad:
            print(f"[filter] dropping {len(bad)} question(s) where the arms "
                  f"retrieved different documents: {sorted(bad, key=str)}")
        rows = [r for r in rows if r["query_id"] not in bad]
    original_judge = "unknown"
    cfg_path = os.path.join(a.run_dir, "config.json")
    if os.path.exists(cfg_path):
        original_judge = json.load(open(cfg_path)).get("judge", "unknown")

    print(f"[re-judging] {a.run_dir} with {judge.spec} "
          f"(original judge: {original_judge})")
    index = load_doc_index(a.pools_from) if a.pools_from else None
    res = rejudge(rows, judge, arms, a.sample, a.seed, index=index)

    L = [f"# Judge robustness — `{os.path.basename(a.run_dir)}`", "",
         f"Original judge: `{original_judge}`  ·  second judge: `{judge.spec}`",
         f"Questions re-judged: {len(res['qids'])}  ·  arms: `{arms[0]}` vs `{arms[1]}`",
         "",
         "Answers are read from the run as produced; only the judge changes.",
         "", "## 1. Agreement between the judges", "",
         "| metric | mean (original) | mean (second) | mean abs diff | exact | within 0.1 |",
         "|---|---|---|---|---|---|"]
    for m in METRICS:
        ag = agreement(res, arms, m)
        if ag.get("n"):
            L.append(f"| {m} | {ag['mean_original']:.3f} | {ag['mean_second']:.3f} | "
                     f"{ag['mean_abs_diff']:.3f} | {ag['exact_agreement']:.0%} | "
                     f"{ag['within_0.1']:.0%} |")
    L += ["", f"## 2. Does `{arms[0]}` − `{arms[1]}` on {a.metric} survive?", "",
          "| judge | Δ | p | W/T/L |", "|---|---|---|---|"]
    o = paired_under(res, arms, a.metric, "original")
    s = paired_under(res, arms, a.metric, "second")
    for label, d in ((original_judge, o), (judge.spec, s)):
        if d.get("n"):
            L.append(f"| `{label}` | {d['delta']:+.3f} | {d['p']:.4f} | "
                     f"{d['wins']}/{d['ties']}/{d['losses']} |")
    L += ["", f"**{verdict(o, s)}**", ""]

    text = "\n".join(L)
    print("\n" + text)
    path = os.path.join(a.run_dir, a.out)
    open(path, "w").write(text + "\n")
    with open(os.path.splitext(path)[0] + ".json", "w") as f:
        json.dump({"judge": judge.spec, "original_judge": original_judge, "arms": arms,
                   "scores": {str(q): v for q, v in res["rejudged"].items()}}, f)
    print(f"[wrote] {path} (+ .json)")


if __name__ == "__main__":
    main()
