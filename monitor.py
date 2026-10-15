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


def advisory_is_about(row: dict, product: str) -> bool:
    """False only when the advisory's own text names a *different* product.

    On `isCve` rows the upstream's `versionProductName` is the ecosystem token
    the row was indexed under, not the affected product: a Backstage advisory
    arrives under "kubernetes", a Dokku one under "docker", a "Mocha Telnet
    Lite for iOS" one under "ios". Measured 2026-10-15 over the live feed, of
    the 90-day advisories whose text names a product at all, 21 of 21 under
    `docker` and 13 of 13 under `kubernetes` were about something else.

    Abstains when the text names nothing parseable, which is most rows. That
    direction is deliberate: carrying an advisory whose subject could not be
    read overstates risk, and dropping a real one hides it.
    """
    # Local import: the extractor lives in the benchmark builder, which is a
    # script rather than a library. Importing it here keeps one copy of the
    # patterns instead of a second drifting one.
    # ponytail: move extract_cve_product to a shared home if a third caller
    # appears -- a library reaching into a script is the wrong direction.
    from build_multiecosystem_benchmark import extract_cve_product

    got = extract_cve_product(row.get("versionReleaseNotes") or "")
    if not got:
        return True
    named = got[0].lower()
    asked = str(product or "").lower().strip()
    if not asked:
        return True
    # Word-boundary both ways, so "macos" matches "macOS Sequoia" but "git"
    # does not match "GitLab" and "node" does not match "Nodemailer".
    return (re.search(rf"\b{re.escape(asked)}\b", named) is not None
            or re.search(rf"\b{re.escape(named)}\b", asked) is not None)


def shipped(rows: List[dict], today: date) -> List[dict]:
    """Releases dated on or before today, highest version first (date as
    tiebreak). The feed carries scheduled future rows (Firefox 159 dated
    2027-01-19 on 2026-09-14) which are not "the latest version" in any sense
    a user means -- those are dropped by the date filter below.

    Sorting by date instead of version would also be wrong: the feed can
    backfill an older build's row with a newer date (Firefox 156.0.0 posted
    on 2026-10-13, two weeks after 157.0.0 shipped), which would make a lower
    version look like the latest. version_key is only meaningful within one
    product's own numbering, which is what `rows` already is here.
    """
    out = [r for r in releases(rows)
           if (d := parse_ymd(r.get("versionReleaseDate"))) and d <= today]
    return sorted(out, key=lambda r: (version_key(r.get("versionNumber")),
                                       parse_ymd(r["versionReleaseDate"])), reverse=True)


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


def by_month(rows: List[dict], days: int = 365, today: Optional[date] = None) -> Dict[str, Dict[str, int]]:
    """{'2026-08': {'releases': 3, 'advisories': 12}, ...} for the trailing `days`."""
    today = today or date.today()
    out: Dict[str, Dict[str, int]] = {}
    for r in rows:
        d = parse_ymd(r.get("versionReleaseDate"))
        if d is None or d > today or (today - d).days > days:
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
              installed: str = "", days: int = 365) -> dict:
    today = today or date.today()
    # Drop advisories the feed filed under this product but whose own text is
    # about a different one -- see advisory_is_about. Done once here, where the
    # product name is known, so risk/by_month/advisories all see the same rows.
    rows = [r for r in rows if not r.get("isCve") or advisory_is_about(r, name)]
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
        "by_month": by_month(rows, days=days, today=today),
        "risk": risk(rows, today, installed),
        "n_rows": len(rows),
    }
