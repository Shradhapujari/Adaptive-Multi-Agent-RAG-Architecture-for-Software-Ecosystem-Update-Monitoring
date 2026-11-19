"""check_claims.py: a quoted number must re-derive from an admissible run."""

import hashlib
import importlib.util
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location(
    "check_claims", os.path.join(ROOT, "scripts", "check_claims.py"))
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def _run(tmp_path, name, vals, system="s", snap="snapA", dh="h", **cfg):
    d = tmp_path / "results" / name
    d.mkdir(parents=True)
    c = {"corpus": {"mode": "replay", "frozen": True, "dir": snap}, "dataset_hash": dh,
         "n_questions": len(vals), "judge_active": True, "judge_pool": True}
    c.update(cfg)
    (d / "config.json").write_text(json.dumps(c))
    (d / "per_query.jsonl").write_text("".join(
        json.dumps({"system": system, "query_id": i,
                    "ir": {"ndcg@3": v}, "ok": v}) + "\n" for i, v in enumerate(vals)))
    return hashlib.sha256((d / "per_query.jsonl").read_bytes()).hexdigest()


def _row(tmp_path, vals=(0.2, 0.4), **over):
    (tmp_path / "paper").mkdir(exist_ok=True)
    (tmp_path / "paper" / "x.tex").write_text("we got nDCG 0.30, ok")
    h = _run(tmp_path, "r1", list(vals)) if not (tmp_path / "results" / "r1").exists() else \
        hashlib.sha256((tmp_path / "results/r1/per_query.jsonl").read_bytes()).hexdigest()
    r = {"file": "paper/x.tex", "quote": "0.30", "runs": "r1", "system": "s",
         "metric": "ir.ndcg@3", "stat": "mean", "value": "0.30", "n": "2", "sha256": h}
    r.update(over)
    return r


def _bad(tmp_path, sub, **over):
    out = C.check(_row(tmp_path, **over), str(tmp_path))
    assert out and any(sub in s for s in out), out


def test_a_true_mean_claim_holds(tmp_path):
    assert C.check(_row(tmp_path), str(tmp_path)) == []


def test_quote_missing_from_file(tmp_path):
    _bad(tmp_path, "quote", quote="0.99")


def test_run_missing_on_disk(tmp_path):
    _bad(tmp_path, "r2", runs="r2", sha256="x")


def test_changed_per_query_fails_the_hash(tmp_path):
    _bad(tmp_path, "sha256", sha256="0" * 64)


def test_wrong_n(tmp_path):
    _bad(tmp_path, "n", n="3")


def test_inadmissible_run_fails_and_says_which_check(tmp_path):
    h = _run(tmp_path, "r1", [0.2, 0.4], corpus={"mode": "record", "frozen": False, "dir": "snapA"})
    out = C.check(_row(tmp_path, sha256=h), str(tmp_path))
    assert any("corpus.mode" in s for s in out), out


def test_number_does_not_rederive(tmp_path):
    _bad(tmp_path, "0.31", value="0.31", quote="0.30")


def test_precision_follows_the_value_string(tmp_path):
    assert C.check(_row(tmp_path, vals=(0.2951, 0.2951)), str(tmp_path)) == []
    t2 = tmp_path / "b"
    t2.mkdir()
    assert C.check(_row(t2, vals=(0.2949, 0.2949)), str(t2))


def test_none_values_are_excluded_and_all_none_is_a_complaint(tmp_path):
    h = _run(tmp_path, "r1", [0.2, None, 0.4])
    assert C.check(_row(tmp_path, sha256=h, n="3"), str(tmp_path)) == []
    t2 = tmp_path / "b"
    t2.mkdir()
    h = _run(t2, "r1", [None, None])
    out = C.check(_row(t2, sha256=h), str(t2))
    assert out and any("no values" in s for s in out), out


def test_median(tmp_path):
    h = _run(tmp_path, "r1", [0.1, 0.3, 0.9])
    assert C.check(_row(tmp_path, stat="median", value="0.30", n="3", sha256=h), str(tmp_path)) == []


def _delta(tmp_path, snap2="snapA", dh2="h", value="0.20"):
    h1 = _run(tmp_path, "r1", [0.5, 0.5])
    h2 = _run(tmp_path, "r2", [0.3, 0.3], snap=snap2, dh=dh2)
    return _row(tmp_path, stat="delta", runs="r1,r2", sha256=f"{h1},{h2}", value=value)


def test_delta_between_two_runs_and_negative_delta(tmp_path):
    r = _delta(tmp_path)
    assert C.check(r, str(tmp_path)) == []
    r.update(runs="r2,r1", sha256=",".join(reversed(r["sha256"].split(","))), value="-0.20")
    assert C.check(r, str(tmp_path)) == []


def test_delta_across_different_snapshot_dirs_fails(tmp_path):
    out = C.check(_delta(tmp_path, snap2="snapB"), str(tmp_path))
    assert any("corpus.dir" in s for s in out), out


def test_delta_across_different_dataset_hash_fails(tmp_path):
    out = C.check(_delta(tmp_path, dh2="g"), str(tmp_path))
    assert any("dataset_hash" in s for s in out), out


def test_count(tmp_path):
    h = _run(tmp_path, "r1", [1, 0, 1, 1, 0])
    assert C.check(_row(tmp_path, stat="count", metric="ok", value="3", n="5", sha256=h),
                   str(tmp_path)) == []
    assert C.check(_row(tmp_path, stat="count", metric="ok", value="2", n="5", sha256=h),
                   str(tmp_path))


def test_manual_is_checked_for_hash_and_admissibility_but_not_rederived(tmp_path):
    assert C.check(_row(tmp_path, stat="manual", value="0.99", quote="0.30"), str(tmp_path)) == []
    _bad(tmp_path, "sha256", stat="manual", sha256="0" * 64)


def _claims(tmp_path, *lines):
    p = tmp_path / "claims.tsv"
    p.write_text("\n".join(lines) + "\n")
    return str(p)


def _line(r):
    return "\t".join(r[k] for k in ("file quote runs system metric stat value n sha256".split()))


def test_main_skips_blank_and_comment_lines_and_reports_bad_rows_by_line(tmp_path, capsys):
    r = _row(tmp_path)
    p = _claims(tmp_path, "file\tquote", "", "# note", _line(r), "too\tfew")
    assert C.main(["--root", str(tmp_path), "--claims", p]) == 1
    out = capsys.readouterr().out
    assert "line 5" in out
    assert "checked 2, failed 1, not re-derived 0" in out


def test_main_exit_code_and_footer(tmp_path, capsys):
    r = _row(tmp_path)
    p = _claims(tmp_path, "file\tquote", _line(r))
    assert C.main(["--root", str(tmp_path), "--claims", p]) == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith("checked 1, failed 0, not re-derived 0\n"
                                 "numbers without a row in claims.tsv are not checked")
    p = _claims(tmp_path, "file\tquote", _line(_row(tmp_path, value="0.31")))
    assert C.main(["--root", str(tmp_path), "--claims", p]) == 1
