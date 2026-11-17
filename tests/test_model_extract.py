"""Model-assisted extraction when the rules find no version (2026-11-17).

The model only reads a value; it is kept when graph.check_verify finds that
value in the document the model cites, so it cannot introduce a version."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app_1  # noqa: E402

# "Zig 15" is single-part, so the rule (multipart versions only) reads nothing.
POOL = [{"doc_id": "r1", "title": "Zig release notes", "source": "vendor_releases",
         "text": "Zig 15 is the newest release, shipped with a new linker."}]


class _Client:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def generate(self, prompt, **kw):
        self.calls += 1
        return self.reply


def test_a_value_stated_in_the_cited_doc_is_kept():
    c = _Client('{"grounded": true, "value": "15", "doc": "r1"}')
    out = app_1.model_extract_version("What is the latest version of Zig?", POOL, client=c)
    assert out["grounded"] and out["value"] == "15" and out["doc"] == "r1"


def test_an_invented_version_is_rejected():
    c = _Client('{"grounded": true, "value": "16.2.1", "doc": "r1"}')
    out = app_1.model_extract_version("What is the latest version of Zig?", POOL, client=c)
    assert not out["grounded"] and "not in doc" in out["reason"]


def test_no_model_call_when_the_rule_already_found_a_version():
    pool = [{**POOL[0], "text": "Zig 0.15.1 is the newest release."}]
    c = _Client("")
    assert app_1.model_extract_version("What is the latest version of Zig?", pool, client=c) is None
    assert c.calls == 0


def test_no_model_call_for_a_question_that_is_not_about_a_version():
    c = _Client("")
    assert app_1.model_extract_version("Is it safe to update Zig?", POOL, client=c) is None
    assert c.calls == 0


def test_a_checked_value_leads_the_answer_line():
    ex = {"grounded": True, "value": "Zig 15", "doc": "r1", "model": "ollama:llama3.1"}
    line = app_1._answer_line({"extracted": ex}, "")
    assert line.startswith("Zig 15 — read by ollama:llama3.1 from [r1]")
    assert app_1._answer_line({"extracted": {**ex, "grounded": False}}, "") == ""
