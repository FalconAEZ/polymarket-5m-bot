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

## Bot state — LIVE (initial resume — pre-bankroll-reset snapshot)

- HEAD `16e8f38` on `claude/jovial-hermann-7e103f`
- bot-staging.service ACTIVE since 2026-05-17 16:25:24 UTC, MainPID 993820
- bankroll $783.91 (cum −$216.09; +$110 above the halt-time snapshot
  due to post-halt settled_correction records)
- L.5 daily-PnL auto-halt active (gate=−$30, check=23:50 UTC)
- M.5 Path-A gate active
- O.1 SURV canary active (will WARN-log on first trip)

## Mid-session pivots — bankroll reset + L.5 scaling + M.5 lookback

After the initial resume above, operator made several further changes
in the same session:

### Bankroll reset to $3,000 (decision #10 override) — 16:32Z

Operator directive: "reset bankroll to 3,000$ go".

- `.envrc`: `PMB_STARTING_BANKROLL=1000` → `3000`,
  `BANKROLL_REPLAY_ENABLED=true` → `false`
- Strict-reset semantics: bot now reads $3,000 directly, ignores JSONL
  replay for bankroll computation (M.5 + SURV canary still read JSONL
  for their rolling state).
- Backup at `.envrc.bak.bankroll-reset-2026-05-17` on VPS.
- Restart: bot-staging.service MainPID 995787 from 16:32:40Z.
- Locked decision #10 ($1,000 paper bankroll) is now OVERRIDDEN. See
  `memory/project_bankroll_reset_2026_05_17.md`.
- Risk implication flagged to operator: Kelly 0.15× of $3k → bet sizes
  ~$135-$450/fire (3-3.8× larger than at $1k). L.5 at −$30 → single
  losing fire blows the gate.

### L.5 scaling: −$30 → −$90 — 16:34Z

Operator directive: "yes scale L.5".

- `.envrc`: `DAILY_PNL_GATE_USD=-30.0` → `-90.0` (3× scaling preserves
  the original 3%-of-bankroll posture).
- Restart: MainPID 996239 from 16:34:04Z.
- Trade-off documented: L.5 still trips tonight at 23:50Z because
  today's pre-halt PnL of −$354.91 is locked in the JSONL and far
  exceeds the new −$90 gate.

### Dashboard env passthrough fix — 16:51Z (commit `98940b1`)

Discovered the dashboard hero row showed `$785.74` (JSONL replay
from $1k anchor) while the bot ran at `$3,000`. Operator-visible
divergence. Fixed:

- `src/polymarket_bot/dashboard/bankroll.py::load_bankroll`: add
  `replay_enabled` kwarg; when False, `current = starting`.
- `src/polymarket_bot/dashboard_server/state.py`: read
  `PMB_STARTING_BANKROLL` + `BANKROLL_REPLAY_ENABLED` from env with
  defaults that preserve historical $1k/replay-on behavior.
- VPS systemd drop-in
  `/etc/systemd/system/dashboard-server.service.d/bankroll.conf` adds
  `Environment=PMB_STARTING_BANKROLL=3000` +
  `Environment=BANKROLL_REPLAY_ENABLED=false`.
- Commit `98940b1`. 697 tests + mypy strict + ruff all green.
- Verified post-deploy: `/api/state` reports
  `bankroll.starting_usd=$3,000`, `current_usd=$3,000`, `delta=$0`.

### M.5 lookback tuning: 30 → 15 — 17:00Z

Operator directive after my "stuck-state" pushback. Recent Path-A WR
on last 15 fires was 66.7% (vs 53.3% on last 30) — recent regime is
improving, faster lookback responds to it.

- `.envrc`: `REGIME_M5_LOOKBACK_N=30` → `15`,
  `REGIME_M5_MIN_SAMPLES=20` → `10` (2/3 ratio preserved).
- Restart: MainPID 1002001 from 17:00:22Z.
- M.5 + SURV canary now share identical lookback shape
  (15-fire / 10-sample). At restart the gate still abstained
  (rolling 66.7% < threshold 75.5%) but the gap narrowed to 8.8pp.

## Post-restart observation (17:00Z → 19:33Z, ~2.5h)

| metric | value |
|---|---|
| New fires | **1** |
| Expected at ~4.5/hr | ~11 (M.5 closes Path A → 30% suppression baseline) |
| Effective rate | ~0.4/hr (signal-quiet stretch dominated) |
| 17:39:36Z fire | tier 30-50% × DOWN @ $0.45, bet $163.64, kelly_f=0.364, p_win=0.65, ev=+0.195 |
| Settle outcome | resolution=UP (LOSS), pnl=−$163.67 |
| settled_correction | applied at 17:46Z (chainlink-vs-polymarket reconciliation) |
| Today PnL change | −$354.91 → −$518.58 |
| Streak | ▼ 4 |

Net Session-1 picture at 19:33Z observation:
- M.5 has held Path A closed (zero new tier 70-85% fires)
- SURV canary stayed open — did not block the 17:39Z tier-30-50% fire
  (canary rolling WR was above threshold at fire-time)
- L.5 trip at 23:50Z UTC is locked in (today PnL −$518.58 ≪ −$90 gate)
- Bot will auto-resume tomorrow morning via the `l5_auto_resume.sh`
  cron at 23:53Z UTC (sentinel reason will be `auto-halt-daily-pnl`,
  not `operator-cooldown` → cron condition passes)

## Bot state — LIVE (final Session 1 snapshot @ 19:33Z)

- HEAD `16e8f38` (code) + `d3ed2a8` (vault docs) + `98940b1` (dashboard fix)
- bot-staging.service ACTIVE since 17:00:22Z, MainPID 1002001
- bankroll $3,000.00 anchor, replay=false
- today PnL −$518.58 (will trigger L.5 at 23:50Z)
- M.5 Path-A gate active (lookback=15, min=10, margin=0.02)
- O.1 SURV canary active (lookback=15, min=10, margin=−0.01)
- M.1a v0 shadow active; M.1a v1 DISABLED
- M.2 v0 shadow active
- L.5 daily-PnL auto-halt active (gate=−$90, check=23:50Z UTC)
- J.2 hour-blocklist active (22, 23, 0 UTC × tier 70-85%)
- H.2.12 block_up active (tier 70-85% × UP fires rejected)
- Kelly 0.15× + multi-fire cap=1
- Phase J.1.5 CH3 fold preserved (tier_relax_p_win_fallback=0.0)

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

## Files written / commits this session

- `16e8f38` — Phase N forensic PDF + O.1 SURV canary impl + tests + backtest
- `d3ed2a8` — Phase O vault docs (initial session note + ledger)
- `98940b1` — dashboard bankroll env-honoring fix
- (this file extended in-place with mid-session pivots)

## Open items for Session 2 (next UTC day)

1. J.2 hour-blocklist EXTENSION to tier 30-50% bleed-hours
   {05, 06, 17, 21, 23, 00} UTC. Requires per-tier-hour env-flag
   redesign (current cross-product would block winner cell hour 22 ×
   tier 30-50%).
2. SURV canary observability — operator asked about a "decisions tape"
   showing every window evaluation including abstains/no-signal. Not
   shipped this session. Would need: bot writes `abstained` records to
   JSONL, dashboard loader + tape renders kind="abstained". ~1h work
   (backend) plus React frontend changes.
3. Day-1 re-soak observation (2026-05-18 UTC) — see
   `2026-05-18-phase-O-session-2-prep.md`.
4. N.5 regime classifier validity test (deferred from Phase N PDF §6).
5. (Conditional) Kelly demotion or further M.5 / SURV canary tuning
   based on Day-1 + Day-2 data.
