#!/usr/bin/env python3
"""
Larger multi-ecosystem benchmark builder
========================================
Mines the *live* releasetrain.io APIs (the same endpoints multiagent_rag_v3.py
queries at runtime) and emits a 300-question benchmark stratified across
~20 software ecosystems and 5 question categories.

Why this exists
---------------
`table_50_questions.json` is 50 Reddit-only questions skewed to one category
(general 26 / releases 11 / bugs 9 / community 4).  That is too small and too
narrow to say anything about how the multi-agent router behaves across the
software ecosystem as a whole.  This script builds a bigger, balanced set from
real data.

Endpoints used (all live, all read-only GETs)
---------------------------------------------
  GET /api/v/                              -> 1000 most recent version records
  GET /api/v/search?q=<term>               -> version records matching a term
  GET /api/c/names                         -> catalogue of product names
  GET /api/c/name/<product>                -> version records for one product
  GET /api/reddit/by-subreddit?q=a,b&page= -> posts from named subreddits
  GET /api/reddit/query/questions?page=    -> update-related user questions
  GET /api/reddit/query/positive           -> high-sentiment community posts
  GET /api/reddit/query/cve?q=&limit=      -> CVE-adjacent community posts
  GET /api/reddit/meta/subreddits          -> subreddit catalogue (coverage log)

Honesty rules
-------------
Nothing is invented silently.  Every emitted record carries:

  source           mined_reddit_title  -> query IS a real Reddit post title
                   mined_release_record-> query is phrased over a real, live
                                          version record (real vendor, real
                                          version number, real release date)
                   backfill_template   -> NO live record was available for that
                                          (ecosystem, category) cell
  mined            True/False, matching the above
  source_endpoint  which API path the record came from
  source_id        redditId or versionId of the underlying record

Backfilled cells are printed to stdout at the end of every run and stored in
the sidecar manifest `data/benchmark_300.manifest.json`.

Scored size vs. file size
-------------------------
The file holds 300 *questions*, but only the `mined_release_record` rows carry
a `ground_truth`. The `mined_reddit_title` rows are real user questions with no
gold answer, so `eval_harness.benchmarks.load_benchmark(...,
require_ground_truth=True)` drops them and a `--benchmark generic` run scores
the subset. The manifest field `scorable` is that count -- quote it, not
`total`, when reporting benchmark accuracy.

Determinism / idempotency
-------------------------
* Fixed seed (SEED).  All ordering is by explicit sort key, never by dict or
  set iteration order.
* Every HTTP response is cached under data/.benchmark_cache/.  Re-running
  without --refresh replays the cache, so the output file is byte-identical.
  --refresh re-fetches; --offline refuses to touch the network.

Usage
-----
    python build_multiecosystem_benchmark.py              # cache-first build
    python build_multiecosystem_benchmark.py --refresh    # re-mine live APIs
    python build_multiecosystem_benchmark.py --offline    # cache only
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import random
import sys
import time
from collections import Counter, defaultdict, OrderedDict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import requests
except ImportError:  # pragma: no cover - environment problem, not logic
    print("ERROR: this script needs `requests` (pip install requests)")
    raise

ROOT = os.path.dirname(os.path.abspath(__file__))
BASE = "https://releasetrain.io"
CACHE_DIR = os.path.join(ROOT, "data", ".benchmark_cache")
DEFAULT_OUT = os.path.join(ROOT, "data", "benchmark_300.json")

SEED = 20260830
TOTAL = 300
CATEGORIES = ["releases", "bugs", "security", "community", "general"]
TIMEOUT = 30
REDDIT_PAGES = 3          # by-subreddit pages per ecosystem (200 posts/page)
QUESTION_PAGES = 4        # /api/reddit/query/questions pages (100/page)

# ─────────────────────────────────────────────────────────────────────────────
# Ecosystem definitions
#
# subreddits    : passed to /api/reddit/by-subreddit as a comma list
# release_terms : passed to /api/v/search (and /api/c/name) for version records
# match_tokens  : word-boundary tokens that must appear in a version record's
#                 product name / brand / search tags for it to count as this
#                 ecosystem.  Guards against the search endpoint's loose
#                 matching (q=arch would otherwise pull in "search", q=node
#                 would pull in "NodeBB", etc.)
# ─────────────────────────────────────────────────────────────────────────────
ECOSYSTEMS: List[Dict[str, Any]] = [
    {
        "key": "apple_ios", "vendor": "Apple iOS",
        "subreddits": ["ios", "apple"],
        "release_terms": ["ios", "iphone", "ipados"],
        "match_tokens": ["ios", "ipados", "iphone", "apple"],
    },
    {
        "key": "apple_macos", "vendor": "Apple macOS",
        "subreddits": ["MacOS", "applehelp", "Safari"],
        "release_terms": ["macos", "safari"],
        "match_tokens": ["macos", "mac os", "safari", "apple"],
    },
    {
        "key": "android", "vendor": "Android",
        "subreddits": ["android", "AndroidQuestions", "Magisk", "scrcpy"],
        "release_terms": ["android"],
        "match_tokens": ["android", "pixel", "magisk"],
    },
    {
        "key": "windows", "vendor": "Microsoft Windows",
        "subreddits": ["windows", "MicrosoftEdge", "PowerToys", "powershell"],
        "release_terms": ["windows", "edge", "powershell"],
        "match_tokens": ["windows", "microsoft edge", "powershell", "powertoys"],
    },
    {
        "key": "ubuntu", "vendor": "Ubuntu",
        "subreddits": ["Ubuntu", "Kubuntu", "Lubuntu", "xubuntu"],
        "release_terms": ["ubuntu", "kubuntu", "xubuntu"],
        "match_tokens": ["ubuntu", "kubuntu", "lubuntu", "xubuntu", "edubuntu"],
    },
    {
        "key": "debian", "vendor": "Debian",
        "subreddits": ["debian"],
        "release_terms": ["debian"],
        "match_tokens": ["debian"],
    },
    {
        "key": "fedora", "vendor": "Fedora / RHEL",
        "subreddits": ["Fedora", "centos", "Bazzite"],
        "release_terms": ["fedora", "centos", "red hat"],
        "match_tokens": ["fedora", "centos", "rhel", "red hat", "bazzite"],
    },
    {
        "key": "arch", "vendor": "Arch Linux",
        "subreddits": ["arch", "cachyos", "omarchy", "EndeavourOS"],
        "release_terms": ["arch", "manjaro", "cachyos"],
        "match_tokens": ["arch", "archlinux", "arch linux", "manjaro",
                         "cachyos", "endeavouros", "pacman"],
    },
    {
        "key": "linux_kernel", "vendor": "Linux kernel / distros",
        "subreddits": ["linux", "linuxquestions", "NixOS", "openSUSE",
                       "mint", "SteamOS", "embeddedlinux"],
        "release_terms": ["linux", "kernel", "nixos", "opensuse"],
        "match_tokens": ["linux", "kernel", "nixos", "opensuse", "torvalds"],
    },
    {
        "key": "firefox", "vendor": "Mozilla Firefox",
        "subreddits": ["firefox", "LibreWolf"],
        "release_terms": ["firefox", "thunderbird"],
        "match_tokens": ["firefox", "mozilla", "thunderbird", "librewolf"],
    },
    {
        "key": "chrome", "vendor": "Google Chrome",
        "subreddits": ["chrome", "chromeos", "Adblock"],
        "release_terms": ["chrome", "chromium"],
        "match_tokens": ["chrome", "chromium", "chromeos"],
    },
    {
        "key": "docker", "vendor": "Docker",
        "subreddits": ["docker", "QEMU"],
        "release_terms": ["docker", "containerd", "podman"],
        "match_tokens": ["docker", "containerd", "podman", "dockerfile"],
    },
    {
        "key": "kubernetes", "vendor": "Kubernetes",
        "subreddits": ["kubernetes", "Talos", "openstack", "opentofu", "ansible"],
        "release_terms": ["kubernetes", "helm", "talos"],
        "match_tokens": ["kubernetes", "k8s", "kubectl", "helm", "talos",
                         "kubelet", "etcd"],
    },
    {
        "key": "npm_node", "vendor": "npm / Node.js",
        "subreddits": ["node", "node.js", "javascript", "typescript",
                       "reactjs", "Deno", "angular", "vue.js"],
        "release_terms": ["node", "npm", "deno", "typescript"],
        "match_tokens": ["node", "nodejs", "node.js", "npm", "deno",
                         "typescript", "javascript"],
    },
    {
        "key": "pip_python", "vendor": "pip / Python",
        "subreddits": ["python", "Python", "django", "FastAPI", "pandas"],
        "release_terms": ["python", "cpython", "django", "pip"],
        "match_tokens": ["python", "cpython", "pypi", "pip", "django",
                         "fastapi", "pandas"],
    },
    {
        "key": "cargo_rust", "vendor": "cargo / Rust",
        "subreddits": ["rust", "tauri", "rustdesk"],
        "release_terms": ["rust", "cargo", "tauri"],
        "match_tokens": ["rust", "cargo", "crates.io", "rustc", "tauri"],
    },
    {
        "key": "homeassistant", "vendor": "Home Assistant / smart home",
        "subreddits": ["homeassistant", "homeautomation", "smarthome",
                       "openhab", "ZigBee", "MQTT", "esp32"],
        "release_terms": ["home assistant", "esphome", "zigbee2mqtt", "openhab"],
        "match_tokens": ["home assistant", "homeassistant", "esphome",
                         "zigbee", "openhab", "hass"],
    },
    {
        "key": "nas_selfhosted", "vendor": "NAS / self-hosted",
        "subreddits": ["truenas", "unRAID", "NextCloud", "ZimaOS", "netapp",
                       "homelab", "immich", "Syncthing"],
        "release_terms": ["truenas", "nextcloud", "synology", "unraid", "immich"],
        "match_tokens": ["truenas", "nextcloud", "synology", "unraid",
                         "immich", "syncthing", "zimaos", "netapp", "freenas"],
    },
    {
        "key": "wordpress", "vendor": "WordPress",
        "subreddits": ["wordpress", "Wordpress", "php", "joomla", "laravel"],
        "release_terms": ["wordpress", "woocommerce"],
        "match_tokens": ["wordpress", "woocommerce", "wp", "elementor"],
    },
    {
        "key": "postgres", "vendor": "PostgreSQL",
        "subreddits": ["postgresql", "PostgreSQL", "Supabase"],
        "release_terms": ["postgresql", "postgres", "supabase"],
        "match_tokens": ["postgresql", "postgres", "pgsql", "psql", "supabase"],
    },
    {
        "key": "mysql", "vendor": "MySQL / SQL",
        "subreddits": ["mysql", "sqlite", "SQL", "sql-server", "oracle-database"],
        "release_terms": ["mysql", "mariadb", "sqlite"],
        "match_tokens": ["mysql", "mariadb", "sqlite", "sql server", "mssql"],
    },
    {
        "key": "nosql", "vendor": "MongoDB / Redis / search",
        "subreddits": ["redis", "elasticsearch", "minio", "ceph"],
        "release_terms": ["mongodb", "redis", "elasticsearch", "valkey"],
        "match_tokens": ["mongodb", "mongo", "redis", "valkey",
                         "elasticsearch", "opensearch", "minio"],
    },
    {
        "key": "llm_ai", "vendor": "LLM / AI models",
        "subreddits": ["ollama", "comfyui", "Vllm", "LangChain", "unsloth",
                       "transformers", "opencode", "openclaw", "LobeHub"],
        "release_terms": [],   # mined from the product catalogue instead
        "match_tokens": ["llama", "gpt", "claude", "gemini", "mistral",
                         "qwen", "deepseek", "ollama", "gemma", "grok"],
    },
    {
        "key": "devtools", "vendor": "Editors / dev tooling",
        "subreddits": ["vscode", "visual-studio-code", "neovim", "git",
                       "github", "intellij-idea", "grafana"],
        "release_terms": ["git", "grafana", "neovim", "gitlab"],
        "match_tokens": ["git", "gitlab", "github", "grafana", "neovim",
                         "vscode", "visual studio code", "jetbrains"],
    },
]

# LLM product-name patterns, matched against /api/c/names.  Only records whose
# versionProductType is literally "LLM" are kept, so a false positive here just
# costs one wasted request.
LLM_NAME_PATTERNS = (
    "gpt-", "claude ", "gemini", "llama ", "mistral ", "qwen", "deepseek",
    "grok", "gemma", "command r", "nova ", "kimi", "glm-", "phi-",
    "sonnet", "opus", "haiku", "o1", "o3",
)

# ─────────────────────────────────────────────────────────────────────────────
# Category classifiers (deterministic regex rules over real post text)
# ─────────────────────────────────────────────────────────────────────────────
SECURITY_RE = re.compile(
    r"cve-\d{4}-\d{3,}|vulnerab|exploit|malware|ransomware|phish|spyware|"
    r"zero[- ]day|0-day|backdoor|rootkit|botnet|"
    r"security (?:update|patch|advisory|fix|flaw|issue|hole|risk|concern)|"
    r"\bbreach|hijack|unauthori[sz]ed|privilege escalation|\brce\b|\bxss\b|"
    r"sql injection|supply chain attack|compromis|keylogger|\bcvss\b|"
    r"data leak|credential", re.I)

RELEASE_RE = re.compile(
    r"\breleased?\b|\breleasing\b|release notes|changelog|\bnew version\b|"
    r"\bupdated? to\b|\bupgraded? to\b|after (?:the )?(?:latest )?update|"
    r"\bis out\b|now available|rolling out|\bnightly\b|"
    r"\blatest version\b|\brolled out\b|\bshipped\b|\bwhat'?s new\b|"
    # A version number, but not a bare two-part decimal -- "$5.46" and "16.04"
    # of prose are not releases. Require a v-prefix or a third component.
    r"\bv\d+\.\d+|\b\d+\.\d+\.\d+", re.I)

BUG_RE = re.compile(
    r"\bbroken?\b|\bcrash|not working|does ?n'?t work|wo ?n'?t (?:start|boot|"
    r"open|load|launch|connect|install|update)|\berrors?\b|\bfail(?:s|ed|ing)?\b|"
    r"\bfreez|\bstuck\b|\bregression\b|\bbugs?\b|\bglitch|\bhangs?\b|"
    r"black screen|no longer|stopped working|\bbroke\b|\bcorrupt|"
    r"\bkeeps? (?:crashing|failing|resetting|disconnecting)\b", re.I)

COMMUNITY_RE = re.compile(
    r"anyone else|thoughts\?|\bopinions?\b|what do you|\bdiscussion\b|"
    r"\brecommend|\bbest\b|\bvs\.?\b|\bpoll\b|which (?:one|is better)|"
    r"\bfavou?rite\b|showcase|i (?:made|built|created|wrote)|\bpsa\b|"
    r"worth it|\bexperiences?\b|\bhot take\b|\bam i the only\b|"
    r"\bshare your\b|\bhow do you (?:all|guys)\b", re.I)

QUESTION_RE = re.compile(
    r"\?|^(?:how|what|why|when|where|which|who|can|is|are|does|do|did|should|"
    r"would|could|any|anyone|has|have|will|need|help)\b", re.I)

# Titles that are noise for a retrieval benchmark.
NOISE_RE = re.compile(r"^(?:\[?removed\]?|\[?deleted\]?|test|hi|hello)$", re.I)

# ─────────────────────────────────────────────────────────────────────────────
# CVE advisory parsing
#
# IMPORTANT (verified against the live API): on rows where isCve is true,
# `versionProductName` is NOT the affected product -- it is the ecosystem token
# the row was indexed under.  e.g. an advisory for "Mocha Telnet Lite for iOS
# 4.2" is stored as versionProductName="iOS", versionNumber="4.2.0"; an advisory
# for "Velero 1.18.1" is stored as versionProductName="Kubernetes".
#
# Asking "Is iOS v4.2.0 affected by a known vulnerability?" would therefore be a
# fabricated claim.  So for CVE rows we parse the real affected product and
# version out of the advisory text and SKIP the row when we cannot.  Non-CVE
# rows keep their product name, which is reliable.
# ─────────────────────────────────────────────────────────────────────────────
_VER = r"\d+(?:\.\d+)+(?:[-.\w]*)?"
_NAME = r"[A-Za-z][\w.+\-]*(?:[ /][A-Za-z][\w.+\-]*){0,4}"
CVE_PRODUCT_PATTERNS = [
    re.compile(r"(?:This issue is|is) fixed in (?P<p>%s) (?P<v>%s)" % (_NAME, _VER)),
    re.compile(r"\bin (?P<p>%s)\s*<=\s*(?P<v>%s)" % (_NAME, _VER)),
    re.compile(r"\b(?:found|discovered|identified|detected|determined) in "
               r"(?P<p>%s)\s+(?:up to|prior to|before|through)\s+(?P<v>%s)"
               % (_NAME, _VER)),
    re.compile(r"^(?P<p>%s)\s+versions?\s+(?:prior to|before|through|up to)\s+"
               r"(?P<v>%s)" % (_NAME, _VER)),
    re.compile(r"^(?P<p>%s)\s+versions?\s+(?P<v>%s)\s+through" % (_NAME, _VER)),
    re.compile(r"^(?P<p>%s)\s+(?P<v>%s)\s+contains" % (_NAME, _VER)),
    re.compile(r"^(?P<p>%s)\s+is\s+(?:an?|the)\b.*?"
               r"\b(?:[Pp]rior to(?: version)?|up to and including|before)\s+"
               r"(?P<v>%s)" % (_NAME, _VER), re.S),
    re.compile(r"^Affected versions of (?P<p>%s)\b" % _NAME),
    re.compile(r"^(?P<p>%s)\s+(?:before|prior to)\s+(?P<v>%s)" % (_NAME, _VER)),
    re.compile(r"\bof (?P<p>%s)\s*<\s*(?P<v>%s)" % (_NAME, _VER)),
]
_EDGE_WORDS = {
    "the", "a", "an", "this", "that", "these", "those", "it", "its", "in", "on",
    "for", "and", "or", "versions", "version", "affected", "prior", "issue",
    "vulnerability", "flaw", "attacker", "users", "user", "there", "when",
    "which", "all", "some", "multiple", "several", "use", "using", "before",
    "after", "through", "up", "to", "contains", "contain", "is", "are", "was",
}


def extract_cve_product(notes: str) -> Optional[Tuple[str, str]]:
    """(product, version) actually named by an advisory, or None."""
    text = clean(notes)
    if not text:
        return None
    for pat in CVE_PRODUCT_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        product = m.group("p").strip(" .,:;")
        version = clean(m.groupdict().get("v")).strip(" .,:;")
        words = product.split()
        while words and words[0].lower() in _EDGE_WORDS:
            words = words[1:]
        while words and words[-1].lower() in _EDGE_WORDS:
            words = words[:-1]
        product = " ".join(words)
        if not (2 <= len(product) <= 48):
            continue
        if product.lower().startswith("cve-") or re.match(r"^[\d.]+$", product):
            continue
        return product, version
    return None

MIN_Q_LEN = 18
MAX_Q_LEN = 190


# ─────────────────────────────────────────────────────────────────────────────
# HTTP with an on-disk replay cache
# ─────────────────────────────────────────────────────────────────────────────
class Api:
    """Cached, fault-tolerant GET wrapper around the releasetrain.io API."""

    def __init__(self, refresh: bool = False, offline: bool = False):
        self.refresh = refresh
        self.offline = offline
        self.session = requests.Session()
        self.failures: List[Tuple[str, str]] = []     # real endpoint failures
        self.not_catalogued: List[str] = []           # 404 = product not tracked
        self.hits = {"cache": 0, "network": 0, "failed": 0, "not_catalogued": 0}
        os.makedirs(CACHE_DIR, exist_ok=True)

    @staticmethod
    def _key(path: str, params: Optional[dict]) -> str:
        blob = path + "?" + json.dumps(params or {}, sort_keys=True)
        return hashlib.sha1(blob.encode()).hexdigest()[:20]

    def get(self, path: str, params: Optional[dict] = None) -> Any:
        cache_file = os.path.join(CACHE_DIR, self._key(path, params) + ".json")
        if not self.refresh and os.path.exists(cache_file):
            try:
                with open(cache_file) as f:
                    self.hits["cache"] += 1
                    return json.load(f)
            except Exception:
                pass  # corrupt cache entry -> re-fetch
        if self.offline:
            self.failures.append((path + json.dumps(params or {}), "offline, no cache"))
            self.hits["failed"] += 1
            return None
        url = BASE + path
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=TIMEOUT)
                if r.status_code == 404:
                    # Endpoint is up; this product name is simply not in the
                    # catalogue. Not a failure -- recorded for the coverage log.
                    self.not_catalogued.append(path)
                    self.hits["not_catalogued"] += 1
                    return None
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                data = r.json()
                with open(cache_file, "w") as f:
                    json.dump(data, f)
                self.hits["network"] += 1
                return data
            except Exception as exc:
                if attempt == 2:
                    self.failures.append(
                        (url + " " + json.dumps(params or {}), str(exc)[:120]))
                    self.hits["failed"] += 1
                    return None
                time.sleep(1.5 * (attempt + 1))
        return None


def _versions_from(payload: Any) -> List[dict]:
    """Both /api/v/ and /api/c/name/<x> return {key: [records]} shapes."""
    out: List[dict] = []
    if isinstance(payload, dict):
        for _, val in sorted(payload.items()):
            if isinstance(val, list):
                out.extend([v for v in val if isinstance(v, dict)])
    elif isinstance(payload, list):
        out = [v for v in payload if isinstance(v, dict)]
    return out


def _posts_from(payload: Any) -> List[dict]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return [p for p in payload["data"] if isinstance(p, dict)]
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    return []


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────────────────────────────────────
def clean(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def norm_query(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", q.lower()).strip()


def token_hit(text: str, tokens: Sequence[str]) -> bool:
    for tok in tokens:
        if re.search(r"(?<![a-z0-9])" + re.escape(tok) + r"(?![a-z0-9])", text):
            return True
    return False


def fmt_date(raw: Any) -> str:
    """ISO (YYYY-MM-DD) date, or "" when the field is not a date we can trust.

    The feed carries corrupt values ("23.30.13102017", "2025[29]0213"). The
    previous version passed anything it could not convert straight through to
    the caller, which then asserted it as fact -- the shipped benchmark
    contains the *ground truth* "published on 23.30.13102017". A ground truth
    stating a date that does not exist is worse than one that omits the date,
    so an unparseable value yields "" and the caller drops the clause.
    """
    d = clean(raw)
    iso = ""
    if len(d) == 8 and d.isdigit():
        iso = f"{d[:4]}-{d[4:6]}-{d[6:]}"
    else:
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", d)
        if m:
            iso = m.group(0)
    if not iso:
        return ""
    try:
        parsed = datetime.date(int(iso[:4]), int(iso[5:7]), int(iso[8:]))
    except ValueError:
        return ""                       # e.g. month 13, day 32
    if not (1990 <= parsed.year <= 2100):
        return ""
    return iso


def usable_title(title: str) -> bool:
    if not (MIN_Q_LEN <= len(title) <= MAX_Q_LEN):
        return False
    if NOISE_RE.match(title):
        return False
    # Needs at least four words to be a meaningful retrieval query.
    return len(title.split()) >= 4


def classify_post(title: str, body: str, num_comments: int,
                  is_about_cve: Any) -> str:
    """Deterministic single-label classification of a real Reddit post.

    The feed's own `isAboutCve` flag is deliberately NOT trusted on its own --
    it fires on posts like "Best budget AI subscription / API tokens?" -- so a
    post only lands in `security` when its own text carries a security signal.
    """
    text = f"{title} {body}"
    if SECURITY_RE.search(text):
        return "security"
    if BUG_RE.search(title):
        return "bugs"
    if RELEASE_RE.search(title):
        return "releases"
    if COMMUNITY_RE.search(title) or num_comments >= 12:
        return "community"
    if BUG_RE.search(text):
        return "bugs"
    return "general"


# ─────────────────────────────────────────────────────────────────────────────
# Miners
# ─────────────────────────────────────────────────────────────────────────────
def mine_reddit(api: Api, eco: Dict[str, Any]) -> List[dict]:
    """Real posts from this ecosystem's subreddits."""
    q = ",".join(eco["subreddits"])
    posts: List[dict] = []
    for page in range(1, REDDIT_PAGES + 1):
        payload = api.get("/api/reddit/by-subreddit",
                          {"q": q, "limit": 200, "page": page})
        batch = _posts_from(payload)
        if not batch:
            break
        posts.extend(batch)
    return posts


def mine_global_reddit(api: Api) -> List[dict]:
    """Cross-ecosystem pools: user questions, positive posts, CVE chatter."""
    posts: List[Tuple[str, dict]] = []
    for page in range(1, QUESTION_PAGES + 1):
        for p in _posts_from(api.get("/api/reddit/query/questions",
                                     {"page": page, "limit": 100})):
            posts.append(("/api/reddit/query/questions", p))
    for p in _posts_from(api.get("/api/reddit/query/positive")):
        posts.append(("/api/reddit/query/positive", p))
    for term in ["CVE-", "security update", "vulnerability", "patch"]:
        for p in _posts_from(api.get("/api/reddit/query/cve",
                                     {"q": term, "limit": 200})):
            posts.append(("/api/reddit/query/cve", p))
    return posts


def mine_versions(api: Api, eco: Dict[str, Any]) -> List[dict]:
    """Real version records for this ecosystem, verified by product tokens."""
    found: Dict[str, dict] = {}
    for term in eco["release_terms"]:
        for endpoint, payload in (
            ("/api/v/search", api.get("/api/v/search", {"q": term})),
            ("/api/c/name", api.get(f"/api/c/name/{term}")),
        ):
            for v in _versions_from(payload):
                vid = clean(v.get("versionId"))
                if not vid or vid in found:
                    continue
                haystack = " ".join([
                    clean(v.get("versionProductName")),
                    clean(v.get("versionProductBrand")),
                    " ".join(str(t) for t in (v.get("versionSearchTags") or [])),
                ]).lower()
                if not token_hit(haystack, eco["match_tokens"]):
                    continue
                v = dict(v)
                v["_endpoint"] = endpoint
                found[vid] = v
    return [found[k] for k in sorted(found)]


def mine_llm_versions(api: Api) -> List[dict]:
    """Real LLM/AI model release records, via the live product catalogue."""
    names = api.get("/api/c/names")
    if not isinstance(names, list):
        return []
    cands = sorted({n for n in names if isinstance(n, str)
                    and any(p in n.lower() for p in LLM_NAME_PATTERNS)})
    found: Dict[str, dict] = {}
    for name in cands:
        for v in _versions_from(api.get(f"/api/c/name/{name}")):
            if str(v.get("versionProductType", "")).upper() != "LLM":
                continue
            vid = clean(v.get("versionId"))
            if vid and vid not in found:
                v = dict(v)
                v["_endpoint"] = "/api/c/name"
                found[vid] = v
    return [found[k] for k in sorted(found)]


def mine_global_versions(api: Api) -> List[dict]:
    out = []
    for v in _versions_from(api.get("/api/v/")):
        v = dict(v)
        v["_endpoint"] = "/api/v/"
        out.append(v)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Candidate construction
# ─────────────────────────────────────────────────────────────────────────────
RELEASE_TEMPLATES = [
    "What changed in {label} {version}?",
    "When was {label} {version} released and on which channel?",
    "What is in the release notes for {label} {version}?",
    "Is {label} {version} the latest release, or is there a newer one?",
    "Should I upgrade to {label} {version}?",
    "What release channel did {label} {version} ship on?",
]

SECURITY_TEMPLATES = [
    "What vulnerability was disclosed in {label} {version}?",
    "Is {label} {version} affected by a published security advisory?",
    "What is the security impact of the advisory filed against {label} {version}?",
    "Do I need to patch {label} {version}, and what does the advisory say?",
    "Which release fixes the vulnerability reported in {label} {version}?",
]

# Used when the record carries no version distinct from the product name
# (LLM/model rows store the model name in versionNumber).
RELEASE_TEMPLATES_NOVER = [
    "What changed in the latest {label} release?",
    "When was the most recent {label} release published, and on which channel?",
    "What is in the release notes for the current {label} release?",
    "Is {label} still being updated, and what is its newest release?",
]
SECURITY_TEMPLATES_NOVER = [
    "What vulnerability was disclosed for {label}?",
    "Is {label} affected by a published security advisory?",
    "What is the security impact of the advisory filed against {label}?",
]

BACKFILL_TEMPLATES = {
    "releases": "What is the most recent {vendor} release and what changed in it?",
    "bugs": "What regressions or breakages have been reported after the latest {vendor} update?",
    "security": "Are there any open security advisories affecting {vendor} right now?",
    "community": "What is the community reaction to the latest {vendor} update?",
    "general": "How do I check which {vendor} version I am running and whether it is current?",
}


def version_label(v: dict) -> str:
    brand = clean(v.get("versionProductBrand"))
    name = clean(v.get("versionProductName"))
    if brand and name and brand.lower() not in name.lower():
        return f"{brand} {name}"
    return name or brand or "the product"


def reddit_candidate(post: dict, eco_key: str, vendor: str,
                     endpoint: str) -> Optional[dict]:
    title = clean(post.get("title"))
    if not usable_title(title):
        return None
    rid = clean(post.get("redditId")) or clean(post.get("_id"))
    if not rid:
        return None
    body = clean(post.get("author_description"))[:600]
    try:
        ncom = int(post.get("num_comments") or 0)
    except (TypeError, ValueError):
        ncom = 0
    category = classify_post(title, body, ncom, post.get("isAboutCve"))
    # Quality: prefer question-shaped, engaged, information-dense titles.
    quality = (
        (3 if QUESTION_RE.search(title) else 0)
        + min(ncom, 20) / 10.0
        + (1 if body else 0)
        + (1 if 30 <= len(title) <= 140 else 0)
        # The feed's CVE flag is a weak signal, so it only breaks ties inside
        # the security bucket rather than deciding membership.
        + (1 if (category == "security" and post.get("isAboutCve") is True) else 0)
    )
    return {
        "query": title,
        "category": category,
        "ecosystem": eco_key,
        "vendor": vendor,
        "reddit_id": rid,
        "url": clean(post.get("url")) or None,
        "source": "mined_reddit_title",
        "source_endpoint": endpoint,
        "source_id": rid,
        "mined": True,
        "subreddit": clean(post.get("subreddit")) or None,
        "ground_truth": None,
        "context": (body[:300] or None),
        "released": clean(post.get("created_utc"))[:10] or None,
        "_quality": quality,
        "_sortkey": rid,
    }


def _eco_for_product(product: str) -> Optional[Dict[str, Any]]:
    """First ecosystem whose distinctive tokens appear in a product name."""
    low = product.lower()
    for e in ECOSYSTEMS:
        if token_hit(low, e["match_tokens"]):
            return e
    return None


def _release_year(v: dict) -> Optional[int]:
    """Year of a version record, or None when the date field is malformed.

    The feed contains a few rows with corrupt dates ("23.30.13102017",
    "2025[29]0213"). Those are dropped rather than reported as fact.
    """
    d = clean(v.get("versionReleaseDate"))
    if len(d) == 8 and d.isdigit():
        year = int(d[:4])
        if 1990 <= year <= 2100:
            return year
    return None


def version_candidate(v: dict, eco_key: str, vendor: str,
                      rng: random.Random) -> Optional[dict]:
    vid = clean(v.get("versionId"))
    if not vid:
        return None
    year = _release_year(v)
    if year is None:
        return None                          # corrupt date -> unusable as fact
    notes = clean(v.get("versionReleaseNotes"))
    date = fmt_date(v.get("versionReleaseDate"))
    channel = clean(v.get("versionReleaseChannel")) or "unspecified"
    notes_is_url = notes.startswith("http")

    if v.get("isCve"):
        # The stored product name is an index token, not the affected product.
        parsed = extract_cve_product(notes)
        if not parsed:
            return None                      # unparseable -> do not guess
        label, version = parsed
        # Only keep the advisory when the *real* product it names belongs to a
        # tracked ecosystem. Trusting the feed's own index token here is what
        # produced "Is iOS v4.2.0 vulnerable?" for a Mocha Telnet advisory.
        owner = _eco_for_product(label)
        if owner is None:
            return None
        eco_key, vendor = owner["key"], owner["vendor"]
        category = "security"
        templates, templates_nover = SECURITY_TEMPLATES, SECURITY_TEMPLATES_NOVER
    else:
        label = version_label(v)
        version = clean(v.get("versionNumber"))
        if not label or label == "the product":
            return None
        if not re.match(r"^[A-Za-z0-9][\w.\-+ ]{0,40}$", version or ""):
            return None                      # malformed version string
        category = "releases"
        templates, templates_nover = RELEASE_TEMPLATES, RELEASE_TEMPLATES_NOVER

    # Model records store the model name in versionNumber ("GPT-5.3"), so guard
    # against rendering "OpenAI GPT-5.3 GPT-5.3".
    if version and version.lower() not in label.lower():
        shown = f"v{version}" if re.match(r"^\d", version) else version
        tmpl = templates[rng.randrange(len(templates))]
        query = tmpl.format(label=label, version=shown)
    else:
        tmpl = templates_nover[rng.randrange(len(templates_nover))]
        query = tmpl.format(label=label)
    if not (MIN_Q_LEN <= len(query) <= MAX_Q_LEN):
        return None

    gt = f"{label} {version}".strip() if version else label
    # Only assert the date when it parsed; see fmt_date.
    if date:
        gt += f" - published {date} on the {channel} channel."
    else:
        gt += f" - published on the {channel} channel."
    if notes and not notes_is_url:
        gt += f" {notes[:320]}"
    # An update-monitoring benchmark cares about current software, so prefer
    # recent records over a 2004 Firefox 1.0 row.
    recency = 3 if year >= 2026 else 2 if year >= 2025 else 1 if year >= 2023 else 0
    return {
        "query": query,
        "category": category,
        "ecosystem": eco_key,
        "vendor": vendor,
        "reddit_id": None,
        "url": notes if notes_is_url else None,
        "source": "mined_release_record",
        "source_endpoint": v.get("_endpoint", "/api/v/"),
        "source_id": vid,
        "mined": True,
        "subreddit": None,
        "ground_truth": gt,
        "context": (notes[:300] if notes and not notes_is_url else None),
        "released": date,
        "_quality": (2 if notes and not notes_is_url else 0)
                    + (1 if version else 0) + recency,
        "_sortkey": vid,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Build
# ─────────────────────────────────────────────────────────────────────────────
def build(api: Api, total: int = TOTAL, seed: int = SEED) -> Tuple[List[dict], dict]:
    rng = random.Random(seed)
    eco_order = [e["key"] for e in ECOSYSTEMS]
    eco_by_key = {e["key"]: e for e in ECOSYSTEMS}

    # subreddit (lowercased) -> ecosystem key, first definition wins
    sub_to_eco: Dict[str, str] = {}
    for e in ECOSYSTEMS:
        for s in e["subreddits"]:
            sub_to_eco.setdefault(s.lower(), e["key"])

    # pools[ecosystem][category][source] -> candidates.  Keeping the two
    # provenance classes apart lets the selector interleave them, so the
    # release/CVE APIs are actually exercised instead of being crowded out by
    # the (much larger) Reddit pools.
    SRC_ORDER = ["mined_release_record", "mined_reddit_title"]
    pools: Dict[str, Dict[str, Dict[str, List[dict]]]] = {
        k: {c: {s: [] for s in SRC_ORDER} for c in CATEGORIES}
        for k in eco_order}
    seen_ids: set = set()
    stats = {"reddit_posts_seen": 0, "version_records_seen": 0}

    def add(cand: Optional[dict]) -> None:
        if not cand:
            return
        sid = cand["source_id"]
        if sid in seen_ids:
            return
        seen_ids.add(sid)
        pools[cand["ecosystem"]][cand["category"]][cand["source"]].append(cand)

    print("  Mining per-ecosystem Reddit + release records ...")
    for e in ECOSYSTEMS:
        posts = mine_reddit(api, e)
        stats["reddit_posts_seen"] += len(posts)
        for p in posts:
            add(reddit_candidate(p, e["key"], e["vendor"],
                                 "/api/reddit/by-subreddit"))
        versions = mine_versions(api, e)
        stats["version_records_seen"] += len(versions)
        for v in versions:
            add(version_candidate(v, e["key"], e["vendor"], rng))
        n = sum(len(pools[e["key"]][c][s])
                for c in CATEGORIES for s in SRC_ORDER)
        print(f"    {e['key']:16s} posts={len(posts):4d} versions={len(versions):5d} "
              f"candidates={n:4d}")

    print("  Mining LLM / AI model release records ...")
    llm = mine_llm_versions(api)
    stats["version_records_seen"] += len(llm)
    for v in llm:
        add(version_candidate(v, "llm_ai", eco_by_key["llm_ai"]["vendor"], rng))
    print(f"    llm_ai           model release records={len(llm)}")

    print("  Mining cross-ecosystem Reddit pools ...")
    extra = mine_global_reddit(api)
    stats["reddit_posts_seen"] += len(extra)
    mapped = 0
    for endpoint, p in extra:
        key = sub_to_eco.get(clean(p.get("subreddit")).lower())
        if not key:
            continue
        mapped += 1
        add(reddit_candidate(p, key, eco_by_key[key]["vendor"], endpoint))
    print(f"    {len(extra)} posts fetched, {mapped} mapped to a tracked ecosystem")

    print("  Mining the global /api/v/ feed ...")
    gv = mine_global_versions(api)
    stats["version_records_seen"] += len(gv)
    matched = 0
    for v in gv:
        haystack = " ".join([
            clean(v.get("versionProductName")),
            clean(v.get("versionProductBrand")),
            " ".join(str(t) for t in (v.get("versionSearchTags") or [])),
        ]).lower()
        for e in ECOSYSTEMS:
            if token_hit(haystack, e["match_tokens"]):
                matched += 1
                add(version_candidate(v, e["key"], e["vendor"], rng))
                break
    print(f"    {len(gv)} version records fetched, {matched} attributed")

    # Stable, quality-first ordering inside every sub-pool.
    for k in eco_order:
        for c in CATEGORIES:
            for s in SRC_ORDER:
                pools[k][c][s].sort(key=lambda d: (-d["_quality"], d["_sortkey"]))

    # ── Selection ────────────────────────────────────────────────────────────
    per_cat = total // len(CATEGORIES)
    selected: List[dict] = []
    used_queries: set = set()
    backfilled: List[Tuple[str, str]] = []
    cursor = {(k, c, s): 0 for k in eco_order for c in CATEGORIES
              for s in SRC_ORDER}
    eco_rank_of = {k: i for i, k in enumerate(eco_order)}
    draws = Counter()   # (eco, cat) -> how many taken so far, drives alternation

    def _take_from(eco_key: str, cat: str, src: str) -> Optional[dict]:
        pool = pools[eco_key][cat][src]
        i = cursor[(eco_key, cat, src)]
        while i < len(pool):
            cand = pool[i]
            i += 1
            nq = norm_query(cand["query"])
            if nq in used_queries:
                continue
            cursor[(eco_key, cat, src)] = i
            used_queries.add(nq)
            return cand
        cursor[(eco_key, cat, src)] = i
        return None

    def take(eco_key: str, cat: str) -> Optional[dict]:
        """Alternate release-record / Reddit provenance within a cell.

        Only `releases` and `security` have release-record candidates at all
        (a version record is never a bug report or a community thread), so the
        alternation is a no-op for the other three categories.
        """
        n = draws[(eco_key, cat)]
        order = (SRC_ORDER if n % 2 == 0 else list(reversed(SRC_ORDER)))
        for src in order:
            cand = _take_from(eco_key, cat, src)
            if cand:
                draws[(eco_key, cat)] += 1
                return cand
        return None

    eco_totals: Counter = Counter()

    for cat in CATEGORIES:
        chosen: List[dict] = []
        # Pass 1: guarantee every ecosystem is represented in every category.
        for key in eco_order:
            if len(chosen) >= per_cat:
                break
            cand = take(key, cat)
            if cand:
                chosen.append(cand)
                eco_totals[key] += 1
            else:
                backfilled.append((key, cat))
        # Pass 2: top up, always giving the next slot to the ecosystem that
        # currently has the fewest questions overall (ties by config order).
        while len(chosen) < per_cat:
            order = sorted(eco_order, key=lambda k: (eco_totals[k], eco_rank_of[k]))
            progressed = False
            for key in order:
                if len(chosen) >= per_cat:
                    break
                cand = take(key, cat)
                if cand:
                    chosen.append(cand)
                    eco_totals[key] += 1
                    progressed = True
                    break        # re-sort so the next slot goes to the new min
            if not progressed:
                break
        selected.extend(chosen)

    # ── Explicit, logged backfill for cells with no live record ─────────────
    backfill_records: List[dict] = []
    for key, cat in backfilled:
        eco = eco_by_key[key]
        query = BACKFILL_TEMPLATES[cat].format(vendor=eco["vendor"])
        nq = norm_query(query)
        if nq in used_queries:
            query = f"{query} ({eco['vendor']} {cat})"
            nq = norm_query(query)
            if nq in used_queries:
                continue
        used_queries.add(nq)
        backfill_records.append({
            "query": query,
            "category": cat,
            "ecosystem": key,
            "vendor": eco["vendor"],
            "reddit_id": None,
            "url": None,
            "source": "backfill_template",
            "source_endpoint": None,
            "source_id": None,
            "mined": False,
            "subreddit": None,
            "ground_truth": None,
            "context": None,
            "released": None,
            "backfill_reason": (
                f"no live {cat} record available for {eco['vendor']} from "
                f"releasetrain.io at build time"),
            "_quality": -1,
            "_sortkey": f"backfill:{key}:{cat}",
        })
    selected.extend(backfill_records)

    # ── Trim / top-up to exactly `total`, keeping categories in band ────────
    if len(selected) > total:
        counts = Counter(r["category"] for r in selected)
        # drop from the largest categories first, backfills before mined rows
        selected.sort(key=lambda r: (r["mined"], -counts[r["category"]]))
        drop = len(selected) - total
        keep = []
        counts_live = Counter(r["category"] for r in selected)
        for r in selected:
            if drop > 0 and counts_live[r["category"]] > total // len(CATEGORIES):
                counts_live[r["category"]] -= 1
                drop -= 1
                continue
            keep.append(r)
        selected = keep[:total] if len(keep) >= total else keep
    if len(selected) < total:
        # Pull whatever live candidates remain, spread across ecosystems.
        cat_counts = Counter(r["category"] for r in selected)
        guard = 0
        while len(selected) < total and guard < 10000:
            guard += 1
            progressed = False
            for cat in sorted(CATEGORIES, key=lambda c: cat_counts[c]):
                for key in eco_order:
                    if len(selected) >= total:
                        break
                    cand = take(key, cat)
                    if cand:
                        selected.append(cand)
                        cat_counts[cat] += 1
                        progressed = True
                        break
                if len(selected) >= total:
                    break
            if not progressed:
                break

    # Deterministic final order: category block, then ecosystem, then source id.
    cat_rank = {c: i for i, c in enumerate(CATEGORIES)}
    eco_rank = {k: i for i, k in enumerate(eco_order)}
    selected.sort(key=lambda r: (cat_rank[r["category"]],
                                 eco_rank[r["ecosystem"]],
                                 str(r["_sortkey"])))

    records = []
    for i, r in enumerate(selected, 1):
        rec = OrderedDict()
        rec["id"] = i
        rec["query"] = r["query"]
        rec["category"] = r["category"]
        rec["ecosystem"] = r["ecosystem"]
        rec["vendor"] = r["vendor"]
        rec["reddit_id"] = r["reddit_id"]
        rec["url"] = r["url"]
        rec["source"] = r["source"]
        rec["source_endpoint"] = r["source_endpoint"]
        rec["source_id"] = r["source_id"]
        rec["mined"] = r["mined"]
        rec["subreddit"] = r["subreddit"]
        rec["date"] = r.get("released")
        rec["ground_truth"] = r["ground_truth"]
        rec["context"] = r["context"]
        if r.get("backfill_reason"):
            rec["backfill_reason"] = r["backfill_reason"]
        records.append(rec)

    # A cell with no live candidate is a *coverage gap*; it only becomes a
    # *backfill* if its template record actually survived into the output.
    emitted_backfills = {(r["ecosystem"], r["category"]) for r in records
                         if r["source"] == "backfill_template"}
    stats["empty_cells"] = sorted(set(backfilled))
    stats["backfilled_cells"] = sorted(emitted_backfills)
    stats["pool_sizes"] = {
        k: {c: {s: len(pools[k][c][s]) for s in SRC_ORDER} for c in CATEGORIES}
        for k in eco_order}
    return records, stats


# ─────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────
def summarize(records: List[dict], stats: dict, api: Api, out_path: str) -> None:
    n = len(records)
    bar = "=" * 72
    print(f"\n{bar}\n  BENCHMARK SUMMARY  —  {out_path}\n{bar}")
    print(f"  Total questions : {n}")

    print("\n  Category breakdown (target 10%-30% each)")
    for cat, c in sorted(Counter(r["category"] for r in records).items(),
                         key=lambda kv: -kv[1]):
        pct = 100.0 * c / n if n else 0
        flag = "  OK" if 10.0 <= pct <= 30.0 else "  OUT OF BAND"
        print(f"    {cat:12s} {c:4d}  {pct:5.1f}%{flag}")

    eco_counts = Counter(r["ecosystem"] for r in records)
    print(f"\n  Ecosystem breakdown ({len(eco_counts)} distinct)")
    vendor_of = {e["key"]: e["vendor"] for e in ECOSYSTEMS}
    for key, c in sorted(eco_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {key:16s} {c:4d}  {vendor_of.get(key, key)}")

    print("\n  Provenance")
    for src, c in sorted(Counter(r["source"] for r in records).items(),
                         key=lambda kv: -kv[1]):
        print(f"    {src:22s} {c:4d}  {100.0*c/n:5.1f}%")
    mined = sum(1 for r in records if r["mined"])
    print(f"    -> mined live      {mined:4d}")
    print(f"    -> backfilled      {n - mined:4d}")

    print("\n  Endpoints used")
    for ep, c in sorted(Counter(r["source_endpoint"] for r in records
                                if r["source_endpoint"]).items(),
                        key=lambda kv: -kv[1]):
        print(f"    {ep:32s} {c:4d}")

    gt = sum(1 for r in records if r.get("ground_truth"))
    print(f"\n  Records with ground_truth : {gt} of {len(records)} "
          f"-- ONLY THESE ARE SCORED")
    print(f"  ({len(records) - gt} title-mined questions have no gold answer; "
          f"load_benchmark(require_ground_truth=True) drops them.)")
    print(f"  Records with context      : "
          f"{sum(1 for r in records if r.get('context'))}")
    print(f"  API calls  cache={api.hits['cache']} "
          f"network={api.hits['network']} "
          f"not_catalogued(404)={api.hits['not_catalogued']} "
          f"failed={api.hits['failed']}")

    if stats["empty_cells"]:
        print(f"\n  COVERAGE GAPS - no live candidate for this ecosystem x "
              f"category ({len(stats['empty_cells'])}):")
        for key, cat in stats["empty_cells"]:
            emitted = (key, cat) in set(map(tuple, stats["backfilled_cells"]))
            note = "TEMPLATE EMITTED" if emitted else "quota met from other ecosystems, no template kept"
            print(f"    {key:16s} {cat:10s} -> {note}")
    else:
        print("\n  COVERAGE GAPS: none - every ecosystem x category cell had "
              "live candidates.")

    if stats["backfilled_cells"]:
        print(f"\n  BACKFILL TEMPLATES IN OUTPUT ({len(stats['backfilled_cells'])}) "
              f"- these questions are NOT mined:")
        for key, cat in stats["backfilled_cells"]:
            print(f"    {key:16s} {cat}")
    else:
        print(f"\n  BACKFILL TEMPLATES IN OUTPUT: none - all {len(records)} questions are "
              "mined from live data.")

    if api.not_catalogued:
        print(f"\n  PRODUCT NAMES NOT IN THE CATALOGUE (HTTP 404, endpoint "
              f"healthy) - {len(api.not_catalogued)}:")
        for path in sorted(set(api.not_catalogued)):
            print(f"    {path}")

    if api.failures:
        print(f"\n  FAILED REQUESTS ({len(api.failures)}):")
        for url, err in api.failures[:25]:
            print(f"    {err:24s} {url[:90]}")
        if len(api.failures) > 25:
            print(f"    ... and {len(api.failures) - 25} more")
    else:
        print("\n  FAILED REQUESTS: none - every endpoint answered.")
    print(bar)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--total", type=int, default=TOTAL)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--refresh", action="store_true",
                    help="ignore the response cache and re-mine the live APIs")
    ap.add_argument("--offline", action="store_true",
                    help="use only the response cache, never the network")
    args = ap.parse_args(argv)

    if args.refresh and args.offline:
        print("ERROR: --refresh and --offline are mutually exclusive")
        return 2

    print("=" * 72)
    print("  Building multi-ecosystem benchmark from live releasetrain.io APIs")
    print(f"  seed={args.seed}  total={args.total}  "
          f"ecosystems={len(ECOSYSTEMS)}  categories={len(CATEGORIES)}")
    print(f"  mode={'refresh' if args.refresh else 'offline' if args.offline else 'cache-first'}")
    print("=" * 72)

    api = Api(refresh=args.refresh, offline=args.offline)

    # Coverage log only - which of the tracked subreddits the API actually has.
    meta = api.get("/api/reddit/meta/subreddits")
    available = {s.lower() for s in (meta or {}).get("data", [])
                 if isinstance(s, str)}
    if available:
        wanted = sorted({s.lower() for e in ECOSYSTEMS for s in e["subreddits"]})
        missing = [s for s in wanted if s not in available]
        print(f"  Subreddit catalogue: {len(available)} available, "
              f"{len(wanted) - len(missing)}/{len(wanted)} tracked subs present")
        if missing:
            print(f"  Tracked subs not in catalogue: {', '.join(missing)}")

    records, stats = build(api, total=args.total, seed=args.seed)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
        f.write("\n")

    manifest = {
        "generated_by": os.path.basename(__file__),
        "seed": args.seed,
        "total": len(records),
        "categories": dict(Counter(r["category"] for r in records)),
        "ecosystems": dict(Counter(r["ecosystem"] for r in records)),
        "vendors": dict(Counter(r["vendor"] for r in records)),
        "sources": dict(Counter(r["source"] for r in records)),
        "mined": sum(1 for r in records if r["mined"]),
        "backfilled": sum(1 for r in records if not r["mined"]),
        # Only records carrying a gold answer are scorable: load_benchmark()
        # drops the rest (`require_ground_truth=True`), so a --benchmark run
        # over this file reports over `scorable`, not over `total`. Recorded
        # here so the headline "300-question benchmark" cannot be misread as
        # 300 *scored* questions.
        "scorable": sum(1 for r in records if r.get("ground_truth")),
        "scorable_by_source": dict(Counter(
            r["source"] for r in records if r.get("ground_truth"))),
        "backfilled_cells": [list(x) for x in stats["backfilled_cells"]],
        "coverage_gap_cells": [list(x) for x in stats["empty_cells"]],
        "failed_requests": [{"url": u, "error": e} for u, e in api.failures],
        "not_catalogued_404": sorted(set(api.not_catalogued)),
        "api_calls": api.hits,
        "reddit_posts_seen": stats["reddit_posts_seen"],
        "version_records_seen": stats["version_records_seen"],
        "pool_sizes": stats["pool_sizes"],
    }
    manifest_path = os.path.splitext(args.out)[0] + ".manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")

    summarize(records, stats, api, args.out)
    print(f"  Wrote {len(records)} records -> {args.out}")
    print(f"  Wrote manifest              -> {manifest_path}")
    return 0 if len(records) == args.total else 1


if __name__ == "__main__":
    sys.exit(main())
