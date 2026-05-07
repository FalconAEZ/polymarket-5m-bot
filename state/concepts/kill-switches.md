---
title: Kill-switches (the five guardrails)
tags: [concept, risk, phase-6, ops]
---

# Kill-switches

> Five independent guardrails that halt new entries when something goes wrong. Each is a daemon-level check; tripping any one halts the bot and pages [[../runbooks/README|Telegram]].

## The five (locked at Phase 6)

1. **Heartbeat** — any of (Binance, Coinbase, Chainlink oracle, Polymarket WS) silent > 10s → halt new entries.
2. **Slippage** — rolling 10-trade average fill slippage > 2¢ → halt new entries.
3. **Drawdown** — session loss > $50 (5% of $1k bankroll) OR cumulative > $100 (10%) → systemd-stop the bot + page Telegram.
4. **Reconciliation drift** — `on_chain_usdc_balance − bot_internal_bankroll > $0.50` sustained 60s → halt new entries.
5. **Win-rate drift** — rolling-100-trade win-rate < `expected − 2σ` (binomial CI) → halt new entries.

## Why each one exists

- **Heartbeat** catches data outages. Without fresh feeds, every signal is stale and every decision is wrong.
- **Slippage** catches orderbook regime change. If we suddenly need to walk the book deeper than expected, our backtest assumptions are no longer valid.
- **Drawdown** is the hard cap. Even if every other check passes, losing $50 in a session means stop and inspect.
- **Reconciliation drift** catches partial-fill misclassification + accounting bugs. If our internal bankroll diverges from on-chain reality by even $0.50, something is wrong and we should not size new trades.
- **Win-rate drift** is the "edge has decayed" detector. If our strategy stops working, we don't want to keep trading hoping it'll come back.

## Synthetic testing requirement

Per [[../runbooks/README|gate discipline]], every kill-switch must be tested by **synthetically tripping it** before Phase 6 goes live. The tests are unit + integration tests that:
- Inject the failure condition (mock feed dropout, mock partial fill, mock 10 losses in a row).
- Assert the bot halts new entries.
- Assert the Telegram alert fires (to a test channel).

Phase 6 gate criterion 3 explicitly checks all 5 have been synthetic-tripped.

## Implementation

Phase 6 deliverable. Files (will land in `src/polymarket_bot/_live/kill_switches/`):
- `heartbeat.py`
- `slippage.py`
- `drawdown.py`
- `reconciler.py`
- `drift.py`
- `supervisor.py` — coordinates all five, owns the `halt_new_entries` flag.

Tests: `tests/kill_switches/*` with one synthetic-trip test per switch.

## Recovery

When a kill-switch trips:
- The bot stops accepting new entries (existing positions ride to resolution).
- Telegram pages the operator.
- A postmortem is mandatory in `state/postmortems/<date>-<switch>.md` before re-enabling.
- For the drawdown breaker specifically: 24h cooling-off period is **mandatory** before re-enable.

## Connections

- [[funder-signer]] — drawdown breaker is calibrated to $1k bankroll
- [[$5-flat-sizing]] — sizing rule that sets the per-trade risk
- [[../runbooks/README]] — operational alert handling
- [[../postmortems/README]] — where the postmortems live
- `RUNBOOK.md` Phase 6 — the gate criteria

## See also

- [[anti-vibe-rules]] — kill-switches embody rule #4 ("no phase advance without gate exit 0") at the operational layer
