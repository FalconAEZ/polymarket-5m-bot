#!/usr/bin/env bash
# Phase 0 gate evidence script.
# Verifies the project foundation is solid before advancing to Phase 1.
# Tee output to runbooks/gate-evidence/phase-0.txt (caller responsibility OR
# `make gate-0` does it for you).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Make sure direnv-loaded vars are available even when invoked from a fresh shell.
if [ -f "$ROOT/.envrc" ] && command -v direnv >/dev/null 2>&1; then
  set -a
  # shellcheck source=/dev/null
  source <(direnv export bash 2>/dev/null) || true
  set +a
fi
# Fallback: source .envrc directly if env vars still not set.
if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -f "$ROOT/.envrc" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ROOT/.envrc"
  set +a
fi

EVIDENCE="$ROOT/runbooks/gate-evidence/phase-0.txt"
mkdir -p "$(dirname "$EVIDENCE")"

{
  echo "== PHASE 0 GATE EVIDENCE =="
  echo "  date: $(date -u +%FT%TZ)"
  echo "  rev:  $(git rev-parse HEAD 2>/dev/null || echo '<no-git>')"
  echo

  echo "[gate-0.1] python ≥ 3.11 (uv-managed)"
  uv run python -c "import sys; assert sys.version_info >= (3, 11), sys.version; print('   ', sys.version.split()[0])"
  echo

  echo "[gate-0.2] make verify (ruff + mypy --strict + pytest)"
  make verify
  echo

  echo "[gate-0.3] github remote configured"
  gh repo view --json url -q .url
  git remote -v | head -1
  echo

  echo "[gate-0.4] agent-skills present at ~/.claude/skills/agent-skills/"
  for f in authentication.md gasless.md; do
    test -f "$HOME/.claude/skills/agent-skills/$f" && echo "    ✓ $f" || (echo "    ✗ $f MISSING" && exit 1)
  done
  echo

  echo "[gate-0.5] reference repos cloned (gitignored)"
  for r in py-clob-client agents poly-market-maker prediction-market-backtesting Polymarket-BTC-15-Minute-Trading-Bot polymarket-bot-arena archetapp-5m-bot; do
    test -d "$ROOT/references/$r" && echo "    ✓ references/$r" || (echo "    ✗ references/$r MISSING" && exit 1)
  done
  echo

  echo "[gate-0.6] secrets loaded (shape-checked, never printed)"
  test -n "${TELEGRAM_BOT_TOKEN:-}" && echo "    ✓ TELEGRAM_BOT_TOKEN  (${#TELEGRAM_BOT_TOKEN} chars)" || (echo "    ✗ TELEGRAM_BOT_TOKEN missing" && exit 1)
  test -n "${TELEGRAM_CHAT_ID:-}" && echo "    ✓ TELEGRAM_CHAT_ID    ($TELEGRAM_CHAT_ID)" || (echo "    ✗ TELEGRAM_CHAT_ID missing" && exit 1)
  test -n "${ANTHROPIC_API_KEY:-}" && echo "    ✓ ANTHROPIC_API_KEY   (${#ANTHROPIC_API_KEY} chars, prefix ${ANTHROPIC_API_KEY:0:10}...)" || (echo "    ✗ ANTHROPIC_API_KEY missing" && exit 1)
  test -n "${POLYGON_RPC_URL:-}" && echo "    ✓ POLYGON_RPC_URL     (${POLYGON_RPC_URL:0:35}...)" || (echo "    ✗ POLYGON_RPC_URL missing" && exit 1)
  echo

  echo "[gate-0.7] Telegram smoke message (will arrive on phone)"
  TG_RESP=$(curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=phase-0 gate smoke test $(date -u +%FT%TZ)")
  echo "$TG_RESP" | python3 -c "import sys, json; d = json.load(sys.stdin); print('    sent: ok=' + str(d['ok']) + ' message_id=' + str(d['result']['message_id']))"
  echo

  echo "[gate-0.8] Polygon RPC live (chain_id check)"
  HTTPS_URL=$(echo "$POLYGON_RPC_URL" | sed 's|^wss:|https:|')
  CHAIN=$(curl -fsS -X POST "$HTTPS_URL" -H "content-type: application/json" \
    -d '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' \
    | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"])')
  test "$CHAIN" = "0x89" && echo "    ✓ chain_id $CHAIN (137 = Polygon mainnet)" || (echo "    ✗ unexpected chain $CHAIN" && exit 1)
  echo

  echo "[gate-0.9] required project files exist"
  for f in pyproject.toml uv.lock mypy.ini ruff.toml .importlinter Makefile .pre-commit-config.yaml .envrc.example .gitignore CLAUDE.md README.md RUNBOOK.md MASTERPLAN.md .github/workflows/ci.yml runbooks/scripts/check_headers.py runbooks/contacts.md state/runbooks/README.md; do
    test -f "$ROOT/$f" && echo "    ✓ $f" || (echo "    ✗ $f MISSING" && exit 1)
  done
  echo

  echo "[gate-0.10] no secrets staged for commit"
  if git diff --cached --name-only | grep -E '^(\.envrc$|env req\.rtf|.*\.age$)' >/dev/null; then
    echo "    ✗ SECRETS STAGED — refusing to pass gate"
    exit 1
  else
    echo "    ✓ no secrets staged"
  fi
  echo

  echo "PHASE 0 GATE PASSED $(date -u +%FT%TZ)  $(git rev-parse HEAD)"
} | tee "$EVIDENCE"
