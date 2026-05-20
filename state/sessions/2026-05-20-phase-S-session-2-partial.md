---
date: 2026-05-20
session: phase-S-session-2-partial
duration_h: ~1.5
branch: claude/phase-S-market-maker
tags: [session-note, phase-S, code]
---

# Phase S Session 2 (partial) — MMB core modules + tests shipped

## What landed

**Modules** (878 LOC, mypy --strict + ruff green):
- [src/polymarket_bot/strategies/j7_priors.py](../../src/polymarket_bot/strategies/j7_priors.py) (189 LOC) — loader for design/j7_priors.json; aligned_wr() + bet_size() with Kelly sizing per design §2.3.
- [src/polymarket_bot/strategies/market_maker.py](../../src/polymarket_bot/strategies/market_maker.py) (689 LOC) — Side / OrderStatus enums; LadderLevel / OpenOrder / PlaceOrder / CancelOrder dataclasses; round_to_tick + tier_for_price utilities; LadderPlanner (plan_levels + plan_update); InventoryTracker (add/confirm/drop/gross/resolve); RiskCaps + RiskGate; PayoutResolver; MarketMakerStrategy orchestrator.

**Tests** (860 LOC, 54 tests, all green):
- tests/strategies/test_j7_priors.py — 18 tests covering loader path-resolution, schema validation, aligned_wr lookups, bet_size pipeline (clamps + abstains), constructor validation.
- tests/strategies/test_market_maker.py — 36 tests across utilities, LadderPlanner.plan_levels (full ladder + skip-low-ask + skip-below-floor + skip-min-size + -EV skip), plan_update (initial / no-op / L1-cancel / cancel-all / window-end), InventoryTracker (add/confirm/drop/gross/resolve UP+DOWN), RiskGate (every cap + halt + daily-loss), PayoutResolver, MarketMakerStrategy integration + multi-market isolation + reset + in-flight cap enforcement.

**Verification**:
- `uv run pytest tests/strategies/test_market_maker.py tests/strategies/test_j7_priors.py` — **54 passed in 0.04s**
- `uv run pytest -q` (full suite) — **728 passed in 46.80s** (no regressions)
- `uv run mypy --strict src/polymarket_bot/strategies/{market_maker,j7_priors}.py` — green
- `uv run ruff check ...` — green

## Hard requirements from S.1.1 honored

Per [runbooks/S-mmb-research-2026-05-20.md](../../runbooks/S-mmb-research-2026-05-20.md) §5.1:

1. **Per-market tick + min-size enforcement** — LadderPlanner.plan_levels rounds via `round_to_tick(price, tick_size)` (Decimal-based to avoid float drift) and rejects levels where `size_shares < min_order_size_shares`.
2. **In-flight = provisional inventory** — InventoryTracker.add_in_flight / confirm_in_flight / drop_in_flight, with `gross_usd` summing both filled + in_flight so caps catch in-flight bursts.
3. **Floor + skip semantics** — `DEFAULT_PRICE_FLOOR = $0.05` (matches Phase 11.A simulator floor at commit `46b3ce6`); ladder skips a side entirely when `best_ask < $0.10`.
4. **Window-end cleanup** — `plan_update(seconds_remaining < 15)` returns CancelOrder for ALL side-orders, NO PlaceOrder.
5. **OrderStatus state machine** — PENDING / LIVE / MATCHED / CONFIRMED / CANCELLED / FAILED mirroring CLOB lifecycle from agent-skills.

The heartbeat task (mandatory per S.1.1 §Heartbeat) is interface-only this session — `MmRunner` (Session 3) owns the asyncio task. The strategy module exposes `BankrollGetter` and `Side` enums but does not depend on asyncio.

## What's NOT shipped (deferred)

- `scripts/research/mmb_backtest.py` — the backtest harness. Listed as a hard Session 2 acceptance gate in `phase-prompts/phase-S-session-2-core.md` §Deliverable 3 but was the biggest single chunk and would have pushed this session past clean-handoff context budget. Next session deliverable.
- `src/polymarket_bot/strategies/__init__.py` re-export — not yet updated to surface MarketMakerStrategy. Trivial.
- Cross-validation gate (within ±50% of bonereaper actuals) — needs the backtest to compute. Same dependency.
- Session 2 closeout checkpoint — `memory/checkpoint_phase_S_session_2.md` not written; this partial note + session 1 checkpoint addendum + the phase ledger are the durable record so far. Memory checkpoint will land when backtest closes Session 2.
- No code shipped under `_paper/` or `_live/` — those are Session 3 deliverables (paper runner + clob_orders.py wrapper). Tests pass without them by construction (no IO dependencies).

## Bug observations during testing

1. Initial pass: 8/54 tests failed at `best_ask=0.90` because L2 (-$0.10=$0.80) lands in 70-85% tier where p_win=0.78 < fill_price=0.80 = -EV. The LadderPlanner correctly skipped it; my test expectations were wrong (I'd been thinking of mid-tier asks). Fixed by changing fixtures to `best_ask=0.40` where all 3 levels are +EV. Real-world implication: **at high asks, MMB will frequently post only 1-2 levels per side**, not always 3. Worth flagging because S.5 live-micro fill-rate math should not assume 6 orders/window guaranteed.
2. One assertion (`places >= 2` at `best_ask=0.48`) was tightened to `places >= 1` because the L1 level there had raw_bet=$4.21 (below MIN_BET=$5 → abstain) and L3 was -EV. The test's invariant is "big move triggers cancel-all + new ladder," not exact level count.

## Next session

**Phase S Session 2 close — backtest harness.** Same branch. Scope per `phase-prompts/phase-S-session-2-core.md` §Deliverable 3:

- `scripts/research/mmb_backtest.py` reconstructs orderbook snapshots from subgraph data + simulates MMB ladder placement against historical book state.
- Output: `runbooks/research/mmb-backtest-2026-05-XX.md` + JSON dump.
- Acceptance: backtest runs to completion, per-window $/window non-catastrophic on ≥5 of 7 days (loose gate per the 2026-05-20 paper-is-fake pivot), cross-validation within ±50% of bonereaper actuals.
- Then write `memory/checkpoint_phase_S_session_2.md` + update MEMORY.md + author `phase-prompts/phase-S-session-3-orders.md`.

## Branch state at close

```
git status --short
 M runbooks/study/weekly-audit.md        (modified Session 1)
?? design/S.1-market-maker-bot.md         (Session 1)
?? design/j7_priors.{json,md}             (Session 1)
?? phase-prompts/phase-S-session-2-core.md (Session 1)
?? runbooks/S-mmb-research-2026-05-20.md  (Session 1)
?? src/polymarket_bot/strategies/j7_priors.py     (Session 2, this)
?? src/polymarket_bot/strategies/market_maker.py  (Session 2, this)
?? state/phases/phase-S-market-maker.md   (Session 1)
?? state/research/bonereaper/weekly_*_2026-05-19.json (Session 1 data)
?? state/sessions/2026-05-19-phase-S-kickoff.md (Session 1)
?? state/sessions/2026-05-20-phase-S-session-2-partial.md (this file)
?? tests/strategies/test_j7_priors.py     (Session 2, this)
?? tests/strategies/test_market_maker.py  (Session 2, this)
```

All uncommitted by design — operator-review-then-commit per anti-vibe rule #1. Branch `claude/phase-S-market-maker` based at `9516f39`.
