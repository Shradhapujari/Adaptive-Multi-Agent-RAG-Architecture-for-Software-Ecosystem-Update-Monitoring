"""
decide: a verdict with evidence obligations, computed by rule from the pool.
=========================================================================

Fourteen findings say every arm retrieves the same documents (nDCG@3 0.30 on
every arm at n=500, 101 won / 103 lost at n=1000). Retrieval metrics cannot
separate architectures that fetch the same thing, so the output changes type:
not a paragraph over the top-k, but a *decision* about the update, each
decision carrying the rule-checkable evidence it needs before it may be made.

    verdict             obligation (every clause checked against the pool)
    ------------------  ------------------------------------------------------
    patch_urgently      an advisory-tier document (CISA KEV / CVE feed) about
                        the product, carrying a CVE id, matching the asked
                        version when one is asked
    hold                >= K community reports of a problem on the product /
                        asked version, and no vendor release newer than the
                        newest report that says it is fixed
    update_with_caveat  a release note for the product / asked version that
                        names a breaking change, deprecation or known issue --
                        or problem reports that a newer release says it fixed
    safe                a release note for the product / asked version, no
                        advisory, fewer than K problem reports, no caveat
    insufficient_evidence  none of the above holds within the pool -> abstain

Precedence is the table's order: an exploited CVE outranks a regression
thread, which outranks a changelog caveat, which outranks silence.

Rule-based and model-free on purpose, for the reason guardrail.py gives: the
check has to run when Ollama is down, and -- the Phase 2 bet -- if structure
does not help as plain Python over the pool we already retrieve, no
orchestration framework will make it help. A document's prose never reaches the
verdict; only fields extracted from it do (source class, CVE ids, version
tokens, dates, problem / fix / caveat markers), which is also what makes an
injected instruction inside a Reddit post irrelevant to the decision.

The five verdicts collapse onto the three the annotation sheet uses
(docs/decision_annotation_guide.md): patch_urgently, update_with_caveat and
safe are all `act`. The five-way split is kept because it names *which*
obligation fired, which is what a human gate (Phase 3) routes on.

    python decide.py                 # verdict distribution over the 200 sheet pools
    python decide.py --gold a1       # ... scored against one annotator's labels
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from eval_harness.benchmarks import extract_versions
from graph import Evidence, asks

# graph.classify answers "does an on-topic document *state the asked
# attribute*" (Evidence); decide answers "what should the asker *do*". The
# stop reasons map onto the graph's evidence classes so the two gates read
# the same way in a trace: no_evidence is ABSENT, an unmet obligation over
# on-topic documents is AMBIGUOUS, a met one is SUFFICIENT.
_EVIDENCE_CLASS = {"no_evidence": Evidence.ABSENT,
                   "evidence_insufficient": Evidence.AMBIGUOUS,
                   "obligations_met": Evidence.SUFFICIENT}

VERDICTS = ("patch_urgently", "hold", "update_with_caveat", "safe",
            "insufficient_evidence")
COLLAPSE = {"patch_urgently": "act", "update_with_caveat": "act", "safe": "act",
            "hold": "hold", "insufficient_evidence": "insufficient_evidence"}

# Source classes, by what a document can be evidence *of*. Mirrors TIER1/TIER2
# in multiagent_rag_v3 but split one level finer: an advisory and a release
# note are both tier 1 and carry different obligations.
ADVISORY = frozenset({"cisa_kev", "circl_cve", "nvd", "cve"})
RELEASE = frozenset({"vendor_releases", "releases", "llm_releases", "apple_rss"})
COMMUNITY = frozenset({"vendor_reddit", "reddit_live", "reddit_search",
                       "google_news", "github", "local"})

# How many independent community reports make a regression a reason to wait.
# One popular wrong post is the failure mode docs/Roadmap names; two is the
# smallest number that is not one post.
K_REPORTS = 2

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
_PROBLEM_RE = re.compile(
    r"\b(brok(e|en)|crash(es|ed|ing)?|bug|regression|not working|stopped working|"
    r"fail(s|ed|ing)?|stuck|bricked|freez(es|ing)|boot ?loop|won'?t (boot|start|open)|"
    r"issue|problem|unusable|drain)\b", re.I)
_FIX_RE = re.compile(r"\b(fix(es|ed)?|resolv(es|ed)|patch(es|ed)?|addresses|hotfix)\b", re.I)
_CAVEAT_RE = re.compile(
    r"\b(breaking change|breaking|deprecat(ed|es|ion)|removed|no longer support|"
    r"incompatib|known issue|requires? (manual|migration)|migration required)\b", re.I)
_DATE_RE = re.compile(r"\b(\d{4})-?(\d{2})-?(\d{2})\b")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9.+#-]{1,}")
_STOP = frozenset("the a an and or to of in on for is are was were be been with "
                  "after update updated updating upgrade upgraded version latest new "
                  "anyone else help why how does did do my i it this that".split())


@dataclass
class Decision:
    verdict: str
    evidence: List[str] = field(default_factory=list)     # doc_ids the rule used
    obligations: Dict[str, bool] = field(default_factory=dict)
    stop_reason: str = ""          # obligations_met | no_evidence | evidence_insufficient
    probes_wanted: List[str] = field(default_factory=list)  # source class a graph would fetch next
    confidence: float = 0.0
    rationale: str = ""

    @property
    def verdict3(self) -> str:
        return COLLAPSE[self.verdict]

    @property
    def evidence_class(self) -> Evidence:
        return _EVIDENCE_CLASS[self.stop_reason]

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "verdict3": self.verdict3,
                "evidence_class": self.evidence_class.value,
                "evidence_doc_ids": list(self.evidence), "obligations": dict(self.obligations),
                "stop_reason": self.stop_reason, "probes_wanted": list(self.probes_wanted),
                "confidence": self.confidence, "rationale": self.rationale}


# ----------------------------------------------------------------- extraction

def _text(d: dict) -> str:
    return f"{d.get('title', '')} {d.get('text', '') or d.get('detail', '')}"


def _date(d: dict) -> Optional[str]:
    m = _DATE_RE.search(str(d.get("date") or ""))
    return "".join(m.groups()) if m else None


def _tokens(s: str) -> set:
    return {w for w in _WORD_RE.findall(s.lower()) if w not in _STOP and len(w) > 2}


def _vendor_tokens(vendors: Iterable[str]) -> set:
    out = set()
    for v in vendors:
        out |= {w for w in _WORD_RE.findall(str(v).lower()) if len(w) > 2}
    return out


def _about(d: dict, vtoks: set, qtoks: set) -> bool:
    """Is the document about the asked product? With a known vendor, the vendor
    name has to appear; without one, fall back to sharing two content tokens
    with the question. The fallback is deliberately weak -- a document the
    question's own words do not touch is not evidence about it."""
    toks = _tokens(_text(d))
    if vtoks:
        return bool(toks & vtoks)
    return len(toks & qtoks) >= 2


def _version_ok(d: dict, asked: Sequence[str]) -> bool:
    """True when no version was asked, or the document names the asked one
    (prefix match, so "26.1" is satisfied by "26.1.1")."""
    if not asked:
        return True
    found = extract_versions(_text(d), multipart_only=False)
    return any(f == a or f.startswith(a + ".") or a.startswith(f + ".")
               for f in found for a in asked)


# ---------------------------------------------------------------------- rules

def decide(pool: Sequence[dict], question: str, vendors: Iterable[str] = (),
           versions: Optional[Sequence[str]] = None, k_reports: int = K_REPORTS) -> Decision:
    """The verdict the pool supports, with the obligations it met and missed.

    `vendors` are the grounded product names (grounding.ground / the sheet's
    `vendor`); `versions` default to the dotted versions in the question.
    """
    asked = list(versions) if versions is not None else \
        extract_versions(question, multipart_only=True)
    vtoks, qtoks = _vendor_tokens(vendors), _tokens(question)
    about = [d for d in pool if d.get("doc_id") and _about(d, vtoks, qtoks)]
    on_version = [d for d in about if _version_ok(d, asked)]

    # An advisory counts when it is about the product even if it does not name
    # the asked version: KEV rows carry a CVE id and a product, not an affected
    # range, and "patch" is the right call for a product under active
    # exploitation. Whether the version was confirmed shows in `confidence`.
    advisories = [d for d in about if d.get("source") in ADVISORY
                  and _CVE_RE.search(_text(d) + " " + str(d.get("url", "")))]
    releases = [d for d in on_version if d.get("source") in RELEASE]
    reports = [d for d in on_version
               if d.get("source") in COMMUNITY and _PROBLEM_RE.search(_text(d))]
    newest_report = max((_date(d) or "" for d in reports), default="")
    fix_releases = [d for d in releases if _FIX_RE.search(_text(d))
                    and (_date(d) or "") > newest_report]
    caveats = [d for d in releases if _CAVEAT_RE.search(_text(d))]

    obligations = {
        "about_product": bool(about),
        "version_matched": bool(on_version),
        "advisory_with_cve": bool(advisories),
        "reports_at_least_k": len(reports) >= k_reports,
        "no_newer_fix_release": not fix_releases,
        "release_note_present": bool(releases),
        "caveat_named": bool(caveats),
    }
    ids = lambda docs: [d["doc_id"] for d in docs]  # noqa: E731

    if advisories:
        versioned = any(_version_ok(d, asked) for d in advisories)
        return Decision("patch_urgently", ids(advisories), obligations, "obligations_met",
                        [], 1.0 if versioned else 0.8,
                        f"{len(advisories)} advisory document(s) with a CVE id about the "
                        f"product" + (f" on {asked[0]}" if versioned and asked else ""))
    if len(reports) >= k_reports and not fix_releases:
        return Decision("hold", ids(reports), obligations, "obligations_met", ["release"],
                        min(1.0, len(reports) / (2 * k_reports)),
                        f"{len(reports)} community reports of a problem and no newer "
                        f"release note saying it is fixed")
    if caveats or (reports and fix_releases):
        used = caveats or (fix_releases + reports)
        return Decision("update_with_caveat", ids(used), obligations, "obligations_met", [],
                        0.8, "release note names a caveat" if caveats else
                        f"{len(reports)} problem report(s) and a newer release that fixes")
    if releases:
        # Absence-based: safe because nothing bad was found, so lower confidence
        # and name what a graph should still go and look for.
        probes = [p for p, have in (("cve", advisories), ("community", reports)) if not have]
        return Decision("safe", ids(releases), obligations, "obligations_met", probes, 0.6,
                        "release note present, no advisory, fewer than "
                        f"{k_reports} problem reports")
    # Nothing an obligation can stand on. Say which class of evidence is missing
    # so an active prober knows where to look instead of re-rolling the rewrite.
    missing = [p for p, have in (("release", releases), ("cve", advisories),
                                 ("community", reports)) if not have]
    reason = "no_evidence" if not about else "evidence_insufficient"
    return Decision("insufficient_evidence", [], obligations, reason, missing, 0.0,
                    "no document about the product" if not about else
                    "documents about the product, none meeting an obligation")


# ------------------------------------------------------------------ rendering

REFUSAL = ("I cannot determine that from the sources retrieved, so I am not "
           "going to state it.")   # same wording as guardrail.REFUSAL, trips is_abstention

_LEAD = {
    "patch_urgently": "Patch now",
    "hold": "Hold off on this update",
    "update_with_caveat": "Update, with a caveat",
    "safe": "Safe to update",
}


def render(decision: Decision, pool: Sequence[dict]) -> str:
    """One sentence a user can act on, citing the documents the rule used."""
    if decision.verdict == "insufficient_evidence":
        return REFUSAL
    by_id = {d.get("doc_id"): d for d in pool}
    cites = " ".join(f"[{by_id[i].get('title', '')[:60]}]" for i in decision.evidence[:3]
                     if i in by_id)
    return f"{_LEAD[decision.verdict]}: {decision.rationale}. {cites}".strip()


# ---------------------------------------------------------------- self-check

def _score(rows: List[dict], gold_block: str) -> dict:
    """System verdict (collapsed) against one annotator block's labels."""
    from collections import Counter
    tp, fp, fn = Counter(), Counter(), Counter()
    abst_tp = abst_fp = abst_fn = 0
    ev_p, ev_r, n = [], [], 0
    for r in rows:
        g = (r.get(gold_block) or {}).get("verdict")
        if g is None:
            continue
        n += 1
        d = decide(r["evidence"], r["query"], vendors=[r.get("vendor", "")])
        p = d.verdict3
        (tp if p == g else fp)[p] += 1
        if p != g:
            fn[g] += 1
        if p == "insufficient_evidence" and g == "insufficient_evidence":
            abst_tp += 1
        elif p == "insufficient_evidence":
            abst_fp += 1
        elif g == "insufficient_evidence":
            abst_fn += 1
        gold_ids = set((r[gold_block] or {}).get("evidence_doc_ids") or [])
        if gold_ids and d.evidence:
            inter = len(gold_ids & set(d.evidence))
            ev_p.append(inter / len(d.evidence))
            ev_r.append(inter / len(gold_ids))
    if not n:
        return {"n": 0}
    f1 = []
    for c in ("act", "hold", "insufficient_evidence"):
        pr = tp[c] / (tp[c] + fp[c]) if tp[c] + fp[c] else 0.0
        rc = tp[c] / (tp[c] + fn[c]) if tp[c] + fn[c] else 0.0
        f1.append(2 * pr * rc / (pr + rc) if pr + rc else 0.0)
    return {
        "n": n, "accuracy": round(sum(tp.values()) / n, 3),
        "macro_f1": round(sum(f1) / 3, 3),
        "abstention_precision": round(abst_tp / (abst_tp + abst_fp), 3) if abst_tp + abst_fp else None,
        "abstention_recall": round(abst_tp / (abst_tp + abst_fn), 3) if abst_tp + abst_fn else None,
        "evidence_precision": round(sum(ev_p) / len(ev_p), 3) if ev_p else None,
        "evidence_recall": round(sum(ev_r) / len(ev_r), 3) if ev_r else None,
    }


if __name__ == "__main__":
    import argparse
    import json
    from collections import Counter

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--sheet", default="data/decision_benchmark_200.jsonl")
    ap.add_argument("--gold", default=None, help="annotator block to score against (a1, a2, gold)")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.sheet) if l.strip()]
    decs = [decide(r["evidence"], r["query"], vendors=[r.get("vendor", "")]) for r in rows]
    print(f"{len(rows)} questions, pool median {sorted(len(r['evidence']) for r in rows)[len(rows)//2]}")
    print("verdict (5):", dict(Counter(d.verdict for d in decs)))
    print("verdict (3):", dict(Counter(d.verdict3 for d in decs)))
    print("stop_reason:", dict(Counter(d.stop_reason for d in decs)))
    print("probes wanted:", dict(Counter(p for d in decs for p in d.probes_wanted)))
    # The sheet carries graph.asks already; fall back to it for any row that
    # does not, so the strata are the gate's and nobody's second opinion.
    strata = [r.get("asks") or asks(r["query"]) for r in rows]
    by_asks = Counter((a, d.verdict3) for a, d in zip(strata, decs))
    for a_ in sorted(set(strata)):
        print(f"  {a_:11s}", {v: by_asks[(a_, v)] for v in ("act", "hold", "insufficient_evidence")})
    if a.gold:
        print(f"vs {a.gold}:", json.dumps(_score(rows, a.gold)))
