#!/usr/bin/env bash
# sync_staging.sh — pull VPS bot-staging state to laptop for dashboard viewing.
#
# Mirrors /home/ops/polymarket-5m-bot/state/decisions/ + token_side_index.json
# into ./state/staging/, dumps the bot-staging journal as state/staging/paper.log,
# synthesizes a feeds_health.json from journal grep so the existing Phase 4.5
# dashboard can render the staging data unchanged. Then prints a one-shot
# numerical summary (uptime, queue depth, decision count, dropped, sentinel)
# pulled live over SSH.
#
# Usage:  bash runbooks/scripts/sync_staging.sh
# After:  PMB_DASH_STATE_DIR=state/staging uv run streamlit run scripts/dashboard.py
# Or:     make dash-staging   (does both)

set -euo pipefail

KEY="${LIGHTSAIL_KEY:-$HOME/Downloads/LightsailDefaultKey-eu-west-1.pem}"
HOST="${VPS_HOST:-ops@108.132.51.116}"
PORT="${VPS_PORT:-2222}"
REMOTE_ROOT="/home/ops/polymarket-5m-bot"
LOCAL_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STAGING="$LOCAL_ROOT/state/staging"

mkdir -p "$STAGING/decisions" "$STAGING/decisions.raw"

# Two-stage path so the dashboard never reads a half-resolved view:
#   decisions.raw/  ← rsynced from VPS (oracle-truth, partially WRONG per
#                     runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md)
#   decisions/      ← rewritten by resolve_decisions.py with Polymarket truth.
#                     Atomic-rename writes; dashboard reads from here.
echo "==> rsync VPS state/decisions/ → $STAGING/decisions.raw/"
rsync -az --delete \
  -e "ssh -i $KEY -p $PORT -o ConnectTimeout=10" \
  "$HOST:$REMOTE_ROOT/state/decisions/" \
  "$STAGING/decisions.raw/"

echo "==> rsync VPS state/token_side_index.json"
rsync -az \
  -e "ssh -i $KEY -p $PORT -o ConnectTimeout=10" \
  "$HOST:$REMOTE_ROOT/state/token_side_index.json" \
  "$STAGING/token_side_index.json" 2>/dev/null || true

echo "==> dump bot-staging journal → $STAGING/paper.log (last 24h)"
ssh -i "$KEY" -p "$PORT" "$HOST" \
  'journalctl -u bot-staging.service --no-pager --since "24 hours ago" --output=short-iso 2>/dev/null' \
  > "$STAGING/paper.log"

echo "==> dump tg-alerter journal → $STAGING/capture.log (placeholder slot)"
# The Phase 4.5 dashboard expects capture.log; we repurpose it for the alerter
# journal so the operator can see Telegram traffic next to bot logs.
ssh -i "$KEY" -p "$PORT" "$HOST" \
  'journalctl -u tg-alerter.service --no-pager --since "24 hours ago" --output=short-iso 2>/dev/null' \
  > "$STAGING/capture.log"

BOT_ACTIVE=$(ssh -i "$KEY" -p "$PORT" "$HOST" 'systemctl is-active bot-staging.service' 2>/dev/null || echo inactive)
ACTIVE_FLAG=$([ "$BOT_ACTIVE" = "active" ] && echo true || echo false)

echo "==> synthesize feeds_health.json (bot-staging=$BOT_ACTIVE)"
python3 "$LOCAL_ROOT/runbooks/scripts/synthesize_feeds_health.py" \
  --journal "$STAGING/paper.log" \
  --out "$STAGING/feeds_health.json" \
  --bot-active "$ACTIVE_FLAG"

# Re-resolve settled decisions against Polymarket Gamma — see
# runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md. Reads from
# decisions.raw/ (just-rsynced, oracle-truth) and writes to decisions/
# (Polymarket-truth). Atomic-rename writes per file; the dashboard's
# read path NEVER sees a half-synced or half-resolved view.
echo "==> re-resolve raw → cooked (Polymarket truth source)"
if uv run python "$LOCAL_ROOT/scripts/resolve_decisions.py" \
    "$STAGING/decisions.raw/" "$STAGING/decisions/" 2>&1 | sed 's/^/  /'; then
  :
else
  echo "  (re-resolution failed — dashboard will continue reading prior cooked dir)"
fi

echo "==> live VPS status:"
ssh -i "$KEY" -p "$PORT" "$HOST" '
  echo "  bot-staging:    $(systemctl is-active bot-staging.service)  (since $(systemctl show -p ActiveEnterTimestamp --value bot-staging.service))"
  echo "  tg-alerter:     $(systemctl is-active tg-alerter.service)"
  echo "  grafana-agent:  $(systemctl is-active grafana-agent.service)"
  echo "  alerts queued:  $(redis-cli LLEN polybot:alerts)"
  echo "  alerts in DLQ:  $(redis-cli LLEN polybot:alerts:dlq)"
  if [ -f /home/ops/polymarket-5m-bot/state/halt.sentinel ]; then
    echo "  HALT SENTINEL:  PRESENT  (bot is halted)"
  else
    echo "  halt sentinel:  absent  (bot running normally)"
  fi
  count=$(grep -h "\"kind\":\"fired\"" /home/ops/polymarket-5m-bot/state/decisions/*.jsonl 2>/dev/null | wc -l | tr -d " ")
  echo "  fired decisions: ${count:-0}"
'

echo "==> done. open the dashboard with:"
echo "    PMB_DASH_STATE_DIR=state/staging uv run streamlit run scripts/dashboard.py"
echo "    (or just: make dash-staging)"
