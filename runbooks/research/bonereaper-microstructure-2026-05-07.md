# Bonereaper microstructure — entry-time vs resolution-time

Run date: 2026-05-07. Wallet: `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`. Lookback: 7 days. Markets enumerated: 2017; markets with bonereaper trades: 1950. Trades analysed: 60500. Fetch time: 265.0s.

**Hypothesis under test (operator's 2026-05-08 framing):** Bonereaper is a *late-window favorite sniper* — most fills at >=70¢ entry land in the final 30-60s of a 5-min window, exploiting spot-vs-book lag on near-certain resolutions.

## Headline

- **60,500 trades** on BTC 5-min markets in the last 7 days
- **Win rate:** 52.3% (31,668/60,500)
- **Gross notional:** $2,764,351.24
- **Gross PnL:** $+37,558.39 (excludes fees / settlement gas)

## Distribution by time-before-resolution

Bucket = `(window_ts + 300) - trade.ts`. Lower = closer to resolution.

| time bucket | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| 0-30s | 2,000 | 51.9% | $321,106 | $+4,663 | $+2.33 |
| 30-60s | 4,365 | 48.1% | $472,260 | $-3,836 | $-0.88 |
| 60-120s | 10,805 | 50.6% | $714,422 | $+7,194 | $+0.67 |
| 120-180s | 12,557 | 52.7% | $463,842 | $+11,486 | $+0.91 |
| 180-240s | 13,930 | 53.3% | $387,663 | $+11,005 | $+0.79 |
| 240-300s | 16,692 | 53.8% | $387,857 | $+10,832 | $+0.65 |
| >300s (post-resolve) | 151 | 33.8% | $17,201 | $-3,785 | $-25.07 |

## Distribution by entry price tier

Mirrors the predicts.guru breakdown the operator shared.

| price tier | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| <15% | 4,147 | 10.0% | $37,172 | $+2,236 | $+0.54 |
| 15-30% | 7,562 | 24.8% | $89,262 | $+5,671 | $+0.75 |
| 30-50% | 16,715 | 43.8% | $280,364 | $+14,856 | $+0.89 |
| 50-70% | 19,756 | 59.7% | $492,161 | $+7,754 | $+0.39 |
| 70-85% | 7,751 | 77.5% | $361,268 | $-1,482 | $-0.19 |
| 85-100% | 4,569 | 93.1% | $1,504,124 | $+8,523 | $+1.87 |

## Joint table — price tier x time-before-resolution

**This is the hypothesis test.** If the cell at `>=70%` x `0-30s` (or `30-60s`) holds the bulk of trades AND has the highest per-trade PnL, the late-window favorite-sniping thesis is confirmed.

| price tier | metric | 0-30s | 30-60s | 60-120s | 120-180s | 180-240s | 240-300s | >300s (post-resolve) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| <15% | trades | 459 | 875 | 1,451 | 908 | 351 | 28 | 75 |
| <15% | win-rate | 11.1% | 8.5% | 11.0% | 9.4% | 11.7% | 10.7% | 0.0% |
| <15% | per-trade PnL | $+3.53 | $-1.31 | $+2.37 | $-0.31 | $+0.48 | $-4.23 | $-19.27 |
| 15-30% | trades | 305 | 723 | 1,894 | 2,038 | 1,889 | 704 | 9 |
| 15-30% | win-rate | 25.2% | 23.5% | 25.2% | 23.4% | 24.6% | 29.3% | 33.3% |
| 15-30% | per-trade PnL | $+1.99 | $+0.48 | $+1.43 | $-0.06 | $+0.26 | $+2.48 | $-10.49 |
| 30-50% | trades | 308 | 806 | 2,334 | 3,245 | 4,232 | 5,772 | 18 |
| 30-50% | win-rate | 43.5% | 39.7% | 42.4% | 45.1% | 41.6% | 45.9% | 44.4% |
| 30-50% | per-trade PnL | $+0.91 | $-1.10 | $+0.54 | $+1.54 | $+0.22 | $+1.46 | $-7.27 |
| 50-70% | trades | 280 | 696 | 2,226 | 3,201 | 4,585 | 8,756 | 12 |
| 50-70% | win-rate | 63.2% | 61.4% | 61.8% | 60.3% | 62.1% | 57.5% | 58.3% |
| 50-70% | per-trade PnL | $+1.78 | $-1.64 | $+0.31 | $+0.42 | $+1.18 | $+0.13 | $-12.59 |
| 70-85% | trades | 187 | 483 | 1,465 | 1,949 | 2,291 | 1,355 | 21 |
| 70-85% | win-rate | 85.6% | 76.4% | 77.3% | 79.0% | 77.8% | 74.2% | 81.0% |
| 70-85% | per-trade PnL | $+6.28 | $-4.30 | $-1.39 | $+1.27 | $+0.84 | $-0.63 | $-99.00 |
| 85-100% | trades | 461 | 782 | 1,435 | 1,216 | 582 | 77 | 16 |
| 85-100% | win-rate | 95.2% | 94.4% | 92.6% | 92.4% | 91.9% | 93.5% | 100.0% |
| 85-100% | per-trade PnL | $+1.04 | $+1.36 | $+0.80 | $+2.54 | $+3.64 | $+6.51 | $+7.19 |

## Verdict

- Of all trades at entry price >=70%, **15.5%** (1,913/12,320) land in the final 60s of their window.
- **Hypothesis REJECTED**: bonereaper's favorite-tier fills are not concentrated in the final minute. Strategy lives somewhere else. Re-examine assumptions before pursuing further.

## Caveats

- Lookback is **last N days only**; the dataset is a slice of bonereaper's much larger history. predicts.guru shows ~$82M lifetime volume; this audit samples a tiny fraction. Don't generalise too hard.
- 5-min markets only (slug `btc-updown-5m-`). Bonereaper also trades 15m and 1h BTC markets; their behaviour there could be different.
- Trade timestamps come from Polymarket Data API (off-chain) and reflect matcher-side timestamps, not on-chain confirmation. Drift of a few seconds is possible but won't change a 30s vs 240s answer.
- Fees and settlement gas are NOT subtracted from gross PnL. Bonereaper's real PnL is lower than the gross numbers above.
