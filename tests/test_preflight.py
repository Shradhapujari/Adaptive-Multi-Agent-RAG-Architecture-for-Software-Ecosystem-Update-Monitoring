import subprocess

from eval_harness import preflight as P


def tags(xs):
    return [x.split(":")[0] for x in xs]


def test_clean_strict_run_has_no_refusals(tmp_path):
    assert P.refusals(f"strict:{tmp_path}", "embed beats bm25 by >= 0.02", False) == []


def test_live_corpus_refused():
    assert "live-corpus" in tags(P.refusals("", "p", False))


def test_lenient_replay_refused(tmp_path):
    assert "lenient-replay" in tags(P.refusals(f"replay:{tmp_path}", "p", False))


def test_record_into_fresh_or_recorded_dir_allowed(tmp_path):
    (tmp_path / "_meta.json").write_text("{}")
    assert P.refusals(f"record:{tmp_path}", "p", False) == []
    assert P.refusals(f"record:{tmp_path / 'new'}", "p", False) == []


def test_record_into_replayed_dir_refused(tmp_path):
    (tmp_path / ".replayed").write_text("")
    assert "record-into-replayed" in tags(P.refusals(f"record:{tmp_path}", "p", False))


def test_dirty_tree_and_blank_prediction_refused(tmp_path):
    got = tags(P.refusals(f"strict:{tmp_path}", "   ", True))
    assert got == ["dirty-tree", "no-prediction"]


def test_git_state_outside_a_repo_is_unknown_and_dirty(tmp_path):
    assert P.git_state(str(tmp_path)) == ("unknown", True)


def _git(cwd, *a):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   cwd=cwd, check=True, capture_output=True)


def test_git_state_ignores_untracked_files(tmp_path):
    _git(tmp_path, "init")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", "a.txt")
    _git(tmp_path, "commit", "-m", "x")
    (tmp_path / "new.txt").write_text("untracked")
    sha, dirty = P.git_state(str(tmp_path))
    assert len(sha) == 40 and dirty is False
    (tmp_path / "a.txt").write_text("2")
    assert P.git_state(str(tmp_path))[1] is True


# ── Task 2: lock, split, CLI enforcement, recorded keys ──────────────────
import json
import os

import pytest

from eval_harness import run_eval as R
from eval_harness.config import EvalConfig


def test_hold_lock_refuses_a_second_holder(tmp_path):
    p = str(tmp_path / ".eval.lock")
    held = P.hold_lock(p)  # noqa: F841 - kept alive on purpose
    with pytest.raises(P.Busy) as e:
        P.hold_lock(p)
    assert e.value.pid == str(os.getpid())


def test_stale_lock_file_does_not_block(tmp_path):
    p = tmp_path / ".eval.lock"
    p.write_text("99999")
    assert P.hold_lock(str(p))


def test_lock_path_is_per_host_not_per_checkout():
    assert P.LOCK_PATH == os.path.expanduser("~/.marag_eval.lock")


def test_split_defaults_to_dev_and_reads_the_manifest(tmp_path):
    ds = tmp_path / "b.json"
    ds.write_text("[]")
    assert P.split_of(str(ds)) == "dev"
    (tmp_path / "b.manifest.json").write_text('{"split": "test"}')
    assert P.split_of(str(ds)) == "test"


@pytest.fixture
def cli(monkeypatch):
    calls = []
    monkeypatch.setattr(R, "run", lambda cfg: calls.append(cfg) or "dir")
    monkeypatch.setattr(P, "git_state", lambda root: ("abc", False))
    monkeypatch.setattr(P, "hold_lock", lambda path: object())
    return calls


def test_main_exits_2_on_refusal_and_names_every_reason(cli, capsys):
    assert R.main(["--corpus", "replay:/x"]) == 2
    out = capsys.readouterr()
    text = out.out + out.err
    assert "lenient-replay" in text and "no-prediction" in text and "--diagnostic" in text
    assert cli == []


def test_main_with_diagnostic_runs_anyway(cli):
    assert R.main(["--corpus", "replay:/x", "--diagnostic"]) == 0
    assert len(cli) == 1 and cli[0].diagnostic is True


def test_main_clean_run_passes_prediction_through(cli, tmp_path):
    assert R.main(["--corpus", f"strict:{tmp_path}", "--prediction", "p"]) == 0
    assert cli[0].prediction == "p" and cli[0].diagnostic is False


def test_main_exits_3_when_another_eval_holds_the_lock(cli, monkeypatch, capsys):
    def busy(path):
        raise P.Busy("4242")
    monkeypatch.setattr(P, "hold_lock", busy)
    assert R.main(["--diagnostic"]) == 3
    out = capsys.readouterr()
    assert "4242" in out.out + out.err and cli == []


class _Gen:
    name = "a"

    def available(self):
        return True

    def generate(self, q):
        return {"answer": q, "docs": [], "self_quality": None}


class _DeadJudge:
    def __init__(self, spec):
        self.spec = spec

    def available(self):
        return False


def _stub_run(tmp_path, monkeypatch, manifest=None):
    ds = tmp_path / "ds.json"
    ds.write_text(json.dumps([{"id": 1, "query": "q", "category": "c", "ground_truth": None}]))
    if manifest:
        (tmp_path / "ds.manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(R, "Judge", _DeadJudge)
    monkeypatch.setattr(R.corpus_snapshot, "activate", lambda spec: None)
    monkeypatch.setattr(R, "build_generators", lambda specs, top_k=4: [_Gen()])
    cfg = EvalConfig(dataset=str(ds), results_dir=str(tmp_path), generators=["a"])
    return R.run(cfg)


def test_run_records_refusals_on_every_run(tmp_path, monkeypatch):
    d = _stub_run(tmp_path, monkeypatch)
    c = json.load(open(os.path.join(d, "config.json")))
    assert any(r.startswith("live-corpus") for r in c["preflight_refusals"])
    assert c["diagnostic"] is True and c["split"] == "dev" and "git_sha" in c
    assert "git_dirty" in c and c["prediction"] == ""
    assert not (tmp_path / "test_split_looks.log").exists()


def test_test_split_run_leaves_exactly_one_look(tmp_path, monkeypatch):
    d = _stub_run(tmp_path, monkeypatch, manifest={"split": "test"})
    lines = (tmp_path / "test_split_looks.log").read_text().splitlines()
    assert len(lines) == 1
    ts, run_id, sha, pred = lines[0].split("\t")
    assert run_id == os.path.basename(d)
