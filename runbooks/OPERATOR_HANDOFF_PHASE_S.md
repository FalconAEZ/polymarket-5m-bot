# OPERATOR HANDOFF — Phase S Market-Maker Bot

**Date authored:** 2026-05-20.
**Branch:** `claude/phase-S-market-maker` @ `<latest>`.
**Status:** all code shipped + locally verified + pushed to origin. VPS code synced. Auxiliary services (monitoring) re-enabled. Trading services (paper + live MMB) still disabled, waiting on operator pre-deploy actions documented below.

This is the single source of truth for getting MMB live. Read top-to-bottom; do each step in order.

---

## 0. What I already did autonomously

1. **10 commits ahead of `9516f39`**, pushed to `origin/claude/phase-S-market-maker`. View on GitHub: `https://github.com/FalconAEZ/polymarket-5m-bot/tree/claude/phase-S-market-maker`.
2. **VPS git pull**: `/home/ops/polymarket-5m-bot` is now on the Phase S branch at the latest commit.
3. **`bot-mm.service` installed** on VPS at `/etc/systemd/system/bot-mm.service`. Status: **disabled + inactive** (won't auto-start; needs operator action).
4. **Monitoring re-enabled** on VPS:
   - `dashboard-server.service` — active + enabled (web UI on port 8505).
   - `litestream.service` — active + enabled (S3 backups of `state/trades.db`).
   - `tg-alerter.service` — active + enabled (Telegram alerts + `/halt` watcher).
   - Verified end-to-end: pushed a test alert via Redis → tg-alerter drained → operator's Telegram received it.
5. **Trading services stay disabled**: `bot.service`, `bot-staging.service`, `bot-mm.service`, `rtt-collector.service` all `disabled + inactive`. Halt sentinel at `state/halt.sentinel` is in place as belt-and-suspenders.

You can monitor the VPS right now via Telegram (`/halt` works) + the dashboard URL (SSH tunnel: `ssh -i ~/Desktop/LightsailDefaultKey-eu-west-1.pem -p 2222 -L 8505:127.0.0.1:8505 ops@108.132.51.116`, then http://localhost:8505).

---

## 1. What I cannot do (your hands required)

Every step below touches real money OR makes a live-trading commitment that I should not gate behind an LLM. Skip none.

### 1.1 Set wallet + CLOB env vars on VPS

SSH in:

```bash
ssh -i ~/Desktop/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116
```

Edit `/home/ops/polymarket-5m-bot/.envrc` — append these lines (replace placeholders with your real values; **never** commit this file):

```bash
# Phase S MMB — wallet + CLOB creds + live consent
export PK_SIGNER='<Signer private key, hex with 0x prefix>'
export POLY_FUNDER='<Funder proxy wallet address, 0x...>'
export POLY_PRIVATE_KEY='<same as PK_SIGNER — derive_creds.py reads this name>'
# Run derive_creds.py first if you don't have these three:
export CLOB_API_KEY='<from derive_creds output>'
export CLOB_API_SECRET='<from derive_creds output>'
export CLOB_API_PASSPHRASE='<from derive_creds output>'
export MM_LIVE_CONFIRM=yes
```

To derive the CLOB L2 creds from the Signer private key:

```bash
cd /home/ops/polymarket-5m-bot
source .envrc   # picks up POLY_PRIVATE_KEY
uv run python scripts/derive_creds.py >> .envrc   # appends 3 export lines
source .envrc   # picks up the new exports
```

Sanity check (no values printed):

```bash
env | grep -E '^(PK_SIGNER|POLY_FUNDER|CLOB_API_KEY|CLOB_API_SECRET|CLOB_API_PASSPHRASE|MM_LIVE_CONFIRM)=' | wc -l
# Expect: 6
```

### 1.2 Set USDC.e allowance

The Signer wallet must approve the CTF Exchange to spend USDC.e. **One-time on-chain tx.**

```bash
cd /home/ops/polymarket-5m-bot
uv run python scripts/mm_set_allowance.py
# Reports current allowance. If sufficient (>= $10k), you're done.
# If not, run with --apply:
uv run python scripts/mm_set_allowance.py --apply
# Prompts for "YES I CONFIRM" before broadcasting.
# Costs ~$0.01 in MATIC gas on the Signer.
```

Alternative (don't want script to broadcast): use Polymarket.com UI "Enable Trading" or `cast send` per the script's docstring. After any path, re-run `mm_set_allowance.py` (no `--apply`) to verify. Successful run produces `state/mm-allowance.json` audit.

### 1.3 Run G11 empirical probes

Three probes against a live BTC 5m market. Each writes a runbook addendum. Total real-money exposure: ~$5 worst case (fee probe).

```bash
cd /home/ops/polymarket-5m-bot

# Probe 1: maker fee (~$5 exposure if fills; auto-cancels after 5min if not)
uv run python scripts/research/mmb_g11_probes.py --mode fee

# Probe 2: cancel latency (places + cancels 100 times; ~$0 exposure)
uv run python scripts/research/mmb_g11_probes.py --mode cancel-latency

# Probe 3: rate-limit (places at increasing rates until 429; ~$0 exposure)
uv run python scripts/research/mmb_g11_probes.py --mode rate-limit
```

Each probe writes to:
- `runbooks/S-mmb-{fee|cancel-latency|rate-limit}-empirical-<UTC>.md`
- `state/research/g11-{fee|cancel-latency|rate-limit}-<UTC>.json`

**Decision point after fee probe:**
- If `realized_fee_bps` ≈ 0: proceed unchanged.
- If `realized_fee_bps` > 0 (e.g., 50-100 bps): tell me the number; I'll recalibrate `J7Priors.bet_size` math (add fee term to EV check) BEFORE you start the bot.

### 1.4 Flip ExecStart + remove halt sentinel

Currently `bot-mm.service` ExecStart points at `scripts/run_mm_paper.py` (paper-mode). To run live:

```bash
sudo sed -i 's|scripts/run_mm_paper.py|scripts/run_mm_live.py|' /etc/systemd/system/bot-mm.service
sudo systemctl daemon-reload
cat /etc/systemd/system/bot-mm.service | grep ExecStart
# Verify it says run_mm_live.py
```

Remove the halt sentinel (the bot will refuse to start if it's present):

```bash
rm /home/ops/polymarket-5m-bot/state/halt.sentinel
```

### 1.5 Start the bot

```bash
sudo systemctl enable bot-mm.service
sudo systemctl start bot-mm.service
sudo journalctl -u bot-mm.service -f
```

Within 5 minutes you should see:
- "pre-flight OK" in the journal.
- "discovering active BTC 5m markets" + "found N markets".
- First ladder placements appear in `state/mm-decisions/<UTC>.jsonl`.
- First fill (whenever it lands) → Telegram alert.

If pre-flight fails, journal shows the specific reason. Fix + restart.

---

## 2. During the soak

### 2.1 Daily check-in (operator)

Every 12–24h:

```bash
# Last 24h MMB activity
ssh -i ~/Desktop/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 \
  "sudo journalctl -u bot-mm.service --since '24h ago' | grep ERROR | wc -l"
# Expected: 0 (or very few)

# Recent decisions
ssh ... "tail -50 /home/ops/polymarket-5m-bot/state/mm-decisions/\$(date -u +%F).jsonl"

# Today's PnL
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/quirky-hamilton-528e8b
# Pull decision log from VPS
mkdir -p /tmp/mmb-soak-data
scp -i ~/Desktop/LightsailDefaultKey-eu-west-1.pem -P 2222 \
  ops@108.132.51.116:/home/ops/polymarket-5m-bot/state/mm-decisions/\*.jsonl \
  /tmp/mmb-soak-data/
uv run python scripts/research/mmb_soak_audit.py --days 1 \
  --decision-log-root /tmp/mmb-soak-data
```

Telegram channel + dashboard URL are the always-on observability.

### 2.2 Day-1 audit (T+24h)

```bash
uv run python scripts/research/mmb_soak_audit.py --days 1 \
  --decision-log-root /tmp/mmb-soak-data
```

Send me the JSON output (just the `pnl_total_usd`, `fill_rate`, and any anomalies). I'll write the formal Day-1 runbook entry.

### 2.3 Day-7 audit (T+7d) — promotion gate

```bash
uv run python scripts/research/mmb_soak_audit.py --days 7 --gate \
  --decision-log-root /tmp/mmb-soak-data
```

Gate criteria (all must pass to advance to S.6):
- Cumulative PnL > $0
- No heartbeat misses / daily-loss trips
- Fill rate in normal bounds [0, 1]

**If PASS** → S.6: scale-up caps (`RiskCaps` to live-micro-target column) + 5-day soak.
**If FAIL** → postmortem at `runbooks/postmortems/2026-05-XX-mmb-s5-failure.md`. Phase S possibly halts at "MMB strategy class not viable at $1k" per design risk R1.
**If marginal (e.g., +$5 cumulative, no incidents)** → extend soak 7 more days at live-micro caps. Tell me; I'll prep the extension.

---

## 3. Emergency procedures

### 3.1 Halt MMB immediately

From your laptop:

```bash
ssh -i ~/Desktop/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 \
  "python3 -c 'import json,time; open(\"/home/ops/polymarket-5m-bot/state/halt.sentinel\",\"w\").write(json.dumps({\"halted_at_ns\":time.time_ns(),\"halted_by\":\"operator-cli\",\"reason\":\"emergency-halt\"}))'"
```

Or via Telegram: send `/halt` to the bot's chat. tg-alerter watches for this.

The bot detects the sentinel within 1s (book-poll cadence) + drains all open orders + exits. systemd's `Restart=on-failure` kicks in but the next start sees the sentinel + exits with code 2. The bot will stay halted until you manually `rm state/halt.sentinel`.

### 3.2 Stop MMB cleanly

```bash
ssh ... "sudo systemctl stop bot-mm.service"
```

SIGTERM handler drains within 30s. systemd's `TimeoutStopSec=30` gives the drain headroom.

### 3.3 Disable MMB so it never restarts

```bash
ssh ... "sudo systemctl disable bot-mm.service && sudo systemctl stop bot-mm.service"
```

---

## 4. What I'm waiting on from you, exactly

Minimum to bring MMB live:

| # | Step | Required input | Risk |
|---|---|---|---|
| 1.1 | Add wallet + CLOB env vars to VPS `.envrc` | PK_SIGNER + POLY_FUNDER + L2 creds + MM_LIVE_CONFIRM=yes | none (config only) |
| 1.2 | Run `mm_set_allowance.py` (verify then `--apply`) | confirmation prompt + ~$0.01 MATIC | one-time on-chain tx |
| 1.3 | Run 3 G11 probes | ~$5 max during fee probe | small real-money exposure |
| 1.4 | sed ExecStart + `rm state/halt.sentinel` | none | unblocks start |
| 1.5 | `systemctl enable + start bot-mm.service` | none | bot begins trading |

After 24h: daily audit (§2.2) — send me numbers.
After 7d: Day-7 audit (§2.3) — promote or postmortem.

---

## 5. Quick links

- Phase plan: [runbooks/phase-S-high-volume-plan-2026-05-20.md](phase-S-high-volume-plan-2026-05-20.md)
- Design lock: [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md)
- S.1.1 research: [runbooks/S-mmb-research-2026-05-20.md](S-mmb-research-2026-05-20.md)
- Backtest runbook: [runbooks/research/mmb-backtest-2026-05-20.md](research/mmb-backtest-2026-05-20.md)
- Session notes: `state/sessions/2026-05-{19,20}-phase-S-*.md`
- Decisions: `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md` (#22, #23)
- Memory checkpoints: `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_*.md`
- VPS access: `memory/reference_vps_ssh.md`

---

## 6. The honest summary

**MMB code is shipped, tested, committed, pushed.** 785 tests passing. All gates green. The bot can be brought live with 5 operator steps totaling ~10 minutes (allowance tx + probes + ExecStart flip + start). What it does once live is what bonereaper's data suggests it might do — but the only way to know is to run it.

**If it works (Day-7 PnL > $0)**: we promote to S.6 scale-up caps.
**If it doesn't (Day-7 PnL ≤ $0 or incidents)**: we have an honest experiment result. Postmortem written; Phase S concluded; we know MMB at $1k isn't viable.

Either outcome is informative. The 7-day soak is the answer.
