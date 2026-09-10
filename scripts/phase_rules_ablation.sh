#!/usr/bin/env bash
# Does AGENT_RULES.md change the answers? Two arms on a frozen corpus.
#
#   scripts/phase_rules_ablation.sh <dataset.json> <snapshot-dir> [limit]
#
# `limit` caps the questions, and every pass gets the same cap so the arms
# still see the same questions. The 50-question sweep ran 16 questions in
# five and a half hours on a contended machine; a cap is how a real answer
# arrives today instead of in two days.
#
# The app prepends AGENT_RULES.md to every prompt it sends; the harness does
# not, so the file has never been measured -- it was verified to reach the
# prompt and assumed to matter. This sweep answers the question the same way
# the ranking ablation does: record the corpus once, replay it for both arms,
# and let MARAG_RULES be the only thing that differs.
#
# MARAG_RERANK is pinned rather than left to the environment. An arm inherits
# whatever the shell exports, and a rules comparison run across two different
# rerankers measures neither.
#
# Everything lives inside main() for the reason phase_ablation.sh gives: bash
# streams a script from a byte offset while it runs, so an edit landing here
# mid-sweep shifts the offsets under the running shell. A function body is
# parsed to its closing brace before any of it runs.
set -euo pipefail

main() {
  cd "$(dirname "$0")/.."
  DATASET="${1:?usage: phase_rules_ablation.sh <dataset.json> <snapshot-dir>}"
  SNAP="${2:?usage: phase_rules_ablation.sh <dataset.json> <snapshot-dir>}"
  LIMIT="${3:-}"
  PY=./venv311/bin/python
  COMMON="--dataset $DATASET --generators marag,single_agent --judge ollama:llama3.1 --judge-pool"
  if [ -n "$LIMIT" ]; then COMMON="$COMMON --limit $LIMIT"; fi
  export MARAG_RERANK=embed

  # A fresh directory, and this one refuses rather than warns. Warm-replaying a
  # snapshot from an earlier, differently-scoped run leaves gaps that leak into
  # every arm -- that is how a 100-question sweep ended with 16 of 200 candidate
  # pools differing across arms, and a snapshot that has been replayed warm is
  # no longer frozen even if it started that way.
  if [ -e "$SNAP" ]; then
    echo "ERROR: $SNAP exists. An ablation needs a corpus no earlier run has" >&2
    echo "       touched -- pick a new directory, or delete this one." >&2
    exit 2
  fi

  # One record pass PER ARM, which is where this sweep differs from
  # phase_ablation.sh. MARAG_RERANK reorders documents the fetch already
  # returned, so one recording covers every ranking arm. The rules reach the
  # query rewriter, so the two arms ask the corpus different questions: a
  # snapshot recorded under one arm has no answer for the other, the harness
  # goes live to fill the gap, and that arm reports frozen=false. Measured, not
  # assumed -- a single off-arm recording gave the on arm 29 misses, 6 of them
  # on corpus hosts. Recording both arms first makes the snapshot the union of
  # what either asks for, and both replays are then frozen.
  #
  # The record passes carry no claim; they report frozen=false by construction.
  for arm in off on; do
    echo "##### RECORD pass, rules $arm | $(date +%H:%M:%S)"
    MARAG_RULES=$arm $PY -m eval_harness.run_eval $COMMON --corpus "record:$SNAP"
  done

  for arm in off on; do
    echo "##### RULES $arm | $(date +%H:%M:%S)"
    MARAG_RULES=$arm $PY -m eval_harness.run_eval $COMMON --corpus "replay:$SNAP"
  done

  echo "##### DONE | $(date +%H:%M:%S)"
  echo "Compare the two replay runs: scripts/check_runs.py"
  echo "Both replays must report frozen=True. One that does not went live for"
  echo "the queries its arm asked and the pair is not comparable -- re-record."
  echo "Each run's config.json records rules_active and rules_sha -- if the two"
  echo "arms disagree on rules_sha, AGENT_RULES.md was edited mid-sweep and the"
  echo "pair is not an ablation of one factor."
}

# `exit` and not a bare call: bash stops before reading another byte of this
# file, so bytes appended mid-run cannot execute after main returns.
main "$@"
exit $?
