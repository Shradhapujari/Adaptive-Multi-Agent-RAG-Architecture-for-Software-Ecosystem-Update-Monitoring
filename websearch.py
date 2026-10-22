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
    # No backend → no documents, so the ABSENT path abstains as before.
    W.available = lambda: False  # type: ignore
    assert W.fallback("anything") == ([], {"backend": False, "n": 0, "used": False})
    print("ok — websearch")


if __name__ == "__main__":
    _demo()
