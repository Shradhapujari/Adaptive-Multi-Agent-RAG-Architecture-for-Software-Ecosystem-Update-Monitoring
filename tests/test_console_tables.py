"""The detail tables say which rows the answer stands on. "Latest Nodej.s
version?" listed seven advisories (Ghost, ApostropheCMS, a Linux md/raid1 fix)
and Linux releases as if they were the answer, when the verdict cited none of
them (live, 2026-11-12). Rows the verdict or the paragraph uses are shown and
marked; the rest are collapsed; with no product recognised, nothing is
presented as verified."""
from __future__ import annotations

import os
import sys
from datetime import date
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402
import vendor  # noqa: E402
from eval_harness.generators import doc_id  # noqa: E402


def _g(*names):
    return SimpleNamespace(vendors=[vendor.VendorMatch(name=n, matched=n) for n in names],
                           vendor_names=list(names))


def _tables():
    return {"security": [{"CVE": "CVE-1", "Link": "u/adv-used"},
                         {"CVE": "CVE-2", "Link": "u/ghost"}],
            "patches": [{"Release": "node.js v26.9.0", "Link": "u/rel-answer"},
                        {"Release": "linux v7.38.0", "Link": "u/linux"}],
            "pages": []}


def test_used_rows_are_marked_and_the_rest_set_aside():
    used, other = app_1._split_tables(_tables(), verdict={"u/adv-used"},
                                      answer={"u/adv-used", "u/rel-answer"}, product=True)
    assert used["security"] == [{"Used by": "verdict · answer", "CVE": "CVE-1", "Link": "u/adv-used"}]
    assert used["patches"] == [{"Used by": "answer", "Release": "node.js v26.9.0", "Link": "u/rel-answer"}]
    assert [r["CVE"] for r in other["security"]] == ["CVE-2"]
    assert [r["Release"] for r in other["patches"]] == ["linux v7.38.0"]
    assert "Used by" not in other["security"][0]


def test_no_product_means_nothing_is_presented_as_used():
    used, other = app_1._split_tables(_tables(), verdict={"u/adv-used"},
                                      answer={"u/rel-answer"}, product=False)
    assert not any(used.values())
    assert sum(len(v) for v in other.values()) == 4


def test_an_empty_key_never_marks_a_row():
    t = {"security": [{"CVE": "—", "Link": ""}], "patches": [], "pages": []}
    used, other = app_1._split_tables(t, verdict={"", "—"}, answer={""}, product=True)
    assert not used["security"] and other["security"]


def test_verdict_keys_come_from_the_rows_the_decision_cites():
    adv = {"title": "CVE-2026-10001", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-10001"}
    rel = {"title": "node.js v26.9.0", "url": "https://nodejs.org/x", "product": "node.js"}
    res = {"releases": [rel], "decision_advisories": [adv],
           "decision": {"evidence_doc_ids": [doc_id(adv)]}}
    keys = app_1._verdict_keys(res)
    assert adv["url"] in keys and "CVE-2026-10001" in keys and rel["url"] not in keys
    assert app_1._verdict_keys({"releases": [rel], "decision": None}) == set()


def test_a_release_with_no_url_is_matched_by_its_name():
    # /api/v/ release rows often carry no url; a "safe" verdict standing on
    # them showed its own evidence under "not used" (live, 2026-11-12).
    rel = {"product": "node.js", "version": "26.13.1", "date": "20261111",
           "notes": "https://github.com/nodejs/node/releases/tag/v26.13.1", "url": ""}
    res = {"releases": [rel], "decision": {"evidence_doc_ids": [doc_id(rel)]}}
    name = vendor.describe_record(rel)
    t = {"security": [], "patches": [{"Release": name, "Link": ""}], "pages": []}
    used, _ = app_1._split_tables(t, verdict=app_1._verdict_keys(res), answer=set(), product=True)
    assert used["patches"] and used["patches"][0]["Used by"] == "verdict"


def test_maintenance_context_is_the_asked_products_only():
    rows = [{"product": "linux", "version": "7.38.0", "date": "20261018"},
            {"product": "node.js", "version": "26.9.0", "date": "20260916"}]
    today = date(2026, 11, 12)
    assert list(app_1._maintenance_context({"releases": rows, "grounding": _g("node.js")}, today)) \
        == ["node.js"]
    assert app_1._maintenance_context({"releases": rows, "grounding": _g()}, today) == {}


def test_sources_list_what_was_used_first():
    a = {"title": "linux v7.38.0", "url": "u/linux", "product": "linux"}
    b = {"title": "node.js v26.9.0", "url": "u/node", "product": "node.js"}
    res = {"releases": [a, b], "decision": {"evidence_doc_ids": [doc_id(b)]}}
    rows = app_1._source_rows(res)
    assert [r["Title"] for r in rows] == ["node.js v26.9.0", "linux v7.38.0"]
