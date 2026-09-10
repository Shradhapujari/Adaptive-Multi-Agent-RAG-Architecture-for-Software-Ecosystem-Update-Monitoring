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
    # answer-comparable head-to-head: both arms synthesise with the same model
    python -m eval_harness.run_eval --generators marag:ollama:mistral,single_agent
    # continue an interrupted run: finished questions are not re-generated
    python -m eval_harness.run_eval --resume run_1788132228_7cdc5685d75a \
        --dataset data/benchmark_300.json
    python -m eval_harness.run_eval --judge ollama:minimax-m2.7:cloud

Outputs a timestamped folder under results/<run_id>/ containing:
    config.json, manifest.json, per_query.jsonl, aggregate.csv,
    qrels.json, qrels_cache_snapshot.json, report.md, and PNG plots.

`qrels.json` holds the judgments that scored THIS run, as
{query_id: {doc_id: grade}}. `qrels_cache_snapshot.json` is the accumulating
cross-run judgment cache and is provenance only -- do not score with it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import Counter, OrderedDict
from typing import Dict, List, Sequence

# corpus_snapshot and rerank live at the project root, next to the package.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import corpus_snapshot
import rerank

from .config import EvalConfig
from .dataset import load_dataset, dataset_hash
from . import benchmarks as bench_mod
from agent_rules import RULES_ENV
from .generators import build_generators, rules_arm
from .judge import Judge
from .metrics import retrieval_metrics, mean_ci
from . import report as report_mod


QRELS_CACHE = "qrels_cache.json"

# A cache entry must be keyed by the QUESTION, not by its position in a file.
# Keying on rec["id"] silently mixed datasets: benchmark_300 ids run 1..300 and
# validation_gt ids run 1..10, both pool documents from the same live APIs, so
# the label judged for validation question 3 was reused for benchmark question
# 3 — a different question about a different product. Hashing the query text
# makes the key dataset-independent, and legitimately shares a label when two
# datasets happen to ask the same question about the same document.
_KEY_RE = re.compile(r"^[0-9a-f]{12}:[0-9a-f]{12}$")


def qrels_key(query: str, doc_id: str) -> str:
    """Cache key for one (question, document) relevance judgment."""
    qh = hashlib.sha1(query.strip().lower().encode("utf-8", "ignore")).hexdigest()[:12]
    return f"{qh}:{doc_id}"


def _load_qrels_cache(results_dir: str) -> dict:
    p = os.path.join(results_dir, QRELS_CACHE)
    if os.path.exists(p):
        try:
            raw = json.load(open(p))
        except Exception:
            return {}
        cache = {k: v for k, v in raw.items() if _KEY_RE.match(k)}
        dropped = len(raw) - len(cache)
        if dropped:
            print(f"[harness] qrels cache: dropped {dropped} entries keyed by "
                  f"dataset position (ambiguous across datasets); they will be "
                  f"re-judged and re-cached by question")
        return cache
    return {}


def _save_qrels_cache(results_dir: str, cache: dict) -> None:
    """Write the judgment cache atomically.

    Two evaluations can share a results dir -- a `--resume` arm running beside
    the next pass of a sweep is the normal case, not an exotic one. Writing this
    file in place means the second writer can land inside the first one's output
    and leave torn JSON. `_load_qrels_cache` swallows the parse error and
    returns {}, so the damage is silent: every judgment is made again, costing
    hours, and judgments made under a different model state can shift results
    mid-sweep.

    Write to a private temp file in the same directory, then rename. os.replace
    is atomic within a filesystem, so a concurrent reader sees either the old
    file or the new one, never a half-written one.
    """
    os.makedirs(results_dir, exist_ok=True)
    final = os.path.join(results_dir, QRELS_CACHE)
    tmp = f"{final}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(cache, f, indent=1)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, final)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


PER_QUERY = "per_query.jsonl"

# Fewer ground-truth questions than this and the correctness column is an
# anecdote, not a measurement. Matches report.MIN_REPORTABLE_N.
MIN_GROUND_TRUTH = 5


def stratify_summary(records: Sequence[dict], key: str) -> str:
    """
    Report the mix a stratified selection actually produced, per field.

    `key` may be composite ("category,ecosystem"). Looking the whole key up as
    one field -- `r.get("category,ecosystem")` -- returns None for every record
    and prints `None=100`, which reads as a successful stratification while
    saying nothing. Each field is counted separately instead; a field with many
    values is summarised by its spread rather than listed in full.
    """
    fields = [f.strip() for f in str(key).split(",") if f.strip()] or ["category"]
    parts = []
    for f in fields:
        mix = Counter(r.get(f) for r in records)
        if len(mix) <= 8:
            body = ", ".join(f"{k}={v}" for k, v in
                             sorted(mix.items(), key=lambda kv: str(kv[0])))
        else:
            body = (f"{len(mix)} distinct, "
                    f"{min(mix.values())}-{max(mix.values())} each")
        parts.append(f"{f}: {body}")
    return "; ".join(parts)


def _read_finished(run_dir: str, systems: List[str]) -> tuple:
    """
    Read a previous run's streamed rows back.

    Returns (rows, done_ids).

    `done_ids` holds the questions already scored for EVERY system in THIS
    run: a question interrupted partway through its systems is re-run whole,
    so resuming cannot produce two rows for one (question, system).

    `rows` keeps everything that is not about to be regenerated, including rows
    for systems this run does not have. Resuming with a different arm list is
    how an arm gets ADDED to a finished run --

        --resume <run_dir> --generators marag:ollama:mistral

    -- and an earlier version dropped every row whose system was not in the new
    list, so adding a third arm silently deleted the two already measured.
    """
    path = os.path.join(run_dir, PER_QUERY)
    if not os.path.exists(path):
        return [], set()
    by_q: "OrderedDict[str, Dict[str, dict]]" = OrderedDict()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue  # a row torn by a kill mid-write
            by_q.setdefault(str(row.get("query_id")), {})[row.get("system")] = row
    want = set(systems)
    rows, done = [], set()
    for qid, per_system in by_q.items():
        complete = want.issubset(per_system)
        if complete:
            done.add(qid)
        for sysname, row in per_system.items():
            # Rows for this run's systems survive only when the question is
            # complete (an incomplete question is redone in full). Rows for any
            # other system are never this run's to discard.
            if sysname not in want or complete:
                rows.append(row)
    return rows, done


def _compact(run_dir: str, rows: List[dict]) -> None:
    """Rewrite per_query.jsonl as exactly the rows being kept."""
    with open(os.path.join(run_dir, PER_QUERY), "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def run(cfg: EvalConfig) -> str:
    random.seed(cfg.seed)
    os.makedirs(cfg.results_dir, exist_ok=True)

    # Default the whole process to no agent rules, before a generator is built.
    # AGENT_RULES.md is prepended by every prompt path that calls
    # `agent_rules.rules_block()` -- which includes multiagent_rag_v3.call_llama,
    # so the rules reached this harness's query rewriter the day the file
    # landed, silently, on a prompt the published numbers were produced without.
    # An arm that wants them says so; a plain run reproduces what was published.
    os.environ.setdefault(RULES_ENV, "off")

    # Freeze the corpus before a single system is built. An ablation whose
    # sources move between arms measures the sources, not the arms.
    snap = corpus_snapshot.activate(cfg.corpus)
    if snap is not None:
        print(f"[harness] corpus {snap.mode}: {snap.dir}")
    else:
        print("[harness] corpus: LIVE (runs are not comparable to each other; "
              "set MARAG_CORPUS=record:<dir> then replay:<dir> for an ablation)")

    # With --stratify, load everything and select afterwards: both loaders
    # implement `limit` as a head slice, which is what drops categories.
    _load_limit = 0 if cfg.stratify else cfg.limit
    if cfg.benchmark:
        records = bench_mod.load_benchmark(cfg.dataset, fmt=cfg.benchmark,
                                           limit=_load_limit)
        print(f"[harness] benchmark mode: {cfg.benchmark} "
              f"({len(records)} questions with ground truth)")
    else:
        records = load_dataset(cfg.dataset, _load_limit)
    if cfg.stratify and cfg.limit:
        before = len(records)
        records = bench_mod.stratified_limit(records, cfg.limit, cfg.stratify)
        print(f"[harness] stratified {cfg.limit}/{before} by {cfg.stratify} -> "
              + stratify_summary(records, cfg.stratify))
    # Ground truth is what `correctness` and the deterministic benchmark scoring
    # are computed from. A selection can be perfectly balanced on category and
    # ecosystem and still carry almost none of it: in benchmark_300.json the
    # ground-truth-bearing records sit late in file order inside each cell, and
    # `stratified_limit` takes each cell in file order, so --stratify picked 2
    # of 100 where the parent file holds 51 of 300. The run then reports a
    # correctness column measured on two questions.
    n_gt = sum(1 for r in records if r.get("ground_truth"))
    if n_gt < MIN_GROUND_TRUTH:
        print(f"[harness] WARNING: only {n_gt}/{len(records)} selected questions "
              f"carry ground truth — `correctness` and benchmark scoring will be "
              f"computed on {n_gt} question(s) and are not reportable. "
              f"data/benchmark_100.json is a 100-question selection that keeps "
              f"28 of them (build_benchmark_subset.py prefers ground-truth "
              f"records inside each cell).")
    ds_hash = dataset_hash(records)
    if cfg.resume:
        run_dir = (cfg.resume if os.path.isabs(cfg.resume)
                   else os.path.join(cfg.results_dir, cfg.resume))
        run_dir = run_dir.rstrip(os.sep)
        run_id = os.path.basename(run_dir)
        if not os.path.isdir(run_dir):
            raise SystemExit(f"--resume: no such run dir: {run_dir}")
        # The dataset hash is in the run id. Resuming a run with a different
        # dataset would silently mix two question sets in one artifact.
        if not run_id.endswith(ds_hash):
            raise SystemExit(
                f"--resume: {run_id} was run on a different dataset "
                f"(its hash vs this dataset's {ds_hash}); "
                f"start a new run instead of mixing them")
    else:
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
    # Rows are streamed to per_query.jsonl as each question finishes rather
    # than written once at the end. A 300-question run is hours long; writing
    # only at the end meant an interruption lost every generated answer while
    # keeping the (cheap, cached) judgments — 67 questions were lost that way.
    per_query: List[dict] = []
    done_ids: set = set()
    if cfg.resume:
        per_query, done_ids = _read_finished(run_dir, [g.name for g in gens])
        _compact(run_dir, per_query)
        print(f"[harness] resuming {run_id}: {len(done_ids)} questions already "
              f"scored for all {len(gens)} systems, "
              f"{len(records) - len(done_ids)} to go")
    stream = open(os.path.join(run_dir, PER_QUERY), "a")
    # The judgments actually used to score THIS run, per query. Kept separate
    # from `qrels_cache`: the cache accumulates across every run and dataset
    # that shares the results dir, so dumping it as the run's qrels made the
    # run's own numbers unreproducible from its own artifacts.
    qrels_used: Dict[str, Dict[str, int]] = {}
    if cfg.resume:
        qpath = os.path.join(run_dir, "qrels.json")
        if os.path.exists(qpath):
            try:
                prior = json.load(open(qpath))
                qrels_used = {k: v for k, v in prior.items()
                              if k in done_ids and isinstance(v, dict)}
            except Exception:
                pass

    for qi, rec in enumerate(records, 1):
        if str(rec["id"]) in done_ids:
            continue
        query = rec["query"]
        print(f"\n[{qi}/{len(records)}] {query[:80]}")
        sys_outputs: Dict[str, dict] = {}
        for g in gens:
            t0 = time.time()
            try:
                out = g.generate(query)
            except corpus_snapshot.CorpusMiss:
                # A strict run asked for a document the snapshot does not hold.
                # Recording that as an error row would defeat the point of
                # strictness: the run would finish and report numbers built on
                # a corpus that silently differed between arms.
                raise
            except Exception as e:  # noqa: BLE001
                out = {"answer": f"[system error: {e}]", "docs": [], "self_quality": None}
            out["latency_s"] = round(time.time() - t0, 2)
            sys_outputs[g.name] = out
            print(f"    {g.name:28s} {len(out['docs'])} docs  {out['latency_s']}s")

        # ---- pool retrieved docs and judge relevance (cached) -----------
        # The judging pool is the union of what the systems *returned*. With
        # judge_pool it widens to what they *considered*, which is what makes
        # pool recall -- the ceiling reranking could reach -- computable.
        pool: Dict[str, dict] = {}
        for out in sys_outputs.values():
            for d in out["docs"]:
                pool.setdefault(d["doc_id"], d)
            if cfg.judge_pool:
                for d in out.get("pool") or []:
                    pool.setdefault(d["doc_id"], d)
        qrels: Dict[str, int] = {}
        if judging:
            for did, d in pool.items():
                ck = qrels_key(query, did)
                if ck in qrels_cache:
                    qrels[did] = qrels_cache[ck]
                else:
                    g_label = judge.relevance_label(query, d)
                    qrels[did] = g_label
                    qrels_cache[ck] = g_label
        qrels_used[str(rec["id"])] = dict(qrels)

        # ---- per-system metrics -----------------------------------------
        rows_this_query: List[dict] = []
        for name, out in sys_outputs.items():
            ranked = [d["doc_id"] for d in out["docs"]]
            ir = retrieval_metrics(ranked, qrels, cfg.ks) if (judging and ranked) else {}
            ans = {}
            if judging:
                contexts = [f"{d['title']}: {d['text']}" for d in out["docs"]]
                ans = judge.score_answer(query, out["answer"], contexts,
                                         rec.get("ground_truth"))
            bench_label = None
            if cfg.benchmark and rec.get("ground_truth"):
                bench_label = bench_mod.score_prediction(out["answer"],
                                                         rec["ground_truth"])
            pool_ids = [d["doc_id"] for d in (out.get("pool") or [])]
            # Ceiling on recall@k for this fetch: the share of judged-relevant
            # documents that were in the pool at all. A low pool recall with a
            # high in-pool precision means the reranker is doing its job and the
            # fetch is not -- no reranker can promote a document it never saw.
            #
            # Only meaningful with judge_pool. Without it the judged set is drawn
            # from the returned top_k alone, every gold document is in the pool
            # by construction, and the number is a tautological 1.0 -- which is
            # worse than absent, because it reads as a finding.
            pool_recall = None
            if cfg.judge_pool:
                gold = {d for d, g in qrels.items() if g > 0}
                pool_recall = (len(gold & set(pool_ids)) / len(gold)) if (gold and pool_ids) else None
            rows_this_query.append({
                "benchmark_label": bench_label,
                "query_id": rec["id"],
                "query": query,
                "category": rec["category"],
                "system": name,
                "n_docs": len(out["docs"]),
                "doc_ids": ranked,
                "pool_size": len(pool_ids),
                "pool_doc_ids": pool_ids,
                "pool_recall": pool_recall,
                # Critique-loop trace, set only by the self-reflective arm.
                # Persisted because that arm's ISREL step *discards* candidates,
                # and the same model later judges relevance for scoring -- so the
                # count of documents the critic removed is what makes the
                # resulting metric inflation measurable rather than hypothetical.
                "critique_trace": out.get("trace"),
                "rerank_spec": out.get("rerank_spec", ""),
                "rerank_degraded": out.get("rerank_degraded", False),
                "latency_s": out["latency_s"],
                "self_quality": out.get("self_quality"),
                "answer": out["answer"],
                # Only set by the synthesising multi-agent arm: which model wrote
                # the scored answer, and the template answer it replaced.
                "synth_model": out.get("synth_model"),
                "template_answer": out.get("template_answer"),
                "ir": ir,
                "answer_scores": ans,
            })

        # Persist this question before starting the next one: the run is now
        # restartable with --resume, losing at most the question in flight.
        per_query.extend(rows_this_query)
        for row in rows_this_query:
            stream.write(json.dumps(row) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        _save_qrels_cache(cfg.results_dir, qrels_cache)
        json.dump(qrels_used, open(os.path.join(run_dir, "qrels.json"), "w"), indent=1)

    # ---- persist + report ----------------------------------------------
    # per_query.jsonl was streamed during the loop; nothing to write here.
    stream.close()
    # qrels.json = exactly what scored this run, keyed by query id, so
    # aggregate.csv can be recomputed from the artifacts alone. Verified: the
    # previous version dumped `qrels_cache` (every judgment ever made in this
    # results dir), which reproduced only 2 of 20 per-query metric rows because
    # the recall/nDCG denominators came out of a much larger judged pool.
    json.dump(qrels_used, open(os.path.join(run_dir, "qrels.json"), "w"), indent=1)
    # The accumulating cross-run cache, snapshotted for provenance only.
    json.dump(qrels_cache,
              open(os.path.join(run_dir, "qrels_cache_snapshot.json"), "w"), indent=1)
    cfg_dict = {k: getattr(cfg, k) for k in vars(cfg)}
    cfg_dict["systems_evaluated"] = [g.name for g in gens]
    cfg_dict["judge_active"] = judging
    cfg_dict["dataset_hash"] = ds_hash
    cfg_dict["n_questions"] = len(records)
    # Which arm this run actually is. Reading it back off the environment at
    # write time would be a guess; ask the reranker the harness really used.
    _rr = rerank.get_reranker()
    cfg_dict["rerank_requested"] = os.environ.get("MARAG_RERANK", rerank.DEFAULT_SPEC)
    cfg_dict["rerank_spec"] = _rr.spec
    cfg_dict["rerank_degraded"] = bool(_rr.degraded)
    # Same rule for the rules factor: ask the generator what it used. The sha
    # is the part that matters across arms -- AGENT_RULES.md is a file anyone
    # can edit between two passes, and two arms built from different rule text
    # are not an ablation of one factor.
    cfg_dict.update(rules_arm())
    cfg_dict["corpus"] = snap.stats() if snap is not None else {"mode": "live",
                                                                "frozen": False}
    if snap is not None:
        st = cfg_dict["corpus"]
        # `record` counts neither hits nor misses -- it passes every call
        # through and stores the response -- so reporting them reads as "the
        # recording captured nothing" when it captured everything. Report the
        # number it actually produced.
        if st["mode"] == "record":
            print(f"[harness] corpus record: {st.get('recorded', 0)} responses "
                  f"stored in {st.get('dir', '?')} (replay this dir to freeze "
                  f"the corpus; a recording pass is never frozen itself)")
        else:
            print(f"[harness] corpus {st['mode']}: {st['hits']} hits, "
                  f"{st['misses']} misses, {st['corpus_misses']} of them on "
                  f"corpus hosts -> frozen={st['frozen']}")
        if st["corpus_misses"]:
            print("[harness] WARNING: corpus hosts were read live during replay; "
                  "this run is NOT comparable to other arms. "
                  f"misses by host: {st['misses_by_host']}")
    json.dump(cfg_dict, open(os.path.join(run_dir, "config.json"), "w"), indent=2)

    if cfg.benchmark:
        by_id = {r["id"]: r for r in records}
        bench_summary = bench_mod.score_run(per_query, by_id)
        json.dump(bench_summary,
                  open(os.path.join(run_dir, "benchmark_scores.json"), "w"), indent=2)
        print("\n[harness] benchmark scores "
              "(accuracy / hallucination / missing / CRAG score):")
        for name, s in sorted(bench_summary.items(),
                              key=lambda kv: -kv[1]["crag_score"]):
            print(f"    {name:28s} {s['accuracy']:.3f}  {s['hallucination']:.3f}  "
                  f"{s['missing']:.3f}  {s['crag_score']:+.3f}   (n={s['n']})")

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
    p.add_argument("--benchmark", default=cfg.benchmark,
                   choices=["", "crag", "generic"],
                   help="score against an established benchmark file "
                        "(deterministic correct/incorrect/missing labelling)")
    p.add_argument("--stratify", default=cfg.stratify, metavar="FIELD",
                   help="make --limit keep the mix of FIELD (e.g. 'category') "
                        "instead of taking the first N in file order")
    p.add_argument("--top-k", type=int, default=cfg.top_k)
    p.add_argument("--seed", type=int, default=cfg.seed)
    p.add_argument("--resume", default=cfg.resume,
                   metavar="RUN_DIR",
                   help="continue an interrupted run: reuse that run dir and "
                        "skip questions already scored for every system")
    p.add_argument("--judge-pool", action="store_true", default=cfg.judge_pool,
                   help="judge every pre-rerank candidate, enabling pool recall")
    p.add_argument("--corpus", default=cfg.corpus,
                   help="record:<dir> | replay:<dir> — freeze the live sources "
                        "so arms of an ablation see identical documents")
    a = p.parse_args()
    cfg.dataset = a.dataset
    cfg.stratify = a.stratify
    cfg.limit = a.limit
    cfg.generators = [s.strip() for s in a.generators.split(",") if s.strip()]
    cfg.judge = a.judge
    cfg.benchmark = a.benchmark
    cfg.top_k = a.top_k
    cfg.seed = a.seed
    cfg.judge_pool = a.judge_pool
    cfg.corpus = a.corpus
    cfg.resume = a.resume
    return cfg


if __name__ == "__main__":
    run(_parse_args())
