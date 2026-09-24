"""A catalog outage must not look like a query that names no product.

extract_vendor returns [] for both, and they mean opposite things: one is a
finding about the question, the other is an outage wearing its clothes. Before
this, a failed fetch left the vendor list empty, said so only on stdout, and
set the loaded flag anyway -- so one timeout at startup meant nothing matched
for the life of the process.

Offline: every fetch here is stubbed. These assertions are about what happens
when the endpoint is down, which is not something to find out by waiting for
it to be down.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _fresh_module():
    """A module with its own globals, so one test's catalog is not another's."""
    spec = importlib.util.spec_from_file_location("mrag_catalog",
                                                  ROOT / "multiagent_rag_v3.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Down:
    def __init__(self, exc=None):
        self.exc = exc or RuntimeError("502 Server Error")

    def __call__(self, *a, **k):
        raise self.exc


def test_a_failed_fetch_falls_back_to_the_local_catalog():
    """Not to an empty list. The disk cache and bundled names already exist."""
    m = _fresh_module()
    m.requests.get = _Down()
    m.load_vendor_lists()
    assert len(m._VENDOR_NAMES) > 100, (
        "an unreachable endpoint left the vendor vocabulary empty, which is "
        "how every question ends up searched unscoped")


def test_the_outage_is_reportable_rather_than_silent():
    m = _fresh_module()
    m.requests.get = _Down()
    m.load_vendor_lists()
    st = m.catalog_status()
    assert st["degraded"] is True
    assert st["source"] in ("cache", "bundled")
    assert any("vendor names" in e for e in st["errors"]), st["errors"]


def test_a_vendor_is_still_found_with_the_endpoint_down():
    """The point of the fallback: a scoped search, not a working status line."""
    m = _fresh_module()
    m.requests.get = _Down()
    assert m.extract_vendor("Should I upgrade to Arch v2026.01.01?") == ["arch"]


def test_a_live_load_is_not_reported_as_degraded():
    m = _fresh_module()

    class _Ok:
        status_code = 200

        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    def _get(url, **k):
        if "c/names" in url:
            return _Ok(["Ubuntu", "Arch", "Rust"])
        return _Ok({"data": ["ubuntu", "archlinux"]})

    m.requests.get = _get
    m.load_vendor_lists()
    st = m.catalog_status()
    assert st["degraded"] is False and st["source"] == "live"
    assert st["errors"] == []
    assert st["vendors"] == 3 and st["subreddits"] == 2


def test_a_total_failure_is_not_cached_as_a_successful_load():
    """If even the local catalog cannot be read there is nothing to remember,
    and a later call should try again rather than answer from nothing for the
    life of the process."""
    m = _fresh_module()
    m.requests.get = _Down()

    def _no_local(*a, **k):
        raise OSError("no catalog on this host")

    import vendor
    original = vendor.load_catalog
    vendor.load_catalog = _no_local
    try:
        m.load_vendor_lists()
        assert m._VENDOR_NAMES == []
        assert m._VENDORS_LOADED is False, (
            "an empty load was remembered, so nothing would ever be retried")
        assert m.catalog_status()["source"] == "unloaded"
    finally:
        vendor.load_catalog = original

# ---- the retry that the un-latching makes possible has to be floored --------

def test_a_total_outage_retries_once_a_minute_not_once_a_question(monkeypatch):
    """Not latching the empty case is what stops one timeout poisoning the
    process. The cost is that the empty case retries, and on a host that can
    reach neither the endpoint nor a local catalog that retry is a 15 s timeout
    per question. The floor keeps both properties."""
    import vendor as _vendor_catalog
    monkeypatch.setattr(_vendor_catalog, "load_catalog",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no cache")))

    m = _fresh_module()
    calls = {"n": 0}

    def dead(*a, **k):
        calls["n"] += 1
        raise RuntimeError("502 Server Error")
    m.requests.get = dead

    m.load_vendor_lists()
    first = calls["n"]
    assert first > 0
    assert m._VENDORS_LOADED is False               # nothing to remember
    assert m.catalog_status()["degraded"] is True

    for _ in range(5):
        m.load_vendor_lists()
    assert calls["n"] == first, "a total outage must not refetch on every call"

    # The floor expires rather than latching, so the process recovers itself.
    m._CATALOG_RETRY_AFTER = 0.0
    m.load_vendor_lists()
    assert calls["n"] > first


def test_a_successful_load_sets_no_floor():
    class _Ok:
        @staticmethod
        def raise_for_status():
            pass

        @staticmethod
        def json():
            return ["Firefox", "Windows"]

    m = _fresh_module()
    m.requests.get = lambda *a, **k: _Ok()

    m.load_vendor_lists()

    assert m._VENDORS_LOADED is True
    assert m._CATALOG_RETRY_AFTER == 0.0
