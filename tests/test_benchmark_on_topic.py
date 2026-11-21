"""--on-topic keeps mined titles that name a product and carry an update signal.

Titles below are real benchmark_1000 rows (2026-11-20).
"""
import pytest

import build_multiecosystem_benchmark as b


@pytest.mark.parametrize("title", [
    "Folders totally rearranged after macOS Tahoe 26.3.1 update – anyone else?",
    "PSA: By default MariaDB opens up to the internet after upgrade to 12.15",
    "Did Debian official repo (trixie-backports) just got compromised or my system?",
    "Seems like Minio is officially dead now",
    "Is this a glitch/bug with the new Ubuntu 26.04 Resolute Racoon?",
    "Omarchy 3.8.3 is here!",
])
def test_update_signal_holds_for_update_questions(title):
    assert b.update_signal(title)


@pytest.mark.parametrize("title", [
    "Which smart speaker gets used the most in your house?",
    "Struggling with LeetCode Easy after doing well on HackerRank Easy",
    # a bug word with no version and no "after/since" is a programming question
    "Do small Node.js services need process-local error grouping?",
    "Need help getting OpenRGB to work",
])
def test_update_signal_rejects_chatter_and_dev_questions(title):
    assert not b.update_signal(title)


class _CachedApi:
    """Stands in for Api with what its cache would return."""
    def __init__(self):
        self.paths = []

    def get(self, path, params=None):
        self.paths.append(path)
        return {"/api/c/names": ["Chrome", "kubernetes", "mysql"],
                "/api/reddit/meta/subreddits": {"data": ["chrome"]}}[path]


def test_product_detector_uses_the_cached_catalogue_not_the_network(monkeypatch):
    import requests
    def no_network(*a, **k):
        raise AssertionError("product_detector went to the network")
    monkeypatch.setattr(requests, "get", no_network)
    import multiagent_rag_v3 as mrag
    for name in ("_VENDOR_NAMES", "_SUBREDDIT_NAMES", "_VENDORS_LOADED"):
        monkeypatch.setattr(mrag, name, getattr(mrag, name))      # restored after
    api = _CachedApi()
    names_product = b.product_detector(api)
    assert api.paths == ["/api/c/names", "/api/reddit/meta/subreddits"]
    assert names_product("Help with mysql.connector connection issue please")
    assert not names_product("Which smart speaker gets used the most in your house?")
