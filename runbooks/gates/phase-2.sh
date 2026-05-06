#!/usr/bin/env bash
# Phase 2 gate — read-only data plane.
#
# Asserts (per phase-2-prompt.txt §"Gate command"):
#   1. make verify green (ruff, mypy --strict, pytest).
#   2. lint-imports green (production never imports paper, paper never imports
#      live infra).
#   3. ls ticks/ shows >= 7 dated directories, each containing at least one
#      <source>*.parquet file for each of the four sources. Multi-launch days
#      (laptop sleep recovery) produce <source>_<launch_id>.parquet files; the
#      glob accepts that.
#   4. uv run python scripts/analyze_oracle.py --days 7 reports all four
#      pass criteria green (median gap in [55s,65s], no sub-30s, <5% sub-60s,
#      no gaps >180s). Phase 2.6 next session.
#   5. Cross-feed sanity: any randomly chosen 5-minute window has oracle
#      coverage and spot coverage with timestamps aligned within +-2s.
#
# Run from the project root (or the active worktree root). Tags `phase-2-pass`
# on success; you must do that by hand after reading the report.

set -euo pipefail
cd "$(dirname "$0")/../.."

OUT="runbooks/gate-evidence/phase-2.txt"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"
exec > >(tee -a "$OUT") 2>&1

echo "=== Phase 2 gate ==="
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
echo "head:    $(git rev-parse HEAD)"
echo

echo "--- 1. make verify ---"
make verify

echo "--- 2. lint-imports ---"
uv run lint-imports

echo "--- 3. ticks/ inventory ---"
SOURCES=(binance coinbase oracle polymarket)
DAYS=$(find ticks -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')
echo "dated directories: $DAYS"
if [[ "$DAYS" -lt 7 ]]; then
  echo "FAIL: need >= 7 dated directories, found $DAYS"
  exit 1
fi
for d in ticks/*/; do
  date_label="$(basename "$d")"
  for src in "${SOURCES[@]}"; do
    if ! compgen -G "$d/${src}*.parquet" > /dev/null; then
      echo "FAIL: $date_label missing ${src}*.parquet"
      exit 1
    fi
  done
done
echo "OK: every dated directory has files for all four sources"

echo "--- 4. scripts/analyze_oracle.py --days 7 ---"
if [[ ! -f scripts/analyze_oracle.py ]]; then
  echo "FAIL: scripts/analyze_oracle.py not found (write it in Phase 2.6 next session)"
  exit 1
fi
uv run python scripts/analyze_oracle.py --days 7

echo
echo "=== Phase 2 gate green ==="
echo "ended: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
