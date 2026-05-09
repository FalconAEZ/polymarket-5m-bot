# 2026-05-10 — Phase 11.A.2 post-incident: background-settle fix + 3 dashboard bugs

**Session:** continuation of the 2026-05-09 instant-settle queue-overflow incident.
**Branches:** `claude/jovial-hermann-7e103f` (PR #1) + `claude/dashboard-pm-truth-fix-7e103f` (PR #2).
**Pickup:** 2026-05-10 ~22:55 UTC. Closed mid-session at the 30-min instant-settle re-soak gate.
**Operator state:** explicit "don't stop and ask" authorization; full-perms session running auto-resume.

## Headline

The 2026-05-09 instant-settle incident is **fixed in code, deployed, and
soaking clean**. The proper background-settle architecture (snapshot +
fire-and-forget asyncio task, never blocks the main loop) ships at
`43872e9` on PR #1 with a 4-test invariant suite — including the explicit
queue-doesn't-overflow check the postmortem demanded. Stash-the-fix proof
verified the bug catches the original failure (72 records dropped under
600ms gamma sleep + 80-record feed burst → 0 dropped after fix).

Re-deployed instant-settle on the VPS at 23:12:00 UTC. As of 23:30 UTC
(18 min in): 0 queue overflows, 0 gamma timeouts, 0 errors, 3 window
closes processed cleanly with sub-1s gamma roundtrips. The 30-min gate
is on track.

In parallel, the three operator-reported dashboard bugs are addressed:
- 2.2 (orphan-fire recovery) — landed on PR #1 at `0ab9d20` with a
  startup-time gamma-resolve pass + 5 idempotency/kill-switch tests.
  Deploys on the next natural restart per the deploy-deferral feedback.
- 2.1 (decisions tape) + 2.3 (DOWN book empty) — landed on PR #2 at
  `30d6196` after typecheck. 2.3's investigation showed token mapping
  + parser are correct; the empty-DOWN observation was a snapshot-in-time
  low-liquidity event, so the change is a UX badge clarification (LIVE /
  EMPTY / WAIT) rather than a data fix.

## What shipped this session

### PR #1 (`claude/jovial-hermann-7e103f`)

**`43872e9` — fix(paper): background-settle architecture**

- New `_SettleSnapshot` dataclass captures `window_ts, decision_id,
  open_oracle, close_oracle, side, settled_fill` at boundary crossing
  BEFORE `_state.start_window` resets state for the next window.
- `_maybe_emit_boundaries` now schedules `_settle_window_background`
  via `asyncio.create_task`, tracks tasks in `self._pending_settles`,
  and returns immediately. Main loop is back to `queue.get()` within
  microseconds of the boundary.
- `_settle_window_background` wraps `_do_settle` in a top-level
  try/except so a settle exception (gamma raise, log raise, etc.) is
  logged + alerted but never propagates to the main loop.
- `run()`'s finally block awaits all pending settles before closing
  the decision log so settled records aren't lost on shutdown.
- 4 new tests in `tests/paper/test_runner_settle_background.py`:
  - `test_main_loop_processes_records_during_slow_settle` — the
    queue-doesn't-overflow check from `feedback_test_under_load.md`.
    Drops==0 with the fix; Drops==72 with the fix stashed.
  - `test_settle_task_failure_doesnt_kill_runner` — RuntimeError from
    record_settled is caught; runner survives; next window settles.
  - `test_shutdown_awaits_in_flight_settles` — early stop signal during
    slow gamma; settled record still lands before run() returns.
  - `test_settle_uses_snapshot_not_live_state` — W2 oracle mutation
    during W1 in-flight settle does not corrupt W1's record.

`make verify` green: ruff clean, mypy --strict 59 src files, **373 tests
pass** (was 369 — +4 background-settle).

**`0ab9d20` — feat(paper): startup-time orphan-fire recovery**

Fixes the 2026-05-09 21:10 UTC orphan (window 1778361000 fired but never
got a settled record because the bot was restarted between fire and
window-close). New `_recover_orphan_fires` runs at startup:

- Reads today + previous N UTC-day decision-log JSONLs.
- Builds set of decision_ids with matching `settled` records.
- For each `fired` without a settled match AND whose closing window is
  past (`active_window_ts > orphan.window_ts`), polls Polymarket Gamma
  via `asyncio.to_thread`.
- On UP/DOWN truth: writes a synthetic settled record marked
  `resolution_source="polymarket-recovery"`. On still-pending: leaves
  the orphan for the next startup to retry.
- Idempotent (filtered by decision_id), bounded (recent days only),
  defensive (gamma raise / malformed fill / missing client all
  log+alert+skip rather than abort).
- Plumbed through `scripts/run_paper.py` as `ORPHAN_RECOVERY_ENABLED`
  (default true) per the kill-switch convention.
- 5 tests in `tests/paper/test_runner_orphan_recovery.py`:
  recovery happens, idempotent, kill-switch suppresses, future-window
  skipped, no-gamma-client safe-skip.

`make verify` green: **378 tests pass** (was 373 — +5 orphan recovery).

### PR #2 (`claude/dashboard-pm-truth-fix-7e103f`)

**`30d6196` — fix(dashboard-v3): tape entry animation + EMPTY market badge**

- `DecisionsTape.tsx` — removed `y: -8` from new-row entry animation.
  The translate moved the row UP into the sticky `<thead>` region; the
  `<motion.tr>`'s implicit transform creates a new stacking context at
  z-auto BELOW the thead's `z-10`, so on Safari the row sometimes
  settled with the top partially clipped. Fade-only entry (opacity +
  scaleY) keeps the row at its destination position.
- `CTFBookPanel.tsx` — distinguish "fetched OK but market has zero
  depth" from "still resolving token IDs":
  - LIVE → slug present AND at least one side has depth
  - EMPTY → slug present but BOTH sides empty
  - WAIT → no slug yet
- Investigation (curled gamma + CLOB from VPS): `outcomes: ["Up","Down"]`
  with `clobTokenIds[0]==UP, [1]==DOWN`; current DOWN book has 32 asks
  + 30 bids (mirror of UP). The 22:35 UTC empty-DOWN report was a
  genuine low-liquidity snapshot, not a fetch/parse bug.
- `tsc --noEmit` clean.

## Deploys

**23:12:00 UTC** — re-enabled `INSTANT_SETTLE_ENABLED=1` on
bot-staging.service after pulling `43872e9` (background-settle fix).
.envrc backed up to `.envrc.bak.1778368293`. Bot restarted cleanly:

> `instant-settle ENABLED: gamma poll timeout=30.0s interval=1.0s`
> `paper-mode runtime up; waiting for SIGTERM/SIGINT or halt sentinel`

Previous shutdown was clean (`shutdown complete; dropped_records=0`).

**Soak as of 23:30 UTC (18 min):** 0 queue overflows, 0 gamma
timeouts, 0 CRITICAL/Traceback/Exception, 0 background-settle task
failures. 3 window closes (23:15, 23:20, 23:25) — gamma roundtrips
all sub-1s.

**Soak final at 23:45:47 UTC (33 min): PASSED.** 0 queue overflows,
0 CRITICAL/Traceback/Exception, 0 settle-task failures, 0 redis
alert backlog, 0 redis DLQ. There WAS exactly 1 gamma timeout at
23:35:30 UTC for window 1778369400 — and the architecture handled
it exactly as designed: the 30s gamma poll ran on a background
task, the main loop never blocked, the chainlink-local fallback
fired cleanly, and ZERO records dropped. This is the precise
failure mode that caused the 22:20 UTC incident; under the new
architecture it's a non-event. Item 3 marked ✓.

## Deferred

- **Orphan-recovery code (`0ab9d20`)** is pushed but NOT yet deployed
  — per `feedback_defer_deploys_to_natural_restart.md`, the next
  natural restart picks it up. Until then, the existing 21:10 UTC
  orphan stays orphan. Operator may choose to deploy when convenient.
- **PR #2 dashboard fixes (`30d6196`)** require a frontend rebuild to
  take effect. If the VPS dashboard runs the built `dist/` bundle,
  operator runs the prod build script + reload before the fixes are
  visible.
- **48h gate review** at 2026-05-10 22:26:15 UTC was already in
  progress at session pickup; this session did not act on it.
- **Items 4 (v2 soak monitoring) + 5 (regime detector validation)**
  from the prompt were deferred — Item 1 + 2 took the full session.

## Anti-vibe checks

- **Bug → failing test → fix → green (#2):** explicitly demonstrated
  for Item 1 — stash the runner fix, run the new test, see 72 records
  drop, restore, see 0 drop.
- **Test runtime behavior under load (the lesson from
  `feedback_test_under_load.md`):** the queue-doesn't-overflow test
  is the explicit guard against the original incident.
- **Always ship a kill-switch env var:** orphan-recovery has
  `ORPHAN_RECOVERY_ENABLED`; instant-settle still has
  `INSTANT_SETTLE_ENABLED`.
- **Defer bot-affecting deploys to natural restart points:** orphan-
  recovery commit pushed but NOT deployed mid-instant-settle-soak.

## Next session

`phase-prompts/phase-11.a.2-post-soak-2026-05-11.txt` (to be written by
operator or this session if context allows). Likely items:
1. Confirm 30-min instant-settle re-soak passed (or roll back).
2. Decide whether to merge PR #1 + PR #2 to main.
3. Restart bot to deploy orphan-recovery; verify the existing 21:10
   UTC orphan gets a `polymarket-recovery` synthesized settle.
4. Item 4 — daily v2 soak rollup; check fire cadence + per-tier PnL.
5. Phase 11.A.2 48h gate review (target was 2026-05-10 22:26:15 UTC).

## Anthropic spend

$0 this session — no LLM calls. Cumulative still $0.405 (Phase 3 only).
