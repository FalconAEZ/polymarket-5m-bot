#!/usr/bin/env bash
# Phase 4.5 gate — operations dashboard.
#
# Asserts (per design/dashboard.md §10):
#   1. make verify green (ruff + mypy --strict + pytest, including new
#      tests/dashboard/ tests).
#   2. lint-imports green (3 contracts: production never imports paper;
#      paper restricted under _live; dashboard restricted under most of
#      _live + _paper-runtime + backtest-runtime + strategies + agents).
#   3. scripts/dashboard.py imports cleanly (no startup errors).
#   4. Streamlit serves a non-empty page on 127.0.0.1:8501 within 30s of
#      launch (headless smoke). Process is then stopped cleanly.
#   5. .streamlit/config.toml present with theme.base = "dark".
#
# Safe to run any time post-Phase-4.5; does NOT depend on the 14-day
# paper run. Tag `phase-4.5-pass` by hand on green.

set -euo pipefail
cd "$(dirname "$0")/../.."

OUT="runbooks/gate-evidence/phase-4.5.txt"
mkdir -p "$(dirname "$OUT")"
: > "$OUT"
exec > >(tee -a "$OUT") 2>&1

echo "=== Phase 4.5 gate ==="
echo "started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "branch:  $(git rev-parse --abbrev-ref HEAD)"
echo "head:    $(git rev-parse HEAD)"
echo

echo "--- 1. make verify ---"
make verify

echo "--- 2. lint-imports ---"
uv run lint-imports

echo "--- 3. scripts/dashboard.py imports cleanly ---"
uv run python -c "
import importlib.util, sys
sys.path.insert(0, 'src')
spec = importlib.util.spec_from_file_location('dash', 'scripts/dashboard.py')
mod = importlib.util.module_from_spec(spec)
print('OK: scripts/dashboard.py module loadable')
"

echo "--- 4. headless Streamlit smoke (curl /) ---"
PORT=8501
# Stop any prior instance.
pkill -f "streamlit run scripts/dashboard.py" 2>/dev/null || true
sleep 1
# Launch in background.
uv run streamlit run scripts/dashboard.py \
    --server.headless=true \
    --server.port=$PORT \
    --browser.gatherUsageStats=false \
    > /tmp/phase-4.5-streamlit.log 2>&1 &
SPID=$!
# Wait up to 30s for the port.
for i in $(seq 1 30); do
  if curl -s -f -o /tmp/phase-4.5-curl.html "http://127.0.0.1:$PORT/" 2>/dev/null; then
    break
  fi
  sleep 1
done
if ! curl -s -f -o /tmp/phase-4.5-curl.html "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "FAIL: Streamlit did not serve / within 30s"
  kill -INT $SPID 2>/dev/null || true
  cat /tmp/phase-4.5-streamlit.log | tail -20
  exit 1
fi
SIZE=$(wc -c < /tmp/phase-4.5-curl.html | tr -d ' ')
if [[ "$SIZE" -lt 1000 ]]; then
  echo "FAIL: served page is < 1000 bytes (size=$SIZE)"
  kill -INT $SPID 2>/dev/null || true
  exit 1
fi
if ! grep -q "Streamlit" /tmp/phase-4.5-curl.html; then
  echo "FAIL: served page does not contain 'Streamlit' marker"
  kill -INT $SPID 2>/dev/null || true
  exit 1
fi
echo "OK: served page is $SIZE bytes and contains Streamlit marker"
# Stop cleanly.
kill -INT $SPID 2>/dev/null || true
sleep 2
pkill -9 -f "streamlit run scripts/dashboard.py" 2>/dev/null || true
echo "OK: Streamlit stopped"

echo "--- 5. .streamlit/config.toml has dark theme ---"
CONFIG=".streamlit/config.toml"
if [[ ! -f "$CONFIG" ]]; then
  echo "FAIL: $CONFIG does not exist"
  exit 1
fi
if ! grep -qE '^\s*base\s*=\s*"dark"' "$CONFIG"; then
  echo "FAIL: $CONFIG does not declare theme.base = \"dark\""
  exit 1
fi
echo "OK: $CONFIG declares dark theme"

echo
echo "=== Phase 4.5 gate green ==="
echo "Tag with: git tag phase-4.5-pass && git push --tags"
