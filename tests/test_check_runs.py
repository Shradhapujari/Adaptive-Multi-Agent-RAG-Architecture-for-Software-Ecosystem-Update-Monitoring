"""check_runs.py: strict counts as frozen replay, post-gate runs must be clean."""

import importlib.util
import json
import os
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "check_runs", os.path.join(ROOT, "scripts", "check_runs.py"))
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


@pytest.fixture(autouse=True)
def _descends_true(monkeypatch):
    monkeypatch.setattr(M, "descends", lambda sha, anc: True)


def _cfg(**over):
    c = {"corpus": {"mode": "strict", "frozen": True}, "judge_active": True,
         "judge_pool": True, "rerank_degraded": False,
         "preflight_refusals": [], "git_sha": "x"}
    c.update(over)
    return c


def ok(cfg):
    return all(p for p, _ in M.admissibility({"cfg": cfg}))


def test_strict_post_gate_run_is_admissible():
    assert ok(_cfg())


def test_legacy_replay_run_without_preflight_key_is_admissible():
    c = _cfg(corpus={"mode": "replay", "frozen": True})
    del c["preflight_refusals"]
    del c["git_sha"]
    assert ok(c)


def test_post_gate_replay_run_is_not():
    assert not ok(_cfg(corpus={"mode": "replay", "frozen": True}))


def test_record_pass_is_never_admissible():
    assert not ok(_cfg(corpus={"mode": "record", "frozen": False}))


def test_any_refusal_makes_it_inadmissible():
    assert not ok(_cfg(preflight_refusals=["dirty-tree: ..."]))


def test_run_older_than_a_fix_commit_is_not(monkeypatch):
    monkeypatch.setattr(M, "descends", lambda sha, anc: False)
    assert not ok(_cfg())


def _mkrun(tmp_path, cfg):
    d = tmp_path / "run_1"
    d.mkdir()
    (d / "config.json").write_text(json.dumps(cfg))
    (d / "per_query.jsonl").write_text("")
    return str(d)


def test_main_returns_1_when_a_run_is_not_admissible(tmp_path):
    d = _mkrun(tmp_path, _cfg(corpus={"mode": "record", "frozen": False}))
    assert M.main(["x", d]) == 1


def test_main_returns_0_when_all_are(tmp_path):
    assert M.main(["x", _mkrun(tmp_path, _cfg())]) == 0


def test_descends_against_a_throwaway_repo(tmp_path, monkeypatch):
    monkeypatch.undo()  # drop the autouse stub; test the real thing
    monkeypatch.setattr(M, "ROOT", str(tmp_path))
    g = lambda *a: subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
        cwd=tmp_path, check=True, capture_output=True, text=True).stdout.strip()
    g("init", "-q")
    g("commit", "-q", "--allow-empty", "-m", "a")
    a = g("rev-parse", "HEAD")
    g("commit", "-q", "--allow-empty", "-m", "b")
    b = g("rev-parse", "HEAD")
    assert M.descends(b, a)
    assert not M.descends(a, b)
    assert not M.descends("unknown", a)


def test_descends_outside_any_repo_is_false(tmp_path, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(M, "ROOT", str(tmp_path))
    assert not M.descends("abc", "def")


def test_explicit_diagnostic_post_gate_run_is_not_admissible():
    assert not ok(_cfg(diagnostic=True))
    assert ok(_cfg(diagnostic=False))


def test_judge_pool_is_not_an_admissibility_check():
    assert ok(_cfg(judge_pool=False))
    c = _cfg(corpus={"mode": "replay", "frozen": True}, judge_pool=False)
    del c["preflight_refusals"]
    del c["git_sha"]
    assert ok(c)
    assert not any("pool" in lab for _, lab in M.admissibility({"cfg": _cfg()}))
