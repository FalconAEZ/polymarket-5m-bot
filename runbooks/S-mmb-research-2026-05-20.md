# S.1.1 — Polymarket mechanics research (Phase S MMB)

**Date:** 2026-05-20.
**Sources:** `~/.claude/skills/agent-skills/` (Polymarket official skill, cloned per `CLAUDE.md`), `state/research/bonereaper/weekly_events_2026-05-19.json` (fresh Gamma API snapshot), `memory/reference_polymarket.md`, py-clob-client documented patterns.
**Purpose:** close the 5 open research items from `design/S.1-market-maker-bot.md` §5 so Session 2 code can start without ambiguity.

## TL;DR

| # | Question | Answer | Confidence |
|---|---|---|---|
| 1 | Maker fees — NegRisk vs CTF, rebate or pay? | Not in skill docs; per public Polymarket framing fees are taken from outcome shares (not USDC) and historically zero on the CLOB. Probe with a real $5-$10 order in Session 3 to confirm realized fee from trade response. | **Medium — empirical confirmation pending** |
| 2 | Maker-only limit semantics, BUY @ best_ask outcome, priority | **post-only is the right flag.** Without it, limit @ best_ask CAN fill as taker (crosses spread). With it, order is REJECTED on cross (error `INVALID_POST_ONLY_ORDER`). MMB always uses `post_only=True`. Price-time priority is standard CLOB convention (not explicitly stated, but implied by all references). | **High** |
| 3 | py-clob-client cancel latency | Not stated in skill docs. Heuristic from decision #2 evidence: app RTT 13-17ms → cancel ≈ 20-50ms total. Measure in Session 3 via existing `scripts/measure_clob_latency.py` adapted for cancel endpoint. | **Medium — measurement deferred to Session 3** |
| 4 | CLOB API rate limits for limit-place | Not stated in skill docs. Known facts: heartbeat MUST fire every 5-10s or all orders cancel; batch order cap is 15 orders/request. No per-second order rate documented. Watch for 429 + `X-RateLimit-*` headers empirically in Session 3. | **Low — empirical only** |
| 5 | BTC 5m markets — NegRisk or CTF? Signing path? | **Standard CTF Exchange** (`0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E`). Verified via live Gamma snapshot 2026-05-19: every BTC 5m event has `negRisk: False`, `enableNegRisk: False`, and per-market `negRisk: False`. Use `options={"neg_risk": False}` in `client.create_and_post_order(...)`. Signature type = `2` (GNOSIS_SAFE / proxy) per Phase 1A OD-4. | **High** |

## Q1: Maker fee structure (CTF vs NegRisk)

### What the skill says
The agent-skills `order-patterns.md` documents 13 order-status codes and 6 trade-status codes; **none mention fees**. The `authentication.md`, `market-data.md`, `gasless.md` files do not document a fee schedule either. Insert response includes `orderID` + `status` (`matched` / `live` / `delayed` / `unmatched`) but no fee field is visible from the documented response shape.

### What we can infer
- Polymarket's public posture has historically been "zero CLOB fees, taken from outcome shares not USDC" on standard markets.
- The skill emphasizes that fills emit `MATCHED → MINED → CONFIRMED` trade events; if a fee were applied, it would surface in the trade record (Data API `/trades` endpoint).
- The 2026-05-19 weekly audit (`runbooks/study/weekly-audit.md`) explicitly says: "**Fees not subtracted.** Polymarket V2 charges ~7.2 bps taker (per market schedule)." — that's the existing project's own note. Source for "7.2 bps taker" is unverified within this runbook.
- For a market-maker, the only fee that bites is the **taker-side fee on a MAKER fill** — i.e., when our resting limit is hit, does the fill emit a fee charged to us (the maker)? Historical CLOB convention is **no maker fee** in this case; the taker pays.

### Action — empirical probe (Session 3)
1. Place ONE $5-$10 post-only BUY limit on the deepest level (-$0.20 below best ask) on a live BTC 5m market.
2. Wait for fill (or cancel + retry if it doesn't hit within the window).
3. Inspect the resulting trade record from `data-api.polymarket.com/trades?market=...&user=...`.
4. Compare gross fill PnL (size × (1 - fill_price) if win, -size × fill_price if loss) to net PnL settled to the funder's USDC.e balance.
5. The delta is the realized fee. Document at `runbooks/S-mmb-fee-empirical-2026-05-XX.md`.

### Decision for Session 2 design
Assume **zero maker fee** for the backtest harness math. If empirical Session 3 probe shows non-zero, recalibrate sizing in S.4 before live-micro.

## Q2: Maker-only limit semantics + price-time priority

### Definitive answer
From `order-patterns.md` §Post-Only Orders (verbatim):

> Guarantee maker status. If order would cross spread, it's rejected (not executed).
> - Only works with GTC and GTD
> - Rejected if combined with FOK or FAK

### Without post-only flag
A limit BUY at exactly best_ask **WILL execute as taker** (matches against the resting ask). Without `post_only=True` the order crosses the spread and pays taker fees (whatever they are per Q1).

### With post-only flag
A limit BUY at exactly best_ask is **rejected with error `INVALID_POST_ONLY_ORDER`**. Order is not placed.

### MMB implication
The `LadderPlanner` per `design/S.1-market-maker-bot.md` §2.2 places at best_ask - $0.05 / -$0.10 / -$0.20, so by construction these don't cross the spread. But **post-only=True is the safety check** that catches misconfigured ladder depths or sub-tick rounding errors. Always set `post_only=True`. Treat `INVALID_POST_ONLY_ORDER` as a soft error: log, skip the level, do not retry.

### Price-time priority
Not explicitly stated in skill docs, but the standard CLOB convention is **price-first, then time-priority among equal-price orders**. This matters for MMB because our ladder levels (-$0.05, -$0.10, -$0.20) below best ask will queue alongside other maker orders at the same price tier. Bonereaper's edge (per [project_v2_1_multi_fire_pure_variance.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_v2_1_multi_fire_pure_variance.md)) is partly QUEUE POSITION at his sizes. At $5-$10 per level our queue position is going to be poor compared to bonereaper's $1000+ orders — confirms the live-micro framing (paper can't model queue position).

## Q3: Cancel latency (py-clob-client)

### What the skill says
Cancel endpoints in `order-patterns.md`:
- `client.cancel(order_id)` — single
- `client.cancel_orders([...])` — multiple
- `client.cancel_all()` — global
- `client.cancel_market_orders(market=..., asset_id=...)` — scoped

All require L2 authentication. No latency SLA documented.

### Heuristic
- Decision #2 evidence (`runbooks/gate-evidence/phase-5.3-latency.txt`): app-layer RTT 13-17 ms verified Dublin VPS → Polymarket origin proxy.
- Cancel is a POST with HMAC headers similar to order-place.
- Reasonable estimate: 20-50ms per single cancel; batch cancel ~50-100ms regardless of count up to limit.

### MMB implication
Ladder cancel-and-replace cadence is bounded by cancel latency. If cancel takes 50ms:
- L1 (-$0.05 from best ask) cancel + replace = 100ms round trip.
- 5 cancel-replace cycles per market per minute = 500ms/min spent on cancels = OK at our rate.
- If cancel latency spikes to 500ms (network blip), MMB ladder is briefly stale; not a correctness problem because the existing levels keep their queue position.

### Action — Session 3 measure
Adapt `scripts/measure_clob_latency.py` (per `runbooks/gate-evidence/phase-5.3-latency.txt`) to probe cancel-endpoint round-trip. Capture 1000 cancel-then-replace cycles, report p50/p95/p99 to `runbooks/S-mmb-cancel-latency-2026-05-XX.md`.

## Q4: Rate limits for limit-place

### What the skill says
- **Batch limit**: `client.post_orders([...])` accepts up to 15 orders per request.
- **Heartbeat**: must POST within 10 seconds (5s buffer); else all open orders auto-cancel.
- **No per-second or per-minute order-place rate is documented anywhere in the skill files.**

### Empirical estimate
Bonereaper places ~30 trades / 5-min window (per `runbooks/research/bonereaper-microstructure-30d-2026-05-08.md`) = ~0.1 orders/sec sustained. At his $760k notional this is clearly well within whatever rate limits exist.

MMB at 6 levels × 1-3 cancel-replace cycles per window = max ~18 orders + 18 cancels per 5-min window = 0.12 orders/sec. Same order of magnitude as bonereaper.

### Risk
Could hit a per-IP or per-user limit when ladder + heartbeat + cancel concurrently fire. Mitigation:
- Single HTTP/2 connection pool (default for httpx-based py-clob-client).
- Watch for HTTP 429 responses + `X-RateLimit-Remaining` / `Retry-After` headers.
- Implement exponential backoff on 429.

### Action — Session 3 implementation
Wrap `clob_orders.py` calls with a rate-limiter (per-IP token bucket, 30 ops/sec ceiling as starting point). Log every 429 to `state/mm-clob-rate-limit.jsonl`. If we never hit 429, the ceiling can be raised. If we hit 429 regularly, the ceiling lowers.

## Q5: NegRisk vs standard CTF for BTC 5m markets

### Definitive answer (verified 2026-05-20)
Live Gamma API snapshot of all BTC 5-min events for the 7-day window ending 2026-05-19 (`state/research/bonereaper/weekly_events_2026-05-19.json`, 2,017 events):

```json
{
  "negRisk": false,
  "enableNegRisk": false,
  "markets": [
    {
      "negRisk": false,
      "enableOrderBook": true,
      "orderPriceMinTickSize": "<varies>",
      "orderMinSize": "<varies>",
      "clobTokenIds": "[UP_token_id, DOWN_token_id]"
    }
  ]
}
```

**BTC 5m markets are NOT NegRisk.** They route to the **standard CTF Exchange** at `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` (per `~/.claude/skills/agent-skills/SKILL.md` Contract Addresses).

### Signing implications
- Use `options={"neg_risk": False}` in every `create_and_post_order(...)` call.
- Signature type: `2` (GNOSIS_SAFE) per locked Phase 1A OD-4 (`memory/checkpoint_phase_1a.md`).
- Funder = the proxy wallet address. Signer = `0x8d97...2B4A` per `memory/checkpoint_phase_1a.md`.

### Decision #17 (gasless relayer) clarification
Decision #17 mandates the gasless relayer "for all order submission (avoids public-mempool MEV)". OD-4 (resolved Phase 1A) reads: "(a) orders go via standard CLOB API not Relayer SDK". For MMB specifically:
- MEV applies to **taker orders** that cross the spread (sandwich attacks). MMB places **maker limit orders** that REST on the book — there is no public-mempool transaction to front-run.
- Therefore decision #17's rationale does not apply to MMB.
- **MMB uses the standard CLOB API path (OD-4), not the relayer.** No conflict with decision #17.

## Cross-cutting findings (NOT in the original 5 questions but critical)

### Heartbeat is MANDATORY
From `order-patterns.md` §Heartbeat:

> If a valid heartbeat is not received within **10 seconds** (with up to a 5-second buffer), **all of your open orders will be cancelled**.

**MMB design implication:** the MmRunner MUST run a heartbeat task in parallel with the strategy loop. Recommended cadence: every 5 seconds, with retry-on-failure. If heartbeat misses 2 consecutive intervals, halt sentinel + Telegram alert. This was not explicitly called out in `design/S.1-market-maker-bot.md` §2.6; adding it as a Session 2 hard requirement.

### Tick size & min order size are per-market
- `orderPriceMinTickSize` — must be honored or order rejected with `INVALID_ORDER_MIN_TICK_SIZE`.
- `orderMinSize` — must be honored or order rejected with `INVALID_ORDER_MIN_SIZE`.
- LadderPlanner must round ladder prices to the market's tick size BEFORE submitting.
- J7Priors size method must ensure final size ≥ `orderMinSize` (probably 5 shares = ~$2.50 at p=0.50). Combined with our MIN_BET=$5, this should be satisfied — but assert it.

### USDC.e allowance must be pre-set
From `order-patterns.md` §Prerequisites:

> Before placing orders, the funder address must approve the Exchange contract:
> - **Buying**: the funder must have set a **USDC.e** allowance greater than or equal to the spending amount.

**MMB design implication:** The Signer wallet must call `USDC.approve(CTFExchange, MAX_UINT256)` once before the first MMB live order. This is a one-time on-chain transaction on Polygon — funder needs MATIC for gas (per OD-4: "Signer pays own MATIC for one-time approvals"). Add to Session 6 pre-deploy checklist.

### Trade lifecycle is async with retry semantics
`MATCHED → MINED → CONFIRMED` (terminal) with `RETRYING` and `FAILED` paths. MMB must not assume a fill is real until `CONFIRMED`. Inventory tracking should account for in-flight `MATCHED`/`MINED` trades as "provisional inventory" — counted toward the cap but not toward realized PnL.

## Decisions for Session 2

1. **Always use post-only=True** on every maker limit placement.
2. **Always set `neg_risk=False`** in order options for BTC 5m.
3. **Heartbeat loop is mandatory** — 5s cadence, 2-miss halt trigger. Add to Session 2 module sketch as a required dependency of MmRunner.
4. **Honor per-market tick + min size** — LadderPlanner reads from `client.get_tick_size()` / `client.get_neg_risk()` at strategy init per market.
5. **Assume zero maker fee for backtest math**; empirical probe in Session 3 + recalibrate before S.5 if non-zero.
6. **Treat in-flight trades as provisional inventory** — counts toward `MAX_INVENTORY_*` caps but not realized PnL until `CONFIRMED`.

## Deferred to Session 3 (empirical probes)

- Maker fee realized rate (probe order on a low-volume market).
- Cancel latency p50/p95/p99 (1000-cycle probe).
- Rate-limit ceiling for limit-place + cancel (raise ceiling until 429, log behavior).
- Heartbeat-miss → all-orders-cancelled behavior verification (intentional miss test).

## References

- [order-patterns.md](file:///Users/hamad/.claude/skills/agent-skills/order-patterns.md) — order types, post-only, cancel, heartbeat, errors
- [authentication.md](file:///Users/hamad/.claude/skills/agent-skills/authentication.md) — L1/L2/Builder auth, signature types
- [market-data.md](file:///Users/hamad/.claude/skills/agent-skills/market-data.md) — Gamma, Data API, CLOB orderbook, batch endpoints
- `state/research/bonereaper/weekly_events_2026-05-19.json` — fresh Gamma snapshot of 2,017 BTC 5m events confirming `negRisk: False`
- `memory/checkpoint_phase_1a.md` — OD-4 resolution: standard CLOB, no relayer, signature_type=2, Signer pays MATIC
- `memory/reference_polymarket.md` — repo + dev-doc pointers
- `design/S.1-market-maker-bot.md` — design lock this runbook closes the §5 items of
