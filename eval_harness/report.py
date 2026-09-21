"""
Reporting: aggregate per-query rows into comparison tables and plots.
====================================================================
Produces the head-to-head deliverables reviewers asked for: a markdown table
(system x metric, with 95% CIs), a CSV, and matplotlib bar charts.
"""

from __future__ import annotations

import csv
import os
from collections import defaultdict
from typing import Dict, List

from .metrics import mean_ci


def _metric_keys(ks: List[int]) -> List[str]:
    keys = ["mrr"]
    for k in ks:
        keys += [f"ndcg@{k}", f"recall@{k}"]
    return keys


ANSWER_KEYS = ["faithfulness", "answer_relevance", "correctness"]


def aggregate(rows: List[dict], ks: List[int]) -> dict:
    """Return {system: {metric: (mean, ci, n)}} plus per-category breakdown."""
    by_system: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    by_cat: Dict[str, Dict[str, Dict[str, list]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list)))

    ir_keys = _metric_keys(ks)
    for r in rows:
        sysname = r["system"]
        cat = r.get("category", "general")
        for mk in ir_keys:
            if r["ir"] and mk in r["ir"]:
                by_system[sysname][mk].append(r["ir"][mk])
                by_cat[cat][sysname][mk].append(r["ir"][mk])
        for ak in ANSWER_KEYS:
            v = (r.get("answer_scores") or {}).get(ak)
            if v is not None:
                by_system[sysname][ak].append(v)
                by_cat[cat][sysname][ak].append(v)
        if r.get("self_quality") is not None:
            by_system[sysname]["self_quality"].append(r["self_quality"])
        by_system[sysname]["latency_s"].append(r.get("latency_s", 0.0))
        tk = r.get("tokens")
        if tk:
            by_system[sysname]["model_calls"].append(tk.get("calls", 0))
            by_system[sysname]["tokens"].append(tk.get("total_tokens", 0))

    def summarize(d):
        out = {}
        for metric, vals in d.items():
            m, ci = mean_ci(vals)
            out[metric] = (round(m, 4), round(ci, 4), len(vals))
        return out

    return {
        "systems": {s: summarize(d) for s, d in by_system.items()},
        "by_category": {c: {s: summarize(d) for s, d in sd.items()}
                        for c, sd in by_cat.items()},
        "ir_keys": ir_keys,
        "answer_keys": ANSWER_KEYS,
    }


def write_csv(agg: dict, path: str) -> None:
    cols = (["system"] + agg["ir_keys"] + agg["answer_keys"]
            + ["self_quality", "latency_s", "model_calls", "tokens"])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for s, m in agg["systems"].items():
            row = [s]
            for c in cols[1:]:
                row.append(m[c][0] if c in m else "")
            w.writerow(row)


# Below this many observations a mean is not reportable as a number with a
# confidence interval. n=1 yields "1.000±0.000", which reads as a perfect score
# measured with certainty; it is one question. Seen in the wild: a 100-question
# run whose `correctness` column was computed on 1-2 questions, because only
# those carried ground truth.
MIN_REPORTABLE_N = 5


def _fmt(cell, n_expected: int = 0) -> str:
    """
    Render one metric cell, making a thin sample impossible to mistake for a
    measurement. The count is shown whenever the metric was not computed on
    every question, since that is exactly when a bare mean misleads.
    """
    if not cell:
        return "—"
    mean, ci, n = cell
    if n == 0:
        return "—"
    if n < MIN_REPORTABLE_N:
        return f"{mean:.3f} (n={n}, too few)"
    if n_expected and n < n_expected:
        return f"{mean:.3f}±{ci:.3f} (n={n})"
    return f"{mean:.3f}±{ci:.3f}"


def _expected_n(m: dict) -> int:
    """Questions this system answered: latency is recorded once per question."""
    cell = m.get("latency_s")
    return cell[2] if cell else 0


def write_markdown(agg: dict, cfg: dict, path: str) -> None:
    L = []
    L.append("# Multi-Agent RAG System Evaluation Report\n")
    L.append(f"- Dataset: `{cfg.get('dataset')}` "
             f"({cfg.get('n_questions')} questions, hash `{cfg.get('dataset_hash')}`)")
    L.append(f"- Judge: `{cfg.get('judge')}` "
             f"({'active' if cfg.get('judge_active') else 'inactive'})")
    L.append(f"- Systems: {', '.join(cfg.get('systems_evaluated', []))}")
    L.append(f"- Seed: {cfg.get('seed')}  |  top_k: {cfg.get('top_k')}\n")
    L.append("Values are mean ± 95% CI. IR metrics use LLM-judged graded "
             "relevance (qrels). Answer metrics are LLM-as-judge (0–1).\n")

    # Main comparison table.
    metrics = agg["ir_keys"] + agg["answer_keys"]
    header = "| System | " + " | ".join(metrics) + " | self_quality | latency_s | calls | tokens |"
    sep = "|" + "---|" * (len(metrics) + 5)
    L.append("## Head-to-head\n")
    L.append(header)
    L.append(sep)
    thin = False
    for s, m in agg["systems"].items():
        n_exp = _expected_n(m)
        cells = [_fmt(m.get(k), n_exp) for k in metrics]
        thin = thin or any("n=" in c for c in cells)
        sq = f"{m['self_quality'][0]:.3f}" if "self_quality" in m else "—"
        lat = f"{m['latency_s'][0]:.2f}" if "latency_s" in m else "—"
        calls = f"{m['model_calls'][0]:.1f}" if "model_calls" in m else "—"
        tok = f"{m['tokens'][0]:.0f}" if "tokens" in m else "—"
        L.append(f"| {s} | " + " | ".join(cells) + f" | {sq} | {lat} | {calls} | {tok} |")
    L.append("")

    # Per-category nDCG@k (k = first in list) if present.
    if agg["by_category"]:
        primary = next((k for k in agg["ir_keys"] if k.startswith("ndcg")), None)
        if primary:
            L.append(f"## Per-category {primary}\n")
            systems = list(agg["systems"].keys())
            L.append("| Category | " + " | ".join(systems) + " |")
            L.append("|" + "---|" * (len(systems) + 1))
            for cat, sd in sorted(agg["by_category"].items()):
                cells = [_fmt(sd.get(s, {}).get(primary), _expected_n(sd.get(s, {})))
                         for s in systems]
                L.append(f"| {cat} | " + " | ".join(cells) + " |")
            L.append("")

    if thin:
        L.append(f"> Note: cells carrying `(n=...)` were computed on fewer than "
                 f"the full question set — a metric is only scored where its "
                 f"input exists (e.g. `correctness` needs ground truth). Below "
                 f"n={MIN_REPORTABLE_N} the CI is omitted: it would read as "
                 f"precision the sample cannot support.\n")
    L.append("> Note: `self_quality` is Multi-Agent RAG System's original built-in heuristic, "
             "shown only for reference — it is not a standard metric.\n")
    open(path, "w").write("\n".join(L))


def write_plots(agg: dict, run_dir: str, ks: List[int]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    systems = list(agg["systems"].keys())

    def bar(metrics, title, fname):
        present = [m for m in metrics
                   if any(m in agg["systems"][s] for s in systems)]
        if not present:
            return
        import numpy as np
        x = np.arange(len(present))
        width = 0.8 / max(len(systems), 1)
        fig, ax = plt.subplots(figsize=(max(7, len(present) * 1.6), 4.5))
        for i, s in enumerate(systems):
            means = [agg["systems"][s].get(m, (0, 0, 0))[0] for m in present]
            errs = [agg["systems"][s].get(m, (0, 0, 0))[1] for m in present]
            ax.bar(x + i * width, means, width, yerr=errs, capsize=3, label=s)
        ax.set_xticks(x + width * (len(systems) - 1) / 2)
        ax.set_xticklabels(present, rotation=20, ha="right")
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("score")
        ax.set_title(title)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(run_dir, fname), dpi=130)
        plt.close(fig)

    bar(agg["ir_keys"], "Retrieval quality (IR metrics)", "plot_retrieval.png")
    bar(agg["answer_keys"], "Answer quality (LLM-as-judge)", "plot_answer.png")
