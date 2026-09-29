#!/usr/bin/env bash
# Phase 4 — the independent judge. Closes threat T2: llama3.1 judges a pipeline
# whose rewriter and two arms are also llama3.1.
#
# THE TRAP THIS SCRIPT EXISTS TO AVOID
# -----------------------------------
# `qrels_key()` is sha1(question):doc_id. The judge model is NOT in the key, and
# results/qrels_cache.json already holds ~19k labels from llama3.1. Run gpt-4o
# against that cache and it answers from llama3.1's labels for every pair it has
# seen -- most of them -- while config.json records `judge: openai:gpt-4o`. You
# would pay for a run that measures the judge it was built to replace.
#
# RESULTS_DIR has no flag and no env override, so isolation is a worktree: its
# own results/, with the inherited cache emptied below. The main tree is never
# touched, and the two label sets stay side by side for the agreement analysis.
#
# WHAT IT REPRODUCES
# ------------------
# The frozen three-arm run behind Table 11 (run_1790126271): same dataset, same
# arms with the synthesis model held constant, flat ranking with the grading
# cascade, strict replay of one snapshot, own-post excluded at fetch time. Only
# the judge differs, which is the whole point -- strict replay reproduces
# retrieval document for document and answers byte for byte at temperature 0
# (Section 4.6.5), so any metric difference is the judge and nothing else.
#
#   scripts/phase_judge.sh [n_questions] [judge_spec]
#
# The judge defaults to ollama:mistral, which costs nothing and is independent
# in the sense T2 names: a different model family from llama3.1, and -- unlike
# qwen2.5:7b-instruct -- playing no part in the run being judged, whose arms are
# llama3.1 and whose grading cascade is qwen. A local 7B judge tests whether the
# ORDERING is robust to the choice of judge. It does not establish that a
# frontier judge agrees; say the first and not the second. openai:gpt-4o is
# still available as the second argument and is the stronger claim.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LIMIT="${1:-100}"
JUDGE="${2:-ollama:mistral}"

case "$JUDGE" in
  openai:*)
    : "${OPENAI_API_KEY:?set OPENAI_API_KEY in this shell first}"
    ./venv311/bin/python -c "import openai" 2>/dev/null || {
      echo "the openai package is not in venv311. It is deliberately not in"
      echo "requirements.txt, so CI does not install it:"
      echo "    ./venv311/bin/pip install openai"
      exit 1
    } ;;
  ollama:*)
    curl -sf --max-time 5 localhost:11434/api/tags >/dev/null || {
      echo "ollama is not answering on localhost:11434"; exit 1; } ;;
esac

SNAP="$ROOT/data/corpus_snapshot_b500_flat_0921"
[ -d "$SNAP" ] || { echo "missing snapshot $SNAP -- it does not travel in git"; exit 1; }

WT="$ROOT/../marag-judge-wt"
if [ ! -d "$WT" ]; then
  git worktree add -f "$WT" HEAD
fi
cd "$WT"
ln -sfn "$ROOT/venv311" venv311
mkdir -p results
echo '{}' > results/qrels_cache.json          # the isolation that makes this real

MARAG_RERANK="llm20@embed:nomic-embed-text:qwen2.5:7b-instruct" \
MARAG_RANK_TIERS=flat \
./venv311/bin/python -m eval_harness.run_eval \
  --dataset "$ROOT/data/benchmark_500.json" \
  --generators marag,marag:ollama:llama3.1,single_agent:ollama:llama3.1 \
  --judge "$JUDGE" \
  --corpus "strict:$SNAP" \
  --top-k 4 \
  --limit "$LIMIT" --stratify category,ecosystem \
  2>&1 | tee "$ROOT/results/judge_${JUDGE//[:\/]/_}.log"

echo
echo "Labels: $WT/results/qrels_cache.json   ($JUDGE only, by construction)"
echo "Against: $ROOT/results/qrels_cache.json  (llama3.1)"
echo "Now read it:"
echo "    python scripts/judge_compare.py --b $WT/results/qrels_cache.json"
echo "It reports both judges' system orderings side by side and per-label kappa."
echo "The claim the paper needs is that the ORDERING survives; per-label"
echo "agreement is expected to be poor and Section 5.5 already says so."
