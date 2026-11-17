"""
A failed fetch must produce no documents, not a document about the failure.

The deployed demo answered "Any critical Linux updates today?" with:

    1 release(s) found:
    • Error: HTTPSConnectionPool(host='releasetrain.io', port=443):
      Read timed out. (read timeout=10) v ()

The fetchers returned a row whose `product` was the exception text, and
nothing downstream could tell that row from a retrieved document: it was
counted ("Releases 1"), rendered under Release Notes, and cited as evidence.
A timeout reached the reader as a retrieved fact.

These tests pin the replacement: no rows, an outage recorded by name, and a
retry so one transient failure does not cost the pool.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")
import app_1  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _fresh_log():
    app_1._reset_fetch_errors()


def _always_timeout(monkeypatch, exc=None):
    def boom(*a, **k):
        raise exc or TimeoutError("Read timed out. (read timeout=20)")
    monkeypatch.setattr(app_1.requests, "get", boom)
    monkeypatch.setattr(app_1.time, "sleep", lambda *_: None)


@pytest.mark.parametrize("fetch,agent", [
    ("fetch_release_notes", "Release Notes"),
    ("fetch_community_feedback", "Community"),
    ("fetch_cve_data", "CVE"),
])
def test_outage_returns_no_documents(monkeypatch, fetch, agent):
    _always_timeout(monkeypatch)
    assert getattr(app_1, fetch)("linux", limit=5) == []


@pytest.mark.parametrize("fetch,agent", [
    ("fetch_release_notes", "Release Notes"),
    ("fetch_community_feedback", "Community"),
    ("fetch_cve_data", "CVE"),
])
def test_outage_is_recorded_against_its_agent(monkeypatch, fetch, agent):
    _always_timeout(monkeypatch)
    getattr(app_1, fetch)("linux", limit=5)
    logged = app_1._FETCH_ERRORS.get()
    assert [e["agent"] for e in logged] == [agent]
    assert "timed out" in logged[0]["error"].lower()


def test_no_row_ever_carries_the_exception_text(monkeypatch):
    # The specific regression: the error string must not appear in any field
    # of any returned document, because that is how it got cited.
    _always_timeout(monkeypatch)
    for fetch in ("fetch_release_notes", "fetch_community_feedback", "fetch_cve_data"):
        for row in getattr(app_1, fetch)("linux", limit=5):
            assert "timed out" not in " ".join(str(v) for v in row.values()).lower()


def test_a_transient_failure_is_retried(monkeypatch):
    calls = {"n": 0}

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("transient")
        return _Resp({"versions": [{"versionProductName": "linux",
                                    "versionNumber": "7.1.0",
                                    "versionReleaseDate": "20260719",
                                    "isCve": False}]})

    monkeypatch.setattr(app_1.requests, "get", flaky)
    monkeypatch.setattr(app_1.time, "sleep", lambda *_: None)
    out = app_1.fetch_release_notes("linux", limit=5)
    assert calls["n"] == 2
    assert out and out[0]["version"] == "7.1.0"
    assert app_1._FETCH_ERRORS.get() == []


def test_a_non_200_is_an_outage_not_an_empty_success(monkeypatch):
    monkeypatch.setattr(app_1.requests, "get",
                        lambda *a, **k: _Resp({}, status=503))
    monkeypatch.setattr(app_1.time, "sleep", lambda *_: None)
    assert app_1.fetch_release_notes("linux", limit=5) == []
    assert "503" in app_1._FETCH_ERRORS.get()[0]["error"]


def test_the_store_fallback_still_sees_an_outage_as_empty(monkeypatch):
    # caching_fetch falls back to previously stored documents when a fetch
    # comes back empty. That path has to keep working now that an outage is
    # empty rather than a placeholder row.
    from store import caching_fetch

    class _Store:
        def search(self, q, pool=None, limit=5, **kw):
            return [{"title": "cached linux release", "url": "u"}]

        def record_documents(self, *a, **k):
            pass

    _always_timeout(monkeypatch)
    fn = caching_fetch(_Store(), "release", app_1.fetch_release_notes)
    assert fn("linux", limit=5)[0]["title"] == "cached linux release"
