# Bonereaper spot-vs-book correlation

Run date: 2026-05-07. Input bonereaper trades: 306,997. Joined with captured BTC spot: 306,966. Skipped: 31 ({'no_spot_data': 31}). Fetch+join time: 0.9s.

**Question under test:** does Bonereaper use BTC spot information to pick a side? Test: for each trade, compare entry-time spot to window-open spot, compute Δ_bps = 10000x(St - S0)/S0, classify alignment (UP+Δ>0 OR DOWN+Δ<0 = aligned; opposite = contrarian; Δ≈0 = flat), and look at win-rate per alignment bucket and per Δ_bps bucket.

## Headline

- **306,966 trades** with spot data joined
- Win rate: **51.7%** (158,710/306,966)
- Gross notional: $12,133,403.29
- Gross PnL: $+234,864.16

## By alignment (the main test)

| alignment | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| aligned | 101,962 | 67.4% | $7,963,111 | $+83,054 | $+0.81 |
| contrarian | 117,040 | 36.4% | $2,083,991 | $+67,310 | $+0.58 |
| flat | 87,964 | 53.9% | $2,086,301 | $+84,499 | $+0.96 |

**Aligned vs contrarian win-rate gap:** +30.9% (aligned 67.4% vs contrarian 36.4%).
→ **Suggests Bonereaper IS spot-aware** when picking sides.

## By Δ_bps bucket (entry-time spot move since window open)

| Δ_bps bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---:|---:|---:|---:|---:|
| Δ<-50bps (down hard) | 8 | 25.0% | $3,177 | $-26 | $-3.31 |
| -50..-20bps | 589 | 41.6% | $130,363 | $+392 | $+0.67 |
| -20..-10bps | 6,040 | 45.4% | $891,945 | $+13,287 | $+2.20 |
| -10..-5bps | 21,981 | 47.5% | $1,356,316 | $+8,250 | $+0.38 |
| -5..+5bps (flat) | 247,955 | 52.8% | $7,149,938 | $+202,803 | $+0.82 |
| +5..+10bps | 22,554 | 48.0% | $1,439,808 | $+12,450 | $+0.55 |
| +10..+20bps | 6,999 | 45.7% | $965,740 | $-3,943 | $-0.56 |
| +20..+50bps | 829 | 42.9% | $195,894 | $+1,725 | $+2.08 |
| Δ>+50bps (up hard) | 11 | 27.3% | $222 | $-74 | $-6.70 |

## By side x Δ_bps (does UP bet win more when spot moves up?)

| side | Δ bucket | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| UP | Δ<-50bps (down hard) | 6 | 0.0% | $68 | $-68 | $-11.33 |
| UP | -50..-20bps | 360 | 10.3% | $4,213 | $-1,220 | $-3.39 |
| UP | -20..-10bps | 3,560 | 19.0% | $41,307 | $+10,963 | $+3.08 |
| UP | -10..-5bps | 12,554 | 26.3% | $166,819 | $+10,843 | $+0.86 |
| UP | -5..+5bps (flat) | 125,791 | 53.5% | $3,639,748 | $+136,616 | $+1.09 |
| UP | +5..+10bps | 9,833 | 75.7% | $1,270,855 | $+2,973 | $+0.30 |
| UP | +10..+20bps | 3,005 | 83.4% | $918,741 | $+735 | $+0.24 |
| UP | +20..+50bps | 363 | 83.7% | $190,564 | $+2,048 | $+5.64 |
| DOWN | -50..-20bps | 229 | 90.8% | $126,150 | $+1,612 | $+7.04 |
| DOWN | -20..-10bps | 2,480 | 83.2% | $850,638 | $+2,324 | $+0.94 |
| DOWN | -10..-5bps | 9,427 | 75.7% | $1,189,497 | $-2,593 | $-0.28 |
| DOWN | -5..+5bps (flat) | 122,164 | 52.0% | $3,510,190 | $+66,187 | $+0.54 |
| DOWN | +5..+10bps | 12,721 | 26.6% | $168,953 | $+9,477 | $+0.74 |
| DOWN | +10..+20bps | 3,994 | 17.3% | $46,999 | $-4,678 | $-1.17 |
| DOWN | +20..+50bps | 466 | 11.2% | $5,330 | $-323 | $-0.69 |
| DOWN | Δ>+50bps (up hard) | 8 | 0.0% | $82 | $-82 | $-10.23 |

## By alignment x price tier (where the alignment edge lands)

| alignment | price tier | trades | win-rate | notional | gross PnL | per-trade |
|---|---|---:|---:|---:|---:|---:|
| aligned | <15% | 722 | 13.7% | $6,794 | $+6,377 | $+8.83 |
| aligned | 15-30% | 3,167 | 25.0% | $37,718 | $+336 | $+0.11 |
| aligned | 30-50% | 14,802 | 45.4% | $262,680 | $+17,307 | $+1.17 |
| aligned | 50-70% | 39,681 | 63.1% | $1,068,239 | $+37,878 | $+0.95 |
| aligned | 70-85% | 28,674 | 78.0% | $1,302,481 | $+11,508 | $+0.40 |
| aligned | 85-100% | 14,916 | 91.7% | $5,285,199 | $+9,648 | $+0.65 |
| contrarian | <15% | 16,622 | 9.9% | $164,751 | $+8,230 | $+0.50 |
| contrarian | 15-30% | 32,174 | 24.4% | $383,906 | $+22,938 | $+0.71 |
| contrarian | 30-50% | 44,300 | 41.0% | $736,611 | $+27,000 | $+0.61 |
| contrarian | 50-70% | 19,319 | 58.2% | $482,580 | $+3,312 | $+0.17 |
| contrarian | 70-85% | 3,740 | 77.9% | $165,992 | $+1,410 | $+0.38 |
| contrarian | 85-100% | 885 | 92.4% | $150,150 | $+4,421 | $+4.99 |
| flat | <15% | 143 | 10.5% | $1,558 | $-394 | $-2.75 |
| flat | 15-30% | 3,523 | 25.6% | $44,582 | $+1,015 | $+0.29 |
| flat | 30-50% | 30,737 | 46.2% | $569,289 | $+48,072 | $+1.56 |
| flat | 50-70% | 47,471 | 58.3% | $1,197,259 | $+32,050 | $+0.68 |
| flat | 70-85% | 5,755 | 75.0% | $244,621 | $+2,219 | $+0.39 |
| flat | 85-100% | 335 | 91.3% | $28,991 | $+1,538 | $+4.59 |

## Verdict

- **Hypothesis SUPPORTED**: aligned trades win meaningfully more often than contrarian. Bonereaper appears to use spot data to pick sides. Next step: a `design/spot_aware_strategy.md` doc describing the trigger this implies (gap between book implied probability and spot-derived probability) before any code lands. Anti-vibe rule #1.

## Caveats

- Spot lookup is forward-fill within 30s. Accuracy degrades on sparse-tick periods; a 5s gap to a 1-bp move shouldn't change bucket assignment but could on edge cases.
- Binance ticks only. Coinbase + oracle would refine but the Binance feed dominates BTC volume so this is a reasonable proxy.
- Captured spot covers a tiny window of bonereaper's full activity. Findings here are suggestive, not conclusive.
- Δ_bps is computed entry vs window-open, not entry vs immediate-prior. A trade entering at t=200s with the price unchanged from window-open but having round-tripped is bucketed as 'flat' even though the path was volatile.
