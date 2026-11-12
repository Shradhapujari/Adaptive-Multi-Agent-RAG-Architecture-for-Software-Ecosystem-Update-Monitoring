"""The single-column Decision console: the pipeline diagram marks what a run
actually walked, the security table states KEV and severity only as the feed
does, and the 6-month context keeps only recent shipped releases."""
from __future__ import annotations

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import answer_agent
import app_1


def _classes(src: str) -> dict:
    out = {}
    for line in src.splitlines():
        if line.startswith("class "):
            _, nodes, cls = line.split()
            out.update({n: cls for n in nodes.split(",")})
    return out


def test_diagram_is_plain_before_a_run():
    assert _classes(app_1._pipeline_mermaid()) == {}


def test_fast_run_skips_the_rewriter_and_abstain():
    res = {"route": {"mode": "fast"},
           "decision": {"path": ["rewrite", "retrieve", "classify", "answer"]}}
    c = _classes(app_1._pipeline_mermaid(res))
    assert c["rewrite"] == "skipped" and c["abstain"] == "skipped"
    assert c["classify"] == c["answer"] == c["retrieve"] == "taken"


def test_full_run_with_no_decision_abstains_before_the_gate():
    c = _classes(app_1._pipeline_mermaid({"route": {"mode": "full"}, "decision": None}))
    assert c["rewrite"] == c["abstain"] == "taken"
    assert c["classify"] == c["answer"] == "skipped"


def test_retry_loop_is_labelled_with_its_count():
    res = {"route": {"mode": "full"},
           "decision": {"path": ["rewrite", "retrieve", "classify", "rewrite",
                                 "retrieve", "classify", "answer"]}}
    assert "retried ×1" in app_1._pipeline_mermaid(res)


def test_security_table_reads_kev_and_severity_from_the_row():
    kev = {"title": "[CISA KEV] Chrome flaw", "source": "cisa_kev", "date": "20261020",
           "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-10001", "detail": "CVE-2026-10001"}
    adv = {"title": "chrome adv", "url": "https://nvd.nist.gov/vuln/detail/CVE-2026-20002",
           "is_cve": True, "product": "chrome", "version": "1.0", "date": "20261020",
           "notes": "bug", "versionSeverity": "high"}
    rows = answer_agent.details(answer_agent.collect_evidence(
        {"releases": [adv], "cve": [kev]}))["security"]
    by_cve = {r["CVE"]: r for r in rows}
    assert by_cve["CVE-2026-10001"]["CISA KEV"] == "yes"
    assert by_cve["CVE-2026-10001"]["Severity"] == "—"          # not stated, not inferred
    assert by_cve["CVE-2026-20002"]["CISA KEV"] == ""
    assert by_cve["CVE-2026-20002"]["Severity"] == "HIGH"


def test_maintenance_context_keeps_six_months_by_component():
    rel = lambda p, v, d: {"product": p, "version": v, "date": d, "is_cve": False,  # noqa: E731
                           "title": f"{p} v{v}", "notes": ""}
    res = {"releases": [rel("Node.js", "26.1.0", "20261001"),
                        rel("Node.js", "25.0.0", "20260101"),     # older than 6 months
                        rel("Chrome", "156.0", "20261020")]}
    ctx = app_1._maintenance_context(res, today=date(2026, 11, 12))
    assert ctx == {"Chrome": ["v156.0 (2026-10-20)"], "Node.js": ["v26.1.0 (2026-10-01)"]}


def test_console_uses_gate_and_verdict_tags():
    res = {"releases": [], "cve": [], "community": [], "timing": {"decision": 0.2},
           "decision": {"verdict": "safe", "evidence_class": "sufficient", "path": ["answer"]}}
    log = app_1._console_log("q", res, {"mode": "full", "why": "x"})
    assert "[GATE]" in log and "[VERDICT] safe" in log and "[TIMING]" in log
    assert "[DECIDE]" not in log and "[SUFFICIENCY]" not in log
