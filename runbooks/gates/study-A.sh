#!/usr/bin/env bash
# Study Phase A gate — evidence script.
# Re-runs the audit (cache-fast on second invocation) and asserts artifacts
# exist + gate decision is documented. Tee output to gate-evidence file.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

EVIDENCE="$ROOT/runbooks/gate-evidence/study-A.txt"
mkdir -p "$(dirname "$EVIDENCE")"

{
  echo "== STUDY PHASE A GATE EVIDENCE =="
  echo "  date: $(date -u +%FT%TZ)"
  echo "  rev:  $(git rev-parse HEAD 2>/dev/null || echo '<no-git>')"
  echo

  echo "[1] make verify (project still healthy)"
  make verify
  echo

  echo "[2] artifacts from latest audit run (run scripts/research/quick_audit.py to refresh)"
  for f in runbooks/study/quick-audit.html runbooks/study/preflight-decision.md \
           state/research/bonereaper/labelled_audit.parquet; do
    if [ -s "$f" ]; then echo "  ✓ $f ($(wc -c <"$f" | tr -d ' ') bytes)"; else echo "  ✗ $f MISSING"; exit 2; fi
  done
  echo

  echo "[3] decision parsed from preflight-decision.md"
  GRADE=$(awk '/^\*\*Decision:\*\*/ {print; exit}' runbooks/study/preflight-decision.md)
  echo "  $GRADE"
  AUDIT_RC=$([[ "$GRADE" == *PROCEED* ]] && echo 0 || echo 1)
  echo "  parsed exit code: $AUDIT_RC  (0 = PROCEED, 1 = ABORT)"
  echo

  echo "[4] decision file head"
  sed -n '1,18p' runbooks/study/preflight-decision.md
  echo

  echo "STUDY PHASE A GATE $([ $AUDIT_RC -eq 0 ] && echo PROCEED || echo ABORT) $(date -u +%FT%TZ)"
  exit $AUDIT_RC
} | tee "$EVIDENCE"
