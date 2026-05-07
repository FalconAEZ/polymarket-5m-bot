# Bonereaper microstructure — entry-time vs resolution-time

Run date: 2026-05-07. Wallet: `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`. Lookback: 30 days. Markets enumerated: 8637; markets with bonereaper trades: 8214. Trades analysed: 306997. Fetch time: 1309.0s.

**Hypothesis under test (operator's 2026-05-08 framing):** Bonereaper is a *late-window favorite sniper* — most fills at >=70¢ entry land in the final 30-60s of a 5-min window, exploiting spot-vs-book lag on near-certain resolutions.

## Headline

- **306,997 trades** on BTC 5-min markets in the last 30 days
- **Win rate:** 51.7% (158,724/306,997)
- **Gross notional:** $12,134,677.54
- **Gross PnL:** $+234,905.96 (excludes fees / settlement gas)

## Distribution by time-before-resolution

Bucket = `(window_ts + 300) - trade.ts`. Lower = closer to resolution.

| time bucket | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| 0-30s | 9,399 | 49.0% | $1,497,414 | $+12,818 | $+1.36 |
| 30-60s | 21,631 | 48.8% | $1,810,484 | $+13,942 | $+0.64 |
| 60-120s | 55,581 | 49.5% | $2,835,275 | $+44,976 | $+0.81 |
| 120-180s | 62,688 | 51.2% | $2,034,018 | $+33,277 | $+0.53 |
| 180-240s | 69,772 | 52.6% | $1,831,054 | $+50,284 | $+0.72 |
| 240-300s | 87,312 | 53.9% | $2,064,843 | $+82,475 | $+0.94 |
| >300s (post-resolve) | 614 | 37.8% | $61,589 | $-2,865 | $-4.67 |

## Distribution by entry price tier

Mirrors the predicts.guru breakdown the operator shared.

| price tier | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| <15% | 17,498 | 10.1% | $173,271 | $+14,046 | $+0.80 |
| 15-30% | 38,870 | 24.5% | $466,306 | $+24,189 | $+0.62 |
| 30-50% | 89,842 | 43.5% | $1,568,684 | $+92,508 | $+1.03 |
| 50-70% | 106,471 | 60.1% | $2,748,079 | $+73,240 | $+0.69 |
| 70-85% | 38,176 | 77.5% | $1,713,417 | $+15,222 | $+0.40 |
| 85-100% | 16,140 | 91.8% | $5,464,920 | $+15,702 | $+0.97 |

## Joint table — price tier x time-before-resolution

**This is the hypothesis test.** If the cell at `>=70%` x `0-30s` (or `30-60s`) holds the bulk of trades AND has the highest per-trade PnL, the late-window favorite-sniping thesis is confirmed.

| price tier | metric | 0-30s | 30-60s | 60-120s | 120-180s | 180-240s | 240-300s | >300s (post-resolve) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| <15% | trades | 2,077 | 3,791 | 6,006 | 3,717 | 1,477 | 129 | 301 |
| <15% | win-rate | 10.3% | 9.9% | 10.5% | 9.9% | 10.6% | 7.8% | 3.3% |
| <15% | per-trade PnL | $+4.68 | $+1.19 | $+1.10 | $-0.51 | $-1.43 | $-5.82 | $-6.84 |
| 15-30% | trades | 1,552 | 3,970 | 9,717 | 10,622 | 9,427 | 3,556 | 26 |
| 15-30% | win-rate | 24.4% | 23.2% | 25.7% | 23.8% | 24.4% | 25.5% | 30.8% |
| 15-30% | per-trade PnL | $+1.66 | $+0.30 | $+1.58 | $+0.15 | $+0.26 | $+0.25 | $+6.00 |
| 30-50% | trades | 1,636 | 4,351 | 13,763 | 17,410 | 22,059 | 30,554 | 69 |
| 30-50% | win-rate | 41.4% | 44.3% | 40.3% | 42.9% | 42.4% | 46.0% | 52.2% |
| 30-50% | per-trade PnL | $+0.16 | $+1.66 | $+0.06 | $+1.15 | $+0.81 | $+1.50 | $+5.58 |
| 50-70% | trades | 1,413 | 3,859 | 13,180 | 16,968 | 23,985 | 46,985 | 81 |
| 50-70% | win-rate | 61.2% | 62.9% | 61.6% | 61.2% | 61.1% | 58.3% | 66.7% |
| 50-70% | per-trade PnL | $+0.30 | $+0.73 | $+0.60 | $+0.55 | $+0.83 | $+0.70 | $+1.67 |
| 70-85% | trades | 1,015 | 2,857 | 7,794 | 10,012 | 10,637 | 5,770 | 91 |
| 70-85% | win-rate | 81.7% | 80.4% | 77.4% | 77.9% | 77.4% | 75.0% | 85.7% |
| 70-85% | per-trade PnL | $+2.04 | $+0.46 | $+0.00 | $+0.38 | $+0.75 | $+0.33 | $-20.30 |
| 85-100% | trades | 1,706 | 2,803 | 5,121 | 3,959 | 2,187 | 318 | 46 |
| 85-100% | win-rate | 96.1% | 92.7% | 91.8% | 90.2% | 89.7% | 92.8% | 100.0% |
| 85-100% | per-trade PnL | $-1.32 | $-1.11 | $+2.80 | $+0.08 | $+1.89 | $+5.94 | $+7.95 |

## Verdict

- Of all trades at entry price >=70%, **15.4%** (8,381/54,316) land in the final 60s of their window.
- **Hypothesis REJECTED**: bonereaper's favorite-tier fills are not concentrated in the final minute. Strategy lives somewhere else. Re-examine assumptions before pursuing further.

## Caveats

- Lookback is **last N days only**; the dataset is a slice of bonereaper's much larger history. predicts.guru shows ~$82M lifetime volume; this audit samples a tiny fraction. Don't generalise too hard.
- 5-min markets only (slug `btc-updown-5m-`). Bonereaper also trades 15m and 1h BTC markets; their behaviour there could be different.
- Trade timestamps come from Polymarket Data API (off-chain) and reflect matcher-side timestamps, not on-chain confirmation. Drift of a few seconds is possible but won't change a 30s vs 240s answer.
- Fees and settlement gas are NOT subtracted from gross PnL. Bonereaper's real PnL is lower than the gross numbers above.
