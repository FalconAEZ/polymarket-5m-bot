#!/usr/bin/env bash
# Polymarket BTC 5-Min Bot — bootstrap
# Run from the project root. Idempotent.
# Does NOT create web accounts (those need a browser).
# Does NOT load Anthropic credits (do that on console.anthropic.com).
set -euo pipefail

echo "== Polymarket BTC 5-Min Bot — bootstrap =="

# 1. brew + brew packages
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
for p in git gh node direnv age jq; do
  brew list "$p" >/dev/null 2>&1 || brew install "$p"
done
command -v wscat >/dev/null || npm install -g wscat

# 2. uv (Python pkg manager)
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. project skeleton
[ -f pyproject.toml ] || uv init --python 3.11 --package
uv add --dev mypy ruff pytest pytest-asyncio pytest-cov import-linter pre-commit anthropic
mkdir -p src/polymarket_bot tests design references state config
mkdir -p runbooks/incidents runbooks/gates runbooks/postmortems runbooks/scripts
mkdir -p state/runbooks state/postmortems state/research/bonereaper
touch src/polymarket_bot/__init__.py tests/__init__.py

# 4. drop Polymarket/agent-skills into ~/.claude/skills/
mkdir -p ~/.claude/skills
[ -d ~/.claude/skills/agent-skills ] || \
  git clone https://github.com/Polymarket/agent-skills.git ~/.claude/skills/agent-skills

# 5. clone reference repos (gitignored)
mkdir -p references && pushd references >/dev/null
for repo in Polymarket/py-clob-client Polymarket/rs-clob-client \
            Polymarket/agents Polymarket/poly-market-maker \
            evan-kolberg/prediction-market-backtesting \
            aulekator/Polymarket-BTC-15-Minute-Trading-Bot \
            ThinkEnigmatic/polymarket-bot-arena ; do
  [ -d "$(basename "$repo")" ] || git clone --depth 1 "https://github.com/$repo.git"
done
[ -d archetapp-5m-bot ] || git clone --depth 1 \
  https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69 archetapp-5m-bot
popd >/dev/null

# 6. .gitignore protects secrets and big files
if ! grep -q "^.envrc$" .gitignore 2>/dev/null; then
  cat >> .gitignore <<'EOF'
.envrc
*.age
references/
state/
runbooks/gate-evidence/
ticks/
trades.db
*.db-shm
*.db-wal
EOF
fi

# 7. .envrc.example (committed) and reminder to fill .envrc
[ -f .envrc.example ] || cat > .envrc.example <<'EOF'
# Copy to .envrc, fill in real values, then run `direnv allow`
export ANTHROPIC_API_KEY="sk-ant-..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
export POLYGON_RPC_URL=""

# Filled in Phase 1 (do NOT add until then)
export POLY_PRIVATE_KEY=""
export POLY_API_KEY=""
export POLY_API_SECRET=""
export POLY_API_PASSPHRASE=""
EOF

# 8. Done
echo ""
echo "== bootstrap complete =="
echo "NEXT: cp .envrc.example .envrc; fill in real values; direnv allow"
echo "THEN: review the verification checklist (REQUIREMENTS.pdf §15) before Phase 0"
