# Windows PC setup — manual-only steps

> **Read first:** this document lists ONLY the things you must do
> with your hands. Anything Claude can do remotely (install Python
> packages via uv, run pytest, write code, edit configs) is omitted.

## What you actually need

You're picking up a Polymarket trading bot project. After cloning the
repo, Claude can do almost everything from a fresh Claude Code session.
The list below is the irreducible "human only" surface — installer
downloads, account sign-ins, security prompts, env-var population.

---

## Step 1 — Install Git for Windows

The repo lives on GitHub. You need git.

1. Download: https://git-scm.com/download/win (the installer)
2. Run it. Default options are fine. **Choose "Use Git from the
   command line and also from 3rd-party software"** when asked.
3. Verify in PowerShell:
   ```powershell
   git --version
   ```
   Should print `git version 2.x.x`.

## Step 2 — Install Python 3.11

The project pins `requires-python = ">=3.11"`.

1. Download: https://www.python.org/downloads/release/python-3119/
   (Windows installer — pick the 64-bit version)
2. Run it. **Check "Add python.exe to PATH"** at the bottom of the
   first installer screen.
3. Verify in PowerShell:
   ```powershell
   python --version
   ```
   Should print `Python 3.11.x`.

## Step 3 — Install uv

uv is the Python package manager the project uses (fast, lockfile-driven).

1. PowerShell (Run as Administrator if needed):
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
2. Close + reopen PowerShell.
3. Verify:
   ```powershell
   uv --version
   ```

## Step 4 — Clone the repo

```powershell
cd $HOME\Desktop                  # or wherever you want it
git clone https://github.com/FalconAEZ/polymarket-5m-bot
cd polymarket-5m-bot
```

The default branch (`main`) is now up-to-date with the latest work
(Phase 0 → Phase 4.5). No branch switching needed.

## Step 5 — Install dependencies

```powershell
uv sync
```

This reads `pyproject.toml` + `uv.lock`, creates `.venv\` in the
repo, and installs everything. Takes 1-2 minutes the first time.

## Step 6 — Populate `.envrc`

The project reads environment variables from `.envrc` (gitignored,
never committed). On Windows you have two options:

### Option A — Use direnv (recommended if you'll do this often)

Install direnv: https://direnv.net/docs/installation.html#windows

Then create `.envrc` in the repo root with:

```bash
export POLYGON_RPC_URL="wss://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY"
export TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN"
export TELEGRAM_CHAT_ID="YOUR_CHAT_ID"
# Phase 1+ wallet keys (only needed for Phase 1+ work, not paper):
# export POLY_PRIVATE_KEY="..."
# export POLY_API_KEY="..."
# export POLY_API_SECRET="..."
# export POLY_API_PASSPHRASE="..."
```

### Option B — Set as Windows environment variables

```powershell
[System.Environment]::SetEnvironmentVariable("POLYGON_RPC_URL", "wss://...", "User")
[System.Environment]::SetEnvironmentVariable("TELEGRAM_BOT_TOKEN", "...", "User")
[System.Environment]::SetEnvironmentVariable("TELEGRAM_CHAT_ID", "...", "User")
```

Close + reopen PowerShell to pick them up.

> **Where to find these values:** they're already provisioned from
> Phase 0. You set them up in the Anthropic + Alchemy + Telegram
> accounts. See `state/sessions/2026-05-06.md` for the original
> Phase 0 close-out — the secrets themselves are NOT in git, they're
> in your password manager / on the Mac.

## Step 7 — Smoke-test the install

```powershell
uv run pytest -q
```

Should show **`274 passed`** (no warnings of consequence). If you see
anything red, that's a regression — open a fresh Claude Code session
in this directory and report it.

```powershell
uv run mypy --strict src\
```

Should show **`Success: no issues found in 43 source files`**.

```powershell
uv run lint-imports
```

Should show **`Contracts: 3 kept, 0 broken`**.

## Step 8 — Install Obsidian

See `runbooks/obsidian-setup.md` — short version:
1. Download from https://obsidian.md/download
2. Open Obsidian → "Open folder as vault" → select `<repo>\state`
3. Skim `state/sessions/2026-05-07-evening.md` for the latest hand-off

## Step 9 — Install a code editor (optional but recommended)

VS Code is the lightest, has the best Python tooling, and integrates
with Claude Code:

1. https://code.visualstudio.com/Download
2. After install, open the repo: `code .` from inside `polymarket-5m-bot\`
3. Install extensions when prompted: Python, Pylance, ruff

## Step 10 — Open Claude Code in the project

```powershell
cd $HOME\Desktop\polymarket-5m-bot
claude
```

(Assuming Claude Code CLI is installed. If not, see
https://docs.claude.com/en/docs/claude-code/quickstart for the Windows
installer.)

Paste the contents of `RESUME-WINDOWS.md` (in the repo root) as your
first message. Everything else from there is automatable.

---

## What you do NOT need to do manually

These are listed so you don't accidentally do them — Claude handles
them better:

- ❌ pip install anything (uv handles it via `uv sync`)
- ❌ Create virtual environments manually (uv creates `.venv/`)
- ❌ Edit Python source files (Claude writes code)
- ❌ Run pytest manually after every change (the dev loop covers it)
- ❌ Write commit messages from scratch (Claude drafts them)
- ❌ Set up git config user.name / user.email if you've used git before
  on this machine
- ❌ Configure ruff/mypy/pre-commit (already set up in repo)

## When you'll need to do something manual mid-session

- Approving destructive operations (Claude asks; you say yes/no)
- Opening browser tabs (Anthropic console, GitHub PR pages)
- Phase 1B and beyond — anything touching real money requires you
- Future VPS provisioning (Phase 5) — see `RESUME-WINDOWS.md`
- Git push to remotes you set up (Claude asks before push)
