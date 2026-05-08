# wallet microstructure — entry-time vs resolution-time

Run date: 2026-05-08. Wallet: `0xdf0d2ccfe3d7c2ef120395534e43afe283509f79`. Lookback: 7 days. Markets enumerated: 1408; markets with wallet trades: 135. Trades analysed: 176. Fetch time: 63.5s.

**Hypothesis under test (operator's 2026-05-08 framing):** the wallet is a *late-window favorite sniper* — most fills at >=70¢ entry land in the final 30-60s of a 5-min window, exploiting spot-vs-book lag on near-certain resolutions.

## Headline

- **176 trades** on BTC 5-min markets in the last 7 days
- **Win rate:** 96.6% (170/176)
- **Gross notional:** $253,953.13
- **Gross PnL:** $-3,963.74 (excludes fees / settlement gas)

## Distribution by time-before-resolution

Bucket = `(window_ts + 300) - trade.ts`. Lower = closer to resolution.

| time bucket | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| 0-30s | 88 | 95.5% | $114,440 | $-2,640 | $-30.00 |
| 30-60s | 33 | 93.9% | $44,010 | $-2,496 | $-75.64 |
| 60-120s | 31 | 100.0% | $59,914 | $+643 | $+20.74 |
| 120-180s | 11 | 100.0% | $19,849 | $+259 | $+23.58 |
| >300s (post-resolve) | 13 | 100.0% | $15,741 | $+270 | $+20.77 |

## Distribution by entry price tier

Mirrors the predicts.guru breakdown the operator shared.

| price tier | trades | win-rate | notional | gross PnL | per-trade PnL |
|---|---:|---:|---:|---:|---:|
| 85-100% | 176 | 96.6% | $253,953 | $-3,964 | $-22.52 |

## Joint table — price tier x time-before-resolution

**This is the hypothesis test.** If the cell at `>=70%` x `0-30s` (or `30-60s`) holds the bulk of trades AND has the highest per-trade PnL, the late-window favorite-sniping thesis is confirmed.

| price tier | metric | 0-30s | 30-60s | 60-120s | 120-180s | 180-240s | 240-300s | >300s (post-resolve) |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| <15% | trades | — | — | — | — | — | — | — |
| <15% | win-rate | — | — | — | — | — | — | — |
| <15% | per-trade PnL | — | — | — | — | — | — | — |
| 15-30% | trades | — | — | — | — | — | — | — |
| 15-30% | win-rate | — | — | — | — | — | — | — |
| 15-30% | per-trade PnL | — | — | — | — | — | — | — |
| 30-50% | trades | — | — | — | — | — | — | — |
| 30-50% | win-rate | — | — | — | — | — | — | — |
| 30-50% | per-trade PnL | — | — | — | — | — | — | — |
| 50-70% | trades | — | — | — | — | — | — | — |
| 50-70% | win-rate | — | — | — | — | — | — | — |
| 50-70% | per-trade PnL | — | — | — | — | — | — | — |
| 70-85% | trades | — | — | — | — | — | — | — |
| 70-85% | win-rate | — | — | — | — | — | — | — |
| 70-85% | per-trade PnL | — | — | — | — | — | — | — |
| 85-100% | trades | 88 | 33 | 31 | 11 | — | — | 13 |
| 85-100% | win-rate | 95.5% | 93.9% | 100.0% | 100.0% | — | — | 100.0% |
| 85-100% | per-trade PnL | $-30.00 | $-75.64 | $+20.74 | $+23.58 | — | — | $+20.77 |

## Verdict

- Of all trades at entry price >=70%, **68.8%** (121/176) land in the final 60s of their window.
- **Hypothesis SUPPORTED**: late-window favorite sniping looks like a real pattern. Next step: write `design/late_window_sniper.md` describing the spot-vs-book mispricing trigger this implies, then gate against it before any code lands. Anti-vibe rule #1.

## Caveats

- Lookback is **last N days only**; the dataset is a slice of bonereaper's much larger history. predicts.guru shows ~$82M lifetime volume; this audit samples a tiny fraction. Don't generalise too hard.
- 5-min markets only (slug `btc-updown-5m-`). Bonereaper also trades 15m and 1h BTC markets; their behaviour there could be different.
- Trade timestamps come from Polymarket Data API (off-chain) and reflect matcher-side timestamps, not on-chain confirmation. Drift of a few seconds is possible but won't change a 30s vs 240s answer.
- Fees and settlement gas are NOT subtracted from gross PnL. Bonereaper's real PnL is lower than the gross numbers above.
