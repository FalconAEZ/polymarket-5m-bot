---
title: Oracle-gap signal
tags: [concept, signal, strategy]
---

# Oracle-gap

> Spot price vs Chainlink last-answer. The latency edge.

The second-largest signal in the deterministic strategy. At any moment, oracle-gap = `(spot_now − chainlink_last_answer) / chainlink_last_answer`.

If spot has moved since the last Chainlink update, the oracle hasn't caught up. The market resolves on the oracle, but the orderbook prices off recent spot moves. That gap is the latency edge.

## Why it works

Per [[chainlink-on-polygon]], Chainlink BTC/USD on Polygon reports on a **60-second heartbeat with no deviation threshold**. So:
- Between heartbeats, the oracle can be up to 60s stale.
- During that window, spot can move 0.3-0.5% and the oracle hasn't seen it.
- The eventual resolution of any active market depends on the *next* oracle update at `window_ts + 300` — but the orderbook reacts to spot in milliseconds.

If spot is 0.3% above last-answer, the next oracle update is *likely* to bring the oracle up — meaning UP is more likely. That's the edge.

## Combined with window-delta

These two signals are correlated but not identical:
- **[[window-delta]]** asks: "since the window opened, has BTC moved up or down?"
- **Oracle-gap** asks: "right now, is the oracle catching up?"

Composite = `w_wd * window_delta + w_og * oracle_gap`. Both heavily weighted. Both directionally informative.

When they agree strongly (both positive, both above threshold), the signal is overdetermined and confidence is high. When they disagree, the situation is ambiguous and we should not enter.

## Caveats

- **Oracle staleness alone isn't tradeable.** If the oracle is 50s stale but spot has moved 0%, oracle-gap is zero — no edge.
- **Heartbeat boundary risk.** If we enter at T-15s and the oracle ticks at T-10s, our oracle-gap signal evaporates between decision and resolution. Time-to-close (TTL) matters.
- **Reorg risk.** Polygon reorgs can rewrite the oracle's last-answer briefly. Rare but possible.

## See also

- [[window-delta]] — the complementary signal
- [[tier-3-deterministic]] — where oracle-gap is consumed
- [[chainlink-on-polygon]] — the heartbeat mechanics
- `pdfs/MASTERPLAN.md` thesis — "edge sources, ranked"
