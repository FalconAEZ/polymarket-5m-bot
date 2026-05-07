---
title: Audit pipeline recipe (per-market enumeration)
tags: [research, methodology, reusable]
---

# Audit pipeline recipe

> The **per-market enumeration** method that worked for Phase A's 7-day audit. Reusable on any wallet, any market type, ~10 minutes for $0.

## The recipe in 5 steps

1. **Generate candidate market slugs deterministically.** For BTC 5-min markets, every 5 minutes corresponds to a window timestamp:
   ```python
   for ts in range(now − 7*86400, now, 300):
       slug = f"btc-updown-5m-{ts}"
   ```
   That's exactly 2,016 candidates per week, no API calls needed.

2. **Resolve each slug to event metadata via Gamma API** (`/events?slug=<slug>`). With concurrency 16, this completes in ~30 seconds. Filter to `closed=true` markets with valid `outcomePrices` (a "1" present means resolved with a winner).

3. **For each closed market, query bonereaper's trades** via the combined-filter endpoint:
   ```
   GET https://data-api.polymarket.com/trades?market=<conditionId>&user=<addr>&limit=500
   ```
   This is the magic: the user filter narrows results well below the 500-row cap, so one call per market gets every fill that user made on that market. With concurrency 16, 2,000 markets complete in ~60 seconds.

4. **Per-trade win/loss labelling.** For each trade, the market's `outcomes` and `outcomePrices` tell you which outcome won. Cross-reference with the trade's `outcome` field:
   ```
   won_token = outcomePrices[traded_outcome_idx] == "1"
   if side == "BUY":
       gross_pnl = (1.0 − price) * size if won_token else −price * size
   ```

5. **Aggregate.** Win-rate, P&L, volume, time-of-day distribution, market coverage. With 56k+ trades, all confidence intervals are tight (±0.4 pp at 95%).

## Why other recipes failed

- **Data API user-trades** caps at offset 3,500. With high-frequency wallets that's ~3 hours of history. Useless for 7-day analysis. (See [[../concepts/polymarket-data-sources|data sources taxonomy]].)
- **Goldsky orderbook subgraph** only indexes the legacy CTF Exchange. Bonereaper's recent activity is on the NegRisk Exchange. Returns zero relevant fills.
- **Direct Polygon RPC** would work but requires ABI decoding, log filtering by topic, and per-event chain queries. ~1 hour to implement vs ~10 minutes for the per-market recipe.

## Generalizing to other audit targets

The recipe works for **any wallet, any market type that has a deterministic slug pattern**:

- ETH 5-min markets: `eth-updown-5m-<ts>`
- ETH 15-min markets: `eth-updown-15m-<ts>`
- Sports markets, etc.: deterministic patterns documented per Polymarket's slug conventions.

To audit a new wallet:
1. Replace `BONEREAPER_ADDR` in `scripts/research/weekly_audit.py` with the new address.
2. Adjust the slug prefix if studying a different market type.
3. Run. Re-runs same-day are cache-instant.

## Caveats

- **Open markets are skipped.** Trades on still-open markets aren't labelled because their outcomes aren't known yet. For 7-day windows this is rare (most markets resolve in 5 min).
- **Fees not subtracted.** Polymarket V2 charges ~7.2 bps taker. Net P&L = `gross_pnl − fees`. For win-rate as a *prediction* metric, fees don't affect the ratio.
- **Per-market footprint assumed under 500.** Validated empirically for bonereaper (~5-50 trades per market). For mass-volume market-makers this might break.
- **Combined filter behavior.** The `?market=&user=` combined filter has worked reliably as of 2026-05-06; if Polymarket changes API behavior, this recipe needs revalidation.

## Files

- `scripts/research/weekly_audit.py` — full implementation
- `scripts/research/_api.py` — `fetch_event_by_slug_simple`, `fetch_user_trades_on_market` helpers
- `runbooks/gates/study-A.sh` — gate script using the output

## See also

- [[bonereaper-study-postmortem]] — what we learned from running this on bonereaper
- [[data-sources-map]] — the broader taxonomy
- [[../concepts/polymarket-data-sources]] — concept-level summary
- [[../phases/phase-A-bonereaper]] — Phase A summary that this powered
