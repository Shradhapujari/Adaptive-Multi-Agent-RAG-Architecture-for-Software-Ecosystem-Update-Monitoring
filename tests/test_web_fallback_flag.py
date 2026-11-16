"""GR-2 is a live web read, so it is off unless MARAG_WEB_FALLBACK=1: a frozen
benchmark must never see it, and the console reads the same flag rather than
hard-coding it on. When it does fire, web documents feed the answer, never the
verdict."""
from __future__ import annotations

import importlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402
import websearch  # noqa: E402
from app_1 import Rewrite  # noqa: E402


@pytest.mark.parametrize("env,want", [(None, False), ("0", False), ("1", True)])
def test_flag_is_off_unless_set(monkeypatch, env, want):
    if env is None:
        monkeypatch.delenv("MARAG_WEB_FALLBACK", raising=False)
    else:
        monkeypatch.setenv("MARAG_WEB_FALLBACK", env)
    try:
        assert importlib.reload(websearch).ENABLE_WEB_FALLBACK is want
    finally:
        monkeypatch.delenv("MARAG_WEB_FALLBACK", raising=False)
        importlib.reload(websearch)


@pytest.mark.parametrize("flag", [False, True])
def test_console_reads_the_flag(monkeypatch, flag):
    seen = {}

    def fake_pipeline(q, **kw):
        seen.update(kw)
        return {"original_query": q, "route": None}

    monkeypatch.setattr(websearch, "ENABLE_WEB_FALLBACK", flag)
    monkeypatch.setattr(app_1.graph, "route_query", lambda q: ("full", "test"))
    monkeypatch.setattr(app_1, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(app_1, "present_answer", lambda *a, **k: None)
    app_1.ask("Is it safe to update Firefox?")
    assert seen["web_fallback"] is flag


@pytest.fixture
def empty_lake(monkeypatch):
    monkeypatch.setattr(app_1, "union_fetch", lambda *a, **k: [])
    monkeypatch.setattr(app_1, "terminal_sources",
                        lambda *a, **k: ({"community": [], "releases": [], "cve": []}, []))
    monkeypatch.setattr(app_1, "rewrite_query", lambda q: Rewrite(q, "rule-based"))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    import nvd
    monkeypatch.setattr(nvd, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(websearch, "trusted", lambda *a, **k: ([], {"backend": True, "n": 0, "used": True, "hosts": []}))
    web = [{"doc_id": "web0", "title": "Zig 0.15.1 released", "source": "web", "kind": "community",
            "text": "[untrusted:community] Zig 0.15.1 fixes CVE-2026-7777 [/untrusted]", "url": "https://x.example"}]
    monkeypatch.setattr(websearch, "fallback", lambda *a, **k: (web, {"backend": True, "n": 1, "used": True}))


def test_gr2_docs_feed_the_answer_not_the_verdict(empty_lake):
    r = app_1.run_pipeline("Is it safe to update Zig?", show_steps=False, web_fallback=True)
    assert r["web_fallback"]["used"] and [d["doc_id"] for d in r["web"]] == ["web0"]
    dec = r["decision"] or {}
    assert dec.get("source") != "web" and dec.get("verdict") != "patch_urgently"


def test_off_means_no_web_read(empty_lake, monkeypatch):
    monkeypatch.setattr(websearch, "fallback", lambda *a, **k: pytest.fail("web read with the flag off"))
    monkeypatch.setattr(websearch, "trusted", lambda *a, **k: pytest.fail("web read with the flag off"))
    r = app_1.run_pipeline("Is it safe to update Zig?", show_steps=False, web_fallback=False)
    assert r["web_fallback"] is None


def test_console_log_says_gr2_is_off(empty_lake):
    r = app_1.run_pipeline("Is it safe to update Zig?", show_steps=False, web_fallback=False)
    r["route"] = {"mode": "full", "why": "test"}
    assert "GR-2 off" in app_1._console_log("Is it safe to update Zig?", r, r["route"])
