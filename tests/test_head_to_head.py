"""Head-to-head scoring: one label per system per question, false green first."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import head_to_head as H  # noqa: E402


def test_parse_takes_verdict_line_only():
    assert H.parse_verdict("don't act yet\nVERDICT: hold") == "hold"
    assert H.parse_verdict("verdict: Insufficient_Evidence") == "insufficient_evidence"
    assert H.parse_verdict("It depends, probably safe") is None
    assert H.parse_verdict("") is None


def test_score_false_green():
    s = H.score(["hold", "hold", "act", "insufficient_evidence"],
                ["act", "hold", "act", None])
    assert s["false_green"] == 0.5 and s["n_hold"] == 2
    assert s["accuracy"] == 0.5 and s["unparsed"] == 1 and s["n"] == 4


def test_score_no_hold_rows():
    assert H.score(["act"], ["act"])["false_green"] is None


def test_load_gold_keeps_agreed_rows(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"id":1,"a1":{"verdict":"hold"},"a2":{"verdict":"hold"}}\n'
                 '{"id":2,"a1":{"verdict":"act"},"a2":{"verdict":"hold"}}\n'
                 '{"id":3,"a1":{"verdict":null},"a2":{"verdict":"act"}}\n')
    rows = H.load_gold(str(p))
    assert [r["id"] for r in rows] == [1] and rows[0]["gold"] == "hold"


def test_ours_returns_collapsed_label():
    row = {"query": "Is it safe to update Firefox?", "vendor": "Firefox", "evidence": []}
    assert H.ours(row) in H.LABELS


def test_llm_system_skips_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(H, "load_dotenv", lambda: None)
    assert H.llm_system("openai:gpt-4o-mini", pooled=False) is None


def test_llm_prompt_pooled_carries_evidence():
    row = {"query": "q?", "context": "", "evidence": [{"doc_id": "d1", "title": "T1", "text": "body"}]}
    assert "T1" in H.prompt_for(row, pooled=True)
    assert "T1" not in H.prompt_for(row, pooled=False)


def test_osv_failure_is_not_green(monkeypatch):
    def boom(*a):
        raise OSError("down")
    monkeypatch.setattr(H, "_osv_query", boom)
    assert H.osv({"query": "q", "vendor": "lodash", "ecosystem": "npm_node"}) is None


def test_osv_unmapped_ecosystem_is_none():
    assert H.osv({"query": "q", "vendor": "Apple iOS", "ecosystem": "apple_ios"}) is None


def test_osv_passes_package_and_version(monkeypatch):
    seen = {}
    def fake(pkg, eco, version):
        seen.update(pkg=pkg, eco=eco, version=version)
        return [{"id": "GHSA-x"}]
    monkeypatch.setattr(H, "OSV_PACKAGES", {("npm_node", "lodash"): "lodash"})
    monkeypatch.setattr(H, "_osv_query", fake)
    assert H.osv({"query": "is lodash 4.17.20 safe", "vendor": "lodash", "ecosystem": "npm_node"}) == "act"
    assert seen == {"pkg": "lodash", "eco": "npm", "version": "4.17.20"}


def test_false_green_ignores_unanswered_holds():
    s = H.score(["hold", "hold"], [None, None])
    assert s["false_green"] is None and s["n_hold"] == 0


# --- final-review fixes -----------------------------------------------------

def test_osv_needs_explicit_package(monkeypatch):
    """C1: an ecosystem label is not a package; no mapping -> no answer, never act."""
    monkeypatch.setattr(H, "_osv_query", lambda *a: [])
    assert H.osv({"query": "q", "vendor": "npm / Node.js", "ecosystem": "npm_node"}) is None


def test_osv_vuln_means_patch(monkeypatch):
    """I6: a known vuln means 'apply the fix' (act), as decide's patch_urgently does."""
    monkeypatch.setattr(H, "OSV_PACKAGES", {("npm_node", "lodash"): "lodash"})
    monkeypatch.setattr(H, "_osv_query", lambda *a: [{"id": "GHSA-x"}])
    assert H.osv({"query": "lodash 4.17.20", "vendor": "lodash", "ecosystem": "npm_node"}) == "act"
    monkeypatch.setattr(H, "_osv_query", lambda *a: [])
    assert H.osv({"query": "q", "vendor": "lodash", "ecosystem": "npm_node"}) == "insufficient_evidence"


def test_ours_uses_grounded_vendors(monkeypatch):
    """C2: the arm grounds vendors from the question, not the sheet's label."""
    seen = {}
    monkeypatch.setattr(H, "_grounded_vendors", lambda q: ["edge"])
    real = H.decide
    def spy(pool, q, vendors=()):
        seen["v"] = list(vendors)
        return real(pool, q, vendors=vendors)
    monkeypatch.setattr(H, "decide", spy)
    H.ours({"query": "q", "vendor": "Apple macOS", "evidence": []})
    assert seen["v"] == ["edge"]


def test_pooled_prompt_has_source_date_and_tiebreak():
    row = {"query": "q?", "evidence": [{"doc_id": "d1", "source": "nvd", "date": "2026-01-02",
                                        "title": "T1", "text": "b"}]}
    p = H.prompt_for(row, pooled=True)
    assert "nvd" in p and "2026-01-02" in p
    assert "If you are torn" in p and "does not address the question" in p


def test_parse_strips_markdown():
    for t in ("**VERDICT: hold**", "VERDICT: **hold**", "_VERDICT: hold_", "## VERDICT: hold", "`VERDICT: hold`"):
        assert H.parse_verdict(t) == "hold", t


def test_llm_error_is_its_own_column(monkeypatch):
    class Boom:
        def available(self): return True
        def generate(self, *a, **k): raise H.LLMError("429")
    monkeypatch.setattr(H, "make_client", lambda spec: Boom())
    monkeypatch.setattr(H, "load_dotenv", lambda: None)
    assert H.llm_system("openai:x", pooled=False)({"query": "q"}) == H.ERROR
    s = H.score(["hold", "act"], [H.ERROR, "act"])
    assert s["errors"] == 1 and s["unparsed"] == 0 and s["false_green"] is None
    assert s["accuracy"] == 0.5 and s["accuracy_answered"] == 1.0
