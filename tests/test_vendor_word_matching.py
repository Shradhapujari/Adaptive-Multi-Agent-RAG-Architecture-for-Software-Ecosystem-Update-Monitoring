"""extract_vendor matches words, short product names and whole-word aliases.

Measured on benchmark_1000 (2026-11-20): splitting on whitespace with only ?/!
removed, plus the len > 3 rule, left npm, pip, php, EKS, "MySQL:" and postgres
questions with no product, and so with no vendor-targeted fetch.
"""
import pytest

import multiagent_rag_v3 as m

# A slice of the live catalog, including the 3-letter non-products the
# len > 3 rule is there for.
CATALOG = ["mysql", "node.js", "node", "kubernetes", "postgresql", "wordpress",
           "rust", "python", "php", "npm", "pip", "csv", "dns", "lan", "framework"]


@pytest.fixture(autouse=True)
def catalog(monkeypatch):
    monkeypatch.setattr(m, "_VENDOR_NAMES", list(CATALOG))
    monkeypatch.setattr(m, "_SUBREDDIT_NAMES", [])
    monkeypatch.setattr(m, "_VENDORS_LOADED", True)


@pytest.mark.parametrize("q,want", [
    ("npm audit fix causes cascading vulnerabilities", ["npm"]),
    ("why i cant pip install autopy?", ["pip"]),
    ("Updated to php 8.2 now photos won't upload", ["php"]),
    ("Nodes are not joining after upgrading eks to v1.33", ["kubernetes"]),
    ("Error setting up MySQL: Table 'mysql.plugin' doesn't exist", ["mysql"]),
    ("Help with mysql.connector connection issue please", ["mysql"]),
    ("Is postgres 17 safe to upgrade?", ["postgresql"]),
    ("Samsung phone keeps restarting after the latest update", ["android"]),
])
def test_named_products_resolve(q, want):
    assert m.extract_vendor(q) == want


def test_short_names_need_the_list_not_just_the_catalog():
    assert m.extract_vendor("export the dns records to csv over lan") == []


def test_whole_words_only():
    assert m.extract_vendor("two weeks after the update it broke") == []   # not "eks"


def test_a_dotted_catalog_name_is_kept_whole():
    assert m.extract_vendor("What context do you include in Node.js error alerts?") == ["node.js"]


def test_a_word_alias_does_not_crowd_out_a_catalog_name():
    assert m.extract_vendor("Working on an Kubernetes operator in PHP") == ["kubernetes", "php"]
    assert m.extract_vendor("Is running postgres inside Kubernetes an anti-pattern?") == \
        ["kubernetes", "postgresql"]


def test_punctuation_no_longer_hides_a_name():
    assert m.extract_vendor("a Brotli codec in pure Rust, optimized") == ["rust"]
