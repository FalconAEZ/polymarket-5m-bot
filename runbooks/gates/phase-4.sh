#!/usr/bin/env bash
# Phase 4 gate — paper trading on live venue.
#
# DO NOT RUN this gate during Phase 4 dev. It evaluates 14 calendar days
# of paper-trade evidence; running it before that data exists will fail
# every assertion. The gate fires after the 14-day run completes per
# RUNBOOK §"PHASE 4 — Paper Trading on Live Venue" §"Gate command".
#
# Asserts (per RUNBOOK §4):
#   1. make verify green (ruff + mypy --strict + pytest).
#   2. lint-imports green (production never imports paper, paper -> _live
#      narrowed to _live.feeds only — see .importlinter).
#   3. >= 14 calendar days of state/decisions/*.jsonl files exist.
#   4. No unhandled-exception lines in state/paper.log.
#   5. Sim-validation report shows >= 90% within-1c
#      (runbooks/gate-evidence/phase-4.3-sim-validation.txt produced by
#      scripts/validate_paper_sim.py over the full 14d window).
#   6. Regime coverage report exists at
#      runbooks/gate-evidence/phase-4-regime-coverage.txt asserting
#      >= 1 CPI/FOMC day, >= 1 weekend, >= 1 BTC daily move > 2%.
#   7. Paper P&L within 20% of backtest expectation
#      (runbooks/gate-evidence/phase-4-pnl-comparison.txt).
#   8. (If ensemble enabled) invalid-response rate < 5%, no None
#      meta-decider votes (runbooks/gate-evidence/phase-4-ensemble-stats.txt).
#
# Phase 4 dev session writes this script as scaffolding. The reports
# referenced by 5-8 do not exist yet; producing them is the operator's
# job at the end of the 14-day run, before invoking this gate.
#
# Tag `phase-4-pass` by hand after the gate passes and you've reviewed
# the report.

set -euo pipefail
cd "$(dirname "$0")/../.."

OUT="runbooks/gate-evidence/phase-4.txt"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"
exec > >(tee -a "$OUT") 2>&1

echo "=== Phase 4 gate ==="
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
echo "head:    $(git rev-parse HEAD)"
echo

echo "--- 1. make verify ---"
make verify

echo "--- 2. lint-imports ---"
uv run lint-imports

echo "--- 3. >= 14 calendar days of state/decisions/*.jsonl ---"
DECISIONS_DIR="state/decisions"
if [[ ! -d "$DECISIONS_DIR" ]]; then
  echo "FAIL: $DECISIONS_DIR does not exist"
  exit 1
fi
N_DAYS=$(ls "$DECISIONS_DIR"/*.jsonl 2>/dev/null | wc -l | tr -d ' ')
if [[ "$N_DAYS" -lt 14 ]]; then
  echo "FAIL: $N_DAYS day-files in $DECISIONS_DIR; need >= 14"
  exit 1
fi
echo "OK: $N_DAYS day-files in $DECISIONS_DIR"

echo "--- 4. no unhandled exceptions in state/paper.log ---"
PAPER_LOG="state/paper.log"
if [[ ! -f "$PAPER_LOG" ]]; then
  echo "FAIL: $PAPER_LOG does not exist"
  exit 1
fi
N_TRACEBACKS=$(grep -c "^Traceback (most recent call last):" "$PAPER_LOG" || true)
if [[ "$N_TRACEBACKS" -gt 0 ]]; then
  echo "FAIL: $N_TRACEBACKS unhandled traceback(s) in $PAPER_LOG"
  grep -n "^Traceback (most recent call last):" "$PAPER_LOG" | head -5
  exit 1
fi
echo "OK: 0 unhandled tracebacks in $PAPER_LOG"

echo "--- 5. sim-validation >= 90% within 1c ---"
SIM_REPORT="runbooks/gate-evidence/phase-4.3-sim-validation.txt"
if [[ ! -f "$SIM_REPORT" ]]; then
  echo "FAIL: $SIM_REPORT does not exist"
  exit 1
fi
if ! grep -qE "^STATUS: PASS" "$SIM_REPORT"; then
  echo "FAIL: $SIM_REPORT does not declare STATUS: PASS"
  grep -E "^STATUS:" "$SIM_REPORT" || true
  exit 1
fi
echo "OK: $SIM_REPORT contains STATUS: PASS"

echo "--- 6. regime coverage ---"
REGIME="runbooks/gate-evidence/phase-4-regime-coverage.txt"
if [[ ! -f "$REGIME" ]]; then
  echo "FAIL: $REGIME does not exist (operator produces this after 14d)"
  exit 1
fi
for marker in "CPI_FOMC" "WEEKEND" "BTC_2PCT_MOVE"; do
  if ! grep -qE "^${marker}:.*OK$" "$REGIME"; then
    echo "FAIL: $REGIME missing '${marker}: ... OK' line"
    exit 1
  fi
done
echo "OK: regime coverage report has all three OK markers"

echo "--- 7. paper P&L within 20% of backtest expectation ---"
PNL_FILE="runbooks/gate-evidence/phase-4-pnl-comparison.txt"
if [[ ! -f "$PNL_FILE" ]]; then
  echo "FAIL: $PNL_FILE does not exist"
  exit 1
fi
if ! grep -qE "^WITHIN_20PCT: YES" "$PNL_FILE"; then
  echo "FAIL: $PNL_FILE does not declare WITHIN_20PCT: YES"
  exit 1
fi
echo "OK: $PNL_FILE declares WITHIN_20PCT: YES"

echo "--- 8. ensemble stats (skipped if deterministic-only) ---"
ENS_FILE="runbooks/gate-evidence/phase-4-ensemble-stats.txt"
if [[ -f "$ENS_FILE" ]]; then
  if ! grep -qE "^INVALID_RESPONSE_RATE: 0\.[0-4]" "$ENS_FILE"; then
    echo "FAIL: $ENS_FILE invalid-response rate >= 5% (or missing line)"
    exit 1
  fi
  if grep -qE "^META_NULL_VOTES: [^0]" "$ENS_FILE"; then
    echo "FAIL: $ENS_FILE has non-zero META_NULL_VOTES"
    exit 1
  fi
  echo "OK: ensemble stats within bounds"
else
  echo "SKIP: $ENS_FILE absent (Phase 3 OD-5 verdict was CUT — deterministic only)"
fi

echo
echo "=== Phase 4 gate green ==="
echo "Tag with: git tag phase-4-pass && git push --tags"
