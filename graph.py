"""The orchestration loop as a typed state machine, in stdlib.

    rewrite -> retrieve -> classify -> { answer | verify | abstain | rewrite }

`orchestrate()` in multiagent_rag_v3.py retries on a term-overlap score, so a
question no source can answer is rewritten until the round cap and then
answered anyway. Here the edge out of `classify` is decided by what the
documents *contain* (a version, a date, a stance, a CVE id about the asked
product), the only way back into `rewrite` is a fetch that failed, and
ABSENT on a healthy fetch is terminal: it abstains, and nothing retries it.

Nothing in this module calls a model or the network. `run()` takes the
rewriter, the retriever and the verifier as callables, so the graph is
exercised by the self-check below without Ollama, and so the eval harness can
wrap it as an arm whose fetches still go through the recorded corpus.

LangGraph was evaluated for this and rejected: it would bring an unpinned
dependency tree under a harness whose claim is byte-identical replay, for a
graph with one cycle. If the graph grows past a handful of nodes, `State`
and `EDGES` here are already its shape.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from typing import Callable, Dict, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tokens  # noqa: E402
from eval_harness.benchmarks import (content_tokens, extract_dates,  # noqa: E402
                                     extract_versions)
from eval_harness.judge import _extract_json  # noqa: E402
from yesno import looks_yesno, stance  # noqa: E402

MAX_ROUNDS = max(1, int(os.environ.get("MARAG_MAX_ROUNDS", "2")))
VERIFY_MAX_TOKENS = 40


class Evidence(Enum):
    SUFFICIENT = "sufficient"   # an on-topic doc states the asked attribute
    AMBIGUOUS = "ambiguous"     # on-topic docs; attribute missing or conflicting
    ABSENT = "absent"           # no doc is about the asked product
    DEGRADED = "degraded"       # the fetch itself failed; not an evidence class


@dataclass(frozen=True)
class Step:
    node: str
    edge_taken: str
    reason: str
    dur_ms: int
    tokens: dict
    contract_ok: bool
    state_hash_in: str
    state_hash_out: str
    out: dict = field(default_factory=dict)


@dataclass(frozen=True)
class State:
    query: str
    asks: str = "other"
    tried: Tuple[str, ...] = ()
    docs: Tuple[dict, ...] = ()
    evidence: Optional[Evidence] = None
    values: Tuple[str, ...] = ()        # what the gate found: versions, dates, ...
    degraded: bool = False
    payload: dict = field(default_factory=dict)   # whatever the gate wants kept (a Decision)
    grounded: Optional[bool] = None     # verify's answer, AMBIGUOUS only
    trace: Tuple[Step, ...] = ()

    def digest(self) -> str:
        d = asdict(replace(self, trace=()))
        d["evidence"] = self.evidence.value if self.evidence else None
        return hashlib.sha1(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


# ───────────────────────────────────────────────────────────── the gate

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)
_CVE_WORDS = re.compile(r"\bCVE-\d{4}-\d{4,7}\b|\b(?:vulnerab|exploit|security (?:fix|patch|update))", re.I)
_DATE_WORDS = re.compile(r"\b(when|release date|released|coming out|eta|how long)\b", re.I)
_VERSION_WORDS = re.compile(r"\b(latest|newest|version|which release|what release|v\d)\b", re.I)
_FIX_WORDS = re.compile(r"\b(fix(?:ed)?|broke(?:n)?|bug|crash|issue|problem|safe to|should i|okay to|worth)\b", re.I)


def asks(question: str) -> str:
    """The attribute a question wants decided: cve | date | version | stance | other.

    Order is specificity. "did 6.8 break grub?" names a version but asks about
    a fix, so the fix words outrank a bare version number; "latest" and "which
    version" outrank the fix words.
    """
    q = question or ""
    if _CVE_WORDS.search(q):
        return "cve"
    if _DATE_WORDS.search(q) or extract_dates(q):
        return "date"
    if _VERSION_WORDS.search(q):
        return "version"
    if _FIX_WORDS.search(q) or looks_yesno(q, is_title=True):
        return "stance"
    if extract_versions(q, multipart_only=True):
        return "version"
    return "other"


def _doc_text(d: dict) -> str:
    return " ".join(str(d.get(k) or "") for k in ("title", "text", "detail", "body", "top_comment"))


def on_topic(query: str, docs: Sequence[dict]) -> list:
    """Docs sharing a non-numeric content token with the question.

    Cheap and deterministic. It is the "about the product" test, not a
    relevance score: a doc about the right product that does not state the
    asked attribute is what makes the gate say AMBIGUOUS rather than ABSENT.
    """
    words = {t for t in content_tokens(query) if not t[0].isdigit()}
    return [d for d in docs if words & set(content_tokens(_doc_text(d)))]


def _values(kind: str, docs: Sequence[dict]) -> list:
    out = []
    for d in docs:
        t = _doc_text(d)
        if kind == "version":
            out += extract_versions(t, multipart_only=True)
        elif kind == "date":
            out += extract_dates(t) + ([d["date"]] if d.get("date") else [])
        elif kind == "cve":
            out += [c.upper() for c in _CVE_RE.findall(t)]
        elif kind == "stance":
            s = stance(str(d.get("top_comment") or d.get("text") or d.get("detail") or ""))
            if s != "unclear":
                out.append(s)
    return sorted(set(out))


def classify(query: str, docs: Sequence[dict], degraded: bool = False,
             kind: Optional[str] = None) -> Tuple[Evidence, str, list]:
    """(evidence class, reason, values) for one question over its documents.

    Zero model calls. SUFFICIENT needs an on-topic document that states the
    asked attribute; a stance needs the stances to agree. AMBIGUOUS is for
    on-topic documents that do not settle it -- the only class that earns a
    model call. ABSENT is for no on-topic document at all.
    """
    if degraded:
        return Evidence.DEGRADED, "fetch degraded", []
    kind = kind or asks(query)
    topical = on_topic(query, docs)
    if not topical:
        return Evidence.ABSENT, "no document is about the asked product", []
    if kind == "other":
        return Evidence.AMBIGUOUS, "attribute not one the gate can read", []
    vals = _values(kind, topical)
    if not vals:
        return Evidence.AMBIGUOUS, f"on-topic documents state no {kind}", []
    if kind == "stance" and len(vals) > 1:
        return Evidence.AMBIGUOUS, "stances conflict", vals
    return Evidence.SUFFICIENT, f"{len(vals)} {kind} value(s) from {len(topical)} on-topic doc(s)", vals


# A gate is any callable (query, docs, degraded) -> (Evidence, reason, payload).
# The attribute gate above is the default; decide.gate() is the verdict rule
# over the same four classes, so the arm and the demo walk one graph.
Gate = Callable[[str, Sequence[dict], bool], Tuple[Evidence, str, dict]]


def attribute_gate(query: str, docs: Sequence[dict], degraded: bool = False) -> Tuple[Evidence, str, dict]:
    ev, reason, vals = classify(query, docs, degraded)
    return ev, reason, {"values": list(vals)}


# ───────────────────────────────────────────────────────── transitions

def _after_classify(s: State) -> str:
    return {
        Evidence.SUFFICIENT: "answer",
        Evidence.AMBIGUOUS: "verify",
        Evidence.ABSENT: "abstain",                       # terminal on a healthy fetch
        Evidence.DEGRADED: "rewrite" if len(s.tried) < MAX_ROUNDS else "abstain",
    }[s.evidence]


EDGES: Dict[str, Callable[[State], str]] = {
    "rewrite": lambda s: "retrieve",
    "retrieve": lambda s: "classify",
    "classify": _after_classify,
    "verify": lambda s: "answer" if s.grounded else "abstain",
}
TERMINAL = ("answer", "abstain")


def verify_prompt(s: State) -> str:
    lines = "\n".join(f"[{d.get('doc_id', i)}] {_doc_text(d)[:300]}" for i, d in enumerate(s.docs))
    return (f"Question: {s.query}\nDocuments:\n{lines}\n\n"
            "Does any document state the answer? Reply with JSON only, no prose: "
            '{"grounded": true|false, "value": "<the stated answer or null>", "doc": "<id or null>"}')


def run(query: str, rewrite: Callable[[str, tuple], str], retrieve: Callable[[str], tuple],
        llm: Optional[Callable[[str, int], str]] = None, max_rounds: int = MAX_ROUNDS,
        gate: Optional[Gate] = None) -> State:
    """Walk the graph once. `retrieve` returns (docs, degraded); `llm(prompt,
    max_tokens)` returns raw text and is called only from `verify`; `gate`
    classifies the pool (default: the attribute gate)."""
    gate = gate or attribute_gate
    s = State(query=query, asks=asks(query))
    node = "rewrite"
    while node not in TERMINAL:
        t0, tok0, h_in = time.time(), tokens.snapshot(), s.digest()
        out: dict = {}
        if node == "rewrite":
            q = rewrite(query, s.tried)
            s = replace(s, tried=s.tried + (q,))
            out = {"rewritten": q}
        elif node == "retrieve":
            docs, degraded = retrieve(s.tried[-1])
            s = replace(s, docs=tuple(docs), degraded=bool(degraded))
            out = {"n_docs": len(docs), "degraded": bool(degraded)}
        elif node == "classify":
            ev, reason, payload = gate(query, s.docs, s.degraded)
            s = replace(s, evidence=ev, values=tuple(payload.get("values", ())), payload=payload)
            out = {"evidence": ev.value, "reason": reason, **payload}
        elif node == "verify":
            raw = llm(verify_prompt(s), VERIFY_MAX_TOKENS) if llm else ""
            obj = _extract_json(raw) or {}
            s = replace(s, grounded=bool(obj.get("grounded")))
            out = {"grounded": s.grounded, "value": obj.get("value"), "doc": obj.get("doc")}
        contract_ok = node != "verify" or bool(_extract_json(raw))
        if node == "classify" and s.evidence is Evidence.DEGRADED and len(s.tried) >= max_rounds:
            nxt = "abstain"
        else:
            nxt = EDGES[node](s)
        step = Step(node=node, edge_taken=nxt, reason=out.get("reason", ""),
                    dur_ms=int((time.time() - t0) * 1000),
                    tokens=tokens.delta(tok0, tokens.snapshot()), contract_ok=contract_ok,
                    state_hash_in=h_in, state_hash_out=s.digest(), out=out)
        s = replace(s, trace=s.trace + (step,))
        tokens.emit({"query": query, **asdict(step)})
        node = nxt
    final = Step(node=node, edge_taken="", reason="terminal", dur_ms=0,
                 tokens=tokens.delta(tokens.snapshot(), tokens.snapshot()), contract_ok=True,
                 state_hash_in=s.digest(), state_hash_out=s.digest())
    return replace(s, trace=s.trace + (final,))


# ─────────────────────────────────────────────────────────── self-check

def _demo() -> None:
    rel = {"doc_id": "r1", "title": "Fedora 44 released", "text": "kernel 6.17.2 ships", "date": "2026-09-01"}
    chat = {"doc_id": "c1", "title": "Fedora grub gone after update", "top_comment": "Yes, same here, the update broke grub."}
    off = {"doc_id": "x1", "title": "Chrome 155 released", "text": "v155.0.8047"}

    assert asks("What is the latest Fedora version?") == "version"
    assert asks("Did the 6.17 kernel break grub on Fedora?") == "stance"
    assert asks("Is CVE-2026-1234 fixed in Fedora?") == "cve"
    assert asks("When is Fedora 45 coming out?") == "date"

    assert classify("latest Fedora version?", [rel])[0] is Evidence.SUFFICIENT
    assert classify("latest Fedora version?", [chat])[0] is Evidence.AMBIGUOUS   # on-topic, no version
    assert classify("latest Fedora version?", [off])[0] is Evidence.ABSENT
    assert classify("latest Fedora version?", [])[0] is Evidence.ABSENT
    assert classify("latest Fedora version?", [rel], degraded=True)[0] is Evidence.DEGRADED
    assert classify("Did 6.17 break grub on Fedora?", [chat])[0] is Evidence.SUFFICIENT
    both = [chat, {"doc_id": "c2", "title": "Fedora grub fine", "top_comment": "No, grub works for me."}]
    assert classify("Did 6.17 break grub on Fedora?", both)[0] is Evidence.AMBIGUOUS
    assert classify("Is CVE-2026-1234 fixed in Fedora?", [dict(rel, text="fixes CVE-2026-1234")])[0] is Evidence.SUFFICIENT

    calls = []
    def rw(q, tried): calls.append("rw"); return f"{q} #{len(tried)}"
    # The invariant: ABSENT on a healthy fetch abstains at once -- one rewrite, no retry.
    s = run("latest Fedora version?", rw, lambda q: ([off], False))
    assert [st.node for st in s.trace] == ["rewrite", "retrieve", "classify", "abstain"], [st.node for st in s.trace]
    assert calls == ["rw"]
    # DEGRADED retries up to the cap, then abstains.
    calls.clear()
    s = run("latest Fedora version?", rw, lambda q: ([], True), max_rounds=2)
    assert calls == ["rw", "rw"] and s.trace[-1].node == "abstain"
    assert [st.edge_taken for st in s.trace if st.node == "classify"] == ["rewrite", "abstain"]
    # SUFFICIENT answers without any model call.
    s = run("latest Fedora version?", rw, lambda q: ([rel], False), llm=lambda p, n: (_ for _ in ()).throw(AssertionError("llm called")))
    assert s.trace[-1].node == "answer" and s.values == ("6.17.2",)
    # AMBIGUOUS is the only path to the model, and its contract is checked.
    seen = {}
    def llm(prompt, max_tokens): seen["n"] = max_tokens; return '{"grounded": true, "value": "44", "doc": "c1"}'
    s = run("latest Fedora version?", rw, lambda q: ([chat], False), llm=llm)
    assert seen["n"] == VERIFY_MAX_TOKENS and s.trace[-1].node == "answer"
    assert all(st.contract_ok for st in s.trace)
    s = run("latest Fedora version?", rw, lambda q: ([chat], False), llm=lambda p, n: "I think so, yes.")
    v = [st for st in s.trace if st.node == "verify"][0]
    assert not v.contract_ok and v.edge_taken == "abstain"
    # A gate of a different kind rides the same edges.
    always = lambda q, d, deg: (Evidence.SUFFICIENT, "custom", {"verdict": "act"})
    s = run("anything?", rw, lambda q: ([], False), gate=always)
    assert s.trace[-1].node == "answer" and s.payload == {"verdict": "act"}
    # Same inputs, same hash chain: the replay proof the trace exists for.
    a = run("latest Fedora version?", rw, lambda q: ([rel], False))
    b = run("latest Fedora version?", rw, lambda q: ([rel], False))
    assert [x.state_hash_out for x in a.trace] == [x.state_hash_out for x in b.trace]
    print("ok — graph")


if __name__ == "__main__":
    _demo()
