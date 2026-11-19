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


def test_osv_maps_hits(monkeypatch):
    seen = {}
    def fake(pkg, eco, version):
        seen.update(pkg=pkg, eco=eco, version=version)
        return [{"id": "GHSA-x"}]
    monkeypatch.setattr(H, "_osv_query", fake)
    assert H.osv({"query": "is lodash 4.17.20 safe", "vendor": "lodash", "ecosystem": "npm_node"}) == "hold"
    assert seen == {"pkg": "lodash", "eco": "npm", "version": "4.17.20"}
    monkeypatch.setattr(H, "_osv_query", lambda *a: [])
    assert H.osv({"query": "q", "vendor": "lodash", "ecosystem": "npm_node"}) == "act"
