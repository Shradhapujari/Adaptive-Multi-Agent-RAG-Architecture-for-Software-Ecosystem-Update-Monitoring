"""
Tests for the relevance-judgment cache keys in eval_harness/run_eval.py.

The cache exists so the slow, non-deterministic LLM judging happens once per
(question, document) pair and every downstream metric is reproducible. That
only holds if the key identifies the question. Keying by the dataset's row id
did not: benchmark_300 numbers its questions 1..300 and validation_gt numbers
its questions 1..10, both pool docs from the same live APIs, so question 3 of
one dataset inherited question 3 of the other's labels.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval_harness.run_eval import (  # noqa: E402
    _load_qrels_cache, qrels_key, _KEY_RE,
)

DOC = "b2647b642ec6"


def test_same_question_and_doc_is_a_cache_hit():
    assert qrels_key("Is Firefox 149 out?", DOC) == qrels_key("Is Firefox 149 out?", DOC)


def test_key_ignores_case_and_surrounding_whitespace():
    assert qrels_key("  Is Firefox 149 out?  ", DOC) == qrels_key("is firefox 149 out?", DOC)


def test_different_questions_over_the_same_doc_do_not_share_a_label():
    """The defect: two datasets' question #3 must not collide."""
    a = qrels_key("G6 Bullet unstable?", DOC)              # validation_gt id 3
    b = qrels_key("Is iOS 18.2 affected by CVE-2024-1?", DOC)  # benchmark_300 id 3
    assert a != b


def test_same_question_across_datasets_does_share_a_label():
    """Reuse is the point: identical question, identical doc, one judgment."""
    assert (qrels_key("Latest Fedora release?", DOC)
            == qrels_key("latest fedora release?", DOC))


def test_position_keyed_entries_are_dropped_on_load(tmp_path, capsys):
    cache = {
        "3:b2647b642ec6": 2,                       # old, dataset-position keyed
        "12:05c1a881a8e2": 1,                      # old
        qrels_key("Latest Fedora release?", DOC): 2,  # new, question keyed
    }
    (tmp_path / "qrels_cache.json").write_text(json.dumps(cache))

    loaded = _load_qrels_cache(str(tmp_path))

    assert loaded == {qrels_key("Latest Fedora release?", DOC): 2}
    assert "dropped 2 entries" in capsys.readouterr().out


def test_missing_or_corrupt_cache_is_not_fatal(tmp_path):
    assert _load_qrels_cache(str(tmp_path)) == {}
    (tmp_path / "qrels_cache.json").write_text("{not json")
    assert _load_qrels_cache(str(tmp_path)) == {}


def test_prompt_variant_tag_separates_only_the_rows_it_touched():
    """The empty-body prompt change must not void 3,500 cached labels, and
    must not reuse the stale ones for the rows it re-worded."""
    from eval_harness.judge import cache_tag
    assert cache_tag({"text": "has a body"}) == ""
    assert cache_tag({"text": "  \n"}) == "nobody2"
    assert qrels_key("q", DOC) == qrels_key("q", DOC, cache_tag({"text": "body"}))
    assert qrels_key("q", DOC) != qrels_key("q", DOC, cache_tag({"text": ""}))
    assert _KEY_RE.match(qrels_key("q", DOC, "nobody2"))
