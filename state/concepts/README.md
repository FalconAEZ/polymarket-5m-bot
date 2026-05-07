---
title: Concept glossary
tags: [moc, concepts, glossary]
---

# Concept glossary

Short notes (50-150 lines each) on the load-bearing concepts of the project. Each one defines the term, lists where it shows up, and links to the canonical source in the project root.

## Strategy / signal concepts

- [[window-delta]] — the dominant signal in the deterministic strategy. "Where is BTC now vs where the 5-min window opened?"
- [[oracle-gap]] — the second-largest signal. Spot price vs Chainlink last-answer.
- [[tier-3-deterministic]] — the fallback strategy that fires when the LLM ensemble can't / shouldn't. Composite ≥ 0.6 of (window_delta, oracle_gap).
- [[llm-ensemble]] — 3 specialized agents + meta-decider. Retained only if Phase 3 A/B shows ≥3pp uplift over deterministic.

## Risk / sizing concepts

- [[funder-signer]] — wallet topology. Funder = working capital, Signer = bot operator. Separation of concerns + blast-radius limit.
- [[kill-switches]] — five guardrails fired in Phase 6. Heartbeat, slippage, drawdown, reconciliation drift, win-rate drift.
- [[$5-flat-sizing]] — the locked sizing rule for the first 100 live trades. 0.5% of $1k bankroll. Pre-Kelly learning budget.

## Infrastructure concepts

- [[gasless-relayer]] — Polymarket's mechanism for placing orders without paying per-tx gas. OD-4 was the design question "do we need it / how do we use it."
- [[chainlink-on-polygon]] — the oracle that resolves BTC 5-min markets. 60s heartbeat, no deviation threshold (the foundational thesis claim).
- [[polymarket-data-sources]] — Data API, Gamma API, CLOB, subgraphs, on-chain RPC. Each has a shape; see [[../research/data-sources-map]] for the taxonomy.

## Discipline concepts

- [[anti-vibe-rules]] — the 10 hard rules + 25 operating rules from `pdfs/BUILD_SPEC.pdf` p. 22-23. Pinned above the desk.
- [[3-fix-rule]] — the specific rule that catches bug-fix loops before they spiral.
- [[gate-discipline]] — what "no phase advances without gate exit 0" means in practice.
