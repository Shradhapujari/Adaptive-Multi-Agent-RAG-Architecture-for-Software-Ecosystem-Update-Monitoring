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
