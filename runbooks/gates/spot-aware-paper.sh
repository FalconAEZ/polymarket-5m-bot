#!/usr/bin/env bash
# Phase 11.A.2 gate — SpotAwareStrategy aggressive-mode paper-soak.
#
# 5 criteria mapped to runbooks/decisions/aggressive-mode-2026-05-09.md hard
# exit triggers:
#   1. Cumulative PnL (any rolling 24h)  ≥ -$50    (decisions JSONL, PM-truth)
#   2. Fire rate (24h projected)          ≤ 350/day (decisions JSONL)
#   3. Net WR (only if n≥100 settled)    ≥ 47%     (decisions JSONL, PM-truth)
#   4. Elapsed since aggressive launch    reportable
#                                            +28h pickup / 48h committed gate
#   5. Operational: services healthy      active   (SSH to VPS)
#
# IMPORTANT: this gate computes against staged (Polymarket-truth) decisions,
# NOT raw VPS decisions. Run `bash runbooks/scripts/sync_staging.sh` first,
# or this script will fail at the audit step. The dashboard on the VPS reads
# oracle-truth and disagrees — see the v2 prompt + the dashboard-truth-drift
# incident note.
#
# Run from operator's laptop:
#   bash runbooks/gates/spot-aware-paper.sh | tee runbooks/gate-evidence/phase-11.a.2.txt
#
# Exits 0 iff none of criteria #1-#3 are BREACHED. Tag spot-aware-paper-pass
# by hand only when ALL criteria are OK AND elapsed >= 48h.

set -uo pipefail
cd "$(dirname "$0")/../.."

KEY="${LIGHTSAIL_KEY:-$HOME/Downloads/LightsailDefaultKey-eu-west-1.pem}"
USERHOST="${VPS_USERHOST:-ops@108.132.51.116}"
PORT="${VPS_PORT:-2222}"
SSH="ssh -i $KEY -p $PORT -o StrictHostKeyChecking=no -o BatchMode=yes $USERHOST"

AGG_LAUNCH_ISO="2026-05-08T22:26:15Z"

echo "============================================================================"
echo "Phase 11.A.2 gate — SpotAwareStrategy aggressive-mode"
echo "  started:           $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "  branch:            $(git rev-parse --abbrev-ref HEAD)"
echo "  head:              $(git rev-parse HEAD)"
echo "  vps:               $USERHOST (port $PORT)"
echo "  aggressive launch: $AGG_LAUNCH_ISO"
echo "============================================================================"
echo

# Make sure staging exists. Bail loudly if not.
if [[ ! -d state/staging/decisions ]] || [[ -z "$(ls -A state/staging/decisions 2>/dev/null)" ]]; then
  echo "FATAL: state/staging/decisions/ missing or empty."
  echo "       Run 'bash runbooks/scripts/sync_staging.sh' first."
  exit 2
fi

PASS=0
BREACH=0
verdicts=()

mark() {
  local n="$1" status="$2" name="$3"
  case "$status" in
    OK)
      echo "  [#$n OK] $name"
      PASS=$((PASS+1))
      ;;
    BREACH)
      echo "  [#$n BREACH] $name"
      BREACH=$((BREACH+1))
      ;;
    GATE-INACTIVE)
      echo "  [#$n GATE-INACTIVE] $name"
      ;;
    INFO)
      echo "  [#$n INFO] $name"
      ;;
  esac
  verdicts+=("$status  #$n  $name")
}

# ------------------------------------------------------------------
# Run the python audit once, parse fields
# ------------------------------------------------------------------
echo "--- audit data load ---"
audit_json=$(uv run python -c "
import json, datetime
from collections import defaultdict
from pathlib import Path

AGG_LAUNCH = datetime.datetime(2026, 5, 8, 22, 26, 15, tzinfo=datetime.timezone.utc)

fired, settled = [], {}
for p in sorted(Path('state/staging/decisions').glob('*.jsonl')):
    if p.suffix == '.bak': continue
    for line in p.read_text().splitlines():
        if not line.strip(): continue
        r = json.loads(line)
        if r.get('kind') == 'fired': fired.append(r)
        elif r.get('kind') == 'settled': settled[r['decision_id']] = r

now = datetime.datetime.now(datetime.timezone.utc)
elapsed_h = (now - AGG_LAUNCH).total_seconds() / 3600.0

agg_fires = [f for f in fired
             if 'mode=aggressive' in f.get('rationale', '')
             or datetime.datetime.fromtimestamp(f['decision_ts_ns']/1e9, tz=datetime.timezone.utc) >= AGG_LAUNCH]

agg_first_h = (datetime.datetime.fromtimestamp(min(f['decision_ts_ns'] for f in agg_fires)/1e9, tz=datetime.timezone.utc)
               if agg_fires else now)
agg_window_h = (now - agg_first_h).total_seconds() / 3600.0 or 0.001

n_fires = len(agg_fires)
n_filled = sum(1 for f in agg_fires if (settled.get(f['decision_id']) or {}).get('fill_at_settle'))
n_won = sum(1 for f in agg_fires if ((settled.get(f['decision_id']) or {}).get('pnl_usd') or 0.0) > 0)
n_lost = sum(1 for f in agg_fires if ((settled.get(f['decision_id']) or {}).get('pnl_usd') or 0.0) < 0)
total_pnl = sum((settled.get(f['decision_id']) or {}).get('pnl_usd') or 0.0 for f in agg_fires)
fire_rate_per_day = n_fires * 24.0 / agg_window_h

# Worst rolling-24h PnL: hour-bucket the PnL, then sum trailing-24h-windows.
by_hour = defaultdict(float)
for f in agg_fires:
    ts = datetime.datetime.fromtimestamp(f['decision_ts_ns']/1e9, tz=datetime.timezone.utc)
    by_hour[ts.strftime('%Y-%m-%d %H')] += (settled.get(f['decision_id']) or {}).get('pnl_usd') or 0.0

sorted_hours = sorted(by_hour.keys())
worst_24h = None
for i in range(len(sorted_hours)):
    trail = sum(by_hour[k] for k in sorted_hours[max(0, i-23):i+1])
    if worst_24h is None or trail < worst_24h:
        worst_24h = trail
worst_24h = worst_24h if worst_24h is not None else 0.0

print(json.dumps({
    'elapsed_h': elapsed_h,
    'agg_window_h': agg_window_h,
    'n_fires': n_fires,
    'n_filled': n_filled,
    'n_won': n_won,
    'n_lost': n_lost,
    'wr_denom': n_won + n_lost,
    'wr_pct': (100.0 * n_won / max(n_won + n_lost, 1)),
    'total_pnl': total_pnl,
    'fire_rate_per_day': fire_rate_per_day,
    'worst_24h_pnl': worst_24h,
}))
" 2>/dev/null)

if [[ -z "$audit_json" ]]; then
  echo "FATAL: python audit returned no output. Aborting gate."
  exit 3
fi

echo "  raw audit: $audit_json"
echo

# Parse fields
ELAPSED_H=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['elapsed_h'])")
N_FIRES=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['n_fires'])")
N_FILLED=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['n_filled'])")
WR_DENOM=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['wr_denom'])")
WR_PCT=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['wr_pct'])")
TOTAL_PNL=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['total_pnl'])")
FIRE_RATE=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['fire_rate_per_day'])")
WORST_24H=$(python3 -c "import json,sys; print(json.loads('''$audit_json''')['worst_24h_pnl'])")

# ------------------------------------------------------------------
echo "--- #1. Cumulative PnL (worst rolling 24h) ≥ -\$50 ---"
echo "    worst rolling 24h PnL = \$$WORST_24H"
echo "    cumulative PnL (full window) = \$$TOTAL_PNL"
if python3 -c "import sys; sys.exit(0 if float('$WORST_24H') >= -50.0 else 1)"; then
  mark 1 OK "rolling 24h PnL within -\$50 floor"
else
  mark 1 BREACH "rolling 24h PnL below -\$50 floor"
fi
echo

# ------------------------------------------------------------------
echo "--- #2. Fire rate ≤ 350/day ---"
echo "    fire rate = ${FIRE_RATE}/day  (n=$N_FIRES over ${ELAPSED_H}h aggressive window)"
if python3 -c "import sys; sys.exit(0 if float('$FIRE_RATE') <= 350.0 else 1)"; then
  mark 2 OK "fire rate within 350/day cap"
else
  mark 2 BREACH "fire rate exceeds 350/day cap"
fi
echo

# ------------------------------------------------------------------
echo "--- #3. Net WR ≥ 47% (only if n_settled ≥ 100) ---"
echo "    net WR = ${WR_PCT}%  (n=$WR_DENOM filled+settled)"
if python3 -c "import sys; sys.exit(0 if int('$WR_DENOM') >= 100 else 1)"; then
  if python3 -c "import sys; sys.exit(0 if float('$WR_PCT') >= 47.0 else 1)"; then
    mark 3 OK "net WR within 47% floor"
  else
    mark 3 BREACH "net WR below 47% floor"
  fi
else
  echo "    n_settled < 100 — gate inactive"
  mark 3 GATE-INACTIVE "n_settled < 100"
fi
echo

# ------------------------------------------------------------------
echo "--- #4. Elapsed since aggressive launch ---"
ELAPSED_INT=$(python3 -c "print(int(float('$ELAPSED_H')))")
echo "    elapsed = ${ELAPSED_H}h"
if [[ $ELAPSED_INT -ge 48 ]]; then
  mark 4 OK "≥ 48h elapsed (full gate window)"
elif [[ $ELAPSED_INT -ge 24 ]]; then
  mark 4 INFO "≥ 24h elapsed (pickup minimum) but < 48h (committed gate review)"
else
  mark 4 INFO "< 24h elapsed (pre-pickup; verdict is informational)"
fi
echo

# ------------------------------------------------------------------
echo "--- #5. Services healthy (SSH probe) ---"
svc_status=$($SSH "systemctl is-active bot-staging.service tg-alerter.service grafana-agent.service litestream.service" 2>/dev/null | tr '\n' ' ')
echo "    services (bot-staging tg-alerter grafana-agent litestream): $svc_status"
exc_count=$($SSH "journalctl -u bot-staging.service --no-pager --since '24 hours ago' 2>/dev/null | grep -cE 'Traceback|Exception|ERROR|CRITICAL' || true" 2>/dev/null)
echo "    bot-staging exception count (24h): $exc_count"
all_active=true
for s in $svc_status; do
  [[ "$s" == "active" ]] || all_active=false
done
if [[ "$all_active" == "true" ]] && [[ "$exc_count" =~ ^[0-9]+$ ]] && [[ "$exc_count" -eq 0 ]]; then
  mark 5 OK "services active + zero unhandled exceptions in 24h"
else
  mark 5 BREACH "service unhealthy or exceptions present"
fi
echo

# ------------------------------------------------------------------
echo "============================================================"
echo "  Verdict"
echo "============================================================"
for v in "${verdicts[@]}"; do
  echo "  $v"
done
echo
echo "  OK:     $PASS"
echo "  BREACH: $BREACH"
echo

if [[ $BREACH -gt 0 ]]; then
  echo "  PHASE 11.A.2 GATE: REVERT (≥1 hard criterion breached)"
  exit 1
elif [[ $ELAPSED_INT -ge 48 ]]; then
  echo "  PHASE 11.A.2 GATE: PROMOTE (all OK + ≥48h elapsed)"
  echo "  Tag with: git tag -a spot-aware-paper-pass -m 'Phase 11.A.2 GREEN'"
  exit 0
elif [[ $ELAPSED_INT -ge 24 ]]; then
  echo "  PHASE 11.A.2 GATE: HOLD (≥24h elapsed, no breach, but < 48h committed mark)"
  echo "  Operator may promote early or wait for 48h review."
  exit 0
else
  echo "  PHASE 11.A.2 GATE: DEFER (< 24h elapsed; verdicts are informational)"
  echo "  No binding promote/revert in this run."
  exit 0
fi
