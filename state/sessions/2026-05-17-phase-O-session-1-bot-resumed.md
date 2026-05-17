# 2026-05-17 — Phase O Session 1: SURV canary shipped, bot RESUMED

## Context handoff

Same UTC day as Phase N forensic Sessions 1+2. Operator chose
"Full plan steps 1-6 (Recommended)" via 4-question dialog — ship the
data-grounded remediations from Phase N's PDF §7 (ranked
recommendation), with M.5 active + M.1a v1 disabled + SURV canary new
(addresses the gap the PDF identified — no Phase M layer was designed
for the SURV-cell flip that drove most of the −$1,562 swing).

## What shipped

### Code (commit `16e8f38`)

- `design/O.0-phase-n-m5-persistence-null.md` — correction-of-record:
  M.5 already implicit-persists via JSONL replay. The PDF's "M.5
  persistence" recommendation was based on a faulty simulator assumption
  and is moot.
- `design/O.1-surv-cell-shift-canary.md` — data-tuned canary spec:
  lookback=15, min_samples=10, margin=−0.01, |Δbps|≥5 threshold.
  Params chosen by parameter sweep on the n=755 forensic dataset.
- `src/polymarket_bot/strategies/surv_canary_metrics.py` — new module
  (~200 LOC), mirrors `path_a_wr_metrics.py` but scoped to tier 30-50%
  × |Δbps|≥5.
- `src/polymarket_bot/strategies/spot_aware_v2_1.py` — canary gate
  plugged in pre-super() at the M.5 site. Tier 30-50% fires abstain
  when rolling_wr < mean_price + margin (margin is negative so this
  means "only abstain when truly losing money below break-even").
- `scripts/run_paper.py` — 60s-cached canary getter + WARN-level
  first-trip/recovery state-transition log.
- `tests/strategies/test_spot_aware_v2_1.py` — 11 new SURV canary
  tests (gate behavior + module unit tests).

### Pre-deploy gates

- 697 tests pass (incl. 11 new SURV canary tests)
- mypy --strict: 86 src files, no issues
- ruff: all checks passed (after `--fix` + research-script noqa)
- import-linter: 3/3 contracts kept

### Backtest on n=755 forensic dataset

Margin=−0.01, lookback=15, min_samples=10:
- 162 fires abstained
- Counterfactual PnL avoided: **+$280.18**
- Pre-peak trips (false positives): 2 (both fast-recovery)
- Post-peak trips: 11

Honest correction to PDF §7.1 step 2: the +$700 counterfactual claim
was over-stated. The actual +$280 is the data-tuned floor.

### VPS deploy

- `git pull` on bot-staging at `16e8f38`
- `.envrc` edits (backup at `.envrc.bak.phase-O-2026-05-17`):
  - `REGIME_M1A_V1_ENABLED=true` → `false` (PDF §7.2 secondary rec)
  - Added: `SURV_CANARY_ENABLED=true` (+ 4 supporting env vars)
  - Kept: `REGIME_M5_PATH_A_GATE_ENABLED=true` (was already on)
- `state/halt.sentinel` → archived at
  `halt.sentinel.cleared.phase-O-2026-05-17`
- `systemctl restart bot-staging.service` → MainPID 993820, active

### Startup-log verification (UTC 16:25:25)

```
spot_aware_v2_1: kelly_mult=0.15 max_bet_abs=$500 multi_fire_cap=1
                 tier_relax_p_win_fallback=None
                 tier_relax_price_floor=0.420
                 block_up_in_tiers=('70-85%',)
                 hour_blocklist_utc=(22, 23, 0)
                 hour_blocklist_tiers=('70-85%',)
M.1a v0 shadow ENABLED (RegimeDetector wired)
M.1a v1 DISABLED (REGIME_M1A_V1_ENABLED=false)
M.5 ACTIVE — Path A regime gate enabled (lookback_n=30, min_samples=20, margin=0.020)
O.1 SURV CANARY ACTIVE — tier 30-50% shift detector enabled
  (lookback_n=15, min_samples=10, margin=-0.010, min_|Δbps|=5.0)
active strategy: spot_aware_v2_1
bankroll replay: starting=$1000.00 current=$783.91
auto_halt_watcher started: gate=$-30.00, check=23:50 UTC, poll=30s
```

No errors, no exceptions.

## Bot state — LIVE

- HEAD `16e8f38` on `claude/jovial-hermann-7e103f`
- bot-staging.service ACTIVE since 2026-05-17 16:25:24 UTC, MainPID 993820
- bankroll $783.91 (cum −$216.09; +$110 above the halt-time snapshot
  due to post-halt settled_correction records)
- L.5 daily-PnL auto-halt active (gate=−$30, check=23:50 UTC)
- M.5 Path-A gate active
- O.1 SURV canary active (will WARN-log on first trip)

## What we did NOT ship this session (deferred to Session 2)

- J.2 hour-blocklist extension to tier 30-50% bleed-hours. Reason:
  current env-flag is cross-product (hours × tiers), which would
  incorrectly block tier-30-50% × hour-22 (a winner cell). Needs a
  per-tier-hour env-flag redesign.
- M.2 v0 imbalance promotion to active (n=3 forensic dataset; un-evaluable).
- N.5/N.6/N.7 regime-classifier validity / shift detection / Kelly
  counterfactual (Future Work from PDF §6).

## Next session

- Watch the first 24-48h of fresh fires on the new config
- Verify SURV canary trips behave (Telegram heartbeat from WARNING-level logs)
- L.5 daily-PnL gate check at 2026-05-17 23:50Z — if today's PnL < −$30
  the bot will auto-halt. The bot resumed at $783.91 with today's PnL
  already at −$354.91 (pre-halt) — **L.5 WILL trip tonight at 23:50Z**
  unless today's PnL is reset (which it isn't, per the auto_halt design).

That trip is INTENDED (it's the daily reset point) — operator clears
sentinel on 2026-05-18 to start fresh.

## Files written this session

- All 16 files committed in `16e8f38`
- `state/sessions/2026-05-17-phase-O-session-1-bot-resumed.md` (this file)
