# Leaderboard scout — final comparison & synthesis

Run date: 2026-05-08. Inputs: scout output + per-candidate microstructure deep analysis + per-candidate spot-vs-book join. Wallets compared: Bonereaper (reference) + Slow-Minute + `0x88f1`.

## TL;DR

**The scout works as a filter** but **its win-rate and per-$ PnL columns are unreliable for ranking** at the sample size we used (300 markets × 500 trades/market cap). Two top candidates (Slow-Minute and 0x88f1) BOTH looked like winners by the scout — high win rate, positive sample PnL. **Both turned out to be net-losing strategies on full 7-day analysis.**

But — significantly — the **spot-Δ signal pattern reproduces across all three wallets**. They all bias toward spot-aligned bets. The difference between the winner and the losers is **price-tier discipline**, not signal awareness.

## Comparison table

| | Bonereaper | Slow-Minute | 0x88f1 |
|---|---:|---:|---:|
| Wallet | `0xeebd…ba30` | `0xdf0d…9f79` | `0x88f1…d3d0` |
| Pseudonym | Popular-Insurrection | Slow-Minute | (none) |
| Current equity | $1,282 | $4,458 | $1,137 |
| 7d trades on BTC 5m | **60,500** | 176 | 89 |
| 7d gross PnL | **+$37,558** | -$3,964 | -$186 |
| 7d gross notional | $2,764,351 | $253,953 | $9,979 |
| Per-trade PnL | +$0.62 | -$22.52 | -$2.09 |
| Per-$ PnL (gross) | **+1.36%** | -1.56% | -1.86% |
| Win rate | 52.3% | **96.6%** | 93.3% |
| Price-tier coverage | All 6 (broad) | 85-100% only | 85-100% only |
| Spot-Δ alignment gap | +32pp (7d) / +30.9pp (30d) | aligned 98.6% WR | aligned 92.9% WR |

## What this teaches

### 1. High win rate is a TRAP without price-tier discipline

Slow-Minute wins 96.6% of trades and **loses money** because they pay 95-99¢ for shares that pay $1. Math:
- Pay $0.99 to win $1 (2.4% margin)
- Need 97.6% win rate JUST to break even before fees
- Their actual 96.6% = -$22.52 expected per trade

**The scout's 98.4% / 97.8% win-rate columns made these wallets look stellar; they were actually bleeders.** "Win rate" is an extremely misleading single-number summary for binary markets at high implied probabilities.

### 2. The spot-Δ signal IS robust — but it's the price-tier mix that wins

All three wallets show a strong spot-Δ alignment bias (they bet WITH spot direction far more than against). Slow-Minute's aligned win rate at 85-100% tier is **98.6%**. 0x88f1's is 92.9%. Bonereaper's is 91.7%.

The reproducibility across three independent operators is **strong evidence that spot-Δ from window-open is a real, stable signal** — not a Bonereaper-specific artifact.

But the signal alone doesn't generate edge at high implied prices. Bonereaper's secret sauce is layering: $5.5M of $12.1M notional in 85-100% (loses ~breakeven there), but also $1.5M in 30-50% tier where 44% win rates at moderate prices generate **+$1.03/trade** (most of the actual PnL).

### 3. Wallet sizing alone doesn't predict per-$ profitability

We hoped to find a "$5k equity making $200/day" wallet. Among the top 7 scout survivors, none qualified. The two we deep-analyzed both ended up losing money. The other 5 had worse sample numbers and probably wouldn't fare better.

That doesn't mean such a wallet doesn't exist — but it suggests:
- They might be **rarer** than we assumed
- They might trade markets we're not sampling (15-min, 1-hour, sports, etc.)
- Or — sobering possibility — Bonereaper's edge **at our scale** is harder to replicate than we hoped

### 4. The scout needs a verification pass to be production-useful

The scout sample (300 markets × 500-trade-per-market cap) is biased toward late-window entries (the API returns most-recent fills) and produces noisy per-$ PnL estimates for low-trade-count wallets.

**Fix for next iteration:** after the scout identifies candidates, run a full per-wallet 7-day pull (the existing `bonereaper_microstructure.py --user <addr>`) and re-rank by FULL gross PnL. We did this manually for the top 2; it should be automated. Maybe ~4 min per wallet × 50 candidates = doable in parallel.

## Implication for our bot's strategy design

Going into `design/spot_aware_strategy.md`, the directive is now sharper:

1. **Use spot-Δ alignment** as the signal trigger (validated across 3 wallets, 30.9pp gap on Bonereaper at 307K trades).
2. **DO NOT buy heavy favorites at >90% implied** — those need 96%+ accuracy to clear fees and we don't have evidence we can hit that.
3. **DO buy at moderate implied prices (30-70%) when spot-Δ is aligned** — Bonereaper's per-trade PnL is highest there (+$1.03 to +$1.56/trade in our 30d analysis).
4. **Reject any trade where (entry_price + fees) > (estimated win_prob × $1)** — explicit EV check before firing.

This is the discipline gap that separates Bonereaper from the bleeders. We can encode it.

## Files

- Scout report: `runbooks/research/leaderboard-scout-2026-05-08.md`
- Slow-Minute deep: `runbooks/research/scout-slow-minute-microstructure-2026-05-08.md` + `scout-slow-minute-spot-vs-book-2026-05-08.md`
- 0x88f1 deep: `runbooks/research/scout-0x88f1-microstructure-2026-05-08.md` + `scout-0x88f1-spot-vs-book-2026-05-08.md`
- This synthesis: `runbooks/research/scout-final-comparison-2026-05-08.md` (you're reading it)
- Raw scout JSON: `state/research/leaderboard/scout-2026-05-08.json`

## Caveats (carry forward)

- 7-day window only; longer history may surface different wallets
- 5-min markets only; 15-min and 1-hour markets unanalyzed
- Polymarket Data API 500-trade-per-market cap biases scout time-bucket cells
- Fees + settlement gas not subtracted from gross PnL anywhere; real edge is ~50-100bps lower than gross
- Three wallets is still a small sample for the "spot-Δ is robust" claim; would benefit from 5-10 more profitable wallets analyzed
