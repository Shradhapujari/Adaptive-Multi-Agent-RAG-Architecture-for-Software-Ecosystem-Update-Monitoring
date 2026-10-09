"""
Standard information-retrieval metrics.
=======================================
Replaces the paper's bespoke "retrieval quality" heuristic with the metrics
reviewers actually expect. All operate on a ranked list of doc_ids plus a
`qrels` dict mapping doc_id -> graded relevance (0 = irrelevant, 1 = related,
2 = highly relevant).

    recall_at_k(ranked, qrels, k)
    precision_at_k(ranked, qrels, k)
    ndcg_at_k(ranked, qrels, k)     # graded gains, standard log2 discount
    mrr(ranked, qrels)              # first relevant (grade >= 1) result

`mean_ci(values)` returns (mean, half-width of 95% CI) so result tables can
carry error bars — the conference talks repeatedly stressed statistical
reporting over single point numbers.

Scope of the denominators (read before quoting an absolute number)
-----------------------------------------------------------------
`run_eval` judges only the documents the run's own systems retrieved, so the
`qrels` handed to these functions is the *per-query pool for that run*, not a
fixed judged corpus. Consequences:

  * `recall_at_k`'s denominator is "relevant docs inside this run's pool".
    Measured on validation_gt.json (n=10), that denominator is 1-3 documents,
    while the accumulated judgment cache holds 2-10 relevant docs for the same
    questions. Reported recall is therefore an upper bound, and a query where
    the pool contains exactly one relevant document scores recall@1 = 1.0.
  * `ndcg_at_k`'s IDCG comes from the same pool, so a system cannot be
    penalised for relevant documents no arm in the run retrieved.
  * Both are still valid for the *paired within-run* comparison every arm in a
    run shares one pool. They are NOT comparable across runs, and they are not
    comparable to published numbers computed against a fixed corpus.

To get corpus-relative numbers, score against the union of all judgments for
each question (`qrels_cache_snapshot.json`) rather than the per-run pool.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List, Sequence, Tuple


def _rel(qrels: Dict[str, int], doc_id: str) -> int:
    return int(qrels.get(doc_id, 0))


def _dedup(ranked: Sequence[str]) -> List[str]:
    """Drop repeated doc_ids, keeping first occurrence. A retriever may return
    the same document via two sources; without this, recall/precision/nDCG can
    exceed their valid range by double-counting."""
    seen = set()
    out = []
    for d in ranked:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def recall_at_k(ranked: Sequence[str], qrels: Dict[str, int], k: int) -> float:
    ranked = _dedup(ranked)
    total_rel = sum(1 for g in qrels.values() if g >= 1)
    if total_rel == 0:
        return 0.0
    hit = sum(1 for d in ranked[:k] if _rel(qrels, d) >= 1)
    return min(hit / total_rel, 1.0)


def precision_at_k(ranked: Sequence[str], qrels: Dict[str, int], k: int) -> float:
    if k == 0:
        return 0.0
    ranked = _dedup(ranked)
    hit = sum(1 for d in ranked[:k] if _rel(qrels, d) >= 1)
    return hit / k


def dcg_at_k(ranked: Sequence[str], qrels: Dict[str, int], k: int) -> float:
    ranked = _dedup(ranked)
    dcg = 0.0
    for i, d in enumerate(ranked[:k]):
        gain = (2 ** _rel(qrels, d)) - 1
        dcg += gain / math.log2(i + 2)
    return dcg


def ndcg_at_k(ranked: Sequence[str], qrels: Dict[str, int], k: int) -> float:
    ideal = sorted(qrels.values(), reverse=True)
    idcg = 0.0
    for i, g in enumerate(ideal[:k]):
        idcg += ((2 ** g) - 1) / math.log2(i + 2)
    if idcg == 0:
        return 0.0
    return dcg_at_k(ranked, qrels, k) / idcg


def mrr(ranked: Sequence[str], qrels: Dict[str, int]) -> float:
    ranked = _dedup(ranked)
    for i, d in enumerate(ranked):
        if _rel(qrels, d) >= 1:
            return 1.0 / (i + 1)
    return 0.0


def mean_ci(values: Sequence[float]) -> Tuple[float, float]:
    """Mean and 95% confidence half-width (normal approx)."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n == 0:
        return 0.0, 0.0
    mean = sum(vals) / n
    if n < 2:
        return mean, 0.0
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    se = math.sqrt(var / n)
    return mean, 1.96 * se


def retrieval_metrics(ranked: List[str], qrels: Dict[str, int],
                      ks: Sequence[int]) -> Dict[str, float]:
    out: Dict[str, float] = {"mrr": mrr(ranked, qrels)}
    for k in ks:
        out[f"recall@{k}"] = recall_at_k(ranked, qrels, k)
        out[f"ndcg@{k}"] = ndcg_at_k(ranked, qrels, k)
        out[f"precision@{k}"] = precision_at_k(ranked, qrels, k)
    return out


def cohen_kappa(pairs: Sequence[Tuple[object, object]]) -> float:
    """Cohen's kappa over (label_a, label_b) pairs; NaN when there are none.

    Chance agreement is computed from each rater's own marginals, so it works
    for any label alphabet -- 0/1/2 relevance grades, verdict strings, booleans.
    """
    n = len(pairs)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in pairs) / n
    ra = Counter(a for a, _ in pairs)
    rb = Counter(b for _, b in pairs)
    pe = sum(ra[k] * rb[k] for k in set(ra) | set(rb)) / (n * n)
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)
