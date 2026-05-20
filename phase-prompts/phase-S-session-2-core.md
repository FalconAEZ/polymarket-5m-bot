# Phase S — Session 2 prompt — Core strategy + tests + backtest

**Authored:** 2026-05-19 (immediately after Session 1 design lock).
**Status:** READY to execute. Pre-conditions: Session 1 sign-off (operator confirmation that `design/S.1-market-maker-bot.md` + `design/j7_priors.{json,md}` are correct).
**Estimated duration:** 5-7 days calendar / multiple sessions if needed.
**Branch:** `claude/phase-S-market-maker` (already cut from `9516f39`).
**Bot status:** Directional bot (Phase Q config) STAYS LIVE on its own service unit throughout. Do NOT touch `bot-staging.service`, `claude/phase-P-hard-reset`, or any directional-bot env. Phase S work is fully isolated.

---

## What you're stepping into

Phase S builds a parallel market-maker bot (MMB) modelled on the bonereaper wallet's observed mechanics. Phase S is 6 sessions; you are starting Session 2. Session 1 (closed 2026-05-19) locked the design + the priors data + the decision carve-out. No code shipped in Session 1.

**Required reading before writing any code:**

1. [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md) — the locked design. §2 defines module layout, ladder, sizing, risk caps, exit. §3 defines backtest. §4 lists R1–R6 risks. §5 lists open research items (close before S.2 ships).
2. [design/j7_priors.json](../design/j7_priors.json) + [design/j7_priors.md](../design/j7_priors.md) — the priors data this session's `J7Priors` class loads.
3. [memory/checkpoint_phase_S_session_1.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_1.md) — what shipped Session 1.
4. [memory/project_decisions.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md) decisions #22 + #23 — the carve-out + capital-exposure context.
5. [state/phases/phase-S-market-maker.md](../state/phases/phase-S-market-maker.md) — phase ledger.

Do not re-litigate the design in Session 2. If something in `design/S.1-market-maker-bot.md` is wrong, raise a doc fix and stop. CLAUDE.md anti-vibe rule #1: design doc before code.

---

## Session 2 scope (locked)

Three deliverables, in dependency order:

### Deliverable 1: `MarketMakerStrategy` + helpers (~1.5d)

Implement per `design/S.1-market-maker-bot.md` §2.1 module layout:

```
src/polymarket_bot/strategies/market_maker.py
    MarketMakerStrategy        — Strategy-protocol implementation
    LadderPlanner               — 3-level ladder per token per market
    InventoryTracker            — per-window UP + DOWN inventory state
    RiskGate                    — caps from §2.4
    PayoutResolver              — window-end inventory → realized PnL

src/polymarket_bot/strategies/j7_priors.py
    J7Priors                    — loads design/j7_priors.json
                                  (runtime fallback path:
                                   state/research/bonereaper/aligned_priors_30d.json
                                   — empty for now, used by future cron refresh)
```

Strategy-protocol expectations: match the existing `SpotAwareStrategyV2_1` protocol in `src/polymarket_bot/strategies/spot_aware_v2_1.py`. The runner calls `on_book_update(event)` per tick and `on_window_close(window)` at resolve; MMB places/cancels via the orders interface (Session 3 plumbs the actual `_paper` + `_live` clients; Session 2 defines the interface).

Hard requirements (CLAUDE.md anti-vibe rules):
- One-paragraph header docstring (≥80 chars) on every new `src/*.py` file.
- Type hints on every function. `mypy --strict src/polymarket_bot/strategies/market_maker.py src/polymarket_bot/strategies/j7_priors.py` green.
- No `TODO` / `FIXME` / `// hack` in committed code.
- All external dependencies behind protocols (`Clock`, `RpcClient`, `RandomSource`). Tests must run deterministically.
- `import-linter` must keep `_paper` ↔ `_live` separation; MMB strategy code stays under `strategies/` (no leak).

### Deliverable 2: ≥30 unit tests (~1.5d)

`tests/strategies/test_market_maker.py` — at minimum:

- `LadderPlanner` generates 3 levels at correct depths (-$0.05, -$0.10, -$0.20)
- `LadderPlanner` skips levels that would post below $0.05 floor
- `LadderPlanner` skips levels where `p_win <= fill_price` (–EV skip per §2.3)
- `LadderPlanner` cancels L1 when top of book moves > $0.02
- `LadderPlanner` cancels L2 + L3 when top moves > $0.05
- `LadderPlanner` cancels ALL when remaining window time < 15s
- `InventoryTracker` UP-side cap respected at **$25 (live-micro) / $50 (scale-up)**
- `InventoryTracker` DOWN-side cap respected at **$25 / $50**
- `InventoryTracker` gross-exposure cap respected at **$50 / $100**
- `RiskGate` halts on inventory breach
- `RiskGate` triggers halt sentinel on daily loss > **$50 (live-micro) / $100 (scale-up)**
- `RiskGate` honors `MM_KILL_SWITCH=true` (drains in <30s test sim)
- `PayoutResolver` computes net PnL correctly on UP-win
- `PayoutResolver` computes net PnL correctly on DOWN-win
- `PayoutResolver` computes net PnL correctly on cross-side inventory (both UP and DOWN held → losing side fully eats payout)
- `J7Priors.aligned_wr("85-100%")` returns 0.917
- `J7Priors.aligned_wr("<15%")` returns 0.137
- `J7Priors.aligned_wr("unknown_tier")` returns None
- `J7Priors` size-method returns 0 when `p_win <= fill_price`
- `J7Priors` size-method clamps to `MIN_BET` ($5)
- `J7Priors` size-method clamps to `MAX_BET` ($10 live-micro / $25 scale-up)
- Strategy + mocked runner: book-update → ladder placed
- Strategy + mocked runner: book-update with moving top → ladder cancelled + replaced
- Strategy + mocked runner: window-close → resolve PnL
- Strategy: window-close with $300 daily loss already crossed → no new orders
- Strategy: multi-market parallel state (3 markets concurrent)
- Strategy: restart resilience — load `state/mm-decisions/<UTC>.jsonl`, reconstruct active window
- Strategy: orphan order detection at startup → cancel orders tagged with MMB user-tag
- Edge case: best_ask < $0.10 on a side → skip that side entirely (ladder would clip floor)
- Edge case: window-end at t-15s → cancel all even mid-tick
- Queue-doesn't-overflow test (per `memory/feedback_test_under_load.md`): 1000 book updates in 1s, queue depth stays bounded

These are the 30 listed in design §2 of `S.1-market-maker-bot.md` plus a few derivations. If you find a missing edge case while implementing, add a test — don't ship without coverage.

### Deliverable 3: Backtest harness (~2d)

`scripts/research/mmb_backtest.py` — simulates MMB on historical data.

Inputs:
- Orderbook snapshots reconstructed from `scripts/research/_subgraph.py` (subgraph fills → per-second book reconstruction)
- BTC spot ticks from `state/research/binance_historical/btcusdt_1m_*.parquet`
- Window resolutions from Polymarket Gamma API (cache to disk)
- Fresh bonereaper data at `state/research/bonereaper/weekly_trades_2026-05-19.json` (refreshed Session 1)

Simulator semantics: use the existing simulator floor + depth guard rules from commits `46b3ce6` (simulator floor 0.02→0.05) + `10e08e8` (maker-side phantom-fill guard) + `f8da51f` (phantom-floor detection). Do NOT reinvent fill semantics; reuse the v2.1 simulator infrastructure.

Output:
- `runbooks/research/mmb-backtest-2026-05-XX.md` — per-day per-tier PnL breakdown
- JSON dump at `state/research/mmb_backtest_<UTC>.json` for downstream analysis

### Acceptance gates (Session 2 close)

**Framing pivot (2026-05-20):** Session 2's backtest is a **plumbing sanity check**, not an edge predictor. Operator pushback was correct: paper-mode cannot validate market-maker mechanics because MMB's own queue position + book presence are part of the edge. The real edge gate is S.5 live-micro PnL on real orders. Do NOT over-tune to backtest numbers.

ALL of:
1. ≥30 tests pass (`pytest tests/strategies/test_market_maker.py -v`).
2. `mypy --strict src/polymarket_bot/strategies/{market_maker,j7_priors}.py` green.
3. `ruff check src/polymarket_bot/strategies/market_maker.py src/polymarket_bot/strategies/j7_priors.py scripts/research/mmb_backtest.py` green.
4. `make verify` green (no regressions in the full test suite).
5. `import-linter` green (no leak between `_paper` and `_live`; MMB strategy under `strategies/`).
6. Backtest harness runs to completion on the 2026-05-19 7-day window without crashing or producing NaN/infinity PnL.
7. Per-window $/window non-catastrophic on ≥5 of 7 days (i.e., > -2× MIN_BET per window). Total simulated PnL is reported in the closeout note as context — NOT a pass/fail gate.
8. Cross-validation: MMB simulated PnL within **±50%** of bonereaper's actual per-day PnL on the SAME markets (relaxed from ±20% — simulator structurally cannot reproduce queue position). If cross-validation fails by an order of magnitude (>10×), STOP and investigate the simulator — do NOT adjust the strategy to make the number prettier.
9. Session 2 closeout writeup at `state/sessions/2026-05-XX-phase-S-session-2.md` + `memory/checkpoint_phase_S_session_2.md` + MEMORY.md index entry.

If any gate fails: see CLAUDE.md "When something feels wrong" + anti-vibe rule #3 (3-fix rule).

---

## Pre-S.2 housekeeping — CLOSED 2026-05-20

S.1.1 research is closed in [runbooks/S-mmb-research-2026-05-20.md](../runbooks/S-mmb-research-2026-05-20.md). Definitive answers (3/5) + empirical-probe deferrals (2/5). The runbook §5.1 surfaces 5 cross-cutting findings that are HARD requirements for Session 2 code:

1. **Heartbeat task is mandatory** — MmRunner must run `client.post_heartbeat(heartbeat_id)` every 5s on its own asyncio task. 2 consecutive misses → halt sentinel + Telegram alert. Without this, server cancels all open orders after 10s + 5s buffer.
2. **post_only=True on every limit** — no exceptions. Treat `INVALID_POST_ONLY_ORDER` as a soft skip (log + don't retry).
3. **neg_risk=False for BTC 5m** — verified via live Gamma snapshot; bake into `LadderPlanner` defaults.
4. **Per-market tick + min size** — `LadderPlanner` reads `orderPriceMinTickSize` + `orderMinSize` per market at strategy init. Round ladder prices to tick size. Assert minimum size before submission.
5. **In-flight trades = provisional inventory** — `InventoryTracker` counts `MATCHED`/`MINED` toward caps; only counts toward realized PnL on `CONFIRMED`.

Read the runbook before writing code; design §5 was rewritten to reflect what's now known vs deferred.

---

## Don't-do rules (operator-stated)

- Do NOT touch `bot-staging.service` or any directional-bot env. As of 2026-05-19 20:48 UTC the directional bot is HALTED + DISABLED on the VPS along with all auxiliary services; `state/halt.sentinel` is in place as a stay-off brake. Do not re-enable anything on the VPS unless explicitly instructed.
- Do NOT re-litigate the design in `design/S.1-market-maker-bot.md`. Raise doc fixes; don't silently change strategy.
- Do NOT skip the 3-fix rule. Three iterations without resolution → write `runbooks/incidents/2026-05-XX-<slug>.md` and stop.
- Do NOT relax the cross-validation gate (±50% match to bonereaper actuals — already widened from ±20% per the 2026-05-20 paper-is-fake pivot). The point is to confirm the simulator is at least within the same order of magnitude.
- Do NOT ship code without the queue-doesn't-overflow test (per `feedback_test_under_load.md`). Async I/O in a hot path needs the test.
- Do NOT change `KELLY_MULT` (locked at 0.10) without explicit operator go. The 0.10 figure is locked at design §2.3 for a reason — Kelly-directional assumption breaks at cross-side fills.

---

## When you finish Session 2

Write the closeout artifacts before considering the session done:

1. `state/sessions/2026-05-XX-phase-S-session-2.md` — session note (use this session note as template: [state/sessions/2026-05-19-phase-S-kickoff.md](../state/sessions/2026-05-19-phase-S-kickoff.md))
2. `memory/checkpoint_phase_S_session_2.md` — memory checkpoint (template: [memory/checkpoint_phase_S_session_1.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_1.md))
3. Update `MEMORY.md` with the Session 2 checkpoint entry (mark Session 1 as superseded for live-status purposes)
4. Update `state/phases/phase-S-market-maker.md` (mark S.2 ✅, S.3 next)
5. Write `phase-prompts/phase-S-session-3-orders.md` — Session 3 prompt (paper runner + py-clob-client wrapper)

If something is blocked or deferred, name it explicitly in the session note tail under "Deferred to Session 2 follow-up" or "Surfaced Session 3 items".

---

## Reference

- Locked design: [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md)
- Priors data: [design/j7_priors.json](../design/j7_priors.json) + [design/j7_priors.md](../design/j7_priors.md)
- Session 1 checkpoint: `memory/checkpoint_phase_S_session_1.md`
- Phase ledger: `state/phases/phase-S-market-maker.md`
- Session 1 note: `state/sessions/2026-05-19-phase-S-kickoff.md`
- Decisions #22 + #23: `memory/project_decisions.md`
- v2.1 strategy precedent: `src/polymarket_bot/strategies/spot_aware_v2_1.py`
- Simulator floor + depth guard: commits `46b3ce6`, `10e08e8`, `f8da51f`
- Phantom-fill defense memory: `memory/project_phantom_defense_equals_fill_rate_problem.md`
- Per-side state pollution pitfall: `memory/project_per_side_state_pollution_pattern.md`
- Test-under-load discipline: `memory/feedback_test_under_load.md`
- VPS deploy verification discipline: `memory/feedback_vps_deploy_verify_late.md`
