# 2026-05-10 — Phase 5 settle-resolution bug session

**Closed at:** ~2026-05-10 05:30 UTC
**Branch / HEAD:** `claude/jovial-hermann-7e103f` @ `6464541` (also `claude/youthful-margulis-964d00`)
**Bot status at close:** active on VPS, restarted 05:24:54 UTC, instant-settle SUCCESS confirmed live

## What we set out to do

Per `phase-prompts/phase-5-settle-resolution-bug-2026-05-11.txt`:

* Item 1 — verify dashboard's resolver_loop actually corrects wrong JSONL records.
* Item 2 — extend gamma instant-settle timeout 30s → 5min.
* Item 3 — implement post-hoc gamma re-resolution background task.
* Item 4 — backfill the 7 wrong settles + recompute today's stats.
* Items 5-6 — re-evaluate Phase 5 ensemble on CLEAN data.

Operator also flagged mid-session: two trades with phantom $449.54 PnLs (windows 1778388600 + 1778389500). Address before closeout.

## What shipped

Two commits on `claude/jovial-hermann-7e103f` (FF-pushed; bot deployed):

### `28c01cf fix(settle): post-hoc gamma re-resolution + bump instant-settle defaults`

* `DEFAULT_INSTANT_SETTLE_TIMEOUT_S: 30s → 300s` (the core bug — 0/22 instant-settles succeeded with 30s; gamma typically takes 1-3 min to flip closed=true).
* `DEFAULT_INSTANT_SETTLE_INTERVAL_S: 1s → 5s` (reduces gamma load + sidesteps CDN-cache hypothesis).
* `DecisionLog.record_settled_correction()` — new `kind: settled_correction` schema (preserves the original `settled` for audit history).
* `PaperRunner._post_hoc_gamma_retry()` — fire-and-forget background task scheduled after every chainlink-local-fallback. Default: wait 5 min, poll gamma every 30s for up to 25 min total. Tracked in `_pending_post_hoc_retries`; shutdown awaits the set so corrections don't get lost on stop.
* `POST_HOC_GAMMA_RETRY_ENABLED` env (default true) is the kill-switch.
* 6 new tests in `tests/paper/test_runner_post_hoc_retry.py`:
  1. Correction fires when chainlink and gamma disagree
  2. No correction when they agree
  3. Graceful give-up when gamma never resolves
  4. Kill-switch off skips the retry path entirely
  5. Queue-doesn't-overflow under feed burst (the explicit lesson from `feedback_test_under_load.md`, applied to this new task class)
  6. Shutdown awaits in-flight retries
* `scripts/backfill_settled_corrections.py` — one-shot CLI that scans for chainlink-fallback settles without an existing correction, calls gamma, and appends settled_correction records for the disagreements. Idempotent. Applied to today's JSONL: **7 corrections, net delta -$6.3428** (matches the audit script EXACTLY).

### `6464541 fix(simulator): refuse fill at price floor when ask depth unknown + neutralize 2 phantom wins`

* `FillSimulator` taker path refuses fills when `best_ask <= DEFAULT_FLOOR_BEST_ASK (0.02)` AND `ask_size_top is None`.
* Root cause: WS `best_bid_ask` and `price_change` events don't carry depth — the simulator was filling $5 at the $0.01 floor, producing 454.5 shares and phantom 90:1 wins.
* 3 new tests: refuses at floor w/o depth; allows at floor with known depth (impact model still runs); allows above floor regardless.
* `scripts/backfill_phantom_floor_fills.py` — neutralized both phantom wins via settled_correction with `corrected_pnl_usd=0.0`, `phantom_fill: true`, `resolution_source: phantom-fill-neutralized`. Aggregate delta: **-$899.09**.

## Verification (live, post-restart)

| Check                              | Result |
|------------------------------------|--------|
| `systemctl is-active`              | active |
| Redis `llm:queue` / `llm:results`  | 0 / 0 (no overflow regression) |
| First post-restart settle source   | **`polymarket`** (window 1778390400, +$5.394) — FIRST instant-settle success since the 30s/1s era |
| Journal: gamma poll cadence        | 5s interval, no errors |
| `make verify`                      | 438 tests pass; mypy strict src clean; ruff clean |
| Dashboard `/api/state`             | `decisions_truth_source: polymarket`, window 1778387400 shows `+$0.487 won=true` (gamma truth, not chainlink's -$5) |
| Re-running backfill (idempotency)  | 0 new corrections, 19 agreed, 1 unresolved |

## Item 1 — no code change required

Operator's concern was that the dashboard was showing wrong PnL because `resolver_loop` wasn't running. Verified instead:

* `dashboard-server.log`: `resolver pass: 63 settled records re-resolved (changed)` every 5 minutes since 05:07:35.
* `state/decisions-resolved/2026-05-10.jsonl` has corrected records with `resolution_source: polymarket` overlaying chainlink truth.
* `/api/state` reports `decisions_truth_source: polymarket` and the dashboard view of the prompt's example window 1778387400 shows `+$0.487 won=true` (gamma) instead of `-$5` (chainlink).
* Resolver_loop IS doing its job. Item 1 closed without code change.

## Known followups (NOT done this session)

1. **Dashboard's resolver_loop doesn't honor `settled_correction` records.** It does its own parallel gamma re-resolution into `decisions-resolved/`. So the PHANTOM-FILL neutralizations (windows 1778388600 + 1778389500 showing `pnl=0` in the bot's JSONL) are still shown as `+$449` each in the dashboard view. Fix: either (a) read settled_correction records and apply them on top, or (b) detect `phantom_fill: true` and force pnl=0. **This is what the operator will see in the dashboard until fixed.**
2. **`/tmp/audit_resolutions_v2.py`** (uncommitted on VPS) doesn't honor settled_correction records — re-running it after the backfill still reports the same 7 mismatches. Update needed.
3. **Pre-restart settles already on disk** don't get a post-hoc retry on subsequent restarts (orphan recovery only handles `fired` records without `settled`). The dashboard's resolver_loop covers the dashboard view; downstream consumers reading raw `decisions/` need the backfill script. Acceptable: it's a one-time gap.
4. **`ensemble_shadow_rollup`** uses laptop's `state/staging/decisions/` which is gamma-corrected by `sync_staging.sh` + `resolve_decisions.py`. The 2 phantom wins WILL show as wide-fire wins unless the rollup also filters `phantom_fill=true`.
5. **WS depth plumbing** is the root cause of the phantom-fill bug. The simulator's defensive guard works around it, but a proper fix would track top-depth across `best_bid_ask` and `price_change` events.

## Items 5-6 — Phase 5 ensemble decision

Per the prompt: needs n ≥ 30 settled trades on clean data; today only has 24 settled. Defer to next session after another 24-48h of shadow soak. **No promote/revert decision made this session.**

## Anti-vibe rule compliance

* Bug → failing test → fix → green: ✅ (6 + 3 = 9 new tests, all green; the queue-doesn't-overflow test for the new task class explicitly mirrors `feedback_test_under_load.md`).
* Kill-switch env var: ✅ `POST_HOC_GAMMA_RETRY_ENABLED`.
* Defer bot-affecting deploys: ✅ bundled all changes into ONE restart at 05:24:54 UTC.
* No TODO/FIXME in src/scripts/tests: ✅ pre-commit hook green.
* `make verify` green before commit: ✅ ruff + mypy strict + 438 tests.

## Hand-off signature

This session closed at HEAD `6464541` on `claude/jovial-hermann-7e103f`. Pushed to GitHub. Bot active in shadow mode at the new code. Bullish: the data integrity issues that contaminated all WR/PnL metrics are now fixed forward AND backward. Bearish: the dashboard view still shows the 2 phantom $449 wins until followup #1 lands. The operator needs to know that "dashboard total PnL" today is overstated by ~$899 vs the corrected JSONL truth.
