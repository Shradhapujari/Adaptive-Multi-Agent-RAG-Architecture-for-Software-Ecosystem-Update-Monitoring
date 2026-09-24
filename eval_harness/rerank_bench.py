"""
Offline reranker bench over dumped candidate pools.
===================================================

Why
---
On the clean n=500 run the multi-agent arm's candidate pool held more of the
judged-relevant documents than the baseline's (455 vs 425) and then left 48
of them outside its top-4 (baseline: 6). Ranked perfectly, the same pools
score nDCG@3 0.42 vs 0.39. So the question is not "does the extra retrieval
help" but "which ranking over the bigger pool keeps it" -- and that can be
answered offline, on identical pools, without a two-day re-run.

Input: a run dir with `pools.jsonl` (from `run_eval.py --dump-pools`) and the
shared `results/qrels_cache.json`. Every ranker below reorders the SAME pool
per (query, system); only the ordering differs.

Rankers are `<mode>:<scorer>`:
  mode    tiered  -- rank within tier1 (verified) then tier2 (community), as
                     RetrieverAgent does today; tier2 can never outrank tier1
          flat    -- one ranking over the whole pool
          flat-nonews -- flat, but google_news documents ranked last
  scorer  none | bm25 | embed[:model] | rrf (bm25+embed, k=60)
          llm:<provider:model>  -- pointwise 0-2 grade on the top-N of rrf,
                     ties broken by rrf. The cascade keeps the model-call count
                     at N per pool instead of |pool|. `llm20@embed:...` grades
                     the top-20 of the embed order instead; the base may be
                     rrf (default), bm25, embed or none, and N defaults to 12.

A document promoted into the top-k that no earlier run judged scores 0 here
and is counted in `unjudged@k`. `--judge` labels those with the harness judge
and merges the labels into the cache, so a second pass is unbiased.

Usage
-----
    python -m eval_harness.rerank_bench results/run_X \\
        --rankers tiered:embed,flat:embed,flat:rrf,flat:llm:ollama:qwen2.5:7b-instruct
    python -m eval_harness.rerank_bench results/run_X --rankers flat:rrf --judge ollama:llama3.1
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import statistics as st
import sys
from typing import Dict, List, Sequence

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import rerank  # noqa: E402

from .judge import Judge  # noqa: E402
from .metrics import retrieval_metrics  # noqa: E402
from .providers import make_client, LLMError  # noqa: E402
from .run_eval import qrels_key, _load_qrels_cache, _save_qrels_cache  # noqa: E402

TIER2_SOURCES = {"vendor_reddit", "google_news", "reddit", "news"}
KS = (1, 3, 5)
RRF_K = 60
LLM_TOP_N = 12
# Bases a `llm<N>@<base>:<model>` cascade may grade on top of. `rerank.py`'s
# own spec accepts bm25|embed|none, so the two have to agree or the same
# string means two different things in the bench and in the pipeline.
BASES = ("rrf", "bm25", "embed", "none")


def tier(d: dict) -> int:
    return 2 if d.get("source") in TIER2_SOURCES else 1


def rrf(orders: Sequence[Sequence[int]], n: int) -> List[float]:
    s = [0.0] * n
    for order in orders:
        for rank, i in enumerate(order):
            s[i] += 1.0 / (RRF_K + rank + 1)
    return s


class Scorer:
    """Returns a descending-score order (list of pool indices)."""

    def __init__(self, spec: str):
        self.spec = spec
        self.bm25 = rerank.BM25Reranker()
        self.embed = None
        self.llm = None
        self.llm_calls = 0
        if spec.startswith("embed"):
            self.embed = rerank.make_reranker(spec)
        elif spec in ("rrf",) or spec.startswith("llm"):
            self.embed = rerank.make_reranker("embed")
        self.llm_n, self.llm_base = LLM_TOP_N, "rrf"
        if spec.startswith("llm"):
            head, model = spec.split(":", 1)
            if "@" in head:
                head, self.llm_base = head.split("@", 1)
            if head[3:]:
                self.llm_n = int(head[3:])
            if self.llm_base not in BASES:
                raise ValueError(
                    f"unknown cascade base {self.llm_base!r} in {spec!r} "
                    f"(expected {'|'.join(BASES)})")
            self.llm = make_client(model)
            self._grade_cache: Dict[str, int] = {}

    def _base(self, mode: str, query: str, docs: List[dict]):
        """(scores, descending order) from one base ranker."""
        n = len(docs)
        if mode == "none":
            return [0.0] * n, list(range(n))
        if mode == "bm25":
            s = self.bm25.scores(query, docs)
        elif mode == "embed":
            s = self.embed.scores(query, docs)
        else:
            b = self.bm25.scores(query, docs)
            e = self.embed.scores(query, docs)
            s = rrf([sorted(range(n), key=lambda i: -b[i]),
                     sorted(range(n), key=lambda i: -e[i])], n)
        return s, sorted(range(n), key=lambda i: -s[i])

    def order(self, query: str, docs: List[dict]) -> List[int]:
        n = len(docs)
        if not n:
            return []
        if self.spec == "none":
            return list(range(n))
        if self.spec == "bm25":
            return self._base("bm25", query, docs)[1]
        if self.spec.startswith("embed"):
            return self._base("embed", query, docs)[1]
        if self.spec == "rrf":
            return self._base("rrf", query, docs)[1]
        # The cascade grades the top-N of the base the spec names. Only
        # `embed` used to be honoured here, so `llm12@bm25:<model>` and
        # `llm12@none:<model>` both graded the RRF fusion and were reported
        # under the base the operator asked for -- silently, which is the one
        # thing an ablation sweep must not do.
        fused, base = self._base(self.llm_base, query, docs)
        head = base[:self.llm_n]
        grades = {i: self._grade(query, docs[i]) for i in head}
        head.sort(key=lambda i: (-grades[i], -fused[i]))
        return head + base[self.llm_n:]

    def _grade(self, query: str, d: dict) -> int:
        key = qrels_key(query, d["doc_id"])
        if key in self._grade_cache:
            return self._grade_cache[key]
        prompt = (
            "You rank search results for a software-update question. Grade the "
            "document's relevance: 2 = directly answers or is about the exact "
            "product+version+issue asked; 1 = same product or area, not a direct "
            "answer; 0 = unrelated.\n\n"
            f'Question: "{query}"\n\n'
            f"Document (source={d.get('source')}):\nTitle: {d.get('title', '')}\n"
            f"Content: {(d.get('text') or '')[:600]}\n\n"
            'Respond with JSON only: {"relevance": <0|1|2>}'
        )
        g = 0
        try:
            raw = self.llm.generate(prompt, temperature=0.0, max_tokens=40)
            self.llm_calls += 1
            m = raw[raw.find("{"):raw.rfind("}") + 1]
            g = int(round(float(json.loads(m).get("relevance", 0))))
        except (LLMError, ValueError, json.JSONDecodeError, AttributeError):
            g = 0
        g = max(0, min(2, g))
        self._grade_cache[key] = g
        return g


NEWS_SOURCES = {"google_news", "news"}


def rank(mode: str, scorer: Scorer, query: str, pool: List[dict], top_k: int) -> List[dict]:
    if mode == "flat":
        return [pool[i] for i in scorer.order(query, pool)][:top_k]
    if mode == "flat-nonews":
        # News last: a headline about a product is rarely the document that
        # answers a question about its update, and it is 17% of the flat top-4.
        ranked = [pool[i] for i in scorer.order(query, pool)]
        return ([d for d in ranked if d.get("source") not in NEWS_SOURCES]
                + [d for d in ranked if d.get("source") in NEWS_SOURCES])[:top_k]
    t1 = [d for d in pool if tier(d) == 1]
    t2 = [d for d in pool if tier(d) == 2]
    return ([t1[i] for i in scorer.order(query, t1)]
            + [t2[i] for i in scorer.order(query, t2)])[:top_k]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("run_dir")
    p.add_argument("--rankers", default="tiered:embed,flat:embed,tiered:bm25,flat:bm25,flat:rrf")
    p.add_argument("--systems", default="marag_llm,single_agent")
    p.add_argument("--top-k", type=int, default=4)
    p.add_argument("--only-judged", action="store_true",
                   help="score only questions with >=1 judged-relevant doc")
    p.add_argument("--judge", default="",
                   help="label unjudged top-k docs with this judge and merge into the cache")
    p.add_argument("--results-dir", default=os.path.join(os.path.dirname(HERE), "results"))
    p.add_argument("--out", default="", help="write per-(query,system,ranker) rows here")
    a = p.parse_args()

    cache = _load_qrels_cache(a.results_dir)
    systems = a.systems.split(",")
    pools = collections.defaultdict(dict)
    for line in open(os.path.join(a.run_dir, "pools.jsonl")):
        x = json.loads(line)
        if x["system"] in systems:
            pools[x["query_id"]][x["system"]] = x

    def qrels_for(query: str, docs: Sequence[dict]) -> Dict[str, int]:
        return {d["doc_id"]: cache[qrels_key(query, d["doc_id"])]
                for d in docs if qrels_key(query, d["doc_id"]) in cache}

    judge = Judge(a.judge) if a.judge else None
    if judge and not judge.available():
        sys.exit(f"judge {a.judge} not available")

    rankers = [r.strip() for r in a.rankers.split(",") if r.strip()]
    scorers: Dict[str, Scorer] = {}
    rows: List[dict] = []
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    unjudged = collections.Counter()
    n_q = 0
    for qid in sorted(pools):
        entry = pools[qid]
        if len(entry) < len(systems):
            continue
        query = next(iter(entry.values()))["query"]
        all_docs = {d["doc_id"]: d for e in entry.values() for d in e["pool"]}
        qrels = qrels_for(query, all_docs.values())
        if a.only_judged and not any(v > 0 for v in qrels.values()):
            continue
        n_q += 1
        tops: Dict[str, List[dict]] = {}
        for sysn in systems:
            pool = entry[sysn]["pool"]
            for spec in rankers:
                mode, scorer_spec = spec.split(":", 1)
                sc = scorers.setdefault(scorer_spec, Scorer(scorer_spec))
                tops[(sysn, spec)] = rank(mode, sc, query, pool, a.top_k)
            tops[(sysn, "as_run")] = entry[sysn]["docs"][:a.top_k]
        if judge:
            new = 0
            for docs in tops.values():
                for d in docs:
                    k = qrels_key(query, d["doc_id"])
                    if k not in cache:
                        cache[k] = judge.relevance_label(query, d)
                        new += 1
            if new:
                _save_qrels_cache(a.results_dir, cache)
                qrels = qrels_for(query, all_docs.values())
        for (sysn, spec), docs in tops.items():
            ranked = [d["doc_id"] for d in docs]
            m = retrieval_metrics(ranked, qrels, KS) if qrels else {f"ndcg@{k}": 0.0 for k in KS} | {"mrr": 0.0} | {f"recall@{k}": 0.0 for k in KS}
            uj = sum(1 for d in docs if qrels_key(query, d["doc_id"]) not in cache)
            unjudged[(sysn, spec)] += uj
            for k, v in m.items():
                per[(sysn, spec)][k].append(v)
            rows.append({"query_id": qid, "system": sysn, "ranker": spec, "doc_ids": ranked,
                         "unjudged": uj, **m})
        print(f"[{n_q}] q{qid} done", file=sys.stderr, end="\r")

    print(f"\n{n_q} questions · top_k={a.top_k} · judged pairs in cache: {len(cache)}")
    base = per[("single_agent", "as_run")] if ("single_agent", "as_run") in per else None
    print(f"\n{'system':14s} {'ranker':22s} {'ndcg@3':>7s} {'Δ vs base':>9s} {'W/T/L':>11s} {'recall@5':>8s} {'mrr':>6s} {'unj@k':>6s}")
    for (sysn, spec), m in sorted(per.items()):
        nd = m["ndcg@3"]
        if base:
            diffs = [x - y for x, y in zip(nd, base["ndcg@3"])]
            w = sum(d > 1e-9 for d in diffs); l = sum(d < -1e-9 for d in diffs)
            delta = f"{st.mean(diffs):+.3f}"; wtl = f"{w}/{len(diffs)-w-l}/{l}"
        else:
            delta = wtl = ""
        print(f"{sysn:14s} {spec:22s} {st.mean(nd):7.3f} {delta:>9s} {wtl:>11s} "
              f"{st.mean(m['recall@5']):8.3f} {st.mean(m['mrr']):6.3f} {unjudged[(sysn, spec)]:6d}")
    for spec, sc in scorers.items():
        if sc.llm:
            print(f"llm calls for {spec}: {sc.llm_calls}")
    if a.out:
        with open(a.out, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    main()
