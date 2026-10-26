"""GR-1 fast path: a single-product version lookup is answered from one
release-feed fetch, with no rewrite, no other feed and no model call; anything
it cannot answer escalates to the full pipeline."""
from __future__ import annotations

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import app_1  # noqa: E402
import grounding  # noqa: E402

NAMES = json.load(open(os.path.join(ROOT, "data", "vendor_names.json")))
Q = "What is the latest version of Node.js?"


def _row(version, date, cve=False, notes="release"):
    return {"title": f"node.js v{version} — {notes}", "product": "node.js",
            "version": version, "date": date, "notes": notes, "url": f"u/{version}",
            "is_cve": cve}


def _never(*a, **k):
    raise AssertionError("the fast path must not call this")


@pytest.fixture
def fast(monkeypatch):
    calls = []
    monkeypatch.setattr(app_1, "ground", lambda q: grounding.ground(q, catalog=NAMES))
    monkeypatch.setattr(app_1, "get_store", lambda: None)
    monkeypatch.setattr(app_1, "_llama_rewrite", _never)
    monkeypatch.setattr(app_1, "rewrite_query", _never)
    monkeypatch.setattr(app_1, "fetch_community_feedback", _never)
    monkeypatch.setattr(app_1, "fetch_cve_data", _never)
    monkeypatch.setattr(app_1, "terminal_sources", _never)
    monkeypatch.setattr(app_1.answer_agent, "_selected_spec", _never)
    rows = [_row("24.9.0", "20260930"), _row("24.8.0", "20260820")]

    def fetch(q, limit=5):
        calls.append(q)
        return list(rows)
    monkeypatch.setattr(app_1, "fetch_release_notes", fetch)
    return calls, rows


def test_a_version_lookup_takes_one_release_fetch_and_no_model(fast, monkeypatch):
    calls, _ = fast
    monkeypatch.setattr(app_1, "run_pipeline", _never)
    results, presented = app_1.ask(Q, source="lake")
    assert calls == ["node.js"]
    assert results["route"]["mode"] == "fast"
    assert results["releases"][0]["version"] == "24.9.0"
    assert results["decision"]["path"] == ["rewrite", "retrieve", "classify", "answer"]
    assert presented.mode == "rule-based" and "fast path" in presented.note


def test_an_advisory_in_the_same_response_still_reaches_the_verdict(fast, monkeypatch):
    _, rows = fast
    rows.append(_row("24.8.0", "20261001", cve=True,
                     notes="Node.js before 24.9.0 allows request smuggling. CVE-2026-4245"))
    monkeypatch.setattr(app_1, "run_pipeline", _never)
    results, _ = app_1.ask(Q, source="lake")
    assert results["decision"]["verdict"] == "patch_urgently"
    assert all(not r["is_cve"] for r in results["releases"])


def test_no_shipped_release_escalates_to_the_full_pipeline(fast, monkeypatch):
    _, rows = fast
    rows.clear()
    monkeypatch.setattr(app_1, "run_pipeline", lambda q, **kw: {"original_query": q})
    monkeypatch.setattr(app_1, "present_answer", lambda q, r, **kw: "full")
    results, presented = app_1.ask(Q, source="lake")
    assert results["route"]["mode"] == "full" and "escalated" in results["route"]["why"]
    assert presented == "full"


def test_a_comparison_never_tries_the_fast_path(fast, monkeypatch):
    calls, _ = fast
    monkeypatch.setattr(app_1, "run_pipeline", lambda q, **kw: {"original_query": q})
    monkeypatch.setattr(app_1, "present_answer", lambda q, r, **kw: "full")
    results, _ = app_1.ask("Is Node.js or Deno more stable?", source="lake")
    assert calls == [] and results["route"]["mode"] == "full"
