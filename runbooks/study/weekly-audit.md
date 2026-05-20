# Bonereaper — 7-day BTC 5-min audit

**Decision:** **ABORT**  (strict: 7-day win-rate ≥ 60%)

Generated: 2026-05-19 15:12 UTC
Method: per-market enumeration via Polymarket Data API + Gamma API.

## Headline numbers

| Metric | Value |
|---|---|
| Resolved BTC 5m trades, last 7d | **21,630** |
| Wins | 11,016 |
| Win-rate | **50.93%** (95% CI [50.26%, 51.60%]) |
| Gross P&L | $+11,024.61 |
| Total notional | $765,956 |
| Avg trade size | 69.89 shares |
| Earliest trade | 2026-05-12 15:10:50+00:00 |
| Latest trade | 2026-05-19 15:03:59+00:00 |

## Coverage

- BTC 5-min markets enumerated (closed + resolved in window): **808**
- Markets where bonereaper traded: **723** (89%)

## Gate

| Criterion | Measured | Threshold | Pass? |
|---|---|---|---|
| 7-day BTC 5m win-rate | 50.93% | ≥ 60% | ❌ |
| 7-day BTC 5m trades | 21,630 | ≥ 500 | ✅ |
| 95% CI upper bound | 51.60% | ≥ 60% | ❌ |

## Method

1. Generated all `btc-updown-5m-<unix_ts>` slugs for the last 7 days deterministically (288 markets per day x 7 = 2,016 candidates).
2. Resolved each slug to event metadata via `/events?slug=` (Gamma API) — concurrency 16.
3. Filtered to events that are `closed=true` with valid `outcomePrices` (a "1" present means resolved).
4. For each closed market, fetched bonereaper's trades via `/trades?market=<conditionId>&user=<addr>` — one call per market, concurrency 16.
5. Per-trade win/loss = (won_token ? (1.0 - price) * size : (-price) * size) for BUY (mirrored for SELL).
6. Aggregated.

## Caveats

- **Fees not subtracted.** Polymarket V2 charges ~7.2 bps taker (per market schedule). Net P&L is gross_pnl - fees; for win-rate as a *prediction* metric, fees do not affect the ratio.
- **Survivorship of resolved markets.** Open markets in the last 7d are excluded — they're not yet labeled. Bonereaper's recent trades on still-open markets are absent from this audit.
- **Per-market trade endpoint scope.** We assume each call returns ALL of bonereaper's trades on that market. Validated empirically: typical per-market footprint is 5-50 trades, well under the 500 cap.
