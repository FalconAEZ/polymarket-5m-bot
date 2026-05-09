# Instant settlement via Polymarket Gamma poll (2026-05-09)

> **Status:** PROPOSED — author this doc, get operator approval, THEN implement.
> Per CLAUDE.md rule #1.

## Why this exists

Operator observation 2026-05-09 ~18:00 UTC: "settling time takes so
long once the 5min window is done and result revealed and still takes
15+ secs to update maybe even 30s i need it to be instant since we
have low ms ping to polymarket!"

Verified: dashboard `/api/state.pipeline.settle_wait_s = 61s` average
across 250 settled windows. Root cause: the bot waits for the next
**Chainlink AnswerUpdated** event after T+300 to compute resolution.
Chainlink has a 1-2 minute heartbeat, so settle latency is 0-120s
(averaging ~60s).

Polymarket Streams (the feed Polymarket itself uses) resolves
sub-second after T+300. We're not using it for the bot's live
settlement path — only post-hoc via `gamma_resolver.re_resolve_file`
(dashboard-side, after sync_staging).

## What this fixes — and what it doesn't

**Fixes:**
- Settle latency 60s → ~1-3s on the bot side
- Eliminates the 33% oracle-vs-Polymarket disagreement at the source
  (no more `resolution_source: chainlink-local` in fresh records;
  always `polymarket` directly)
- Dashboard's `decisions_truth_source` becomes `polymarket` for ALL
  decisions, not just the resolver-loop-corrected backlog
- Removes the post-hoc `resolve_decisions.py` workaround complexity
  on a long enough timeline

**Does NOT fix:**
- Trading-decision latency (already sub-ms; the latency edge is for
  ORDER PLACEMENT, not settlement)
- Capital recycling (negligible at $5/trade)
- Real-money go/no-go (Phase 11.B, separate decision)
- The strategy itself (orthogonal — v2 design doc is the strategy fix)

**Honest framing:** this is mostly a cosmetic-quality + Phase 6
prereq fix for paper. It becomes load-bearing in real-money trading
where capital is constrained and settle-derived state (streaks, halts,
position sizing) needs to be fresh. Not an emergency for paper at $5/trade.

## Design

### Approach: Gamma-poll at T+300+1s (not Streams WS)

**Trade-off considered:**

| Approach | Latency | Complexity | Robustness |
|---|---|---|---|
| **(A) Gamma REST poll** | 1-3s | Low (reuses existing GammaClient) | High (REST is sturdy) |
| (B) Polymarket Streams WS | <1s | High (new WS subscription, reconnect logic, auth) | Medium (WS can drop) |
| (C) Chainlink Streams (pull-based) | <1s | High (different RPC + abi + signing) | Low (operator-side complexity) |

**Pick (A)** for v1 of this fix. Sub-3s settle is "instant enough" for
the operator's stated need ("15+ secs maybe 30s") — going from 60s →
2s is a 30x improvement and removes the operator's complaint. (B) and
(C) are saved for Phase 6 when real-money capital management makes
sub-second matter.

### Settle loop changes

**Current** (`src/polymarket_bot/_paper/runner.py::_settle_current_window`,
lines 276-296):

```python
def _settle_current_window(self, ...):
    resolution = actual_resolution(window_ts, open_oracle, close_oracle)
    # ↑ This uses local Chainlink-only oracle. Wait was implicit in
    # observe_oracle being slow.
    pnl = _realised_pnl(fill, won)
    self._log.record_settled(
        ...,
        resolution=resolution,
        resolution_source="chainlink-local",  # implicit current behavior
        ...,
    )
```

**Proposed** — add an async polling step before the local fallback:

```python
async def _settle_current_window_v2(self, ...):
    # 1. Try Gamma first.
    truth = await self._poll_gamma_for_resolution(
        window_ts,
        max_wait_s=GAMMA_POLL_TIMEOUT_S,  # 30s
        poll_interval_s=GAMMA_POLL_INTERVAL_S,  # 1s
    )
    if truth is not None:
        resolution = truth
        resolution_source = "polymarket"
    else:
        # 2. Chainlink fallback (current path).
        resolution = actual_resolution(window_ts, open_oracle, close_oracle)
        resolution_source = "chainlink-local-fallback"
    pnl = _realised_pnl(fill, resolution == fill.side)
    self._log.record_settled(
        ...,
        resolution=resolution,
        resolution_source=resolution_source,
        ...,
    )
```

**Polling logic** (new method on the runner OR a new module):

```python
async def _poll_gamma_for_resolution(
    self, window_ts: int, *, max_wait_s: float, poll_interval_s: float
) -> Side | None:
    """Poll Gamma every poll_interval_s for up to max_wait_s seconds.
    Returns resolution as soon as available, or None on timeout."""
    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        truth = await asyncio.to_thread(
            gamma_resolution, window_ts, client=self._gamma_client
        )
        if truth is not None:
            return truth
        await asyncio.sleep(poll_interval_s)
    return None
```

The `gamma_resolution` function is **the SAME function** added to
`src/polymarket_bot/dashboard/gamma_resolver.py` for the dashboard
fix (PR #2 / commit ecc51b3). We reuse it directly.

### Module placement

The dashboard's `gamma_resolver.py` lives under `polymarket_bot.dashboard.*`,
which is a layer the import-linter PROHIBITS the live runtime from
importing (contract `layered3`: dashboard never imports live; therefore
live shouldn't import dashboard either, by symmetry).

**Solution**: move `gamma_resolution`, `realised_pnl`,
`re_resolve_file` to a NEUTRAL module:
**`src/polymarket_bot/gamma_resolver.py`** (top-level, no layer
membership). Both `polymarket_bot.dashboard.gamma_resolver` (CLI shim)
and `polymarket_bot._paper.runner` (bot settle loop) import from
there.

### Configuration knobs

```bash
# /home/ops/polymarket-5m-bot/.envrc on the VPS:
export INSTANT_SETTLE_ENABLED=1                # default ON; can disable
export INSTANT_SETTLE_GAMMA_POLL_INTERVAL_S=1.0  # how often to retry
export INSTANT_SETTLE_GAMMA_TIMEOUT_S=30.0       # max wait before fallback
```

If `INSTANT_SETTLE_ENABLED=0` → fall back to current Chainlink-only
behavior.

## What changes downstream

- **Dashboard**: the `decisions_truth_source` field starts saying
  `polymarket` for all NEW decisions (the resolver-loop becomes a
  no-op for fresh decisions; still useful for back-fill of any
  records pre-deploy or during Gamma outages).
- **`scripts/resolve_decisions.py`**: still useful for back-fill of
  legacy decisions written by old bot versions.
- **`runbooks/scripts/sync_staging.sh`**: unchanged (still runs
  resolve_decisions just in case).
- **Pipeline latency `settle_wait_s`** drops from 61s → 1-3s.
- **Polymarket Gamma rate limit consumption**: bot fires ~12 trades/hr,
  each settle adds 1-3 Gamma GETs (avg ~2). Total ~24 GETs/hr from
  the bot. Plus the dashboard resolver-loop's existing pass every
  5min. Well under any reasonable rate limit.

## Tests

**`tests/_paper/test_settle_loop_gamma.py`** (new file):

1. `test_gamma_resolution_returns_immediately` — happy path: Gamma
   returns "UP" on first poll → settle is fast and uses polymarket
   source
2. `test_gamma_polls_until_resolution_available` — Gamma returns
   None twice then "UP" → settle waits ~3 polls, then uses polymarket
3. `test_gamma_timeout_falls_back_to_chainlink` — Gamma never
   resolves within timeout → settle uses chainlink-local-fallback
4. `test_gamma_disabled_via_env_uses_chainlink_only` — `INSTANT_SETTLE_ENABLED=0`
   → never polls Gamma, uses chainlink-local
5. `test_pnl_recomputed_correctly_under_polymarket_truth` — Chainlink
   says UP, Gamma says DOWN, side was DOWN → pnl is positive (Gamma
   wins, was correct)
6. `test_gamma_http_error_falls_back_gracefully` — Gamma 503 → falls
   back without crashing the settle loop

All using `httpx.MockTransport` — no real network I/O in tests.

## Rollout plan

1. **Land this design doc + the implementation in PR #Y** (alongside
   v2 strategy in PR #X — they deploy together at the 48h gate).
2. **Refactor first**: move `gamma_resolver` from `dashboard/` to
   top-level `polymarket_bot/`. Update dashboard imports. This is
   pure mechanical.
3. **Then add the runner-side polling**.
4. **Tests pass; no deploy yet.**
5. **At the 48h gate** (2026-05-10 22:26:15 UTC):
   - Revert v1 aggressive (per v2 strategy design)
   - Switch to v2 strategy
   - Enable instant settlement
   - **One bot restart, three changes** — riskier in the moment but
     clean cut-over
6. **Verify post-restart**:
   - First post-window settle records have `resolution_source: "polymarket"`
   - Dashboard `pipeline.settle_wait_s` drops to <5s
   - No new exceptions in `journalctl -u bot-staging.service`

## Risk + mitigation

**Risk**: Gamma polling under load could hit rate limits or 5xx
during high-traffic windows.

**Mitigation**: 30s timeout + chainlink-local-fallback. Worst case
we degrade to current behavior, not break.

**Risk**: introducing async I/O in the settle loop changes the runner's
event-loop pressure. Could affect MarketEvent ingestion.

**Mitigation**: poll runs on `asyncio.to_thread` so the synchronous
Gamma call doesn't block the event loop. Same pattern as the
dashboard `resolver_loop` (already in production).

**Risk**: a Gamma response that says "closed=true outcomePrices=[0.5,
0.5]" (tied market, undecided) — gamma_resolution returns None, we
keep polling, eventually fall back to Chainlink.

**Mitigation**: this is the existing behavior and is correct.

**Risk**: deploying v2 + instant-settle + revert all in one restart at
the 48h gate compresses three risks into one window.

**Mitigation**: full pre-deploy testing on laptop with replay; rollback
plan in the deploy commit message; deploy at low-traffic UTC hour
(03-05 UTC has been our best window).

## Locked decisions touched

None. This is consistent with:
- Decision #2 (Dublin VPS for sub-5ms CLOB) — this fix LEVERAGES the
  low latency; it doesn't change deployment topology.
- Decision #17 (Polymarket gasless relayer) — orthogonal; settlement
  is read-only, not order placement.
- The orphan-FD-decisions defense (DecisionLog inode-stability) —
  unchanged; this fix doesn't touch the JSONL write path.

## What this is NOT

- Not Polymarket Streams WS integration (that's Phase 6 — sub-second).
  This is the simpler REST-poll path that still gets us 30x faster.
- Not a strategy change — orthogonal to v2 strategy design.
- Not changing the Chainlink-local feed — kept as the fallback safety
  net. The local feed isn't going anywhere; it's just no longer the
  primary truth source for settle.
- Not removing `resolve_decisions.py` — it's still needed for the
  ~250 legacy decisions written under chainlink-local truth.
- Not changing `pnl_usd` computation — same `realised_pnl` formula,
  just with PM-truth resolution as input.

## See also

- `src/polymarket_bot/dashboard/gamma_resolver.py` — existing
  implementation we'll move to a neutral module + reuse
- `src/polymarket_bot/_paper/runner.py::_settle_current_window` —
  the function being modified
- `src/polymarket_bot/resolver.py::actual_resolution` — current
  Chainlink-local resolution function (becomes the fallback)
- `runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md` — the
  underlying Chainlink vs Polymarket Streams gap that motivates this
- `runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md` —
  the dashboard surface we already fixed (PR #2); this is the bot
  surface
- `design/spot_aware_v2_tier_restricted.md` — sibling design doc
  shipped together at the 48h gate
