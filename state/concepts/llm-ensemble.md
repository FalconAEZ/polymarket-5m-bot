---
title: LLM ensemble (3 agents + meta-decider)
tags: [concept, strategy, llm, anthropic]
---

# LLM ensemble

> 3 specialized Anthropic agents + 1 meta-decider. Optional layer on top of [[tier-3-deterministic]]. Retained only if Phase 3 A/B shows ≥3 pp uplift.

## Locked composition (decision #5)

| Agent | Model | Input | Output |
|---|---|---|---|
| **Orderbook microstructure** | Haiku 4.5 | top-5 bid/ask depth, spread, recent trade prints | `{vote: UP\|DOWN\|abstain, confidence: 0..1, rationale: str}` |
| **Oracle-gap** | Haiku 4.5 | spot ticks, last-answer + age, current [[oracle-gap]] value | same JSON |
| **Momentum** | Haiku 4.5 | last-N tick history, vol regime | same JSON |
| **Meta-decider** | Sonnet 4.6 | the 3 agents' votes + deterministic composite | final `{side, size_usd, confidence, rationale}` |

Per [[../decisions/README#decision-5|decision #5]], we lock at exactly 3 agents + 1 meta. **No 4th agent.** The optional `behavioral_mimic` agent that the bonereaper cloning study would have produced is **out** per [[../decisions/README#decision-19|decision #19]].

## Anthropic-only (decision #4)

No OpenAI fallback. The deterministic [[tier-3-deterministic]] catches every LLM failure path. Simpler matrix.

## Cost envelope (decision #14)

Empirical: $0.19-0.58/hour at full live load. Phase 3 backtest budget: $15-50 with cache discipline. Phase 4 (paper, 14 days × 24/7): $50-195 — top up Anthropic to $150 first. Phase 6 (live, 14 days × 24/7): $50-195 — top up to $300 first. Sustained: ~$200/month.

## Cache strategy

Static system prompt (the agent's role + output schema) cached at the breakpoint. Per-window dynamic block (the actual market state) is the only uncached portion. This is critical to keeping cost ≤ $0.012 per call.

## Failure handling

Per [[../concepts/anti-vibe-rules|anti-vibe enforcement]], every agent call goes through `validate_or_retry(json_schema, max_retries=1)`:
- Schema-fail or refusal → that agent abstains, log `invalid_response`.
- <2 valid agents in a window → meta is bypassed, [[tier-3-deterministic]] fires alone.
- Latency budget breach (per-call timeout) → same as schema-fail.

## A/B retention rule (decision #16)

Phase 3 runs the backtest twice on the same data:
1. Deterministic-only (Tier-3 standalone)
2. Deterministic + LLM ensemble (full stack)

Keep the ensemble **iff**:
- Win-rate uplift ≥ 3 pp over baseline
- p99 decision latency ≤ 4s
- $/decision ≤ $0.01

If any criterion fails, ship the deterministic strategy and revisit the ensemble in Phase 8.

## See also

- [[tier-3-deterministic]] — the fallback / standalone alternative
- [[window-delta]] + [[oracle-gap]] — the math the agents and meta-decider also see
- [[../decisions/README#decision-4|Decision #4]] — Anthropic-only
- [[../decisions/README#decision-5|Decision #5]] — 3 agents + meta locked
- [[../decisions/README#decision-14|Decision #14]] — cost envelope
- [[../decisions/README#decision-16|Decision #16]] — A/B retention
