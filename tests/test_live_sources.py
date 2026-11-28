"""live_sources: question types the feeds can't answer, each from a fixed live
source. Console only; offline here (every fetch is substituted)."""
import os
import pathlib
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import live_sources as L  # noqa: E402
import websearch  # noqa: E402


# ─────────────────────────────────────────────── Task 2: classifier

@pytest.mark.parametrize("q,want", [
    ("Is the requests package safe to use?", "package_safety"),
    ("is lodash npm safe", "package_safety"),
    ("Is requests 2.31.0 safe? (pip)", "package_safety"),
    ("Is GitHub down?", "down_now"),
    ("is openai down right now", "down_now"),
    ("What was the Microsoft outage about?", "incident"),
    ("Is Azure down?", "incident"),            # no status host -> incident
    ("Is Python 3.9 still supported?", "eol"),
    ("When is Node 20 end of life?", "eol"),
    ("Should I use Postgres or MySQL for a new project?", "compare"),
    ("Does Django 5 support Python 3.13?", "compat"),
    ("How do I fix EACCES on npm install?", "howto"),
    ("What is the latest Linux version?", None),
    ("Any critical CVEs in Chrome?", None),
    ("Is zoom better or teams?", "compare"),
    ("What happened to Microsoft recently?", "news"),
    ("Any news about Slack?", "news"),
    ("What's going on with Blockify?", "news"),
    ("What is Kubernetes?", "general"),
    ("How does Upsert work?", "general"),
    ("Why does Linux not need anti-virus software?", "general"),
    ("What is the latest Chrome version?", None),          # release intent
    ("What is CVE-2024-1234?", None),                      # update cue
    ("Why is Chrome not updating?", None),                 # update cue
    ("iOS 26.3 WiFi/RAM issues?", None),                   # update report, no general cue
    ("Latest Node.js version?", None),                     # release intent
    ("What happened during the GitHub outage?", "incident"),  # precedence
    # Review 2026-11-22: security and breakage reports phrased without the
    # classifier's cues must keep the feed verdict, not become news/general.
    ("Was Chrome hacked recently?", None),
    ("What happened with the Chrome 0day?", None),
    ("Any news on the OpenSSL bug?", None),
    ("Why is Windows Defender flagging Chrome?", None),
    ("What happened to Chrome passwords?", None),
    ("Recently installed Ubuntu 26.04 and wifi broke", None),
    ("Any recent problems with iOS 26.1?", None),
    ("Recent Chrome issues?", None),
    ("Is Chrome broken lately?", None),
    ("Why is Windows 11 so slow lately?", None),
    ("Why is Windows 11 24H2 breaking printers?", None),
    ("What is the Windows 11 24H2 bug?", None),
    ("Why is Firefox crashing?", None),
    ("What is Chrome 131?", None),
    ("What are the changes in Chrome 131?", None),
])
def test_kind(q, want):
    assert L.kind(q) == want


def test_package_safety_never_fires_for_a_catalog_vendor():
    assert L.kind("Is the firefox package safe?", vendors=["firefox"]) != "package_safety"


def test_safe_to_update_without_package_cue_is_not_package_safety():
    assert L.kind("Is it safe to update Firefox right now?") is None


def test_precedence_down_now_over_compare():
    assert L.kind("Is GitHub down, should I switch to GitLab?") == "down_now"


@pytest.mark.parametrize("q,want", [
    ("Is the requests package safe to use?", ("requests", None, None)),
    ("Is requests 2.31.0 safe? (pip)", ("requests", "PyPI", "2.31.0")),
    ("npm install left-pad 1.3.0 safe?", ("left-pad", "npm", "1.3.0")),
    ("Is it safe?", None),
])
def test_package_ref(q, want):
    assert L.package_ref(q) == want


def test_frozen_paper_modules_do_not_import_live_sources():
    root = pathlib.Path(L.__file__).parent
    frozen = ["graph.py", "decide.py", "intent.py", "grounding.py", "multiagent_rag_v3.py",
              *[str(p.relative_to(root)) for p in (root / "eval_harness").rglob("*.py")]]
    for f in frozen:
        assert not re.search(r"\bimport live_sources\b|\bfrom live_sources\b",
                             (root / f).read_text()), f


# ─────────────────────────────────────────────── Task 3: answer-only fetchers

def _search_returns(monkeypatch, hits, err=None, seen=None):
    def fake(q, limit=5, timelimit=None, news=False):
        if seen is not None:
            seen.append({"q": q, "timelimit": timelimit, "news": news})
        return list(hits), err
    monkeypatch.setattr(websearch, "search", fake)


def _json_by_url(monkeypatch, table):
    """Stub _get_json: table maps a URL substring to (data, error)."""
    def fake(url, post=None, timeout=10):
        for key, val in table.items():
            if key in url:
                return val
        return None, "HTTP 404"
    monkeypatch.setattr(L, "_get_json", fake)


def test_down_now_reads_status_page(monkeypatch):
    _json_by_url(monkeypatch, {"githubstatus.com": ({"status": {"description": "Partial Outage"},
        "incidents": [{"name": "Actions delayed", "status": "investigating",
                       "updated_at": "2026-11-19T10:00:00Z"}]}, None)})
    docs, meta = L.fetch("down_now", "Is GitHub down?")
    assert meta["resolved"] and meta["error"] is None and meta["source"] == "GitHub status page"
    assert "Partial Outage" in docs[0]["text"] and "Actions delayed" in docs[0]["text"]
    assert docs[0]["label"] == "Status page - githubstatus.com"
    assert docs[0]["text"].startswith("[untrusted:community]")


def test_status_page_failure_falls_back_to_incident(monkeypatch):
    _json_by_url(monkeypatch, {"githubstatus.com": (None, "HTTP 503")})
    _search_returns(monkeypatch, [{"title": "GitHub outage", "body": "b", "url": "https://n.com/a",
                                   "date": "2026-11-19T09:00:00+00:00", "source": "N"}])
    docs, meta = L.fetch("down_now", "Is GitHub down?")
    assert docs and "HTTP 503" in meta["error"]


def test_incident_newest_first_with_dates(monkeypatch):
    seen = []
    _search_returns(monkeypatch, [
        {"title": "old", "body": "b", "url": "https://a.com/1", "date": "2026-11-01T00:00:00+00:00", "source": "A"},
        {"title": "new", "body": "b", "url": "https://v.com/2", "date": "2026-11-17T22:01:21+00:00", "source": "The Verge"},
    ], seen=seen)
    docs, meta = L.fetch("incident", "What was the Microsoft outage about?")
    assert [d["title"] for d in docs] == ["new", "old"]
    assert docs[0]["label"] == "News - The Verge, 2026-11-17" and docs[0]["date"] == "2026-11-17"
    assert seen[0] == {"q": "What was the Microsoft outage about?", "timelimit": "m", "news": True}
    assert meta["source"] == "DuckDuckGo news, last month" and not meta["resolved"]


def test_incident_undated_hit_sorts_last(monkeypatch):
    _search_returns(monkeypatch, [
        {"title": "undated", "body": "b", "url": "https://a.com/1", "source": "A"},
        {"title": "dated", "body": "b", "url": "https://b.com/2", "date": "2026-11-10T00:00:00+00:00", "source": "B"},
    ])
    docs, _ = L.fetch("incident", "Microsoft outage")
    assert [d["title"] for d in docs] == ["dated", "undated"]
    assert docs[1]["label"] == "News - A"


def test_incident_falls_back_to_text_when_news_is_empty(monkeypatch):
    seen = []
    def fake(q, limit=5, timelimit=None, news=False):
        seen.append(news)
        return ([] if news else [{"title": "t", "body": "b", "href": "https://w.org/x"}]), None
    monkeypatch.setattr(websearch, "search", fake)
    docs, _ = L.fetch("incident", "Microsoft outage")
    assert seen == [True, False] and docs[0]["label"] == "Web - w.org"


PY = [{"cycle": "3.10", "eol": "2026-10-31", "latest": "3.10.19"},
      {"cycle": "3.9", "eol": "2025-10-31", "latest": "3.9.25"}]


def test_eol_reads_cycle(monkeypatch):
    L._eol_slugs.cache_clear()
    _json_by_url(monkeypatch, {"all.json": (["python", "nodejs"], None), "/python.json": (PY, None)})
    docs, meta = L.fetch("eol", "Is Python 3.9 still supported?")
    assert meta["resolved"] and meta["source"] == "endoflife.date"
    assert "Python 3.9: support ended 2025-10-31 (" in docs[0]["text"]
    assert "latest 3.9.25" in docs[0]["text"]
    assert docs[0]["label"] == "endoflife.date - python 3.9"


def test_eol_alias_postgres(monkeypatch):
    L._eol_slugs.cache_clear()
    asked = []
    def fake(url, post=None, timeout=10):
        asked.append(url)
        if url.endswith("all.json"):
            return ["postgresql"], None
        return [{"cycle": "13", "eol": "2025-11-13", "latest": "13.22"}], None
    monkeypatch.setattr(L, "_get_json", fake)
    docs, meta = L.fetch("eol", "Is Postgres 13 still supported?")
    assert asked[-1] == "https://endoflife.date/api/postgresql.json" and meta["resolved"]


def test_eol_unknown_slug_falls_back_to_web(monkeypatch):
    L._eol_slugs.cache_clear()
    _json_by_url(monkeypatch, {"all.json": (["python"], None)})
    seen = []
    _search_returns(monkeypatch, [{"title": "Bun EOL", "body": "b", "href": "https://bun.sh/x"}], seen=seen)
    docs, meta = L.fetch("eol", "Is Bun 1.2 still supported?")
    assert seen[0]["q"] == "bun end of life" and not meta["resolved"] and docs


def test_search_error_reaches_meta(monkeypatch):
    _search_returns(monkeypatch, [], err="search failed: RuntimeError")
    docs, meta = L.fetch("howto", "How do I fix EACCES on npm install?")
    assert docs == [] and meta["error"] == "search failed: RuntimeError"


def test_compat_searches_last_year(monkeypatch):
    seen = []
    _search_returns(monkeypatch, [], seen=seen)
    L.fetch("compat", "Does Django 5 support Python 3.13?")
    assert seen[0]["timelimit"] == "y"


def test_news_searches_news_last_month(monkeypatch):
    seen = []
    _search_returns(monkeypatch, [{"title": "t", "body": "b", "href": "https://n.com/x",
                                   "date": "2026-11-20", "source": "N"}], seen=seen)
    docs, meta = L.fetch("news", "What happened to Microsoft recently?")
    assert seen[0] == {"q": "What happened to Microsoft recently?", "timelimit": "m", "news": True}
    assert meta["kind"] == "news" and docs[0]["label"].startswith("News - ")


def test_news_error_reaches_meta(monkeypatch):
    _search_returns(monkeypatch, [], err="search failed: RatelimitException")
    _, meta = L.fetch("news", "Any news about Slack?")
    assert meta["kind"] == "news" and meta["error"] == "search failed: RatelimitException"


def test_general_is_a_plain_search(monkeypatch):
    seen = []
    _search_returns(monkeypatch, [], seen=seen)
    _, meta = L.fetch("general", "What is Kubernetes?")
    assert seen[0]["news"] is False and seen[0]["timelimit"] is None and meta["kind"] == "general"


def test_news_and_general_replace_the_verdict():
    assert L.answer_only("news", "What happened to Microsoft recently?")
    assert L.answer_only("general", "What is Kubernetes?")


# ─────────────────────────────────────────────── Task 4: package safety (OSV)

REQ = "Is requests 2.31.0 safe? (pip)"


def osv(*vulns):
    return {"vulns": list(vulns)}


FIXED = {"id": "GHSA-9wx4-h78v-vm56", "aliases": ["CVE-2024-35195"], "summary": "Session verify bypass",
         "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}
UNFIXED = {"id": "GHSA-aaaa", "aliases": ["CVE-2026-1"], "summary": "x",
           "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}]}]}]}
NO_CVE = {"id": "PYSEC-2026-1", "aliases": [], "summary": "y",
          "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}
OLD_FIX = {"id": "GHSA-old", "aliases": ["CVE-2018-1"], "summary": "z",   # fix older than the asked version
           "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.20.0"}]}]}]}


@pytest.fixture
def stub(monkeypatch):
    """Stub _get_json by URL substring; `stub.table` is editable, `stub.posts` records OSV bodies."""
    class S:
        table = {"pypi.org/pypi/requests/json": ({"info": {"version": "2.34.2"}}, None),
                 "api.osv.dev": (osv(), None)}
        posts = []

    def fake(url, post=None, timeout=10):
        if post is not None:
            S.posts.append(post)
        for key, val in S.table.items():
            if key in url:
                return val
        return None, "HTTP 404"
    monkeypatch.setattr(L, "_get_json", fake)
    return S


def test_fixed_cve_advisory_reaches_verdict(stub):
    stub.table["api.osv.dev"] = (osv(FIXED), None)
    r = L.package_safety(REQ)
    assert [d["title"] for d in r["verdict_docs"]] == ["GHSA-9wx4-h78v-vm56"]
    v = r["verdict_docs"][0]
    assert v["text"].startswith("requests 2.31.0: ") and "CVE-2024-35195" in v["text"]
    assert "Fixed in 2.32.0." in v["text"] and v["source"] == "cve"
    assert v["url"] == "https://osv.dev/vulnerability/GHSA-9wx4-h78v-vm56"


def test_one_cve_filed_twice_is_one_advisory(stub):
    """Live 2026-11-28: OSV returns a GHSA and a PYSEC entry per CVE, so
    "Is requests 2.31.0 safe?" read "6 advisory document(s)" for 3 CVEs."""
    twin = dict(FIXED, id="PYSEC-2026-1873", aliases=["CVE-2024-35195"])
    stub.table["api.osv.dev"] = (osv(FIXED, twin, NO_CVE), None)
    r = L.package_safety(REQ)
    assert [d["title"] for d in r["verdict_docs"]] == ["GHSA-9wx4-h78v-vm56"]
    assert [d["label"] for d in r["answer_docs"]] == ["OSV - GHSA-9wx4-h78v-vm56", "OSV - PYSEC-2026-1"]


def test_unfixed_advisory_stays_out_of_verdict(stub):
    stub.table["api.osv.dev"] = (osv(UNFIXED), None)
    r = L.package_safety(REQ)
    assert r["verdict_docs"] == []
    assert "requests 2.31.0: unfixed advisory GHSA-aaaa, no fixed release yet" in r["answer_docs"][0]["text"]


def test_fix_older_than_checked_version_is_not_a_fix(stub):
    stub.table["api.osv.dev"] = (osv(OLD_FIX), None)
    r = L.package_safety(REQ)
    assert r["verdict_docs"] == [] and "no fixed release yet" in r["answer_docs"][0]["text"]


def test_no_cve_advisory_is_shown_only(stub):
    stub.table["api.osv.dev"] = (osv(NO_CVE), None)
    r = L.package_safety(REQ)
    assert r["verdict_docs"] == [] and r["answer_docs"][0]["label"] == "OSV - PYSEC-2026-1"


def test_clean_result_is_not_a_green_light(stub):
    r = L.package_safety("Is the requests package safe?")
    assert r["verdict_docs"] == []
    assert "OSV: no known advisories against requests 2.34.2" in r["answer_docs"][0]["text"]
    assert r["meta"]["resolved"] and r["meta"]["error"] is None


def test_question_version_is_checked_not_latest(stub):
    L.package_safety(REQ)
    assert stub.posts[-1] == {"version": "2.31.0", "package": {"name": "requests", "ecosystem": "PyPI"}}


def test_no_ecosystem_prefers_pypi(stub):
    stub.table["registry.npmjs.org/requests/latest"] = ({"version": "0.3.0"}, None)
    r = L.package_safety("Is the requests package safe?")
    assert r["meta"]["source"].startswith("OSV via PyPI")
    assert stub.posts[-1]["package"]["ecosystem"] == "PyPI"


def test_npm_when_only_npm_knows_it(stub):
    stub.table = {"registry.npmjs.org/left-pad/latest": ({"version": "1.3.0"}, None),
                  "api.osv.dev": (osv(), None)}
    r = L.package_safety("Is the left-pad package safe?")
    assert r["meta"]["source"] == "OSV via npm, left-pad 1.3.0"


def test_unknown_package_is_unresolved(stub):
    stub.table = {"api.osv.dev": (osv(), None)}
    r = L.package_safety("Is the zzqq package safe?")
    assert not r["meta"]["resolved"] and r["verdict_docs"] == [] and r["meta"]["error"]
    assert not any("no known advisories" in d["text"] for d in r["answer_docs"])


def test_osv_failure_is_an_error_not_clean(stub):
    stub.table["api.osv.dev"] = (None, "timeout")
    r = L.package_safety("Is the requests package safe?")
    assert r["meta"]["error"] == "timeout" and r["verdict_docs"] == []
    assert not any("no known advisories" in d["text"] for d in r["answer_docs"])


def test_lowest_newer_fix_is_named_in_version_order(stub):
    two = {"id": "GHSA-two", "aliases": ["CVE-2026-2"], "summary": "s",
           "affected": [{"ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "2.10.0"}]},
                                    {"type": "ECOSYSTEM", "events": [{"introduced": "2.31.0"}, {"fixed": "2.9.0"}]}]}]}
    stub.table["api.osv.dev"] = (osv(two), None)
    r = L.package_safety("Is requests 2.8.0 safe? (pip)")
    assert "Fixed in 2.9.0." in r["verdict_docs"][0]["text"]


def test_bare_a_or_b_is_a_comparison():
    assert L.kind("Postgres or MySQL for a new project?") == "compare"
    assert L.kind("React or Vue in 2026?") == "compare"


# ─────────────────────────────────────────────── final review fixes

def test_git_commit_fix_is_not_a_fixed_release(stub):
    """Review #2: PYSEC ranges carry GIT commits; a SHA is not a release."""
    git_only = {"id": "PYSEC-2026-9", "aliases": ["CVE-2026-9"], "summary": "s",
                "affected": [{"ranges": [{"type": "GIT", "repo": "https://github.com/psf/requests",
                                          "events": [{"introduced": "0"},
                                                     {"fixed": "74ea7cf7a6a27a4eeb2ae24e162bcc942a6706d5"}]}]}]}
    stub.table["api.osv.dev"] = (osv(git_only), None)
    r = L.package_safety(REQ)
    assert r["verdict_docs"] == [] and "no fixed release yet" in r["answer_docs"][0]["text"]


def test_fix_for_another_package_does_not_count(stub):
    other = {"id": "GHSA-o", "aliases": ["CVE-2026-8"], "summary": "s",
             "affected": [{"package": {"name": "requests-toolbelt", "ecosystem": "PyPI"},
                           "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": "9.0"}]}]}]}
    stub.table["api.osv.dev"] = (osv(other), None)
    assert L.package_safety(REQ)["verdict_docs"] == []


def test_verdict_row_names_its_cve_and_fix_in_the_paragraph(stub):
    """Review #3: the row behind "Yes, update now" reached the paragraph blank."""
    import answer_agent
    stub.table["api.osv.dev"] = (osv(FIXED), None)
    r = L.package_safety(REQ)
    ev = answer_agent.collect_evidence({"decision_advisories": r["verdict_docs"]})
    assert "CVE-2024-35195" in ev[0].label and "Fixed in 2.32.0" in ev[0].detail


def test_news_publisher_name_is_scrubbed_and_capped(monkeypatch):
    """Review #4: the publisher field sits outside the [untrusted] wrapper."""
    _search_returns(monkeypatch, [{"title": "t", "body": "b", "url": "https://n.com/a",
                                   "date": "2026-11-19T00:00:00+00:00", "source": "Evil\u200b" * 50}])
    docs, _ = L.fetch("incident", "Microsoft outage")
    label = docs[0]["label"]
    assert "\u200b" not in label and len(label) <= len("News - ") + 60 + len(", 2026-11-19")


def test_eol_never_answers_for_a_stray_word(monkeypatch):
    """Review #5: "go" in "should I go with Deno" picked Go, stated as fact."""
    L._eol_slugs.cache_clear()
    _json_by_url(monkeypatch, {"all.json": (["go", "python"], None)})
    seen = []
    _search_returns(monkeypatch, [{"title": "Bun EOL", "body": "b", "href": "https://bun.sh/x"}], seen=seen)
    docs, meta = L.fetch("eol", "Is Bun 1.2 still supported or should I go with Deno?")
    assert not meta["resolved"] and seen[0]["q"] == "bun end of life"


def test_eol_site_down_is_reported_not_called_missing(monkeypatch):
    L._eol_slugs.cache_clear()
    _json_by_url(monkeypatch, {"all.json": (None, "HTTP 503")})
    _search_returns(monkeypatch, [])
    _, meta = L.fetch("eol", "Is Python 3.9 still supported?")
    assert "endoflife.date unreachable" in meta["source"] and "HTTP 503" in meta["error"]


@pytest.mark.parametrize("q,want", [
    ("Is GitHub down?", True), ("Is Python 3.9 still supported?", True),
    ("Does Django 5 support Python 3.13?", True), ("Postgres or MySQL for a new project?", True),
    ("Does Chrome 131 fix CVE-2024-1234?", False),
    ("What does the latest Chrome update fix?", False),
    ("Kernel panic after update - how to fix?", False),
    ("Is Docker Desktop 4.36 safe to update? My container went down", False),
    ("VS Code updated and keeps freezing", False),
])
def test_answer_only_needs_no_update_or_security_words(q, want):
    """Review #1: an update/CVE question that also reads as how-to keeps its verdict."""
    assert L.answer_only(L.kind(q), q) is want



# ─────────────────────────────────────────────── deferred minors

def test_incident_text_hits_clear_the_news_error(monkeypatch):
    def fake(q, limit=5, timelimit=None, news=False):
        return (([], "search failed: RuntimeError") if news
                else ([{"title": "t", "body": "b", "href": "https://w.org/x"}], None))
    monkeypatch.setattr(websearch, "search", fake)
    docs, meta = L.fetch("incident", "Microsoft outage")
    assert docs and meta["error"] is None


def test_incident_reports_the_news_error_when_nothing_came_back(monkeypatch):
    def fake(q, limit=5, timelimit=None, news=False):
        return ([], "search failed: RuntimeError") if news else ([], None)
    monkeypatch.setattr(websearch, "search", fake)
    docs, meta = L.fetch("incident", "Microsoft outage")
    assert docs == [] and meta["error"] == "search failed: RuntimeError"


@pytest.mark.parametrize("q,want", [
    ("Should I use Postgres or MySQL for a new project?", "Postgres vs MySQL"),
    ("Which is better, Rust or Go?", "Rust vs Go"),
    ("is Postgres better than MySQL", "Postgres vs MySQL"),
    ("React vs. Vue in 2026?", "React vs Vue"),
    ("Which one should I pick for a new project?", "Which one should I pick for a new project?"),
])
def test_compare_searches_a_vs_b(monkeypatch, q, want):
    seen = []
    _search_returns(monkeypatch, [], seen=seen)
    L.fetch("compare", q)
    assert seen[0]["q"] == want


@pytest.mark.parametrize("q,want", [("npm install left-pad", True), ("Is the requests package safe?", True),
                                    ("How do I bake bread?", False)])
def test_has_package_cue(q, want):
    assert L.has_package_cue(q) is want


@pytest.mark.parametrize("pkg", ["lodash", "express", "django"])
def test_catalog_vendors_never_reach_osv(pkg):
    """These resolve as catalog vendors, so the feeds answer them, not OSV."""
    assert L.kind(f"Is the {pkg} npm package safe?", vendors=[pkg]) != "package_safety"


# ─────────────────────────────────────────────── typo suggestions

def test_suggestion_only_names_resolve_typos_without_becoming_known():
    import vendor
    assert vendor.suggest("What happended to miscrosoft recently?") == "microsoft"
    assert vendor.suggest("Is Slaack down?") == "slack"          # insertion typo
    assert vendor.suggest("Is Zooom down?") == "zoom"
    assert not {"microsoft", "zoom", "teams", "slack"} & set(vendor.known_products())


def test_eol_states_past_and_future_against_today(monkeypatch):
    # The presenter can't tell "eol 2025-10-31" is past; the doc must say so.
    import datetime as dt
    L._eol_slugs.cache_clear()
    _json_by_url(monkeypatch, {"all.json": (["python"], None), "/python.json": (PY, None)})
    today = dt.date(2026, 11, 23)
    docs, _ = L._eol("Is Python 3.9 still supported?", today=today)
    assert "Python 3.9: support ended 2025-10-31 (1 year ago, as of 2026-11-23)" in docs[0]["text"]
    docs, _ = L._eol("Is Python 3.10 still supported?", today=dt.date(2026, 10, 1))
    assert "Python 3.10: supported until 2026-10-31 (30 days left, as of 2026-10-01)" in docs[0]["text"]


@pytest.mark.parametrize("q", [
    "Is Stack Overflow down?", "What about tears of the kingdom update?",
    "Is Snack safe?", "Read the terms of service", "Is Texas Instruments safe?",
    "Should I tease the new build?", "Is Smack a good XMPP library?",
])
def test_english_words_near_slack_or_teams_get_no_suggestion(q):
    """One substitution in a five-letter name scores 0.8, the general cutoff:
    "stack" -> Slack and "tears" -> Teams (review, 2026-11-22). The four
    suggestion-only names need a closer match."""
    import vendor
    assert vendor.suggest(q) not in vendor._SUGGEST_ONLY


# ─────────────────────────────────────────────── "Is X down?" (sweep 2026-11-25)

def test_stack_overflow_reads_its_status_page(monkeypatch):
    # "Is Stack Overflow down?" had no status host and was answered with AI
    # coding news that never named Stack Overflow.
    assert L.kind("Is Stack Overflow down?") == "down_now"
    _json_by_url(monkeypatch, {"stackstatus.net": ({"status": {"description": "All Systems Operational"},
                                                    "incidents": []}, None)})
    docs, meta = L.fetch("down_now", "Is Stack Overflow down?")
    assert meta["resolved"] and meta["source"] == "Stack Overflow status page"
    assert "All Systems Operational" in docs[0]["text"]


def test_is_x_down_news_must_name_x(monkeypatch):
    _search_returns(monkeypatch, [
        {"title": "Satya Nadella admits VS Code faded", "body": "IDEs...", "url": "https://w.com/1",
         "date": "2026-11-23T00:00:00+00:00", "source": "Windows Latest"},
        {"title": "Azure outage hits Europe", "body": "b", "url": "https://v.com/2",
         "date": "2026-11-22T00:00:00+00:00", "source": "The Verge"},
    ])
    docs, _ = L.fetch("incident", "Is Azure down?")
    assert [d["title"] for d in docs] == ["Azure outage hits Europe"]


def test_is_x_down_with_nothing_naming_x_says_so(monkeypatch):
    _search_returns(monkeypatch, [{"title": "Unrelated AI study", "body": "b", "url": "https://b.com/1",
                                   "date": "2026-11-24T00:00:00+00:00", "source": "B"}])
    docs, meta = L.fetch("incident", "Is Foobarqux down?")
    assert docs == [] and "Foobarqux" in meta["error"]


def test_about_subject_keeps_only_docs_naming_the_service():
    docs = [{"title": "Downdetector - Check real-time service problems", "text": "generic"},
            {"title": "Zorblaxio status", "text": "All good"}]
    assert L.about_subject("Is Zorblaxio down?", docs) == docs[1:]
    assert L.about_subject("What was the Microsoft outage about?", docs) == docs
