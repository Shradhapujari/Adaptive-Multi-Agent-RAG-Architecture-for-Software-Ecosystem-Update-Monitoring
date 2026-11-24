"""A sidebar question answers on click: `_submit` fills both question boxes and
flags one run; a Reddit pick carries its thread into `ask()`, which then takes
the full path, since the fast path never reads a thread."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_1


@pytest.fixture
def state(monkeypatch):
    s = {}
    monkeypatch.setattr(app_1.st, "session_state", s)
    return s


def test_submit_fills_both_boxes_and_flags_a_run(state):
    app_1._submit("Is it safe?")
    assert state["main_query"] == state["ask_query"] == "Is it safe?"
    assert state["auto_ask"] is True


def test_submit_with_a_thread_remembers_it(state):
    app_1._submit("T", {"title": "T", "redditId": "abc"})
    assert state["reddit_id"] == "abc"
    assert state["reddit_title"] == "T"


def test_example_after_a_thread_forgets_it(state):
    state["reddit_id"] = "abc"
    app_1._submit("Latest Django release notes")
    assert "reddit_id" not in state


@pytest.fixture
def calls(monkeypatch):
    seen = {"fast": [], "full": []}

    def fake_pipeline(q, **kw):
        seen["full"].append(kw)
        return {"original_query": q}

    def fake_fast(q, **kw):
        seen["fast"].append(q)
        return None

    monkeypatch.setattr(app_1, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(app_1, "run_fast", fake_fast)
    monkeypatch.setattr(app_1, "_present_answer", lambda *a, **k: object())
    monkeypatch.setattr(app_1.graph, "route_query", lambda q: ("fast", "version lookup"))
    return seen


def test_picked_thread_goes_full_path_with_its_id(calls):
    results, _ = app_1.ask("Did 44 break grub?", reddit_id="abc")
    assert calls["fast"] == []
    assert calls["full"][0]["reddit_id"] == "abc"
    assert results["route"]["mode"] == "full"


def test_typed_question_has_no_thread(calls):
    app_1.ask("Latest Node.js version?")
    assert all(kw.get("reddit_id") is None for kw in calls["full"])
