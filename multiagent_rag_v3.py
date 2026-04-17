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



# ─────────────────────────────────────────────────────────────
# VERIFIED SOURCE AGENTS — Tier 1 (official) + Tier 2 (community)
# ─────────────────────────────────────────────────────────────

# Source trust tiers
TIER1 = ["vendor_releases","releases","apple_rss","cisa_kev","circl_cve","nvd","cve"]
TIER2 = ["vendor_reddit","reddit_live","reddit_search","google_news","github"]

APPLE_RSS  = "https://developer.apple.com/news/releases/rss/releases.rss"
CISA_KEV   = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
CIRCL_APPLE = "https://vulnerability.circl.lu/recent/cvelistv5.atom?vendor=apple&per_page=20"

def fetch_apple_rss(query, limit=5):
    """Tier 1 — Official Apple release RSS feed."""
    try:
        import requests as req, xml.etree.ElementTree as ET
        r = req.get(APPLE_RSS, timeout=15)
        root = ET.fromstring(r.content)
        items = root.findall(".//item")
        terms = set(query.lower().replace("?","").replace("!","").split())
        results = []
        for item in items:
            title = item.find("title")
            link  = item.find("link")
            pub   = item.find("pubDate")
            if title and title.text:
                t = title.text.lower()
                hits = sum(1 for w in terms if w in t)
                if hits >= 1 or any(k in t for k in ["ios","macos","iphone","ipad","siri","apple","security","watchos"]):
                    results.append((hits, {
                        "title":   title.text,
                        "subreddit": "Apple Official",
                        "sentiment": "Negative" if any(w in t for w in ["security","vulnerability","fix","patch"]) else "Positive",
                        "score": 0, "divergence": 0.0,
                        "source": "apple_rss",
                        "url": link.text if link is not None else "",
                        "date": (pub.text or "")[:16] if pub is not None else "",
                        "verified": True,
                        "tier": 1,
                    }))
        results.sort(key=lambda x: x[0], reverse=True)
        return [d for _,d in results[:limit]]
    except Exception as e:
        return []

def fetch_cisa_kev(query, limit=3):
    """Tier 1 — CISA Known Exploited Vulnerabilities (US Gov, actively exploited only)."""
    try:
        import requests as req
        r = req.get(CISA_KEV, timeout=15)
        data = r.json().get("vulnerabilities", [])
        terms = set(query.lower().replace("?","").replace("!","").split())
        results = []
        for v in data:
            txt = (v.get("vendorProject","") + " " + v.get("product","") + " " +
                   v.get("vulnerabilityName","") + " " + v.get("shortDescription","")).lower()
            hits = sum(1 for w in terms if w in txt)
            if hits >= 2:
                results.append((hits, {
                    "title":   f"[CISA KEV] {v.get('vulnerabilityName','')} — {v.get('product','')}",
                    "subreddit": "CISA US-CERT",
                    "sentiment": "Negative",
                    "score": 0, "divergence": 0.5,
                    "source": "cisa_kev",
                    "url": f"https://nvd.nist.gov/vuln/detail/{v.get('cveID','')}",
                    "date": v.get("dateAdded",""),
                    "detail": v.get("shortDescription","")[:150],
                    "cve_id": v.get("cveID",""),
                    "action": v.get("requiredAction",""),
                    "verified": True,
                    "tier": 1,
                }))
        results.sort(key=lambda x: x[0], reverse=True)
        return [d for _,d in results[:limit]]
    except Exception as e:
        return []

def fetch_circl_apple(query, limit=3):
    """Tier 1 — CIRCL Apple CVE Atom feed (no API key, aggregates NVD+CISA+CVEProject)."""
    try:
        import requests as req, xml.etree.ElementTree as ET
        r = req.get(CIRCL_APPLE, timeout=15)
        root = ET.fromstring(r.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        terms = set(query.lower().replace("?","").replace("!","").split())
        results = []
        for e in entries:
            title   = e.find("atom:title", ns)
            link    = e.find("atom:link", ns)
            summary = e.find("atom:summary", ns)
            updated = e.find("atom:updated", ns)
            if title and title.text:
                txt = (title.text + " " + (summary.text or "")).lower()
                hits = sum(1 for w in terms if w in txt)
                if hits >= 1:
                    results.append((hits, {
                        "title":    title.text,
                        "subreddit": "CIRCL/NVD",
                        "sentiment": "Negative",
                        "score": 0, "divergence": 0.4,
                        "source": "circl_cve",
                        "url": link.get("href","") if link is not None else "",
                        "date": (updated.text or "")[:10] if updated is not None else "",
                        "detail": (summary.text or "")[:150],
                        "verified": True,
                        "tier": 1,
                    }))
        results.sort(key=lambda x: x[0], reverse=True)
        return [d for _,d in results[:limit]]
    except Exception as e:
        return []

def fetch_reddit_subreddit(query, subreddits=None, limit=5):
    """Tier 2 — Direct Reddit subreddit JSON search (community, not verified)."""
    try:
        import requests as req
        if subreddits is None:
            # Auto-detect relevant subreddits from query
            q = query.lower()
            if any(w in q for w in ["ios","iphone","ipad","siri","apple","macos"]):
                subreddits = ["applehelp","ios","apple"]
            elif any(w in q for w in ["linux","ubuntu","fedora","debian","grub","kernel"]):
                subreddits = ["linuxquestions","linux","Ubuntu"]
            elif any(w in q for w in ["chrome","firefox","edge","browser"]):
                subreddits = ["chrome","firefox","MicrosoftEdge"]
            elif any(w in q for w in ["windows","microsoft","win11"]):
                subreddits = ["windows","techsupport","sysadmin"]
            else:
                subreddits = ["techsupport","sysadmin","software"]

        results = []
        headers = {"User-Agent": "AMARA-Research/1.0"}
        for sub in subreddits[:2]:  # max 2 subreddits
            try:
                url = f"https://www.reddit.com/r/{sub}/search.json"
                r = req.get(url, params={"q": query, "sort":"relevance","limit":10,"restrict_sr":"on"},
                            headers=headers, timeout=10)
                if r.status_code == 200:
                    posts = r.json().get("data",{}).get("children",[])
                    for p in posts:
                        d = p.get("data",{})
                        results.append({
                            "title":     d.get("title",""),
                            "subreddit": d.get("subreddit",""),
                            "sentiment": "Negative" if any(w in d.get("title","").lower()
                                         for w in ["broken","fix","issue","bug","error","fail"]) else "Positive",
                            "score":     d.get("score",0),
                            "divergence": 0.0,
                            "source":    "reddit_search",
                            "url":       f"https://reddit.com{d.get('permalink','')}",
                            "date":      "",
                            "verified":  False,
                            "tier":      2,
                        })
            except: pass
        return results[:limit]
    except Exception as e:
        return []

def get_source_label(source):
    """Return trust label and icon for a source."""
    labels = {
        "vendor_releases": ("✅ VERIFIED", "releasetrain.io — Targeted Vendor Release Notes"),
        "apple_rss":       ("✅ VERIFIED", "Apple Official Release Feed"),
        "cisa_kev":        ("✅ VERIFIED", "CISA US-CERT Known Exploited Vulnerabilities"),
        "circl_cve":       ("✅ VERIFIED", "CIRCL/NVD Apple CVE Database"),
        "nvd":             ("✅ VERIFIED", "NVD/NIST Official CVE Database"),
        "releases":        ("✅ VERIFIED", "releasetrain.io Release Notes (general)"),
        "cve":             ("✅ VERIFIED", "releasetrain.io CVE Advisories"),
        "vendor_reddit":   ("🟡 COMMUNITY", "Reddit — Vendor Subreddit (targeted)"),
        "reddit_live":     ("🟡 COMMUNITY", "Reddit Community Posts (releasetrain.io)"),
        "reddit_search":   ("🟡 COMMUNITY", "Reddit Community Posts (direct search)"),
        "google_news":     ("🟡 COMMUNITY", "Google News Press Coverage"),
        "github":          ("🟡 COMMUNITY", "GitHub Release Notes"),
        "local":           ("⚠️ UNVERIFIED", "Local Dataset (may be outdated)"),
    }
    return labels.get(source, ("⚠️ UNVERIFIED", f"Unknown source: {source}"))



# ─────────────────────────────────────────────────────────────
# VENDOR EXTRACTION — Dr. Berhe's recommendation
# Extract product/vendor from query first, then query targeted APIs
# ─────────────────────────────────────────────────────────────

import difflib
import requests as requests

_VENDOR_NAMES    = []   # from /api/c/names        — 14,223 products
_SUBREDDIT_NAMES = []   # from /api/reddit/meta/subreddits — 628 subreddits
_VENDORS_LOADED  = False

def load_vendor_lists():
    """Cache vendor + subreddit lists once at startup."""
    global _VENDOR_NAMES, _SUBREDDIT_NAMES, _VENDORS_LOADED
    if _VENDORS_LOADED:
        return
    try:
        r1 = requests.get("https://releasetrain.io/api/c/names", timeout=15)
        _VENDOR_NAMES = [v.lower() for v in r1.json() if isinstance(v, str)]
        print(f"  Loaded {len(_VENDOR_NAMES)} vendor names")
    except Exception as e:
        print(f"  Warning: could not load vendor names: {e}")

    try:
        r2 = requests.get("https://releasetrain.io/api/reddit/meta/subreddits", timeout=15)
        _SUBREDDIT_NAMES = [s.lower() for s in r2.json().get("data", []) if isinstance(s, str)]
        print(f"  Loaded {len(_SUBREDDIT_NAMES)} subreddit names")
    except Exception as e:
        print(f"  Warning: could not load subreddits: {e}")

    _VENDORS_LOADED = True

# Common aliases — maps query terms to canonical vendor names
VENDOR_ALIASES = {
    # Apple
    "ios": "ios", "iphone": "ios", "ipad": "ios", "siri": "ios",
    "icloud": "ios", "apple id": "ios", "find my": "ios",
    "macos": "macos", "mac": "macos", "macbook": "macos", "tahoe": "macos",
    # Browsers
    "firefox": "firefox", "ff": "firefox",
    "chrome": "chrome", "chromium": "chrome",
    "edge": "MicrosoftEdge", "microsoft edge": "MicrosoftEdge",
    # OS
    "windows": "windows", "win11": "windows", "win10": "windows",
    "linux": "linux", "ubuntu": "ubuntu", "debian": "debian",
    "fedora": "fedora", "kernel": "linux",
    "android": "android", "pixel": "android",
    "orcaslicer": "orcaslicer", "tapo": "tapo",
    "truenas": "truenas", "aws": "aws", "spotify": "spotify",
    "tinder": "tinder", "otbr": "homeassistant",
    "neovim": "neovim", "nvim": "neovim",
    "microsoftedge": "MicrosoftEdge",
}

VENDOR_STOP_WORDS = {
    "version","text","firmware","updater","arrow","maybe","server",
    "desktop","downloads","core","config","plugins","software","update",
    "latest","release","new","fix","bug","issue","error","crash",
    "install","upgrade","support","help","question","problem","using",
    "after","before","when","how","why","what","where","which","can",
    "will","does","did","has","have","been","some","many","most","all",
    "any","get","set","run","use","make","take","need","want","know",
    "think","see","look","try","back","first","last","next","same",
    "other","good","bad","big","small","free","open","automattic",
    "trash","dead","broken","terrible","stupid","awful","great","performance","behavior","recent","update","patch","stable","unstable","issue","security","release","releases","software","latest","fixed","bugs","community","reaction","feedback","negative","positive","versions","version","offline","execute","tasks","after","update","fail","fails","failing",
}

# Subreddit → vendor fallback map
SUBREDDIT_VENDOR_MAP = {
    "microsoftedge": "MicrosoftEdge",
    "androidquestions": "android",
    "androiddev": "android",
    "homenetworking": "linux",
    "homelab": "linux",
    "aws": "aws",
    "neovim": "neovim",
    "linuxquestions": "linux",
    "applehelp": "ios",
    "homeassistant": "homeassistant", "home assistant": "homeassistant", "hass": "homeassistant", "ha": "homeassistant", "hassio": "homeassistant",
    "fedora": "fedora",
    "debian": "debian",
    "ubuntu": "ubuntu",
    "chrome": "chrome",
    "firefox": "firefox",
    "openclaw": "openclaw",
    "comfyui": "comfyui",
    "ollama": "ollama", "ollama.ai": "ollama",
    "ubiquiti": "Ubiquiti",
    # Hardware/Networking
    "ubiquiti": "Ubiquiti", "unifi": "Ubiquiti", "g6": "Ubiquiti", "g6 bullet": "Ubiquiti",
    "bullet": "Ubiquiti", "udr": "Ubiquiti", "udm": "Ubiquiti", "uap": "Ubiquiti", "edgerouter": "Ubiquiti",
    "proxmox": "Proxmox", "nginx": "nginx", "apache": "apache",
    "docker": "docker",
    # AI/ML tools
    "ollama": "ollama",
    "comfyui": "comfyui", "comfy": "comfyui", "gguf": "comfyui",
    "ace-step": "comfyui", "acestep": "comfyui", "queue": "comfyui",
    "wan2": "comfyui", "flux": "comfyui",
    "ace-step": "comfyui", "ace step": "comfyui",
    "wan2": "comfyui", "wan 2": "comfyui",
    "openclaw": "openclaw",
    # GPU
    "nvidia": "nvidia", "nvidia drivers": "nvidia",
    # Home automation
    "home assistant": "homeassistant", "homeassistant": "homeassistant", "home assistant": "homeassistant", "hass": "homeassistant", "ha": "homeassistant", "hassio": "homeassistant",
    "zigbee": "homeassistant", "z2m": "homeassistant",
    # Dev tools
    "vscode": "vscode", "vs code": "vscode",
    "wordpress": "Wordpress", "wp": "Wordpress",
    "git": "git", "github": "github",
    "python": "python",
    "nginx": "nginx",
}

def extract_vendor(query: str, _subreddit_hint: str = "") -> list:
    """
    Extract vendor/product names from a query.
    Returns list of matched vendor names (lowercase).
    Priority: aliases > exact word match in vendor list > subreddit match > fuzzy.
    Falls back to [] if no match found.
    """
    load_vendor_lists()
    q_lower = query.lower()
    found = []

    # 0a. Multi-word and short aliases — checked BEFORE stop-word filter
    MULTI_WORD = {
        "g6 bullet":      "Ubiquiti",
        "home assistant": "homeassistant",
        "home-assistant": "homeassistant",
        "hassio":         "homeassistant",
        "microsoft edge": "MicrosoftEdge",
        "ace step":       "comfyui",
        "ace-step":       "comfyui",
        "proxmox ve":     "Proxmox",
    }
    for phrase, pvendor in MULTI_WORD.items():
        if phrase in q_lower:
            return [pvendor]
    # Short tokens (len<=2) that stop-word filter drops
    for token in q_lower.split():
        if token == "g6":
            return ["Ubiquiti"]

    # 0. Check [r/subreddit] prefix from auto mode
    import re
    sub_match = re.match(r'\[r/(\w+)\]', query.strip())
    if sub_match:
        sub_name = sub_match.group(1).lower()
        # Map subreddit to vendor
        SUB_TO_VENDOR = {
            "comfyui": "comfyui", "ubiquiti": "Ubiquiti",
            "openclaw": "openclaw", "ollama": "ollama",
            "homeassistant": "homeassistant", "home assistant": "homeassistant", "hass": "homeassistant", "ha": "homeassistant", "hassio": "homeassistant", "applehelp": "ios",
            "linuxquestions": "linux", "fedora": "linux",
            "linux": "linux", "ubuntu": "ubuntu",
        }
        if sub_name in SUB_TO_VENDOR:
            found.append(SUB_TO_VENDOR[sub_name])

    # 1. Check aliases first (fastest, most reliable)
    for alias, canonical in VENDOR_ALIASES.items():
        if alias in q_lower:
            if canonical.lower() not in [f.lower() for f in found]:
                found.append(canonical)

    # 2. Check exact word match against vendor names list
    if not found:
        words = set(q_lower.replace("?","").replace("!","").split())
        for word in words:
            if len(word) > 3 and word in _VENDOR_NAMES:
                found.append(word)

    # 3. Check subreddit names (they're curated and clean)
    if not found:
        words = set(q_lower.replace("?","").replace("!","").split())
        for word in words:
            if len(word) > 3 and word in _SUBREDDIT_NAMES:
                found.append(word)

    # 4. Fuzzy match as last resort — skip stop-words
    if not found and _VENDOR_NAMES:
        words = [w for w in q_lower.split()
                 if len(w) > 4 and w not in VENDOR_STOP_WORDS]
        for word in words:
            matches = difflib.get_close_matches(word, _VENDOR_NAMES, n=1, cutoff=0.92)
            if matches and matches[0].lower() not in VENDOR_STOP_WORDS:
                found.append(matches[0])
                break  # take first confident match only

    # 5. Subreddit fallback — use subreddit name if still no vendor found
    if not found and _subreddit_hint:
        sub_vendor = SUBREDDIT_VENDOR_MAP.get(_subreddit_hint.lower())
        if sub_vendor:
            found.append(sub_vendor)

        # Score each vendor by how strongly it matches the query
    # and return only the single best match
    found = list(dict.fromkeys(found))
    if len(found) <= 1:
        return found

    q_lower_check = query.lower()
    def vendor_score(v):
        vl = v.lower()
        # Direct name in query = highest confidence
        if vl in q_lower_check:
            return 0
        # Alias match
        for alias, canonical in VENDOR_ALIASES.items():
            if alias in q_lower_check and canonical.lower() == vl:
                return 1
        # Subreddit fallback = lowest confidence
        return 2

    found.sort(key=vendor_score)
    return found[:1]

def extract_date_from_query(query: str):
    """Extract a target date from a query like 'on January 1st 2026' or 'in March 2025'."""
    import re
    q = query.lower()
    # Match patterns like "january 1st 2026", "jan 1 2026", "2026-01-01", "20260101"
    months = {"january":1,"jan":1,"february":2,"feb":2,"march":3,"mar":3,
              "april":4,"apr":4,"may":5,"june":6,"jun":6,"july":7,"jul":7,
              "august":8,"aug":8,"september":9,"sep":9,"october":10,"oct":10,
              "november":11,"nov":11,"december":12,"dec":12}
    # Pattern: month name + optional day + year
    for name, num in months.items():
        pattern = rf"{name}\s*(\d{{1,2}})(?:st|nd|rd|th)?[,\s]+(\d{{4}})"
        m = re.search(pattern, q)
        if m:
            day, year = int(m.group(1)), int(m.group(2))
            return f"{year}{num:02d}{day:02d}"
        # Just month + year
        pattern2 = rf"{name}[,\s]+(\d{{4}})"
        m2 = re.search(pattern2, q)
        if m2:
            year = int(m2.group(1))
            return f"{year}{num:02d}01"
    # Pattern: YYYY-MM-DD or YYYYMMDD
    m3 = re.search(r"(\d{4})-(\d{2})-(\d{2})", q)
    if m3: return m3.group(1)+m3.group(2)+m3.group(3)
    m4 = re.search(r"\b(20\d{6})\b", q)
    if m4: return m4.group(1)
    return None

def fetch_vendor_releases(vendor: str, limit: int = 10, target_date: str = None) -> list:
    """Fetch targeted releases for a specific vendor using /api/c/name/{vendor}.
    If target_date (YYYYMMDD) provided, returns the version active on that date."""
    try:
        url = f"https://releasetrain.io/api/c/name/{vendor.lower()}"
        r = requests.get(url, timeout=15)
        if r.status_code != 200:
            return []
        data = r.json()
        releases = []
        for key, items in data.items():
            if isinstance(items, list):
                releases.extend(items)

        # If date requested: filter to releases on or before that date, take closest
        if target_date:
            dated = [(str(v.get("versionReleaseDate","")), v)
                     for v in releases if str(v.get("versionReleaseDate","")) <= target_date]
            dated.sort(key=lambda x: x[0], reverse=True)
            # Only keep canonical torvalds releases if linux
            if vendor.lower() in ["linux"]:
                dated = [(d,v) for d,v in dated
                         if "torvalds" in str(v.get("versionProductName","")).lower()
                         or "torvalds" in str(v.get("versionProductBrand","")).lower()]
            releases = [v for _, v in dated[:limit]]
        else:
            releases = releases[:limit]

        # ── Canonical brand prioritization ─────────────────────────────
        # Move entries where brand EXACTLY matches vendor to the front
        # This fixes Linux returning openCryptoki instead of torvalds kernel
        CANONICAL_MAP = {
            "linux": ["torvalds", "linux kernel"],
            "ios":   ["apple", "ios"],
            "macos": ["apple", "macos"],
            "firefox": ["mozilla", "firefox"],
            "chrome": ["google", "chrome"],
        }
        canonical_brands = [b.lower() for b in CANONICAL_MAP.get(vendor.lower(), [vendor.lower()])]

        def canonical_score(v):
            brand = str(v.get("versionProductBrand","")).lower()
            name  = str(v.get("versionProductName","")).lower()
            # Exact canonical match = highest priority
            if any(cb in brand or cb in name for cb in canonical_brands):
                return 0
            # Vendor name exact match = second priority
            if brand == vendor.lower():
                return 1
            # CVE noise = lowest priority
            if v.get("isCve"):
                return 3
            return 2

        if not target_date:
            releases.sort(key=canonical_score)

        results = []
        for v in releases:
            notes = v.get("versionReleaseNotes", "")
            if isinstance(notes, list): notes = " ".join(notes)
            date_str = str(v.get("versionReleaseDate",""))[:8]
            title = f"{v.get('versionProductBrand',vendor)} v{v.get('versionNumber','')} — {str(notes)[:120]}"
            if target_date:
                title = f"{v.get('versionProductBrand',vendor)} v{v.get('versionNumber','')} (released {date_str}) — {str(notes)[:80]}"
            results.append({
                "title":     title,
                "subreddit": v.get("versionProductBrand", vendor),
                "sentiment": "Negative" if v.get("isCve") else "Positive",
                "score":     0,
                "divergence": 0.0,
                "source":    "vendor_releases",
                "url":       v.get("versionUrl", ""),
                "date":      date_str,
                "detail":    str(notes)[:150],
                "verified":  True,
                "tier":      1,
                "vendor":    vendor,
            })
        return results
    except Exception as e:
        return []

def fetch_vendor_reddit(vendor: str, query: str = "", limit: int = 10) -> list:
    """Fetch targeted Reddit posts for a specific vendor subreddit, filtered by query relevance."""
    try:
        r = requests.get(
            "https://releasetrain.io/api/reddit/by-subreddit",
            params={"q": vendor.lower(), "limit": 200},
            timeout=15
        )
        if r.status_code != 200:
            return []
        data = r.json()
        posts = data.get("data", [])

        # Filter by query relevance if query provided
        if query:
            q_terms = set(w.lower().strip("?!.,") for w in query.split() if len(w) > 3)
            scored = []
            for p in posts:
                title = p.get("title", "").lower()
                body  = str(p.get("author_description", "") or "").lower()
                txt   = title + " " + body
                hits  = sum(1 for t in q_terms if t in txt)
                # Boost exact title match
                if query.lower()[:25] in title:
                    hits += 10
                scored.append((hits, p))
            scored.sort(key=lambda x: x[0], reverse=True)
            posts = [p for _, p in scored if _ > 0][:limit]
        else:
            posts = posts[:limit]

        results = []
        for p in posts:
            title  = p.get("title", "")
            body   = str(p.get("author_description", "") or "")[:300]
            f_comm = str(p.get("first_author_comment", "") or "")[:200] if p.get("first_author_comment") else ""
            detail = (body + (" | Top comment: " + f_comm if f_comm else "")).strip()
            results.append({
                "title":     title,
                "subreddit": p.get("subreddit", vendor),
                "sentiment": "Negative" if any(w in title.lower()
                             for w in ["broken","fix","bug","error","fail","crash","issue","unstable"]) else "Positive",
                "score":     p.get("score", 0),
                "divergence": 0.0,
                "source":    "vendor_reddit",
                "url":       p.get("url", ""),
                "date":      "",
                "detail":    detail,
                "verified":  False,
                "tier":      2,
                "vendor":    vendor,
            })
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

        # ── STEP 1: Extract vendor/product from query (Dr. Berhe) ──
        vendors = extract_vendor(rewritten_query)
        if vendors:
            print(f"  Vendor   : Detected → {vendors}")
        else:
            print(f"  Vendor   : None detected — using general search")

        # ── STEP 2: Targeted vendor queries (if vendor found) ──
        vendor_releases = []
        vendor_reddit   = []
        # Extract date from query if present
        target_date = extract_date_from_query(rewritten_query)
        if target_date:
            print(f"  Date     : Detected → {target_date}")

        if vendors:
            # Expand vendor to related subreddits for better coverage
            VENDOR_SUBREDDITS = {
                "linux":     ["linux","linuxquestions","Fedora","Ubuntu","debian"],
                "ollama":    ["ollama","LocalLLaMA","openclaw"],
                "comfyui":   ["comfyui"],
                "openclaw":  ["openclaw"],
                "Ubiquiti":  ["Ubiquiti"],
                "ios":       ["applehelp","ios","apple"],
                "macos":     ["MacOS","applehelp"],
                "windows":   ["windows","techsupport"],
                "chrome":    ["chrome","chromium"],
                "homeassistant": ["homeassistant"],
            }
            for v in vendors[:2]:  # max 2 vendors
                print(f"  Fetching : releasetrain.io/api/c/name/{v} ...")
                vendor_releases += fetch_vendor_releases(v, limit=8, target_date=target_date)
                # Search all related subreddits for this vendor
                subs_to_search = VENDOR_SUBREDDITS.get(v, [v])
                for sub in subs_to_search[:3]:
                    print(f"  Fetching : releasetrain.io/api/reddit/by-subreddit?q={sub} ...")
                    vendor_reddit += fetch_vendor_reddit(sub, query=rewritten_query, limit=8)

        # ── STEP 3: General sources (always run as fallback/supplement) ──
        print(f"  Fetching : releasetrain.io/api/v/ (general) ...")
        releases = fetch_live_releases(rewritten_query, limit=4) if not vendor_releases else []

        print(f"  Fetching : Apple Official RSS ...")
        apple = fetch_apple_rss(rewritten_query, limit=3)

        print(f"  Fetching : CISA KEV (actively exploited CVEs) ...")
        cisa = fetch_cisa_kev(rewritten_query, limit=2)

        print(f"  Fetching : CIRCL Apple CVE feed ...")
        circl = fetch_circl_apple(rewritten_query, limit=2)

        print(f"  Fetching : releasetrain.io/api/reddit/query/cve ...")
        cve = fetch_live_cve(rewritten_query, limit=2)

        print(f"  Fetching : releasetrain.io/api/reddit/query/positive ...")
        reddit = fetch_live_reddit(rewritten_query, limit=3) if not vendor_reddit else []

        print(f"  Fetching : Google News RSS ...")
        news = fetch_google_news(rewritten_query, limit=2)

        # ── Tier 1: vendor-specific first, then general verified ──
        tier1 = vendor_releases + releases + apple + cisa + circl + cve
        # ── Tier 2: vendor reddit first, then general community ──
        tier2 = vendor_reddit + reddit + news

        # Boost: if Apple RSS or Reddit has direct query match, put it first
        q_low = rewritten_query.lower()
        boosted, rest = [], []
        for d in tier1 + tier2:
            title = d.get("title","").lower()
            # Direct product/topic match — move to front
            if any(w in title for w in q_low.split()[:4] if len(w)>3):
                boosted.append(d)
            else:
                rest.append(d)
        results = boosted + rest

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

        t1_count = len(tier1); t2_count = len(tier2)
        print(f"  Found    : {len(results)} results | ✅ Tier1={t1_count} (verified) | 🟡 Tier2={t2_count} (community)")
        for i, doc in enumerate(results[:6], 1):
            lbl, src_name = get_source_label(doc.get("source","?"))
            icon = "🔴" if doc["sentiment"]=="Negative" else "🟢"
            date = f" ({doc.get('date','')[:10]})" if doc.get('date') else ''
            print(f"    {i}. {icon} {lbl[:4]} [{doc.get('source','?')}] {doc['title'][:55]}{date}")
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
        if docs:
            scores = []
            for d in docs:
                txt = (d.get("title","") + " " + d.get("subreddit","") +
                       " " + d.get("detail","")).lower()
                hits = len(query_terms & set(txt.split()))
                # Bonus for verified sources with any match
                if d.get("source","") in ["apple_rss","cisa_kev","circl_cve"] and hits >= 1:
                    hits += 3
                # Bonus for exact title match in community posts
                if original_query.lower()[:20] in txt:
                    hits += 5
                scores.append(hits)
            best = max(scores) if scores else 0
            quality = round(min(best / max(len(query_terms), 1), 1.0), 2)
            # If we have verified Apple sources, minimum quality is MEDIUM
            has_apple = any(d.get("source") in ["apple_rss","cisa_kev","circl_cve"]
                           for d in docs)
            if has_apple and quality < 0.3:
                quality = 0.3
        else:
            quality = 0.0
        # If vendor-targeted releases found — that IS a quality signal
        has_vendor_releases = any(d.get("source") == "vendor_releases" for d in docs)
        has_vendor_reddit   = any(d.get("source") == "vendor_reddit"   for d in docs)
        tier1_hits = [d for d in docs if d.get("source","") in TIER1]
        tier2_hits = [d for d in docs if d.get("source","") in TIER2]
        has_ios_match = any(
            any(w in (d.get("title","") + d.get("detail","")).lower()
                for w in ["ios","iphone","apple","siri","ipad","macos"])
            for d in docs
        )

        # Vendor-targeted results = strong relevance signal
        if has_vendor_releases and has_vendor_reddit:
            quality = max(quality, 0.65)  # HIGH — both vendor sources confirmed
        elif has_vendor_releases:
            quality = max(quality, 0.50)  # MEDIUM-HIGH — release notes found
        elif has_vendor_reddit:
            quality = max(quality, 0.40)  # MEDIUM — community posts found
            quality = max(quality, 0.5)
        elif tier1_hits and quality < 0.3:
            quality = 0.3

        signal = "✅ positive" if quality >= 0.15 else "⚠️  negative — manager will retry"

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
        elif confidence == "LOW" and not any(d.get("source") in ["reddit_live","cve"] for d in docs):
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
            # ── Llama synthesis — generate a direct answer from retrieved docs ──
            context_parts = []
            # Prioritize vendor-specific docs first
            sorted_docs = sorted(docs, key=lambda d: (
                0 if d.get("source") in ["vendor_releases","vendor_reddit"] else 1
            ))
            for d in sorted_docs[:8]:
                src    = d.get('source','?')
                title  = d.get('title','')[:120]
                detail = d.get('detail','')[:350] if d.get('detail') else ''
                url    = d.get('url','')
                cve    = url.split('/')[-1] if url and 'CVE' in url else ''
                sub    = d.get('subreddit','')
                src_lbl = "COMMUNITY POST" if d.get('source') in ['vendor_reddit','reddit_live'] else "RELEASE NOTE"
                entry  = f"[{src_lbl}][{sub}] {title}"
                if detail: entry += f"\n  Content: {detail}"
                if cve:    entry += f"\n  CVE: {cve}"
                context_parts.append(entry)
            context = "\n\n".join(context_parts) if context_parts else "No direct matches found."


            # Get vendor name from docs — must be before prompt
            vendor_name = next((d.get("vendor","") for d in docs if d.get("vendor")), "the vendor")
            vendor_url  = f"https://github.com/search?q={vendor_name}" if vendor_name != "the vendor" else "releasetrain.io"

            # Detect query type to give Llama the right instructions
            q_low = original_query.lower()
            is_version_query = any(w in q_low for w in ["latest version","what version","current version","which version","version of"])
            is_bug_query     = any(w in q_low for w in ["broken","crash","fail","issue","unstable","doesnt load","not working","error","bug","freeze","slow","dead","missing","disappeared"])

            if is_version_query:
                version_instruction = """IMPORTANT: This is a VERSION query.
Look at the FIRST release source. Extract the version number and date.
Respond EXACTLY in this format:
The latest version of [product] is v[version], released on [date]. Source: [url]
Do NOT say you could not find it. The version is in the sources."""
            elif is_bug_query:
                version_instruction = """IMPORTANT: This is a BUG/ISSUE query.
State whether this issue is confirmed by community posts or release notes.
If confirmed: say "This is a known issue. [what sources say]. Verdict: CONFIRMED."
If not found: say "No matching reports found for this specific issue." """
            else:
                version_instruction = """Answer directly from the sources. Be specific and factual.
If release notes are present, state what changed. If community posts match, summarize them."""

            llm_prompt = f"""You are a software update assistant. Answer ONLY using the sources below.

{version_instruction}

STRICT RULES:
- NEVER say "I couldn't find" if at least one source was retrieved
- NEVER invent version numbers, CVE IDs, or fixes not in the sources
- NEVER say "it appears" or "it is likely" — only state what sources confirm
- Keep answer to 2-3 sentences maximum

User question: "{original_query}"

Sources retrieved:
{context}

Answer:"""

            print(f"  Synthesizing answer with Llama 3.1...")
            llm_answer = call_llama(llm_prompt)
            # Separate by trust tier
            tier1_docs = [d for d in docs if d.get("source","") in TIER1]
            tier2_docs = [d for d in docs if d.get("source","") in TIER2]
            unverified = [d for d in docs if d.get("source","") not in TIER1+TIER2]

            lines.append(f"  ✅ ANSWER (synthesized by Llama 3.1):")
            lines.append("")
            lines.append(f"  {llm_answer}")
            lines.append("")

            if tier1_docs:
                lines.append(f"  ✅ VERIFIED SOURCES ({len(tier1_docs)}):")
                for d in tier1_docs[:4]:
                    lbl, src_name = get_source_label(d.get("source","?"))
                    date = f" ({d.get('date','')[:10]})" if d.get('date') else ''
                    cve_id = d.get("cve_id","")
                    lines.append(f"    • {lbl} [{src_name}]")
                    lines.append(f"      {d['title'][:90]}{date}")
                    if d.get('detail'): lines.append(f"      ↳ {d['detail'][:100]}")
                    if cve_id: lines.append(f"      ↳ CVE: {cve_id}")
                    if d.get('url'):    lines.append(f"      🔗 {d['url']}")
                    if d.get('action'): lines.append(f"      ⚡ Action: {d['action'][:80]}")
                lines.append("")

            if tier2_docs:
                lines.append(f"  🟡 COMMUNITY SOURCES ({len(tier2_docs)}) — not officially verified:")
                for d in tier2_docs[:4]:
                    lbl, src_name = get_source_label(d.get("source","?"))
                    sub  = d.get("subreddit","")
                    date = f" ({d.get('date','')[:10]})" if d.get('date') else ''
                    ups  = f" ↑{d.get('score',0)}" if d.get('score',0) > 0 else ''
                    lines.append(f"    • {lbl} [r/{sub}]{ups}")
                    lines.append(f"      {d['title'][:90]}{date}")
                    if d.get('url'): lines.append(f"      🔗 {d['url']}")
                lines.append("")

            if unverified:
                lines.append(f"  ⚠️  OTHER SOURCES ({len(unverified)}) — treat with caution:")
                for d in unverified[:2]:
                    lines.append(f"    • [{d.get('source','unknown')}] {d['title'][:80]}")
                lines.append("")

            if not tier1_docs and not tier2_docs:
                lines.append("  ⚠️  No verified or community sources matched this query.")
                lines.append("  Please check vendor documentation directly.")
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
    "What is the latest version of Linux?",
    "Siri fail to execute tasks when offline after iOS 26.4 update",
    "Updated to kernel 6.19.11 and now desktop doesnt load",
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


def auto_mode(limit=5):
    """AUTO MODE — fetch live Reddit questions and answer each one automatically."""
    print("\n" + "="*58)
    print("  AUTO MODE — Fetching latest Reddit questions...")
    print("="*58)
    try:
        # Fetch page 1 + page 2 = 200 live questions
        questions = []
        for page in [1, 2]:
            r = requests.get(
                "https://releasetrain.io/api/reddit/query/questions",
                params={"page": page, "limit": 100},
                timeout=15
            )
            data = r.json()
            batch = data if isinstance(data, list) else data.get("data", [])
            questions.extend(batch)
    except Exception as e:
        print(f"  Could not fetch questions: {e}")
        return
    if not questions:
        print("  No questions returned from API.")
        return
    print(f"  Found {len(questions)} live questions — answering top {limit}:")
    for i, q in enumerate(questions[:limit], 1):
        title = q.get("title", q.get("query", ""))
        sub   = q.get("subreddit", "")
        url   = q.get("url", "")
        if not title:
            continue
        print("\n" + "-"*58)
        print(f"  [{i}/{limit}]  r/{sub}")
        print(f"  Q: {title}")
        if url:
            print(f"  Reddit: {url}")
        print("-"*58)
        run_demo(title)
        ans = input("\n  Press Enter for next (or q to quit auto mode): ")
        if ans.strip().lower() == "q":
            break
    print("\n" + "="*58)
    print("  Auto mode complete.")
    print("="*58)

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
    print("    'auto' — AUTO MODE: fetch live Reddit questions and answer them")
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
        elif user_input.lower() in ("auto", "auto mode"):
            try:
                n = input("  How many questions to answer? (default 5): ").strip()
                n = int(n) if n else 5
            except:
                n = 5
            auto_mode(limit=n)
        else:
            run_demo(user_input)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        show_why()
        for q in DEMO_QUERIES: run_demo(q)
    else:
        interactive()
# ─────────────────────────────────────────────────────────────
# AUTO MODE — fetch live Reddit questions and answer them
# ─────────────────────────────────────────────────────────────

def auto_mode(limit=5):
    """Fetch latest Reddit questions and answer each one automatically."""
    print("\n" + "═"*58)
    print("  🤖  AUTO MODE — Fetching latest Reddit questions...")
    print("═"*58)

    try:
        # Fetch page 1 + page 2 = 200 live questions
        questions = []
        for page in [1, 2]:
            r = requests.get(
                "https://releasetrain.io/api/reddit/query/questions",
                params={"page": page, "limit": 100},
                timeout=15
            )
            data = r.json()
            batch = data if isinstance(data, list) else data.get("data", [])
            questions.extend(batch)
    except Exception as e:
        print(f"  ❌ Could not fetch questions: {e}")
        return

    if not questions:
        print("  ❌ No questions returned from API.")
        return

    print(f"  Found {len(questions)} live questions — answering top {limit}:\n")

    for i, q in enumerate(questions[:limit], 1):
        title = q.get("title", q.get("query", ""))
        sub   = q.get("subreddit", "")
        url   = q.get("url", "")

        if not title:
            continue

        print(f"\n" + "─"*58)
        print(f"  [{i}/{limit}]  r/{sub}")
        print(f"  ❓  {title}")
        if url:
            print(f"  🔗  Reddit: {url}")
        print("─"*58)

        # Run through the full AMARA pipeline
        # Prepend subreddit context to help vendor detection
        query_with_context = f"[r/{sub}] {title}" if sub else title
        run_demo(query_with_context)

        ans = input("\n  Press Enter for next question (or q to quit): ")
        if ans.strip().lower() == "q":
            break

    print("\n" + "═"*58)
    print("  Auto mode complete.")
    print("═"*58)
