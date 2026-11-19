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
    assert "Python 3.9: end of life 2025-10-31, latest 3.9.25" in docs[0]["text"]
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


# ─────────────────────────────────────────────── Task 4: package safety (OSV)

REQ = "Is requests 2.31.0 safe? (pip)"


def osv(*vulns):
    return {"vulns": list(vulns)}


FIXED = {"id": "GHSA-9wx4-h78v-vm56", "aliases": ["CVE-2024-35195"], "summary": "Session verify bypass",
         "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}
UNFIXED = {"id": "GHSA-aaaa", "aliases": ["CVE-2026-1"], "summary": "x",
           "affected": [{"ranges": [{"events": [{"introduced": "0"}]}]}]}
NO_CVE = {"id": "PYSEC-2026-1", "aliases": [], "summary": "y",
          "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.32.0"}]}]}]}
OLD_FIX = {"id": "GHSA-old", "aliases": ["CVE-2018-1"], "summary": "z",   # fix older than the asked version
           "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.20.0"}]}]}]}


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
           "affected": [{"ranges": [{"events": [{"introduced": "0"}, {"fixed": "2.10.0"}]},
                                    {"events": [{"introduced": "2.31.0"}, {"fixed": "2.9.0"}]}]}]}
    stub.table["api.osv.dev"] = (osv(two), None)
    r = L.package_safety("Is requests 2.8.0 safe? (pip)")
    assert "Fixed in 2.9.0." in r["verdict_docs"][0]["text"]


def test_bare_a_or_b_is_a_comparison():
    assert L.kind("Postgres or MySQL for a new project?") == "compare"
    assert L.kind("React or Vue in 2026?") == "compare"
