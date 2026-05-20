# Phase S.1 — Market-Maker Bot (MMB) — Session 1 design lock

**Status:** DRAFT for operator review · 2026-05-19, updated 2026-05-20 for $1k pivot.
**Branch:** `claude/phase-S-market-maker` (cut from `claude/phase-P-hard-reset@9516f39`).
**Implementation target:** Sessions S.2–S.6 of Phase S.
**Source-of-truth prompt:** the operator-supplied Phase S prompt (this conversation, 2026-05-19) + the 2026-05-20 $1k bankroll + paper-is-fake pivots.
**Concurrent bot:** directional bot **OFF** as of 2026-05-19 20:48 UTC (all 6 project services on VPS halted + disabled by operator decision 2026-05-20). MMB now ships into a clean dormant VPS — no parallel-bot interference, no shared Signer concerns to resolve before live deploy.

---

## 0. One-paragraph header

MMB places maker-limit BUY orders on BOTH tokens of each Polymarket 5-min BTC up/down market, ladders deep into the book ($0.05 – $0.20 below best ask), cancels-and-replaces on book moves, accumulates inventory across the window, and holds to resolution. Net edge comes from the population-level positive $/trade observed on the bonereaper wallet ($0.66/trade across 306,997 trades, 51.7% direct WR, 67.4% aligned WR) under the hypothesis that the edge is per-trade EV, not directional WR. Phase S Session 1 locks the design; Session 2 ships the strategy class; Session 3 wires orders + paper-mode plumbing (shakedown only); Session 4 wires safety circuits + dashboard; Session 5 = **live-micro soak** at minimum size ($5/level) — replaces the original shadow-soak plan because paper-mode does not validate market-maker mechanics (operator pushback 2026-05-20: MMB's presence in the book is part of the edge; a sim that doesn't place real orders cannot reproduce queue position or taker-flow response); Session 6 = scale toward full **$1k** bankroll only after live-micro empirically positive over 7-14 days.

---

## 1. Why MMB now — and what's actually different from J.7

### 1.1  J.7 vs MMB — same data, different deployment

J.7 (sketched at [design/bonereaper_blended_priors.md](design/bonereaper_blended_priors.md), commit `83fe119`) uses the bonereaper 30d aligned-WR table as a **Bayesian prior anchor** plugged into the directional bot's adaptive-priors layer. Same strategy class as v2.1 (single-fire per window, directional taker), just with a stronger p_win input.

MMB uses the same underlying data corpus as a **trade-mechanics proof point**, not as a prior input. The hypothesis MMB tests is structurally different:

| Dimension | J.7 (directional) | MMB (market-maker) |
|---|---|---|
| Orders per window | 0–2 (cap=1 or cap=2) | 6+ (3-level ladder × 2 sides) |
| Sides fired | One (UP or DOWN) | Both (UP and DOWN simultaneously) |
| Fill semantics | Taker-side; takes best ask | Maker-only limit; waits for fills |
| Edge model | Aligned-WR ≥ p_win threshold × Kelly sizing | Aggregate positive $/trade across ladder |
| Bankroll model | Single position per window | Net inventory P&L at window-end |
| Capital intensity | ~$15 / window (Kelly 0.15× on $3k) | $50–$300 / window across ladders |
| Risk class | Single-direction exposure | Cross-side inventory exposure |

These are different strategy classes. Decision #19 (cloning abort) blocks the COPY-trade class. Neither J.7 nor MMB is a copy-trade — both are independent builds using a public dataset as bench. The carve-out for MMB is logged separately in `project_decisions.md` (this session).

### 1.2  The honest version of bonereaper's edge

The operator's Phase S prompt frames the bonereaper edge as "aligned WR 67.4% above our 60% gate". That figure is correct in isolation but needs decomposition before sizing MMB:

| Sub-population (30d, n=306,997) | n | WR | $/trade |
|---|---:|---:|---:|
| All trades | 306,997 | 51.7% | +$0.77 |
| Aligned (spot-Δ matches side) | 101,962 | 67.4% | +$0.81 |
| Contrarian (spot-Δ opposes side) | 117,040 | 36.4% | +$0.58 |
| Flat (\|Δ\| < 5 bps) | 87,964 | 53.9% | +$0.96 |

Source: [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md).

Key observations MMB must respect:

1. **Bonereaper's REAL operating WR is 51.7%, not 67.4%.** The 67.4% is conditional on a specific sub-population (aligned-only). MMB will fill across all three sub-populations when the book moves, so MMB's effective WR will be closer to ~52%.
2. **Profitability comes from per-trade EV ($0.66–$0.96), not WR.** This is the "slim-edge high-volume market-maker" mechanic the Phase A postmortem identified (`state/research/bonereaper-study-postmortem.md` line 24).
3. **Per-tier $/trade is highest at the price-tier extremes (<15% +$8.83 aligned, 85-100% +$0.65 aligned)** but bonereaper places the bulk of his notional ($5.46M of $12.13M) in the 85-100% tier — the slim-edge / high-volume / favored-side dynamic.
4. **Direct WR is 7pp below the original 60% gate that aborted Phase A.** That gate was correct for the COPY-trade class. MMB does not replicate his fills; it builds an independent ladder. Therefore the 60% gate does not apply to MMB; we replace it with a positive-$/trade gate (S.5 acceptance).

### 1.3  Phase Q link

Phase Q (single commit `599b5ff`, 2026-05-19) added `MMD_ABSTAIN_BY_SIDE` to target the killer cell identified by the 13-day Polymarket-bookchain audit (n=1403 fills, killer cell `MMD=MIXED × side=DOWN` at +$3.16/tr on n=226). That's the directional bot's surgical concentration. MMB does NOT replicate Phase Q's gate logic — MMB places ladders on BOTH sides irrespective of MMD, because the market-maker mechanic doesn't pre-commit to a direction.

*The operator's prompt mentions "killer cell +$5.15/tr backtest"; the actual figure in the Phase Q commit message is +$3.16/tr on n=226. The +$5.15/tr figure may come from a different audit slice — flagging for operator confirmation in S.1 sign-off.*

---

## 2. MMB architecture (the locked design)

### 2.1  Module layout

```
src/polymarket_bot/strategies/market_maker.py
    MarketMakerStrategy        — Strategy-protocol implementation
    LadderPlanner               — computes 3-level limit ladder per token per market
    InventoryTracker            — per-window position state (UP + DOWN tokens)
    RiskGate                    — enforces caps from §2.4
    PayoutResolver              — window-end inventory → realized PnL

src/polymarket_bot/strategies/j7_priors.py
    J7Priors                    — loads per-tier aligned-WR table for sizing only

src/polymarket_bot/_paper/mm_runner.py
    MmRunner                    — paper-mode driver (separate from v2.1 PaperRunner)

src/polymarket_bot/_live/clob_orders.py
    ClobOrderClient             — py-clob-client wrapper (limit place + cancel + status)

scripts/run_mm_paper.py
    paper-mode entrypoint

scripts/research/mmb_backtest.py
    backtest harness (Session 2)

design/j7_priors.json            — machine-readable priors (Session 1)
design/j7_priors.md              — human companion (Session 1)
```

### 2.2  The ladder (§S.1.3 in the prompt, locked)

For each (market, token∈{UP, DOWN}) at each book update:

1. Read best_ask on that token.
2. Compute 3 ladder levels:
   - L1 = best_ask − $0.05
   - L2 = best_ask − $0.10
   - L3 = best_ask − $0.20
3. For each level, post a maker BUY limit at that price for size determined by §2.3.
4. On book move:
   - If top of book moves > $0.02: cancel L1, repost at new best_ask − $0.05.
   - If top of book moves > $0.05: cancel L2 and L3, repost both at new depths.
5. At window time-remaining < 15s: cancel ALL remaining open orders. No mid-window exits.

Floor: do not post any order at price < $0.05 (Phase 11.A phantom-floor guard equivalent; matches `46b3ce6` simulator floor bump rationale).

Skip: do not post a level if best_ask < $0.10 on that side (the ladder would clip the floor and the level would post at $0.05 — meaningless).

### 2.3  Sizing per ladder level

Use J.7 priors as p_win at each tier the level lives in:

```
expected_pnl_per_$1_filled = p_win × (1 − fill_price) − (1 − p_win) × fill_price
                            = p_win − fill_price
```

The level is +EV iff p_win > fill_price. Size only +EV levels:

```
fraction_of_bankroll = kelly_mult × (p_win − fill_price) / (1 − fill_price)
                     = 0.10  × (kelly EV / (1 − fill_price))
size_$ = max(MIN_BET, min(MAX_BET, fraction_of_bankroll × bankroll))
```

Bounds (live-micro defaults; scale-up values in parens):
- `KELLY_MULT = 0.10` (more conservative than v2.1's 0.15× — directional Kelly assumption breaks at cross-side fills)
- `MIN_BET = $5` (floor stays; payout dust below $5 is noise)
- `MAX_BET = $10` (scale-up: $25)

If p_win ≤ fill_price: skip the level. Do not post a –EV order even at minimum size.

### 2.4  Inventory + risk caps

Hard caps enforced at `RiskGate`. **Recalibrated 2026-05-20 to $1k bankroll** (matches decision #10 baseline; HW wallet trigger #12 = $2k is NOT crossed at this scale, so no Phase S.6 HW-wallet dependency).

| Gate | Live-micro (S.5) | Scale-up target (S.6+) | Rationale |
|---|---:|---:|---|
| BANKROLL | $1,000 | $1,000 | decision #10 aligned |
| MAX_INVENTORY_PER_TOKEN_PER_WINDOW | $25 | $50 | one-side max; 2.5%–5% per window |
| MAX_GROSS_EXPOSURE_PER_WINDOW | $50 | $100 | sum across both sides |
| MAX_OPEN_ORDERS_GLOBAL | 20 | 50 | rate-limiter ceiling |
| MAX_DAILY_LOSS_$ | $50 | $100 | halt-sentinel trigger; 5%–10% bankroll/day |
| MAX_ORDERS_PER_MINUTE | 30 | 50 | rate-limit guard |
| MIN_BET (sizing floor) | $5 | $5 | post-resolution payout dust at $5 cost basis is ~$0.25; below this is noise |
| MAX_BET (sizing ceiling) | $10 | $25 | live-micro ceiling intentionally tight |

The live-micro column is the S.5 entry config. Promotion to the scale-up column requires the S.5 7-day live-micro soak showing net positive PnL on ≥4 of 7 days. The 1k bankroll itself does NOT change between the columns — only the per-window / per-day caps scale up.

Halt-sentinel path: when `MAX_DAILY_LOSS_$` triggers, write `state/halt.sentinel` with reason `mm-cooldown` and STOP placing new orders. Existing open orders are cancelled. Inventory held to window resolve, then run idles until manual restart.

Kill switch (env): `MM_KILL_SWITCH=true` → drain pending orders within 30s, halt placement. Matches the operator's preference from `feedback_test_under_load.md`.

### 2.5  Exit logic — window-end only

There is no mid-window exit. Inventory accumulated during the window holds to resolution. At window resolve:

```
winning_token_payout  = sum(winning_fills_$ × $1)
losing_token_payout   = 0
realized_pnl          = winning_token_payout − total_fills_$
```

This matches bonereaper's observed behavior: he places limits in the window, fills accumulate, no observed mid-window unwinds in the 30d microstructure data.

### 2.6  Cancel-on-halt + restart resilience

On startup, MMB queries open orders from CLOB and cancels any tagged with the MMB user-tag. This matches the orphan-recovery pattern shipped at `73c8fc5`. Window-state is reconstructed from `state/mm-decisions/<UTC>.jsonl` on the active window only.

---

## 3. Backtest plan (S.2.4 deliverable)

### 3.1  Data inputs

| Source | Path | Coverage |
|---|---|---|
| Bonereaper 30d fills | `state/research/bonereaper/weekly_*_2026-05-19.json` (refreshing) + `state/research/bonereaper/*_2026-05-06.json` | bench truth |
| Orderbook snapshots | reconstruct from subgraph (see `scripts/research/_subgraph.py`) | per-second book |
| BTC spot ticks | `state/research/binance_historical/btcusdt_1m_*.parquet` | spot-Δ alignment |
| Window resolutions | Polymarket Gamma API (cached) | win/loss labels |

### 3.2  Simulator semantics

For each historical 5-min window:
1. Reconstruct the orderbook per second from subgraph data.
2. At each tick, simulate MMB's ladder placement decision per `LadderPlanner`.
3. Simulate fills using the simulator floor + depth guard rules from `46b3ce6` and `10e08e8` (the maker-side phantom-fill guard).
4. At window resolve, compute realized PnL.

### 3.3  Acceptance gates (Session 2 close)

**Important framing:** the Session 2 backtest is a **plumbing sanity check**, not a live-PnL predictor. The operator's 2026-05-20 paper-mode insight (MMB's edge depends on its own queue position + presence influencing taker flow) means simulator PnL is structurally optimistic. Use the backtest to confirm:
- The strategy classes (Strategy / LadderPlanner / InventoryTracker / RiskGate / PayoutResolver) integrate correctly with the runner harness.
- Window-end payout math is correct.
- Cancel-and-replace + window-end cleanup behave deterministically.

Sim-PnL gates (loose; do not over-tune to these):
- Per-window $/window non-catastrophic on ≥5 of 7 days (i.e., > -2× MIN_BET per window).
- Total simulated PnL across 7 days is NOT a gate — it's a number reported in the closeout note for context.
- **Cross-validation gate:** MMB simulated PnL on the SAME windows as bonereaper actuals is within ±50% (relaxed from the original ±20% — the simulator cannot reproduce queue position, so a wider tolerance is honest).

If cross-validation fails by an order of magnitude: stop, investigate simulator floor/depth assumptions. Do not adjust the strategy to make the number prettier — fix the simulator.

The real edge gate is S.5 **live-micro** PnL, not Session 2 backtest PnL.

---

## 4. Risks (R1–R6)

### R1: Edge non-transferability (transferred from J.7 §R1)

Bonereaper's +$0.66/trade may be fill-quality (capital depth + presence early) rather than signal. At $3k bankroll our ladders are 250× shallower than his (~$760k). Expect transfer 30–50% lower; design must still be net-positive at degraded edge.

### R2: Cross-side exposure

Placing on BOTH UP and DOWN tokens at the same time means losses on the losing side fully eat winning-side payoffs unless avg_fill < p_win. The maker-rebate buffer (if any) is the safety margin. Need to confirm Polymarket fee structure in S.1.1 research.

### R3: Order-rate throttling

py-clob-client + CLOB API may throttle high-frequency limit posts. Bonereaper averages 30/window = 0.1/sec; our 3×2=6 levels × cancel-replace on every tick could push much higher. Need to instrument + cap.

### R4: Capital concentration in a single tier

If we ladder only at high-tier (e.g., 85–100% level), we accumulate inventory mostly on the favored side. Losing trades there cost ~$0.90 expected per $1 fill. A bad-streak day at $400/window × 5 windows = $2000 exposure can drain a major fraction of the $3k bankroll in hours.

### R5: Phase Q interaction (zero — by design)

MMB shares NO state with the directional bot. Different service unit (`bot-mm.service`), different env namespace (`MM_*`), different decision log (`state/mm-decisions/`), different bankroll envelope. The two bots only share the VPS and the Polymarket account.

### R6: Decision-#10 + #12 capital exposure (RESOLVED 2026-05-20)

Operator confirmed $1k MMB bankroll (matches decision #10 baseline) + directional bot halted 2026-05-19 20:48 UTC (all 6 services off, disabled). **Total operator-level exposure: $1k**. Decision #12 ($2k HW wallet trigger) is NOT crossed at this scale — no HW wallet dependency for Phase S.6. Decision #23 (capital exposure addendum) updated 2026-05-20 to reflect this. If S.5 + S.6 succeed and operator later scales bankroll beyond $2k, HW wallet wiring becomes a pre-requisite for the bankroll-bump phase (separate decision at that time).

---

## 5. Open research items — CLOSED 2026-05-20

All 5 items closed in [runbooks/S-mmb-research-2026-05-20.md](../runbooks/S-mmb-research-2026-05-20.md). Definitive answers (3/5) + empirical-probe deferrals (2/5):

1. **Maker fees** — empirical probe deferred to Session 3 ($5-$10 order on a live market, compare gross fill vs net USDC.e). Backtest assumes zero maker fee until proven otherwise.
2. **Maker-only semantics** — DEFINITIVE: use `post_only=True` always. Without it a limit @ best_ask CAN execute as taker. With it, order is rejected on cross (error `INVALID_POST_ONLY_ORDER`).
3. **Cancel latency** — empirical measurement deferred to Session 3. Heuristic: 20-50ms based on decision #2's 13-17ms app RTT.
4. **Rate limits** — not documented; empirical only. Watch for 429 + `X-RateLimit-*` headers in Session 3. Starting ceiling 30 ops/sec.
5. **NegRisk vs CTF for BTC 5m** — DEFINITIVE: standard **CTF Exchange** (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`). Verified via live Gamma snapshot 2026-05-19: every BTC 5m event has `negRisk: False`. Use `options={"neg_risk": False}` + signature_type=2.

### 5.1 Cross-cutting findings (BLOCKING for Session 2)

Surfaced from the research; not in the original 5 questions but Session 2 code MUST honor these:

- **Heartbeat is mandatory.** `client.post_heartbeat(heartbeat_id)` every 5 seconds. If no heartbeat within 10s (+5s buffer), ALL open orders auto-cancel server-side. MmRunner gets a dedicated heartbeat task. 2 consecutive misses → halt sentinel + Telegram alert.
- **Per-market tick + min size enforcement.** Read `orderPriceMinTickSize` + `orderMinSize` per market at strategy init. Round all ladder prices to the tick size. Assert `level_size_$ × shares ≥ orderMinSize` or skip the level.
- **USDC.e allowance one-time pre-deploy.** Signer (`0x8d97...2B4A`) must call `USDC.approve(CTFExchange, MAX_UINT256)` once before first live order. Funder needs MATIC for gas. Add to S.6 pre-deploy checklist.
- **In-flight trades = provisional inventory.** Count `MATCHED`/`MINED` toward inventory caps; only count toward realized PnL on `CONFIRMED`.
- **Decision #17 (gasless relayer) does NOT apply to MMB.** MEV applies to taker orders that cross spread; MMB places resting maker limits. Per OD-4 (`memory/checkpoint_phase_1a.md`) MMB uses the standard CLOB API path. No conflict with #17.

---

## 6. Sign-off gates (this session)

Session 1 closes when ALL of the following are true:

- [ ] `design/S.1-market-maker-bot.md` reviewed by operator and locked (this file).
- [ ] `design/j7_priors.json` + `design/j7_priors.md` shipped (separately tracked Session 1 task).
- [ ] `runbooks/S-mmb-research-2026-05-19.md` answers the 5 open research items in §5.
- [ ] `memory/project_decisions.md` carries the Phase S carve-out from decision #19 + the #10/#12 capital-exposure note.
- [ ] `state/phases/phase-S-market-maker.md` ledger present in vault.
- [ ] `state/sessions/2026-05-19-phase-S-kickoff.md` session note present.
- [ ] `memory/checkpoint_phase_S_session_1.md` + `memory/MEMORY.md` index entry.
- [ ] `phase-prompts/phase-S-session-2-core.md` next-session prompt staged.

If a sign-off item is deferred, it's noted in the session note tail and added to a Session-1-followup task.

---

## 7. References

- [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md) — aligned-WR per-tier source
- [runbooks/research/bonereaper-microstructure-30d-2026-05-08.md](runbooks/research/bonereaper-microstructure-30d-2026-05-08.md) — time-bucket × tier microstructure
- [state/research/bonereaper-study-postmortem.md](state/research/bonereaper-study-postmortem.md) — Phase A abort context (decision #19 source)
- [design/bonereaper_blended_priors.md](design/bonereaper_blended_priors.md) — J.7 sketch (different deployment class)
- [design/adaptive_priors.md](design/adaptive_priors.md) — J.3 (Bayesian blend formula MMB borrows for sizing)
- Phase Q commit [`599b5ff`](https://github.com/FalconAEZ/polymarket-5m-bot/commit/599b5ff) — directional bot side-specific gate
- `BONEREAPER_STUDY.pdf` p. 22-23 (archived) — operating-discipline rules
- `BUILD_SPEC.pdf` — anti-vibe rules #1-#25
- `pdfs/REQUIREMENTS.pdf` — bootstrap doc
- `MEMORY.md` — durable cross-session memory index
