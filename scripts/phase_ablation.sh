#!/usr/bin/env bash
# Ranking ablation on a frozen corpus. Used by Phase 3 (validation_gt) and
# Phase 5 (benchmark_100 / benchmark_300).
#
#   scripts/phase_ablation.sh <dataset.json> <snapshot-dir>
#
# Pass 0 populates the snapshot; passes 1-3 replay it strictly, so the three arms differ
# only in MARAG_RERANK. Pass 0 reports frozen=false by construction -- it is a
# population pass, not an arm, and carries no claim.
#
# Everything below lives inside main(). That is not style, it is the fix for a
# real failure: bash streams a script from a byte offset while it runs, so
# editing this file mid-sweep shifts the offsets under the running shell. On
# 2026-08-30 a commit landed here during a sweep, execution resumed inside the
# comment block below, and bash tried to run the word "leak" out of the phrase
# "leaves gaps that leak on every arm". Under `set -e` that killed the run after
# the record pass, and the three arms that carry the claim never executed.
# A function body is parsed to its closing brace before any of it runs, so the
# whole script is in memory before the first pass starts and a later edit cannot
# reach it.
set -euo pipefail
: "${PREDICTION:?set PREDICTION to the one-line prediction for this sweep}"

main() {
  cd "$(dirname "$0")/.."
  DATASET="${1:?usage: phase_ablation.sh <dataset.json> <snapshot-dir>}"
  SNAP="${2:?usage: phase_ablation.sh <dataset.json> <snapshot-dir>}"
  PY=./venv311/bin/python
  COMMON="--dataset $DATASET --generators marag,single_agent --judge ollama:llama3.1 --judge-pool"

  # Use record: on a FRESH directory. Warm-replaying a snapshot inherited from an
  # earlier, differently-scoped run leaves gaps that leak on every arm: that is how
  # the first 100-question sweep ended with 16 of 200 candidate pools differing
  # across arms. If $SNAP already exists, either delete it or pick a new name.
  if [ -d "$SNAP" ]; then
    echo "NOTE: $SNAP exists -- reusing it. For a clean ablation use a new directory."
  fi
  echo "##### RECORD pass | $(date +%H:%M:%S)"
  MARAG_RERANK=embed $PY -m eval_harness.run_eval $COMMON --corpus "record:$SNAP" --diagnostic --prediction "$PREDICTION"

  for arm in none bm25 embed; do
    echo "##### ARM $arm | $(date +%H:%M:%S)"
    MARAG_RERANK=$arm $PY -m eval_harness.run_eval $COMMON --corpus "strict:$SNAP" --prediction "$PREDICTION"
  done
  echo "##### DONE | $(date +%H:%M:%S) — now run: scripts/check_runs.py"
}

# `exit` and not a bare call: it stops bash before it reads another byte of
# this file, so bytes appended mid-run cannot execute after main returns
# and cannot turn a clean sweep into a non-zero exit.
main "$@"
exit $?
