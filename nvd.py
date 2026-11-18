"""Live NVD (NIST) CVE feed.

The releasetrain CVE feed is Reddit, and the store's newest advisory was last
seen 2026-10-13, so a security question in November was answered from
September. This reads NVD's CVE API 2.0 directly for the last `days`.

Two behaviours the console exposes as guardrails:

* retry loop -- NVD rate-limits keyless clients (5 requests / 30 s) with 403,
  429 or 503; a single attempt turns that into "no CVEs", which a verdict reads
  as safe. Retried with NVD's recommended 6 s spacing.
* api key -- with NVD_API_KEY set (env, or a root-level key in
  .streamlit/secrets.toml, which Streamlit exports as env) it is sent as the
  `apiKey` header: 50 requests / 30 s instead of 5, and 0.6 s retry spacing.
* fallback sort -- NVD returns matches oldest-first (measured 2026-11-15:
  1952 Chrome CVEs since 1 Aug, first page dated 5 Aug), so the first page is
  the stalest. With the sort on, the tail of the result set is fetched and
  ordered newest-first.
"""
from __future__ import annotations

import os
import time
from datetime import timedelta
from typing import Callable, List, Optional

import requests

import temporal

API = "https://services.nvd.nist.gov/rest/json/cves/2.0"
_RETRY = {403, 429, 500, 502, 503, 504}


def _get(params: dict, get: Callable, attempts: int, pause: float,
         headers: Optional[dict] = None) -> dict:
    last: Exception = RuntimeError("no attempt")
    kw = {"headers": headers} if headers else {}
    for i in range(attempts):
        try:
            r = get(API, params=params, timeout=30, **kw)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"NVD HTTP {r.status_code}")
            if r.status_code not in _RETRY:
                break
        except requests.RequestException as e:
            last = e
        if i + 1 < attempts:
            time.sleep(pause * (i + 1))
    raise last


def _row(v: dict) -> dict:
    c = v.get("cve", {})
    desc = next((d["value"] for d in c.get("descriptions", []) if d.get("lang") == "en"), "")
    metrics = c.get("metrics", {})
    sev = ""
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30"):
        if metrics.get(key):
            sev = metrics[key][0].get("cvssData", {}).get("baseSeverity", "")
            break
    return {
        "title": f"{c.get('id', '')} — {desc[:120]}",
        "subreddit": "NVD/NIST",
        "source": "nvd",
        "url": f"https://nvd.nist.gov/vuln/detail/{c.get('id', '')}",
        "date": (c.get("published") or "")[:10],
        "detail": desc[:300],
        "notes": desc,
        "text": desc,
        "cve_id": c.get("id", ""),
        "severity": sev,
        "is_cve": True,
        "verified": True,
        "tier": 1,
    }


def fetch(keyword: str, limit: int = 5, days: int = 90, retry: bool = True,
          newest_first: bool = True, get: Optional[Callable] = None,
          pause: Optional[float] = None, api_key: Optional[str] = None) -> List[dict]:
    """CVEs published in the last `days` whose text mentions `keyword`.

    Raises on an outage so the caller can record it: an unread feed is not an
    empty one.
    """
    get = get or requests.get
    attempts = 3 if retry else 1
    key = api_key if api_key is not None else os.environ.get("NVD_API_KEY", "").strip()
    headers = {"apiKey": key} if key else None
    if pause is None:
        pause = 0.6 if key else 6.0          # NVD's own spacing advice per tier
    end = temporal.now()
    start = end - timedelta(days=min(days, 120))      # NVD caps a range at 120 days
    params = {"keywordSearch": keyword,
              "pubStartDate": start.strftime("%Y-%m-%dT00:00:00.000"),
              "pubEndDate": end.strftime("%Y-%m-%dT23:59:59.999")}
    if newest_first:
        total = _get({**params, "resultsPerPage": 1}, get, attempts, pause, headers).get("totalResults", 0)
        if not total:
            return []
        page = min(total, max(limit * 10, 50))
        params |= {"resultsPerPage": page, "startIndex": total - page}
    else:
        params |= {"resultsPerPage": limit}
    rows = [_row(v) for v in _get(params, get, attempts, pause, headers).get("vulnerabilities", [])]
    if newest_first:
        rows.sort(key=lambda r: r["date"], reverse=True)
    return rows[:limit]


if __name__ == "__main__":
    class _R:
        def __init__(self, code, body=None):
            self.status_code, self._b = code, body or {}

        def json(self):
            return self._b

    def vuln(i, d):
        return {"cve": {"id": f"CVE-2026-{i}", "published": d,
                        "descriptions": [{"lang": "en", "value": f"Google Chrome flaw {i}"}]}}

    calls = []

    def fake(url, params, timeout):
        calls.append(params)
        if len(calls) == 1:
            return _R(429)                                      # rate-limited once
        if params["resultsPerPage"] == 1:
            return _R(200, {"totalResults": 3})
        return _R(200, {"vulnerabilities": [vuln(1, "2026-09-01T00:00"), vuln(2, "2026-11-10T00:00"),
                                            vuln(3, "2026-10-01T00:00")]})

    out = fetch("chrome", limit=2, get=fake, pause=0)
    assert [r["cve_id"] for r in out] == ["CVE-2026-2", "CVE-2026-3"], out
    assert calls[-1]["startIndex"] == 0
    calls.clear()
    try:
        fetch("chrome", get=fake, retry=False, pause=0)
        raise SystemExit("a single 429 must raise when the retry loop is off")
    except RuntimeError:
        pass
    print("nvd ok")
