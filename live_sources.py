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
from functools import lru_cache
from typing import List, Optional, Sequence, Tuple

import graph
import websearch

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

_STATUS_NAME = {"github": "GitHub", "npm": "npm", "cloudflare": "Cloudflare",
                "openai": "OpenAI", "reddit": "Reddit", "vercel": "Vercel",
                "docker": "Docker", "discord": "Discord", "atlassian": "Atlassian"}
EOL_ALIASES = {"node": "nodejs", "node.js": "nodejs", "postgres": "postgresql",
               "k8s": "kubernetes"}

_I = re.I
_PKG_CUE = re.compile(r"\b(?:package|library|module|npm|pip|pypi)\b", _I)
_SAFETY = re.compile(r"\b(?:safe|unsafe|vulnerab\w*|secure|malicious|compromised|backdoor\w*|cves?)\b", _I)
_DOWN = re.compile(r"\b(?:is|are)\b.*\bdown\b|\bdown (?:right )?now\b|\bnot (?:working|loading)\b", _I)
_INCIDENT = re.compile(r"\b(?:outages?|incidents?|went down|was down|disruptions?|downtime)\b", _I)
_EOL = re.compile(r"\bend[- ]of[- ]life\b|\beol\b|\bstill supported\b|\bend of support\b"
                  r"|\bsupport(?:ed)? (?:until|ends?)\b", _I)
_CHOOSE = re.compile(r"\bshould i (?:use|pick|choose|go with|learn)\b.*\bor\b"
                     r"|\bwhich (?:should|is better)\b", _I)
# "Postgres or MySQL for a new project?": two capitalised names either side of "or".
_A_OR_B = re.compile(r"\b[A-Z][\w.+#-]* or [A-Z][\w.+#-]*")
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
    if graph._COMPARE_RE.search(q) or _CHOOSE.search(q) or _A_OR_B.search(q):
        return "compare"
    if _COMPAT.search(q):
        return "compat"
    if _HOWTO.search(q) or _ERRNO.search(q):
        return "howto"
    return None


# ─────────────────────────────────────────────────────────── fetchers

def _get_json(url: str, post: Optional[dict] = None, timeout: int = 10):
    """(data, error). Never raises: a dead source is reported, not a crash."""
    import requests
    try:
        r = (requests.post(url, json=post, timeout=timeout) if post is not None
             else requests.get(url, timeout=timeout))
        if r.status_code >= 400:
            return None, f"HTTP {r.status_code}"
        return r.json(), None
    except ValueError:
        return None, "not JSON"
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


def _doc(hit: dict, label: str, date: str = "", host: str = "") -> Optional[dict]:
    """A hit screened and wrapped like every web doc, then labelled."""
    d = websearch._to_doc(0, hit)
    if d:
        d.update(label=label, source="live", date=date,
                 host=host or websearch._host(d["url"]))
    return d


def _web_docs(hits: List[dict], news: bool) -> List[dict]:
    out = []
    for h in hits:
        url = str(h.get("href") or h.get("url") or "")
        host = websearch._host(url)
        if news:
            date = str(h.get("date") or "")[:10]
            label = f"News - {h.get('source') or host}" + (f", {date}" if date else "")
        else:
            date, label = "", f"Web - {host}"
        d = _doc(h, label, date, host)
        if d:
            out.append(d)
    return sorted(out, key=lambda d: d["date"], reverse=True)   # undated ("") last


def _meta(kind_: str, source: str, docs: list, error, resolved: bool) -> dict:
    return {"kind": kind_, "source": source, "n": len(docs), "error": error,
            "resolved": resolved}


def _down_now(query: str):
    product = status_product(query)
    host = STATUS_HOSTS[product]
    data, err = _get_json(f"https://{host}/api/v2/summary.json")
    if err or not isinstance(data, dict):
        docs, meta = _incident(query)
        meta.update(kind="down_now", error=f"{_STATUS_NAME[product]} status page: {err or 'bad reply'}"
                    + (f"; {meta['error']}" if meta["error"] else ""))
        return docs, meta
    name = _STATUS_NAME[product]
    text = f"{name} status: {(data.get('status') or {}).get('description', 'unknown')}."
    for i in data.get("incidents") or []:
        text += (f" Incident: {i.get('name', '')} - {i.get('status', '')}"
                 f" (updated {str(i.get('updated_at', ''))[:16]}).")
    short = host.removeprefix("www.")
    date = str((data.get("page") or {}).get("updated_at") or "")[:10]
    d = _doc({"title": f"{name} status", "body": text, "url": f"https://{host}"},
             f"Status page - {short}", date, short)
    docs = [d] if d else []
    return docs, _meta("down_now", f"{name} status page", docs, None, True)


def _incident(query: str):
    hits, err = websearch.search(query, timelimit="m", news=True)
    if hits:
        docs = _web_docs(hits, news=True)
        return docs, _meta("incident", "DuckDuckGo news, last month", docs, None, False)
    hits, err2 = websearch.search(query, timelimit="m")
    docs = _web_docs(hits, news=False)
    return docs, _meta("incident", "DuckDuckGo, last month", docs, err2 or err, False)


@lru_cache(maxsize=1)
def _eol_slugs() -> frozenset:
    """endoflife.date's product slugs. A failed fetch raises, so it isn't cached."""
    data, err = _get_json("https://endoflife.date/api/all.json")
    if err or not isinstance(data, list):
        raise LookupError(err or "bad reply")
    return frozenset(data)


_WORD = re.compile(r"[a-z0-9][\w.+-]*", _I)
_NAME_BEFORE_VERSION = re.compile(r"\b([a-z][\w.+-]*)\s+v?(\d+(?:\.\d+)*)\b", _I)


def _eol(query: str):
    try:
        slugs = _eol_slugs()
    except LookupError:
        slugs = frozenset()
    m = _NAME_BEFORE_VERSION.search(query)
    words = ([m.group(1).lower()] if m else []) + [w.lower() for w in _WORD.findall(query)]
    slug = word = None
    for w in words:
        cand = EOL_ALIASES.get(w, w)
        if cand in slugs:
            slug, word = cand, w
            break
    if not slug:
        name = m.group(1).lower() if m else ""
        hits, err = websearch.search(f"{name} end of life" if name else query)
        docs = _web_docs(hits, news=False)
        return docs, _meta("eol", "DuckDuckGo (not on endoflife.date)", docs, err, False)
    cycles, err = _get_json(f"https://endoflife.date/api/{slug}.json")
    if err or not isinstance(cycles, list):
        return [], _meta("eol", "endoflife.date", [], err or "bad reply", True)
    vm = re.search(rf"\b{re.escape(word)}\s+v?(\d+(?:\.\d+)*)", query, _I)
    asked = vm.group(1) if vm else None
    pick = [c for c in cycles if asked and (str(c.get("cycle")) == asked
                                            or asked.startswith(f"{c.get('cycle')}."))][:1]
    pick = pick or cycles[:4]

    def line(c):
        eol = c.get("eol")
        when = ("no end-of-life date yet" if eol is False else
                "end of life (date not given)" if eol is True else f"end of life {eol}")
        return f"{word.capitalize()} {c.get('cycle')}: {when}, latest {c.get('latest', '?')}"

    text = "; ".join(line(c) for c in pick) + "."
    label = f"endoflife.date - {word}" + (f" {pick[0].get('cycle')}" if len(pick) == 1 else "")
    d = _doc({"title": f"{word} end of life", "body": text,
              "url": f"https://endoflife.date/{slug}"}, label, "", "endoflife.date")
    docs = [d] if d else []
    return docs, _meta("eol", "endoflife.date", docs, None, True)


def _plain(kind_: str, query: str, timelimit: Optional[str], source: str):
    hits, err = websearch.search(query, timelimit=timelimit)
    docs = _web_docs(hits, news=False)
    return docs, _meta(kind_, source, docs, err, False)


def fetch(kind_: str, query: str) -> Tuple[List[dict], dict]:
    """(docs, meta) for one of the answer-only types. meta: kind, source, n,
    error, resolved (the product was found by name in a structured source)."""
    if kind_ == "down_now":
        return _down_now(query)
    if kind_ == "incident":
        return _incident(query)
    if kind_ == "eol":
        return _eol(query)
    if kind_ == "compat":
        return _plain(kind_, query, "y", "DuckDuckGo, last year")
    return _plain(kind_, query, None, "DuckDuckGo")


# ─────────────────────────────────────────────── package safety (OSV)

OSV_QUERY = "https://api.osv.dev/v1/query"
_REGISTRY = {"PyPI": ("https://pypi.org/pypi/{}/json", lambda d: (d.get("info") or {}).get("version")),
             "npm": ("https://registry.npmjs.org/{}/latest", lambda d: d.get("version"))}


def _newer(fix: str, version: str) -> bool:
    """Is `fix` a later release than `version`? An unparseable pair counts as
    a fix, so the advisory is cited as fixable rather than called unfixed."""
    from packaging.version import InvalidVersion, Version
    try:
        return Version(fix) > Version(version)
    except InvalidVersion:
        return True


def _vkey(v: str):
    """Sort key: real version order where parseable, text order after."""
    from packaging.version import InvalidVersion, Version
    try:
        return (0, Version(v), "")
    except InvalidVersion:
        return (1, Version("0"), v)


def _latest(name: str, ecosystem: str) -> Optional[str]:
    url, read = _REGISTRY[ecosystem]
    data, err = _get_json(url.format(name))
    return read(data) if not err and isinstance(data, dict) else None


def package_safety(query: str) -> dict:
    """OSV advisories for the package the question names.

    verdict_docs: advisories with a CVE id and a fix newer than the checked
    version -- the only live evidence allowed near the verdict, because
    "Patch now" is then advice the user can follow. answer_docs: every
    advisory, unfixed and CVE-less ones included, for the paragraph. A clean
    result is stated, never turned into a green light.
    """
    out = {"verdict_docs": [], "answer_docs": []}
    ref = package_ref(query)
    if not ref:
        return out | {"meta": _meta("package_safety", "OSV", [], "no package named", False)}
    name, eco, asked = ref
    ecos = [eco] if eco else ["PyPI", "npm"]
    found = next(((e, v) for e in ecos for v in [_latest(name, e)] if v), None)
    if not found:
        return out | {"meta": _meta("package_safety", "OSV", [],
                                    f"{name} not found on {' or '.join(ecos)}", False)}
    eco, latest = found
    version = asked or latest
    source = f"OSV via {eco}, {name} {version}"
    data, err = _get_json(OSV_QUERY, post={"version": version,
                                           "package": {"name": name, "ecosystem": eco}})
    if err or not isinstance(data, dict):
        return out | {"meta": _meta("package_safety", source, [], err or "bad reply", True)}
    import guardrail
    for v in data.get("vulns") or []:
        vid = str(v.get("id", ""))
        cves = [a for a in [vid, *(v.get("aliases") or [])] if str(a).upper().startswith("CVE-")]
        fixes = [ev["fixed"] for aff in v.get("affected") or () for rg in aff.get("ranges") or ()
                 for ev in rg.get("events") or () if "fixed" in ev]
        newer = [f for f in fixes if _newer(f, version)]
        summary = guardrail.scrub(str(v.get("summary") or v.get("details") or "")[:300])[0]
        url = f"https://osv.dev/vulnerability/{vid}"
        date = str(v.get("published") or "")[:10]
        if newer:
            fix = min(newer, key=_vkey)
            text = (f"{name} {version}: {vid} ({', '.join(cves) or 'no CVE id'}) {summary}. "
                    f"Fixed in {fix}.")
            if cves:
                out["verdict_docs"].append({"title": vid, "text": text, "body": text, "url": url,
                                            "source": "cve", "is_cve": True, "date": date,
                                            "tier": "OSV"})   # the Sources table's attribution
        else:
            text = f"{name} {version}: unfixed advisory {vid}, no fixed release yet. {summary}"
        d = _doc({"title": vid, "body": text, "url": url}, f"OSV - {vid}", date, "osv.dev")
        if d:
            out["answer_docs"].append(d)
    if not out["answer_docs"]:
        d = _doc({"title": f"{name} {version}", "url": f"https://osv.dev/list?q={name}",
                  "body": f"OSV: no known advisories against {name} {version}."},
                 f"OSV - {name} {version}", "", "osv.dev")
        out["answer_docs"] = [d] if d else []
    return out | {"meta": _meta("package_safety", source, out["answer_docs"], None, True)}
