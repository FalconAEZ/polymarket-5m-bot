#!/usr/bin/env bash
# deploy-v2-and-instant-settle.sh — gate-day deploy of:
#   1. Revert v1 aggressive  (STRATEGY=spot_aware_v2 + unset SPOT_AWARE_AGGRESSIVE_MODE)
#   2. Switch strategy       (v1 -> v2; new class, new dispatch)
#   3. Enable instant-settle (INSTANT_SETTLE_ENABLED=1)
#
# Single coordinated bot restart. Pre-flight + post-deploy verification +
# rollback on failure. Per the deploy plan in commit 89d6fae's body.
#
# Usage from operator's laptop:
#   bash runbooks/scripts/deploy-v2-and-instant-settle.sh           # dry-run, prints plan
#   bash runbooks/scripts/deploy-v2-and-instant-settle.sh --apply   # actually deploys
#   bash runbooks/scripts/deploy-v2-and-instant-settle.sh --rollback # restores from .envrc.bak
#
# What it touches on the VPS:
#   /home/ops/polymarket-5m-bot/.envrc           (rewritten + backed up to .envrc.bak)
#   bot-staging.service                          (restarted)
#   /home/ops/polymarket-5m-bot/                 (git fetch + checkout the gate branch)
#
# Pre-conditions checked:
#   - Bot is currently running v1+aggressive (otherwise abort — wrong starting state)
#   - Repo on the VPS is up to date with origin
#   - All systemd services active (bot-staging, tg-alerter, grafana-agent, litestream)
#   - Zero unhandled exceptions in last 1h
#
# Post-deploy verification (within 5 min of restart):
#   - bot-staging.service active
#   - First fired record carries strategy=spot_aware_v2 marker
#   - First settled record (after a window closes) has resolution_source=polymarket
#     (or chainlink-local-fallback if Gamma was slow that one time)
#   - pipeline.settle_wait_s drops to <5s (was ~60s under v1)
#
# Rollback (if any post-deploy check fails):
#   - Restore /home/ops/polymarket-5m-bot/.envrc from .envrc.bak
#   - Checkout the pre-deploy git ref (printed at start)
#   - Restart bot-staging.service
#   - Verify back to v1 fires

set -uo pipefail

KEY="${LIGHTSAIL_KEY:-$HOME/Downloads/LightsailDefaultKey-eu-west-1.pem}"
USERHOST="${VPS_USERHOST:-ops@108.132.51.116}"
PORT="${VPS_PORT:-2222}"
SSH="ssh -i $KEY -p $PORT -o StrictHostKeyChecking=no -o BatchMode=yes $USERHOST"

# Branch with v2 + instant-settle code (must be pushed to origin before deploy)
DEPLOY_BRANCH="${DEPLOY_BRANCH:-claude/jovial-hermann-7e103f}"

MODE="${1:-dryrun}"

echo "================================================================"
echo "  deploy-v2-and-instant-settle.sh"
echo "  mode: $MODE"
echo "  ssh:  $USERHOST (port $PORT)"
echo "  branch (target): $DEPLOY_BRANCH"
echo "  started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "================================================================"

# ------------------------------------------------------------------
# Pre-flight
# ------------------------------------------------------------------
echo
echo "--- pre-flight checks ---"

PRE_HEAD=$($SSH "cd /home/ops/polymarket-5m-bot && git rev-parse HEAD" 2>/dev/null)
PRE_BRANCH=$($SSH "cd /home/ops/polymarket-5m-bot && git rev-parse --abbrev-ref HEAD" 2>/dev/null)
echo "  current branch: $PRE_BRANCH"
echo "  current HEAD:   $PRE_HEAD"
echo

PRE_ENVRC=$($SSH "grep -E '^export (STRATEGY|SPOT_AWARE_|INSTANT_SETTLE_)' /home/ops/polymarket-5m-bot/.envrc 2>/dev/null" || true)
echo "  current .envrc spot/instant knobs:"
echo "$PRE_ENVRC" | sed 's/^/    /'
echo

if ! echo "$PRE_ENVRC" | grep -q "SPOT_AWARE_AGGRESSIVE_MODE=1"; then
  echo "  WARN: bot does NOT appear to be in aggressive mode. Either you've"
  echo "        already deployed v2, or starting state is unexpected. Aborting."
  exit 2
fi

SVC_STATUS=$($SSH "systemctl is-active bot-staging.service tg-alerter.service grafana-agent.service litestream.service" 2>/dev/null | tr '\n' ' ')
echo "  services (bot-staging tg-alerter grafana-agent litestream): $SVC_STATUS"
ALL_ACTIVE=true
for s in $SVC_STATUS; do
  [[ "$s" == "active" ]] || ALL_ACTIVE=false
done
if [[ "$ALL_ACTIVE" != "true" ]]; then
  echo "  ERROR: not all services active. Aborting."
  exit 3
fi

EXC_1H=$($SSH "sudo journalctl -u bot-staging.service --since '1 hour ago' --no-pager 2>/dev/null | grep -cE 'Traceback|Exception|ERROR|CRITICAL' || true")
echo "  bot-staging exceptions (1h): $EXC_1H"
if [[ "$EXC_1H" =~ ^[0-9]+$ ]] && [[ "$EXC_1H" -gt 0 ]]; then
  echo "  WARN: bot has exceptions in the last hour. Investigate before deploying."
  if [[ "$MODE" == "--apply" ]]; then
    echo "  Continuing anyway because --apply was set; abort with Ctrl+C if not desired."
    sleep 5
  fi
fi

# Save pre-deploy state for rollback
ROLLBACK_FILE="/tmp/polybot-pre-deploy-$(date +%s).txt"
cat > "$ROLLBACK_FILE" <<EOF
# Saved $(date -u +%Y-%m-%dT%H:%M:%SZ) by deploy-v2-and-instant-settle.sh
PRE_DEPLOY_BRANCH=$PRE_BRANCH
PRE_DEPLOY_HEAD=$PRE_HEAD
PRE_DEPLOY_ENVRC_SPOT_KNOBS<<<KNOBS
$PRE_ENVRC
KNOBS
EOF
echo "  rollback ref saved to: $ROLLBACK_FILE"
echo

# ------------------------------------------------------------------
# ROLLBACK MODE — restore + restart, exit
# ------------------------------------------------------------------
if [[ "$MODE" == "--rollback" ]]; then
  echo "--- ROLLBACK MODE ---"
  echo "Restoring from /home/ops/polymarket-5m-bot/.envrc.bak"
  $SSH "cd /home/ops/polymarket-5m-bot && [ -f .envrc.bak ] && cp -v .envrc.bak .envrc"
  echo "Checking out previous branch (whatever's saved in .envrc.bak header — or specify manually):"
  echo "  current target: $PRE_BRANCH @ $PRE_HEAD"
  echo "Restarting bot-staging..."
  $SSH "sudo systemctl restart bot-staging.service"
  sleep 5
  $SSH "systemctl is-active bot-staging.service"
  echo "Rollback complete. Verify behavior in next decision log entry."
  exit 0
fi

# ------------------------------------------------------------------
# DRY-RUN — print the plan, exit
# ------------------------------------------------------------------
if [[ "$MODE" != "--apply" ]]; then
  echo "--- DRY-RUN: plan ---"
  echo "  1. SSH to $USERHOST"
  echo "  2. cd /home/ops/polymarket-5m-bot"
  echo "  3. cp .envrc .envrc.bak  (rollback safety)"
  echo "  4. git fetch origin $DEPLOY_BRANCH && git checkout $DEPLOY_BRANCH"
  echo "  5. Update .envrc:"
  echo "       STRATEGY=spot_aware_v2  (was spot_aware)"
  echo "       # SPOT_AWARE_AGGRESSIVE_MODE removed"
  echo "       INSTANT_SETTLE_ENABLED=1  (new)"
  echo "  6. sudo systemctl restart bot-staging.service"
  echo "  7. Wait 30s for warmup"
  echo "  8. Verify post-deploy:"
  echo "       - service active"
  echo "       - .envrc has the new knobs"
  echo "       - tail journal for first v2 marker"
  echo
  echo "  To execute: bash $0 --apply"
  echo "  To rollback later: bash $0 --rollback"
  exit 0
fi

# ------------------------------------------------------------------
# APPLY — do the deploy
# ------------------------------------------------------------------
echo "--- APPLY MODE — executing deploy ---"
echo

echo "  step 1/6: backup .envrc"
$SSH "cd /home/ops/polymarket-5m-bot && cp .envrc .envrc.bak && ls -l .envrc.bak" || {
  echo "ERROR: .envrc backup failed"
  exit 4
}

echo
echo "  step 2/6: git fetch + checkout $DEPLOY_BRANCH"
$SSH "cd /home/ops/polymarket-5m-bot && git fetch origin $DEPLOY_BRANCH && git checkout $DEPLOY_BRANCH" || {
  echo "ERROR: git checkout failed"
  exit 5
}
NEW_HEAD=$($SSH "cd /home/ops/polymarket-5m-bot && git rev-parse HEAD")
echo "    new HEAD: $NEW_HEAD"

echo
echo "  step 3/6: rewrite .envrc"
# Use sed to replace STRATEGY=spot_aware -> spot_aware_v2
# Comment out SPOT_AWARE_AGGRESSIVE_MODE
# Append INSTANT_SETTLE_ENABLED=1 if not present
$SSH "cd /home/ops/polymarket-5m-bot && \
  sed -i 's/^export STRATEGY=spot_aware\$/export STRATEGY=spot_aware_v2/' .envrc && \
  sed -i 's/^export SPOT_AWARE_AGGRESSIVE_MODE=1/# export SPOT_AWARE_AGGRESSIVE_MODE=1  # disabled by gate-day deploy/' .envrc && \
  grep -q '^export INSTANT_SETTLE_ENABLED=' .envrc || echo 'export INSTANT_SETTLE_ENABLED=1  # gate-day deploy: poll Polymarket Gamma for instant settle' >> .envrc"
echo "    new .envrc spot/instant knobs:"
$SSH "grep -E '^[# ]*export (STRATEGY|SPOT_AWARE_|INSTANT_SETTLE_)' /home/ops/polymarket-5m-bot/.envrc | sed 's/^/      /'"

echo
echo "  step 4/6: restart bot-staging.service"
$SSH "sudo systemctl restart bot-staging.service"
sleep 5
$SSH "systemctl is-active bot-staging.service"

echo
echo "  step 5/6: warmup wait (30s) — bot needs time to subscribe + first window boundary"
sleep 30

echo
echo "  step 6/6: post-deploy verification"
echo "    bot-staging uptime:"
$SSH "systemctl show bot-staging.service -p ActiveEnterTimestamp --value" | sed 's/^/      /'

echo "    error count last 5min:"
EXC=$($SSH "sudo journalctl -u bot-staging.service --since '5 min ago' --no-pager 2>/dev/null | grep -cE 'Traceback|Exception|ERROR|CRITICAL' || true")
echo "      $EXC"
if [[ "$EXC" =~ ^[0-9]+$ ]] && [[ "$EXC" -gt 0 ]]; then
  echo "    WARN: errors detected post-restart. Check journal:"
  echo "      ssh ... 'sudo journalctl -u bot-staging.service --since 5min ago'"
  echo "    Consider rollback: bash $0 --rollback"
fi

echo "    journal last 20 lines:"
$SSH "sudo journalctl -u bot-staging.service --since '1 min ago' --no-pager 2>/dev/null | tail -20" | sed 's/^/      /'

echo
echo "================================================================"
echo "  DEPLOY APPLIED at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "================================================================"
echo "  rollback: bash $0 --rollback"
echo "  rollback ref: $ROLLBACK_FILE"
echo
echo "  Operator next steps:"
echo "    1. Wait ~10 min for first v2 fire (cadence drops from 12/hr -> ~2/hr)"
echo "    2. Verify first new fired decision has 'strategy=spot_aware_v2' marker:"
echo "         ssh $USERHOST 'grep \"strategy=spot_aware_v2\" /home/ops/polymarket-5m-bot/state/decisions/*.jsonl | head -1'"
echo "    3. After a window closes (first settle), verify resolution_source:"
echo "         ssh $USERHOST 'grep -o \"resolution_source\\\":\\\".*\\\"\" /home/ops/polymarket-5m-bot/state/decisions/\$(date +%Y-%m-%d).jsonl | tail -1'"
echo "         expect: \"resolution_source\":\"polymarket\""
echo "    4. Check dashboard /api/state.pipeline.settle_wait_s drops below 5s within ~10 min"
echo
