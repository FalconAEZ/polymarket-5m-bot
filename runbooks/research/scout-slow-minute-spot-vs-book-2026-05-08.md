# Bonereaper spot-vs-book correlation

Run date: 2026-05-08. Input bonereaper trades: 176. Joined with captured BTC spot: 155. Skipped: 21 ({'no_spot_data': 21}). Fetch+join time: 0.0s.

**Question under test:** does Bonereaper use BTC spot information to pick a side? Test: for each trade, compare entry-time spot to window-open spot, compute Δ_bps = 10000x(St - S0)/S0, classify alignment (UP+Δ>0 OR DOWN+Δ<0 = aligned; opposite = contrarian; Δ≈0 = flat), and look at win-rate per alignment bucket and per Δ_bps bucket.

## Headline

- **155 trades** with spot data joined
- Win rate: **98.1%** (152/155)
- Gross notional: $239,657.89
- Gross PnL: $-612.34

## By alignment (the main test)

| alignment | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| aligned | 146 | 98.6% | $224,503 | $-276 | $-1.89 |
| contrarian | 9 | 88.9% | $15,155 | $-337 | $-37.41 |

## By Δ_bps bucket (entry-time spot move since window open)

| Δ_bps bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| -50..-20bps | 1 | 100.0% | $2,970 | $+30 | $+30.00 |
| -20..-10bps | 17 | 100.0% | $26,297 | $+301 | $+17.72 |
| -10..-5bps | 27 | 100.0% | $41,344 | $+587 | $+21.74 |
| -5..+5bps (flat) | 63 | 98.4% | $96,405 | $+672 | $+10.67 |
| +5..+10bps | 28 | 92.9% | $48,802 | $-2,456 | $-87.71 |
| +10..+20bps | 18 | 100.0% | $20,871 | $+223 | $+12.40 |
| +20..+50bps | 1 | 100.0% | $2,970 | $+30 | $+30.00 |

## By side x Δ_bps (does UP bet win more when spot moves up?)

| side | Δ bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| UP | -5..+5bps (flat) | 33 | 97.0% | $48,478 | $+185 | $+5.61 |
| UP | +5..+10bps | 28 | 92.9% | $48,802 | $-2,456 | $-87.71 |
| UP | +10..+20bps | 18 | 100.0% | $20,871 | $+223 | $+12.40 |
| DOWN | -20..-10bps | 17 | 100.0% | $26,297 | $+301 | $+17.72 |
| DOWN | -10..-5bps | 26 | 100.0% | $39,364 | $+567 | $+21.81 |
| DOWN | -5..+5bps (flat) | 30 | 100.0% | $47,927 | $+487 | $+16.24 |

## By alignment x price tier (where the alignment edge lands)

| alignment | price tier | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| aligned | 85-100% | 146 | 98.6% | $224,503 | $-276 | $-1.89 |
| contrarian | 85-100% | 9 | 88.9% | $15,155 | $-337 | $-37.41 |

## Verdict

- **Insufficient sample** (<50 trades in either alignment bucket). Need broader spot-tick capture.

## Caveats

- Spot lookup is forward-fill within 30s. Accuracy degrades on sparse-tick periods; a 5s gap to a 1-bp move shouldn't change bucket assignment but could on edge cases.
- Binance ticks only. Coinbase + oracle would refine but the Binance feed dominates BTC volume so this is a reasonable proxy.
- Captured spot covers a tiny window of bonereaper's full activity. Findings here are suggestive, not conclusive.
- Δ_bps is computed entry vs window-open, not entry vs immediate-prior. A trade entering at t=200s with the price unchanged from window-open but having round-tripped is bucketed as 'flat' even though the path was volatile.
