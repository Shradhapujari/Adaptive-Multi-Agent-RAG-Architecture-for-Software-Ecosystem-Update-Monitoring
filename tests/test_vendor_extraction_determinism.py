"""extract_vendor must not depend on PYTHONHASHSEED.

Found via a real Phase 5 frozen-corpus ablation: `check_runs.py`'s pool-identity
gate failed at 184/200 (not 200/200) between two arms replaying the same
corpus_snapshot with zero external misses on either arm. The corpus was frozen;
the vendor DECISION was not. `extract_vendor` iterated `set(words)` when
checking exact-word vendor matches, then broke score ties by insertion order --
so a query containing two words that are both registered vendor names
("rust-lang rust v1.92.0 ship" matches both "rust" and, spuriously, "release"
from "release channel") could resolve to either one depending on the process's
hash seed, which is randomized per process by default. That silently changed
which vendor-specific endpoints got queried, producing a different candidate
pool for byte-identical input across separate `run_eval` invocations.

These tests run under several explicit PYTHONHASHSEED values via a subprocess,
because re-exec'ing with a different seed inside one process has no effect --
the seed is fixed at interpreter startup.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MRAG = ROOT / "multiagent_rag_v3.py"

SEEDS = ["0", "1", "2", "3", "4", "17", "42", "1000"]

# The catalogs extract_vendor matches against, pinned.
#
# They are normally fetched from /api/c/names and /api/reddit/meta/subreddits
# by load_vendor_lists(), which swallows a failed fetch and leaves the list
# empty. Each seed below is its own process and so its own pair of fetches, so
# one request failing while the others succeed makes the seeds disagree about
# the vendor -- and this test reports that as "extract_vendor is not
# seed-invariant", which is not what happened. Seen 2026-09-24, while the
# b1000 eval was competing with this machine for the same endpoint: the suite
# failed here, and the same test passed three times in a row on its own
# minutes later.
#
# The property under test is that a tie between two registered names resolves
# the same way whatever the hash seed. That needs a list containing the tie,
# not the live list: "release" and "rust" are both registered names, which is
# what made the reported query ambiguous in the first place. Pinning them
# keeps the tie and removes the network.
_VENDORS = ["arch", "release", "rust", "rust-lang", "ubuntu", "upgrade",
            "channel", "fedora", "debian"]
_SUBREDDITS = ["archlinux", "rust", "ubuntu", "linux"]

_PROBE = '''
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("mrag", {mrag!r})
mrag = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mrag)
# Pin the catalogs before the call, and mark them loaded so the fetch that
# would replace them never runs. Set after exec_module because the module
# defines these at import.
mrag._VENDOR_NAMES = {vendors!r}
mrag._SUBREDDIT_NAMES = {subreddits!r}
mrag._VENDORS_LOADED = True
print(json.dumps(mrag.extract_vendor({query!r})))
'''


def _run_with_seed(seed: str, query: str) -> list:
    src = _PROBE.format(mrag=str(MRAG), query=query,
                        vendors=_VENDORS, subreddits=_SUBREDDITS)
    out = subprocess.run(
        [sys.executable, "-c", src],
        cwd=ROOT, env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    lines = [l for l in out.stdout.splitlines() if l.strip().startswith("[")]
    assert lines, f"no JSON output for seed={seed}: {out.stdout!r} {out.stderr!r}"
    import json
    return json.loads(lines[-1])


class TestVendorExtractionIsSeedInvariant:
    def test_the_exact_reported_query(self):
        """This is the query that actually flipped between arms in Phase 5."""
        query = "What release channel did rust-lang rust v1.92.0 ship on?"
        results = {tuple(_run_with_seed(s, query)) for s in SEEDS}
        assert len(results) == 1, (
            f"extract_vendor is not seed-invariant: got {results} across "
            f"seeds {SEEDS}"
        )

    def test_a_second_ambiguous_query(self):
        """Different word pair, same class of tie: both are exact-name hits."""
        query = "Should I upgrade to Arch v2026.01.01?"
        results = {tuple(_run_with_seed(s, query)) for s in SEEDS}
        assert len(results) == 1, (
            f"extract_vendor is not seed-invariant: got {results} across "
            f"seeds {SEEDS}"
        )


class TestVendorExtractionUnitLevel:
    """Same property, without paying for a subprocess per case."""

    @classmethod
    def setup_class(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location("mrag_unit", MRAG)
        cls.mrag = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mrag)
        # Same pinning as the subprocess probe, and for the same reason: these
        # assertions are about the matching rules, not about whether
        # releasetrain.io answered while the suite was running.
        cls.mrag._VENDOR_NAMES = list(_VENDORS)
        cls.mrag._SUBREDDIT_NAMES = list(_SUBREDDITS)
        cls.mrag._VENDORS_LOADED = True

    def test_sorted_not_raw_set_iteration(self):
        """Regression pin on the mechanism, not just the symptom: the exact-word
        match steps must iterate a sorted sequence, so a source read shows the
        fix in place even if the seed-invariance test above is ever skipped."""
        import inspect
        src = inspect.getsource(self.mrag.extract_vendor)
        assert "words = set(" not in src, (
            "extract_vendor iterates a raw set again -- this reintroduces "
            "PYTHONHASHSEED-dependent vendor selection on tied matches"
        )

    def test_still_finds_the_intended_vendor_when_unambiguous(self):
        assert self.mrag.extract_vendor("Is Ubuntu v13.3.0 out yet?") == ["ubuntu"]
