"""The quoted thread has to name the product itself, not just sit in its
subreddit. "Any critical security vulnerabilities in Linux this month?" led
with the top comment of "SuperTux v0.7.0.1 and v0.7.0.2 released: Security
patch..." from r/linux -- a game, quoted as the community's answer (live
check, 2026-11-22). No network: the feed is stubbed."""
import requests
import pytest
import yesno

SUPERTUX = {"title": "SuperTux v0.7.0.1 and v0.7.0.2 released: Security patch and a few bugfixes!",
            "author_description": "New visuals and music.", "subreddit": "linux",
            "comments": [{"body": "It's awesome this game is still worked on.", "score": 4}]}
KERNEL = {"title": "Linux 6.18 security fix for io_uring, should I update now?",
          "author_description": "", "subreddit": "linux", "comments": []}


def _feed(monkeypatch, rows):
    class _R:
        def raise_for_status(self): pass
        def json(self): return {"data": [dict(r) for r in rows]}
    monkeypatch.setattr(requests, "get", lambda *a, **k: _R())


Q = "Any critical security vulnerabilities in Linux this month?"


def test_a_thread_that_never_names_the_product_is_no_thread(monkeypatch):
    _feed(monkeypatch, [SUPERTUX])
    assert yesno.find_thread(Q, must_mention=["security"], must_name=["linux"]) is None


def test_a_thread_that_names_it_is_kept(monkeypatch):
    _feed(monkeypatch, [KERNEL])
    t = yesno.find_thread(Q, must_mention=["security"], must_name=["linux"])
    assert t is not None and t["title"].startswith("Linux 6.18")


def test_name_is_a_whole_word(monkeypatch):
    # "util-linux" is not Linux (the same rule as vendor.advisory_names_vendor).
    _feed(monkeypatch, [{**SUPERTUX, "title": "util-linux security patch released"}])
    assert yesno.find_thread(Q, must_mention=["security"], must_name=["linux"]) is None


def test_no_product_no_gate(monkeypatch):
    _feed(monkeypatch, [SUPERTUX])
    assert yesno.find_thread(Q, must_mention=["security"]) is not None
