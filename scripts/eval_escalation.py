"""Escalation & abstention correctness: did the system spend, abstain and escalate right?

A product eval, not a model eval: it scores the *decisions* the pipeline makes
around an answer, all of them deterministic, over pools already on disk.

    a) routing     graph.route_query against hand labels (ROUTE_GOLD)
    b) abstention  ABSENT on a healthy fetch must abstain on round 1, no retry;
                   with --gold, abstention precision/recall vs an annotator
    c) high stakes a CISA KEV row whose product field names the asked product
                   must decide `patch_urgently`; anything greener is a false green

Every failure is tagged with a mode (FAILURE_MODES) and, with --freeze,
appended to tests/regression/frozen_failures.jsonl with its pool, where
tests/test_escalation_eval.py replays it on every run of the suite.

    python scripts/eval_escalation.py                        # 200 sheet pools, offline
    python scripts/eval_escalation.py --gold a1              # + abstention P/R vs annotator a1
    python scripts/eval_escalation.py --run results/run_X    # + modes in that run's per_query.jsonl
    python scripts/eval_escalation.py --freeze               # append new failures to the regression file
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import decide  # noqa: E402
import graph  # noqa: E402
from eval_harness.benchmarks import is_abstention  # noqa: E402
from guardrail import normalize  # noqa: E402

FROZEN = os.path.join(ROOT, "tests", "regression", "frozen_failures.jsonl")

# Hand labels, written from the question alone: one product and one value is
# a lookup (`fast`); several products, or a judgement, is `full`.
ROUTE_GOLD = [
    ("What is the latest version of Firefox?", "fast"),
    ("When does iOS 27 come out?", "fast"),
    ("Which release of Node.js is current?", "fast"),
    ("Firefox vs Chrome: which is more stable right now?", "full"),
    ("Is Ubuntu 24.04 more stable than Fedora 44?", "full"),
    ("Did macOS 26.1 break Bluetooth?", "full"),
    ("Is it safe to update Firefox right now?", "full"),
    ("Is CVE-2026-1234 fixed in Chrome 140?", "full"),
    ("Should I upgrade to Windows 11 25H2?", "full"),
    ("What are the latest versions of Python and Node.js?", "full"),
    ("Latest version of Postgres or MySQL?", "full"),
    ("When will Kubernetes 1.35 and Docker 29 be released?", "full"),
]

FAILURE_MODES = {
    "query_drop": "retrieval returned nothing, or generation errored",
    "unanswerable_leak": "evidence ABSENT / insufficient, yet the answer is not an abstention",
    "retry_on_absent": "ABSENT on a healthy fetch was rewritten and fetched again",
    "false_green": "a KEV row names the product, verdict is act-but-not-patch",
    "missed_advisory": "a KEV row names the product, verdict is hold / insufficient_evidence",
    "attribution_mismatch": "patch_urgently cites an advisory that never names the product",
    "judge_parse_failure": "the judge returned no score on any axis",
}

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)


def _words(vendor: str) -> list:
    return [w for w in re.findall(r"[a-z0-9][a-z0-9.+#-]{2,}", vendor.lower())]


def kev_names_vendor(doc: dict, vendor: str) -> bool:
    """A CISA KEV row with a CVE id whose product field names the vendor.

    KEV titles end "— <product>"; matching there, on word boundaries, keeps
    "MySQL / SQL" off "Metabase SQL Injection" and "Rust" off "untrusted".
    Independent of decide's attribution on purpose: two rules that agree are
    a check, one rule scored against itself is not.
    """
    if doc.get("source") != "cisa_kev":
        return False
    title = normalize(str(doc.get("title") or ""))
    if not _CVE_RE.search(normalize(f"{title} {doc.get('text', '')} {doc.get('url', '')}")):
        return False
    product = title.rsplit("—", 1)[-1].lower()
    return any(re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", product) for w in _words(vendor))


def walk(row: dict):
    """(graph state, Decision) for one sheet row, through the same graph and
    gate the marag_decide arm uses, over the row's recorded pool."""
    pool = row["evidence"]
    s = graph.run(row["query"], rewrite=lambda q, tried: q, retrieve=lambda q: (pool, False),
                  gate=decide.gate([row.get("vendor", "")]))
    return s, decide.Decision.from_dict(s.payload)


def failure_modes(row: dict, s, dec) -> list:
    """The FAILURE_MODES this decision exhibits on this row's pool."""
    pool, vendor = row["evidence"], row.get("vendor", "")
    modes = []
    if s.evidence is graph.Evidence.ABSENT and len(s.tried) > 1:
        modes.append("retry_on_absent")
    if dec.verdict == "insufficient_evidence" and not is_abstention(decide.render(dec, pool)):
        modes.append("unanswerable_leak")
    if any(kev_names_vendor(d, vendor) for d in pool):
        if dec.verdict3 == "act" and dec.verdict != "patch_urgently":
            modes.append("false_green")
        elif dec.verdict3 != "act":
            modes.append("missed_advisory")
    if dec.verdict == "patch_urgently":
        by_id = {d["doc_id"]: d for d in pool}
        words = _words(vendor)
        # ponytail: a word match, so "MariaDB Connector/Node.js" still passes for
        # Node.js; a product catalogue would catch that one.
        if any(not any(w in normalize(decide._text(by_id[i])).lower() for w in words)
               for i in dec.evidence if i in by_id):
            modes.append("attribution_mismatch")
    return modes


def run_modes(run_dir: str) -> Counter:
    """Modes readable from a harness run's rows, for every arm."""
    c = Counter()
    for line in open(os.path.join(run_dir, "per_query.jsonl")):
        r = json.loads(line)
        sysname, ans = r.get("system"), str(r.get("answer") or "")
        if not r.get("n_docs") or ans.startswith("[generation error"):
            c[(sysname, "query_drop")] += 1
        if (r.get("decision") or {}).get("evidence_class") == "absent":
            if r.get("rounds", 1) > 1:
                c[(sysname, "retry_on_absent")] += 1
            if not is_abstention(ans):
                c[(sysname, "unanswerable_leak")] += 1
        sc = r.get("answer_scores")
        if sc and all(v is None for k, v in sc.items() if k != "correctness"):
            c[(sysname, "judge_parse_failure")] += 1
    return c


def _pct(a, b):
    return f"{a}/{b} ({a / b:.0%})" if b else f"{a}/0"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sheet", default=os.path.join(ROOT, "data", "decision_benchmark_200.jsonl"))
    ap.add_argument("--gold", help="annotator block for abstention P/R (a1, a2, gold)")
    ap.add_argument("--run", help="results/run_* dir: tag modes in its per_query.jsonl")
    ap.add_argument("--freeze", action="store_true", help=f"append new failures to {FROZEN}")
    a = ap.parse_args()

    print("a) routing vs hand labels")
    miss = [(q, w, graph.route_query(q)) for q, w in ROUTE_GOLD if graph.route_query(q)[0] != w]
    print(f"   accuracy {_pct(len(ROUTE_GOLD) - len(miss), len(ROUTE_GOLD))}")
    for q, w, got in miss:
        print(f"   MISROUTE want {w}, got {got[0]} ({got[1]}): {q}")
    print("   note: this scores the route label; app_1.run_fast dispatches on its own "
          "gate (grounding finds exactly one vendor)")

    rows = [json.loads(l) for l in open(a.sheet) if l.strip()]
    walked = [(r, *walk(r)) for r in rows]
    ev = Counter(s.evidence.value for _, s, _ in walked)
    absent = [s for _, s, _ in walked if s.evidence is graph.Evidence.ABSENT]
    r1 = sum(1 for s in absent if [st.node for st in s.trace] == ["rewrite", "retrieve", "classify", "abstain"])
    print(f"\nb) abstention over {len(rows)} sheet pools")
    print(f"   evidence class {dict(ev)}  (ABSENT {_pct(len(absent), len(rows))})")
    print(f"   ABSENT abstained on round 1, no retry: {_pct(r1, len(absent))}")
    print(f"   model calls: verify only, on AMBIGUOUS: {ev.get('ambiguous', 0)} "
          f"of {len(rows)} questions")
    if a.gold:
        print(f"   vs {a.gold}: {json.dumps(decide._score(rows, a.gold))}")

    kev = [(r, s, d) for r, s, d in walked
           if any(kev_names_vendor(x, r.get("vendor", "")) for x in r["evidence"])]
    hit = sum(1 for _, _, d in kev if d.verdict == "patch_urgently")
    print("\nc) high stakes: pools with a KEV row naming the product")
    print(f"   patch_urgently {_pct(hit, len(kev))}")

    tagged = [(r, m) for r, s, d in walked for m in failure_modes(r, s, d)]
    print(f"\nfailure modes on the sheet: {dict(Counter(m for _, m in tagged)) or 'none'}")
    for r, m in tagged:
        print(f"   {m:20s} #{r['id']:<4} {r.get('vendor', '')[:18]:18s} {r['query'][:70]}")

    if a.run:
        c = run_modes(a.run)
        print(f"\nfailure modes in {a.run}: {'' if c else 'none'}")
        for (sysname, m), n in sorted(c.items()):
            print(f"   {sysname:28s} {m:20s} {n}")

    if a.freeze:
        os.makedirs(os.path.dirname(FROZEN), exist_ok=True)
        have = {(c["id"], c["mode"]) for c in map(json.loads, open(FROZEN))} \
            if os.path.exists(FROZEN) else set()
        new = [r | {"mode": m, "status": "open", "note": FAILURE_MODES[m]}
               for r, m in tagged if (r["id"], m) not in have]
        with open(FROZEN, "a") as f:
            for c in new:
                f.write(json.dumps({k: c[k] for k in ("id", "mode", "status", "note",
                                                      "query", "vendor", "evidence")}) + "\n")
        print(f"\nfroze {len(new)} new case(s) into {os.path.relpath(FROZEN, ROOT)}")


if __name__ == "__main__":
    main()
