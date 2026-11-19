"""Live sources for questions the feeds can't answer -- console only.

The releasetrain.io feeds answer update questions: latest version, what
changed, which CVEs. People also ask whether a service is down, what an outage
was about, whether a version is still supported, which of two tools to pick,
how to fix an error, and whether a package is safe. Each of those gets one
fixed live source here, picked by `kind()`.

Console only. The paper's code (graph, decide, intent, grounding,
multiagent_rag_v3, eval_harness) must never import this: a live read in a
frozen replay is non-reproducible. tests/test_live_sources.py enforces it.

Web text never makes a green light. Only package advisories that have a fixed
release and a CVE id may reach the verdict (`package_safety`); everything else
feeds the answer paragraph, screened and wrapped like any web document.

ponytail: the type cues are hand rules. A wording they miss falls through to
the console's existing behaviour, which is the old answer, not a wrong one.
"""
from __future__ import annotations

import re
from typing import Optional, Sequence, Tuple

import graph

KINDS = ("package_safety", "down_now", "incident", "eol", "compare", "compat", "howto")
KIND_LABEL = {"package_safety": "Package safety", "down_now": "Is it down",
              "incident": "Incident", "eol": "End of life", "compare": "Comparison",
              "compat": "Compatibility", "howto": "How-to"}

# Statuspage hosts verified 2026-11-19 (/api/v2/summary.json answered).
STATUS_HOSTS = {
    "github": "www.githubstatus.com", "npm": "status.npmjs.org",
    "cloudflare": "www.cloudflarestatus.com", "openai": "status.openai.com",
    "reddit": "www.redditstatus.com", "vercel": "www.vercel-status.com",
    "docker": "www.dockerstatus.com", "discord": "discordstatus.com",
    "atlassian": "status.atlassian.com",
}

_I = re.I
_PKG_CUE = re.compile(r"\b(?:package|library|module|npm|pip|pypi)\b", _I)
_SAFETY = re.compile(r"\b(?:safe|unsafe|vulnerab\w*|secure|malicious|compromised|backdoor\w*|cves?)\b", _I)
_DOWN = re.compile(r"\b(?:is|are)\b.*\bdown\b|\bdown (?:right )?now\b|\bnot (?:working|loading)\b", _I)
_INCIDENT = re.compile(r"\b(?:outages?|incidents?|went down|was down|disruptions?|downtime)\b", _I)
_EOL = re.compile(r"\bend[- ]of[- ]life\b|\beol\b|\bstill supported\b|\bend of support\b"
                  r"|\bsupport(?:ed)? (?:until|ends?)\b", _I)
_CHOOSE = re.compile(r"\bshould i (?:use|pick|choose|go with|learn)\b.*\bor\b"
                     r"|\bwhich (?:should|is better)\b", _I)
_COMPAT = re.compile(r"\bcompatib\w*|\bworks? with\b|\bdoes \S+(?: \S+)? support\b", _I)
_HOWTO = re.compile(r"\bhow (?:do|can|to|should)\b|\berror\b|\bfix\b|\bexception\b|\bfailed\b", _I)
_ERRNO = re.compile(r"\bE[A-Z]{3,}\b")          # EACCES, ENOENT: case-sensitive

_VERSION = re.compile(r"\bv?(\d+(?:\.\d+)+)\b")
_NAME = r"([a-z0-9][\w.-]*[a-z0-9]|[a-z0-9])"
_NOT_A_NAME = {"the", "a", "an", "is", "it", "this", "that", "my", "any", "on", "in",
               "of", "for", "to", "use", "using", "safe"}
_INSTALL = re.compile(r"\b(pip|npm)\s+install\s+" + _NAME, _I)
_BEFORE_CUE = re.compile(_NAME + r"\s+(?:package|library|module|npm|pip|pypi)\b", _I)
_IS_VERSIONED = re.compile(r"\bis\s+(?:the\s+)?" + _NAME + r"\s+v?\d+(?:\.\d+)+", _I)


def status_product(query: str) -> Optional[str]:
    """The STATUS_HOSTS key the question names, if any."""
    q = query.lower()
    return next((p for p in STATUS_HOSTS if re.search(rf"\b{re.escape(p)}\b", q)), None)


def _ecosystem(query: str) -> Optional[str]:
    if re.search(r"\b(?:pip|pypi|python (?:package|library|module))\b", query, _I):
        return "PyPI"
    if re.search(r"\b(?:npm|yarn|node (?:package|module))\b", query, _I):
        return "npm"
    return None


def package_ref(query: str) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """(name, ecosystem, version) for a package the question names, or None."""
    name = None
    for rx in (_INSTALL, _BEFORE_CUE, _IS_VERSIONED):
        for m in rx.finditer(query):
            cand = m.group(m.lastindex).lower()
            if cand not in _NOT_A_NAME:
                name = cand
                break
        if name:
            break
    if not name:
        return None
    after = query[query.lower().index(name) + len(name):]
    v = _VERSION.search(after)
    return name, _ecosystem(query), v.group(1) if v else None


def kind(query: str, vendors: Sequence[str] = ()) -> Optional[str]:
    """Which live type the question is, in KINDS precedence order, or None."""
    q = query or ""
    if (not vendors and _PKG_CUE.search(q) and _SAFETY.search(q)
            and package_ref(q) is not None):
        return "package_safety"
    if _DOWN.search(q) and status_product(q):
        return "down_now"
    if _INCIDENT.search(q) or _DOWN.search(q):
        return "incident"
    if _EOL.search(q):
        return "eol"
    if graph._COMPARE_RE.search(q) or _CHOOSE.search(q):
        return "compare"
    if _COMPAT.search(q):
        return "compat"
    if _HOWTO.search(q) or _ERRNO.search(q):
        return "howto"
    return None
