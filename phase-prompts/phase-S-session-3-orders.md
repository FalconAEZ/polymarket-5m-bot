# Phase S — Session 3 prompt — Order management + paper runner + S.1.1 empirical probes

**Authored:** 2026-05-20 (immediately after Session 2 close).
**Pre-conditions:** Session 2 CLOSED with backtest passing — `state/sessions/2026-05-20-phase-S-session-2-close.md` + `memory/checkpoint_phase_S_session_2.md` written.
**Estimated duration:** 3–5 days calendar (most complex Phase S session — networking + asyncio + heartbeat correctness).
**Branch:** `claude/phase-S-market-maker` (continue on same branch).
**Bot status:** Directional bot + all VPS services HALTED + DISABLED. `state/halt.sentinel` in place. Do NOT touch.

---

## What you're stepping into

Phase S Session 3 wires MMB to the actual Polymarket CLOB. Session 2 shipped the strategy logic (modules + 54 tests green) + a plumbing-only backtest (+$1,586 simulated 7d PnL at $1k bankroll). Session 3 ships the order-placement plumbing: a py-clob-client wrapper, a heartbeat task, and a paper-mode runner that drives `MarketMakerStrategy` against a mocked CLOB to validate end-to-end behavior without spending real money.

**Required reading before any code:**

1. [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md) — locked design.
2. [runbooks/S-mmb-research-2026-05-20.md](../runbooks/S-mmb-research-2026-05-20.md) — S.1.1 closure + hard requirements (heartbeat-mandatory, post-only-always, neg_risk=False, tick + min-size enforcement, in-flight=provisional).
3. [runbooks/research/mmb-backtest-2026-05-20.md](../runbooks/research/mmb-backtest-2026-05-20.md) — Session 2 backtest findings.
4. [memory/checkpoint_phase_S_session_2.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_2.md) — what's shipped.
5. [runbooks/phase-S-high-volume-plan-2026-05-20.md](../runbooks/phase-S-high-volume-plan-2026-05-20.md) §3 S.3 row + §2 G2/G3/G4/G11 — scope + dependencies.
6. [~/.claude/skills/agent-skills/order-patterns.md](file:///Users/hamad/.claude/skills/agent-skills/order-patterns.md) + `authentication.md` + `websocket.md` — Polymarket reference.

Strategy logic is LOCKED. Do not change `src/polymarket_bot/strategies/{market_maker,j7_priors}.py`. If a real bug surfaces, raise a separate Edit + run the test suite green before continuing.

---

## Deliverables

### G2 — `src/polymarket_bot/_live/clob_orders.py`

py-clob-client wrapper. Required surface:

```python
class ClobOrderClient(Protocol):
    """Interface for production CLOB calls + mock paper-mode swap-in."""
    async def place_maker_limit(
        self, *, token_id: str, side: Literal["BUY"], price: float,
        size_shares: float, tick_size: str, neg_risk: bool = False,
    ) -> PlaceOrderResult: ...
    async def cancel(self, order_id: str) -> None: ...
    async def cancel_all(self) -> int: ...
    async def cancel_market_orders(self, market: str, asset_id: str | None = None) -> None: ...
    async def get_orderbook(self, token_id: str) -> Orderbook: ...
    async def post_heartbeat(self, heartbeat_id: str = "") -> str: ...
```

Concrete implementations:
- `LiveClobOrderClient` — wraps `py_clob_client.client.ClobClient`. Always `post_only=True`, always `neg_risk=False` (BTC 5m default; configurable). Signature type 2 / Funder = `0x512D...5d22` / Signer = `0x8d97...2B4A` per Phase 1A.
- `MockClobOrderClient` — in-memory book for paper runs; honors floor + tick + min-size; emits fills probabilistically OR deterministically (operator config).

Error handling: classify CLOB errors per agent-skills `order-patterns.md` §Error Codes. `INVALID_POST_ONLY_ORDER` → soft skip (log + drop level, don't retry). `INVALID_ORDER_MIN_TICK_SIZE` or `INVALID_ORDER_MIN_SIZE` → fail-loud (it's our bug). `EXECUTION_ERROR` or `ORDER_DELAYED` → log + treat as PENDING.

### G3 — Heartbeat asyncio task

Standalone `mm_heartbeat_loop(client, halt_writer)` task. 5-second cadence. On miss: log warning + retry. On 2 consecutive misses (10s window): write halt sentinel + push Telegram alert via the alerter Redis queue (alerter currently disabled — push to the queue anyway; will drain when alerter is re-enabled in S.4).

Heartbeat ID rotates per the documented protocol (empty string first call; server returns the ID to use for the next).

### G4 — `src/polymarket_bot/_paper/mm_runner.py` + `scripts/run_mm_paper.py`

Paper-mode driver. Orchestrates:
- A `MarketMakerStrategy` instance + injected `MockClobOrderClient`.
- An event loop that ticks per simulated book update.
- Inventory accounting via the strategy's `on_fill` / `on_resolution` calls.
- Decision logging to `state/mm-decisions/<UTC>.jsonl` (mirror inode-stability pattern from `_paper/decision_log.py`).
- Bankroll replay-on-startup pattern (read prior day's mm-decisions; reconstruct `BankrollGetter` so a restart doesn't lose state).

`scripts/run_mm_paper.py` entrypoint: env-driven config (`MM_STARTING_BANKROLL=1000`, `MM_RISK_CAPS=live_micro|scale_up`, `MM_KILL_SWITCH=true`). 60-minute clean run is the gate.

### G11 — Empirical S.1.1 probes (3 short runbook addenda)

Run against a LIVE but low-volume BTC 5m market with **real but tiny ($5)** test orders. The Signer needs USDC.e allowance set first (G6) — if not done, this is a Session 3 follow-up and the probes get deferred to Session 4.

1. **Maker fee probe** → `runbooks/S-mmb-fee-empirical-2026-05-XX.md`. Place 5 maker-limit BUY orders at deep depths ($0.20 below ask). Wait for fills. Compare gross PnL (size × (1 - fill_price) if win else -size × fill_price) to net USDC.e settled to Funder. Delta = realized fee.
2. **Cancel latency probe** → `runbooks/S-mmb-cancel-latency-empirical-2026-05-XX.md`. Place + cancel 1000 orders sequentially. Record p50/p95/p99. Reuse `scripts/measure_clob_latency.py` infra.
3. **Rate-limit probe** → `runbooks/S-mmb-rate-limit-empirical-2026-05-XX.md`. Place orders at increasing rates until a 429 returns. Log `X-RateLimit-*` headers. Establish the per-IP order-place ceiling.

### Tests (≥20 new)

`tests/_live/test_clob_orders.py` + `tests/_paper/test_mm_runner.py`. At minimum:

- `LiveClobOrderClient` calls py-clob-client with `post_only=True` always.
- `LiveClobOrderClient` defaults `neg_risk=False` for BTC 5m markets.
- `MockClobOrderClient` honors floor + tick + min-size on place.
- `MockClobOrderClient` simulates a fill from a configurable taker stream.
- `place_maker_limit` returns `PENDING` initially; transitions on subsequent ack events.
- Heartbeat task on a 5s timer fires `post_heartbeat`.
- Heartbeat task on 2-miss writes halt sentinel.
- Heartbeat task is cancellable via the `MM_KILL_SWITCH` env path.
- Error classification: `INVALID_POST_ONLY_ORDER` → soft skip.
- Error classification: `INVALID_ORDER_MIN_TICK_SIZE` → raises.
- `MmRunner` drives `MarketMakerStrategy.on_book_update` per tick.
- `MmRunner` records decisions to `state/mm-decisions/<UTC>.jsonl`.
- `MmRunner` honors the strategy's PlaceOrder + CancelOrder action list.
- `MmRunner` on startup recovers bankroll from prior day's jsonl.
- `MmRunner` on startup cancels all open orders tagged with MMB user-tag (orphan-recovery pattern).
- `MmRunner` halts on `state/halt.sentinel` presence.
- `MmRunner` window-close drains inventory + writes payout PnL.
- Multi-market parallel: 3 markets concurrent, no state crosstalk.
- Queue-doesn't-overflow under 1000 book updates / 1s (per `feedback_test_under_load`).
- Integration: 60-second simulated paper run with mocked taker stream produces a sane decision-log + PnL number.
- Mypy --strict + ruff + import-linter all green on the new modules.

---

## Acceptance gates (Session 3 close)

ALL of:

1. `uv run python scripts/run_mm_paper.py --duration-min 60` completes cleanly.
2. Mocked-CLOB paper run produces 0 orphan orders + 0 heartbeat-misses (verified via `state/mm-decisions/` + heartbeat log).
3. `uv run pytest -q` → ≥748 tests pass (728 baseline + 20+ new).
4. `uv run mypy --strict src/polymarket_bot/_live/clob_orders.py src/polymarket_bot/_paper/mm_runner.py` → green.
5. `uv run ruff check ...` → green.
6. The 3 empirical-probe runbooks shipped (OR deferred to Session 4 with operator approval, with the deferral written into the session note).
7. Session 3 closeout: `state/sessions/2026-05-XX-phase-S-session-3-close.md` + `memory/checkpoint_phase_S_session_3.md` + MEMORY.md index entry + `phase-prompts/phase-S-session-4-dashboard.md`.

---

## Don't-do rules

- Do NOT modify `src/polymarket_bot/strategies/{market_maker,j7_priors}.py` unless a real bug surfaces (then ship the failing test first, per anti-vibe rule #2).
- Do NOT relax the 5s heartbeat cadence — Polymarket auto-cancels all orders if no heartbeat within 10s + 5s buffer.
- Do NOT submit live orders (real USDC.e) outside the empirical probes' $5 test orders. Phase S real-money flow is locked to S.5 deploy.
- Do NOT re-enable the directional bot or any of the 5 dormant VPS services. VPS stays in halted state.
- Do NOT skip the queue-doesn't-overflow test per `feedback_test_under_load.md` — async I/O in hot paths needs this.
- Do NOT decide on the `<15%` tier blocklist surfaced by Session 2 findings. That's a strategy change requiring design-doc revision (anti-vibe rule #1). Carry it as a Session 3 followup or surface for operator decision before S.5.

---

## When you finish Session 3

Write the closeout artifacts BEFORE considering the session done:

1. `state/sessions/2026-05-XX-phase-S-session-3-close.md` (template: [state/sessions/2026-05-20-phase-S-session-2-close.md](../state/sessions/2026-05-20-phase-S-session-2-close.md)).
2. `memory/checkpoint_phase_S_session_3.md` (template: [memory/checkpoint_phase_S_session_2.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_2.md)).
3. Update `MEMORY.md` — mark Session 2 superseded for live status; add Session 3 entry.
4. Update `state/phases/phase-S-market-maker.md` — mark S.3 CLOSED, S.4 next.
5. Write `phase-prompts/phase-S-session-4-dashboard.md` (Session 4 prompt: dashboard re-enable + safety circuits + Telegram MMB alerts).

If deferring any deliverable, name it explicitly in the session note's "Deferred to follow-up" section + add a tracking task.

---

## Reference

- Session 2 close: [state/sessions/2026-05-20-phase-S-session-2-close.md](../state/sessions/2026-05-20-phase-S-session-2-close.md)
- Backtest results: [runbooks/research/mmb-backtest-2026-05-20.md](../runbooks/research/mmb-backtest-2026-05-20.md)
- Phase plan: [runbooks/phase-S-high-volume-plan-2026-05-20.md](../runbooks/phase-S-high-volume-plan-2026-05-20.md)
- Polymarket skill: `~/.claude/skills/agent-skills/`
- Locked design: [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md)
- Strategy module: [src/polymarket_bot/strategies/market_maker.py](../src/polymarket_bot/strategies/market_maker.py)
- Decision log pattern: [src/polymarket_bot/_paper/decision_log.py](../src/polymarket_bot/_paper/decision_log.py)
- Halt sentinel: [src/polymarket_bot/_live/alerter/halt.py](../src/polymarket_bot/_live/alerter/halt.py)
- Latency probe pattern: [scripts/measure_clob_latency.py](../scripts/measure_clob_latency.py)
- Test-under-load discipline: `memory/feedback_test_under_load.md`
- Gate-revision discipline: `memory/feedback_pragmatic_gate_revision.md`
