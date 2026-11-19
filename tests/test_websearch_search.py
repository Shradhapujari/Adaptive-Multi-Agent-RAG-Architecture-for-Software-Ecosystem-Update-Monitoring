"""websearch.search: one retry, and a failed search is an error, not 0 results.

DuckDuckGo throttles: the same query came back empty on one try and with five
hits on the next (2026-11-19). Before this, a blocked search and a genuine miss
both read "0 results" on screen.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import websearch  # noqa: E402


def _no_sleep(monkeypatch):
    monkeypatch.setattr(websearch, "_sleep", lambda s: None)


def test_retries_once_after_exception(monkeypatch):
    calls = []

    def boom_then_ok(q, limit, timelimit, news):
        calls.append(q)
        if len(calls) == 1:
            raise RuntimeError("ratelimit")
        return [{"title": "t", "body": "b", "href": "https://x.org"}]

    monkeypatch.setattr(websearch, "_ddg", boom_then_ok)
    _no_sleep(monkeypatch)
    hits, err = websearch.search("q")
    assert len(calls) == 2 and err is None and len(hits) == 1


def test_two_failures_report_error_not_empty(monkeypatch):
    def boom(*a):
        raise RuntimeError("ratelimit")

    monkeypatch.setattr(websearch, "_ddg", boom)
    _no_sleep(monkeypatch)
    assert websearch.search("q") == ([], "search failed: RuntimeError")


def test_empty_twice_is_a_real_miss(monkeypatch):
    calls = []
    monkeypatch.setattr(websearch, "_ddg", lambda *a: calls.append(1) or [])
    _no_sleep(monkeypatch)
    assert websearch.search("q") == ([], None)
    assert len(calls) == 2


def test_news_and_timelimit_are_passed_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(websearch, "_ddg",
                        lambda q, l, t, n: seen.update(t=t, n=n) or [{"title": "x"}])
    websearch.search("q", timelimit="m", news=True)
    assert seen == {"t": "m", "n": True}


def test_no_backend_is_reported(monkeypatch):
    monkeypatch.setattr(websearch, "available", lambda: False)
    assert websearch.search("q") == ([], "no backend")


def test_fallback_meta_carries_the_error(monkeypatch):
    monkeypatch.setattr(websearch, "available", lambda: True)
    monkeypatch.setattr(websearch, "search", lambda q, limit=5, **k: ([], "search failed: RuntimeError"))
    docs, meta = websearch.fallback("q")
    assert docs == [] and meta["error"] == "search failed: RuntimeError"
