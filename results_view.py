"""Read-only view over evaluation runs in results/<run_id>/ for the app.

Nothing here re-runs an eval; the harness does that in minutes and belongs in
`eval_harness.run_eval`. This only answers "which questions did well, and why".
"""
import csv
import glob
import json
import os
from collections import defaultdict
from typing import Dict, List

import intent
import vendor

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
FEEDBACK_PATH = os.path.join(RESULTS_DIR, "ui_feedback.jsonl")


def list_runs() -> List[str]:
    """Run ids that have a per_query.jsonl, newest first."""
    runs = [os.path.basename(os.path.dirname(p))
            for p in glob.glob(os.path.join(RESULTS_DIR, "run_*", "per_query.jsonl"))]
    return sorted(runs, reverse=True)


def load_run(run_id: str) -> Dict:
    d = os.path.join(RESULTS_DIR, run_id)
    with open(os.path.join(d, "per_query.jsonl"), encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]
    agg = []
    try:
        with open(os.path.join(d, "aggregate.csv"), encoding="utf-8") as fh:
            agg = list(csv.DictReader(fh))
    except OSError:
        pass
    catalog = vendor.load_catalog(fetch=False)
    # Vendor detection is the slow part (~0.1s per query over the full
    # catalog); the same query appears once per arm, so detect it once.
    seen: Dict[str, str] = {}
    return {"rows": [_flatten(r, catalog, seen) for r in rows], "aggregate": agg}


def _flatten(r: dict, catalog=None, seen: Dict[str, str] = None) -> dict:
    ir, ans = r.get("ir") or {}, r.get("answer_scores") or {}
    q = r.get("query", "")
    if seen is None or q not in seen:
        found = ", ".join(v.name for v in vendor.detect_vendors(
            q, catalog=catalog if catalog is not None else vendor.load_catalog(fetch=False)))
        if seen is not None:
            seen[q] = found
    else:
        found = seen[q]
    return {
        "query": q, "arm": r.get("system", ""), "category": r.get("category", ""),
        "ndcg@3": ir.get("ndcg@3"), "mrr": ir.get("mrr"),
        "faithfulness": ans.get("faithfulness"), "correctness": ans.get("correctness"),
        "vendor named": found or "none",
        "intent": intent.classify_label(q),
    }


def summarize(rows: List[dict], metric: str = "ndcg@3") -> List[str]:
    """Which query shapes score best and worst, as two plain lines."""
    groups: Dict[str, list] = defaultdict(list)
    for r in rows:
        if r.get(metric) is None:
            continue
        groups[f"vendor {'named' if r['vendor named'] != 'none' else 'not named'}"].append(r[metric])
        groups[f"intent {r['intent']}"].append(r[metric])
    means = {k: sum(v) / len(v) for k, v in groups.items() if v}
    if not means:
        return ["No scored queries in this run."]
    best, worst = max(means, key=means.get), min(means, key=means.get)
    return [f"Best: {best} questions — mean {metric} {means[best]:.2f} (n={len(groups[best])})",
            f"Worst: {worst} questions — mean {metric} {means[worst]:.2f} (n={len(groups[worst])})"]


def record_feedback(entry: dict) -> None:
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def feedback_tally() -> Dict[str, int]:
    t = {"correct": 0, "wrong": 0}
    try:
        with open(FEEDBACK_PATH, encoding="utf-8") as fh:
            for line in fh:
                v = json.loads(line).get("verdict")
                if v in t:
                    t[v] += 1
    except OSError:
        pass
    return t


if __name__ == "__main__":
    rows = [{"query": "Chrome crash?", "system": "marag", "ir": {"ndcg@3": 0.9},
             "answer_scores": {}},
            {"query": "any updates today", "system": "marag", "ir": {"ndcg@3": 0.1},
             "answer_scores": {}}]
    flat = [_flatten(r) for r in rows]
    assert flat[0]["vendor named"] != "none" and flat[1]["vendor named"] == "none", flat
    lines = summarize(flat)
    assert lines[0].startswith("Best: vendor named") or lines[0].startswith("Best: intent"), lines
    assert "Worst:" in lines[1]
    runs = list_runs()
    assert runs and load_run(runs[0])["rows"], runs
    print("ok", runs[0], summarize(load_run(runs[0])["rows"]))
