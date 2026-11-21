"""The verdict reads an advisory's whole description. Both release-row
builders keep 200 characters of /api/v/ notes for display, and that cut is
what let CVE-2026-115930 ("The MongoDB Shell (mongosh) relies on Node.js ...")
count for a Node.js question: the clause that names the owner was past it."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("streamlit")

import app_1  # noqa: E402
import multiagent_rag_v3  # noqa: E402

LONG = "The MongoDB Shell (mongosh) relies on Node.js. " + "x" * 300 + " prior to 2.14.0"
RAW = {"versionProductName": "node.js", "versionNumber": "2.2", "versionReleaseDate": "20261026",
       "versionReleaseNotes": LONG, "isCve": True,
       "versionUrl": "https://nvd.nist.gov/vuln/detail/CVE-2026-115930"}


def test_fetcher_keeps_the_display_cut_and_the_whole_text(monkeypatch):
    monkeypatch.setattr(app_1, "_get_json", lambda *a, **k: {"versions": [RAW]})
    row, = app_1.fetch_release_notes("node.js")
    assert len(row["notes"]) == 200 and row["notes_full"] == LONG


def test_ranked_release_row_carries_the_whole_text():
    row = multiagent_rag_v3.release_row(RAW)
    assert len(row["notes"]) == 200 and row["notes_full"] == LONG


def test_decision_pool_reads_the_whole_text():
    row = {"title": "node.js v2.2", "notes": LONG[:200], "notes_full": LONG,
           "url": RAW["versionUrl"], "is_cve": True}
    d, = app_1._decide_pool({"releases": [row]})
    assert "prior to 2.14.0" in d["text"] and d["text"].count("relies on") == 1
