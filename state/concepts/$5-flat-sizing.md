---
title: $5 flat sizing (the first 100 trades)
tags: [concept, risk, sizing]
---

# $5 flat sizing

> For the first 100 live trades, every entry is exactly **$5**. No Kelly, no scaling, no dynamic sizing. Pre-Kelly learning budget.

## The rule (decision #9)

```
size_usd = 5.0  # for trade 1..100
```

Cleared $4.75 minimum order size on Polymarket. 0.5% of $1k bankroll. Survives 200 consecutive losses (well beyond statistical possibility on a positive-edge strategy).

## Why "flat" not "Kelly"

Kelly off a backtested win rate is a math fiction. Backtest win-rates are subject to:
- Look-ahead bias (the simulator might know things the live bot doesn't)
- Regime selection (the captured data might over-represent one market regime)
- Fee approximation (fees are baked into fills crudely in simulation)

Until we have **real live trades** with real fills, real slippage, and real fee accounting, we don't know our true edge. So we don't size to it. We pay tuition in $5 increments until we have empirical evidence.

After 100 trades, we have a usable empirical win-rate. Then we transition to fractional Kelly:

```
size_usd = max($5, kelly_fraction * bankroll * confidence)
where kelly_fraction ≤ 0.25 and size_usd ≤ 0.10 * bankroll
```

That's the rule for trade 101 onwards.

## Why $5 specifically

- **$4.75 minimum**: Polymarket requires 5 shares × ~$0.95 = $4.75 minimum order size. $5 round-numbers above that, leaves a buffer.
- **0.5% of $1k bankroll**: small enough that 10 losses in a row is recoverable, large enough to actually pay attention to.
- **Doesn't trigger Kelly's math**: at $5 flat, we're explicitly NOT optimizing for growth. We're optimizing for *learning what our edge actually is.*

## Connection to bankroll (decision #10)

The $1k bankroll was chosen partly so that $5 flat is a meaningful 0.5% sizing — not so small as to be irrelevant, not so large as to be reckless. At $100 starting bankroll (the original spec), $5 would have been 5% per trade, which is far too aggressive for unconfirmed-edge testing. At $10k, $5 would be 0.05% — too small to bother.

## Connection to drawdown breaker

The drawdown breaker ([[kill-switches#3-drawdown|kill-switch #3]]) is set at -$50 daily / -$100 cumulative. At $5 flat sizing:
- $50 daily = 10 losing trades in a row at full $5 loss (unlikely; fills are usually mid-price so net loss is smaller).
- $100 cumulative = 20 such losses. Statistical near-impossibility on positive-edge.

If the drawdown breaker DOES trip at $5 flat sizing, that's a strong signal something's wrong (regime change, bug, or no edge at all).

## See also

- [[../decisions/README#decision-9|Decision #9]] — $5 flat for first 100 trades
- [[../decisions/README#decision-10|Decision #10]] — $1k starting bankroll
- [[funder-signer]] — wallet topology that holds this $1k
- [[kill-switches]] — the limits that protect the bankroll
- [[../phases/phase-1-wallet-auth|Phase 1B]] — when the first $5 trade actually fires
