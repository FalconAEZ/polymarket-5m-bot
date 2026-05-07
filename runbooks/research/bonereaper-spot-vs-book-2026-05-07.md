# Bonereaper spot-vs-book correlation

Run date: 2026-05-07. Input bonereaper trades: 60,500. Joined with captured BTC spot: 837. Skipped: 59,663 ({'no_spot_data': 59663}). Fetch+join time: 0.2s.

**Question under test:** does Bonereaper use BTC spot information to pick a side? Test: for each trade, compare entry-time spot to window-open spot, compute Δ_bps = 10000x(St - S0)/S0, classify alignment (UP+Δ>0 OR DOWN+Δ<0 = aligned; opposite = contrarian; Δ≈0 = flat), and look at win-rate per alignment bucket and per Δ_bps bucket.

## Headline

- **837 trades** with spot data joined
- Win rate: **55.2%** (462/837)
- Gross notional: $55,571.31
- Gross PnL: $+1,640.17

## By alignment (the main test)

| alignment | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| aligned | 459 | 78.0% | $49,815 | $+3,260 | $+7.10 |
| contrarian | 334 | 25.1% | $4,893 | $-1,510 | $-4.52 |
| flat | 44 | 45.5% | $863 | $-110 | $-2.51 |

**Aligned vs contrarian win-rate gap:** +52.8% (aligned 78.0% vs contrarian 25.1%).
→ **Suggests Bonereaper IS spot-aware** when picking sides.

## By Δ_bps bucket (entry-time spot move since window open)

| Δ_bps bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| -20..-10bps | 8 | 87.5% | $5,456 | $+84 | $+10.54 |
| -10..-5bps | 30 | 50.0% | $12,914 | $+69 | $+2.31 |
| -5..+5bps (flat) | 752 | 54.8% | $20,658 | $+1,286 | $+1.71 |
| +5..+10bps | 44 | 61.4% | $14,484 | $+192 | $+4.37 |
| +10..+20bps | 3 | 33.3% | $2,060 | $+9 | $+2.87 |

## By side x Δ_bps (does UP bet win more when spot moves up?)

| side | Δ bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| UP | -10..-5bps | 15 | 0.0% | $139 | $-139 | $-9.27 |
| UP | -5..+5bps (flat) | 398 | 46.7% | $8,690 | $-433 | $-1.09 |
| UP | +5..+10bps | 29 | 93.1% | $14,323 | $+353 | $+12.18 |
| DOWN | -20..-10bps | 7 | 100.0% | $5,447 | $+93 | $+13.32 |
| DOWN | -10..-5bps | 15 | 100.0% | $12,775 | $+208 | $+13.88 |
| DOWN | -5..+5bps (flat) | 354 | 63.8% | $11,968 | $+1,718 | $+4.85 |
| DOWN | +5..+10bps | 15 | 0.0% | $161 | $-161 | $-10.72 |

## By alignment x price tier (where the alignment edge lands)

| alignment | price tier | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| aligned | 30-50% | 66 | 77.3% | $1,122 | $+834 | $+12.64 |
| aligned | 50-70% | 238 | 70.2% | $5,394 | $+1,174 | $+4.93 |
| aligned | 70-85% | 103 | 86.4% | $4,569 | $+559 | $+5.43 |
| aligned | 85-100% | 51 | 100.0% | $38,719 | $+704 | $+13.81 |
| contrarian | <15% | 37 | 0.0% | $358 | $-358 | $-9.66 |
| contrarian | 15-30% | 87 | 12.6% | $994 | $-408 | $-4.68 |
| contrarian | 30-50% | 159 | 35.2% | $2,486 | $-358 | $-2.25 |
| contrarian | 50-70% | 51 | 33.3% | $1,056 | $-387 | $-7.59 |
| flat | 30-50% | 21 | 47.6% | $380 | $+20 | $+0.96 |
| flat | 50-70% | 23 | 43.5% | $484 | $-131 | $-5.67 |

## Verdict

- **Hypothesis SUPPORTED**: aligned trades win meaningfully more often than contrarian. Bonereaper appears to use spot data to pick sides. Next step: a `design/spot_aware_strategy.md` doc describing the trigger this implies (gap between book implied probability and spot-derived probability) before any code lands. Anti-vibe rule #1.

## Caveats

- Spot lookup is forward-fill within 30s. Accuracy degrades on sparse-tick periods; a 5s gap to a 1-bp move shouldn't change bucket assignment but could on edge cases.
- Binance ticks only. Coinbase + oracle would refine but the Binance feed dominates BTC volume so this is a reasonable proxy.
- Captured spot covers a tiny window of bonereaper's full activity. Findings here are suggestive, not conclusive.
- Δ_bps is computed entry vs window-open, not entry vs immediate-prior. A trade entering at t=200s with the price unchanged from window-open but having round-tripped is bucketed as 'flat' even though the path was volatile.
