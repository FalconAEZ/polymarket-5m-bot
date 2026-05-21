# Paper vs live trading — directional bot delta

**Authored:** 2026-05-21 (Phase T Session 1 deliverable A).
**Scope:** the directional bot on branch `claude/phase-T-directional-revival` @ `ad0a797`. MMB (Phase S, parked on a different branch) has a separate, more advanced live path covered by `pdfs/PHASE_S_MMB_OVERVIEW.pdf` §4 — not in scope here.

---

## §0. The headline finding

**The directional bot has no live-order-submission code path.** It is paper-only by construction. Every PnL number across Phases G→P (the $1k → $2,235 peak → $1,095 trough through Phase K, the −$1,562 swing in Phase N, the $0 net cumulative across 11 phases on ~3,500 fires) is **simulator-fill PnL**, not realized USDC.e in a Funder wallet.

Three facts that make this concrete:

1. `src/polymarket_bot/_live/` on this branch contains feeds (Binance, Coinbase, Chainlink, Polymarket WebSockets), runtime/storage/health (capture pipeline), and an alerter (Telegram). It does **not** contain `clob_orders.py` or any `py-clob-client.post_order` call. The only `_live/clob_orders.py` in the repo is on the `claude/phase-S-market-maker` branch (MMB-specific).
2. `src/polymarket_bot/_paper/runner.py:118-196` constructs a `PaperRunner` with a `ShadowBook` whose `attempt_fill()` delegates to a `FillSimulator` ([_paper/shadow_book.py:35-56](../src/polymarket_bot/_paper/shadow_book.py)). Decisions become simulated fills via `FillSimulator.attempt_fill()`; no order ever leaves the process.
3. `runner.py:944` calls `self._bankroll.apply_settle(pnl)` against `BankrollTracker.current_usd` — an in-memory float. The Funder/Signer wallets generated in Phase 1A (`0x512D...5d22` / `0x8d97...2B4A`) have **never had Polymarket orders signed against them**. Phase 1B (funded gate, decision #20) never closed.

**What this means**: when you've been making decisions about Kelly multipliers, halt thresholds, and gate refinements, you've been optimizing the simulator's response, not real-money behavior. The simulator's accuracy is the gating question for whether any of the Phase G-P findings transfer to real trading.

---

## §1. The 10-dimension comparison

| # | Dimension | Paper (today) | Live (would-be) | Modelled? | What the model gets wrong |
|---|---|---|---|---|---|
| 1 | **Order submission** | `FillSimulator.attempt_fill()` against the latest `BookUpdate` snapshot for `decision.asset_id`. TTL-gated (`decision.ttl_s`). | `py-clob-client.create_order()` + `post_order(GTC, post_only=False)` to `https://clob.polymarket.com`. Limit order enters the real CLOB book. | **No** (sim assumes instant) | Sim treats fill as binary (yes/no this tick); real fills are partial + queue-ordered. |
| 2 | **Fill price** | Simulator returns `Fill(price_filled=decision.limit_price, size_filled=requested_size)` when the latest book's best_ask ≤ limit. Clean exact-limit fill. | Real fills sweep through book levels until size is filled or order rests. Price-improvement on the maker side, slippage on the taker side. | **Partially** (FillSimulator has some price logic) | Phase 11.A "phantom fill" incident: the sim over-filled at the limit when book depth was unknown. Backfill scripts (`scripts/backfill_phantom_floor_fills.py`) exist to scrub these post-hoc. |
| 3 | **Fees** | `FillSimulator` uses `fee_estimate_pct=0.005` (default 0.5%) baked into PnL math. | Zero maker fees on Polymarket CTF; ~3% taker fees on fee-enabled markets (per Polymarket docs, verified MLB markets show `fee: 3%`). **G11 fee probe has never run for the directional bot — actual BTC 5m taker fee is unmeasured.** | **Yes but wrong** | Bot is TAKER (single-fire fills at best ask). If real fee is >0.5% on BTC 5m, paper PnL is systematically overstated by `(real_fee − 0.005) × gross_notional`. Could be material — at 3% real fee + $50 daily turnover that's −$1.25/day, −$37.50/month. |
| 4 | **Settlement source** | Real Chainlink-on-Polygon oracle round (paper uses real settlement data even though fills are sim'd). Cross-checked against Polymarket gamma. | Same Chainlink-on-Polygon oracle. Paper and live are identical here. | **Yes (identical)** | Phase 5 settle-resolution bug (2026-05-10): chainlink-local fallback disagreed with gamma on ~33% of windows. Post-hoc gamma retry shipped at `runner.py:957`. Live would inherit this fix unchanged. |
| 5 | **Bankroll** | `BankrollTracker.current_usd` in-memory float; persisted via decision-log replay on restart (`BANKROLL_REPLAY_ENABLED=true`). | Funder wallet USDC.e balance, polled via `getBalanceAllowance(COLLATERAL)`. Live PnL = balance delta over time. | **Approximate** | Real balance reflects gas costs (none in paper), failed-tx costs (none in paper), partial fills resolving at unexpected prices (clean in paper). Real bankroll can drift from decision-log-replay value; needs reconciliation. |
| 6 | **Latency** | Zero. `attempt_fill()` returns synchronously from in-memory state. | Polymarket CLOB roundtrip ~50-200ms (per Phase S G11 cancel-latency probe — never run). Plus WebSocket book staleness up to 1s polling cadence. | **No** | The directional bot's edge depends on `d_bps` thresholds; if real CLOB latency means our order hits the book 200ms after we decided, the d_bps that triggered the fire may have already reversed. Paper assumes the decision-time book IS the fill-time book. |
| 7 | **Rate limits** | Unlimited. PaperRunner can fire 10/sec if the strategy emits. | Polymarket CLOB rate-limited at an unknown rate (G11 rate-limit probe never run). MMB's `RiskCaps.max_orders_per_minute=30` is a guess. | **No** | Bursty cancel-replace under regime shift could hit 429s. Bot has no 429 handling in `_paper/runner.py`. |
| 8 | **Order rejection** | Never. Sim always returns a Fill or None (TTL/book-miss). | Can fail with: insufficient balance, insufficient allowance, market closed, neg-risk vs CTF mismatch, malformed payload, sig type wrong, network 5xx. | **No** | Bot has no rejection handling; would need retry-with-backoff or skip-the-window logic. |
| 9 | **Halt sentinel** | `state/halt.sentinel` file presence checked in `_halt_watcher` at `run_paper.py:110-129`. Sets stop_event; runner drains queue + exits. | **Identical** — the halt sentinel mechanism is venue-independent. Telegram `/halt` writes the sentinel via tg-alerter regardless of paper/live. | **Yes (identical)** | Nothing. This is the one piece that works the same. |
| 10 | **Heartbeat** | Feed-health snapshot every 30s via `health_task` ([_live/health.py](../src/polymarket_bot/_live/health.py)). Monitors WebSocket connection liveness, not order venue. | Would need additional CLOB connection heartbeat (a no-op `GET /` every 5s, 2-miss → halt sentinel). MMB has `_live/mm_heartbeat.py` on the Phase S branch; directional bot doesn't. | **Partially** (feed only) | Loss of CLOB connection in live mode would mean orders fail silently; bot wouldn't know until the next book event arrives. |

---

## §2. What was real all along

Despite being paper-only, the directional bot used REAL data for everything except order submission and balance:

- **Spot price ticks** — real Binance + Coinbase WebSocket trades
- **Oracle** — real Chainlink-on-Polygon BTC/USD heartbeat (~33s cadence per Phase 2)
- **Polymarket book** — real Gamma + CLOB book state
- **Settlement outcomes** — real chainlink + gamma resolution per window

So the Phase G "zero edge" finding (50.0% WR / −$18.96 over n=635) IS a real finding *about the directional strategy class's ability to predict 5-min BTC moves*. What it's NOT is a real finding about how the strategy would perform under live execution constraints.

The Phase N forensic's SURV-cell flip (60.7% → 46.5% WR at peak) is a real regime-detection failure of the strategy. Whether real-money trading would have been better or worse at that moment is **unknown** — could be worse (queue position, fees), could be better (the sim's over-fill bias might have manufactured some losing fills that real queue position would have avoided).

---

## §3. What would have to be built to go live

In rough effort order, to take the directional bot from `ad0a797` to a real-order-submission deploy:

1. **Add `_live/clob_orders.py` for directional** — lift the pattern from MMB's `_live/clob_orders.py` on `origin/claude/phase-S-market-maker`. ~150 LOC + 10-15 tests. Wraps `py-clob-client` with the bot's `Decision → Fill` interface.
2. **Add `_live/heartbeat.py` for CLOB connection** — lift from MMB's `mm_heartbeat.py`. ~80 LOC + 5 tests.
3. **Add live preflight gates** — `STRATEGY_LIVE=yes`, allowance audit (run `scripts/mm_set_allowance.py` against the directional Funder), CLOB L2 creds present, halt sentinel absent. ~50 LOC + 4 tests.
4. **Replace `PaperRunner.shadow_book.attempt_fill` with branch on STRATEGY_LIVE** — preserve the simulator path for paper mode, swap in real CLOB for live. Strategic decision: clean module split (LiveRunner vs PaperRunner) or a single Runner with a Pluggable filler. Latter is less code, former is cleaner per the import-linter contracts.
5. **Add real bankroll reconciliation** — every N minutes, fetch real Funder USDC.e balance; compare to decision-log-replay value; alert + halt if drift > $5. ~100 LOC + tests.
6. **Run G11 probes** — fee, cancel-latency, rate-limit. ~$5 real money for the fee probe. **Must run before live deploy** — if real fees are >0.5%, the bot's EV math (which subtracts 0.005 fee) is wrong and needs recalibration.
7. **Close Phase 1B** — funded wallet gate that never shipped. Fund the directional Signer (`0x8d97...`) with $1k USDC.e via the Funder (`0x512D...`); set allowance to the CTF Exchange via `mm_set_allowance.py`.
8. **Operator-supervised first fire** — same discipline as MMB's Phase S Session 6 plan. Watch 5 minutes hands-on. Halt immediately on anomaly.

Estimated total effort: **5-8 sessions of focused work**, comparable to Phase S Sessions 3-6 combined. Most of the architecture exists (in MMB's code path); it's adaptation, not invention.

---

## §4. What this means for Phase T

Three implications worth holding explicit:

1. **The Phase T improvements (#1-#6) are improvements to a paper-only bot.** Their value transfers IF and only IF the simulator's fill model is close enough to real execution. Phase 11.A's phantom-fill incident is the existence proof that the simulator has known biases. We don't know how big the bias is for the strategy class as currently designed; the G11 probes would be the only way to find out.
2. **The 14-day Phase T soak gate (cum PnL > +$300) is a SIMULATOR soak gate**, not a live one. A PASS would be evidence the strategy class works in sim; it would NOT be evidence the strategy class works in real markets. The pivot to live still requires §3 above.
3. **MMB's Phase S preparation already did much of this work.** `_live/clob_orders.py`, `mm_heartbeat.py`, `mm_set_allowance.py`, the G11 probe harness, the operator handoff doc all exist on the parked Phase S branch and are 80%+ portable to directional. The decision to "deploy directional first" effectively duplicates 5-8 sessions of work that MMB has already shipped.

This is not an argument to flip back to MMB-first. It's an argument that, if the Phase T directional revival succeeds at its 14-day soak gate, the next step (taking it live) is meaningfully larger than just "remove halt.sentinel + start the service." The operator should budget for §3 before celebrating any PASS.

---

## §5. References

- `src/polymarket_bot/_paper/runner.py:118-196` — PaperRunner construction, simulator wiring
- `src/polymarket_bot/_paper/shadow_book.py:35-56` — `attempt_fill()` implementation
- `src/polymarket_bot/_paper/decision_log.py` — schema for fired + settled records
- `src/polymarket_bot/_live/` — feeds + runtime + health + alerter (NO order submission)
- `scripts/run_paper.py:110-129` — halt-sentinel watcher (identical in paper + would-be live)
- `pdfs/PHASE_S_MMB_OVERVIEW.pdf` §4 (on `origin/claude/phase-S-market-maker`) — MMB's live architecture, much of which is portable
- `runbooks/OPERATOR_HANDOFF_PHASE_S.md` (on `origin/claude/phase-S-market-maker`) — the live-deploy checklist that doesn't exist for the directional bot yet
- `memory/project_decisions.md` #20 — Phase 1B (funded wallet) never closed
- `memory/checkpoint_phase_11_a.md` — phantom-fill incident, evidence that the simulator has bias
- `runbooks/research/phase-N-forensic-summary.md` — what the bot did in sim during the worst week
