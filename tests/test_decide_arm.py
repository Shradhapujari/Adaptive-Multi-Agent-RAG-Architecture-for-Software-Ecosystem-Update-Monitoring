"""The marag_decide arm: grounded retrieval in, a persisted decision out, no model."""

import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import decide
import multiagent_rag_v3 as marag
from eval_harness import generators as G


class _Retriever:
    def __init__(self, docs):
        self.docs = docs
        self.calls = []

    def run(self, query, top_k=4, original_query="", **kw):
        self.calls.append((query, top_k, original_query))
        return self.docs


def _arm(docs):
    a = G.DecideGenerator.__new__(G.DecideGenerator)
    a.marag, a.top_k, a._now, a._catalog, a._decide = marag, 4, None, [], decide
    a.retriever = _Retriever(docs)
    a._ground = lambda q, now=None, catalog=None: SimpleNamespace(
        vendor_names=["Ubuntu"], retrieval_query="ubuntu 24.04", rewritten=q, intent=None)
    return a


def test_generate_persists_decision_and_cites_evidence_first():
    docs = [{"title": "Fedora 42 out", "detail": "", "source": "vendor_releases", "url": "u0", "date": ""},
            {"title": "Ubuntu 24.04 broke wifi", "detail": "", "source": "vendor_reddit", "url": "u1", "date": "2026-05-02"},
            {"title": "ubuntu 24.04 stuck at boot", "detail": "", "source": "vendor_reddit", "url": "u2", "date": "2026-05-03"}]
    a = _arm(docs)
    out = a.generate("Is Ubuntu 24.04 safe to upgrade to?")
    d = out["decision"]
    assert d["verdict"] == "hold" and d["verdict3"] == "hold"
    assert out["answer"].startswith("Hold off")
    assert [x["doc_id"] for x in out["docs"][:2]] == d["evidence_doc_ids"]
    assert len(out["pool"]) == 3 and out["rounds"] == 1
    assert a.retriever.calls[0][1] >= 24, "over-fetches so the rules have a pool"
    assert a.retriever.calls[0] == ("ubuntu 24.04", 24, "Is Ubuntu 24.04 safe to upgrade to?")
    assert d["path"] == ["rewrite", "retrieve", "classify", "answer"]
    assert d["evidence_class"] == "sufficient"


def test_empty_pool_is_the_refusal():
    out = _arm([]).generate("Is Ubuntu 24.04 safe to upgrade to?")
    assert out["answer"] == decide.REFUSAL
    assert out["decision"]["verdict"] == "insufficient_evidence"
    assert out["docs"] == []
    assert out["decision"]["path"] == ["rewrite", "retrieve", "classify", "abstain"]
    assert out["decision"]["evidence_class"] == "absent" and out["rounds"] == 1


def test_spec_builds_the_arm(monkeypatch):
    import vendor
    monkeypatch.setattr(vendor, "load_catalog", lambda *a, **k: [])
    gens = G.build_generators(["marag_decide"])
    assert [g.name for g in gens] == ["marag_decide"] and gens[0].available()


def test_on_product_docs_meeting_no_obligation_abstain_via_ambiguous():
    docs = [{"title": "Ubuntu 24.04 wallpaper thread", "detail": "", "source": "vendor_reddit", "url": "u9", "date": ""}]
    out = _arm(docs).generate("Is Ubuntu 24.04 safe to upgrade to?")
    d = out["decision"]
    assert d["verdict"] == "insufficient_evidence" and d["evidence_class"] == "ambiguous"
    assert d["path"] == ["rewrite", "retrieve", "classify", "verify", "abstain"]
    assert out["answer"] == decide.REFUSAL
