# wallet microstructure — entry-time vs resolution-time

Run date: 2026-05-08. Wallet: `0x88f17731836942b533f33958a302fb4c31bad3d0`. Lookback: 7 days. Markets enumerated: 893; markets with wallet trades: 55. Trades analysed: 90. Fetch time: 40.2s.

**Hypothesis under test (operator's 2026-05-08 framing):** the wallet is a *late-window favorite sniper* — most fills at >=70¢ entry land in the final 30-60s of a 5-min window, exploiting spot-vs-book lag on near-certain resolutions.

## Headline

- **90 trades** on BTC 5-min markets in the last 7 days
- **Win rate:** 93.3% (84/90)
- **Gross notional:** $9,980.33
- **Gross PnL:** $-182.67 (excludes fees / settlement gas)

## Distribution by time-before-resolution

Bucket = `(window_ts + 300) - trade.ts`. Lower = closer to resolution.

| time bucket | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| 0-30s | 13 | 92.3% | $1,325 | $-37 | $-2.88 |
| 30-60s | 12 | 100.0% | $1,510 | $+22 | $+1.85 |
| 60-120s | 33 | 87.9% | $3,756 | $-325 | $-9.85 |
| 120-180s | 21 | 95.2% | $2,204 | $+91 | $+4.31 |
| 180-240s | 10 | 100.0% | $1,184 | $+63 | $+6.34 |
| >300s (post-resolve) | 1 | 100.0% | $2 | $+4 | $+3.72 |

## Distribution by entry price tier

Mirrors the predicts.guru breakdown the operator shared.

| price tier | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| 15-30% | 1 | 100.0% | $2 | $+4 | $+3.72 |
| 85-100% | 89 | 93.3% | $9,979 | $-186 | $-2.09 |

## Joint table — price tier x time-before-resolution

**This is the hypothesis test.** If the cell at `>=70%` x `0-30s` (or `30-60s`) holds the bulk of trades AND has the highest per-trade PnL, the late-window favorite-sniping thesis is confirmed.

| price tier | metric | 0-30s | 30-60s | 60-120s | 120-180s | 180-240s | 240-300s | >300s (post-resolve) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| <15% | trades | — | — | — | — | — | — | — |
| <15% | win-rate | — | — | — | — | — | — | — |
| <15% | per-trade PnL | — | — | — | — | — | — | — |
| 15-30% | trades | — | — | — | — | — | — | 1 |
| 15-30% | win-rate | — | — | — | — | — | — | 100.0% |
| 15-30% | per-trade PnL | — | — | — | — | — | — | $+3.72 |
| 30-50% | trades | — | — | — | — | — | — | — |
| 30-50% | win-rate | — | — | — | — | — | — | — |
| 30-50% | per-trade PnL | — | — | — | — | — | — | — |
| 50-70% | trades | — | — | — | — | — | — | — |
| 50-70% | win-rate | — | — | — | — | — | — | — |
| 50-70% | per-trade PnL | — | — | — | — | — | — | — |
| 70-85% | trades | — | — | — | — | — | — | — |
| 70-85% | win-rate | — | — | — | — | — | — | — |
| 70-85% | per-trade PnL | — | — | — | — | — | — | — |
| 85-100% | trades | 13 | 12 | 33 | 21 | 10 | — | — |
| 85-100% | win-rate | 92.3% | 100.0% | 87.9% | 95.2% | 100.0% | — | — |
| 85-100% | per-trade PnL | $-2.88 | $+1.85 | $-9.85 | $+4.31 | $+6.34 | — | — |

## Verdict

- Of all trades at entry price >=70%, **28.1%** (25/89) land in the final 60s of their window.
- **Hypothesis WEAK**: some concentration in the final 60s but not decisive. Pull more data (longer lookback) or look at alternative patterns (15m or 1h markets, off-hours regime, etc.).

## Caveats

- Lookback is **last N days only**; the dataset is a slice of bonereaper's much larger history. predicts.guru shows ~$82M lifetime volume; this audit samples a tiny fraction. Don't generalise too hard.
- 5-min markets only (slug `btc-updown-5m-`). Bonereaper also trades 15m and 1h BTC markets; their behaviour there could be different.
- Trade timestamps come from Polymarket Data API (off-chain) and reflect matcher-side timestamps, not on-chain confirmation. Drift of a few seconds is possible but won't change a 30s vs 240s answer.
- Fees and settlement gas are NOT subtracted from gross PnL. Bonereaper's real PnL is lower than the gross numbers above.
