"""monitor.py derives history, forecast and risk from one search pull; these
pin the parts that would silently mislead if they broke (future rows counted
as latest, drift miscounted, forecast from too few points)."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import monitor  # noqa: E402

TODAY = date(2026, 9, 14)


def _rel(v, d, cve=False, sev=None):
    r = {"versionNumber": v, "versionReleaseDate": d, "isCve": cve}
    if sev:
        r["versionSeverity"] = sev
    return r


ROWS = [
    _rel("159.0.0", "20270119"),                     # scheduled, future
    _rel("156.0.0", "20260914"),
    _rel("155.1.0", "20260908", cve=True, sev="HIGH"),
    _rel("155.0.1", "20260901"),
    _rel("155.0.0", "20260825"),
    _rel("154.0.0", "20260818"),
    _rel("1.2.3", "20260501", cve=True, sev="CRITICAL"),  # older than 90d
]


def test_future_rows_are_upcoming_not_latest():
    s = monitor.summarize("firefox", ROWS, TODAY)
    assert s["latest"]["versionNumber"] == "156.0.0"
    assert s["days_ago"] == 0
    assert [r["versionNumber"] for r in s["upcoming"]] == ["159.0.0"]


def test_forecast_uses_median_gap():
    f = monitor.forecast_next(ROWS, TODAY)
    assert f["gap_days"] == 7 and f["date"] == date(2026, 9, 21)
    assert monitor.forecast_next(ROWS[:3], TODAY) is None


def test_risk_counts_drift_and_recent_severity_only():
    r = monitor.risk(ROWS, TODAY, installed="155.0.0")
    assert r["behind"] == 2 and r["cves_since_installed"] == 1
    assert r["severity"] == {"HIGH": 1}          # the CRITICAL one is >90d old
    assert r["score"] == 15 + 2 * 8 and r["band"] == "Medium"
    assert monitor.risk([], TODAY)["band"] == "Low"


def test_version_key_orders_numerically():
    assert monitor.version_key("3.12.4") > monitor.version_key("3.9.9")
    assert monitor.version_key("") == (0,)


def test_by_month_buckets_kinds():
    m = monitor.by_month(ROWS, today=TODAY)
    assert m["2026-09"] == {"releases": 2, "advisories": 1}
    assert "2027-01" not in m
