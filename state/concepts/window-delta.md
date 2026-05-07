---
title: Window-delta signal
tags: [concept, signal, strategy]
---

# Window-delta

> Where is BTC right now vs where the 5-min window opened?

The dominant signal in the deterministic strategy ([[tier-3-deterministic]]). At any moment within an active 5-min market, window-delta = `(spot_now − window_open_price) / window_open_price`.

If window-delta is strongly positive, the market is likely to resolve UP. Strongly negative → DOWN. Near zero → coinflip; we should not enter.

## Why it dominates

Polymarket's 5-min markets resolve to whatever Chainlink BTC/USD reports at `window_ts + 300`. Chainlink on Polygon has a 60-second heartbeat with no deviation threshold (per `pdfs/MASTERPLAN.md` thesis). So:

- The eventual oracle reading is *correlated with current spot price*, with some delay and smoothing.
- A move that's already happened in spot will, with high probability, be reflected in the oracle by `window_ts + 300`.
- Therefore window-delta at any point in the window is a strong predictor of the resolution.

This is the cleanest signal because it's:
- **Deterministic** — given a price feed and the window boundaries, you compute it exactly the same every time.
- **Direct** — no model, no learned parameters, no LLM. Pure math.
- **Cheap** — no API calls, no inference. ~1µs.

## How it shows up

- In Phase 3 deterministic strategy: `composite = w_wd * window_delta + w_og * oracle_gap`. Threshold ≥ 0.6 fires.
- In the [[bonereaper-postmortem|Phase A audit]] this was confirmed as bonereaper's primary signal too — when bonereaper enters with strong window-delta, his win-rate is higher than at neutral window-delta.
- In [[tier-3-deterministic]] this is half the composite signal.

## Caveats

- **Not directional in the last 30 seconds.** When TTL < 30s the window-delta is mostly priced into the orderbook already; entry edge is small.
- **Mean-reverts on noise spikes.** A 0.3% spike that gets retraced in 60s is window-delta but not signal.
- **Doesn't account for oracle staleness.** If the oracle is mid-heartbeat (~30s into a 60s cycle), the *current* oracle reading hasn't seen the latest spot move yet — that's where [[oracle-gap]] complements window-delta.

## See also

- [[oracle-gap]] — the complementary signal
- [[tier-3-deterministic]] — where window-delta is consumed
- [[chainlink-on-polygon]] — why the resolution behaves the way it does
- `pdfs/MASTERPLAN.md` — the thesis that justifies all of this
