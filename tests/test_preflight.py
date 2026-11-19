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
import time

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


def test_main_with_diagnostic_runs_anyway(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "git_state", lambda root: ("abc", True))  # dirty-tree
    assert R.main(["--corpus", f"strict:{tmp_path}", "--diagnostic"]) == 0
    assert len(cli) == 1 and cli[0].diagnostic is True


def test_lenient_replay_is_fatal_even_with_diagnostic(cli, capsys):
    assert R.main(["--corpus", "replay:/x", "--prediction", "p", "--diagnostic"]) == 2
    out = capsys.readouterr()
    text = out.out + out.err
    assert "lenient-replay" in text and "strict:" in text and "pass --diagnostic" not in text
    assert cli == []


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


def _stub_run(tmp_path, monkeypatch, manifest=None, name="ds", query="q", gen=None, **kw):
    ds = tmp_path / f"{name}.json"
    ds.write_text(json.dumps([{"id": 1, "query": query, "category": "c", "ground_truth": None}]))
    if manifest:
        (tmp_path / f"{name}.manifest.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(R, "Judge", _DeadJudge)
    monkeypatch.setattr(R.corpus_snapshot, "activate", lambda spec: None)
    monkeypatch.setattr(R, "build_generators", lambda specs, top_k=4: [gen or _Gen()])
    cfg = EvalConfig(dataset=str(ds), results_dir=str(tmp_path), generators=["a"], **kw)
    return R.run(cfg)


def test_run_records_refusals_on_every_run(tmp_path, monkeypatch):
    d = _stub_run(tmp_path, monkeypatch)
    c = json.load(open(os.path.join(d, "config.json")))
    assert any(r.startswith("live-corpus") for r in c["preflight_refusals"])
    assert c["diagnostic"] is True and c["split"] == "dev" and "git_sha" in c
    assert "git_dirty" in c and c["prediction"] == ""
    assert not (tmp_path / "test_split_looks.log").exists()


def test_test_split_runs_log_and_print_looks_per_dataset(tmp_path, monkeypatch, capsys):
    t = {"split": "test"}
    d = _stub_run(tmp_path, monkeypatch, t)
    assert "test split: look 1 at this set" in capsys.readouterr().out
    time.sleep(1.1)  # run_id is a per-second timestamp + dataset hash
    _stub_run(tmp_path, monkeypatch, t)
    assert "test split: look 2 at this set" in capsys.readouterr().out
    _stub_run(tmp_path, monkeypatch, t, name="other", query="different")
    assert "test split: look 1 at this set" in capsys.readouterr().out
    lines = (tmp_path / "test_split_looks.log").read_text().splitlines()
    assert len(lines) == 3
    ts, run_id, sha, dshash, pred = lines[0].split("\t")
    assert run_id == os.path.basename(d) and run_id.endswith(dshash)


def test_record_into_replayed_dir_is_fatal_even_with_diagnostic(cli, tmp_path, capsys):
    (tmp_path / ".replayed").write_text("")
    for extra in (["--diagnostic"], []):
        assert R.main(["--corpus", f"record:{tmp_path}", "--prediction", "p", *extra]) == 2
        out = capsys.readouterr()
        text = out.out + out.err
        assert "record-into-replayed" in text and "pass --diagnostic" not in text
        assert "fresh directory" in text
    assert cli == []


def test_diagnostic_record_into_unreplayed_dir_with_dirty_tree_runs(cli, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "git_state", lambda root: ("abc", True))
    assert R.main(["--corpus", f"record:{tmp_path}", "--prediction", "p", "--diagnostic"]) == 0
    assert len(cli) == 1


def test_git_state_ignores_tracked_files_under_results(tmp_path):
    _git(tmp_path, "init")
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "x.json").write_text("{}")
    (tmp_path / "a.txt").write_text("1")
    _git(tmp_path, "add", "a.txt", "results/x.json")
    _git(tmp_path, "commit", "-m", "x")
    (tmp_path / "results" / "x.json").write_text('{"k": 1}')
    assert P.git_state(str(tmp_path))[1] is False
    (tmp_path / "a.txt").write_text("2")
    assert P.git_state(str(tmp_path))[1] is True


# ── final-review fixes: gate computed once at the top, gate.json, resume ──

def _cfgj(d):
    return json.load(open(os.path.join(d, "config.json")))


def _gatej(d):
    return json.load(open(os.path.join(d, "gate.json")))


def _sha(monkeypatch, sha, dirty=False):
    monkeypatch.setattr(P, "git_state", lambda root: (sha, dirty))


def test_gate_is_taken_at_the_top_not_after_the_loop(tmp_path, monkeypatch):
    tree = {"dirty": False}

    class _Dirties(_Gen):  # the loop writes a tracked file, as the qrels cache did
        def generate(self, q):
            tree["dirty"] = True
            return super().generate(q)
    monkeypatch.setattr(P, "git_state", lambda root: ("s", tree["dirty"]))
    d = _stub_run(tmp_path, monkeypatch, gen=_Dirties(), corpus=f"strict:{tmp_path}",
                  prediction="p")
    c = _cfgj(d)
    assert c["git_dirty"] is False and c["preflight_refusals"] == [] and c["diagnostic"] is False


def test_fresh_run_writes_gate_json(tmp_path, monkeypatch):
    _sha(monkeypatch, "s1")
    d = _stub_run(tmp_path, monkeypatch, corpus=f"strict:{tmp_path}", prediction="p")
    g = _gatej(d)
    assert g == {"git_sha": "s1", "git_dirty": False, "corpus": f"strict:{tmp_path}",
                 "prediction": "p", "preflight_refusals": [], "diagnostic": False}


def _resume(tmp_path, monkeypatch, d, **kw):
    return _stub_run(tmp_path, monkeypatch, resume=os.path.basename(d), **kw)


def test_diagnostic_run_resumed_cleanly_stays_diagnostic(tmp_path, monkeypatch):
    # the reviewer's probe: live, dirty, no prediction; then a clean strict resume
    _sha(monkeypatch, "a" * 40, True)
    d = _stub_run(tmp_path, monkeypatch)
    rows = open(os.path.join(d, "per_query.jsonl"), "rb").read()
    _sha(monkeypatch, "b" * 40, False)
    d2 = _resume(tmp_path, monkeypatch, d, corpus=f"strict:{tmp_path}",
                 prediction="written afterwards")
    assert d2 == d and open(os.path.join(d, "per_query.jsonl"), "rb").read() == rows
    c = _cfgj(d)
    assert c["diagnostic"] is True and c["prediction"] == "" and c["git_sha"] == "a" * 40
    tags_ = [r.split(":")[0] for r in c["preflight_refusals"]]
    assert {"live-corpus", "dirty-tree", "no-prediction", "resumed-across-change"} <= set(tags_)
    assert _gatej(d)["prediction"] == "" and _gatej(d)["corpus"] == ""


def test_resume_with_a_different_sha_or_corpus_is_refused(tmp_path, monkeypatch):
    _sha(monkeypatch, "s1")
    d = _stub_run(tmp_path, monkeypatch, corpus=f"strict:{tmp_path}", prediction="p")
    _sha(monkeypatch, "s2")
    _resume(tmp_path, monkeypatch, d, corpus=f"strict:{tmp_path}", prediction="p")
    c = _cfgj(d)
    assert any(r.startswith("resumed-across-change") and "git_sha" in r
               for r in c["preflight_refusals"]) and c["diagnostic"] is True
    assert c["git_sha"] == "s1"
    t2 = tmp_path / "b"
    t2.mkdir()
    _sha(monkeypatch, "s1")
    d = _stub_run(t2, monkeypatch, corpus=f"strict:{t2}/x", prediction="p")
    _resume(t2, monkeypatch, d, corpus=f"strict:{t2}/y", prediction="p")
    assert any(r.startswith("resumed-across-change") and "corpus" in r
               for r in _cfgj(d)["preflight_refusals"])
    assert _gatej(d)["corpus"] == f"strict:{t2}/x"


def test_resume_of_a_run_with_no_gate_record_is_refused(tmp_path, monkeypatch):
    _sha(monkeypatch, "s1")
    d = _stub_run(tmp_path, monkeypatch, corpus=f"strict:{tmp_path}", prediction="p")
    os.remove(os.path.join(d, "gate.json"))
    _resume(tmp_path, monkeypatch, d, corpus=f"strict:{tmp_path}", prediction="p")
    assert "resumed-across-change: no gate record for this run" in _cfgj(d)["preflight_refusals"]
    assert _cfgj(d)["diagnostic"] is True


def test_clean_run_resumed_cleanly_stays_clean(tmp_path, monkeypatch):
    _sha(monkeypatch, "s1")
    d = _stub_run(tmp_path, monkeypatch, corpus=f"strict:{tmp_path}", prediction="p")
    _resume(tmp_path, monkeypatch, d, corpus=f"strict:{tmp_path}")  # prediction kept
    c = _cfgj(d)
    assert c["preflight_refusals"] == [] and c["diagnostic"] is False and c["prediction"] == "p"


def test_main_refuses_a_resume_across_change_unless_diagnostic(cli, tmp_path, capsys):
    d = tmp_path / "run_1_abc"
    d.mkdir()
    (d / "per_query.jsonl").write_text("")
    args = ["--resume", str(d), "--corpus", f"strict:{tmp_path}", "--prediction", "p"]
    assert R.main(args) == 2
    assert "resumed-across-change" in capsys.readouterr().err and cli == []
    assert R.main(args + ["--diagnostic"]) == 0 and len(cli) == 1


def test_explicit_diagnostic_is_recorded_and_sticks_on_resume(tmp_path, monkeypatch):
    _sha(monkeypatch, "s1")
    d = _stub_run(tmp_path, monkeypatch, corpus=f"strict:{tmp_path}", prediction="p",
                  diagnostic=True)
    assert _cfgj(d)["diagnostic"] is True and _gatej(d)["diagnostic"] is True
    assert _cfgj(d)["preflight_refusals"] == []
    _resume(tmp_path, monkeypatch, d, corpus=f"strict:{tmp_path}", prediction="p")
    assert _cfgj(d)["diagnostic"] is True


class _Boom(_Gen):
    def generate(self, q):
        raise KeyboardInterrupt  # a run killed at the first question


def test_test_split_look_is_logged_before_the_loop_and_not_on_resume(tmp_path, monkeypatch):
    t = {"split": "test"}
    with pytest.raises(KeyboardInterrupt):
        _stub_run(tmp_path, monkeypatch, t, gen=_Boom(), prediction="p")
    log = tmp_path / "test_split_looks.log"
    assert len(log.read_text().splitlines()) == 1
    run_id = log.read_text().split("\t")[1]
    _resume(tmp_path, monkeypatch, tmp_path / run_id, manifest=t)
    assert len(log.read_text().splitlines()) == 1
