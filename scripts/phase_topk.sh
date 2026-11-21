#!/usr/bin/env bash
# top_k sweep on a frozen corpus. Holds everything constant except the slot
# budget, so the only moving part is how many candidates survive to the answer.
#
#   scripts/phase_topk.sh <dataset.json> <snapshot-dir> [k ...]
#
# Why this exists. On the n=100 frozen ablation the multi-agent arm held 520
# judged-relevant documents in its candidate pool against the baseline's 434 --
# including 110 the baseline never fetched -- yet shipped 145 in top_k against
# the baseline's 150. Pool recall separated cleanly (0.979 vs 0.845); recall@5
# and nDCG@3 did not. The obvious reading, "the reranker is worse", does not
# survive a matched-ceiling control (diff -0.049, p=0.16), because marag's pool
# is 1.48x larger and competes for the same 4 slots. That leaves top_k as the
# suspected throttle, and this script is the experiment that settles it.
#
# MARAG_RERANK is pinned to embed (the strongest arm) throughout: varying two
# things at once would make the result uninterpretable. The k=4 pass is the
# control -- it must reproduce the embed arm of scripts/phase_ablation.sh.
#
# Read the results with: scripts/topk_report.py
# Everything runs inside main() so that bash parses the whole script before the
# first pass starts. Bash streams a script from a byte offset while it runs, so
# an edit landing mid-sweep shifts those offsets under the running shell -- on
# 2026-08-30 that killed a 4-hour ablation after its first pass, when a commit
# touched scripts/phase_ablation.sh while it was executing. A function body is
# parsed to its closing brace before any of it runs, so a later edit cannot
# reach a sweep already in flight.
set -euo pipefail
: "${PREDICTION:?set PREDICTION to the one-line prediction for this sweep}"

main() {
cd "$(dirname "$0")/.."

DATASET="${1:?usage: phase_topk.sh <dataset.json> <snapshot-dir> [k ...]}"
SNAP="${2:?usage: phase_topk.sh <dataset.json> <snapshot-dir> [k ...]}"
shift 2
KS=("$@")
[ ${#KS[@]} -eq 0 ] && KS=(4 10 20)

PY=./venv311/bin/python
LOG=/tmp/topk_sweep.log

if [ ! -d "$SNAP" ]; then
  echo "ERROR: $SNAP does not exist. Populate it first with scripts/phase_ablation.sh," >&2
  echo "       which runs a record pass before its replay arms." >&2
  exit 1
fi

: > "$LOG"
echo "##### QUEUED | $(date +%H:%M:%S) — waiting for any running evaluation" | tee -a "$LOG"

# specs/status.md §1: this repo has been damaged twice by concurrent sessions.
# Two evaluations sharing one Ollama also distort the latency column. Wait for a
# sustained idle window before starting.
#
# Keying on phase_ablation.sh matters: that wrapper stays alive between its own
# passes, so waiting only on run_eval would start this in the gap between two of
# its arms and contend anyway.
idle=0
while true; do
  if pgrep -f "phase_ablation.sh" >/dev/null 2>&1 || pgrep -f "eval_harness.run_eval" >/dev/null 2>&1; then
    idle=0
  else
    idle=$((idle + 15))
  fi
  [ "$idle" -ge 60 ] && break
  sleep 15
done

echo "##### START | $(date +%H:%M:%S) — idle, sweeping top_k = ${KS[*]}" | tee -a "$LOG"

for K in "${KS[@]}"; do
  echo "" | tee -a "$LOG"
  echo "===== top_k=$K | $(date +%H:%M:%S) =====" | tee -a "$LOG"
  # set -e is deliberately suspended here: a failed arm should be reported with
  # its exit code, not vanish behind an unexplained shell death.
  set +e
  MARAG_RERANK=embed "$PY" -u -m eval_harness.run_eval \
    --dataset "$DATASET" \
    --generators marag,single_agent \
    --judge ollama:llama3.1 \
    --judge-pool \
    --corpus "strict:$SNAP" \
    --prediction "$PREDICTION" \
    --top-k "$K" >> "$LOG" 2>&1
  rc=$?
  set -e
  echo "----- top_k=$K exit=$rc | $(date +%H:%M:%S)" | tee -a "$LOG"
  if [ "$rc" -ne 0 ]; then
    echo "##### TOPK ABORTED at top_k=$K (exit $rc)" | tee -a "$LOG"
    exit "$rc"
  fi
done

echo "" | tee -a "$LOG"
echo "##### TOPK DONE | $(date +%H:%M:%S) — now run: scripts/topk_report.py" | tee -a "$LOG"
}

# `exit` and not a bare call: it stops bash before it reads another byte of
# this file, so bytes appended mid-run cannot execute after main returns
# and cannot turn a clean sweep into a non-zero exit.
main "$@"
exit $?
