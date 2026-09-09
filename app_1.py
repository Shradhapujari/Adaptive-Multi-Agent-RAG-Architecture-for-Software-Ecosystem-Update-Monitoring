"""
Multi-Agent RAG System — Adaptive Multi-Agent RAG Architecture
=============================================
Streamlit web app for software ecosystem monitoring.
Uses 4 live releasetrain.io API endpoints.

Agents:
  0. Temporal Grounder   → rule-based, resolves "today"/"last week" to dates
  1. Community Agent     → reddit/query/positive
  2. Release Notes Agent → /api/v/
  3. CVE Agent           → reddit/query/cve
  4. Query Rewriter      → Llama 3.1 via Ollama (local)
  5. Answer Presenter    → prose paragraph with bracketed evidence
                           (eval_harness provider layer; rule-based offline)

Run:
    pip install streamlit requests
    streamlit run app.py

University of the Pacific — Agentic AI Research — 2026
"""

import streamlit as st
import requests
import json
import urllib.request
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional

from temporal import resolve_temporal, matches_window
from fetch_union import union_fetch, product_terms
from answer_agent import present_answer
from store import open_store, caching_fetch
from grounding import ground
import vendor
import yesno
import survey

# ── PAGE CONFIG ──────────────────────────────────────────
st.set_page_config(
    page_title="Multi-Agent RAG System — Software Ecosystem Monitor",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CUSTOM CSS ───────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #0D1B2A 0%, #0E9AA7 100%);
        padding: 2rem;
        border-radius: 12px;
        margin-bottom: 2rem;
        color: white;
    }
    .agent-card {
        background: #f8f9fa;
        border-left: 4px solid #0E9AA7;
        padding: 1rem;
        border-radius: 8px;
        margin: 0.5rem 0;
    }
    .result-card {
        background: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 1rem;
        margin: 0.5rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-box {
        background: #0D1B2A;
        color: white;
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
    }
    .positive { border-left: 4px solid #2E7D32; }
    .negative { border-left: 4px solid #E8593C; }
    .neutral  { border-left: 4px solid #F5A623; }
    .cve-card { border-left: 4px solid #C62828; background: #FFF5F5; }
    .release-card { border-left: 4px solid #1565C0; background: #F0F4FF; }
</style>
""", unsafe_allow_html=True)

# ── API ENDPOINTS ─────────────────────────────────────────
REDDIT_POSITIVE_API = "https://releasetrain.io/api/reddit/query/positive"
RELEASES_API        = "https://releasetrain.io/api/v/"
CVE_API             = "https://releasetrain.io/api/reddit/query/cve"
OLLAMA_API          = "http://localhost:11434/api/generate"


def presenter_spec() -> str:
    """Which model the Answer Presenter uses, if any.

    Read from Streamlit secrets first so a deployed host can supply one without
    a code change; empty means the presenter runs its rule-based path, which is
    what Community Cloud does today (no Ollama, no key).
    """
    try:
        return str(st.secrets.get("PRESENTER_MODEL", "") or "")
    except Exception:
        return ""

# ── AGENT 1: QUERY REWRITER ──────────────────────────────

@dataclass
class Rewrite:
    """A rewritten query and which path produced it.

    Same shape and vocabulary as `answer_agent.PresentedAnswer`, and for the
    same reason: the demo must never show rule-based output while implying a
    model produced it. The presenter already said which path it took; the
    rewriter returned a bare string, so a rule-based expansion appeared under
    the heading "Query Rewriter Agent — Llama 3.1" with nothing to distinguish
    it. On Streamlit Community Cloud, where no Ollama is reachable, that is
    every run.
    """
    query: str
    mode: str                  # "llm" or "rule-based"
    model: str = ""
    note: str = ""


def _rule_based_rewrite(query: str) -> str:
    """Keyword expansion used when no model is reachable."""
    expansions = {
        "bugs": "bug fixes resolved defects",
        "latest": "latest version release notes",
        "critical": "critical security vulnerability patch",
        "update": "software update release changelog",
        "today": f"released {datetime.now().strftime('%Y-%m-%d')}",
    }
    rewritten = query.lower()
    for k, v in expansions.items():
        if k in rewritten:
            rewritten = rewritten.replace(k, v)
    return rewritten


def rewrite_query(query: str) -> Rewrite:
    """Rewrite for retrieval with Llama 3.1, or by rule, saying which."""
    prompt = f"""You are a software update search expert.
Rewrite this query to better match software update documents and Reddit posts.
Focus on: bug fixes, security patches, release notes, CVE vulnerabilities, version updates.
Query: "{query}"
Return ONLY the rewritten query in under 15 words, nothing else:"""

    payload = json.dumps({
        "model": "llama3.1",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0}
    }).encode()

    try:
        req = urllib.request.Request(
            OLLAMA_API,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            out = json.loads(r.read()).get("response", "").strip()
            # Llama wraps the rewrite in quotes often enough that the quotes
            # end up in the `q` parameter; strip them rather than search for them.
            out = out.strip(" \"'").strip()
        if out:
            return Rewrite(out, mode="llm", model="llama3.1")
        return Rewrite(_rule_based_rewrite(query), mode="rule-based",
                       note="llama3.1 returned an empty rewrite")
    except Exception as exc:                    # noqa: BLE001 - reported, not hidden
        return Rewrite(_rule_based_rewrite(query), mode="rule-based",
                       note=f"llama3.1 not reachable ({type(exc).__name__})")

# ── STORE ────────────────────────────────────────────────
# One SQLite file under data/, opened once per Streamlit process. Two jobs:
# it caches every document the agents retrieve, so a host that cannot reach
# releasetrain.io answers from what earlier runs fetched instead of from an
# "API unavailable" placeholder; and it logs each answered question with the
# documents behind it, so a run is inspectable after the tab is closed.
#
# `cache_resource` and not `cache_data`: the connection is a handle, not a
# value, and re-opening it on every widget interaction would leave a file
# handle per rerun. A store that fails to open is not a reason to refuse the
# question -- the pipeline runs storeless, exactly as it did before.

@st.cache_resource(show_spinner=False)
def get_store():
    try:
        return open_store()
    except Exception:
        return None



# ── FETCH OUTAGES ────────────────────────────────────────
# A failed fetch used to return one row whose title was the exception text:
#
#   [{"product": "API unavailable: HTTPSConnectionPool(... Read timed out)"}]
#
# That row is indistinguishable from a document once it leaves the fetcher. It
# was counted ("Releases 1"), rendered as a release, and cited as a source, so
# a network timeout reached the reader as a retrieved fact. A system that says
# "1 release found" and names a stack trace has not degraded gracefully, it has
# fabricated a citation.
#
# Fetchers now return no documents and record the outage here instead. The
# pipeline reports the feed as unreachable, which is true and is checkable.
_FETCH_ERRORS: ContextVar[Optional[List[Dict[str, str]]]] = ContextVar(
    "marag_fetch_errors", default=None)


def _reset_fetch_errors() -> List[Dict[str, str]]:
    """Start a fresh outage log for one pipeline run, and return it."""
    log: List[Dict[str, str]] = []
    _FETCH_ERRORS.set(log)
    return log


def _record_fetch_error(agent: str, exc: Exception) -> list:
    """Log an outage and return the empty result the caller should propagate."""
    log = _FETCH_ERRORS.get()
    if log is not None:
        log.append({"agent": agent, "error": f"{type(exc).__name__}: {exc}"})
    return []


def _get_json(url: str, params: dict, agent: str, attempts: int = 2,
              timeout: int = 20) -> Optional[dict]:
    """GET with one retry, or None with the outage recorded.

    The screenshot that prompted this read `Read timed out. (read timeout=10)`
    against releasetrain.io, so the timeout is longer and a single transient
    failure no longer costs the whole pool.
    """
    last: Optional[Exception] = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            last = RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:          # noqa: BLE001 - reported, not swallowed
            last = exc
        if attempt + 1 < attempts:
            time.sleep(1.0)
    _record_fetch_error(agent, last or RuntimeError("unknown failure"))
    return None



_CVE_ID = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.I)
_SECURITY_WORDS = re.compile(
    r"\b(vulnerab\w*|exploit\w*|security|patch\w*|advisor\w*|malware|"
    r"ransomware|breach\w*|zero.?day|rce|privilege escalation|backdoor)\b", re.I)


def is_security_post(row: dict) -> bool:
    """Whether a Reddit row from the CVE feed is actually about security.

    /api/reddit/query/cve does not filter by security any more than it filters
    by `q`. Measured 2026-09-01, `q=linux&limit=5` returned "North Pi case with
    custom side panel", "Air Force Sys Admin" and "Coding as a hobby?" -- no CVE
    id in any title, `isAboutCve` unset on every row, and nothing about Linux.
    Rendering those under a padlock as security findings, and counting them
    beside real NVD advisories, states something false about them.

    So the feed's own claim is not taken on faith: a row has to carry a CVE id,
    the upstream flag, or a security word of its own.
    """
    text = " ".join(str(row.get(f) or "") for f in ("title", "notes"))
    tags = " ".join(str(t) for t in (row.get("tags") or []))
    return bool(row.get("is_cve")
                or _CVE_ID.search(text) or _CVE_ID.search(tags)
                or _SECURITY_WORDS.search(text))


# ── AGENT 2: COMMUNITY AGENT ─────────────────────────────

def fetch_community_feedback(query: str, limit: int = 5) -> list:
    """Fetches community Reddit feedback from releasetrain.io."""
    data = _get_json(REDDIT_POSITIVE_API, {"q": query, "limit": limit},
                     agent="Community")
    if data is not None:
        posts = data.get("data", [])
        return [{
            "title":      p.get("title", ""),
            "reddit_id":  p.get("redditId", ""),
            "subreddit":  p.get("subreddit", ""),
            "url":        p.get("url", ""),
            "score":      p.get("score", 0),
            "sentiment":  "Positive" if p.get("metadata", {}).get("predicted", {}).get("positiveScore", 0) > 0.5 else "Neutral",
            "date":       p.get("created_utc", "")[:10],
            "is_cve":     p.get("isAboutCve", False),
            "is_update":  p.get("isAboutLatestUpdate", False),
        } for p in posts[:limit]]
    return []

# ── SINGLE-AGENT BASELINE ────────────────────────────────

def run_single_agent(query: str, top_k: int = 4) -> dict:
    """The paper's baseline arm, run from the UI on the user's own question.

    Not a reimplementation: this is `eval_harness.generators.SingleAgentGenerator`,
    the same object the published comparison scores. A demo that showed a
    single-agent arm built here instead would be comparing the pipeline
    against a strawman written to lose, and the measured numbers would no
    longer describe the thing on screen.

    Raw query straight to the retriever, one synthesis call, and nothing else:
    no temporal grounding, no vendor/intent detection, no rewriting, no CVE
    agent, no RLAIF, no survey weighting, no yes/no tally.

    With no model reachable the generator's prose path returns a generation
    error, which would read as the baseline failing rather than as the host
    lacking Ollama. Its deterministic `template` rendering is used instead and
    the caller is told which arm actually ran.
    """
    from eval_harness.generators import SingleAgentGenerator
    from eval_harness.providers import make_client

    spec = presenter_spec() or "ollama:mistral"
    client = None
    try:
        client = make_client(spec)
        prose = client.available()
    except Exception:
        prose = False
    gen = (SingleAgentGenerator(client=client, top_k=top_k, render="prose")
           if prose else SingleAgentGenerator(top_k=top_k, render="template"))
    t0 = time.time()
    out = gen.generate(query)
    return {**out, "arm": gen.name, "model": spec if prose else "",
            "elapsed": round(time.time() - t0, 1)}


# ── AGENT 3: RELEASE NOTES AGENT ─────────────────────────

def fetch_release_notes(query: str, limit: int = 5) -> list:
    """Fetches live software release notes from releasetrain.io."""
    data = _get_json(RELEASES_API, {"q": query, "limit": limit},
                     agent="Release Notes")
    if data is not None:
        versions = data.get("versions", [])
        # The endpoint ignores `limit` and returns the whole product's
        # history newest-first, so the slice below is ours. Taking the
        # first `limit` rows takes only advisories: measured 2026-09-01,
        # q=Linux returns 606 rows of which 449 are CVE records dated
        # 2026-08-28, while the newest shipped kernel is dated 2026-07-19.
        # Every release is therefore behind every advisory, and any slice
        # short of ~450 rows contains no release at all.
        #
        # So take `limit` of each kind rather than `limit` of the whole.
        # The pool then carries both, and the intent filter downstream
        # decides which may be cited -- a decision that needs both kinds
        # present to be a decision.
        advisories = [v for v in versions if v.get("isCve")]
        releases = [v for v in versions if not v.get("isCve")]
        versions = releases[:limit] + advisories[:limit]
        return [{
            "product":   v.get("versionProductName", ""),
            "version":   v.get("versionNumber", ""),
            "date":      v.get("versionReleaseDate", ""),
            "notes":     v.get("versionReleaseNotes", "")[:200],
            "channel":   v.get("versionReleaseChannel", ""),
            "url":       v.get("versionUrl", ""),
            "security":  v.get("classification", {}).get("securityType", []),
            "breaking":  v.get("classification", {}).get("breakingType", []),
            "is_cve":    v.get("isCve", False),
        } for v in versions]
    return []

# ── AGENT 4: CVE AGENT ───────────────────────────────────

def fetch_cve_data(query: str, limit: int = 5) -> list:
    """Fetches CVE security vulnerability data from releasetrain.io."""
    data = _get_json(CVE_API, {"q": query, "limit": limit}, agent="CVE")
    if data is not None:
        posts = data.get("data", [])
        return [{
            "title":     p.get("title", ""),
            "subreddit": p.get("subreddit", ""),
            "url":       p.get("url", ""),
            "date":      p.get("created_utc", "")[:10],
            "score":     p.get("score", 0),
            "tags":      p.get("tags", []),
        } for p in posts[:limit]]
    return []

# ── RLAIF EVALUATOR ──────────────────────────────────────

def evaluate_results(community: list, releases: list, cve: list, query: str,
                     survey_on: bool = True) -> dict:
    """Scores result quality and generates RLAIF signal.

    The count-based score says how much came back, not whether any of it is
    what people wanted. With `survey_on`, the 52-respondent priority weights
    (see survey.py) supply the second half: a run that returned five documents
    none of which touch a stated priority scores below one that returned three
    that do. Blended rather than substituted -- volume is still evidence, it is
    just no longer the only evidence -- and the base score is kept alongside so
    the effect of the toggle is visible instead of merely applied.
    """
    total   = len(community) + len(releases) + len(cve)
    quality = min(total / 15.0, 1.0)
    base    = quality
    align   = survey.alignment(list(community) + list(releases) + list(cve))
    if survey_on:
        quality = 0.7 * quality + 0.3 * align["score"]
    signal  = "positive" if quality >= 0.3 else "negative"

    # Count relevant results
    relevant = sum(1 for r in releases if any(
        w in r.get("notes", "").lower() + r.get("product", "").lower()
        for w in query.lower().split()
    ))

    return {
        "quality":        round(quality, 2),
        "quality_base":   round(base, 2),
        "survey_on":      survey_on,
        "survey":         align,
        "signal":         signal,
        "total_results":  total,
        "community_count": len(community),
        "release_count":  len(releases),
        "cve_count":      len(cve),
        "relevant":       relevant,
    }

# ── MANAGER AGENT — ORCHESTRATOR ─────────────────────────

def run_pipeline(query: str, show_steps: bool = True, limit: int = 5,
                 yesno_on: bool = True, unclear_as_no: bool = False,
                 survey_on: bool = True) -> dict:
    """Main orchestrator — runs all 4 agents and returns results."""
    results = {
        "original_query":  query,
        "grounded_query":  query,
        "temporal":        None,
        "rewritten_query": "",
        "rewrite":         None,
        "fetch_phrasings": [],
        "release_phrasings": [],
        "community":       [],
        "releases":        [],
        "cve":             [],
        "evaluation":      {},
        "timing":          {},
        "errors":          [],
    }

    # Step 0 — Temporal Grounder
    # Runs before everything else: retrieval is similarity-based, and no
    # document contains the word "today" -- it contains a date. Resolving the
    # deictic term first means the rewriter, the fetch and the ranker all see
    # the absolute date instead of a token that cannot match.
    errors = _reset_fetch_errors()
    results["errors"] = errors

    t0 = time.time()
    # One call, and it is the same call the evaluation's `single_agent_grounded`
    # arm makes: temporal grounding, vendor detection from the /api/c/names
    # catalog, and intent classification. Keeping the demo and the measured arm
    # on one code path is the point -- a demo that grounds differently from the
    # thing being measured is not a demo of it.
    g = ground(query)
    temporal = g.temporal
    results["temporal"] = temporal
    results["grounding"] = g
    results["grounded_query"] = g.rewritten
    results["timing"]["temporal"] = round(time.time() - t0, 2)
    grounded = temporal.query

    # Step 1 — Query Rewriter
    if show_steps:
        with st.spinner("🔄 Query Rewriter Agent — Llama 3.1 rewriting query..."):
            t0 = time.time()
            # The rewriter sees the *stripped* phrasing: its job is vocabulary
            # expansion, and handing it the resolved date only gets the date
            # copied into a query that then fetches nothing. The grounded
            # phrasing is fetched alongside it, below.
            rw = rewrite_query(temporal.stripped or query)
            rewritten = rw.query
            results["rewrite"] = rw
            results["rewritten_query"] = rewritten
            results["timing"]["rewriter"] = round(time.time()-t0, 1)

    # Fetch phrasings: the expanded one first (recall), then the grounded one
    # (date-aware), deduped so an unchanged query is not fetched twice.
    phrasings = []
    for p in [rewritten or temporal.stripped or query] + temporal.fetch_phrasings:
        if p and p not in phrasings:
            phrasings.append(p)
    results["fetch_phrasings"] = phrasings

    # The release endpoint matches product names, so a sentence retrieves
    # nothing from it however well phrased. Fetch the product term too; the
    # sentence phrasings still run, so nothing they would have found is lost.
    # Catalog-detected products lead, because /api/v/ matches `q` against
    # product names and nothing else: measured 2026-09-01, q="linux" returns
    # 606 rows and q="linux version" returns 0. product_terms stays as the
    # fallback for a question naming something the catalog does not hold.
    release_phrasings = g.vendor_names + [p for p in phrasings
                                          if p not in g.vendor_names]
    release_phrasings += [t for t in product_terms(temporal.stripped or query)
                          if t not in release_phrasings]
    results["release_phrasings"] = release_phrasings

    # Each agent's fetch is wrapped so its results are written to the store and
    # so an unreachable endpoint falls back to the documents earlier runs
    # retrieved. The wrapper is transparent to `union_fetch`, which takes the
    # fetch function as an argument precisely so it can be substituted.
    db = get_store()
    community_fetch = caching_fetch(db, "community", fetch_community_feedback)
    release_fetch   = caching_fetch(db, "release",   fetch_release_notes)
    cve_fetch       = caching_fetch(db, "cve",       fetch_cve_data)

    # Both pools are fetched deeper than they are shown, because the filters
    # in step 4b run *after* the fetch and cutting to `limit` first leaves them
    # nothing to keep. /api/v/ returns its rows newest-first and 449 of the 606
    # Linux rows are advisories filed daily, so the first 5 are always
    # advisories and a release question filtered down to an empty pool. Same
    # truncate-before-filter shape as the bug fixed in fetch_vendor_releases.
    pool_limit = max(limit * 10, 50)

    # Step 2 — Community Agent
    if show_steps:
        with st.spinner("💬 Community Agent — fetching Reddit feedback..."):
            t0 = time.time()
            results["community"] = union_fetch(community_fetch, phrasings,
                                               pool_limit, temporal)
            results["timing"]["community"] = round(time.time()-t0, 1)

    # Step 3 — Release Notes Agent
    if show_steps:
        with st.spinner("📦 Release Notes Agent — fetching live releases..."):
            t0 = time.time()
            results["releases"] = union_fetch(release_fetch, release_phrasings,
                                              pool_limit, temporal)
            results["timing"]["releases"] = round(time.time()-t0, 1)

    # Step 4 — CVE Agent
    if show_steps:
        with st.spinner("🔐 CVE Agent — fetching security vulnerabilities..."):
            t0 = time.time()
            results["cve"] = union_fetch(cve_fetch, phrasings, limit, temporal)
            results["timing"]["cve"] = round(time.time()-t0, 1)

    # Step 4b — Vendor and record-type filter
    # This is where "Linux v25.642087.0" is stopped. /api/v/?q=Linux returns
    # 606 rows of which 449 are NVD CVE records whose versionNumber is an
    # affected-version string, not a version that shipped; the pipeline used to
    # sort them all by date and report the newest, which is always an advisory.
    # For a release question those rows are not weak evidence, they are wrong
    # evidence, so intent decides whether they may be cited at all.
    #
    # Filters never empty a pool: an answer over imperfect documents beats an
    # answer over none, and a demo that returns nothing teaches the reader
    # nothing about what it fixed.
    t0 = time.time()
    if g.vendors:
        scoped = vendor.filter_by_vendor(results["releases"], g.vendors)
        results["releases"] = scoped or results["releases"]
        # No `or results["community"]` fallback: when the subject filter finds
        # nothing about this question in the feed, that is the finding. The
        # fallback used to restore the pool it had just rejected, which is how
        # "How to limit battery charge?" ended up cited as the community
        # evidence for a question about a deleted kernel.
        results["community"] = vendor.filter_community(results["community"],
                                                       g.vendors, terms=g.terms)

    # The CVE feed is Reddit, not an advisory feed, so it gets the same vendor
    # scoping as the community pool and then has to prove it is about security
    # at all. Filters never empty a pool; a thin pool beats a false one.
    if g.vendors:
        results["cve"] = vendor.filter_community(results["cve"], g.vendors,
                                                 terms=g.terms)
    on_topic = [r for r in results["cve"] if is_security_post(r)]
    results["cve_dropped"] = len(results["cve"]) - len(on_topic)
    results["cve"] = on_topic

    if "cve" not in g.citable_kinds:
        shipped = [r for r in results["releases"] if vendor.is_release_record(r)]
        results["advisories_excluded"] = len(results["releases"]) - len(shipped)
        results["releases"] = shipped or results["releases"]
    else:
        results["advisories_excluded"] = 0

    # Only now cut to what the user asked to see. Everything above ranked and
    # filtered over the deep pool.
    results["community"] = results["community"][:limit]
    results["releases"] = results["releases"][:limit]
    results["cve"] = results["cve"][:limit]
    results["timing"]["filter"] = round(time.time() - t0, 2)

    # Step 4b — Yes/No consensus
    # Only for questions phrased to take a one-word answer, and only off the
    # comments of the thread that was retrieved for them: this counts what
    # other people answered, it does not infer an answer from the documents.
    results["yesno"] = None
    # `is_title=True`: what the user typed is the question itself, the same
    # shape a post's title is, not prose with a question somewhere inside it.
    if yesno_on and yesno.looks_yesno(query, is_title=True):
        thread = yesno.find_thread(query)
        if thread is not None:
            results["yesno"] = {**yesno.tally(thread, unclear_as_no=unclear_as_no),
                                "thread": thread}

    # Step 5 — RLAIF Evaluator
    results["evaluation"] = evaluate_results(
        results["community"], results["releases"],
        results["cve"], grounded, survey_on=survey_on
    )

    return results

def _n_shipped(rows) -> int:
    """How many of the release-feed rows are versions that actually shipped."""
    return sum(1 for r in (rows or []) if vendor.is_release_record(r))


def _agent_table(results=None, presented=None) -> str:
    """The sidebar's agent roster, reporting what each agent actually did.

    It used to be a static table: "Query Rewriter | Llama 3.1" whether or not
    a model was reachable, "CVE Security | Live API" whether or not the feed
    answered. On Streamlit Community Cloud no Ollama is reachable, so the
    rewriter row was wrong on every run there, and a timed-out feed still
    advertised itself as live.

    The sidebar renders before the pipeline does, so this is written into a
    placeholder twice: an idle roster first, then the real one once the run
    has finished and every status is known.
    """
    def row(icon, name, status):
        return f"| {icon} {name} | {status} |"

    head = ["| Agent | Status |", "|-------|--------|"]
    if results is None:
        return "\n".join(head + [
            row("📅", "Temporal Grounder", "Rule-based"),
            row("🏷", "Vendor & Intent", "Catalog + cues"),
            row("🔄", "Query Rewriter", "Llama 3.1 / rule"),
            row("💬", "Community", "Live API"),
            row("📦", "Release Notes", "Live API"),
            row("🔐", "Security", "Live API"),
            row("🧾", "Answer Presenter", "LLM / rule-based"),
            "", "*Idle — statuses fill in after a run.*"])

    down = {e["agent"] for e in (results.get("errors") or [])}

    tr = results.get("temporal")
    temporal_status = "Grounded" if (tr is not None and tr.changed) else "Nothing to ground"

    gq = results.get("grounding")
    if gq is None:
        vendor_status = "—"
    elif gq.vendors:
        intent = gq.intent.label if (gq.intent and gq.intent.confident) else "no intent"
        vendor_status = f"{', '.join(gq.vendor_names)} · {intent}"
    else:
        vendor_status = "no product matched"

    rw = results.get("rewrite")
    if rw is None:
        rewriter_status = "Not run"
    elif rw.mode == "llm":
        rewriter_status = rw.model
    else:
        rewriter_status = "Rule-based (fallback)"

    def feed(agent, rows, extra=""):
        if agent in down:
            return "⚠️ Unreachable"
        return f"{len(rows)} doc(s){extra}"

    rel = results.get("releases") or []
    shipped = _n_shipped(rel)
    rel_extra = f" · {len(rel) - shipped} advisory" if len(rel) > shipped else ""
    dropped = results.get("cve_dropped") or 0

    if presented is None:
        presenter_status = "Not run"
    elif presented.mode == "llm":
        presenter_status = presented.model
    else:
        presenter_status = "Rule-based"

    return "\n".join(head + [
        row("📅", "Temporal Grounder", temporal_status),
        row("🏷", "Vendor & Intent", vendor_status),
        row("🔄", "Query Rewriter", rewriter_status),
        row("💬", "Community", feed("Community", results.get("community") or [])),
        row("📦", "Release Notes",
            feed("Release Notes", [r for r in rel if vendor.is_release_record(r)], rel_extra)),
        row("🔐", "Security",
            feed("CVE", results.get("cve") or [],
                 f" · {dropped} off-topic dropped" if dropped else "")),
        row("🧾", "Answer Presenter", presenter_status),
    ])


# ── SIDEBAR ───────────────────────────────────────────────

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/en/b/bb/University_of_the_Pacific_seal.svg", width=80)
    st.markdown("### Multi-Agent RAG System")
    st.markdown("**Adaptive Multi-Agent RAG Architecture**")
    st.markdown("University of the Pacific · 2026")
    st.divider()

    st.markdown("#### 🤖 Active Agents")
    # Filled in again at the end of the run, once every status is a fact
    # rather than an advertisement.
    agent_status_slot = st.empty()
    agent_status_slot.markdown(_agent_table())
    spec = presenter_spec()
    st.caption(f"Presenter model: `{spec}`" if spec
               else "Presenter model: none configured — cited paragraph is "
                    "composed rule-based.")
    st.divider()

    st.markdown("#### ⚙️ Settings")
    mode = st.radio(
        "Answering mode",
        ["Multi-agent pipeline", "Single agent (paper baseline)"],
        help="The baseline is the evaluation's own `single_agent` arm: raw "
             "query to the retriever and one synthesis call, with every "
             "coordinating agent removed. Same question, so the difference on "
             "screen is the difference the paper measures.")
    single_mode = mode.startswith("Single")
    result_limit = st.slider("Results per agent", 3, 10, 5)
    show_pipeline = st.toggle("Show pipeline steps", value=True)
    show_raw = st.toggle("Show raw API data", value=False)
    yesno_on = st.toggle("Yes/No consensus", value=True, disabled=single_mode,
                         help="For questions that take a one-word answer, count how "
                              "the retrieved thread's commenters actually answered it.")
    unclear_as_no = st.toggle("Count non-committal comments as No", value=False,
                              disabled=single_mode or not yesno_on,
                              help="A commenter who neither confirms nor denies is "
                                   "read as a no. Defensible for “did this happen to "
                                   "you?” — someone it happened to says so — but it "
                                   "is an inference from silence, not from the comment.")
    survey_on = st.toggle(f"Survey-informed evaluator (n={survey.respondents()})",
                          value=True, disabled=single_mode,
                          help="Blend the 2024 software-update survey's user "
                               "priorities into the quality score, and report which "
                               "of them these results address.")

    if single_mode:
        st.caption("Baseline arm selected — the agents above it are switched "
                   "off, which is what makes it the baseline.")

    st.divider()
    st.markdown("#### 💡 Example queries")
    examples = [
        "Any critical Linux updates today?",
        "Security patches released in the past 7 days",
        "Critical software updates published today",
        "What bugs were fixed in Chrome recently?",
        "Any security vulnerabilities in Python?",
        "Latest Django release notes",
        "MacOS updates with negative community reaction",
        "Did the latest Fedora 44 update delete your kernel and grub?",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["query_input"] = ex

    st.divider()
    st.markdown("#### 🗄️ Store")
    _db = get_store()
    if _db is None:
        st.caption("Unavailable — the pipeline runs without it, fetching live "
                   "every time and keeping no history.")
    else:
        _stats = _db.stats()
        sc1, sc2 = st.columns(2)
        sc1.metric("Documents", _stats["documents_total"])
        sc2.metric("Runs", _stats["runs"])
        by_pool = _stats["documents"]
        if by_pool:
            st.caption(" · ".join(f"{k} {v}" for k, v in sorted(by_pool.items())) +
                       (f" · since {(_stats['since'] or '')[:10]}" if _stats["since"] else ""))
        else:
            st.caption("Empty — it fills as questions are asked. Cached documents "
                       "are what answers a question when the API cannot be reached.")

        _recent = _db.recent_runs(limit=8)
        if _recent:
            with st.expander(f"🕘 Last {len(_recent)} question(s)"):
                for r in _recent:
                    flag = " · offline" if r.offline else ""
                    st.markdown(f"**{r.query}**")
                    st.caption(f"{r.ts[:16].replace('T', ' ')} · "
                               f"{r.n_documents} document(s){flag}")
                    if st.button("Ask again", key=f"again_{r.run_id}",
                                 use_container_width=True):
                        st.session_state["query_input"] = r.query

# ── MAIN UI ───────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🤖 Multi-Agent RAG System — Software Ecosystem Monitor</h1>
    <p>Adaptive Multi-Agent RAG Architecture · University of the Pacific · releasetrain.io</p>
    <p style="font-size:0.9rem; opacity:0.8">
        4 agents · Live APIs · Llama 3.1 · RLAIF feedback · Self-improving
    </p>
</div>
""", unsafe_allow_html=True)

# Query input
query = st.text_input(
    "Ask about any software update, security vulnerability, or release:",
    value=st.session_state.get("query_input", ""),
    placeholder='e.g. "Any critical Linux updates today?" or "What bugs were fixed in Chrome?"',
    key="main_query"
)

col1, col2, col3 = st.columns([2, 1, 1])
with col1:
    run_btn = st.button("🚀 Run Single Agent" if single_mode
                        else "🚀 Run Multi-Agent Pipeline",
                        type="primary", use_container_width=True)
with col2:
    if st.button("🔁 Clear", use_container_width=True):
        st.session_state["query_input"] = ""
        st.rerun()

# ── PIPELINE EXECUTION ────────────────────────────────────

if run_btn and query and single_mode:
    # ── SINGLE-AGENT BASELINE ─────────────────────────────
    # Rendered before the pipeline branch and returning early: the sections
    # below report what the coordinating agents did, and this arm has none of
    # them. Showing their headings with "n/a" underneath would suggest the
    # baseline attempted the work and failed at it.
    st.markdown("---")
    with st.spinner("🤖 Single agent — retrieve, then answer..."):
        sa = run_single_agent(query, top_k=result_limit)

    st.markdown("### 🤖 Single Agent (baseline)")
    st.caption(f"Arm `{sa['arm']}`" + (f" · model `{sa['model']}`" if sa["model"]
               else " · no model reachable, so the deterministic template "
                    "rendering ran instead of prose synthesis")
               + f" · {sa['elapsed']}s")
    st.info("**Raw question → retriever → one answer.** No temporal grounding, "
            "no vendor or intent detection, no query rewriting, no CVE agent, "
            "no RLAIF evaluator, no survey weighting, no yes/no tally. This is "
            "the arm the paper compares against, run on your question.")

    st.markdown("#### ✅ Answer")
    st.success(sa["answer"] or "_(the baseline returned nothing)_")

    docs = sa.get("docs") or []
    with st.expander(f"📄 Documents it retrieved ({len(docs)})"):
        if not docs:
            st.caption("None — the raw query matched nothing.")
        for d in docs:
            title = d.get("title") or d.get("product") or "(untitled)"
            src = d.get("source") or d.get("kind") or "?"
            st.markdown(f"• **{title}**  ·  `{src}`")
            if d.get("url"):
                st.caption(d["url"])

    st.caption("Switch **Answering mode** in the sidebar to run the same "
               "question through the multi-agent pipeline and compare.")

elif run_btn and query:

    # Pipeline steps display
    if show_pipeline:
        st.markdown("---")
        st.markdown("### 🧠 Manager Agent — Think & Plan")
        step_col0, step_col1, step_col2, step_col3, step_col4 = st.columns(5)
        with step_col0:
            st.markdown("""<div class="agent-card">
                <b>Step 0</b><br>📅 Temporal Grounder<br><small>rule-based, offline</small>
            </div>""", unsafe_allow_html=True)
        with step_col1:
            st.markdown("""<div class="agent-card">
                <b>Step 1</b><br>🔄 Query Rewriter<br><small>Llama 3.1 local</small>
            </div>""", unsafe_allow_html=True)
        with step_col2:
            st.markdown("""<div class="agent-card">
                <b>Step 2</b><br>💬 Community Agent<br><small>Reddit Live API</small>
            </div>""", unsafe_allow_html=True)
        with step_col3:
            st.markdown("""<div class="agent-card">
                <b>Step 3</b><br>📦 Release Notes Agent<br><small>Releases Live API</small>
            </div>""", unsafe_allow_html=True)
        with step_col4:
            st.markdown("""<div class="agent-card">
                <b>Step 4</b><br>🔐 CVE Agent<br><small>Security Live API</small>
            </div>""", unsafe_allow_html=True)
        st.markdown("---")

    # Run the pipeline
    results = run_pipeline(query, show_steps=show_pipeline, limit=result_limit,
                           yesno_on=yesno_on, unclear_as_no=unclear_as_no,
                           survey_on=survey_on)

    # ── TEMPORAL GROUNDING RESULT ─────────────────────────
    tr = results["temporal"]
    st.markdown("### 📅 Temporal Grounder Agent")
    if tr is not None and tr.changed:
        tg1, tg2 = st.columns(2)
        with tg1:
            st.info(f"**As asked:** {tr.original}")
        with tg2:
            st.success(f"**Grounded:** {tr.query}")
        st.caption(f"Resolved {tr.describe()} — relative words are rewritten to "
                   f"absolute dates before retrieval, because no document "
                   f"contains the word “today”, only a date.")
    else:
        st.caption("No relative time expression in this query — nothing to ground. "
                   "(Version words like “latest” are left alone on purpose: they "
                   "are ordinal over releases, not a date.)")

    # ── FEED OUTAGES ──────────────────────────────────────
    # Named explicitly. The alternative this replaced was a document whose
    # title was the exception text, which the answer then cited as a source.
    if results.get("errors"):
        for e in results["errors"]:
            st.error(f"**{e['agent']} feed unreachable** — {e['error']}. "
                     "No documents from this feed are included below, and "
                     "nothing is cited from it.")

    # ── VENDOR + INTENT GROUNDING RESULT ──────────────────
    gq = results.get("grounding")
    if gq is not None:
        st.markdown("### 🏷 Vendor & Intent Grounder")
        vg1, vg2 = st.columns(2)
        with vg1:
            if gq.vendors:
                st.success("**Products:** " + ", ".join(
                    f"“{v.matched}” → `{v.name}`" for v in gq.vendors))
            else:
                st.warning("**Products:** none matched the catalog — "
                           "retrieval is not vendor-scoped for this question.")
        with vg2:
            if gq.intent and gq.intent.confident:
                st.success(f"**Intent:** {gq.intent.describe()}")
            else:
                st.warning(f"**Intent:** {gq.intent.describe() if gq.intent else 'not classified'}")
        if gq.rewritten != gq.original:
            st.info(f"**Question as grounded:** {gq.rewritten}")
        excluded = results.get("advisories_excluded", 0)
        if excluded:
            st.caption(
                f"{excluded} CVE advisory row(s) excluded from the release pool. "
                "A CVE record's version field is the *affected* version, not a "
                "version that shipped — citing one as a release is what produced "
                "answers like “Linux v25.642087.0”.")
        elif gq.intent and gq.intent.label == "security":
            st.caption("Security question — advisories are kept and cited as "
                       "advisories, named by their CVE id rather than by the "
                       "affected-version string.")
        else:
            # Reached when no intent was confident enough to route on. Saying
            # "security question" here contradicted the line directly above it,
            # which had just reported no clear intent.
            st.caption("No intent was confident enough to narrow the search, so "
                       "every source is searched and advisories are cited as "
                       "advisories rather than as releases.")
        if gq.needs_clarification:
            st.error("No product and no clear intent were found in this "
                     "question. The answer below is drawn from an unscoped "
                     "search — naming a product would make it specific.")

    # ── QUERY REWRITING RESULT ────────────────────────────
    st.markdown("### 🔄 Query Rewriter Agent")
    rw_col1, rw_col2 = st.columns(2)
    with rw_col1:
        st.info(f"**Grounded input:** {results['grounded_query']}")
    with rw_col2:
        rw = results.get("rewrite")
        text = results['rewritten_query'] or results['original_query']
        if rw is not None and rw.mode == "llm":
            st.success(f"**Rewritten** by {rw.model}: {text}")
        elif rw is not None:
            # Never shown as model output. On a host with no reachable Ollama
            # -- Streamlit Community Cloud, for one -- this is every run, and
            # the heading above still reads "Llama 3.1 local".
            st.warning(f"**Rewritten** by rule: {text}")
            st.caption(f"Rule-based keyword expansion — {rw.note}. "
                       "The rewrite is blunter than a model's; retrieval still "
                       "runs on the grounded product term alongside it.")
        else:
            st.success(f"**Rewritten:** {text}")
    fetched_on = results.get("release_phrasings") or results.get("fetch_phrasings", [])
    if len(fetched_on) > 1:
        st.caption("Fetched on every phrasing and unioned — " +
                   " · ".join(f"“{p}”" for p in fetched_on) +
                   ". The plain phrasing and the product term find the documents; "
                   "the dated one lets the window rank them.")

    # ── YES/NO CONSENSUS ──────────────────────────────────
    # Shown above the evaluator because for this shape of question it *is*
    # the answer, and a paragraph synthesised underneath it is elaboration.
    yn = results.get("yesno")
    if yn is not None:
        st.markdown("### ✅ Yes/No Consensus")
        line = yesno.verdict_line(yn)
        (st.success if yn["answered"] else st.warning)(f"**{line}**")
        st.caption(f"Counted off the comments of “{yn['thread']['title']}” "
                   f"(r/{yn['thread'].get('subreddit','')}) — one vote per commenter, "
                   f"the person who asked excluded.")
        if yn["thread"].get("url"):
            st.caption(f"🔗 {yn['thread']['url']}")
        if yn["asker_report"]:
            st.caption(f"The asker's own report: “{yn['asker_report'][:200]}”")
        with st.expander(f"Show the {len(yn['votes'])} comment(s) behind this count"):
            for v in yn["votes"]:
                icon = {"yes": "🟥", "no": "🟩", "unclear": "⬜"}[v["stance"]]
                st.markdown(f"{icon} **{v['stance'].upper()}** — {v['body'][:300]}")
                if v["url"]:
                    st.caption(v["url"])
        st.markdown("---")

    # ── RLAIF EVALUATION METRICS ──────────────────────────
    st.markdown("### 📊 RLAIF Evaluator")
    ev = results["evaluation"]
    sv = ev.get("survey", {})
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Quality Score", f"{ev['quality']:.2f}/1.0",
              delta=(f"{ev['quality'] - ev['quality_base']:+.2f} vs. count only"
                     if ev.get("survey_on") else None))
    m2.metric("RLAIF Signal", "✅ Positive" if ev["signal"]=="positive" else "⚠️ Retry")
    m3.metric("User-Priority Fit", f"{sv.get('score', 0):.2f}/1.0")
    m4.metric("Community Posts", ev["community_count"])
    m5.metric("Release Notes", ev["release_count"])
    m6.metric("CVE Results", ev["cve_count"])

    # ── SURVEY-INFORMED PRIORITIES ────────────────────────
    if sv:
        n = sv["n"]
        if ev.get("survey_on"):
            st.caption(f"Quality blends retrieval volume with user-priority fit "
                       f"(0.7 / 0.3). Count alone would score {ev['quality_base']:.2f}.")
        else:
            st.caption(f"Survey off — quality is retrieval volume alone. The fit "
                       f"against {n} respondents' priorities is still reported, "
                       f"it just does not move the score.")
        cov = ", ".join(f"{c['label']} ({c['respondents']}/{n})" for c in sv["covered"])
        miss = ", ".join(f"{m['label']} ({m['respondents']}/{n})" for m in sv["missing"])
        if cov:
            st.success(f"**Speaks to:** {cov}")
        if miss:
            st.warning(f"**Says nothing about:** {miss}")
        with st.expander(f"What the {n} surveyed users said they care about"):
            st.caption("Counts are respondents who raised the priority — by "
                       "ticking it, writing about it, or both. Read from "
                       "`data/SoftwareUpdateSurvey.csv` on every run.")
            for pr in survey.priorities():
                hit = any(c["key"] == pr["key"] for c in sv["covered"])
                matched = next((", ".join(c["matched"]) for c in sv["covered"]
                                if c["key"] == pr["key"]), "")
                st.markdown(f"{'🟢' if hit else '⚪️'} **{pr['label']}** — "
                            f"{pr['respondents']}/{n} respondents "
                            f"({pr['share']:.0%})"
                            + (f" · matched on _{matched}_" if matched else ""))
                if pr["quote"]:
                    st.caption(f"“{pr['quote'][:240]}”")

    timing = results["timing"]
    st.caption(f"⏱ Timing — Temporal: {timing.get('temporal',0)}s | Rewriter: {timing.get('rewriter',0)}s | Community: {timing.get('community',0)}s | Releases: {timing.get('releases',0)}s | CVE: {timing.get('cve',0)}s")

    st.markdown("---")

    # ── RESULTS TABS ──────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        # The release tab counted advisories as releases, so a pool of four NVD
        # records and one kernel read as "Release Notes (5)" while the answer
        # below it said one release. Both numbers were right about different
        # things; only the label was wrong.
        f"📦 Releases ({_n_shipped(results['releases'])})"
        + (f" + {len(results['releases']) - _n_shipped(results['releases'])} advisory"
           if len(results['releases']) > _n_shipped(results['releases']) else ""),
        f"💬 Community Feedback ({len(results['community'])})",
        f"🔐 Security Discussion ({len(results['cve'])})",
    ])

    # Release Notes Tab
    with tab1:
        st.markdown("**Live software releases from releasetrain.io/api/v/**")
        if tr is not None and tr.window and results["releases"]:
            inside = sum(1 for r in results["releases"]
                         if matches_window(r.get("date", ""), tr) is True)
            st.caption(f"{inside} of {len(results['releases'])} shown releases fall "
                       f"inside {tr.window[0]} … {tr.window[1]}. Out-of-window results "
                       f"are kept and ranked last rather than dropped, so a quiet day "
                       f"still returns something to read.")
        if results["releases"]:
            for r in results["releases"]:
                is_security = "SECURITY" in r.get("security", [])
                has_breaking = len(r.get("breaking", [])) > 0
                badge = "🔴 SECURITY" if is_security else ("🟡 BREAKING" if has_breaking else "🟢 UPDATE")
                # Whether this release actually falls in the asked-about window.
                # None = no window asked for, or an unparseable date: shown as
                # nothing rather than as a miss.
                in_win = matches_window(r.get("date", ""), tr) if tr is not None else None
                win_badge = "" if in_win is None else (" 📅 in window" if in_win else " ⏳ outside window")

                with st.expander(f"{badge} {r['product']} v{r['version']} — {r['date']}{win_badge}"):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.markdown(f"**Release Notes:** {r['notes'] or 'No notes available'}")
                        if r.get("breaking"):
                            st.warning(f"⚠️ Breaking changes: {', '.join(r['breaking'])}")
                        if r.get("security") and r["security"] != ["UNKNOWN"]:
                            st.error(f"🔐 Security type: {', '.join(r['security'])}")
                    with col2:
                        st.markdown(f"**Channel:** {r['channel']}")
                        if r.get("url"):
                            st.markdown(f"[View on GitHub]({r['url']})")
        else:
            st.info("No release notes found for this query.")

    # Community Feedback Tab
    with tab2:
        st.markdown("**Live Reddit community feedback from releasetrain.io**")
        if results["community"]:
            for post in results["community"]:
                sentiment_class = "positive" if post["sentiment"]=="Positive" else "negative" if post["sentiment"]=="Negative" else "neutral"
                icon = "🟢" if post["sentiment"]=="Positive" else "🔴" if post["sentiment"]=="Negative" else "🟡"

                with st.expander(f"{icon} {post['title'][:80]}"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Subreddit", f"r/{post['subreddit']}")
                    col2.metric("Score", post["score"])
                    col3.metric("Date", post["date"])

                    tags = []
                    if post.get("is_cve"): tags.append("🔐 CVE")
                    if post.get("is_update"): tags.append("📦 Update")
                    if tags: st.markdown(" ".join(tags))
                    if post.get("url"): st.markdown(f"[View on Reddit]({post['url']})")
        else:
            st.info("No community feedback found for this query.")

    # CVE Tab
    with tab3:
        st.markdown("**Security vulnerabilities from releasetrain.io CVE feed**")
        if results["cve"]:
            for cve in results["cve"]:
                with st.expander(f"🔐 {cve['title'][:80]}"):
                    col1, col2 = st.columns(2)
                    col1.metric("Subreddit", f"r/{cve['subreddit']}")
                    col2.metric("Date", cve["date"])
                    if cve.get("tags"): st.markdown(f"**Tags:** {', '.join(cve['tags'])}")
                    if cve.get("url"): st.markdown(f"[View post]({cve['url']})")
        else:
            st.info("No CVE results found. Try adding 'CVE' or a specific version to your query.")

    # Raw data
    if show_raw:
        with st.expander("🔍 Raw API response data"):
            # `temporal` holds a dataclass, which st.json cannot serialise;
            # show its resolved fields instead of dropping the step from view.
            raw = dict(results)
            raw["temporal"] = {
                "original": tr.original, "grounded": tr.query,
                "resolved": [{"matched": a, "as": b} for a, b in tr.terms],
                "window": [str(tr.start), str(tr.end)] if tr.window else None,
            } if tr is not None else None
            # Same reason: GroundedQuestion is a dataclass holding further
            # dataclasses. Show what it decided, not the object.
            raw["grounding"] = {
                "rewritten": gq.rewritten,
                "vendors": gq.vendor_names,
                "intent": gq.intent.label if gq.intent else None,
                "intent_scores": gq.intent.scores if gq.intent else None,
                "citable_kinds": list(gq.citable_kinds),
                "retrieval_phrasings": gq.retrieval_phrasings,
                "needs_clarification": gq.needs_clarification,
            } if gq is not None else None
            _rw = results.get("rewrite")
            raw["rewrite"] = {"query": _rw.query, "mode": _rw.mode,
                              "model": _rw.model, "note": _rw.note} \
                if _rw is not None else None
            st.json(raw)

    # ── FINAL GROUNDED ANSWER ─────────────────────────────
    # The Answer Presenter agent turns the retrieved documents into one
    # readable paragraph and cites each claim in brackets. It reuses the
    # eval harness's provider layer, so the presenting model is configurable
    # (PRESENTER_MODEL in Streamlit secrets or the environment); with no model
    # reachable it composes the same shape by rule and says so, rather than
    # dressing rule-based text up as model output.
    st.markdown("---")
    st.markdown("### ✅ Final Answer")

    window_note = ""
    if tr is not None and tr.window:
        a, b = tr.window
        window_note = (a.strftime("%b %d, %Y") if a == b
                       else f'{a.strftime("%b %d, %Y")} to {b.strftime("%b %d, %Y")}')

    with st.spinner("🧾 Answer Presenter Agent — writing a cited paragraph..."):
        t0 = time.time()
        presented = present_answer(
            results["original_query"], results,
            model_spec=presenter_spec(), window_note=window_note,
            per_kind=result_limit,
        )
        present_secs = round(time.time() - t0, 1)

    st.success(presented.text)

    # The roster now describes this run: which feeds answered, whether the
    # rewrite came from a model, how many advisories were separated out.
    agent_status_slot.markdown(_agent_table(results, presented))

    src_label = (f"Presented by {presented.model}" if presented.mode == "llm"
                 else f"Presented rule-based ({presented.note})")
    st.caption(f"{src_label} · {len(presented.evidence)} evidence item(s) cited · {present_secs}s")

    if presented.evidence:
        with st.expander("🔗 Evidence behind the bracketed citations"):
            for e in presented.evidence:
                line = f"**[{e.label}]** — {e.title}"
                if e.url:
                    line += f" · [open source]({e.url})"
                st.markdown(line)

    # ── LOG THE RUN ───────────────────────────────────────
    # Written after the answer exists, so the stored row is the whole run --
    # question, phrasings, retrieved documents in rank order, and which of them
    # the answer actually cited. `record_run` swallows its own failures and
    # returns None; a store that cannot write must not cost the user an answer
    # already on screen.
    #
    # A run is marked offline when any shown document came from the store
    # rather than the endpoint. Cache-served rows carry `_last_seen`, which a
    # freshly fetched row does not, so the flag is read off the documents
    # instead of guessed from an exception that never reached this scope.
    _db_run = get_store()
    if _db_run is not None:
        _served = (results["releases"] + results["community"] + results["cve"])
        _offline = any("_last_seen" in d for d in _served if isinstance(d, dict))
        _run_id = _db_run.record_run(
            dict(results,
                 cited_keys=[e.url for e in presented.evidence if e.url]),
            answer=presented.text, offline=_offline)
        if _offline:
            st.warning("Some sources were unreachable — the documents above "
                       "were served from the local store, retrieved during an "
                       "earlier run. Dates on them are release dates, not "
                       "retrieval dates.")
        if _run_id is not None:
            st.caption(f"Logged as run #{_run_id} in the local store.")

elif run_btn and not query:
    st.warning("Please enter a query first.")

# ── FOOTER ────────────────────────────────────────────────
st.markdown("---")
st.markdown("""
<div style="text-align:center; color:#888; font-size:0.85rem;">
    Multi-Agent RAG System · Adaptive Multi-Agent RAG Architecture · University of the Pacific · 2026<br>
    Shradha Devendra Pujari · Dr. Solomon Berhe · releasetrain.io
</div>
""", unsafe_allow_html=True)
