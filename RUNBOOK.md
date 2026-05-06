# RUNBOOK.md — Polymarket BTC 5-Min Bot Execution Plan

> **Source of truth for execution.** When this file disagrees with `MASTERPLAN.md`, this wins until the next gate review. `MASTERPLAN.md` explains *why*; this explains *what to do next*.

**Owner:** Hamad (UAE) · **Started:** 2026-05-04 · **Status:** awaiting Phase 0 start

---

## A. Anchors

| Artifact | Path |
|---|---|
| Master plan (rationale) | `/Users/hamad/Desktop/PolyMarket-5m/MASTERPLAN.md` |
| Master plan PDF | `/Users/hamad/Desktop/PolyMarket-5m/MASTERPLAN.pdf` |
| **This runbook** | `/Users/hamad/Desktop/PolyMarket-5m/RUNBOOK.md` |
| Locked decisions | `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md` |
| Memory index | `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/MEMORY.md` |
| Gate evidence (built up over time) | `/Users/hamad/Desktop/PolyMarket-5m/runbooks/gate-evidence/phase-N.txt` |

---

## B. Locked Decisions (do not relitigate)

Mirror of `memory/project_decisions.md`. If you find yourself questioning one of these mid-phase, stop — open the decisions file, escalate to the user, do not silently override.

1. **UAE-resident operator** — Polymarket-permitted.
2. **Dublin AWS Lightsail eu-west-1** — sub-5ms to CLOB.
3. **NautilusTrader + py-clob-client** — engine + signing.
4. **Anthropic API only — OpenAI cut.** Deterministic Tier-3 catches LLM failures.
5. **3 agents + meta-decider** ensemble.
6. **Tier-3 deterministic fallback** = window-delta + oracle-gap, composite ≥ 0.6.
7. **Telegram bot (BotFather)** for operator alerts. Inbound `/halt`.
8. **GitHub private repo.**
9. **$5 flat per trade for first 100 trades**, then fractional Kelly.
10. **$1,000 starting bankroll.**
11. **Funder/Signer wallet separation** from Phase 1.
12. **Hardware wallet at $2k bankroll trigger**, not day 1.
13. **Phase 1 order:** derive creds → test sign → fund.
14. **Anthropic API budget tiers** (revised from real-bot empirical data $0.19-0.58/hour): $50 covers Phases 0-3 with cache discipline. Top up to **$150 before Phase 4** (paper 14d × 24/7). Top up to **$300 before Phase 6** if ensemble ROI confirmed. Sustained: **$200/month** OPEX.
15. **UTC everywhere** — logs, DB, daily notes.
16. **LLM-vs-deterministic A/B in Phase 3**; LLM retained only if uplift ≥ 3pp.
17. **Polymarket gasless relayer** for all order submission.
18. **Obsidian: laptop-only vault**; bot writes to `state/` in git, laptop pulls.

---

## C. Open Decision-Points (resolve as encountered)

| # | Decision | Resolved in |
|---|---|---|
| OD-1 | Polygon RPC: Alchemy / Chainstack / QuickNode | Phase 2.0 (default: Alchemy free tier) |
| OD-2 | Backup target for trades.db: B2 / R2 / S3 | Phase 6.5 (default: Backblaze B2) |
| OD-3 | Anthropic top-up: $50 → $150 before Phase 4; → $300 before Phase 6 | Before each phase boundary |
| OD-4 | Polymarket gasless relayer: builder credentials vs proxy-only | Phase 1.5 (read `agent-skills/gasless.md`) |
| OD-5 | LLM ensemble retained Y/N after Phase 3 A/B | Phase 3 gate |
| OD-6 | Funder hardware wallet purchase | $2k bankroll trigger |

---

## D. Anti-Vibe-Coding Operating Rules

These are non-negotiable. The user accepted a single carve-out: rules 1, 2, 3, and 6 do not apply to *pure* formatting / docstring / dependency-bump fixes (no logic change). Everything that touches trading logic, signing, money flow, or async control flow obeys all rules.

1. **Design doc before code.** Every file in `src/` is paired with `design/<filename>.md` committed in the same PR or earlier. If you can't write the design, you can't write the file.
2. **Bug → failing test → fix → green.** Never patch a symptom. The test stays in the suite afterward as a regression guard.
3. **3-fix rule.** If three consecutive iterations don't resolve a bug, stop — write `runbooks/incidents/<date>-<slug>.md` naming the root-cause hypothesis. Get user sign-off before touching code again.
4. **No phase advances** until its gate command exits 0 and output is captured to `runbooks/gate-evidence/phase-N.txt`. Commit the evidence file.
5. **Every file** ships with a one-paragraph header comment stating purpose. Absent header = absent file (CI rejects).
6. **Type hints on every Python function.** `mypy --strict src/` green from Phase 2 onward; `mypy --strict --ignore-missing-imports tests/` green from Phase 3.
7. **External calls behind interfaces.** Production code never imports from `src/_paper/`; tests never import from `src/_live/`. CI enforces with import-linter.
8. **No `TODO`, `FIXME`, `// hack`** in committed code. CI greps and rejects. File a GitHub issue or fix it now.
9. **Pinned deps + lockfile.** `uv.lock` committed. No floating versions. Dependabot disabled until Phase 8 (we don't want auto-PRs during live).
10. **Stochastic inputs injected, not imported.** `Clock`, `LLMClient`, `RpcClient`, `RandomSource` all behind protocols; tests inject deterministic implementations.

---

## E. Cost & Wall-Clock Summary

Adjust expectations based on actual progress. Estimates assume focused work, not calendar time.

| Phase | Wall-clock (focused) | USD cost (cumulative) | Critical risk if rushed |
|---|---|---|---|
| 0 — Foundations | 1 day | $0 | Tooling drift later |
| 1 — Wallet & Auth | ½ day | $5 (gas + dust) | Stranded funds |
| 2 — Data Plane | 2-3 days + 7d capture | $5-10 (RPC) | Bad data → bad backtest |
| 3 — Backtest + LLM A/B | 3-4 days | $15-50 (Anthropic, with cache discipline) | Optimistic backtests = live losses |
| 4 — Paper Trading | 14 calendar days | $50-195 (Anthropic 24/7 + RPC) — top up to $150 before starting | Simulator drift |
| 5 — VPS Provisioning | ½ day | $5/mo VPS recurring | Latency surprises |
| 6 — Live | 14 calendar days | $1,000 working capital + $50-195 (LLM live 24/7) — top up Anthropic to $300 before starting | Real money |
| 7 — Scale | ongoing | bankroll-driven | Premature scaling |
| 8 — Hardening | ongoing | TBD | Migration / regression |
| **Total to first $1 live** | ~30 calendar days | ~$170 setup + $1,000 capital | — |

---

# PHASE 0 — Foundations

**Owner intent.** Stand up a clean development environment, confirm every account-level prerequisite is in hand, and seed the project skeleton. No money moves. No keys generated. No production data touched.

## Pre-flight checklist
- [ ] UAE jurisdiction confirmed (this is locked decision #1; treat as done).
- [ ] GitHub account active with SSH key configured: `ssh -T git@github.com` returns success.
- [ ] Anthropic API key (≥$50 credit balance) accessible.
- [ ] Telegram account active on phone.
- [ ] Obsidian installed locally.
- [ ] Local Python ≥ 3.11: `python3 --version`.
- [ ] `uv` installed: `uv --version`. If absent: `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- [ ] Node ≥ 20 installed (`node --version`) — needed for some MCP servers.
- [ ] Claude Code CLI installed and authenticated.

## Tasks

### 0.1 — Initialize project skeleton
**Why:** Standard Python layout. `uv` as single source of dep truth. Lockfile committed from day 1.

```bash
cd /Users/hamad/Desktop/PolyMarket-5m
uv init --python 3.11 --package
uv add --dev mypy ruff pytest pytest-cov pytest-asyncio import-linter pre-commit
mkdir -p src/polymarket_bot tests design runbooks/incidents runbooks/gate-evidence runbooks/postmortems state/postmortems state/runbooks references config
touch src/polymarket_bot/__init__.py tests/__init__.py
```

**Expected output:** `pyproject.toml`, `uv.lock`, `src/polymarket_bot/`, `tests/`, etc.
**Verification:** `uv run python -c "import polymarket_bot"` exits 0.

### 0.2 — Configure type checking, linting, import boundaries
**Why:** Enforce rules 6 and 7 from CI day 1.

Files to create:

**`mypy.ini`**
```ini
[mypy]
strict = True
warn_unused_ignores = True
warn_redundant_casts = True
disallow_untyped_decorators = True
plugins = []

[mypy-tests.*]
strict = True
ignore_missing_imports = True
```

**`ruff.toml`**
```toml
target-version = "py311"
line-length = 100
[lint]
select = ["E", "F", "W", "I", "B", "UP", "ASYNC", "RUF", "S", "PT"]
ignore = ["E501"]  # line-length is a soft limit; ruff format handles it
[lint.per-file-ignores]
"tests/*" = ["S101"]  # asserts in tests are fine
```

**`.importlinter`** — enforces "no production import of paper-mocks"
```ini
[importlinter]
root_package = polymarket_bot

[importlinter:contract:layered]
name = production never imports paper
type = forbidden
source_modules = polymarket_bot._live
forbidden_modules = polymarket_bot._paper

[importlinter:contract:layered2]
name = paper never imports live infra
type = forbidden
source_modules = polymarket_bot._paper
forbidden_modules = polymarket_bot._live
```

**`Makefile`**
```make
.PHONY: verify lint type test gate-0 gate-1 gate-2 gate-3 gate-4 gate-5 gate-6

verify: lint type test
lint:
	uv run ruff check src/ tests/
	uv run ruff format --check src/ tests/
type:
	uv run mypy --strict src/
test:
	uv run pytest -q

gate-0:
	@bash runbooks/gates/phase-0.sh
gate-1:
	@bash runbooks/gates/phase-1.sh
# ... and so on per phase
```

**Verification:** `make lint` exits 0 (empty src is fine).

### 0.3 — Initialize git, create GitHub private repo, configure CI
**Why:** Version control from commit zero. CI enforces our rules so they can't decay.

```bash
git init
git add -A
git commit -m "chore: initial scaffold (uv, mypy, ruff, import-linter, Makefile)"
gh repo create polymarket-5m-bot --private --source=. --remote=origin --push
```

**`.github/workflows/ci.yml`**
```yaml
name: ci
on: [push, pull_request]
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.11
      - run: uv sync --frozen
      - run: make verify
      - name: forbid TODO/FIXME/hack in src
        run: |
          ! grep -rEn 'TODO|FIXME|//\s*hack' src/ tests/ design/ || (echo "found TODO/FIXME/hack" && exit 1)
      - name: forbid files without header docstring
        run: |
          uv run python runbooks/scripts/check_headers.py src/
      - run: uv run lint-imports
```

**`runbooks/scripts/check_headers.py`** (small script, design-doc-trivial, exempt from rule 1):
- Walks `src/` and asserts every `.py` file's first non-blank, non-shebang line is a triple-quoted module docstring of ≥ 80 chars.

**Verification:** `git push` triggers CI; CI run completes green on the empty scaffold.

### 0.4 — Create Telegram bot via BotFather
**Why:** Replaces the original Discord plan. Critical alerts go here. Bot also accepts inbound `/halt`.

1. On phone Telegram, message **@BotFather**.
2. `/newbot` → choose a name (e.g. `polymarket-5m-ops`) → choose a username (must end in `bot`).
3. BotFather returns a **bot token**. Copy.
4. Find your own chat ID:
   - Message your bot once (any text).
   - On laptop: `curl "https://api.telegram.org/bot<TOKEN>/getUpdates"` → look for `chat.id` in the JSON.
5. Test send: `curl -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" -d "chat_id=<ID>&text=hello+from+phase+0"` — confirm message arrives on phone.
6. Save token + chat_id in `config/telegram.env.example` as placeholders. Real values go in `.envrc` (Phase 0.7).

**Verification:** test message received on phone. Document the bot username in `runbooks/contacts.md`.

### 0.5 — Drop Polymarket/agent-skills into Claude Code skills
**Why:** Official skills give Claude authenticated knowledge of every Polymarket primitive (auth, orders, WS, token ops, bridging, **gasless**, neg-risk).

```bash
mkdir -p ~/.claude/skills
git -C ~/.claude/skills clone https://github.com/Polymarket/agent-skills.git
ls ~/.claude/skills/agent-skills/
```

Verify the skills directory contains at minimum:
- `authentication.md`
- `trading.md`
- `websocket.md`
- `gasless.md` ← important for OD-4
- `markets.md`

**Verification:** in a Claude Code session, ask "what's the L2 auth flow for Polymarket?" and confirm the answer cites the skill.

### 0.6 — Clone reference repos (read-only)
**Why:** Mining-only references; we never depend on these as runtime dependencies.

```bash
mkdir -p references
cd references
git clone --depth 1 https://github.com/Polymarket/py-clob-client.git
git clone --depth 1 https://github.com/Polymarket/agents.git
git clone --depth 1 https://github.com/Polymarket/poly-market-maker.git
git clone --depth 1 https://github.com/evan-kolberg/prediction-market-backtesting.git
git clone --depth 1 https://github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot.git
git clone --depth 1 https://github.com/ThinkEnigmatic/polymarket-bot-arena.git
# Archetapp gist (best timing/window logic):
git clone --depth 1 https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69 archetapp-5m-bot
cd ..
```

Add `references/` to `.gitignore` — these are not part of our repo's history.

**Verification:** `ls references/` shows all 7 directories. None of them are tracked in git: `git status` shows clean.

### 0.7 — Wire Obsidian + secrets baseline
**Why:** Obsidian indexes a local directory. Bot will write to `state/` in this repo from Phase 5; for now, just wire the index.

1. Open Obsidian → "Open folder as vault" → select `/Users/hamad/Desktop/PolyMarket-5m/state/`.
2. Install the Templater + Daily-notes core plugins for runbook discipline.
3. Create `state/runbooks/README.md` with one paragraph explaining the directory's purpose.
4. (Optional this phase, required by Phase 5) Install the [obsidian-claude-code-mcp](https://github.com/iansinnott/obsidian-claude-code-mcp) plugin so Claude Code can read/write the vault.

Set up secrets:

**`.envrc.example`** (committed, no real values)
```sh
# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Telegram
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."

# Polymarket (filled in Phase 1)
export POLY_PRIVATE_KEY=""
export POLY_API_KEY=""
export POLY_API_SECRET=""
export POLY_API_PASSPHRASE=""
export POLY_FUNDER_ADDRESS=""
export POLY_SIGNATURE_TYPE="1"

# Polygon RPC (filled in Phase 2)
export POLYGON_RPC_URL=""
```

**`.envrc`** (gitignored): copy `.envrc.example` and fill the values you have today (Anthropic + Telegram).

**`.gitignore`** must include:
```
.envrc
.envrc.local
*.age
references/
state/
runbooks/gate-evidence/
ticks/
trades.db
*.db-shm
*.db-wal
```

Confirm with `git check-ignore -v .envrc` returns a hit.

Install `direnv` (`brew install direnv`) and add `eval "$(direnv hook zsh)"` to `~/.zshrc`. Run `direnv allow` in the project root.

**Verification:** `echo $ANTHROPIC_API_KEY` (in the project shell) returns your key; in any other directory, returns empty.

### 0.8 — Run /init to seed CLAUDE.md
**Why:** Project-level CLAUDE.md is the durable preferences file every Claude Code session reads automatically.

In Claude Code, run `/init`. The generated file should include (add manually if missing):
- Pointer to `RUNBOOK.md` as execution source-of-truth.
- The 10 anti-vibe-coding rules (copy from this runbook's section D).
- The locked-decisions table (copy from section B) or a pointer to `memory/project_decisions.md`.
- Current phase (manually update on each gate pass).

Commit the file.

### 0.9 — Set up pre-commit hooks
**Why:** Catch rule-breakers locally before CI does.

**`.pre-commit-config.yaml`**
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: local
    hooks:
      - id: forbid-todos
        name: forbid TODO/FIXME/hack
        entry: bash -c '! grep -rEn "TODO|FIXME|//\s*hack" src/ tests/ design/ 2>/dev/null'
        language: system
        pass_filenames: false
      - id: file-headers
        name: enforce module docstrings
        entry: uv run python runbooks/scripts/check_headers.py src/
        language: system
        pass_filenames: false
```

```bash
uv run pre-commit install
```

**Verification:** `git commit --allow-empty -m "test"` runs hooks (they should all pass on empty src).

## Files this phase creates

| Path | Purpose |
|---|---|
| `pyproject.toml` | Package metadata, dep manifest |
| `uv.lock` | Pinned dep graph |
| `mypy.ini` | Strict typing config |
| `ruff.toml` | Linting + formatting config |
| `.importlinter` | Production/paper boundary enforcement |
| `Makefile` | Single entry point for verify/lint/type/test/gate-N |
| `.github/workflows/ci.yml` | CI pipeline |
| `.pre-commit-config.yaml` | Local-side checks |
| `.envrc.example` / `.envrc` | Secret loading via direnv |
| `.gitignore` | Excludes secrets, ticks, db, references, state |
| `CLAUDE.md` | Project preferences for Claude Code |
| `runbooks/scripts/check_headers.py` | Module-docstring enforcer |
| `runbooks/contacts.md` | Telegram bot username, etc. |
| `state/runbooks/README.md` | Vault entry point |
| `references/*` (gitignored) | Read-only reference repos |

## Gate command — must exit 0

```bash
bash runbooks/gates/phase-0.sh
```

**`runbooks/gates/phase-0.sh`**
```bash
#!/usr/bin/env bash
set -euo pipefail
echo "[gate-0] checking python version"
uv run python -c "import sys; assert sys.version_info >= (3, 11), sys.version"
echo "[gate-0] checking mypy + ruff (empty src is fine)"
make verify
echo "[gate-0] checking GitHub remote"
gh repo view --json url -q .url
echo "[gate-0] checking agent-skills present"
test -f ~/.claude/skills/agent-skills/authentication.md
test -f ~/.claude/skills/agent-skills/gasless.md
echo "[gate-0] checking Telegram bot token loaded"
test -n "${TELEGRAM_BOT_TOKEN:-}" || (echo "TELEGRAM_BOT_TOKEN missing" && exit 1)
echo "[gate-0] checking Telegram bot chat_id loaded"
test -n "${TELEGRAM_CHAT_ID:-}" || (echo "TELEGRAM_CHAT_ID missing" && exit 1)
echo "[gate-0] sending Telegram smoke message"
curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
  --data-urlencode "text=phase-0 gate smoke test $(date -u +%FT%TZ)" >/dev/null
echo "[gate-0] checking Anthropic key loaded"
test -n "${ANTHROPIC_API_KEY:-}" || (echo "ANTHROPIC_API_KEY missing" && exit 1)
echo "[gate-0] checking references cloned"
for r in py-clob-client agents poly-market-maker prediction-market-backtesting Polymarket-BTC-15-Minute-Trading-Bot polymarket-bot-arena archetapp-5m-bot; do
  test -d "references/$r" || (echo "missing references/$r" && exit 1)
done
echo "[gate-0] OK"
```

Capture output: `bash runbooks/gates/phase-0.sh | tee runbooks/gate-evidence/phase-0.txt && git add runbooks/gate-evidence/phase-0.txt && git commit -m "evidence: phase 0 gate green"`.

## Rollback procedure

- Did anything in CI fail? Read the actual error, do not paper over.
- GitHub repo creation failed mid-step? `gh repo delete polymarket-5m-bot --yes` and retry from 0.3.
- Telegram smoke test failing? Most common cause: the `chat_id` is wrong because the user never messaged the bot first. Fix by messaging bot, re-fetching `getUpdates`.
- direnv not loading? `direnv allow` then re-source the shell.
- Worst case (deeply broken): `cd ~/Desktop && rm -rf PolyMarket-5m && mkdir PolyMarket-5m` and start Phase 0 over. Nothing of value lost; no money was on the table.

## Wall-clock estimate

4-6 hours focused. The Telegram + GitHub round-trips take longer than they look.

## USD cost

$0.

## Memory checkpoint at completion

Write `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_0.md`:

```markdown
---
name: checkpoint_phase_0
description: Phase 0 (Foundations) gate passed YYYY-MM-DD. Ready to begin Phase 1.
type: project
---

Phase 0 complete. Gate evidence: runbooks/gate-evidence/phase-0.txt.
Next phase: 1 — Wallet & Auth.
Open decisions resolved this phase: [list].
Open decisions still open: OD-1 through OD-6 except those resolved.
```

Update `MEMORY.md` to point at this checkpoint.

---

# PHASE 1 — Wallet & Auth

> **Phase 1 is split into 1A (no money) and 1B (funded).** See locked
> decision #20 and [`design/gasless.md`](design/gasless.md) §6. Phase 1A
> covers tasks 1.0, 1.1, 1.2, 1.3, 1.6 and gates via
> `runbooks/gates/phase-1a.sh` (tag `phase-1a-pass`); zero on-chain
> footprint. Phase 1B covers tasks 1.4 (fund + sweep) and 1.5 ($5 test
> order) and gates via `runbooks/gates/phase-1.sh` (tag `phase-1-pass`);
> 1B fires immediately before Phase 6 go-live, after Phase 4 paper testing
> closes. The pre-flight checklist below applies in full only at 1B time;
> 1A needs only the Phase 0 tag and the agent-skills reads.

**Owner intent.** Generate the Funder + Signer wallet pair, derive Polymarket L2 credentials, **prove signing works before funding any wallet**, then fund minimally and execute one gasless test order. By the end of this phase you have demonstrated the full auth + order flow with $5 at risk.

## Pre-flight checklist
- [ ] Phase 0 gate green (evidence committed).
- [ ] Have $60 USDC available to deposit into Polymarket (you'll send $50; $10 buffer for gas / mistakes).
- [ ] Have ~$5 worth of MATIC to bridge to Funder for gas.
- [ ] Read `references/py-clob-client/README.md` and `~/.claude/skills/agent-skills/authentication.md`.
- [ ] Read `~/.claude/skills/agent-skills/gasless.md` — confirm gasless flow is well-defined; if not, escalate as a blocker before funding.

## Tasks

### 1.0 — Resolve OD-4 (gasless relayer specifics)
**Why:** We do not fund anything until we know how the gasless flow signs orders.

Review `agent-skills/gasless.md` and `references/py-clob-client` for `RelayerClient` or equivalent. Document in `design/gasless.md`:
- Which transactions are gasless (orders? approvals? both?)
- Which still require MATIC on Signer (typically: USDC approval to the exchange contract, redeems).
- Whether builder credentials are needed for our use case (probably not).

If the gasless path turns out to require a builder relationship, demote to public submission with a Phase 8 ticket to revisit. Either way, document the decision before continuing.

### 1.1 — Generate Funder and Signer wallets (offline)
**Why:** Two wallets, full segregation. Funder is the long-term holder; Signer is the daily operator.

Use a clean offline laptop session. Recommended: `eth-account` Python library with strong entropy.

```python
# scripts/genwallets.py — design/genwallets.md required first
"""Offline wallet generator. Run once. Never commit the private keys.

Usage: uv run python scripts/genwallets.py
Outputs two wallets to stdout. Operator copies them into separate
age-encrypted files on the laptop and (for Funder) optionally a
hardware wallet. Wallets must NEVER be reused across this project.
"""
from eth_account import Account
import secrets

def gen():
    return Account.create(secrets.token_bytes(32))

funder = gen()
signer = gen()
print(f"FUNDER  address: {funder.address}")
print(f"FUNDER  privkey: {funder.key.hex()}")
print(f"SIGNER  address: {signer.address}")
print(f"SIGNER  privkey: {signer.key.hex()}")
```

Encrypt and store:
```bash
brew install age
mkdir -p ~/secrets/polymarket-5m
uv run python scripts/genwallets.py > /tmp/wallets.txt
age -p -o ~/secrets/polymarket-5m/funder.age <(grep FUNDER /tmp/wallets.txt)
age -p -o ~/secrets/polymarket-5m/signer.age <(grep SIGNER /tmp/wallets.txt)
shred -u /tmp/wallets.txt
```

The Signer privkey also goes into the project `.envrc` as `POLY_PRIVATE_KEY` (this is intentional — Signer is the operator wallet).

**Verification:**
```bash
test -f ~/secrets/polymarket-5m/funder.age
test -f ~/secrets/polymarket-5m/signer.age
test ! -f /tmp/wallets.txt
```

### 1.2 — Derive Polymarket L2 credentials (no funding required)
**Why:** L2 creds are deterministic from the Signer private key + a signed nonce; no balance needed.

Pattern from `py-clob-client`:

```python
# scripts/derive_creds.py — design/derive_creds.md required first
"""Derive Polymarket L2 API credentials from the Signer private key.

L1 EIP-712 signature creates apiKey/secret/passphrase used for L2 HMAC auth.
Reads POLY_PRIVATE_KEY from env. Writes derived creds to stdout for the
operator to paste into .envrc. Never commits anything.
"""
import os
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

key = os.environ["POLY_PRIVATE_KEY"]
host = "https://clob.polymarket.com"
client = ClobClient(host, key=key, chain_id=POLYGON)
creds = client.create_or_derive_api_creds()
print(f"POLY_API_KEY={creds.api_key}")
print(f"POLY_API_SECRET={creds.api_secret}")
print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")
```

Run, copy output into `.envrc`, `direnv allow`.

**Verification:** `echo $POLY_API_KEY` returns a UUID-format string.

### 1.3 — Test signing without funding
**Why:** Locked decision #13 — never fund before signing is verified.

```python
# scripts/test_auth.py
"""Read-only signed call against Polymarket /info. Confirms L2 auth works
without ever needing on-chain funds. Failure here means we have a creds
problem, not a funding problem; do not move on until this exits 0.
"""
import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

client = ClobClient(
    "https://clob.polymarket.com",
    key=os.environ["POLY_PRIVATE_KEY"],
    chain_id=137,
    creds=ApiCreds(
        api_key=os.environ["POLY_API_KEY"],
        api_secret=os.environ["POLY_API_SECRET"],
        api_passphrase=os.environ["POLY_API_PASSPHRASE"],
    ),
)
print(client.get_address())  # this is L2-authenticated
```

```bash
uv run python scripts/test_auth.py
# expected: prints the Signer address that matches what you stored
```

If this fails, **do not fund anything**. Debug auth first. Most common failure: copy-paste error in `.envrc` (newline in the secret).

### 1.4 — Fund the Funder, then sweep dust to Signer
**Why:** Funder holds working capital; Signer never holds more than 2 days' worth.

1. From your existing exchange (UAE-permitted CEX): withdraw $50 USDC + ~$3 MATIC on Polygon network to the **Funder** address.
2. Confirm balance on PolygonScan: `https://polygonscan.com/address/<FUNDER>`.
3. From the Funder, send $20 USDC + 0.5 MATIC to the **Signer** address (use a wallet UI like Rabby or Frame; never paste the Funder privkey on a hot machine if you can avoid it).
4. Approve Polymarket exchange contract to spend Signer's USDC: this is a one-time on-chain tx, **costs MATIC**, **not** gasless. The `py-clob-client` README documents the exact approval call.

**Verification:**
```bash
# Signer USDC balance ≥ 20
# Signer USDC allowance to Polymarket Exchange ≥ 1e18 (effectively unlimited)
```

(In Phase 2 we'll script these checks; for now, eyeball on PolygonScan.)

### 1.5 — Place + cancel a $5 limit via gasless relayer
**Why:** Prove the full live order path with the smallest realistic stake.

Pick a low-volume market unrelated to BTC (e.g. an obscure long-dated political market) so your test order doesn't accidentally get filled at a bad price. Place a limit order well below the bid:

```python
# scripts/test_gasless_order.py
"""Place + cancel a $5 limit on a non-time-critical market via the
Polymarket gasless relayer. Confirms end-to-end signing, submission,
order acknowledgement, and cancellation flow with minimal capital.
"""
# ... uses py-clob-client + relayer; specifics confirmed in 1.0 design doc
```

Place → confirm order ID returned → query order status (should be `OPEN`) → cancel → confirm `CANCELED`.

**Verification:**
- Order placed: API returns `order_id`.
- Order open: `client.get_order(order_id).status == "OPEN"`.
- Cancel succeeds: `client.cancel(order_id)` returns success.
- Final status: `CANCELED`.
- Capture all four states to `runbooks/gate-evidence/phase-1.txt`.

### 1.6 — Document operational hygiene
Create `runbooks/wallet-ops.md`:
- Funder address, Signer address.
- "Funder key never on the running bot machine."
- Sweep policy: "When Signer balance > $50, sweep excess to Funder. When Funder balance > $200, sweep to cold storage (Phase 7 task)."
- Recovery: "If Signer is compromised, immediately revoke USDC allowance from the compromised key, regenerate Signer wallet, derive new creds. Funder is unaffected because its key never touched the same machine."

## Files this phase creates

| Path | Purpose |
|---|---|
| `design/gasless.md` | OD-4 resolution: how the gasless flow works for our use case |
| `design/genwallets.md` | Why we generate two wallets and offline |
| `design/derive_creds.md` | L2 creds derivation flow |
| `scripts/genwallets.py` | One-shot wallet generator |
| `scripts/derive_creds.py` | One-shot credential deriver |
| `scripts/test_auth.py` | Signed read-only test |
| `scripts/test_gasless_order.py` | $5 place + cancel test |
| `runbooks/wallet-ops.md` | Hot-and-cold wallet hygiene |
| `runbooks/gate-evidence/phase-1.txt` | Captured proof |

`.envrc` updated with real Polymarket creds (gitignored).
`~/secrets/polymarket-5m/funder.age` and `signer.age` exist offline.

## Gate command — must exit 0

```bash
bash runbooks/gates/phase-1.sh
```

Script asserts:
1. `scripts/test_auth.py` exits 0 returning the expected Signer address.
2. PolygonScan API confirms Signer USDC balance ≥ $20.
3. Polymarket exchange-contract allowance from Signer ≥ unlimited.
4. `runbooks/gate-evidence/phase-1.txt` exists and contains the four order-state transitions for the test order.
5. `~/secrets/polymarket-5m/funder.age` exists and is age-encrypted (verifiable header).
6. **Funder private key is NOT in `.envrc`** (grep negative).

## Rollback procedure

- **Auth test failed** → debug `.envrc` (most common: stray whitespace), do not fund.
- **Funded the wrong address** → it's only $20-50; treat as tuition, but check whether you accidentally sent to a non-Polygon chain. If it's the wrong chain, recover via the bridge or write off.
- **Order didn't cancel** → wait 5 min and retry; if still stuck, it's likely a network/relayer issue, contact Polymarket support; in the meantime do not advance.
- **Approval tx failed** → check Signer MATIC balance; common cause is dust gas. Top up by 0.5 MATIC and retry.

## Wall-clock estimate

4 hours. Most time is on PolygonScan double-checking, not on code.

## USD cost

$5 in MATIC + $50 USDC moved into the system (not consumed). Real spend ≈ $1 in gas.

## Memory checkpoint

Write `checkpoint_phase_1.md` recording:
- Funder + Signer addresses (public, safe to record).
- That OD-4 was resolved with the chosen gasless model.
- Confirmation that signing works before funding was the actual order followed.

---

# PHASE 2 — Read-only Data Plane

**Owner intent.** Stand up three reliable, well-archived data feeds (spot, oracle, market). After 7 days of clean capture, we know the oracle behaves the way the thesis assumes; if it doesn't, we re-evaluate before any backtest.

## Pre-flight checklist
- [ ] Phase 1 gate green.
- [ ] Decide OD-1 (Polygon RPC). Default: Alchemy free tier (300M compute units / month, fine for our event subscription rate). Sign up, create a Polygon mainnet app, copy the WSS URL into `.envrc` as `POLYGON_RPC_URL`.
- [ ] Read Chainlink BTC/USD aggregator address on Polygon: `0xc907E116054Ad103354f2D350FD2514433D57F6f` (verify via [data.chain.link](https://data.chain.link/feeds/polygon/mainnet/btc-usd) before coding against it).

## Tasks

### 2.0 — Design the data plane
**Why:** Three feeds, three failure modes, one shared archive format. Get the design right before the code.

Write `design/data_plane.md`:
- Each feed runs as a separate async task.
- Each feed produces records into a single Parquet writer per UTC-day with schema: `(ts_utc_ns, source, kind, payload_json)`.
- Reconnect policy: exponential backoff to 60s; halt + page Telegram if disconnected > 5 min.
- Backpressure: if writer queue > 10k items, drop and log (we prefer recent over complete).
- Storage: `ticks/<utc-date>/<source>.parquet`. Rotate at UTC midnight.
- Internal interface: `Feed` protocol — `async def stream() -> AsyncIterator[Record]`.

### 2.1 — Implement `spot_feed.py`
Two upstreams (Binance + Coinbase) merged via async fan-in. Each is its own concrete class behind the `Feed` protocol.

Files:
- `src/polymarket_bot/_live/feeds/spot_binance.py`
- `src/polymarket_bot/_live/feeds/spot_coinbase.py`
- `src/polymarket_bot/_live/feeds/spot_aggregator.py`
- `tests/feeds/test_spot_*.py` — using injected fake WS clients.

Header docstring on each file (required).

**Verification:** `pytest tests/feeds -q` green; running the aggregator for 60 seconds prints both source ticks at expected rates (Binance ≈ 5/s, Coinbase ≈ 2-10/s).

### 2.2 — Implement `oracle_watcher.py`
Subscribes to Chainlink `AnswerUpdated(int256 current, uint256 roundId, uint256 updatedAt)` events on the BTC/USD aggregator via Polygon WSS.

Files:
- `src/polymarket_bot/_live/feeds/oracle.py`
- `tests/feeds/test_oracle.py` — fixture replays a captured event log.

**Verification:** running for 5 min logs at least 4 oracle updates with timestamps spaced ~60s.

### 2.3 — Implement `market_feed.py`
Subscribes to active 5m BTC market via Polymarket WS at `wss://ws-subscriptions-clob.polymarket.com/ws/market`. Computes the active market slug deterministically:

```python
def active_window_ts(now_utc_s: int) -> int:
    return now_utc_s - (now_utc_s % 300)

def active_slug(window_ts: int) -> str:
    return f"btc-updown-5m-{window_ts}"
```

Header docstring required. Files:
- `src/polymarket_bot/_live/feeds/polymarket.py`
- `tests/feeds/test_polymarket.py`

**Verification:** captures orderbook snapshots and trade events for the current and next window.

### 2.4 — Implement the resolver helper
**Why:** "What does this market resolve as if it ended now?" is a constant ground-truth check.

```python
# src/polymarket_bot/resolver.py
def hypothetical_resolution(window_open_oracle: float, current_oracle: float) -> Literal["UP","DOWN"]:
    return "UP" if current_oracle >= window_open_oracle else "DOWN"
```

But the *real* resolver is "current oracle as of T+300, not now." Make sure both are in code, named distinctly: `hypothetical_now()` vs `actual_resolution(window_ts)`.

### 2.5 — Capture for 7 days
Run all three feeds under `systemctl --user` or a tmux session for 7 calendar days. Daily check: file exists for yesterday's date, size grew vs the day before.

### 2.6 — Verify oracle behavior (the thesis-validation gate)
**Why:** This is the 60s-heartbeat verification we promised in MASTERPLAN.md. The thesis depends on it.

After 7 days of capture, run `scripts/analyze_oracle.py`:

```python
# scripts/analyze_oracle.py — design/oracle_analysis.md required first
"""Analyze 7 days of Chainlink BTC/USD update events. Reports:
  - count of updates
  - median / p10 / p90 inter-update gap
  - count of sub-60s updates (these would indicate a deviation trigger)
  - count of intervals > 65s (indicates skipped heartbeats)
Failure of any single criterion forces a thesis re-evaluation
before Phase 3 begins.
"""
```

Pass criteria:
- Median inter-update gap ∈ [55s, 65s].
- Zero sub-30s updates (these would be deviation-triggered and would shrink the lag window dangerously).
- Sub-60s updates < 5% of total (small jitter is fine).
- Zero gaps > 180s (a Chainlink outage we'd need to design for).

If any criterion fails, **stop**. Open a thesis-revaluation document in `runbooks/incidents/oracle-behavior-N.md` and escalate to user. Do not proceed.

## Files this phase creates

| Path | Purpose |
|---|---|
| `design/data_plane.md` | Three-feed architecture |
| `design/oracle_analysis.md` | What we're verifying and why |
| `src/polymarket_bot/_live/feeds/{spot_binance,spot_coinbase,spot_aggregator,oracle,polymarket}.py` | Live feeds |
| `src/polymarket_bot/_live/storage.py` | Parquet writer |
| `src/polymarket_bot/resolver.py` | Hypothetical + actual resolution |
| `tests/feeds/*` | Mocked-WS unit tests |
| `scripts/analyze_oracle.py` | 7-day verifier |
| `ticks/<date>/*.parquet` (gitignored) | Raw archive |
| `runbooks/gate-evidence/phase-2.txt` | Captured proof |

## Gate command — must exit 0

```bash
bash runbooks/gates/phase-2.sh
```

Asserts:
1. `make verify` green (mypy strict, ruff, tests).
2. `lint-imports` green.
3. `ls ticks/` shows ≥ 7 dated directories, each with `binance.parquet`, `coinbase.parquet`, `oracle.parquet`, `polymarket.parquet`.
4. `uv run python scripts/analyze_oracle.py --days 7` reports all four criteria pass.
5. Cross-feed sanity: for any randomly chosen window, oracle update timestamps are within ±2s of expected 60s cadence and align (UTC) with spot tick coverage.

## Rollback

- Feed dies overnight: `journalctl --user -u <feed-service>` for cause; usually it's a WS provider hiccup. Re-launch and *extend the capture window* — do not advance with gaps.
- Oracle criteria fail: write up in `runbooks/incidents/`, escalate. The thesis may need a different aggregator (e.g. data streams instead of price feeds) or a fundamentally different strategy. **Do not handwave this.**
- Schema mismatch in Parquet over time: pin to a single schema in `design/data_plane.md`, write a migrator if needed.

## Wall-clock

3-4 days dev, then 7 days of background capture (you can move on to Phase 3 design/research during the capture, just not Phase 3 code that depends on data).

## USD cost

$0-5 (Alchemy free tier covers our usage; Binance/Coinbase WS is free).

## Memory checkpoint

Write `checkpoint_phase_2.md` including: oracle median heartbeat measured, sub-60s update count, any anomalies. **This is the data point that justifies or kills the thesis.**

---

# PHASE 3 — Backtest Harness + LLM A/B Test

**Owner intent.** Build a deterministic baseline strategy, validate it on captured data, then test whether adding the LLM ensemble improves it by ≥3pp. If LLMs don't add value, ship deterministic and revisit ensemble later — don't carry $/day cost without alpha.

## Pre-flight checklist
- [ ] Phase 2 gate green.
- [ ] **Anthropic credits ≥ $50** — confirmed sufficient for Phase 3 *if* (a) cache hit-rate ≥ 80%, (b) max 4 backtest passes, (c) early-abort on cumulative spend > $35 per pass. The bigger top-up ($150) is required before Phase 4, not now.
- [ ] Read NautilusTrader Polymarket integration docs.

## Tasks

### 3.0 — Design the backtest harness
`design/backtest.md`:
- Replay engine consumes Parquet archives in event order.
- Strategy interface: `async def on_event(event) -> Decision | None` where `Decision = (side, size_usd, price_limit, ttl_s)`.
- Fill simulator: matches against captured top-5 orderbook with a self-impact model (a $5 trade against $5K depth moves price ~0.1¢; calibrate from real Phase 1 fill data once Phase 6 has any).
- Walk-forward: rolling 7-day train, 1-day test, slide forward 1 day.
- Cost-tracker: counts every API call, multiplies by per-token price, asserts cumulative spend ≤ session budget.

### 3.1 — Implement the deterministic baseline
**Why:** Ship-able as a complete strategy on its own — we never depend on LLMs to be alpha-positive.

```python
# src/polymarket_bot/strategies/deterministic.py
"""Window-delta + oracle-gap composite signal. The Tier-3 fallback path,
also tested as a standalone strategy in Phase 3 A/B. No LLM calls; pure
math from spot, oracle, and window state.

composite = w_wd * (spot_now - window_open) / window_open
          + w_og * (spot_now - oracle_last) / oracle_last
fire if abs(composite) >= 0.6 AND ttl_s in [10, 30]
"""
```

Backtest pass — capture per-window: predicted side, fill price, fill size, P&L. Walk-forward over 21 days (after losing 7d for warmup).

**Result target:** ≥ 53% win-rate after fees on ≥ 2,500 trades. If below, iterate weights *before* introducing LLMs (don't paper over a weak baseline with model magic).

### 3.2 — Implement the 3-agent ensemble
Files:
- `src/polymarket_bot/agents/orderbook.py` — agent 1: orderbook microstructure (Binance + Coinbase L2 imbalance), Haiku 4.5.
- `src/polymarket_bot/agents/oracle_gap.py` — agent 2: spot-vs-oracle delta + recent oracle cadence, Haiku 4.5.
- `src/polymarket_bot/agents/momentum.py` — agent 3: last 60s tick trend + acceleration, Haiku 4.5.
- `src/polymarket_bot/agents/meta.py` — meta-decider: weighs the three votes + the deterministic composite, Sonnet 4.6.
- `src/polymarket_bot/agents/protocol.py` — `Agent` protocol, `AgentVote` JSON schema, validator.
- `src/polymarket_bot/agents/budget.py` — per-day spend cap, hard kill at 1.2x.
- `src/polymarket_bot/agents/cache.py` — explicit Anthropic prompt cache layout: static system block (cached) + per-window dynamic block (uncached).

Each agent's prompt is committed in `prompts/<agent>.md` (versioned, inspectable in git). Schema enforced via `pydantic` on every response; failure → agent abstains, meta-decider proceeds without it; <2 valid agents → Tier-3.

### 3.3 — Run the A/B
Two backtest passes over the same 21-day walk-forward window:
1. Deterministic only.
2. Deterministic + LLM ensemble (meta uses LLM + composite).

Same fill simulator, same fees, same hyperparameters where they overlap.

Report: trade-by-trade comparison, win-rate delta, latency overhead, $/decision.

### 3.4 — Decide
**LLM kept if and only if:** uplift in win-rate after fees ≥ 3 percentage points AND p99 decision latency ≤ 4 seconds AND $/decision ≤ $0.01.

If LLMs lose:
- Mark OD-5 as resolved: deterministic-only.
- Document the comparison in `runbooks/decisions/llm-ab-result.md`.
- Phase 4 onward runs deterministic-only. Ensemble revisited in Phase 8.

If LLMs win:
- Mark OD-5 as resolved: ensemble-on.
- Phase 4 includes ensemble in paper mode.

Either outcome is a successful gate.

## Files this phase creates

| Path | Purpose |
|---|---|
| `design/backtest.md` | Replay + walk-forward design |
| `design/agents.md` | Per-agent role, schema, cache strategy |
| `src/polymarket_bot/backtest/{engine,fills,walk_forward,cost}.py` | Replay infra |
| `src/polymarket_bot/strategies/deterministic.py` | Baseline strategy |
| `src/polymarket_bot/agents/{orderbook,oracle_gap,momentum,meta,protocol,budget,cache}.py` | Ensemble |
| `prompts/*.md` | Versioned prompts |
| `tests/backtest/*` | Replay correctness tests |
| `tests/agents/*` | Schema + adversarial fixtures |
| `runbooks/decisions/llm-ab-result.md` | OD-5 resolution doc |
| `runbooks/gate-evidence/phase-3.txt` | Captured proof |

## Gate command

`bash runbooks/gates/phase-3.sh` asserts:
1. `make verify` green.
2. Backtest pass on 21-day window: deterministic ≥ 2,500 trades, win-rate ≥ 53% after fees.
3. A/B result file exists with explicit "kept" or "cut" verdict + supporting metrics.
4. If kept: ensemble cost-per-decision documented and ≤ $0.01.
5. Cumulative API spend during this phase ≤ $150 (alarms at $100 within the run).

## Rollback

- Deterministic < 53% win-rate: don't introduce LLMs. Iterate weights, threshold, fee model. Ask: is the captured data biased (e.g. a market regime that doesn't repeat)? Extend capture, re-run.
- Backtest spend overrun: cost-tracker should have killed the run; if it didn't, that's a P0 bug — write postmortem, fix, re-run.
- LLM passes return high refusal rates (>5%): tighten prompts, retry. If still high, that's a real "kill ensemble" signal.

## Wall-clock

3-4 days of focused work. The actual backtest passes are minutes; the design + tests are days.

## USD cost

$50-150 in Anthropic API. Why the wide range: prompt-cache hit rate dictates final cost and we don't know the hit rate until we measure it.

## Memory checkpoint

`checkpoint_phase_3.md`: deterministic win-rate, LLM uplift, OD-5 resolution, total API spend.

---

# PHASE 4 — Paper Trading on Live Venue

**Owner intent.** Run the chosen strategy (deterministic or deterministic+ensemble) against live data for 14 calendar days in paper mode. Validate the simulator. Catch every bug that backtest didn't.

## Pre-flight checklist
- [ ] Phase 3 gate green; OD-5 resolved.
- [ ] 14-day window covers ≥1 CPI/FOMC release, ≥1 weekend low-vol period, ≥1 BTC daily move > 2%. Plan the start date to satisfy this — don't begin Phase 4 the day after FOMC and lose your high-vol regime.

## Tasks

### 4.1 — Implement paper-mode runtime
- `src/polymarket_bot/_paper/shadow_book.py` — receives strategy decisions, simulates fills against the *live* orderbook seen at decision time.
- `src/polymarket_bot/_paper/runner.py` — top-level loop, mirrors `_live` but never submits real orders.
- Import-linter ensures `_paper` and `_live` never cross.

### 4.2 — Schema validation + refusal handling
(If ensemble retained.) Wrap every agent call in `validate_or_retry(schema, max_retries=1)`. On refusal → agent abstains, log `invalid_response`. <2 valid agents in a window → Tier-3 fires.

### 4.3 — Validate the simulator
Before relying on paper mode, prove the simulator's fills match real fills. Take 100 hypothetical decisions over 24h, simulate fills, compare to *the actual top-of-book at that exact timestamp*. Require: ≥ 90% of simulated fills within 1¢ of real top-of-book.

### 4.4 — Run for 14 days
Background process. Daily ritual: review previous day's PnL, alerts, any unhandled exception logs. Postmortem any anomaly > $3 simulated divergence vs backtest expectation.

### 4.5 — Pre-trade decision logging
Every simulated decision logs the full input snapshot (orderbook, oracle state, agent votes, meta rationale). Stored in `state/decisions/<date>.jsonl`. This is the raw material for postmortems and for explaining behavior later.

## Gate command

`bash runbooks/gates/phase-4.sh` asserts:
1. 14 calendar days of paper-mode logs without unhandled exceptions.
2. Regime-coverage criteria met (CPI/FOMC, weekend, >2% move).
3. Simulator validation report shows ≥ 90% of simulated fills within 1¢ of real top-of-book.
4. Paper PnL within 20% of backtest expectation.
5. If ensemble: invalid-response rate < 5%, no decisions reached meta-decider with `None` votes.

## Rollback

- Paper PnL diverges by > 20%: investigate. Common causes: (a) simulator is optimistic on partial fills; (b) live data has microstructure backtest didn't replicate (e.g. quote-stuffing); (c) timing assumptions wrong (e.g. T-10s decisions in paper actually fire at T-9.7s in live, fills move). Iterate the simulator, not the strategy.
- Repeated unhandled exceptions: those are bugs in our code, not the strategy. Apply the 3-fix rule.

## Wall-clock

14 days calendar; 2-3 days dev + monitoring overhead.

## USD cost

$5-15 in API + RPC.

## Memory checkpoint

`checkpoint_phase_4.md`: simulator validation pass-rate, regime coverage achieved, top 3 incidents and resolutions.

---

# PHASE 5 — VPS Provisioning

**Owner intent.** Move execution to Dublin. Verify latency in the way that matters (WS to CLOB). Stand up monitoring + Telegram alerts. Stage the bot in paper mode against live data on the VPS for 24h before declaring the gate.

## Pre-flight checklist
- [ ] Phase 4 gate green.
- [ ] AWS account with billing alerts set ($20/mo cap).

## Tasks

### 5.1 — Provision Lightsail
- Region: `eu-west-1` (Dublin). Plan: 2 vCPU / 4GB / 80GB NVMe. OS: Ubuntu 24.04 LTS. Static IP attached.
- SSH-key only auth, port 2222 (custom port, not 22). UFW: allow 2222 only.
- Create `ops` user, sudoer; disable root SSH.
- `unattended-upgrades` enabled; auto-reboots disabled (we control restarts).
- `chrony` installed and verified: `chronyc sources` shows healthy peers, `chronyc tracking` shows offset < 10ms.

### 5.2 — Install runtime
```bash
apt install -y python3.11 python3.11-venv git redis-server prometheus-node-exporter litestream
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Clone the repo via deploy key (read-only). Install deps via `uv sync --frozen`.

### 5.3 — Latency check the right endpoint
```bash
# WS-specific, not REST:
wscat -c wss://ws-subscriptions-clob.polymarket.com/ws/market 2>&1 | ts %.s | head -200
```
Compute round-trip from a ping-style subscribe → first message. Repeat over 1 hour. Required: p50 < 5ms, p99 < 15ms.

### 5.4 — Two systemd units
- `bot-staging.service` — `mode=paper`, listens on metrics port 9101, runs against live data.
- `bot.service` — `mode=live`, metrics port 9100. **Disabled** until Phase 6 gate.

Both restart on failure with 30s delay. Journal retention 30 days.

### 5.5 — Monitoring stack
- `prometheus-node-exporter` (system metrics) + bot-exposed Prometheus on 9100/9101 (decision counts, win-rate, fill latency, balance).
- Grafana Cloud free tier scrapes both.
- Telegram bot (already running from Phase 0): alert routing through a small `tg-alerter.service` that consumes a Redis-backed alert queue from the bot.
- Inbound `/halt` command: tg-alerter handler writes a sentinel file that the bot's supervisor loop checks every second; on sentinel, bot exits cleanly.

### 5.6 — Move Signer key to VPS
Transfer via age-encrypted file over SSH. Do NOT copy via clipboard. Confirm `.envrc` mode 0600. **Funder key never goes to the VPS.**

### 5.7 — 24h staging run
Start `bot-staging.service`. Watch metrics + Telegram alerts. After 24h with zero unhandled exceptions, gate passes.

## Gate command

`bash runbooks/gates/phase-5.sh` asserts (run from VPS):
1. `systemctl is-active bot-staging` = `active`.
2. `bot.service` exists but is `disabled`.
3. WS p99 latency over the last hour < 15ms (computed from a metrics dump).
4. `chronyc tracking` offset < 10ms.
5. Telegram smoke alert received on phone.
6. `/halt` smoke command works (sets sentinel, bot exits).
7. 24h of staging logs with zero unhandled exceptions.
8. `litestream` replicating `trades.db` to chosen S3-compatible target (resolves OD-2; default Backblaze B2).

## Rollback

- Latency > 15ms p99: try a different Lightsail availability zone within eu-west-1, retest. If still bad, escalate — Polymarket may have rotated infra.
- Telegram inbound `/halt` doesn't fire: most common cause is the alerter polling, not the bot. Check `tg-alerter` logs.
- Signer key transfer botched: regenerate Signer wallet (don't reuse a leaked key), redo Phase 1.4 funding sweep.

## Wall-clock

½-1 day setup + 24h staging.

## USD cost

$5/mo VPS recurring; ~$1 first-month prorated. B2 storage $0.005/GB/mo (negligible).

## Memory checkpoint

`checkpoint_phase_5.md`: VPS public IP, measured WS latencies (p50/p99), staging exception count over 24h.

---

# PHASE 6 — Live with Kill-Switches

**Owner intent.** $1,000 funded. $5 flat per trade (0.5% sizing). Five kill-switches. 14 days. Every kill-switch tested synthetically before real money rides on it.

## Pre-flight checklist
- [ ] Phase 5 gate green.
- [ ] Signer balance on Polymarket = $50 (transferred via Phase 1 setup; re-verify).
- [ ] You are awake during the first hour of live trading. Ideally not at midnight UTC.

## Tasks

### 6.1 — Implement the five kill-switches
Each is a guard that sets `bot.halt_new_entries = True` and pages Telegram.

1. **Heartbeat:** any of (binance, coinbase, oracle, polymarket) silent > 10s.
2. **Slippage:** rolling-10-trade avg fill slippage > 2¢.
3. **Drawdown:** session loss > **$50 (5% of $1k bankroll)** OR cumulative loss > **$100 (10%)**.
4. **Reconciliation drift:** `on_chain_usdc - internal_bankroll > $0.50` for 60s sustained.
5. **Win-rate drift:** rolling-100-trade win-rate < `expected - 2σ` (binomial CI).

Files:
- `src/polymarket_bot/_live/kill_switches/{heartbeat,slippage,drawdown,reconciler,drift}.py`
- `src/polymarket_bot/_live/supervisor.py` — coordinates all five, owns the halt flag.
- `tests/kill_switches/*` — synthetic-trip tests for each.

### 6.2 — Pre-flight: synthetic kill-switch tests
**Why:** All five must trip in test before they're trusted in live.

```bash
uv run pytest tests/kill_switches -q --runintegration
```
Each test injects the failure condition and asserts: bot halts new entries, Telegram alert sent (to the test channel, not the production one).

### 6.3 — $5 flat sizing
`src/polymarket_bot/strategies/sizing.py`:
- For first 100 live trades: `size_usd = 5.0` (clears the $4.75 minimum; 0.5% of $1k bankroll).
- Trade #101+: switch to `size_usd = max(5.0, kelly_fraction * bankroll * confidence)` where `kelly_fraction ≤ 0.25`.
- Hard cap: `size_usd ≤ 0.10 * bankroll` always (= $100 cap at $1k bankroll).
- **Funder/Signer split:** Funder holds $900, Signer holds ≤$100. Nightly: if Signer > $100 sweep excess back to Funder.

### 6.4 — Daily ritual
Every day at 12:00 UTC:
- Run `scripts/daily_recon.py`: PnL summary, kill-switch trip count, win-rate, simulator-vs-live divergence.
- Output mirrored to Telegram (full daily digest) and `state/daily/<date>.md`.

### 6.5 — Postmortem any incident
Any kill-switch trip, any > $3 unexplained loss, any unhandled exception → `state/postmortems/<date>-<slug>.md` within 24h. Use the standard template at `state/postmortems/_template.md`.

### 6.6 — Maker-rebate side income (optional this phase)
If win-rate stable after 7 days, enable the maker layer: park resting limit orders close to mid on weak-signal windows. Free yield from CLOB v2 rebate program. Cap: 25% of bankroll in resting orders at any time.

## Gate command

`bash runbooks/gates/phase-6.sh` asserts:
1. 14 calendar days live.
2. ≥ 100 trades executed (so we have a usable empirical win-rate).
3. All 5 kill-switches tripped at least once (via synthetic injection during the period).
4. Zero unexplained losses (every loss has a postmortem if > $3 vs simulator expectation).
5. Reconciliation drift never exceeded $0.50.
6. Cumulative session PnL >= -$25 (i.e., the total drawdown breaker was never within $5 of its absolute trip).

## Rollback

- Drawdown breaker trips: bot halts. Mandatory cooling-off: 24h before re-enabling. Postmortem must be written and signed off (by user).
- Reconciliation drift trips: investigate immediately — most common cause is a partial fill the bot called as full. Don't restart until on-chain state matches internal state, by hand if necessary.
- Win-rate drift trips: this is the regime-change signal. Stop, investigate, decide whether to refit weights (Phase 8) or pause.

## Wall-clock

14 days calendar; ongoing daily attention 30 min/day.

## USD cost

$1,000 working capital (not consumed; at risk). $5/mo VPS + $50-195 LLM API (24/7) — top up Anthropic to $300 before this phase starts.

## Memory checkpoint

`checkpoint_phase_6.md`: empirical 100-trade win-rate, total trades, session PnL, kill-switch trip log.

---

# PHASE 7 — Scale + Maker Rebates

**Owner intent.** Only after Phase 6 passes cleanly: scale bankroll along $1k → $3k → $10k → $30k. Add a competing strategy variant in shadow. Switch to fractional Kelly.

## Phase 7 ladder
Each rung requires: 7 calendar days of positive PnL on previous rung, zero kill-switch trips, OD-6 evaluated at the $3k step.

| Rung | Bankroll | Trade size rule | New constraint |
|---|---|---|---|
| 7.1 | $3,000  | Kelly fraction × 0.25 × bankroll, min $5 | **Buy hardware wallet for Funder** (resolves OD-6); breaker -$150 daily |
| 7.2 | $10,000 | Kelly × 0.20 | Multi-account proxy wallets, per-account caps |
| 7.3 | $30,000 | Kelly × 0.15 | LLC consideration; tax software (Koinly) integration |

### 7.4 — Variant arena
Pattern from `references/polymarket-bot-arena`. Run a second variant in shadow mode. Variants compete weekly; winner takes capital allocation.

### 7.5 — Quarterly weight refit
- `scripts/refit_weights.py` — input: last 30 days of trades, output: new weights vector with A/B comparison vs current.
- Promotion rule: refit weights ship only if backtest uplift over current ≥ 1pp AND paper-mode 48h validation matches.

## Gate command

Per-rung gate. `bash runbooks/gates/phase-7-rung-N.sh` asserts the rung's specific criteria.

## Wall-clock + cost

Ongoing. Each rung gate is 7+ days minimum.

## Memory checkpoint

`checkpoint_phase_7_rung_N.md` per rung.

---

# PHASE 8 — Hardening (ongoing)

**Owner intent.** Production-grade ops. Migration handling. Standby. Multi-account.

Tracked items (open ad-hoc):

- USDC.e → native USDC migration as Polymarket completes the rollout.
- Frankfurt warm-standby VPS via litestream replication.
- Multi-account proxy wallets at > $50k.
- On-call rotation (eventually with someone other than just you).
- Quarterly Polymarket changelog review (1 day/quarter budgeted).
- Re-evaluate dropped LLM ensemble if deterministic strategy decays — A/B again.
- Re-evaluate OpenAI fallback when LLM ensemble runs at scale.

No fixed gate; each item is its own design + implementation + test pass.

---

# Appendix A — Memory checkpoint template

Save as `~/.claude/projects/.../memory/checkpoint_phase_N.md`:

```markdown
---
name: checkpoint_phase_N
description: Phase N gate passed YYYY-MM-DD. Next phase: N+1.
type: project
---

**Phase N complete.** Gate evidence: `runbooks/gate-evidence/phase-N.txt`.

**Key numbers measured:**
- [ ] ...
- [ ] ...

**Decisions resolved this phase:**
- OD-X: <how>

**Decisions still open:**
- [list remaining]

**Anomalies observed (worth remembering):**
- ...

**Next phase pre-flight items I already know are not in place:**
- ...
```

# Appendix B — Gate evidence format

Each `runbooks/gate-evidence/phase-N.txt` is the literal stdout of `runbooks/gates/phase-N.sh` plus a final line:

```
PHASE N GATE PASSED <ISO-8601 UTC>  <git rev-parse HEAD>
```

Commit the file. Tag the commit: `git tag phase-N-pass`. Tags are how future sessions find the most recent green gate.

# Appendix C — Cost ledger format

`runbooks/cost-ledger.md` — a simple running log:

```
2026-MM-DD  | phase  | item                  | USD     | cumulative
2026-05-04  | 0      | gh repo, telegram     |    0.00 |       0.00
2026-05-05  | 1      | MATIC + USDC funded   |   55.00 |      55.00
...
```

# Appendix D — Rollback inventory

| Phase | Reversible items | Hard-to-reverse items |
|---|---|---|
| 0 | everything | none |
| 1 | derive creds, sign tests | wallet generation (key material exists), USDC funded (recoverable to Funder) |
| 2 | code, captured data | none (data can be re-captured) |
| 3 | code | API spend (sunk cost; cap enforced) |
| 4 | code, paper logs | API + RPC spend (sunk cost) |
| 5 | VPS provision | Signer key now on second machine (regenerate if leak suspected) |
| 6 | most | live trades (real PnL, sunk) |
| 7 | most | larger sums at risk; rolling back doesn't recover losses |
| 8 | most | depends on item |

---

**End of RUNBOOK.md.** Resume work by finding the highest `phase-N-pass` tag in git, reading that phase's checkpoint memory, and starting the next phase's pre-flight checklist.
