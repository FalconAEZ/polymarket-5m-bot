---
title: Phase F — Final-stage architecture audit (Items 1 + 2 EXECUTED)
date: 2026-05-12
phase: F
status: items-1-2-shipped-soak-underway
---

# Phase F — Architecture audit cut: ensemble + wide_fire → spot_aware_v3

Executed under auto-resume per operator directive ("execute - you have auto resume on"). Drove the Phase F prompt's Items 1 + 2 in sequence; stopped at the +5min sign-off gate per prompt §"OPERATOR SIGN-OFF GATE: post the +5min check. Wait for 'go' before Item 3."

## Item 1 — Operator sign-off (interpreted from auto-resume directive)

The prompt's KEEP/REMOVE/SIMPLIFY recommendation accepted as-is. Operator did not override any specific calls (no parallel A/B requested, no extended-audit window requested). Cut executed verbatim against the prompt's `From → To` env block.

## Item 2 — Strategy cut + deploy

### Code change (commit `d1510bd`, pushed to `claude/jovial-hermann-7e103f`)

`scripts/run_paper.py:66-72` — `DEFAULT_STRATEGY_NAME` flipped `spot_aware` → `spot_aware_v3`. Module-level comment block updated to reference the 5-day audit data and the regime-classifier validation evidence. Lint passed (`uv run ruff check`). 18 spot_aware_v3 + regime detector tests green.

No other code touched. Ensemble + wide_fire + router code remain in the dispatch as research artifacts — rollback path is `STRATEGY=ensemble + ENSEMBLE_MODE=gate + ENSEMBLE_BASE_STRATEGY=wide_fire` re-engaged via env flip.

### VPS .envrc edits (in-place via `sed`; backup at `.envrc.phase-F-backup-20260512-122500`)

4 surgical changes applied with `# PHASE-F 2026-05-13` markers (rollback = uncomment 4 lines, comment 1):

| Line | From | To |
|------|------|-----|
| 29 | `export STRATEGY=ensemble` | `# export STRATEGY=ensemble` (commented; new line: `export STRATEGY=spot_aware_v3`) |
| 30 | `export ENSEMBLE_MODE=gate` | commented |
| 34 | `export ENSEMBLE_BASE_STRATEGY=wide_fire` | commented |
| 53 | `export EVERY_WINDOW_SHADOW=true` | commented |

Kept untouched: `ANTHROPIC_API_KEY`, `ANTHROPIC_DAILY_BUDGET_USD=10`, `TIER_GATE_ENABLED=false`, `REGIME_GATE_ENABLED=false`, `INSTANT_SETTLE_ENABLED=1`, `POST_HOC_GAMMA_RETRY_ENABLED=1`, `SPOT_AWARE_EV_MIN_DOLLARS=0.003`.

**Flag for operator review: `SPOT_AWARE_EV_MIN_DOLLARS=0.003` is still set.** It was added 2026-05-10 for the wide_fire shadow ("# reverted 2026-05-10 for Phase 5 wide-fire shadow"). It overrides v3's default 0.5¢ floor → 0.3¢. The Phase F prompt's `From → To` block did not name this var; followed prompt verbatim and left it set. Regime-classifier validation evidence (trending WR 70.59%) was collected on v3 defaults — running with EV_min=0.003 is a small but real divergence. Operator should decide at +30min whether to comment this out too.

### Deploy (one restart, intentional, per `feedback_defer_deploys_to_natural_restart`)

- Pre-deploy VPS HEAD: `7a5b19e`
- `git pull --ff-only origin claude/jovial-hermann-7e103f` → fast-forwarded to `d1510bd` (3 commits: `be35c76` Phase 19 design lock + `e4feb49` Phase F prompt + `d1510bd` default flip)
- Verified `DEFAULT_STRATEGY_NAME = "spot_aware_v3"` in pulled code
- `DEPLOY_TS_UNIX=1778588728` (= 2026-05-12 12:25:28 UTC) via `date +%s` on VPS, per `feedback_vps_timestamp_arithmetic`
- `sudo systemctl restart bot-staging.service`
- MainPID `570290 → 581764`, NRestarts=0, ActiveEnterTimestamp `Tue 2026-05-12 12:25:33 UTC`
- bot-staging + dashboard-server both `active`

### Pre-deploy 5-day audit (from Phase F prompt, truth-corrected)

```
date         fires  filled  fillR  WR     true_pnl   strategy
2026-05-08      39      23    59%   35.7%   -20.24    spot_aware aggressive
2026-05-09     262     262   100%   52.1%   +44.51    spot_aware aggressive  ← best real day
2026-05-10     184     102    55%   52.4%   +46.34    spot_aware_v2 tier-restricted
2026-05-11      85      42    49%   43.9%   -33.69    wide_fire + ensemble gate
2026-05-12      39      21    54%   38.1%   -37.57    wide_fire + ensemble gate
                                            ────────
                                              -0.65   TOTAL (5 days)
```

The +4.1pp shadow uplift Phase 5 measured did not reproduce in gate mode. Per-trade PnL flipped from +$0.17 / +$0.25 (spot_aware family) to −$0.40 / −$0.96 (ensemble gate). The empirical case for `ENSEMBLE_MODE=gate` is gone.

### Pre-deploy baseline (`/api/state` 12:22 UTC)

- `n_decisions_total = 611`
- Net win-rate (trip wire): 51.23%
- 24h fire rate: 0/d (low-fire stretch)
- 24h PnL trip wire: $+0.00
- Elapsed since gate review: 87.2h
- Incidents: 0
- `halt_requested: false`

## +5min check — RESULTS (captured 2026-05-12 12:30:01 UTC, +4:33 since deploy)

### Service status (GREEN)

- bot-staging.service `active / running`, MainPID 581764, NRestarts=0
- dashboard-server.service `active`
- ActiveEnterTimestamp `Tue 2026-05-12 12:25:33 UTC` (matches deploy timestamp captured pre-restart)

### Error check (GREEN)

`journalctl -u bot-staging.service --since "@1778588728" -p err` → `-- No entries --`. Zero error-level log records since deploy.

### Strategy confirmation (GREEN)

Startup log captures the cut taking effect at the runtime level:

```
2026-05-12 12:25:34 WARNING spot_aware_v3 overrides: {'ev_min_dollars_per_share': 0.003}
2026-05-12 12:25:34 INFO regime detector: 5m=300s / 10m=600s thresholds trending>1.2 chop<0.8
2026-05-12 12:25:34 INFO active strategy: spot_aware_v3
2026-05-12 12:25:34 INFO instant-settle ENABLED: gamma poll timeout=300.0s interval=5.0s
2026-05-12 12:25:34 INFO orphan-fire recovery ENABLED at startup
2026-05-12 12:25:34 INFO periodic orphan-recovery ENABLED: interval=300.0s
2026-05-12 12:25:34 INFO post-hoc gamma retry ENABLED
```

- `active strategy: spot_aware_v3` ✅
- All Phase 11.A + Phase 15.5 defense layers report ENABLED ✅
- Regime detector thresholds at defaults (trending > 1.2, chop < 0.8) ✅
- **Confirms the SPOT_AWARE_EV_MIN_DOLLARS=0.003 divergence I flagged** — `v3 overrides: {'ev_min_dollars_per_share': 0.003}` warning logged. Operator decision needed at +30min on whether to tighten to v3 default (0.005).

### Decision-log freshness (GREEN — within expected behavior)

`state/decisions/2026-05-12.jsonl` last entries: 14 fired + 15 settled + 1 settled_correction in the last 30, all from pre-cut (`rationale=strategy=wide_fire mode=ensemble_base`, timestamps ≤ 12:23 UTC). No new entries between 12:25:34 (deploy) and 12:30:01 (check) — expected: v3 is the most selective strategy (regime-classifier validation: ~6% of windows trending). First v3-tagged FIRE will appear when a trending window opens. Compare to ensemble+wide_fire which logged FIRE on essentially every window (262/day on May 9). The volume drop is the WHOLE POINT of the cut.

### Pre-cut soak hangover

The pre-cut process (PID 570290, 11:31:51–12:25:28 UTC) logged at shutdown: `dropped_records=22117`. Consistent with the deep-dive audit (`state/sessions/2026-05-12-deep-dive-audit.md`) finding 119,722 dropped records over the 5.5h pre-audit soak — gate-mode inline LLM await blocked the runner from draining the feed queue. **This dropped-records counter should go to ~0 under spot_aware_v3** since there is no inline LLM await on the hot path. Monitor at +30min and +24h.

### Items 2 — DONE. Session boundary (b) reached.

Next action: defer Phase F.3 soak audit to next session at +48h (= 2026-05-14 ~12:25 UTC). Draft `phase-prompts/phase-F-3-spot-aware-v3-soak-audit-2026-05-14.txt` before stopping the next session.

## What did NOT happen this session (per prompt §"WHAT THIS PHASE EXPLICITLY DOES NOT DO")

- No code deletions. Ensemble + wide_fire + router code intact; reachable via env flip.
- No locked-decision changes. Decisions #4 / #5 / #6 / #9 / #10 all stand.
- No phantom-fill defense changes (Phase 11.A intact).
- No `meta_outcome` telemetry changes (Phase 18B intact — but will be empty post-cut since no ensemble fires).
- No regime-detector code changes (it's now PROMOTED to production filter inside v3).
- No `EVERY_WINDOW_MODE=true` flip. Router code stays in repo; shadow soak paused via env.
- No Phase 19 implementation. Design doc stays as research artifact.
- No litestream / alerter / halt-sentinel / systemd touches.

## Phase status updates after this session

- **Phase 16.B** → **PAUSED** for promotion. Router code + design intact; `EVERY_WINDOW_SHADOW=true` flipped to commented. If we ever return to it, redesign as a no-LLM router (W_DET=0.30, W_REG=0.30, W_TIER=0.20, W_KELLY=0.20) — see prompt §"SIMPLIFY".
- **Phase 19** → **SHELVED**. Design doc complete but implementation deferred indefinitely. The 12s inline-await latency problem disappears when the LLM is removed from the fire path.

## Soak parameters (Phase F.3, next session at +48h)

Per prompt §"ITEM 3 — Verification window: 48-72h spot_aware_v3 soak":

PROMOTE criteria (Phase F.3 → F.4):
- `rolling_wr_at_72h >= 0.52`
- `daily_pnl_min >= -10.0`
- `fires_per_day >= 50` (else too selective)
- `queue_overflow_incidents == 0` (predicted true; gate is removed)

ROLLBACK criteria:
- WR < 0.45 over 48h
- OR daily_pnl < −30 on any day
- OR fires_per_day < 20 (gated too tight)

Daily check command: `uv run python -u scripts/four_day_audit.py` (or whatever the prompt-referenced script is — confirm name at next session).

## Session boundary hit

(b) Items 1-2 complete (cut deployed); soak underway → defer Phase F.3 audit to next session at +48h. ✅ **partial**.

Next session prompt: `phase-prompts/phase-F-3-spot-aware-v3-soak-audit-2026-05-14.txt` (drafted at +48h).
