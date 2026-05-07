---
title: Tier-3 deterministic strategy
tags: [concept, strategy, fallback]
---

# Tier-3 deterministic

> The strategy that fires when the LLM ensemble can't / shouldn't. Pure math. No LLM. Always available.

## Definition

```
composite = w_wd * window_delta + w_og * oracle_gap
fire if abs(composite) ≥ 0.6  AND  ttl_s ∈ [10, 30]  AND  liquidity_available
side = sign(composite)  # positive = UP, negative = DOWN
```

Locked threshold: **composite ≥ 0.6** per [[../decisions/README#decision-6|decision #6]].

## Why "Tier-3"?

It's the third and final tier of decision-making in the live runtime:

1. **Tier 1**: 3 LLM agents ([[llm-ensemble]]) vote with confidence on the active window.
2. **Tier 2**: meta-decider (Sonnet) weighs the 3 votes + the deterministic composite.
3. **Tier 3**: deterministic only. Fires when:
   - Any LLM agent 429s (rate limit)
   - Latency budget at T-15s is blown
   - Schema-fail or refusal from any agent
   - Fewer than 2 valid agent votes
   - Operator manually disables LLM tier (cost emergencies)

It's also a complete strategy on its own. Per [[../decisions/README#decision-16|decision #16]] (Phase 3 A/B), the LLM ensemble is retained **only if** it shows ≥3 pp win-rate uplift over Tier-3-alone. If it doesn't, we ship Tier-3 as the production strategy.

## Why the threshold is 0.6

The original `pdfs/BONEREAPER_STUDY.pdf` framework set the abort gate at 60% win-rate. That same number anchors the deterministic threshold: only enter when our composite signal exceeds 0.6 absolute value, which empirically corresponds (via Phase 3 backtest tuning) to win-rate ≥ 60% on selected windows.

We **trade fewer windows** but only when the signal is strong. That's the philosophical opposite of bonereaper's approach (trade lots of windows on slim edge). Per the [[phase-A-bonereaper|Phase A postmortem]]: "We're not trying to out-edge bonereaper, we're trying to be more selective."

## Integration with the LLM ensemble

When all systems are go:
1. 3 agents return votes within their per-call latency budgets.
2. Meta-decider weighs (agent_1, agent_2, agent_3, deterministic_composite) → decision.
3. If meta-decider abstains OR <2 agents valid → fall through to Tier-3 alone.

Tier-3's composite is also a *feature* fed into the meta-decider, not just a fallback. So the deterministic signal influences every decision, not just the fallback ones.

## Implementation note

In `src/polymarket_bot/strategies/deterministic.py` (Phase 3 deliverable):
- Pure-Python computation, no async, no IO.
- Inputs: spot price (Binance + Coinbase aggregated microprice), Chainlink last-answer + age, window_open_price, ttl_s.
- Outputs: `(side: UP|DOWN|None, confidence: float ∈ [0, 1], rationale: str)`.

## See also

- [[window-delta]] — first signal component
- [[oracle-gap]] — second signal component
- [[llm-ensemble]] — the upper-tier strategy that this falls back from
- [[../phases/phase-1-wallet-auth]] — Phase 1 doesn't touch this; Phase 3 builds it
- [[../decisions/README#decision-6|Decision #6]] — threshold lock
- [[../decisions/README#decision-16|Decision #16]] — A/B retention rule
