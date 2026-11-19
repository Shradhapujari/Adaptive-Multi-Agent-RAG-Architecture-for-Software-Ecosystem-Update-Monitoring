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
