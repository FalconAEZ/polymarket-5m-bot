# Bonereaper spot-vs-book correlation

Run date: 2026-05-08. Input bonereaper trades: 90. Joined with captured BTC spot: 88. Skipped: 2 ({'no_spot_data': 2}). Fetch+join time: 0.0s.

**Question under test:** does Bonereaper use BTC spot information to pick a side? Test: for each trade, compare entry-time spot to window-open spot, compute Δ_bps = 10000x(St - S0)/S0, classify alignment (UP+Δ>0 OR DOWN+Δ<0 = aligned; opposite = contrarian; Δ≈0 = flat), and look at win-rate per alignment bucket and per Δ_bps bucket.

## Headline

- **88 trades** with spot data joined
- Win rate: **93.2%** (82/88)
- Gross notional: $9,680.90
- Gross PnL: $-187.24

## By alignment (the main test)

| alignment | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| aligned | 86 | 93.0% | $9,382 | $-195 | $-2.27 |
| contrarian | 2 | 100.0% | $299 | $+8 | $+3.84 |

## By Δ_bps bucket (entry-time spot move since window open)

| Δ_bps bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| -50..-20bps | 2 | 100.0% | $151 | $+2 | $+0.80 |
| -20..-10bps | 9 | 100.0% | $1,333 | $+35 | $+3.88 |
| -10..-5bps | 17 | 100.0% | $1,949 | $+87 | $+5.14 |
| -5..+5bps (flat) | 26 | 80.8% | $2,786 | $-283 | $-10.87 |
| +5..+10bps | 22 | 95.5% | $2,338 | $-75 | $-3.41 |
| +10..+20bps | 11 | 100.0% | $975 | $+45 | $+4.11 |
| +20..+50bps | 1 | 100.0% | $149 | $+2 | $+1.51 |

## By side x Δ_bps (does UP bet win more when spot moves up?)

| side | Δ bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| UP | -5..+5bps (flat) | 15 | 86.7% | $1,378 | $-108 | $-7.20 |
| UP | +5..+10bps | 22 | 95.5% | $2,338 | $-75 | $-3.41 |
| UP | +10..+20bps | 11 | 100.0% | $975 | $+45 | $+4.11 |
| DOWN | -20..-10bps | 9 | 100.0% | $1,333 | $+35 | $+3.88 |
| DOWN | -10..-5bps | 17 | 100.0% | $1,949 | $+87 | $+5.14 |
| DOWN | -5..+5bps (flat) | 11 | 72.7% | $1,408 | $-175 | $-15.89 |

## By alignment x price tier (where the alignment edge lands)

| alignment | price tier | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| aligned | 85-100% | 85 | 92.9% | $9,380 | $-199 | $-2.34 |

## Verdict

- **Insufficient sample** (<50 trades in either alignment bucket). Need broader spot-tick capture.

## Caveats

- Spot lookup is forward-fill within 30s. Accuracy degrades on sparse-tick periods; a 5s gap to a 1-bp move shouldn't change bucket assignment but could on edge cases.
- Binance ticks only. Coinbase + oracle would refine but the Binance feed dominates BTC volume so this is a reasonable proxy.
- Captured spot covers a tiny window of bonereaper's full activity. Findings here are suggestive, not conclusive.
- Δ_bps is computed entry vs window-open, not entry vs immediate-prior. A trade entering at t=200s with the price unchanged from window-open but having round-tripped is bucketed as 'flat' even though the path was volatile.
