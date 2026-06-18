"""
Evaluation runner.
==================
Orchestrates the full Tier-1 evaluation:

  load dataset -> run each system -> pool retrieved docs -> judge relevance
  (cached qrels) -> compute IR metrics -> judge answers -> aggregate -> report.

Usage:
    python -m eval_harness.run_eval                       # defaults from config
    python -m eval_harness.run_eval --dataset table_50_questions.json --limit 20
    python -m eval_harness.run_eval --generators marag,raw:ollama:mistral
    python -m eval_harness.run_eval --judge ollama:minimax-m2.7:cloud

Outputs a timestamped folder under results/<run_id>/ containing:
    config.json, manifest.json, per_query.jsonl, aggregate.csv,
    qrels.json, report.md, and PNG comparison plots.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from typing import Dict, List

from .config import EvalConfig
from .dataset import load_dataset, dataset_hash
from .generators import build_generators
from .judge import Judge
from .metrics import retrieval_metrics, mean_ci
from . import report as report_mod


QRELS_CACHE = "qrels_cache.json"


def _load_qrels_cache(results_dir: str) -> dict:
    p = os.path.join(results_dir, QRELS_CACHE)
    if os.path.exists(p):
        try:
            return json.load(open(p))
        except Exception:
            return {}
    return {}


def _save_qrels_cache(results_dir: str, cache: dict) -> None:
    os.makedirs(results_dir, exist_ok=True)
    json.dump(cache, open(os.path.join(results_dir, QRELS_CACHE), "w"), indent=1)


def run(cfg: EvalConfig) -> str:
    random.seed(cfg.seed)
    os.makedirs(cfg.results_dir, exist_ok=True)

    records = load_dataset(cfg.dataset, cfg.limit)
    ds_hash = dataset_hash(records)
    run_id = "run_" + str(int(time.time())) + "_" + ds_hash
    run_dir = os.path.join(cfg.results_dir, run_id)
    os.makedirs(run_dir, exist_ok=True)
    print(f"\n[harness] dataset={cfg.dataset} questions={len(records)} hash={ds_hash}")
    print(f"[harness] run dir: {run_dir}")

    # Build systems, drop those that can't run right now.
    gens = []
    for g in build_generators(cfg.generators, top_k=cfg.top_k):
        if g.available():
            gens.append(g)
            print(f"[harness] system ready: {g.name}")
        else:
            print(f"[harness] system SKIPPED (unavailable): {g.name}")
    if not gens:
        raise SystemExit("No systems available to evaluate (is Ollama running?).")

    judge = Judge(cfg.judge)
    judging = judge.available()
    print(f"[harness] judge: {judge.spec} ({'on' if judging else 'OFF — metrics limited'})")

    qrels_cache = _load_qrels_cache(cfg.results_dir)
    per_query: List[dict] = []

    for qi, rec in enumerate(records, 1):
        query = rec["query"]
        print(f"\n[{qi}/{len(records)}] {query[:80]}")
        sys_outputs: Dict[str, dict] = {}
        for g in gens:
            t0 = time.time()
            try:
                out = g.generate(query)
            except Exception as e:  # noqa: BLE001
                out = {"answer": f"[system error: {e}]", "docs": [], "self_quality": None}
            out["latency_s"] = round(time.time() - t0, 2)
            sys_outputs[g.name] = out
            print(f"    {g.name:28s} {len(out['docs'])} docs  {out['latency_s']}s")

        # ---- pool retrieved docs and judge relevance (cached) -----------
        pool: Dict[str, dict] = {}
        for out in sys_outputs.values():
            for d in out["docs"]:
                pool.setdefault(d["doc_id"], d)
        qrels: Dict[str, int] = {}
        if judging:
            for did, d in pool.items():
                ck = f"{rec['id']}:{did}"
                if ck in qrels_cache:
                    qrels[did] = qrels_cache[ck]
                else:
                    g_label = judge.relevance_label(query, d)
                    qrels[did] = g_label
                    qrels_cache[ck] = g_label

        # ---- per-system metrics -----------------------------------------
        for name, out in sys_outputs.items():
            ranked = [d["doc_id"] for d in out["docs"]]
            ir = retrieval_metrics(ranked, qrels, cfg.ks) if (judging and ranked) else {}
            ans = {}
            if judging:
                contexts = [f"{d['title']}: {d['text']}" for d in out["docs"]]
                ans = judge.score_answer(query, out["answer"], contexts,
                                         rec.get("ground_truth"))
            per_query.append({
                "query_id": rec["id"],
                "query": query,
                "category": rec["category"],
                "system": name,
                "n_docs": len(out["docs"]),
                "doc_ids": ranked,
                "latency_s": out["latency_s"],
                "self_quality": out.get("self_quality"),
                "answer": out["answer"],
                "ir": ir,
                "answer_scores": ans,
            })
        _save_qrels_cache(cfg.results_dir, qrels_cache)

    # ---- persist + report ----------------------------------------------
    with open(os.path.join(run_dir, "per_query.jsonl"), "w") as f:
        for row in per_query:
            f.write(json.dumps(row) + "\n")
    json.dump(qrels_cache, open(os.path.join(run_dir, "qrels.json"), "w"), indent=1)
    cfg_dict = {k: getattr(cfg, k) for k in vars(cfg)}
    cfg_dict["systems_evaluated"] = [g.name for g in gens]
    cfg_dict["judge_active"] = judging
    cfg_dict["dataset_hash"] = ds_hash
    cfg_dict["n_questions"] = len(records)
    json.dump(cfg_dict, open(os.path.join(run_dir, "config.json"), "w"), indent=2)

    agg = report_mod.aggregate(per_query, cfg.ks)
    report_mod.write_csv(agg, os.path.join(run_dir, "aggregate.csv"))
    report_mod.write_markdown(agg, cfg_dict, os.path.join(run_dir, "report.md"))
    try:
        report_mod.write_plots(agg, run_dir, cfg.ks)
    except Exception as e:  # noqa: BLE001 — plots are nice-to-have
        print(f"[harness] plot step skipped: {e}")

    print(f"\n[harness] DONE. Report: {os.path.join(run_dir, 'report.md')}")
    return run_dir


def _parse_args() -> EvalConfig:
    cfg = EvalConfig()
    p = argparse.ArgumentParser(description="Multi-Agent RAG System Tier-1 evaluation harness")
    p.add_argument("--dataset", default=cfg.dataset)
    p.add_argument("--limit", type=int, default=cfg.limit)
    p.add_argument("--generators", default=",".join(cfg.generators),
                   help="comma-separated generator specs")
    p.add_argument("--judge", default=cfg.judge)
    p.add_argument("--top-k", type=int, default=cfg.top_k)
    p.add_argument("--seed", type=int, default=cfg.seed)
    a = p.parse_args()
    cfg.dataset = a.dataset
    cfg.limit = a.limit
    cfg.generators = [s.strip() for s in a.generators.split(",") if s.strip()]
    cfg.judge = a.judge
    cfg.top_k = a.top_k
    cfg.seed = a.seed
    return cfg


if __name__ == "__main__":
    run(_parse_args())
