"""
Explain a presented answer: which source each claim rests on, and why that
source was in the pool at all.

Two questions get asked of this system in a demo and neither is answered by the
paragraph itself: "where did that come from?" and "why did it look at that
thread?". The pipeline already knows both -- the citation label ties a sentence
to an Evidence row, and the row carries the terms, the date and the security
flag that put it in front of the presenter. This module only reads that back.

No model involved: an explanation produced by a second model is one more thing
to verify, and the honest trace here is a join, not an inference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from eval_harness.benchmarks import content_tokens, extract_dates, extract_versions

import guardrail

__all__ = ["Trace", "explain", "render"]

_SENT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Trace:
    query: str
    sources: List[Dict] = field(default_factory=list)
    sentences: List[Dict] = field(default_factory=list)
    violations: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def _why(query_terms: set, e) -> str:
    """One line saying what put this source in the pool."""
    hit = sorted(query_terms & set(content_tokens(f"{getattr(e, 'title', '')} "
                                                  f"{getattr(e, 'detail', '')}")))
    bits = [f"matches {', '.join(repr(t) for t in hit)}"] if hit else ["no query-term overlap"]
    if getattr(e, "date", ""):
        bits.append(f"dated {e.date}")
    if getattr(e, "security", False):
        bits.append("flagged SECURITY")
    if getattr(e, "sentiment", ""):
        bits.append(f"{e.sentiment.lower()} sentiment")
    return "; ".join(bits)


def explain(query: str, answer: str, evidence: Sequence) -> Trace:
    """Join an answer back onto its evidence, sentence by sentence."""
    terms = set(content_tokens(query))
    text = (answer or "").strip()
    cited_anywhere = {c.strip() for c in guardrail._CITE_RE.findall(text)}

    sources = [{
        "label": getattr(e, "label", ""),
        "kind": getattr(e, "kind", ""),
        "title": getattr(e, "title", ""),
        "url": getattr(e, "url", ""),
        "why_retrieved": _why(terms, e),
        "used": getattr(e, "label", "") in cited_anywhere,
    } for e in evidence or ()]

    sentences = []
    for s in filter(None, (x.strip() for x in _SENT_RE.split(text))):
        cites = [c.strip() for c in guardrail._CITE_RE.findall(s)]
        facts = extract_versions(guardrail._ISO_RE.sub(" ", s)) + extract_dates(s)
        sentences.append({
            "text": s,
            "cites": cites,
            "facts": facts,
            # A sentence that states a version or a date and cites nothing is
            # the shape a hallucination arrives in, even when the fact is real.
            "grounded": bool(cites) or not facts,
        })

    v = guardrail.check(text, evidence)
    return Trace(query, sources, sentences, [str(x) for x in v.violations])


def render(trace: Trace) -> str:
    """The trace as the text a demo can put under the answer."""
    out = [f"Q: {trace.query}", "", "Why these sources:"]
    for s in trace.sources:
        mark = "used" if s["used"] else "unused"
        out.append(f"  [{s['label']}] {s['kind']:9s} {s['title'][:60]}")
        out.append(f"       {s['why_retrieved']}  ({mark})")
    out += ["", "Claim by claim:"]
    for s in trace.sentences:
        src = ", ".join(f"[{c}]" for c in s["cites"]) or "— no citation"
        flag = "" if s["grounded"] else "  << states a fact with no source"
        out.append(f"  {s['text'][:80]}\n       {src}{flag}")
    if trace.violations:
        out += ["", "Guardrail:"] + [f"  {v}" for v in trace.violations]
    return "\n".join(out)


def _demo() -> None:
    from answer_agent import Evidence

    ev = [
        Evidence(label="R1", kind="release", title="Fedora 44 released",
                 date="2026-09-01", security=True, detail="kernel 6.17.2"),
        Evidence(label="C1", kind="community", title="Anyone else losing grub after update?",
                 date="2026-09-02", sentiment="Negative"),
        Evidence(label="R2", kind="release", title="Debian 13.2 point release",
                 date="2026-08-20"),
    ]
    q = "did the fedora 44 update break grub"
    a = ("Fedora 44 shipped on 2026-09-01 with kernel 6.17.2 [R1]. "
         "Users report grub loss after it [C1]. Nothing points at a fix yet.")

    t = explain(q, a, ev)
    assert t.ok, t.violations
    assert [s["used"] for s in t.sources] == [True, True, False]
    assert "'fedora'" in t.sources[0]["why_retrieved"] and "SECURITY" in t.sources[0]["why_retrieved"]
    assert "no query-term overlap" in t.sources[2]["why_retrieved"]   # Debian row, off topic
    assert len(t.sentences) == 3
    assert t.sentences[2]["grounded"]                                  # no facts, no citation needed

    bad = explain(q, "Fedora 45 is out.", ev)
    assert not bad.sentences[0]["grounded"] and bad.violations
    print(render(t))


if __name__ == "__main__":
    _demo()
