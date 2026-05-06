# Bonereaper — 7-day BTC 5-min audit

**Decision:** **ABORT**  (strict: 7-day win-rate ≥ 60%)

Generated: 2026-05-06 06:15 UTC
Method: per-market enumeration via Polymarket Data API + Gamma API.

## Headline numbers

| Metric | Value |
|---|---|
| Resolved BTC 5m trades, last 7d | **56,972** |
| Wins | 29,995 |
| Win-rate | **52.65%** (95% CI [52.24%, 53.06%]) |
| Gross P&L | $+31,053.53 |
| Total notional | $2,344,672 |
| Avg trade size | 70.14 shares |
| Earliest trade | 2026-04-29 06:11:14+00:00 |
| Latest trade | 2026-05-06 06:04:06+00:00 |

## Coverage

- BTC 5-min markets enumerated (closed + resolved in window): **2,015**
- Markets where bonereaper traded: **1,927** (96%)

## Gate

| Criterion | Measured | Threshold | Pass? |
|---|---|---|---|
| 7-day BTC 5m win-rate | 52.65% | ≥ 60% | ❌ |
| 7-day BTC 5m trades | 56,972 | ≥ 500 | ✅ |
| 95% CI upper bound | 53.06% | ≥ 60% | ❌ |

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
