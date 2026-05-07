#!/usr/bin/env bash
# Phase 3 gate — backtest harness + LLM A/B verdict.
#
# Asserts (per phase-3.3-prompt.txt §3.3c):
#   1. make verify green (ruff + mypy --strict + pytest).
#   2. lint-imports green (production never imports paper, paper never
#      imports live infra).
#   3. At least one A/B evidence file exists from this session:
#        runbooks/gate-evidence/phase-3.3-llm-ab.txt   OR
#        runbooks/gate-evidence/phase-3.3-deterministic-ab.txt
#   4. runbooks/decisions/llm-ab-result.md exists and contains an explicit
#      "VERDICT: KEPT" or "VERDICT: CUT" string per locked decision #16.
#   5. If KEPT: cumulative API spend recorded in the verdict file is <= $50
#      (locked decision #14 Phase 3 cumulative cap).
#
# Run from the project root (or the active worktree root). Tags
# `phase-3-pass` on success; you must do that by hand after reading the
# report.

set -euo pipefail
cd "$(dirname "$0")/../.."

OUT="runbooks/gate-evidence/phase-3.txt"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"
exec > >(tee -a "$OUT") 2>&1

echo "=== Phase 3 gate ==="
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
echo "head:    $(git rev-parse HEAD)"
echo

echo "--- 1. make verify ---"
make verify

echo "--- 2. lint-imports ---"
uv run lint-imports

echo "--- 3. A/B evidence file present ---"
LLM_AB="runbooks/gate-evidence/phase-3.3-llm-ab.txt"
DET_AB="runbooks/gate-evidence/phase-3.3-deterministic-ab.txt"
if [[ ! -f "$LLM_AB" && ! -f "$DET_AB" ]]; then
  echo "FAIL: neither $LLM_AB nor $DET_AB exists"
  exit 1
fi
[[ -f "$LLM_AB" ]] && echo "OK: $LLM_AB present ($(wc -l < "$LLM_AB" | tr -d ' ') lines)"
[[ -f "$DET_AB" ]] && echo "OK: $DET_AB present ($(wc -l < "$DET_AB" | tr -d ' ') lines)"

echo "--- 4. verdict file present + KEPT|CUT ---"
VERDICT="runbooks/decisions/llm-ab-result.md"
if [[ ! -f "$VERDICT" ]]; then
  echo "FAIL: $VERDICT does not exist"
  exit 1
fi
if grep -qE "^VERDICT: (KEPT|CUT)$" "$VERDICT"; then
  VLINE=$(grep -E "^VERDICT: (KEPT|CUT)$" "$VERDICT" | head -1)
  echo "OK: $VLINE"
else
  echo "FAIL: $VERDICT missing 'VERDICT: KEPT' or 'VERDICT: CUT' line"
  exit 1
fi

echo "--- 5. spend cap (only enforced if VERDICT: KEPT) ---"
if grep -q "^VERDICT: KEPT$" "$VERDICT"; then
  # Look for a "spend_usd:" or "Cumulative spend (USD):" numeric line.
  SPEND=$(grep -E "^(spend_usd|Cumulative spend \(USD\)):[[:space:]]*[0-9]" "$VERDICT" \
    | head -1 | sed -E 's/^[^:]+:[[:space:]]*([0-9.]+).*/\1/')
  if [[ -z "$SPEND" ]]; then
    echo "FAIL: VERDICT KEPT but no 'spend_usd:' line in $VERDICT"
    exit 1
  fi
  # Compare against $50 cap (decision #14).
  if awk -v s="$SPEND" 'BEGIN { exit !(s+0 <= 50.0) }'; then
    echo "OK: spend \$$SPEND <= \$50.00 cap"
  else
    echo "FAIL: spend $SPEND > 50.00 (locked decision #14 Phase 3 cap)"
    exit 1
  fi
else
  echo "OK: VERDICT CUT — spend cap check not applicable"
fi

echo
echo "=== Phase 3 gate green ==="
echo "ended: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
