---
title: Chainlink BTC/USD on Polygon
tags: [concept, oracle, polygon, foundational-thesis]
---

# Chainlink BTC/USD on Polygon

> The oracle that resolves every BTC 5-min market on Polymarket. **60-second heartbeat, no deviation threshold.** This is the foundational thesis.

## Why it matters

Per `pdfs/MASTERPLAN.md` thesis:

> The exploitable inefficiency is Chainlink BTC/USD on Polygon's **60-second heartbeat with no deviation threshold**. Spot can move 0.3-0.5% while the oracle is silent. Combined with thin orderbooks and last-10-second decision dynamics, that's the edge.

Without this property, the strategy doesn't work. With it, [[oracle-gap]] becomes a tradeable signal and [[window-delta]] gains predictive power because the oracle's eventual reading lags spot.

## Mechanics

- **Heartbeat:** every 60 seconds, the Chainlink aggregator updates whether or not there's been a deviation.
- **Deviation threshold:** none on Polygon BTC/USD. Other chains (e.g. Ethereum mainnet) often have a 0.5% deviation trigger that updates more frequently. Polygon does not.
- **Resolution semantics:** every BTC 5-min market resolves on the snapshot of Chainlink BTC/USD at exactly `window_ts + 300`. If the oracle hasn't updated within that 300s, the resolution uses the most recent answer.
- **Reorg risk:** Polygon has rare but possible reorgs that can rewrite the last-answer briefly. We assume the oracle's reported value is canonical.

## Verification (Phase 2 task)

The thesis claim ("60s heartbeat, no deviation") was originally going to be verified empirically in Phase 2 — that's still a Phase 2 deliverable. We capture 7 days of `AnswerUpdated` events from the on-chain aggregator (`0xc907E116054Ad103354f2D350FD2514433D57F6f` on Polygon) and verify:
- Median inter-update gap ∈ [55s, 65s]
- Zero sub-30s updates (those would be deviation-triggered, would shrink the lag window)
- Sub-60s updates < 5% of total

If verification fails, the thesis needs revision. Phase 2 audit can stop the bot before any money is at risk (this is exactly what the [[../phases/phase-1-wallet-auth|1A/1B split]] also enables — paper-trade through Phase 4 first, fund only after the thesis verifies).

## Aggregator address

```
Polygon mainnet:  0xc907E116054Ad103354f2D350FD2514433D57F6f
```

Public dashboard: [data.chain.link/feeds/polygon/mainnet/btc-usd](https://data.chain.link/feeds/polygon/mainnet/btc-usd)

## Subscription pattern

Phase 2 implements `src/polymarket_bot/_live/feeds/oracle.py`:
- WebSocket subscription via Alchemy RPC (`wss://polygon-mainnet.g.alchemy.com/...`).
- Subscribe to `AnswerUpdated` event topic on the aggregator address.
- Each event: `(int256 current, uint256 roundId, uint256 updatedAt)`.
- Archive every event into Parquet with timestamp + block number.

## See also

- [[oracle-gap]] — the signal we derive from the lag
- [[window-delta]] — the complementary signal
- [[tier-3-deterministic]] — the strategy that uses these
- [[polymarket-data-sources]] — the broader data source taxonomy
- [[../research/data-sources-map]] — Polygon RPC entry
