"""
Multi-Agent RAG System — Adaptive Multi-Agent RAG Architecture
Streamlit App with Live releasetrain.io APIs
University of the Pacific · 2026
"""

import streamlit as st
import requests
import json
import urllib.request
import time

st.set_page_config(page_title="Multi-Agent RAG System", page_icon="🤖", layout="wide")

# ── LIVE API ENDPOINTS ────────────────────────────────────
REDDIT_API   = "https://releasetrain.io/api/reddit/query/positive"
RELEASES_API = "https://releasetrain.io/api/v/"
CVE_API      = "https://releasetrain.io/api/reddit/query/cve"
OLLAMA_API   = "http://localhost:11434/api/generate"

# ── AGENT 1: QUERY REWRITER (Llama 3.1 local) ────────────
def rewrite_query(query):
    payload = json.dumps({
        "model": "llama3.1",
        "prompt": f'Rewrite for software update search: "{query}" - return only rewritten query under 15 words:',
        "stream": False,
        "options": {"temperature": 0}
    }).encode()
    try:
        req = urllib.request.Request(
            OLLAMA_API, data=payload,
            headers={"Content-Type": "application/json"}, method="POST"
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read()).get("response", "").strip()
    except:
        return query

# ── AGENT 2: COMMUNITY AGENT (Reddit live API) ───────────
def fetch_community(query, limit=5):
    """
    API: releasetrain.io/api/reddit/query/positive
    Returns live Reddit posts about software updates.
    Fields: title, subreddit, url, score, created_utc,
            isAboutCve, isAboutLatestUpdate, versionList,
            metadata.predicted.positiveScore
    """
    try:
        r = requests.get(REDDIT_API, timeout=10)
        if r.status_code != 200:
            return []
        all_posts = r.json().get("data", [])
        # Filter by query terms against title + subreddit
        terms = set(query.lower().split())
        scored = []
        for p in all_posts:
            text = (p.get("title","") + " " + p.get("subreddit","")).lower()
            overlap = len(terms & set(text.split()))
            if overlap > 0:
                scored.append((overlap, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [p for _,p in scored[:limit]] if scored else all_posts[:limit]
        return [{
            "title":      p.get("title", ""),
            "subreddit":  p.get("subreddit", ""),
            "url":        p.get("url", ""),
            "score":      p.get("score", 0),
            "date":       p.get("created_utc", "")[:10],
            "is_cve":     p.get("isAboutCve", False),
            "is_update":  p.get("isAboutLatestUpdate", False),
            "versions":   p.get("versionList", []),
            "pos_score":  round(p.get("metadata",{}).get("predicted",{}).get("positiveScore",0), 3),
        } for p in results]
    except Exception as e:
        return [{"title": f"Error: {e}", "subreddit":"","url":"","score":0,"date":"","is_cve":False,"is_update":False,"versions":[],"pos_score":0}]

# ── AGENT 3: RELEASE NOTES AGENT (live releases API) ─────
def fetch_releases(query, limit=5):
    """
    API: releasetrain.io/api/v/
    Returns live software release notes.
    Fields: versionProductName, versionNumber, versionReleaseDate,
            versionReleaseNotes, versionReleaseChannel,
            versionSearchTags, versionUrl, classification
    No server-side filter — we filter client-side by versionSearchTags.
    """
    try:
        r = requests.get(RELEASES_API, timeout=10)
        if r.status_code != 200:
            return []
        all_versions = r.json().get("versions", [])
        terms = set(query.lower().split())
        scored = []
        for v in all_versions:
            tags = " ".join(v.get("versionSearchTags", []) + [v.get("versionProductName","")]).lower()
            notes = v.get("versionReleaseNotes","").lower()
            overlap = len(terms & set(tags.split()))
            note_match = sum(1 for t in terms if t in notes)
            total = overlap + note_match
            if total > 0:
                scored.append((total, v))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = [v for _,v in scored[:limit]] if scored else all_versions[:limit]
        return [{
            "product":   v.get("versionProductName", ""),
            "brand":     v.get("versionProductBrand", ""),
            "version":   v.get("versionNumber", ""),
            "date":      v.get("versionReleaseDate", ""),
            "notes":     v.get("versionReleaseNotes", "")[:250],
            "channel":   v.get("versionReleaseChannel", ""),
            "url":       v.get("versionUrl", ""),
            "tags":      v.get("versionReleaseTags", []),
            "security":  v.get("classification", {}).get("securityType", []),
            "breaking":  v.get("classification", {}).get("breakingType", []),
            "is_cve":    v.get("isCve", False),
        } for v in results]
    except Exception as e:
        return [{"product": f"Error: {e}", "brand":"","version":"","date":"","notes":"","channel":"","url":"","tags":[],"security":[],"breaking":[],"is_cve":False}]

# ── AGENT 4: CVE AGENT (live CVE API) ────────────────────
def fetch_cve(query, limit=5):
    """
    API: releasetrain.io/api/reddit/query/cve
    Returns CVE-related Reddit posts.
    Fields: title, subreddit, url, created_utc, author_description (CVE details)
    """
    try:
        r = requests.get(CVE_API, params={"q": query, "limit": limit}, timeout=10)
        if r.status_code != 200:
            return []
        posts = r.json().get("data", [])
        return [{
            "title":       p.get("title", ""),
            "subreddit":   p.get("subreddit", ""),
            "url":         p.get("url", ""),
            "date":        p.get("created_utc", "")[:10],
            "author":      p.get("author", ""),
            "description": (p.get("author_description","") or "")[:300],
            "score":       p.get("score", 0),
        } for p in posts[:limit]]
    except Exception as e:
        return [{"title": f"Error: {e}", "subreddit":"","url":"","date":"","author":"","description":"","score":0}]

# ── RLAIF EVALUATOR ──────────────────────────────────────
def rlaif_evaluate(community, releases, cve, query):
    total   = len(community) + len(releases) + len(cve)
    quality = round(min(total / 15.0, 1.0), 2)
    signal  = "✅ Positive" if quality >= 0.3 else "⚠️ Retry"
    return {"quality": quality, "signal": signal,
            "total": total, "community": len(community),
            "releases": len(releases), "cve": len(cve)}

# ── SIDEBAR ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🤖 Multi-Agent RAG System")
    st.markdown("**Adaptive Multi-Agent RAG**")
    st.markdown("University of the Pacific · 2026")
    st.divider()
    st.markdown("**🤖 Active Agents:**")
    st.markdown("🔄 Query Rewriter — Llama 3.1 local")
    st.markdown("💬 Community — reddit/query/positive")
    st.markdown("📦 Releases — /api/v/ (live)")
    st.markdown("🔐 CVE — reddit/query/cve")
    st.divider()
    st.markdown("**💡 Try these:**")
    examples = [
        "Any critical Linux updates today?",
        "Critical software updates published today",
        "Chrome bug fixes latest version",
        "Security vulnerabilities Python",
        "Django latest release notes",
        "Windows security patch",
        "CVE vulnerability nodejs",
    ]
    for ex in examples:
        if st.button(ex, use_container_width=True):
            st.session_state["q"] = ex
            st.rerun()

# ── MAIN UI ───────────────────────────────────────────────
st.title("🤖 Multi-Agent RAG System — Software Ecosystem Monitor")
st.caption("Adaptive Multi-Agent RAG · University of the Pacific · releasetrain.io Live APIs")

query = st.text_input(
    "Ask about any software update, release, or security vulnerability:",
    value=st.session_state.get("q", ""),
    placeholder='e.g. "Any critical Linux updates today?"'
)

run = st.button("🚀 Run Multi-Agent Pipeline", type="primary")

if run and query:

    # Step indicators
    c1,c2,c3,c4 = st.columns(4)
    c1.info("🔄 Step 1\nQuery Rewriter\nLlama 3.1")
    c2.info("💬 Step 2\nCommunity\nReddit API")
    c3.info("📦 Step 3\nRelease Notes\nLive API")
    c4.info("🔐 Step 4\nCVE Security\nLive API")
    st.markdown("---")

    # Run all agents
    with st.spinner("🔄 Query Rewriter — Llama 3.1 rewriting..."):
        t0 = time.time()
        rewritten = rewrite_query(query)
        t_rw = round(time.time()-t0, 1)

    with st.spinner("💬 Community Agent — fetching live Reddit posts..."):
        t0 = time.time()
        community = fetch_community(rewritten or query)
        t_co = round(time.time()-t0, 1)

    with st.spinner("📦 Release Notes Agent — fetching live releases..."):
        t0 = time.time()
        releases = fetch_releases(rewritten or query)
        t_re = round(time.time()-t0, 1)

    with st.spinner("🔐 CVE Agent — fetching live CVE data..."):
        t0 = time.time()
        cve = fetch_cve(query)
        t_cv = round(time.time()-t0, 1)

    # Show rewrite result
    col1, col2 = st.columns(2)
    col1.info(f"**Original:** {query}")
    col2.success(f"**Rewritten:** {rewritten or query}")

    # RLAIF metrics
    ev = rlaif_evaluate(community, releases, cve, query)
    st.markdown("### 📊 RLAIF Evaluator")
    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("Quality", f"{ev['quality']}/1.0")
    m2.metric("Signal", ev["signal"])
    m3.metric("Community", ev["community"])
    m4.metric("Releases", ev["releases"])
    m5.metric("CVE", ev["cve"])
    st.caption(f"⏱ Rewriter:{t_rw}s | Community:{t_co}s | Releases:{t_re}s | CVE:{t_cv}s")
    st.markdown("---")

    # Results tabs
    tab1, tab2, tab3 = st.tabs([
        f"📦 Release Notes ({len(releases)})",
        f"💬 Community ({len(community)})",
        f"🔐 CVE ({len(cve)})"
    ])

    with tab1:
        st.caption("Live from releasetrain.io/api/v/")
        if releases:
            for r in releases:
                sec = "SECURITY" in r.get("security", [])
                brk = len(r.get("breaking", [])) > 0
                cve_flag = r.get("is_cve", False)
                badge = "🔴 CVE" if cve_flag else ("🔴 SECURITY" if sec else ("🟡 BREAKING" if brk else "🟢"))
                label = f"{badge}  {r['product']} v{r['version']}  —  {r['date']}  [{r['channel']}]"
                with st.expander(label):
                    st.markdown(f"**Release Notes:**")
                    st.write(r["notes"] or "No notes available")
                    if r.get("breaking"):
                        st.warning(f"⚠️ Breaking: {', '.join(r['breaking'])}")
                    if r.get("security") and r["security"] != ["UNKNOWN"]:
                        st.error(f"🔐 Security: {', '.join(r['security'])}")
                    if r.get("tags"):
                        st.caption(f"Tags: {', '.join(r['tags'])}")
                    if r.get("url"):
                        st.markdown(f"[View on GitHub ↗]({r['url']})")
        else:
            st.info("No matching releases found. Try broader terms like 'linux', 'python', 'chrome'.")

    with tab2:
        st.caption("Live from releasetrain.io/api/reddit/query/positive")
        if community:
            for p in community:
                icon = "🔐" if p["is_cve"] else ("📦" if p["is_update"] else "💬")
                with st.expander(f"{icon}  {p['title'][:85]}"):
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Subreddit", f"r/{p['subreddit']}")
                    col2.metric("Score", p["score"])
                    col3.metric("Date", p["date"])
                    if p.get("versions"):
                        st.caption(f"Versions mentioned: {', '.join(p['versions'])}")
                    if p.get("pos_score"):
                        st.caption(f"Positive score: {p['pos_score']}")
                    if p.get("url"):
                        st.markdown(f"[View on Reddit ↗]({p['url']})")
        else:
            st.info("No community posts found.")

    with tab3:
        st.caption("Live from releasetrain.io/api/reddit/query/cve")
        if cve:
            for c in cve:
                with st.expander(f"🔐  {c['title'][:85]}"):
                    col1, col2 = st.columns(2)
                    col1.metric("Subreddit", f"r/{c['subreddit']}")
                    col2.metric("Date", c["date"])
                    if c.get("description"):
                        st.markdown(f"**Details:**")
                        st.write(c["description"])
                    if c.get("url"):
                        st.markdown(f"[View on Reddit ↗]({c['url']})")
        else:
            st.info("No CVE results. Try adding 'CVE' or a software name to your query.")

    # Final answer
    st.markdown("---")
    st.markdown("### ✅ Final Answer")
    parts = []
    if releases:
        sec_r = [r for r in releases if "SECURITY" in r.get("security",[])]
        if sec_r:
            parts.append(f"🔐 **{len(sec_r)} security release(s) found:**")
            for r in sec_r[:3]: parts.append(f"  • **{r['product']} v{r['version']}** ({r['date']}): {r['notes'][:120]}")
        else:
            parts.append(f"📦 **{len(releases)} release(s) found:**")
            for r in releases[:3]: parts.append(f"  • **{r['product']} v{r['version']}** ({r['date']})")
    if cve:
        parts.append(f"\n🔐 **{len(cve)} CVE discussion(s) in community:**")
        for c in cve[:2]: parts.append(f"  • {c['title'][:80]}")
    if community:
        parts.append(f"\n💬 **{len(community)} community post(s) found** across Reddit")
    if not parts:
        parts = ["No results found. Try: 'linux update', 'chrome bug', 'python security', or 'CVE'."]
    st.success("\n".join(parts))

elif run and not query:
    st.warning("Please enter a query.")

st.markdown("---")
st.caption("Multi-Agent RAG System · Adaptive Multi-Agent RAG Architecture · University of the Pacific · Shradha Devendra Pujari · Dr. Solomon Berhe · 2026")
