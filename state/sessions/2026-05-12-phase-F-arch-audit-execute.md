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

Next action: defer Phase F.3 soak audit to next session at +48h (= 2026-05-14 ~12:25 UTC). F.3 prompt drafted this session at `phase-prompts/phase-F-3-spot-aware-v3-soak-audit-2026-05-14.txt` (commit [ca4336a]).

## +30min check — RESULTS (captured 2026-05-12 12:55:33 UTC, +30:05 since deploy)

### Service status (GREEN)

- bot-staging.service `active`, MainPID 581764, NRestarts=0
- ActiveEnterTimestamp unchanged: `Tue 2026-05-12 12:25:33 UTC` (no silent restarts)
- dashboard-server.service `active`
- `STRATEGY=spot_aware_v3` still set in .envrc (parallel-session-reset guard pass — `feedback_vps_deploy_verify_late`)

### Error check (GREEN)

`journalctl -p err --since "@1778588728"` → `-- No entries --`. Zero error-level records over the full 30-minute window.

### LLM removal verification (GREEN)

- **Anthropic API calls since deploy: 0.** Confirms the LLM is fully removed from the fire path. (Pre-cut: 4 calls in the 9 seconds before shutdown at 12:25:25.)
- No `ensemble_vote` records, no `meta_outcome` records, no `wide_fire` mentions in any post-cut log line.

### Queue overflow verification (GREEN — Phase F prediction holds)

- `dropped_records=22117` line is from the OLD process shutdown at 12:25:33 (pre-cut tally).
- After cut: **zero** `dropped_records` or `queue.*overflow` log entries over 30 min.
- The whole architectural class of queue-overflow incidents (Phase 19's motivation) is gone.

### Runner background loops (GREEN)

| Loop | Cadence | Observed |
|------|---------|----------|
| Warmer | every 5min | 6 successful runs, 1 new window each, token catalog 1526 → 1538 |
| Orphan recovery | every 5min | 6 successful runs, 0 orphans found each |
| Post-hoc gamma retry | per design | (no settled-correction triggers during window) |

### v3 fire activity (within expectation)

- Decision-log `state/decisions/2026-05-12.jsonl`: 86 lines total, **unchanged since 12:23 UTC** (pre-cut last entry).
- 0 post-cut entries (`ts_ns >= 1778588728`).
- 0 v3-tagged FIRE records.
- 41 fires + 42 settled + 3 settled_correction in the file are ALL pre-cut (`rationale=strategy=wide_fire mode=ensemble_base`).

**Is this a bug?** No — verified at `src/polymarket_bot/strategies/spot_aware_v3.py:50-77`:

```python
async def on_event(self, event):
    if isinstance(event, SpotTick):
        self._regime.observe_spot(event.ts_utc_ns, event.price)
    decision = await super().on_event(event)
    if decision is None:
        return None
    regime = self._regime.classify(event.ts_utc_ns)
    if regime != "trending":
        self._fired_for_window = None
        return None
    return decision
```

v3 silently returns `None` on abstain — no log line, no decision-log entry. Only fires produce decisions. So zero log lines from v3 over 30 min == "v3 evaluated, no trending window observed."

**Statistical consistency check:** Bot started 12:25:33; regime detector needs 600s (10 min) buffer. First trainable window: 12:35. Evaluations at 12:35, 12:40, 12:45, 12:50, 12:55 = 5 windows. v3 fires on ~6% of windows that pass v2's earlier gates. P(0 fires in 5 windows at 6% rate) = 0.94⁵ ≈ 0.73. So **73% probability of seeing exactly what we saw**. Within expectation.

### /api/state snapshot

- `n_decisions_total = 611` (unchanged from pre-cut baseline)
- `halt_requested = False`
- `incidents = 0`
- 24h trip wires: PnL $+0.00, fire-rate 0/d, WR 51.2% (still dominated by ensemble+wide_fire history from before the cut), elapsed 87.8h

### What this +30min check does NOT verify

- ❌ First v3-tagged FIRE has not yet appeared. Statistical estimate: probability of >=1 fire in next 24h with v3's ~6% trending rate × ~288 windows/day = 1 - 0.94^288 ≈ ~100%. Very high confidence we'll see at least one fire by tomorrow's +24h check.
- ❌ Win-rate on v3-tagged fires — N/A until fires accumulate.
- ❌ Per-trade PnL on v3 — same.

These are the Phase F.3 questions, which are next-session work.

### +30min verdict

**GREEN on all measurable criteria:**
- Service health, error count, env preservation, LLM removal, queue stability all clean.
- v3 fire-volume is unobservable yet but **statistically consistent** with v3's selectivity profile.

**Next checkpoint: +24h (= 2026-05-13 12:25:33 UTC).** Per `feedback_vps_deploy_verify_late`. Look for first v3 fires + early WR signal.

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
