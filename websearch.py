"""Bounded web-search fallback (GR-2): one DuckDuckGo hop when the local lake
is ABSENT, and never otherwise.

Why this lives outside `graph.py`. The graph is network-free by construction so
the eval harness can replay it byte-for-byte; this module does live HTTP, so it
is an *orchestration-layer* escalation the caller runs only after `graph.run`
has already returned ABSENT on a healthy fetch. The escalation is bounded: at
most one search, at most `limit` results, and if the web is also empty of a
verifiable version / date / CVE the caller still abstains. The thesis is
unchanged -- "answer when the evidence exists, abstain when it does not" -- the
lake is just no longer the only place evidence can exist.

The eval harness must NOT import this: its fetches go through the recorded
corpus, and a live web read in a replay is non-reproducible. It is referenced
only from `app_1.py`'s ABSENT path.

Untrusted by default. A forum page is community text from the open web, so every
snippet is NFKC/zero-width-screened (`guardrail.screen`) and wrapped
`[untrusted:community] ... [/untrusted]` exactly like a Reddit body, and the
egress guardrail still validates any CVE id the answer cites against these very
documents. DuckDuckGo is optional: with no backend installed `available()` is
False and `fallback()` returns no documents, so the ABSENT path degrades to the
old honest abstention rather than erroring.

    pip install ddgs      # enables the live path
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

import guardrail

MAX_RESULTS = 5
UNTRUSTED = "[untrusted:community] {body} [/untrusted]"
_VER = re.compile(r"\bv?\d+(?:\.\d+){1,3}\b")
_CVE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.I)


def available() -> bool:
    """True when a DuckDuckGo backend is importable."""
    try:
        import ddgs  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        try:
            import duckduckgo_search  # noqa: F401
            return True
        except Exception:  # noqa: BLE001
            return False


def _raw_search(query: str, limit: int) -> List[dict]:
    """Raw hits from DuckDuckGo: [{title, body, href}]. Isolated so the
    self-check can substitute it and run offline; returns [] if no backend."""
    try:
        from ddgs import DDGS  # type: ignore
    except Exception:  # noqa: BLE001
        try:
            from duckduckgo_search import DDGS  # type: ignore
        except Exception:  # noqa: BLE001
            return []
    try:
        with DDGS() as ddg:
            return list(ddg.text(query, max_results=limit))
    except Exception:  # noqa: BLE001 -- a dead search is a web miss, not a crash
        return []


def _to_doc(i: int, hit: dict) -> Optional[dict]:
    """One raw hit → a pool document, screened and tagged, or None if it
    survives nothing after screening."""
    title = str(hit.get("title") or "").strip()
    body = str(hit.get("body") or hit.get("snippet") or "").strip()
    url = str(hit.get("href") or hit.get("url") or "").strip()
    raw = f"{title}. {body}"
    if guardrail.screen({"title": title, "text": body}) is not None:  # tripped the injection screen
        return None
    scrubbed, _ = guardrail.scrub(raw)   # NFKC + zero-width, same as a Reddit body
    return {
        "doc_id": f"web{i}",
        "title": title,
        "text": UNTRUSTED.format(body=scrubbed),
        "url": url,
        "source": "web",
        "kind": "community",            # treated as community tier for citable_kinds
        "tier": "Web search",
        "versions": _VER.findall(raw),
        "cves": [c.upper() for c in _CVE.findall(raw)],
    }


def fallback(query: str, limit: int = MAX_RESULTS) -> Tuple[List[dict], dict]:
    """The bounded escalation. Returns (docs, meta).

    `meta`: {"backend": bool, "n": int, "used": bool}. `used` is True whenever
    the search was attempted (so the console can say "GR-2 fired, 0 results"
    distinctly from "GR-2 not available").
    """
    if not available():
        return [], {"backend": False, "n": 0, "used": False}
    docs = [d for d in (_to_doc(i, h) for i, h in enumerate(_raw_search(query, limit))) if d]
    return docs, {"backend": True, "n": len(docs), "used": True}


# ─────────────────────────────────────────────── trusted vendor pages
#
# The feeds say *that* an advisory exists; the vendor's own release post says
# what the release fixed, in the vendor's words. Those posts are on the open
# web, so they are searched the same keyless way (DuckDuckGo) and kept only
# when the host is the vendor's own or an advisory authority. Anything else a
# search returns is dropped, not ranked lower.
#
# ponytail: a hand list keyed by grounding's vendor names; extend it as
# products show up, or read it from data/vendor_kb.json if it grows past a page.
VENDOR_DOMAINS = {
    "chrome": ("chromereleases.googleblog.com", "chromium.org"),
    "firefox": ("mozilla.org",),
    "edge": ("learn.microsoft.com", "msrc.microsoft.com"),
    "windows": ("support.microsoft.com", "msrc.microsoft.com", "learn.microsoft.com"),
    "macos": ("support.apple.com",), "ios": ("support.apple.com",),
    "safari": ("support.apple.com",),
    "python": ("python.org",), "django": ("djangoproject.com",),
    "node.js": ("nodejs.org",), "nodejs": ("nodejs.org",),
    "linux": ("kernel.org",), "ubuntu": ("ubuntu.com",),
    "fedora": ("fedoraproject.org", "fedoramagazine.org"),
    "debian": ("debian.org",), "openssl": ("openssl.org",),
    "postgresql": ("postgresql.org",), "kubernetes": ("kubernetes.io",),
    "docker": ("docs.docker.com",), "android": ("source.android.com",),
}
ADVISORY_DOMAINS = ("nvd.nist.gov", "cisa.gov", "cve.org", "osv.dev")
_HOST = re.compile(r"^https?://([^/]+)", re.I)
# DuckDuckGo leads a snippet with the page date: "Oct 1, 2026 · The Stable ..."
# or, for a fresh page, "2 days ago · Here are expedited security releases".
_LEAD_DATE = re.compile(r"^\s*([A-Z][a-z]{2,8}\.? \d{1,2}, \d{4})\s*[·\-–]\s*")
_LEAD_AGO = re.compile(r"^\s*(\d+) (minute|hour|day|week)s? ago\s*[·\-–]\s*")


def _host(url: str) -> str:
    m = _HOST.match(url or "")
    return m.group(1).lower().removeprefix("www.") if m else ""


def _on(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _lead_date(body: str, today=None) -> Tuple[str, str]:
    """("2026-10-01", body without the date) or ("", body)."""
    from datetime import date as _date, datetime, timedelta
    ago = _LEAD_AGO.match(body or "")
    if ago:
        n, unit = int(ago.group(1)), ago.group(2)
        days = {"minute": 0, "hour": 0, "day": n, "week": 7 * n}[unit]
        return ((today or _date.today()) - timedelta(days=days)).isoformat(), body[ago.end():]
    m = _LEAD_DATE.match(body or "")
    if not m:
        return "", body or ""
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b. %d, %Y"):
        try:
            return datetime.strptime(m.group(1), fmt).date().isoformat(), body[m.end():]
        except ValueError:
            pass
    return "", body


def trusted(query: str, vendors, limit: int = MAX_RESULTS) -> Tuple[List[dict], dict]:
    """Vendor and advisory pages that answer `query`, newest first.

    At most two searches: one scoped to the first vendor's own site, one open
    search filtered to every trusted host. Returns (docs, meta) like
    `fallback`; meta also names the hosts searched.

    The site search is "<vendor> security fixes <Month YYYY>", not the
    question: "what bugs were fixed recently" matches the boilerplate every
    Chrome post carries ("Many of our security bugs are detected using...")
    and returned posts from 2025; the month put October's bug list first.
    ponytail: current month only; add last month if early-month runs come back thin.
    """
    from datetime import date as _date
    named = [str(v).lower() for v in (vendors or ()) if str(v).lower() in VENDOR_DOMAINS]
    own = [d for v in named for d in VENDOR_DOMAINS[v]]
    allowed = tuple(dict.fromkeys(own)) + ADVISORY_DOMAINS
    if not available():
        return [], {"backend": False, "n": 0, "used": False, "hosts": list(allowed)}
    month = _date.today().strftime("%B %Y")
    searches = ([f"{named[0]} security fixes {month} site:{own[0]}"] if own else []) + [query]
    docs, seen = [], set()
    for q in searches:
        for hit in _raw_search(q, limit * 2):
            url = str(hit.get("href") or hit.get("url") or "").strip()
            host = _host(url)
            if not _on(host, allowed) or url in seen:
                continue
            seen.add(url)
            date, body = _lead_date(str(hit.get("body") or hit.get("snippet") or ""))
            doc = _to_doc(len(docs), {"title": hit.get("title"), "body": body, "href": url})
            if doc:
                doc.update(source="web_trusted", tier="Vendor / official web",
                           host=host, date=date, body=guardrail.scrub(body)[0])
                docs.append(doc)
    docs.sort(key=lambda d: d["date"], reverse=True)
    docs = docs[:limit]
    return docs, {"backend": True, "n": len(docs), "used": True, "hosts": list(allowed)}


# ─────────────────────────────────────────────────────────── self-check

def _demo() -> None:
    import websearch as W
    # Offline: substitute the raw searcher so the module is exercised with no
    # network and no DDG backend installed.
    W._raw_search = lambda q, limit: [  # type: ignore
        {"title": "Node.js 24.9.0 released", "body": "v24.9.0 ships 2026-10-01, fixes CVE-2026-5555.",
         "href": "https://nodejs.org/en/blog"},
        {"title": "", "body": "​zeroｗidth junk", "href": ""},   # screened/scrubbed
    ]
    W.available = lambda: True  # type: ignore
    docs, meta = W.fallback("latest node version", limit=5)
    assert meta["used"] and meta["backend"] and meta["n"] == 2, meta
    assert docs[0]["source"] == "web" and docs[0]["kind"] == "community"
    assert docs[0]["text"].startswith("[untrusted:community]") and docs[0]["text"].endswith("[/untrusted]")
    assert "24.9.0" in docs[0]["versions"] and "CVE-2026-5555" in docs[0]["cves"]
    # The gate reads the wrapped text and still finds the version.
    import graph
    ev, _, vals = graph.classify("latest Node.js version?", docs, kind="version")
    assert ev is graph.Evidence.SUFFICIENT and "24.9.0" in vals, (ev, vals)
    # Trusted: only the vendor's own host or an advisory authority survives,
    # the page date is read off the snippet, and newest comes first.
    W._raw_search = lambda q, limit: [  # type: ignore
        {"title": "Stable Channel Update for Desktop", "href":
         "https://chromereleases.googleblog.com/2026/10/stable.html",
         "body": "Oct 1, 2026 · The Stable channel has been updated to 154.0.8037.97."},
        {"title": "Chrome bug megathread", "href": "https://www.reddit.com/r/chrome/x",
         "body": "Sep 3, 2026 · anyone else?"},
        {"title": "CVE-2026-1 Detail", "href": "https://nvd.nist.gov/vuln/detail/CVE-2026-1",
         "body": "Sep 9, 2026 · Use after free in Skia."},
    ]
    docs, meta = W.trusted("chrome bugs fixed", ["chrome"])
    assert [d["host"] for d in docs] == ["chromereleases.googleblog.com", "nvd.nist.gov"], docs
    assert docs[0]["date"] == "2026-10-01" and docs[0]["body"].startswith("The Stable")
    assert docs[0]["source"] == "web_trusted" and meta["n"] == 2
    # No backend → no documents, so the ABSENT path abstains as before.
    W.available = lambda: False  # type: ignore
    assert W.fallback("anything") == ([], {"backend": False, "n": 0, "used": False})
    print("ok — websearch")


if __name__ == "__main__":
    _demo()
