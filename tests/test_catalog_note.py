"""The degraded catalog has to reach the reader, not just stdout.

`catalog_status()` has distinguished "this question names no product" from "the
catalog could not be loaded" since the local-catalog fallback went in, but
nothing read it: the only report was a print on a host nobody is tailing. These
pin the line the app shows, including the one case where "no product matched"
below it means nothing at all.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import multiagent_rag_v3 as marag
import app_1


@pytest.fixture
def catalog(monkeypatch):
    """Set the module's catalog state without touching the real one."""
    def _set(source, vendors, errors):
        monkeypatch.setattr(marag, "_CATALOG_SOURCE", source, raising=False)
        monkeypatch.setattr(marag, "_VENDOR_NAMES", vendors, raising=False)
        monkeypatch.setattr(marag, "_CATALOG_ERRORS", errors, raising=False)
    return _set


def test_a_live_catalog_says_nothing(catalog):
    """No banner on a healthy run: a warning shown every time is not a warning."""
    catalog("live", ["firefox"], [])
    assert app_1._catalog_note() is None


def test_a_cached_catalog_names_the_source_the_count_and_the_cause(catalog):
    catalog("cache", ["x"] * 5613, ["vendor names: HTTPError: 502"])
    note = app_1._catalog_note()
    assert "degraded" in note
    assert "cached copy on disk" in note
    assert "5613" in note          # how much vocabulary survived
    assert "502" in note           # why the live fetch was not used


def test_the_cause_keeps_the_distinguishing_part_and_drops_the_pool_dump(catalog):
    """str(e) from requests carries the connection pool, host, port, url and a
    nested cause -- six lines on screen saying nothing the reader acts on. A
    502 has to stay tellable from a timeout and from a refused connection."""
    catalog("cache", ["x"] * 10, [
        "vendor names: HTTPError: 502 Server Error: Bad Gateway for url: "
        "https://releasetrain.io/api/c/names"])
    cause = app_1._catalog_note().split("Cause: ")[1]
    assert cause == "vendor names: HTTPError: 502 Server Error: Bad Gateway"

    catalog("cache", ["x"] * 10, [
        "vendor names: ConnectionError: HTTPConnectionPool(host='127.0.0.1', "
        "port=9): Max retries exceeded with url: / (Caused by "
        'NewConnectionError("[Errno 61] Connection refused"))'])
    cause = app_1._catalog_note().split("Cause: ")[1]
    assert "ConnectionError" in cause
    assert "HTTPConnectionPool" not in cause
    assert "Caused by" not in cause
    assert len(cause) < 90, cause


def test_no_catalog_at_all_is_not_worded_as_a_partial_one(catalog):
    """The severe case: nothing loaded, so "no product matched" is meaningless
    rather than a finding, and every question is unscoped until a retry wins."""
    catalog("unloaded", [], ["vendor names: Timeout", "local catalog: OSError: none"])
    note = app_1._catalog_note()
    assert "No product catalog loaded" in note
    assert "means nothing" in note
    assert str(int(marag.CATALOG_RETRY_SECONDS)) in note
    assert "degraded" not in note   # a different, worse state than cache/bundled
