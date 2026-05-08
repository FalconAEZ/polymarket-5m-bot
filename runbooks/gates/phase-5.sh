#!/usr/bin/env bash
# Phase 5 gate — VPS provisioning + 24h staging + replicated state.
#
# 8 criteria (per state/phases/phase-5-vps.md "Phase 5 gate" + design/litestream.md §8):
#   1. systemctl is-active bot-staging.service == active
#   2. systemctl is-enabled bot.service == disabled (Phase 6 stub)
#   3. WS subscribe -> first-msg p50<20ms p99<30ms (revised per Option B,
#      runbooks/incidents/2026-05-07-clob-latency-gate-analysis.md)
#   4. chronyc tracking offset |Last offset| < 10ms
#   5. Telegram smoke alert received (operator-attested at 5.5 closeout)
#   6. /halt smoke works (operator-attested at 5.5 closeout)
#   7. journalctl -u bot-staging --since "24h ago": zero unhandled exceptions
#   8. litestream replicating trades.db to S3 (active + S3 generation present
#      + restore drill green)
#
# Run from operator's laptop (Mac):
#   bash runbooks/gates/phase-5.sh | tee runbooks/gate-evidence/phase-5.txt
#
# Exits 0 iff all 8 GREEN. Tag `phase-5-pass` by hand on green.

set -uo pipefail
cd "$(dirname "$0")/../.."

KEY="${LIGHTSAIL_KEY:-$HOME/Downloads/LightsailDefaultKey-eu-west-1.pem}"
USERHOST="${VPS_USERHOST:-ops@108.132.51.116}"
PORT="${VPS_PORT:-2222}"
SSH="ssh -i $KEY -p $PORT -o StrictHostKeyChecking=no -o BatchMode=yes $USERHOST"

echo "=== Phase 5 gate ==="
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
echo "head:    $(git rev-parse HEAD)"
echo "vps:     $USERHOST (port $PORT)"
echo

PASS=0
FAIL=0
verdicts=()

mark() {
  local n="$1" status="$2" name="$3"
  if [[ "$status" == "PASS" ]]; then
    echo "  [#$n PASS] $name"
    PASS=$((PASS+1))
  else
    echo "  [#$n FAIL] $name"
    FAIL=$((FAIL+1))
  fi
  verdicts+=("$status  #$n  $name")
}

# ----------------------------------------------------------------------
echo "--- #1. bot-staging.service active ---"
if active=$($SSH "systemctl is-active bot-staging.service" 2>/dev/null) && [[ "$active" == "active" ]]; then
  uptime=$($SSH "systemctl show bot-staging.service -p ActiveEnterTimestamp --value" 2>/dev/null)
  echo "    ActiveEnterTimestamp=$uptime"
  mark 1 PASS "bot-staging.service active"
else
  echo "    is-active=$active"
  mark 1 FAIL "bot-staging.service active"
fi

# ----------------------------------------------------------------------
echo
echo "--- #2. bot.service disabled ---"
# `systemctl is-enabled` exits non-zero when the unit is disabled/masked even
# while reporting it on stdout — so trust the stdout, not the exit code.
enabled=$($SSH "systemctl is-enabled bot.service 2>/dev/null || true" 2>/dev/null)
echo "    is-enabled=$enabled"
if [[ "$enabled" == "disabled" || "$enabled" == "masked" ]]; then
  mark 2 PASS "bot.service disabled (Phase 6 stub)"
else
  mark 2 FAIL "bot.service disabled"
fi

# ----------------------------------------------------------------------
echo
echo "--- #3. WS subscribe->first-msg p50<20ms p99<30ms (cached from phase-5.3-latency.txt) ---"
LAT="runbooks/gate-evidence/phase-5.3-latency.txt"
if [[ -f "$LAT" ]] && python3 - "$LAT" <<'PY'
import re, sys
text = open(sys.argv[1]).read()
m = re.search(r'subscribe -> first msg.*?p50=\s*([\d.]+).*?p99=\s*([\d.]+)', text)
if not m:
    print("    parse-fail")
    sys.exit(1)
p50, p99 = float(m.group(1)), float(m.group(2))
print(f"    p50={p50}ms (gate <20ms)  p99={p99}ms (gate <30ms)")
sys.exit(0 if p50 < 20.0 and p99 < 30.0 else 1)
PY
then
  mark 3 PASS "WS subscribe->first-msg latency within revised gate"
else
  mark 3 FAIL "WS subscribe->first-msg latency outside revised gate"
fi

# ----------------------------------------------------------------------
echo
echo "--- #4. chrony |Last offset| < 10ms ---"
chrony_out=$($SSH "chronyc tracking | grep 'Last offset'" 2>/dev/null)
if [[ -n "$chrony_out" ]] && python3 - <<PY
import re, sys
m = re.search(r'Last offset\s*:\s*(-?[\d.eE+-]+)\s*seconds', "$chrony_out")
if not m:
    print("    parse-fail")
    sys.exit(1)
off_s = float(m.group(1))
off_ms = off_s * 1000.0
print(f"    Last offset = {off_s} s ({off_ms:.6f} ms)  gate |x|<10ms")
sys.exit(0 if abs(off_ms) < 10.0 else 1)
PY
then
  mark 4 PASS "chrony offset within 10ms"
else
  mark 4 FAIL "chrony offset >= 10ms or unparseable"
fi

# ----------------------------------------------------------------------
echo
echo "--- #5. Telegram smoke alert (operator-attested) ---"
if grep -qiE 'Telegram smoke.*operator.confirmed|operator.confirmed.*Telegram' state/phases/phase-5-vps.md ; then
  echo "    ATTESTED — see state/phases/phase-5-vps.md (5.5 row + 'What's next' table)"
  mark 5 PASS "Telegram smoke alert (attested)"
else
  echo "    no attestation found in state/phases/phase-5-vps.md"
  mark 5 FAIL "Telegram smoke alert"
fi

# ----------------------------------------------------------------------
echo
echo "--- #6. /halt smoke (operator-attested) ---"
if grep -qiE '/halt smoke.*operator.confirmed|halt sentinel|operator typed .*halt' state/phases/phase-5-vps.md ; then
  echo "    ATTESTED — see state/phases/phase-5-vps.md (5.5 row + 'What's next' table)"
  mark 6 PASS "/halt smoke (attested)"
else
  echo "    no attestation found in state/phases/phase-5-vps.md"
  mark 6 FAIL "/halt smoke"
fi

# ----------------------------------------------------------------------
echo
echo "--- #7. 24h bot-staging journal: zero unhandled exceptions ---"
exc=$($SSH "journalctl -u bot-staging.service --no-pager --since '24 hours ago' 2>/dev/null | grep -cE 'Traceback|Exception|ERROR|CRITICAL' || true" 2>/dev/null)
echo "    exception count (24h) = $exc"
if [[ "$exc" =~ ^[0-9]+$ ]] && [[ "$exc" -eq 0 ]]; then
  mark 7 PASS "24h staging logs zero exceptions"
else
  mark 7 FAIL "24h staging logs have exceptions"
fi

# ----------------------------------------------------------------------
echo
echo "--- #8. litestream replicating trades.db (active + S3 upload evidence + restore-tested) ---"
ls_active=$($SSH "systemctl is-active litestream.service 2>/dev/null || true" 2>/dev/null)
echo "    litestream.service is-active = $ls_active"

# litestream 0.5.x has no `snapshots`/`generations` subcommands. Use journal
# evidence instead — every successful S3 upload logs `ltx file uploaded` or
# `snapshot complete`. At least one of those proves the service has talked
# to S3 since the systemd unit started.
upload_count=$($SSH "journalctl -u litestream.service --no-pager 2>/dev/null | grep -cE 'ltx file uploaded|snapshot complete' || true" 2>/dev/null)
echo "    journal entries with 'ltx file uploaded' or 'snapshot complete' = $upload_count"

restore_evidence="runbooks/gate-evidence/phase-5.7-litestream-restore.txt"
if [[ -f "$restore_evidence" ]] && grep -q "RESTORE OK — byte-for-byte identical" "$restore_evidence" ; then
  echo "    restore drill = OK ($restore_evidence)"
  drill_ok=1
else
  echo "    restore drill = MISSING or did not pass"
  drill_ok=0
fi

if [[ "$ls_active" == "active" ]] && [[ "$upload_count" =~ ^[0-9]+$ ]] && [[ "$upload_count" -ge 1 ]] && [[ "$drill_ok" -eq 1 ]]; then
  mark 8 PASS "litestream active + S3 upload journal evidence + restore drill green"
else
  mark 8 FAIL "litestream not fully wired (see lines above)"
fi

# ----------------------------------------------------------------------
echo
echo "================================================================"
echo "  Verdict"
echo "================================================================"
for v in "${verdicts[@]}"; do
  echo "  $v"
done
echo
echo "  PASS: $PASS / 8"
echo "  FAIL: $FAIL / 8"
echo
if [[ "$FAIL" -eq 0 ]]; then
  echo "  PHASE 5 GATE: GREEN"
  echo "  Tag with: git tag -a phase-5-pass -m 'Phase 5 GREEN' && git push --tags"
  exit 0
else
  echo "  PHASE 5 GATE: RED"
  exit 1
fi
