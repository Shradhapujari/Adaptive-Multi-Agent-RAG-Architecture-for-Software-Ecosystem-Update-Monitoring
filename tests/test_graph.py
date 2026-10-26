"""The graph's invariants, as pytest sees them; graph._demo() is the long form."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import graph  # noqa: E402


def test_self_check_passes():
    graph._demo()


def test_absent_on_healthy_fetch_never_retries():
    rw = lambda q, tried: q
    s = graph.run("latest Fedora version?", rw, lambda q: ([], False), max_rounds=5)
    assert s.evidence is graph.Evidence.ABSENT
    assert len(s.tried) == 1 and s.trace[-1].node == "abstain"


def test_trace_is_emitted_as_jsonl_when_asked(tmp_path, monkeypatch):
    p = tmp_path / "t.jsonl"
    monkeypatch.setenv(graph.tokens.TRACE_ENV, str(p))
    graph.run("latest Fedora version?", lambda q, t: q, lambda q: ([], False))
    lines = p.read_text().splitlines()
    assert [__import__("json").loads(l)["node"] for l in lines] == ["rewrite", "retrieve", "classify"]
    assert all(k in __import__("json").loads(lines[0]) for k in
               ("edge_taken", "reason", "tokens", "contract_ok", "state_hash_in", "state_hash_out"))


# ── verify contract: only a JSON true, citing a pool doc that states the value ──
# Before this, bool(obj.get("grounded")) read the string "false" as True, and a
# value/doc the model invented was answered with as if a document said it.

_CUR = {"doc_id": "c3", "title": "Fedora 44 is the current release"}   # AMBIGUOUS: bare major
_Q = "latest Fedora version?"


def _verify(reply, docs=(_CUR,)):
    s = graph.run(_Q, lambda q, t: q, lambda q: (list(docs), False), llm=lambda p, n: reply)
    return s, next(st for st in s.trace if st.node == "verify")


def test_verify_answers_when_the_cited_doc_states_the_value():
    s, v = _verify('{"grounded": true, "value": "44", "doc": "c3"}')
    assert s.trace[-1].node == "answer" and v.contract_ok


def test_verify_a_well_formed_no_abstains_and_keeps_the_contract():
    s, v = _verify('{"grounded": false, "value": null, "doc": null}')
    assert s.trace[-1].node == "abstain" and v.contract_ok


import pytest  # noqa: E402


@pytest.mark.parametrize("reply", [
    '{"grounded": "false", "value": "44", "doc": "c3"}',   # string, not a boolean
    '{"grounded": "no", "value": "44", "doc": "c3"}',
    '{"grounded": "true", "value": "44", "doc": "c3"}',    # even a string "true"
    '{"grounded": 1, "value": "44", "doc": "c3"}',
    '{"value": "44", "doc": "c3"}',                        # key missing
])
def test_verify_rejects_a_grounded_that_is_not_a_json_boolean(reply):
    s, v = _verify(reply)
    assert s.trace[-1].node == "abstain" and not v.contract_ok, v.out


@pytest.mark.parametrize("reply, why", [
    ('{"grounded": true, "value": "44", "doc": "zz"}', "doc"),       # not in the pool
    ('{"grounded": true, "value": "45", "doc": "c3"}', "value"),     # doc does not say it
    ('{"grounded": true, "value": "9.9.9", "doc": "c3"}', "value"),
    ('{"grounded": true, "value": null, "doc": "c3"}', "value"),     # grounded in nothing
    ('{"grounded": true, "value": "44", "doc": null}', "doc"),
])
def test_verify_rejects_a_value_or_doc_the_pool_does_not_carry(reply, why):
    s, v = _verify(reply)
    assert s.trace[-1].node == "abstain" and not v.contract_ok
    assert why in v.reason, v.reason


def test_verify_value_match_is_whole_token_not_substring():
    # "4" is inside "44" but the document never states 4.
    s, _ = _verify('{"grounded": true, "value": "4", "doc": "c3"}')
    assert s.trace[-1].node == "abstain"


def test_verify_accepts_the_index_label_a_doc_without_id_is_shown_under():
    # verify_prompt labels a doc with no doc_id by its position, and the model
    # may echo that label back as a number.
    nodoc = {"title": "Fedora 44 is the current release"}
    s, _ = _verify('{"grounded": true, "value": "44", "doc": 0}', docs=(nodoc,))
    assert s.trace[-1].node == "answer"
