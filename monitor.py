"""Component monitor: what releasetrain.io's component search shows, computed
locally from one `/api/v/search?q=<name>` pull.

The site's own history/forecast/risk endpoints (`/api/v/fc`, `/api/c/frequency`,
`/api/dashboard/mltl-risk`) answered "no data" or 502 on every probe made
2026-09-14, so everything below is derived from the rows the search feed does
return: releases and CVE advisories for one product, newest first.

Pure functions over those rows; the caller fetches. No model, no network.
"""

from __future__ import annotations

import re
import statistics
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

SEVERITY_WEIGHT = {"CRITICAL": 25, "HIGH": 15, "MEDIUM": 6, "LOW": 2}


def parse_ymd(s) -> Optional[date]:
    s = str(s or "")[:8]
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def version_key(v: str) -> tuple:
    """`'3.12.4'` → `(3, 12, 4)`; anything non-numeric drops. Good enough for
    ordering shipped versions of one product."""
    return tuple(int(x) for x in re.findall(r"\d+", str(v or ""))) or (0,)


def releases(rows: List[dict]) -> List[dict]:
    return [r for r in rows if not r.get("isCve")]


def advisories(rows: List[dict]) -> List[dict]:
    return [r for r in rows if r.get("isCve")]


def shipped(rows: List[dict], today: date) -> List[dict]:
    """Releases dated on or before today, newest first. The feed carries
    scheduled future rows (Firefox 159 dated 2027-01-19 on 2026-09-14) which
    are not "the latest version" in any sense a user means."""
    out = [r for r in releases(rows)
           if (d := parse_ymd(r.get("versionReleaseDate"))) and d <= today]
    return sorted(out, key=lambda r: parse_ymd(r["versionReleaseDate"]), reverse=True)


def forecast_next(rows: List[dict], today: date, n: int = 8) -> Optional[dict]:
    """Median gap between the last `n` distinct release dates, projected from
    the newest. Returns {"date", "gap_days", "samples"} or None below 3 dates."""
    dates = sorted({parse_ymd(r["versionReleaseDate"]) for r in shipped(rows, today)},
                   reverse=True)[:n]
    if len(dates) < 3:
        return None
    gaps = [(a - b).days for a, b in zip(dates, dates[1:])]
    gap = max(1, int(statistics.median(gaps)))
    return {"date": dates[0] + timedelta(days=gap), "gap_days": gap, "samples": len(dates)}


def by_month(rows: List[dict], months: int = 12, today: Optional[date] = None) -> Dict[str, Dict[str, int]]:
    """{'2026-08': {'releases': 3, 'advisories': 12}, ...} for the trailing window."""
    today = today or date.today()
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        d = parse_ymd(r.get("versionReleaseDate"))
        if d is None or d > today or (today - d).days > 31 * months:
            continue
        m = d.strftime("%Y-%m")
        kind = "advisories" if r.get("isCve") else "releases"
        out.setdefault(m, {"releases": 0, "advisories": 0})[kind] += 1
    return dict(sorted(out.items()))


def risk(rows: List[dict], today: date, installed: str = "") -> dict:
    """0-100 deployment-risk score in the site's four bands.

    ponytail: additive heuristic -- severity-weighted advisories in the last
    90 days, plus version drift if an installed version is given, plus a
    staleness term. Replace with the site's mltl-risk endpoint when it answers.
    """
    recent = [a for a in advisories(rows)
              if (d := parse_ymd(a.get("versionReleaseDate"))) and 0 <= (today - d).days <= 90]
    sev: Dict[str, int] = {}
    for a in recent:
        s = str(a.get("versionSeverity") or "UNKNOWN").upper()
        sev[s] = sev.get(s, 0) + 1
    score = sum(SEVERITY_WEIGHT.get(s, 3) * n for s, n in sev.items())

    ship = shipped(rows, today)
    latest = ship[0] if ship else None
    behind = 0
    cves_since_installed = 0
    if installed and ship:
        ik = version_key(installed)
        behind = sum(1 for r in ship if version_key(r.get("versionNumber")) > ik)
        score += min(behind, 5) * 8
        mine = next((r for r in ship if version_key(r.get("versionNumber")) == ik), None)
        if mine:
            since = parse_ymd(mine["versionReleaseDate"])
            cves_since_installed = sum(
                1 for a in advisories(rows)
                if (d := parse_ymd(a.get("versionReleaseDate"))) and d > since)
    if latest:
        age = (today - parse_ymd(latest["versionReleaseDate"])).days
        score += 10 if age > 365 else 0

    score = min(100, score)
    band = ("Critical" if score >= 75 else "High" if score >= 50
            else "Medium" if score >= 25 else "Low")
    return {"score": score, "band": band, "severity": sev, "recent_advisories": len(recent),
            "behind": behind, "cves_since_installed": cves_since_installed}


def summarize(name: str, rows: List[dict], today: Optional[date] = None,
              installed: str = "") -> dict:
    today = today or date.today()
    ship = shipped(rows, today)
    latest = ship[0] if ship else None
    return {
        "name": name,
        "latest": latest,
        "days_ago": (today - parse_ymd(latest["versionReleaseDate"])).days if latest else None,
        "history": ship[:10],
        "upcoming": [r for r in releases(rows)
                     if (d := parse_ymd(r.get("versionReleaseDate"))) and d > today],
        "forecast": forecast_next(rows, today),
        "advisories": advisories(rows)[:10],
        "by_month": by_month(rows, today=today),
        "risk": risk(rows, today, installed),
        "n_rows": len(rows),
    }
