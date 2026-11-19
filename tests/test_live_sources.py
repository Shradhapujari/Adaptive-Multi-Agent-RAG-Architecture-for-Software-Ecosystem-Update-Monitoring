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
