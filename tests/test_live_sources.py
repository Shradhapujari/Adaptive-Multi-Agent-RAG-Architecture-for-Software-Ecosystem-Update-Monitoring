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
