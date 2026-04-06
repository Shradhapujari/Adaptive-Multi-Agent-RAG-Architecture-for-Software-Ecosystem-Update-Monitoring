"""
Multi-Agent RAG Demo — with real Ollama LLM
============================================
Same architecture as v2 but Query Rewriter now uses
Llama 3.1 via Ollama for intelligent query rewriting.

Run:
    python multiagent_rag_v3.py          # interactive
    python multiagent_rag_v3.py demo     # all 3 demo queries
"""

import json, time, sys, urllib.request
from pathlib import Path

DATA_PATH = Path(__file__).parent / "data" / "enhanced_automated_sentiment_results.json"

# Live API endpoints
RELEASES_API = "https://releasetrain.io/api/v/"
REDDIT_API   = "https://releasetrain.io/api/reddit/query/positive"
CVE_API      = "https://releasetrain.io/api/reddit/query/cve"

SYNONYMS = {
    "linux":["linux","ubuntu","debian","kernel","fedora","redhat"],
    "security":["security","vulnerability","cve","patch","exploit","advisory"],
    "bug":["bug","defect","issue","error","crash","regression"],
    "fix":["fix","patch","resolve","resolved","hotfix","bugfix"],
    "update":["update","upgrade","release","version","changelog"],
    "critical":["critical","severe","high","urgent","important","major"],
    "python":["python","pip","pypi","cpython"],
    "chrome":["chrome","chromium","browser","google"],
    "windows":["windows","microsoft","win11","win10"],
    "macos":["macos","mac","apple","osx"],
    "linux":["linux","ubuntu","debian","kernel","fedora"],
    "nodejs":["nodejs","node","npm","javascript"],
    "grafana":["grafana","monitoring","dashboard","metrics"],
    "django":["django","python","web","framework"],
    "vscode":["vscode","editor","ide","microsoft"],
}

def expand_terms(query):
    terms = set(query.lower().split())
    expanded = set(terms)
    for t in terms:
        for base,syns in SYNONYMS.items():
            if t in syns or t==base: expanded.update(syns)
    return expanded

def fetch_live_releases(query, limit=5, min_overlap=2):
    try:
        import requests as req
        r = req.get(RELEASES_API, timeout=30)
        all_v = r.json().get("versions",[]) if r.status_code==200 else []
        exp = expand_terms(query)
        scored = []
        for v in all_v:
            txt = (" ".join(v.get("versionSearchTags",[])) + " " +
                   v.get("versionProductName","") + " " +
                   v.get("versionReleaseNotes","")).lower()
            overlap = sum(1 for t in exp if t in txt)
            if overlap >= min_overlap:
                scored.append((overlap, {
                    "title": f"{v.get('versionProductName')} v{v.get('versionNumber')} — {v.get('versionReleaseNotes','')[:80]}",
                    "subreddit": v.get("versionReleaseChannel","release"),
                    "sentiment": "Negative" if "SECURITY" in v.get("classification",{}).get("securityType",[]) else "Positive",
                    "score": overlap,
                    "divergence": 0.0,
                    "source": "releases",
                    "url": v.get("versionUrl",""),
                    "date": v.get("versionReleaseDate",""),
                }))
        scored.sort(key=lambda x:x[0], reverse=True)
        return [d for _,d in scored[:limit]]
    except Exception as e:
        return []

def fetch_live_reddit(query, limit=5):
    try:
        import requests as req
        r = req.get(REDDIT_API, timeout=15)
        all_p = r.json().get("data",[]) if r.status_code==200 else []
        exp = expand_terms(query)
        scored = []
        for p in all_p:
            txt = (p.get("title","") + " " + p.get("subreddit","")).lower()
            overlap = sum(1 for t in exp if t in txt)
            if overlap > 0:
                scored.append((overlap, {
                    "title": p.get("title",""),
                    "subreddit": p.get("subreddit",""),
                    "sentiment": "Positive" if p.get("metadata",{}).get("predicted",{}).get("positiveScore",0) > 0.5 else "Neutral",
                    "score": p.get("score",0),
                    "divergence": 0.0,
                    "source": "reddit_live",
                    "url": p.get("url",""),
                    "date": p.get("created_utc","")[:10],
                }))
        scored.sort(key=lambda x:x[0], reverse=True)
        return [d for _,d in scored[:limit]]
    except:
        return []

def fetch_live_cve(query, limit=3):
    try:
        import requests as req
        r = req.get(CVE_API, params={"q":query,"limit":limit}, timeout=30)
        posts = r.json().get("data",[]) if r.status_code==200 else []
        return [{
            "title": p.get("title",""),
            "subreddit": p.get("subreddit",""),
            "sentiment": "Negative",
            "score": p.get("score",0),
            "divergence": 0.5,
            "source": "cve",
            "url": p.get("url",""),
            "date": p.get("created_utc","")[:10],
            "detail": (p.get("author_description") or "")[:150],
        } for p in posts]
    except:
        return []

import xml.etree.ElementTree as ET

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GITHUB_TAGS_API = "https://api.github.com/search/repositories"

import xml.etree.ElementTree as ET

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GITHUB_TAGS_API = "https://api.github.com/search/repositories"

def fetch_google_news(query, limit=5):
    """Fetch real news articles from Google News RSS — verified press sources."""
    try:
        import requests as req
        r = req.get(
            GOOGLE_NEWS_RSS,
            params={"q": query + " software update security", "hl": "en", "gl": "US", "ceid": "US:en"},
            timeout=15
        )
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        results = []
        for item in items[:limit]:
            title  = item.find("title")
            link   = item.find("link")
            pubdate= item.find("pubDate")
            source = item.find("source")
            if title is not None:
                results.append({
                    "title":     title.text or "",
                    "subreddit": source.text if source is not None else "Google News",
                    "sentiment": "Negative" if any(w in (title.text or "").lower()
                                 for w in ["vulnerability","breach","hack","exploit","critical","attack"]) else "Neutral",
                    "score":     0,
                    "divergence": 0.0,
                    "source":    "google_news",
                    "url":       link.text if link is not None else "",
                    "date":      (pubdate.text or "")[:16] if pubdate is not None else "",
                })
        return results
    except Exception as e:
        return []

def fetch_github_releases(query, limit=4):
    """Fetch GitHub release info for software matching the query."""
    try:
        import requests as req
        # Extract main software name from query
        software_terms = [w for w in query.lower().split()
                         if len(w) > 3 and w not in
                         {"what","when","where","which","latest","update","release","version","security","patch","bug","fix"}]
        if not software_terms:
            return []
        search_term = software_terms[0]
        r = req.get(
            "https://api.github.com/search/repositories",
            params={"q": search_term, "sort": "updated", "per_page": 3},
            timeout=15
        )
        repos = r.json().get("items", [])
        results = []
        for repo in repos[:2]:
            # Get latest release for each repo
            owner = repo.get("owner", {}).get("login", "")
            name  = repo.get("name", "")
            try:
                rel_r = req.get(
                    f"https://api.github.com/repos/{owner}/{name}/releases/latest",
                    timeout=10
                )
                if rel_r.status_code == 200:
                    rel = rel_r.json()
                    results.append({
                        "title":     f"{name} {rel.get('tag_name','')} — {rel.get('name','')}",
                        "subreddit": "GitHub",
                        "sentiment": "Positive",
                        "score":     0,
                        "divergence": 0.0,
                        "source":    "github",
                        "url":       rel.get("html_url",""),
                        "date":      rel.get("published_at","")[:10],
                        "detail":    (rel.get("body","") or "")[:150],
                    })
            except:
                pass
        return results
    except Exception as e:
        return []


def fetch_google_news(query, limit=5):
    """Fetch real news articles from Google News RSS — verified press sources."""
    try:
        import requests as req
        r = req.get(
            GOOGLE_NEWS_RSS,
            params={"q": query + " software update security", "hl": "en", "gl": "US", "ceid": "US:en"},
            timeout=15
        )
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        results = []
        for item in items[:limit]:
            title  = item.find("title")
            link   = item.find("link")
            pubdate= item.find("pubDate")
            source = item.find("source")
            if title is not None:
                results.append({
                    "title":     title.text or "",
                    "subreddit": source.text if source is not None else "Google News",
                    "sentiment": "Negative" if any(w in (title.text or "").lower()
                                 for w in ["vulnerability","breach","hack","exploit","critical","attack"]) else "Neutral",
                    "score":     0,
                    "divergence": 0.0,
                    "source":    "google_news",
                    "url":       link.text if link is not None else "",
                    "date":      (pubdate.text or "")[:16] if pubdate is not None else "",
                })
        return results
    except Exception as e:
        return []

def fetch_github_releases(query, limit=4):
    """Fetch GitHub release info for software matching the query."""
    try:
        import requests as req
        # Extract main software name from query
        software_terms = [w for w in query.lower().split()
                         if len(w) > 3 and w not in
                         {"what","when","where","which","latest","update","release","version","security","patch","bug","fix"}]
        if not software_terms:
            return []
        search_term = software_terms[0]
        r = req.get(
            "https://api.github.com/search/repositories",
            params={"q": search_term, "sort": "updated", "per_page": 3},
            timeout=15
        )
        repos = r.json().get("items", [])
        results = []
        for repo in repos[:2]:
            # Get latest release for each repo
            owner = repo.get("owner", {}).get("login", "")
            name  = repo.get("name", "")
            try:
                rel_r = req.get(
                    f"https://api.github.com/repos/{owner}/{name}/releases/latest",
                    timeout=10
                )
                if rel_r.status_code == 200:
                    rel = rel_r.json()
                    results.append({
                        "title":     f"{name} {rel.get('tag_name','')} — {rel.get('name','')}",
                        "subreddit": "GitHub",
                        "sentiment": "Positive",
                        "score":     0,
                        "divergence": 0.0,
                        "source":    "github",
                        "url":       rel.get("html_url",""),
                        "date":      rel.get("published_at","")[:10],
                        "detail":    (rel.get("body","") or "")[:150],
                    })
            except:
                pass
        return results
    except Exception as e:
        return []


def load_docs():
    """Load local dataset as fallback only."""
    if DATA_PATH.exists():
        with open(DATA_PATH) as f:
            posts = json.load(f).get("all_analyzed_posts", [])
        return [{"title": p["title"], "subreddit": p["subreddit"],
                 "sentiment": p["title_sentiment"]["label"],
                 "score": p["score"], "divergence": p["metrics"]["sentiment_divergence"],
                 "source": "local"}
                for p in posts]
    return []

DOCS = load_docs()
W    = 58

def bar(c="─"): print(c * W)
def pause(): time.sleep(0.4)

# ─────────────────────────────────────────────────────────────
# OLLAMA HELPER — calls Llama 3.1 locally
# ─────────────────────────────────────────────────────────────

def call_llama(prompt: str) -> str:
    """Call Llama 3.1 via Ollama REST API running locally."""
    payload = json.dumps({
        "model": "llama3.1",
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0}
    }).encode()

    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result.get("response", "").strip()
    except Exception as e:
        return f"[Ollama error: {e}]"

# ─────────────────────────────────────────────────────────────
# AGENT 1 — QUERY REWRITER (now uses real Llama 3.1)
# ─────────────────────────────────────────────────────────────

class QueryRewriterAgent:
    name = "🔄  Query Rewriter Agent  (Llama 3.1 via Ollama)"

    def run(self, query: str) -> dict:
        print(f"\n  {self.name}")
        bar()
        print(f"  Purpose  : Real LLM detects semantic gap + rewrites query")
        print(f"  Model    : Llama 3.1 running locally via Ollama")
        print(f"  Input    : \"{query}\"")
        print(f"  Thinking ...")
        pause()

        prompt = f"""You are a search query rewriting expert for a software update research system.

A user asked: "{query}"

Your job:
1. Identify if the query is vague or uses shorthand
2. Rewrite it to match technical document vocabulary
3. Make it specific enough to find relevant software update posts

Rules:
- Keep it under 20 words
- Focus on: bug fixes, releases, changelogs, security patches, performance
- Return ONLY the rewritten query, nothing else

Rewritten query:"""

        rewritten = call_llama(prompt)

        # fallback if Ollama fails
        if rewritten.startswith("[Ollama error"):
            print(f"  ⚠️  Ollama unavailable — using rule-based fallback")
            rewritten = f"{query} software update bug fixes release notes changelog"

        print(f"  Output   : \"{rewritten[:70]}\"")
        return {"original": query, "rewritten": rewritten}

# ─────────────────────────────────────────────────────────────
# AGENT 2 — RETRIEVER (unchanged — searches real dataset)
# ─────────────────────────────────────────────────────────────

class RetrieverAgent:
    name = "📚  Retriever Agent"

    def run(self, rewritten_query: str, top_k: int = 4) -> list:
        print(f"\n  {self.name}")
        bar()
        print(f"  Purpose  : Live API search — Releases + Reddit + CVE")
        pause()

        # Fetch from all 5 verified sources simultaneously
        print(f"  Fetching : releasetrain.io/api/v/ ...")
        releases = fetch_live_releases(rewritten_query, limit=4)

        print(f"  Fetching : releasetrain.io/api/reddit/query/positive ...")
        reddit = fetch_live_reddit(rewritten_query, limit=3)

        print(f"  Fetching : releasetrain.io/api/reddit/query/cve ...")
        cve = fetch_live_cve(rewritten_query, limit=2)

        print(f"  Fetching : Google News RSS ...")
        news = fetch_google_news(rewritten_query, limit=3)

        print(f"  Fetching : GitHub Releases ...")
        github = fetch_github_releases(rewritten_query, limit=2)

        # Combine all verified sources
        results = releases + reddit + cve + news + github

        # Fallback to local if live APIs return nothing
        if not results:
            print(f"  Live APIs unavailable — using local dataset")
            query_terms = set(rewritten_query.lower().split())
            scored = sorted(
                [(len(query_terms & set((d["title"]+" "+d["subreddit"]).lower().split())), d)
                 for d in DOCS],
                key=lambda x: x[0], reverse=True
            )
            results = [d for s, d in scored if s > 0][:top_k] or DOCS[:top_k]

        print(f"  Found    : {len(results)} results | releases={len(releases)} reddit={len(reddit)} cve={len(cve)} news={len(news)} github={len(github)}")
        for i, doc in enumerate(results[:top_k], 1):
            icon = "🔴" if doc["sentiment"]=="Negative" else "🟢" if doc["sentiment"]=="Positive" else "🟡"
            src  = f"[{doc.get('source','?')}]"
            date = f" ({doc.get('date','')})" if doc.get('date') else ""
            print(f"    {i}. {icon} {src} {doc['title'][:55]}{date}")
        return results[:top_k]

# ─────────────────────────────────────────────────────────────
# AGENT 3 — EVALUATOR (unchanged — RLAIF scoring)
# ─────────────────────────────────────────────────────────────

class EvaluatorAgent:
    name = "📊  Evaluator Agent"

    def run(self, docs: list, original_query: str) -> dict:
        print(f"\n  {self.name}")
        bar()
        print(f"  Purpose  : Score retrieval quality (RLAIF) + generate answer")
        pause()

        query_terms = set(original_query.lower().split())
        quality     = round(min(len(query_terms & set(docs[0]["title"].lower().split()))
                                / max(len(query_terms), 1), 1.0), 2) if docs else 0.0
        signal      = "✅ positive" if quality >= 0.15 else "⚠️  negative — manager will retry"

        print(f"  Quality  : {quality:.2f} / 1.0")
        print(f"  RLAIF    : {signal}")
        pause()

        neg  = [d for d in docs if d["sentiment"] == "Negative"]
        pos  = [d for d in docs if d["sentiment"] == "Positive"]
        subs = list(set(d["subreddit"] for d in docs))

        from datetime import datetime as _dt
        verified_src = list(set(d.get('source','local') for d in docs))
        has_live = any(s in ['releases','reddit_live','cve','google_news','github'] for s in verified_src)
        has_live     = any(s in ['releases','reddit_live','cve'] for s in verified_src)
        confidence   = "HIGH" if quality >= 0.5 else "MEDIUM" if quality >= 0.3 else "LOW"
        verified_tag = "✅ VERIFIED from live releasetrain.io APIs" if has_live else "⚠️  From local dataset — may not reflect today's data"

        lines = []
        lines.append(f'Query: "{original_query}"')
        lines.append(f'Verified: {verified_tag}')
        lines.append(f'Confidence: {confidence} (quality={quality:.2f}) | Sources: {", ".join(verified_src)}')
        lines.append(f'Retrieved: {_dt.now().strftime("%Y-%m-%d %H:%M")}')
        lines.append("")

        if not docs:
            lines.append("  ❌ NO RESULTS FOUND for this query.")
            lines.append("  The system could not find verified information matching your question.")
            lines.append("  Suggestions:")
            lines.append("    • Try rephrasing — e.g. 'Linux kernel security patch' instead of 'Linux updates'")
            lines.append("    • Check releasetrain.io directly for latest releases")
            lines.append("    • Try a more specific version number or CVE ID")
        elif confidence == "LOW":
            lines.append("  ⚠️  LOW CONFIDENCE — Results found but may not directly answer your question.")
            lines.append("  Here are the closest matches found. Please verify independently:")
            lines.append("")
            for d in docs[:4]:
                icon = "🔴" if d["sentiment"]=="Negative" else "🟢"
                src  = d.get('source','?')
                date = f" ({d.get('date','')})" if d.get('date') else ''
                lines.append(f"  {icon} [{src}] {d['title'][:90]}{date}")
                if d.get('url'): lines.append(f"       🔗 {d['url']}")
            lines.append("")
            lines.append("  Alternative suggestions:")
            lines.append("    • Search CVE database: https://nvd.nist.gov")
            lines.append("    • Check vendor release notes directly")
        else:
            lines.append(f"  ✅ ANSWER — Based on {len(docs)} verified source(s):")
            lines.append("")
            if neg:
                lines.append(f"  🔴 CRITICAL/SECURITY ({len(neg)} item(s)):")
                for d in neg[:4]:
                    src  = d.get('source','?')
                    date = f" ({d.get('date','')})" if d.get('date') else ''
                    lines.append(f"    • [{src}] {d['title'][:90]}{date}")
                    if d.get('detail'): lines.append(f"      Detail: {d['detail'][:100]}")
                    if d.get('url'):    lines.append(f"      🔗 {d['url']}")
            if pos:
                lines.append(f"\n  🟢 UPDATES/RELEASES ({len(pos)} item(s)):")
                for d in pos[:3]:
                    src  = d.get('source','?')
                    date = f" ({d.get('date','')})" if d.get('date') else ''
                    lines.append(f"    • [{src}] {d['title'][:90]}{date}")
                    if d.get('url'): lines.append(f"      🔗 {d['url']}")
            lines.append("")
            src_str = ", ".join(verified_src)
            lines.append(f"  Data sourced from: {src_str} | releasetrain.io")
        return {"quality": quality, "signal": signal, "answer": "\n".join(lines)}

# ─────────────────────────────────────────────────────────────
# MANAGER AGENT — ORCHESTRATOR
# ─────────────────────────────────────────────────────────────

class ManagerAgent:
    name = "🧠  Manager Agent (Orchestrator)"

    def __init__(self):
        self.rewriter  = QueryRewriterAgent()
        self.retriever = RetrieverAgent()
        self.evaluator = EvaluatorAgent()

    def run(self, query: str) -> str:
        print(f"\n  {self.name}")
        bar()
        print(f"  Think & Plan:")
        print(f"    Step 1 → delegate to Query Rewriter Agent  (Llama 3.1)")
        print(f"    Step 2 → delegate to Retriever Agent")
        print(f"    Step 3 → delegate to Evaluator Agent (RLAIF)")
        print(f"    Step 4 → if quality low, trigger retry")

        rewrite = self.rewriter.run(query)
        docs    = self.retriever.run(rewrite["rewritten"])
        result  = self.evaluator.run(docs, query)

        if "negative" in result["signal"] and "retry" not in query:
            print(f"\n  Manager: RLAIF signal negative — retrying with broader query...")
            docs   = self.retriever.run(query + " software update release", top_k=4)
            result = self.evaluator.run(docs, query)

        return result["answer"]

# ─────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────

def show_why():
    print()
    bar("═")
    print("  WHY MULTI-AGENT? The core argument")
    bar("═")
    print("""
  SINGLE AGENT (the problem):
    → One model does everything
    → Gets confused mixing rewriting + retrieval + evaluation
    → No specialization = shallow, generic answers
    → If one thing fails, everything fails

  MULTI-AGENT (the solution):
    → Each agent has ONE job and does it well
    → Manager coordinates — like a research team lead
    → Rewriter uses real Llama 3.1 LLM (running on your Mac)
    → RLAIF evaluator catches bad results and retries
    → Transparent, explainable, extensible

  YOUR RESEARCH (6-phase roadmap):
    Phase 2  →  Query Rewriter Agent  (Llama 3.1 — live now!)
    Phase 3  →  Manager orchestration (CrewAI — next step)
    Phase 4  →  Retriever Agent       (FAISS + BGE-Large)
    Phase 5  →  Evaluator Agent       (RLAIF / Zero-HF)
    """)

DEMO_QUERIES = [
    "What bugs were fixed in the latest update?",
    "Which software releases got negative community reaction?",
    "Are there any security fixes in recent updates?",
]

def run_demo(query: str):
    print()
    bar("═")
    print(f"  📨  USER QUERY: \"{query}\"")
    bar("═")
    manager = ManagerAgent()
    answer  = manager.run(query)
    print()
    bar("═")
    print("  ✅  FINAL ANSWER")
    bar("═")
    print(answer)
    bar("═")

def interactive():
    print()
    bar("═")
    print("  Multi-Agent RAG Demo  —  releasetrain.io")
    print(f"  Dataset  : {len(DOCS)} Reddit posts about software updates")
    print(f"  LLM      : Llama 3.1 via Ollama (local, no API key)")
    bar("─")
    print("  Commands:")
    print("    'why'  — show why multi-agent matters (start here!)")
    print("    'demo' — run all 3 demo queries")
    print("    'exit' — quit")
    print("    or type any question")
    bar("═")

    while True:
        try:
            user_input = input("\n> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!"); break
        if not user_input: continue
        if user_input.lower() in ("exit","quit"): print("Goodbye!"); break
        elif user_input.lower() == "why":  show_why()
        elif user_input.lower() == "demo":
            for q in DEMO_QUERIES:
                run_demo(q)
                input("\n  Press Enter for next query...")
        else:
            run_demo(user_input)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        show_why()
        for q in DEMO_QUERIES: run_demo(q)
    else:
        interactive()