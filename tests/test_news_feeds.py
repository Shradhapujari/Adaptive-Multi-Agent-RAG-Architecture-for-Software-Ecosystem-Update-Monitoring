"""news_feeds: press coverage with a body, replacing headline-only google_news under MARAG_NEWS."""
import urllib.parse

import pytest

import corpus_snapshot
import multiagent_rag_v3 as m

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Chrome 131 patches&nbsp;12 flaws &amp; one zero-day</title>
<link>https://www.securityweek.com/chrome-131/</link>
<pubDate>Wed, 18 Nov 2026 11:43:22 +0000</pubDate>
<description><![CDATA[<p>Google has released <b>Chrome 131</b> with fixes for 12 vulnerabilities.</p>]]></description>
</item>
<item><title>Second post</title><link>https://www.securityweek.com/2/</link>
<description>Body two</description></item>
</channel></rss>"""


class _Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_a_post_comes_back_with_its_excerpt_as_the_body(monkeypatch):
    seen = {}

    def get(url, params=None, **kw):
        seen.update(url=url, params=params)
        return _Resp(RSS)
    monkeypatch.setattr("requests.get", get)
    docs = m.fetch_news_feed("SecurityWeek", "chrome", limit=1)
    assert seen["params"] == {"s": "chrome", "feed": "rss2"}
    assert len(docs) == 1
    d = docs[0]
    assert d["source"] == "news_feeds" and d["subreddit"] == "SecurityWeek"
    assert d["title"] == "Chrome 131 patches 12 flaws & one zero-day"   # &nbsp; no longer fatal
    assert d["detail"] == "Google has released Chrome 131 with fixes for 12 vulnerabilities."
    assert d["url"] == "https://www.securityweek.com/chrome-131/"


def test_a_post_that_does_not_name_the_term_is_dropped(monkeypatch):
    """WordPress search hits the full article; a passing mention is not coverage."""
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(RSS))
    assert [d["title"] for d in m.fetch_news_feed("SecurityWeek", "body two", limit=5)] == ["Second post"]
    assert m.fetch_news_feed("SecurityWeek", "kubernetes", limit=5) == []
    assert m.fetch_news_feed("SecurityWeek", "ease", limit=5) == []      # inside "released"


def test_a_failing_site_contributes_nothing(monkeypatch):
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(b"", 503))
    assert m.fetch_news_feed("SecurityWeek", "chrome") == []
    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp(b"<html>not a feed"))
    assert m.fetch_news_feed("SecurityWeek", "chrome") == []


def test_news_mode_defaults_to_google_and_rejects_typos(monkeypatch):
    monkeypatch.delenv("MARAG_NEWS", raising=False)
    assert m.news_mode() == "google"
    monkeypatch.setenv("MARAG_NEWS", "feed")
    with pytest.raises(ValueError):
        m.news_mode()


def _stub_fetchers(monkeypatch):
    calls = []
    for name in dir(m):
        if name.startswith("fetch_") and callable(getattr(m, name)):
            monkeypatch.setattr(m, name, lambda *a, _n=name, **k: calls.append((_n, a)) or [])
    return calls


@pytest.mark.parametrize("mode,google,feeds", [("google", 2, 0), ("feeds", 0, 7), ("both", 2, 7)])
def test_mode_decides_which_news_source_is_searched(monkeypatch, mode, google, feeds):
    monkeypatch.setenv("MARAG_NEWS", mode)
    monkeypatch.setenv("MARAG_FETCH_WORKERS", "1")
    calls = _stub_fetchers(monkeypatch)
    m.gather_sources("chrome 131 security fixes", original_query="is chrome 131 safe",
                     vendors=["chrome"])
    assert sum(n == "fetch_google_news" for n, _ in calls) == google
    feed_calls = [a for n, a in calls if n == "fetch_news_feed"]
    assert len(feed_calls) == feeds            # once per site, not once per phrasing
    assert all(a[1] == "chrome" for a in feed_calls)


def test_no_product_means_no_feed_search(monkeypatch):
    monkeypatch.setenv("MARAG_NEWS", "feeds")
    calls = _stub_fetchers(monkeypatch)
    m.gather_sources("what changed in the latest release", vendors=[])
    assert not any(n == "fetch_news_feed" for n, _ in calls)


def test_every_feed_host_counts_as_a_corpus_host():
    """Otherwise a strict replay that went live for a feed would not be a miss."""
    for url in m.NEWS_FEEDS.values():
        assert corpus_snapshot.is_corpus_host(url), urllib.parse.urlparse(url).hostname


def test_news_feeds_is_community_evidence_like_google_news():
    import decide
    assert "news_feeds" in m.TIER2 and "news_feeds" in decide.COMMUNITY
    assert m.get_source_label("news_feeds")[0] == m.get_source_label("google_news")[0]


def test_a_recorded_feed_replays_identically_under_strict(tmp_path, monkeypatch):
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: _Resp(RSS))
    with corpus_snapshot.Snapshot("record", str(tmp_path)):
        recorded = m.fetch_news_feed("SecurityWeek", "chrome")
    assert recorded and recorded[0]["detail"]

    def offline(*a, **k):
        raise AssertionError("strict replay went to the network")
    monkeypatch.setattr(requests, "get", offline)
    snap = corpus_snapshot.Snapshot("strict", str(tmp_path))
    with snap:
        assert m.fetch_news_feed("SecurityWeek", "chrome") == recorded
        # an unrecorded search is a corpus miss, not a silent empty source
        with pytest.raises(corpus_snapshot.CorpusMiss):
            m.fetch_news_feed("SecurityWeek", "firefox")
