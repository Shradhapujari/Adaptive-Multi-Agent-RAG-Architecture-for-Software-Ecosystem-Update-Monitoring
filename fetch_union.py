"""
Two-phrasing union fetch with window-aware ordering.
====================================================
Shared by the demo app; kept out of the Streamlit script so it is importable
and testable without a Streamlit runtime.
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from typing import Callable, Dict, List, Optional

from guardrail import screen
from temporal import TemporalResolution, matches_window

__all__ = ["union_fetch", "doc_key", "product_terms", "reset_screened"]

# What the fetches of one pipeline run refused to hand on, as
# {"doc": …, "pattern": …} entries. Same shape as the app's outage log, and
# for the same reason: the drop happens three call levels below the code that
# has to report it, and neither the docs nor the callers in between want a
# second return value threaded through them.
#
# A ContextVar and not a module list: the log belongs to one run, so it is
# reset once per run by the caller rather than per fetch. `union_fetch` is
# called once per agent -- community, releases, CVE -- and a per-fetch clear
# meant each agent erased the one before it, leaving only the last agent's
# drops for a question that any of the three could have been attacked through.
_SCREENED: ContextVar[Optional[List[Dict]]] = ContextVar(
    "marag_screened", default=None)


def reset_screened() -> List[Dict]:
    """Start a fresh drop log for one pipeline run, and return it."""
    log: List[Dict] = []
    _SCREENED.set(log)
    return log

# The release endpoint (`/api/v/`) matches `q` against product names, not
# free text: "Linux" returns 606 versions, "critical Linux updates" returns 0.
# So a sentence-shaped phrasing -- the user's, the rewriter's, or the grounded
# one -- retrieves nothing from it, and a product term has to be fetched
# alongside them. Measured directly against the live endpoint, 2026-08-31.
_KNOWN_PRODUCTS = (
    "linux", "kernel", "chrome", "chromium", "firefox", "safari", "edge",
    "windows", "macos", "ios", "android", "ubuntu", "debian", "fedora",
    "python", "django", "flask", "node", "nodejs", "deno", "bun", "react",
    "angular", "vue", "next.js", "rust", "golang", "java", "kotlin", "swift",
    "php", "laravel", "ruby", "rails", "postgres", "postgresql", "mysql",
    "mariadb", "mongodb", "redis", "sqlite", "docker", "kubernetes", "helm",
    "terraform", "ansible", "nginx", "apache", "openssl", "openssh", "curl",
    "git", "gitlab", "github", "jenkins", "elasticsearch", "kafka", "spark",
    "tensorflow", "pytorch", "numpy", "pandas", "vscode", "intellij", "slack",
    "zoom", "office", "outlook", "teams", "wordpress", "drupal", "jira",
)

_STOPWORDS = frozenset((
    "any", "the", "a", "an", "what", "which", "were", "was", "are", "is",
    "in", "on", "of", "for", "to", "and", "or", "with", "about", "critical",
    "security", "update", "updates", "release", "releases", "notes", "bug",
    "bugs", "fix", "fixes", "fixed", "patch", "patches", "vulnerability",
    "vulnerabilities", "cve", "latest", "newest", "new", "recent", "version",
    "versions", "software", "published", "shipped", "reaction", "community",
))


def doc_key(d: dict) -> str:
    """Dedupe key for a fetched item: its URL, else product+version, else title.

    The fallbacks are case-folded because `/api/v/` echoes the query's own
    capitalisation into `product`: asking "What bugs were fixed in Chrome
    recently?" fetches on both "chrome" and "Chrome", and Chrome 152.0.7977
    came back as `chrome|152.0.7977` from one and `Chrome|152.0.7977` from the
    other. Two of the five release slots then held one release, and it was
    cited to the reader as two sources.

    The URL branch is left alone: a URL path is case-sensitive, and two that
    differ only in case are not reliably the same document.
    """
    url = (d.get("url") or "").strip()
    if url:
        return url
    pv = f"{d.get('product','')}|{d.get('version','')}".strip("|")
    return (pv or d.get("title", "")).strip().lower()


def product_terms(query: str, limit: int = 2) -> List[str]:
    """Product/vendor words in a query, as single-term phrasings to fetch on.

    Deliberately small and local rather than a call to
    `multiagent_rag_v3.extract_vendor`: that one downloads and caches the full
    vendor list at first use, which the demo host should not have to do to
    answer one question. Known names win; otherwise a capitalised non-initial
    word is taken as a product name.
    """
    words = re.findall(r"[A-Za-z][A-Za-z0-9.+#_-]*", query)
    found: List[str] = []

    def add(term: str):
        if term and term.lower() not in [f.lower() for f in found]:
            found.append(term)

    for w in words:
        if w.lower() in _KNOWN_PRODUCTS:
            add(w)
    for i, w in enumerate(words):
        if i > 0 and w[:1].isupper() and w.lower() not in _STOPWORDS:
            add(w)
    return found[:limit]


def union_fetch(fetch_fn: Callable, phrasings: List[str], limit: int,
                temporal: Optional[TemporalResolution] = None,
                fetch_limit: Optional[int] = None) -> List[dict]:
    """Run one agent's fetch over every phrasing and union the results.

    Grounding a date into the query helps a scorer that can read dates and
    hurts a keyword endpoint that cannot (releasetrain matches `q` against
    note text, where "Aug 31, 2026" does not appear). Fetching both phrasings
    and unioning is the same two-phrasing fetch the retriever uses: recall
    comes from the plain phrasing, date-awareness from the grounded one.

    When a window was asked about, items inside it are ordered first — the
    date decides rank, not membership, so a thin day never returns an empty
    answer.
    """
    # With a window to rank by, ask each phrasing for more than will be shown:
    # ranking the first `limit` items by date cannot surface a match that was
    # never fetched, and the endpoint returns newest-irrelevant-first.
    if fetch_limit is None:
        fetch_limit = max(limit, 25) if (temporal is not None and temporal.window) else limit
    seen, out = set(), []
    for phrase in phrasings:
        if not phrase:
            continue
        for item in fetch_fn(phrase, limit=fetch_limit):
            k = doc_key(item)
            if k in seen:
                continue
            seen.add(k)
            # Screened here rather than at the presenter: a fetched row that
            # carries an instruction reaches the ranker, the evidence list and
            # the prompt through this one loop, so this is the only place a
            # drop covers all three. Dropping before the `limit` cut also means
            # an attack costs a real document its slot, not the user an answer.
            attack = screen(item)
            if attack:
                log = _SCREENED.get()
                if log is not None:
                    log.append({"doc": item, "pattern": attack})
                continue
            out.append(item)
    if temporal is not None and temporal.window:
        # False (outside) and None (undated / unparseable) both sort after the
        # in-window items, but an undated item is not evidence of a miss.
        out.sort(key=lambda d: 0 if matches_window(d.get("date", ""), temporal) else 1)
    return out[:limit]
