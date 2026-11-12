"""Escalation & abstention correctness: routing, round-1 abstention, KEV -> patch.

Offline: pools are built here or read from the frozen regression file; no
model, no network. Every case in tests/regression/frozen_failures.jsonl is
replayed: a `fixed` case must stay fixed, an `open` one is a strict xfail, so
fixing it fails the suite until its status is flipped.
"""

import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import decide as D  # noqa: E402
import eval_escalation as E  # noqa: E402
import graph  # noqa: E402

KEV = {"doc_id": "k1", "source": "cisa_kev", "url": "", "date": "2026-10-01",
       "title": "[CISA KEV] Mozilla Firefox Use-After-Free Vulnerability — Firefox",
       "text": "Mozilla Firefox contains a use-after-free. CVE-2026-1234"}
REL = {"doc_id": "r1", "source": "vendor_releases", "url": "", "date": "2026-09-01",
       "title": "Firefox 150.0 release notes", "text": "Firefox 150.0"}
Q = "Is it safe to update Firefox right now?"


@pytest.mark.parametrize("cve", ["CVE-2026-1234", "CVE​-2026-1234", "ＣＶＥ-2026-1234"],
                         ids=["plain", "zero-width", "fullwidth"])
def test_kev_triggers_patch_urgently_however_the_cve_id_is_spelled(cve):
    pool = [dict(KEV, text=f"Mozilla Firefox contains a use-after-free. {cve}"), REL]
    assert D.decide(pool, Q, ["Firefox"]).verdict == "patch_urgently"


def test_kev_oracle_reads_the_product_field_not_any_substring():
    sql = dict(KEV, title="[CISA KEV] Metabase SQL Injection Vulnerability — Metabase")
    assert E.kev_names_vendor(KEV, "Firefox")
    assert not E.kev_names_vendor(sql, "MySQL / SQL")


@pytest.mark.parametrize("q,want", E.ROUTE_GOLD)
def test_route_matches_hand_label(q, want):
    assert graph.route_query(q)[0] == want


def test_absent_abstains_on_round_one_without_a_retry():
    off = {"doc_id": "o1", "source": "vendor_releases", "title": "Zig 0.15 released",
           "text": "", "date": "", "url": ""}
    row = {"id": 0, "query": Q, "vendor": "Firefox", "evidence": [off]}
    s, dec = E.walk(row)
    assert s.evidence is graph.Evidence.ABSENT and len(s.tried) == 1
    assert [st.node for st in s.trace] == ["rewrite", "retrieve", "classify", "abstain"]
    assert E.failure_modes(row, s, dec) == []


def test_false_green_is_tagged():
    row = {"id": 0, "query": Q, "vendor": "Firefox", "evidence": [KEV, REL]}
    s, dec = E.walk(row)
    hidden = dict(dec.__dict__, verdict="safe")     # what the 2026-10-14 bug produced
    assert "false_green" in E.failure_modes(row, s, D.Decision(**hidden))


def _frozen():
    path = os.path.join(ROOT, "tests", "regression", "frozen_failures.jsonl")
    return [json.loads(l) for l in open(path) if l.strip()] if os.path.exists(path) else []


@pytest.mark.parametrize("case", _frozen(), ids=lambda c: f"{c['mode']}-{c['id']}")
def test_frozen_failure_does_not_recur(case):
    s, dec = E.walk(case)
    recurs = case["mode"] in E.failure_modes(case, s, dec)
    if case["status"] == "open":
        assert recurs, "this open failure no longer fires: set its status to fixed"
        pytest.xfail(case.get("note", ""))
    assert not recurs
