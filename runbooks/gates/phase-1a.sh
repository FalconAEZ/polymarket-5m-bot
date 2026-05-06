#!/usr/bin/env bash
# Phase 1A gate evidence script.
# Verifies the no-money portion of Phase 1 is solid: wallets exist
# offline, .envrc is shape-correct, signing works against Polymarket
# without any wallet being funded. Phase 1B (funding + $5 test order)
# runs at pre-live; its gate is runbooks/gates/phase-1.sh.
# Tee output to runbooks/gate-evidence/phase-1a.txt (caller responsibility
# OR `make gate-1a` does it for you).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# Locate .envrc. In a regular checkout it sits at $ROOT. In a git worktree
# the actual .envrc lives in the parent project, so walk upward (mirroring
# direnv's hierarchical search).
ENVRC=""
SEARCH="$ROOT"
while [ "$SEARCH" != "/" ] && [ "$SEARCH" != "" ]; do
  if [ -f "$SEARCH/.envrc" ]; then
    ENVRC="$SEARCH/.envrc"
    break
  fi
  SEARCH="$(dirname "$SEARCH")"
done

# Make sure direnv-loaded vars are available even when invoked from a fresh shell.
if [ -n "$ENVRC" ] && command -v direnv >/dev/null 2>&1; then
  set -a
  # shellcheck source=/dev/null
  source <(direnv export bash 2>/dev/null) || true
  set +a
fi
# Fallback: source .envrc directly if env vars still not set.
if [ -z "${POLY_PRIVATE_KEY:-}" ] && [ -n "$ENVRC" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$ENVRC"
  set +a
fi

EVIDENCE="$ROOT/runbooks/gate-evidence/phase-1a.txt"
mkdir -p "$(dirname "$EVIDENCE")"
SECRETS_DIR="${PHASE_1A_SECRETS_DIR:-$HOME/secrets/polymarket-5m}"

{
  echo "== PHASE 1A GATE EVIDENCE =="
  echo "  date: $(date -u +%FT%TZ)"
  echo "  rev:  $(git rev-parse HEAD 2>/dev/null || echo '<no-git>')"
  echo "  secrets-dir: $SECRETS_DIR"
  echo

  echo "[gate-1a.1] make verify (ruff + mypy --strict + pytest)"
  make verify
  echo

  echo "[gate-1a.2] both .age files exist with valid age v1 armor"
  for role in funder signer; do
    AGE_PATH="$SECRETS_DIR/$role.age"
    test -f "$AGE_PATH" \
      || (echo "    ✗ $AGE_PATH MISSING (run scripts/genwallets.py)" && exit 1)
    HEAD21=$(head -c 21 "$AGE_PATH")
    test "$HEAD21" = "age-encryption.org/v1" \
      && echo "    ✓ $role.age  age-armored, $(wc -c <"$AGE_PATH" | tr -d ' ') bytes" \
      || (echo "    ✗ $role.age missing armor prefix (got '$HEAD21')" && exit 1)
  done
  echo

  echo "[gate-1a.3] secrets directory mode is 0700"
  DIR_MODE=$(stat -f '%Lp' "$SECRETS_DIR")
  test "$DIR_MODE" = "700" \
    && echo "    ✓ $SECRETS_DIR mode = 700" \
    || (echo "    ✗ $SECRETS_DIR mode = $DIR_MODE (expected 700)" && exit 1)
  echo

  echo "[gate-1a.4] .envrc mode is 0600"
  test -n "$ENVRC" \
    || (echo "    ✗ .envrc not found in $ROOT or any parent" && exit 1)
  ENVRC_MODE=$(stat -f '%Lp' "$ENVRC")
  test "$ENVRC_MODE" = "600" \
    && echo "    ✓ .envrc mode = 600  ($ENVRC)" \
    || (echo "    ✗ $ENVRC mode = $ENVRC_MODE (expected 600)" && exit 1)
  echo

  echo "[gate-1a.5] required POLY_* env vars present"
  for var in POLY_PRIVATE_KEY POLY_API_KEY POLY_API_SECRET POLY_API_PASSPHRASE; do
    eval VAL="\${$var:-}"
    test -n "$VAL" \
      && echo "    ✓ $var      (${#VAL} chars)" \
      || (echo "    ✗ $var missing — run derive_creds.py and direnv allow" && exit 1)
  done
  echo

  echo "[gate-1a.6] forbidden Funder env vars are NOT set"
  for forbidden in POLY_FUNDER_PRIVATE_KEY POLY_FUNDER_ADDRESS; do
    eval VAL="\${$forbidden:-}"
    test -z "$VAL" \
      && echo "    ✓ $forbidden  not set (correct)" \
      || (echo "    ✗ $forbidden IS SET — Funder material must not be in env" && exit 1)
  done
  echo

  echo "[gate-1a.7] forbidden Funder lines are NOT in .envrc"
  if grep -E '^\s*export\s+POLY_FUNDER' "$ENVRC" >/dev/null 2>&1; then
    echo "    ✗ POLY_FUNDER_* line found in $ENVRC — must not be there"
    exit 1
  else
    echo "    ✓ no POLY_FUNDER_* lines in .envrc"
  fi
  echo

  echo "[gate-1a.8] forbidden Funder material is NOT in any tracked file"
  if git grep -nE 'POLY_FUNDER_PRIVATE_KEY|POLY_FUNDER_ADDRESS' \
        -- ':!runbooks/wallet-ops.md' \
        ':!runbooks/gates/phase-1a.sh' \
        ':!design/gasless.md' \
        ':!design/genwallets.md' \
        2>/dev/null; then
    echo "    ✗ Funder env-var name found in tracked code — must not be there"
    exit 1
  else
    echo "    ✓ no POLY_FUNDER_* references in tracked code"
  fi
  echo

  echo "[gate-1a.9] no secrets staged for commit"
  if git diff --cached --name-only | grep -E '^(\.envrc$|.*\.age$)' >/dev/null; then
    echo "    ✗ SECRETS STAGED — refusing to pass gate"
    exit 1
  else
    echo "    ✓ no secrets staged"
  fi
  echo

  echo "[gate-1a.10] scripts/test_auth.py exits 0 (full L1+L2 auth check)"
  uv run python scripts/test_auth.py
  echo

  echo "PHASE 1A GATE PASSED $(date -u +%FT%TZ)  $(git rev-parse HEAD)"
} | tee "$EVIDENCE"
