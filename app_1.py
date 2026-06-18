"""
Multi-Agent RAG System — Adaptive Multi-Agent RAG Architecture
=============================================
Streamlit web app for software ecosystem monitoring.
Uses 4 live releasetrain.io API endpoints.

Agents:
  1. Community Agent    → reddit/query/positive
  2. Release Notes Agent → /api/v/
  3. CVE Agent          → reddit/query/cve
  4. Query Rewriter     → Llama 3.1 via Ollama (local)

Run:
    pip install streamlit requests
    streamlit run app.py

University of the Pacific — Agentic AI Research — 2026
"""

import streamlit as st
import requests
import json
import urllib.request
import time
from datetime import datetime

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

# ── AGENT 1: QUERY REWRITER ──────────────────────────────

def rewrite_query(query: str) -> str:
    """Calls Llama 3.1 locally to rewrite the query for better retrieval."""
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
            return json.loads(r.read()).get("response", "").strip()
    except Exception:
        # Fallback rule-based rewriting
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

# ── AGENT 2: COMMUNITY AGENT ─────────────────────────────

def fetch_community_feedback(query: str, limit: int = 5) -> list:
    """Fetches community Reddit feedback from releasetrain.io."""
    try:
        resp = requests.get(
            REDDIT_POSITIVE_API,
            params={"q": query, "limit": limit},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            posts = data.get("data", [])
            return [{
                "title":      p.get("title", ""),
                "subreddit":  p.get("subreddit", ""),
                "url":        p.get("url", ""),
                "score":      p.get("score", 0),
                "sentiment":  "Positive" if p.get("metadata", {}).get("predicted", {}).get("positiveScore", 0) > 0.5 else "Neutral",
                "date":       p.get("created_utc", "")[:10],
                "is_cve":     p.get("isAboutCve", False),
                "is_update":  p.get("isAboutLatestUpdate", False),
            } for p in posts[:limit]]
    except Exception as e:
        return [{"title": f"API unavailable: {e}", "subreddit": "", "url": "", "score": 0, "sentiment": "Neutral", "date": "", "is_cve": False, "is_update": False}]
    return []

# ── AGENT 3: RELEASE NOTES AGENT ─────────────────────────

def fetch_release_notes(query: str, limit: int = 5) -> list:
    """Fetches live software release notes from releasetrain.io."""
    try:
        resp = requests.get(
            RELEASES_API,
            params={"q": query, "limit": limit},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            versions = data.get("versions", [])
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
            } for v in versions[:limit]]
    except Exception as e:
        return [{"product": f"API unavailable: {e}", "version": "", "date": "", "notes": "", "channel": "", "url": "", "security": [], "breaking": [], "is_cve": False}]
    return []

# ── AGENT 4: CVE AGENT ───────────────────────────────────

def fetch_cve_data(query: str, limit: int = 5) -> list:
    """Fetches CVE security vulnerability data from releasetrain.io."""
    try:
        resp = requests.get(
            CVE_API,
            params={"q": query, "limit": limit},
            timeout=10
        )
        if resp.status_code == 200:
            data = resp.json()
            posts = data.get("data", [])
            return [{
                "title":     p.get("title", ""),
                "subreddit": p.get("subreddit", ""),
                "url":       p.get("url", ""),
                "date":      p.get("created_utc", "")[:10],
                "score":     p.get("score", 0),
                "tags":      p.get("tags", []),
            } for p in posts[:limit]]
    except Exception as e:
        return [{"title": f"CVE API unavailable: {e}", "subreddit": "", "url": "", "date": "", "score": 0, "tags": []}]
    return []

# ── RLAIF EVALUATOR ──────────────────────────────────────

def evaluate_results(community: list, releases: list, cve: list, query: str) -> dict:
    """Scores result quality and generates RLAIF signal."""
    total   = len(community) + len(releases) + len(cve)
    quality = min(total / 15.0, 1.0)
    signal  = "positive" if quality >= 0.3 else "negative"

    # Count relevant results
    relevant = sum(1 for r in releases if any(
        w in r.get("notes", "").lower() + r.get("product", "").lower()
        for w in query.lower().split()
    ))

    return {
        "quality":        round(quality, 2),
        "signal":         signal,
        "total_results":  total,
        "community_count": len(community),
        "release_count":  len(releases),
        "cve_count":      len(cve),
        "relevant":       relevant,
    }

# ── MANAGER AGENT — ORCHESTRATOR ─────────────────────────

def run_pipeline(query: str, show_steps: bool = True) -> dict:
    """Main orchestrator — runs all 4 agents and returns results."""
    results = {
        "original_query":  query,
        "rewritten_query": "",
        "community":       [],
        "releases":        [],
        "cve":             [],
        "evaluation":      {},
        "timing":          {},
    }

    # Step 1 — Query Rewriter
    if show_steps:
        with st.spinner("🔄 Query Rewriter Agent — Llama 3.1 rewriting query..."):
            t0 = time.time()
            rewritten = rewrite_query(query)
            results["rewritten_query"] = rewritten
            results["timing"]["rewriter"] = round(time.time()-t0, 1)

    # Step 2 — Community Agent
    if show_steps:
        with st.spinner("💬 Community Agent — fetching Reddit feedback..."):
            t0 = time.time()
            results["community"] = fetch_community_feedback(rewritten or query)
            results["timing"]["community"] = round(time.time()-t0, 1)

    # Step 3 — Release Notes Agent
    if show_steps:
        with st.spinner("📦 Release Notes Agent — fetching live releases..."):
            t0 = time.time()
            results["releases"] = fetch_release_notes(rewritten or query)
            results["timing"]["releases"] = round(time.time()-t0, 1)

    # Step 4 — CVE Agent
    if show_steps:
        with st.spinner("🔐 CVE Agent — fetching security vulnerabilities..."):
            t0 = time.time()
            results["cve"] = fetch_cve_data(query)
            results["timing"]["cve"] = round(time.time()-t0, 1)

    # Step 5 — RLAIF Evaluator
    results["evaluation"] = evaluate_results(
        results["community"], results["releases"],
        results["cve"], query
    )

    return results

# ── SIDEBAR ───────────────────────────────────────────────

with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/en/b/bb/University_of_the_Pacific_seal.svg", width=80)
    st.markdown("### Multi-Agent RAG System")
    st.markdown("**Adaptive Multi-Agent RAG Architecture**")
    st.markdown("University of the Pacific · 2026")
    st.divider()

    st.markdown("#### 🤖 Active Agents")
    st.markdown("""
    | Agent | Status |
    |-------|--------|
    | 🔄 Query Rewriter | Llama 3.1 |
    | 💬 Community | Live API |
    | 📦 Release Notes | Live API |
    | 🔐 CVE Security | Live API |
    """)
    st.divider()

    st.markdown("#### ⚙️ Settings")
    result_limit = st.slider("Results per agent", 3, 10, 5)
    show_pipeline = st.toggle("Show pipeline steps", value=True)
    show_raw = st.toggle("Show raw API data", value=False)

    st.divider()
    st.markdown("#### 💡 Example queries")
    examples = [
        "Any critical Linux updates today?",
        "Critical software updates published today",
        "What bugs were fixed in Chrome recently?",
        "Any security vulnerabilities in Python?",
        "Latest Django release notes",
        "MacOS updates with negative community reaction",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["query_input"] = ex

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
    run_btn = st.button("🚀 Run Multi-Agent Pipeline", type="primary", use_container_width=True)
with col2:
    if st.button("🔁 Clear", use_container_width=True):
        st.session_state["query_input"] = ""
        st.rerun()

# ── PIPELINE EXECUTION ────────────────────────────────────

if run_btn and query:

    # Pipeline steps display
    if show_pipeline:
        st.markdown("---")
        st.markdown("### 🧠 Manager Agent — Think & Plan")
        step_col1, step_col2, step_col3, step_col4 = st.columns(4)
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
    results = run_pipeline(query, show_steps=show_pipeline)

    # ── QUERY REWRITING RESULT ────────────────────────────
    st.markdown("### 🔄 Query Rewriter Agent")
    rw_col1, rw_col2 = st.columns(2)
    with rw_col1:
        st.info(f"**Original:** {results['original_query']}")
    with rw_col2:
        st.success(f"**Rewritten:** {results['rewritten_query'] or results['original_query']}")

    # ── RLAIF EVALUATION METRICS ──────────────────────────
    st.markdown("### 📊 RLAIF Evaluator")
    ev = results["evaluation"]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Quality Score", f"{ev['quality']:.2f}/1.0")
    m2.metric("RLAIF Signal", "✅ Positive" if ev["signal"]=="positive" else "⚠️ Retry")
    m3.metric("Community Posts", ev["community_count"])
    m4.metric("Release Notes", ev["release_count"])
    m5.metric("CVE Results", ev["cve_count"])

    timing = results["timing"]
    st.caption(f"⏱ Timing — Rewriter: {timing.get('rewriter',0)}s | Community: {timing.get('community',0)}s | Releases: {timing.get('releases',0)}s | CVE: {timing.get('cve',0)}s")

    st.markdown("---")

    # ── RESULTS TABS ──────────────────────────────────────
    tab1, tab2, tab3 = st.tabs([
        f"📦 Release Notes ({len(results['releases'])})",
        f"💬 Community Feedback ({len(results['community'])})",
        f"🔐 CVE Security ({len(results['cve'])})",
    ])

    # Release Notes Tab
    with tab1:
        st.markdown("**Live software releases from releasetrain.io/api/v/**")
        if results["releases"]:
            for r in results["releases"]:
                is_security = "SECURITY" in r.get("security", [])
                has_breaking = len(r.get("breaking", [])) > 0
                badge = "🔴 SECURITY" if is_security else ("🟡 BREAKING" if has_breaking else "🟢 UPDATE")

                with st.expander(f"{badge} {r['product']} v{r['version']} — {r['date']}"):
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
            st.json(results)

    # ── FINAL GROUNDED ANSWER ─────────────────────────────
    st.markdown("---")
    st.markdown("### ✅ Final Answer")

    answer_parts = []

    if results["releases"]:
        security_releases = [r for r in results["releases"] if "SECURITY" in r.get("security",[])]
        if security_releases:
            answer_parts.append(f"🔐 **{len(security_releases)} security release(s) found:**")
            for r in security_releases[:3]:
                answer_parts.append(f"  • {r['product']} v{r['version']} ({r['date']}): {r['notes'][:100]}")
        else:
            answer_parts.append(f"📦 **{len(results['releases'])} release(s) found:**")
            for r in results["releases"][:3]:
                answer_parts.append(f"  • {r['product']} v{r['version']} ({r['date']})")

    if results["cve"]:
        answer_parts.append(f"\n🔐 **{len(results['cve'])} CVE discussion(s) in community:**")
        for c in results["cve"][:2]:
            answer_parts.append(f"  • {c['title'][:80]}")

    if results["community"]:
        neg = [p for p in results["community"] if p["sentiment"]=="Negative"]
        pos = [p for p in results["community"] if p["sentiment"]=="Positive"]
        if neg: answer_parts.append(f"\n⚠️ **{len(neg)} negative community reaction(s) detected**")
        if pos: answer_parts.append(f"\n✅ **{len(pos)} positive community post(s) found**")

    if not answer_parts:
        answer_parts = ["No specific results found. Try a different query or check the individual tabs above."]

    st.success("\n".join(answer_parts))

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
