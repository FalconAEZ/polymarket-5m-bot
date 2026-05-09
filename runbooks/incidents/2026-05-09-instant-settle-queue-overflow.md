# Incident: instant-settle gamma poll caused paper-runner queue overflow (2026-05-09 22:20 UTC)

**Severity**: HIGH (~1h of decision data lost; ~4,600+ market events
dropped; operator paged via Telegram at 2:20 AM local).

**Discovered**: 2026-05-09 ~22:24 UTC by operator after returning to
their laptop and seeing a cascade of WARN alerts in Telegram.

**Root cause introduced**: 2026-05-09 21:13:50 UTC by my deploy of v2
+ instant-settle (`ad26a7c` runtime + `7e6b73f` Phase 3+4 deliverables).

**Mitigation**: 2026-05-09 22:25:05 UTC — disabled
`INSTANT_SETTLE_ENABLED` in VPS .envrc; restarted bot-staging.service.
Bot back to normal (v2 strategy preserved; Chainlink-only settle path
restored). 0 queue overflow alerts since restart. Redis alert queues
empty.

## Timeline

| UTC | Event |
|---|---|
| 21:13:50 | Deploy: bot restarted with `STRATEGY=spot_aware_v2` + `INSTANT_SETTLE_ENABLED=1` |
| 21:13:51 - 22:14:59 | Bot operating normally; v2 hadn't fired yet (v2 is much pickier than v1) |
| ~22:15:00 | Window 1778364900 closed; v2 had a fired decision in this window (first v2 fire post-deploy) |
| 22:20:00 | Boundary crossing → `_settle_current_window` called; gamma poll started |
| 22:20:00 → 22:20:30 | Gamma polled every 1s, returned 200 OK but no resolution (Polymarket hadn't yet marked market closed) |
| 22:20:30 | Gamma timeout (30s) → fallback to chainlink-local resolution → settle complete → alert: "instant-settle gamma timeout #1" |
| 22:20:00 → 22:20:30 (concurrently) | Main runner loop blocked in `await self._on_record(record)` → couldn't pull from queue → upstream feeds (binance/coinbase/oracle/polymarket pumps) overflowed the 1024-slot queue → drop-oldest cycled ~4,600+ records |
| 22:20:00 → 22:20:30 | Cascade of WARN alerts: dropped=1, 100, 200, 300, ..., 4600 (one alert per 100 dropped per the existing alert dedup logic) |
| 22:24 | Operator returns to laptop, sees the cascade, asks me what's wrong |
| 22:25:05 | I disabled `INSTANT_SETTLE_ENABLED` in .envrc + restarted bot-staging.service |
| 22:25:05+ | 0 new overflow alerts; bot operating normally on v2 + chainlink-local-only settle |

## Root cause

The instant-settle implementation called `await asyncio.to_thread(poll_gamma_for_resolution, ...)` from inside `_settle_current_window`, which is called from the main runner loop's `await self._on_record(record)` chain.

I documented in the code (and patted myself on the back for catching it in code review):

> "CRITICAL: poll_gamma_for_resolution is synchronous (sleep+http). It MUST be wrapped in asyncio.to_thread so the runner's event loop keeps processing incoming market events for the NEXT window while we wait for Gamma."

**That comment was technically right but practically wrong.** `asyncio.to_thread` releases the event loop for OTHER coroutines (the upstream pump tasks, the warmer, the halt-watcher). It does NOT help the SEQUENTIAL processing in the main loop. The main loop is single-tasked through `await queue.get() ; await self._on_record(record)` — it cannot pull more records while ANY single record is being processed.

So while gamma polled for 30 seconds:
- Pump tasks kept putting feed records in the queue (event loop free for them)
- Main loop was stuck awaiting the gamma poll's return
- Queue filled past 1024 → drop-oldest policy cycled records out

Worse: the bot fires v2 decisions ~1/day (per the fire-rate model in
`runbooks/research/edge-discovery-2026-05-09.md`). EVERY v2 fire would
trigger this 30s block on the next window boundary. Predictable and
recurrent.

## Why I didn't catch this in tests

Tests use `instant_settle_timeout_s=2.0` (`tests/paper/test_runner_instant_settle.py:215`)
and `instant_settle_interval_s=0.1`. With a `MockTransport` that returns
no resolution immediately, the timeout fires fast and the test passes.
But the test doesn't simulate concurrent feed traffic during the
settle await, so it never exercises the queue overflow scenario.

**The test mocked the wrong thing.** I tested the gamma-resolver behavior
(does it timeout? does the fallback fire? does resolution_source land?)
but NOT the runtime behavior (does the main loop stay responsive while
settle is in progress?).

## What WORKS in the current state

- Bot is running on v2 strategy (preserved through the mitigation)
- Chainlink-local settle (legacy, sync, fast) is functioning
- Decision logging works
- Dashboard's resolver_loop continues to provide PM-truth correction
  post-hoc (the dashboard fix from PR #2 wasn't affected)

## What's BROKEN until proper fix lands

- **Instant-settle is disabled** — settle latency back to ~60s (Chainlink heartbeat)
- **The CONCEPT is sound** but the implementation needs to use
  fire-and-forget background tasks instead of `await` in the main loop

## Proper fix (next session)

Schedule settle as a fire-and-forget background task instead of awaiting
inline. Sketch:

```python
class PaperRunner:
    def __init__(self, ...):
        ...
        self._pending_settles: set[asyncio.Task[None]] = set()

    async def _maybe_emit_boundaries(self, ts_ns: int) -> None:
        ...
        if new_window_ts != current:
            await self._strategy.on_event(WindowBoundary(...kind=close...))
            # Snapshot state for the closing window BEFORE start_window resets it
            snap = self._snapshot_for_settle()
            # Fire-and-forget — main loop continues immediately
            task = asyncio.create_task(
                self._settle_window_background(snap),
                name=f"settle-{snap.window_ts}",
            )
            self._pending_settles.add(task)
            task.add_done_callback(self._pending_settles.discard)
            self._state.start_window(new_window_ts)
            ...

    async def _settle_window_background(self, snap: SettleSnapshot) -> None:
        try:
            # Gamma poll + chainlink fallback + log.record_settled
            # Same logic as old _settle_current_window but reads from snap
            # and writes via try/except to never propagate errors
            ...
        except Exception as exc:
            LOG.exception("settle background task failed: %s", exc)
            self._alert(Level.CRITICAL, f"settle task failed: {exc}",
                        decision_id=snap.decision_id)

    async def run(self, ...) -> None:
        try:
            ...
        finally:
            # Wait for in-flight settle tasks before closing log
            if self._pending_settles:
                LOG.info("awaiting %d in-flight settle tasks", len(self._pending_settles))
                await asyncio.gather(*self._pending_settles, return_exceptions=True)
            self._log.close()
```

Plus tests:
- Test that settle runs in the background (main loop processes more records WHILE settle is in progress)
- Test that shutdown awaits in-flight settles
- Test that a failed settle doesn't kill the runner

Effort: ~1-2h coding + tests. Best done in a fresh session with
operator approval.

## Lessons

1. **Don't use `await` for I/O that can block for ≥1s in a single-tasked
   main loop.** Use `asyncio.create_task` with proper lifecycle management.
2. **Test that the runtime behaves correctly under load**, not just that
   individual functions work. Specifically: when adding async I/O to the
   hot path, write a test that verifies concurrent event processing
   continues during the await.
3. **Code-review comments are not tests.** I documented the concern
   ("the runner's event loop keeps processing incoming market events for
   the NEXT window") and STILL got it wrong because I conflated "event
   loop responsive" with "main loop continues".
4. **30-second timeouts on settle paths are too aggressive.** Even with
   a proper background fix, polling Gamma for 30s on every window boundary
   is wasteful. Better: poll for 5-10s; if Gamma hasn't resolved by then,
   fall back to chainlink-local immediately.
5. **Always include a kill-switch env var for new features.** I had
   `INSTANT_SETTLE_ENABLED` already; the mitigation took 30 seconds
   because of this. Without it, the rollback would have required a
   git checkout + restart (slower).

## Cross-refs

- `design/instant_settlement.md` — the design doc that needs updating
- `src/polymarket_bot/_paper/runner.py::_settle_current_window` — the
  buggy code path
- `tests/paper/test_runner_instant_settle.py` — the tests that didn't
  catch this
- `~/.claude/projects/.../memory/feedback_test_under_load.md` — new
  memory note created from this incident
