# Incident: ensemble LLM call caused paper-runner queue overflow (2026-05-10 04:20 UTC)

**Severity**: HIGH (~30 min of bot data lost; **16,223 market events
dropped**; operator paged via Telegram).

**Discovered**: 2026-05-10 ~04:20 UTC by operator after Telegram alert
"warn [bot-staging] paper-runner queue overflow; dropped=16100".

**Root cause introduced**: 2026-05-10 03:51:42 UTC by my deploy of the
ensemble in shadow mode (`STRATEGY=ensemble`, `ENSEMBLE_MODE=shadow`,
base=wide_fire). Specifically commit `2576c72` — fully wired Phase 5
LLM ensemble.

**Mitigation**: 2026-05-10 04:24:02 UTC. Reverted `STRATEGY=ensemble →
spot_aware_v2`, commented out `ENSEMBLE_MODE=shadow`, restarted
bot-staging.service. Bot back to v2-tight (validated, no LLM calls).
0 queue overflow alerts since restart.

## Timeline

| UTC | Event |
|---|---|
| 03:33:40 | Bot restarted with `STRATEGY=ensemble`, `ENSEMBLE_MODE=shadow`, base=spot_aware_v2 — 2 fires, 2 LLM votes, low fire rate, no overflow |
| 03:51:42 | Bot restarted with base=wide_fire (operator's directive: max volume) |
| 03:55:00 → 04:20 | wide_fire fired ~1-2 times per 5m window (much higher cadence than v2-tight) |
| 04:00 onwards | Each fire blocked main runner loop for ~1.5s while LLM ensemble (3 specialists + meta) ran inline |
| 04:10 - 04:20 | Queue accumulated dropped records; alert fired at dropped=100, 200, ..., 16,100 |
| 04:20:00 | Operator alerted via Telegram |
| 04:24:02 | I disabled ensemble in `.envrc`, restarted bot-staging. dropped_records final = 16,223 |

## Root cause

Same architectural bug class as the 2026-05-09 instant-settle queue
overflow incident. The runner's main consumer loop is single-tasked:

```python
while active > 0:
    record = await queue.get()
    await self._on_record(record)  # ← anything inside this await blocks queue.get()
```

The path inside `_on_record` for each event:
1. `decode_record(record)` (sync, fast)
2. `await self._on_event(event)` for each decoded event
3. Inside `_on_event` → `await self._strategy.on_event(event)`
4. With `STRATEGY=ensemble`, the strategy is `EnsembleWrapper`
5. `EnsembleWrapper.on_event` ran `await self._run_ensemble(ctx)` INLINE
6. `_run_ensemble` does:
   - `asyncio.gather(*specialists)` — 3 Haiku calls in parallel (~500ms)
   - then `await self._meta.decide(...)` — Sonnet call, sequential after
     specialists (~1000ms)
7. Total inline await: ~1.5s per fire

While that 1.5s elapsed, the main loop could not call `queue.get()`
again. Pump tasks (binance, coinbase, oracle, polymarket) kept putting
records into the bounded 1024-slot queue. Queue filled, `drop-oldest`
policy cycled records out. wide_fire's high fire rate (1+ per window
× 5 min × 12 windows/hour = many fires per hour) compounded the
problem. By 04:20 UTC, 16,223 records had been dropped.

## Why I didn't catch this in tests (the second time)

The 2026-05-09 instant-settle incident produced
`feedback_test_under_load.md`:

> **Heuristic flag**: any `await` on I/O that can take >1s inside a
> single-tasked main loop = needs a "queue-doesn't-overflow" test.

I followed this for the gamma-poll path (background-settle fix has the
explicit test). I **did not apply it to the ensemble**. When I added
`await self._run_ensemble(ctx)` to `EnsembleWrapper.on_event`, I should
have flagged it as exactly the same pattern: long async I/O on the
main loop's path. I didn't, the test wasn't written, the bug shipped.

The fix this incident produces:
`tests/strategies/test_ensemble_wrapper.py::test_shadow_mode_does_not_block_main_loop_under_slow_llm`
asserts `on_event` returns in <200ms even when specialists+meta have
1.5s of simulated latency. This is the same pattern as
`test_main_loop_processes_records_during_slow_settle` in
`tests/paper/test_runner_settle_background.py`.

**Both tests exist now.** The lesson is: when adding ANY async I/O to
the runner's main loop chain, write the queue-doesn't-block test BEFORE
shipping.

## What WORKED in the current state (post-mitigation)

- v2-tight strategy on bot-staging (validated, performant)
- Background-settle architecture (the original fix from 2026-05-09)
- Orphan-fire recovery
- Cross-restart double-fire guard (also shipped today)
- Decision logging
- Dashboard

## What's BROKEN (until the proper fix re-enables ensemble)

- Phase 5 LLM ensemble is OFF in production (re-enable requires the
  fix in this commit + careful redeployment)

## Proper fix (this commit)

Convert shadow-mode LLM call to fire-and-forget background task —
exactly the same architectural pattern as background-settle. Sketch:

```python
async def on_event(self, event):
    # ...
    if self._mode == "shadow":
        self._spawn_shadow_vote(ctx, candidate, event_ts_ns)
        return candidate  # main loop returns IMMEDIATELY
    # gate mode — inline await as before
    votes, meta = await self._run_ensemble(ctx)
    # ...

def _spawn_shadow_vote(self, *, ctx, candidate, event_ts_ns):
    task = asyncio.create_task(
        self._run_shadow_vote_task(ctx=ctx, ...),
        name=f"ensemble-shadow-vote-{event_ts_ns}",
    )
    self._pending_shadow_votes.add(task)
    task.add_done_callback(self._pending_shadow_votes.discard)

async def aclose(self):
    if self._pending_shadow_votes:
        await asyncio.gather(*self._pending_shadow_votes, return_exceptions=True)
```

Plus runner.run()'s shutdown finally block calls
`getattr(self._strategy, "aclose", None)` so in-flight votes finish
writing to disk before the log closes.

Plus the queue-doesn't-overflow regression test — passes after fix,
fails (with `on_event took 1504ms`) when fix is stashed.

Plus separately, the LLM prompts (`prompts/meta.md`, `prompts/orderbook.md`,
`prompts/oracle_gap.md`, `prompts/momentum.md`) get a hard economic
gate: ABSTAIN if `best_ask >= 0.90` regardless of directional signal.
This is operator-requested option C from the same-session conversation
about price economics — unrelated to the queue-overflow fix but
shipped together since both are blockers to safely re-enabling the
ensemble.

Effort: ~2h coding + tests. Done.

## Lessons (learned twice now)

1. **Heuristic flag**: any `await` on I/O that can take >1s inside the
   single-tasked main loop needs a queue-doesn't-overflow test. This
   is the second time I missed this. Mark `EnsembleWrapper.on_event`,
   `_settle_current_window`, and any future similar code path in the
   runner's hot path as "load-test required".
2. **Same code class, same incident**: the gamma-poll bug (2026-05-09)
   and the LLM-ensemble bug (2026-05-10) are the same architectural
   anti-pattern: blocking the runner's sequential consumer on long
   async I/O. Future PRs that add async I/O to this code path MUST
   ship as fire-and-forget OR explicitly justify why blocking is OK.
3. **Cost pressure pushes you toward inline await** because it's
   "simpler". The 2-line `await ensemble; log()` looks innocent. It
   isn't. Async-but-blocking is still blocking from the queue's
   perspective.
4. **Operator caught it in <30 min via Telegram**. The alerting
   pipeline works. Without it, the bleed could have been hours.

## Cross-refs

- `runbooks/incidents/2026-05-09-instant-settle-queue-overflow.md` —
  the first incident, same pattern
- `~/.claude/projects/.../memory/feedback_test_under_load.md` — the
  feedback memo I should have honored
- `src/polymarket_bot/strategies/ensemble_wrapper.py` — the file with
  the bug + the fix
- `tests/strategies/test_ensemble_wrapper.py::test_shadow_mode_does_not_block_main_loop_under_slow_llm`
  — the regression test
- `prompts/{meta,orderbook,momentum,oracle_gap}.md` — the price-
  economics prompt updates (option C)
