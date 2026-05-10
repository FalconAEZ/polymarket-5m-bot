# Phase 5 — LLM Ensemble + Wide-Fire Strategy

> **Status:** PROPOSED 2026-05-10. Operator-approved direction: revert
> ev_min to fire every window (Phase 11.A "wide fire") AND wire the
> already-built Phase 5 LLM ensemble to filter for high-WR fires. Goal:
> volume × LLM-filtered quality ≥ 60% WR sustained.

## TL;DR

Phase 3 built `src/polymarket_bot/agents/` (3 specialists + Sonnet meta
+ AnthropicAdapter + BudgetTracker) AND `src/polymarket_bot/strategies/
ensemble.py` (the EnsembleStrategy that bridges agents into the runner).
Phase 3 then **CUT** the ensemble for failing latency + cost gates
against the v1+aggressive baseline. Phase 11.A.2 has since validated
two new edge signals (oracle-gap +12pp WR, regime-trending +23pp WR).

This phase **reactivates** the dormant Phase 5 code AND **reverts ev_min
to wide-fire** (per operator's 2026-05-10 directive). The bet: with LLM
ensemble as the FINAL gate, wide-fire's volume + LLM's selection lifts
production WR to 60%+ — substantially above the deterministic-only WR
of ~50% that Phase 3's cost gate was measured against.

## Why now

Three reasons Phase 3 was wrong to cut, that have changed by 2026-05-10:

1. **Better deterministic signals to feed the meta-decider.** Phase 3's
   composite was just window-delta + oracle-gap. We now have v2's
   priors-based EV, the regime classifier (validated +23pp), and the
   oracle-gap aligned/magnitude signal (validated +12pp WR). Meta has
   richer material to synthesise.
2. **Cheaper models.** Phase 3 used the then-flagship Sonnet for meta
   and Haiku for specialists. Token prices have come down; same
   architecture is cheaper to run today.
3. **Wider data baseline.** 299-fire dataset (state/staging/decisions/)
   gives backtest coverage for ensemble eval; Phase 3 only had ~30.

## Architecture (the plan operator approved)

```
                    spot/book/oracle event
                              │
                              ▼
                ┌─────────────────────────┐
                │   v2 with WIDE gates    │ ← ev_min reverted to 0.003
                │   (delta_min=5,         │   (or 0.001 — fire ~every
                │    rejected tiers,      │   window with any spot move)
                │    oracle_gap optional) │   tier rejects STILL apply
                └─────────────┬───────────┘
                              │ candidate fire
                              ▼
                ┌─────────────────────────┐
                │   3 specialists vote    │ ← prompts/orderbook.md +
                │   in parallel (Haiku)   │   prompts/oracle_gap.md +
                │   • orderbook           │   prompts/momentum.md
                │   • oracle_gap          │
                │   • momentum            │
                └─────────────┬───────────┘
                              │ ≥2 votes (Tier-3 fallback if <2)
                              ▼
                ┌─────────────────────────┐
                │   Sonnet meta decides   │ ← prompts/meta.md
                │   FIRE or ABSTAIN       │   adaptive thinking, medium effort
                └─────────────┬───────────┘
                              │ FIRE only
                              ▼
                       PaperRunner fires
```

### Two-mode operation (the safety lever)

The ensemble runs in one of two modes via `ENSEMBLE_MODE` env var:

- **`shadow`** (default) — Ensemble votes are logged to a separate
  JSONL but the deterministic strategy's verdict drives actual fires.
  Zero production risk; pure data collection. Used to validate the
  Phase 3 cost/latency cut on fresh data.

- **`gate`** — Ensemble's meta verdict OVERRIDES the deterministic
  strategy: a fire happens iff (deterministic candidate AND meta=FIRE).
  This is the "production" mode the operator wants. We don't switch
  to gate mode until shadow-mode data shows ≥+5pp WR uplift over
  deterministic-only.

The kill-switch on the gate side: setting `ENSEMBLE_MODE=off` reverts
to deterministic-only without restart (env reload via SIGHUP if the
runtime supports it; otherwise restart).

## Cost model (sharply quantified)

Per locked decision #14 budget envelopes:

| Mode | Calls/day | Tokens/call | Daily $ | Monthly $ |
|---|---|---|---|---|
| Shadow (specialists only on candidate fires) | ~288 × 3 | ~600 in/100 out | $0.70 | **$21** |
| Shadow + meta on candidate fires only | ~288 specialist + ~80 meta | + Sonnet | $1.20 | **$36** |
| Gate (production) | ~80 candidate × (3 + 1) | same | $1.50 | **$45** |

Sustained ~$36-45/month → well within decision #14's $200/month cap.
Hard limit per BudgetTracker: $5/day or $150/month, whichever first.
Beyond cap → graceful degrade to Tier-3 deterministic + alert.

## Phased execution

### Phase 5.0 — Activate the existing wiring (this session, ~2h)

1. Wire `STRATEGY=ensemble` dispatch in `scripts/run_paper.py`
2. Construct ensemble at boot: `OrderbookAgent(adapter)`,
   `OracleGapAgent(adapter)`, `MomentumAgent(adapter)`, `MetaAgent(adapter)`
3. Construct AnthropicAdapter from `ANTHROPIC_API_KEY` env (already
   exists in the agents module)
4. Add `EnsembleWrapper` strategy that:
   - Runs v2 (or any wrapped strategy) first
   - On candidate fire, calls ensemble in parallel
   - In `shadow` mode: logs `{decision_id, agent_votes, meta_decision,
     deterministic_decision, actual_fire}` to `state/ensemble/<date>.jsonl`
   - In `gate` mode: only fires if meta=FIRE
   - In `off` mode: bypasses ensemble entirely
5. Tests using `agents.fakes.FakeAdapter` so we don't burn tokens in CI
6. `make verify` green

### Phase 5.1 — Revert ev_min on VPS (this session, ~10min)

1. SSH + edit `.envrc`: `SPOT_AWARE_EV_MIN_DOLLARS=0.003` (was 0.05)
2. Set `ENSEMBLE_MODE=shadow`, `ANTHROPIC_API_KEY=$key`
3. Restart bot-staging.service
4. Verify journal shows ensemble loaded + shadow mode active

### Phase 5.2 — 24-72h shadow data collection (passive)

Operator runs `runbooks/scripts/ensemble_shadow_rollup.py` daily to
compare:
- Deterministic-only WR vs (deterministic AND meta-FIRE) WR
- Per-specialist agreement rate
- Cost actually spent vs budget cap

### Phase 5.3 — Promotion gate (operator decision after 5.2)

If shadow data shows:
- (a) Meta's gate WR ≥ deterministic WR + 5pp → flip `ENSEMBLE_MODE=gate`
- (b) WR within ±3pp → keep deterministic; ship the shadow-rollup as
  ongoing monitoring; reduce ensemble cost via caching priors
- (c) Meta WR worse → drop ensemble, write Phase 5 postmortem

### Phase 5.4 — Offline calibration loop (continuous, post-promotion)

Weekly: replay past 7 days through ensemble against actual outcomes;
LLM-summarised Anthropic call recommends prior/threshold updates.
Operator reviews + applies.

## Risks I've already explained to the operator

1. **Bleed during shadow window** — wide ev_min fires loose; before
   ensemble is gating in production, expected drag is ~$0.08/trade ×
   288 fires/day = -$23/day. Across a 3-day shadow window: **-$70**
   bankroll bleed before promotion. Reversible via `SPOT_AWARE_EV_MIN_
   DOLLARS=0.05` env-flip.

2. **LLM ensemble may not lift WR** — Phase 3 already cut it once. We
   may discover the same. Shadow-mode is the test; the cost is bounded
   ($1-2/day for 3 days = $3-6 total Anthropic spend to validate).

3. **Latency** — Phase 3 cut on latency budget. With instant-settle
   (background-task) this matters less; the fire-time Anthropic call
   no longer blocks the runner main loop. But meta-decision still must
   complete within window-fire-eligible time (a few seconds typically).

## What this DOES NOT change

- Background-settle architecture (kept)
- Orphan recovery (kept)
- Tier rejection 50-70% (kept) — fundamental loss tier
- Decision-log JSONL schema (extended with ensemble-vote section but
  not breaking)
- Bankroll, sizing ($5 flat per decision #9)
- Real money gating (Phase 10, far future)

## Files touched (this session)

- `scripts/run_paper.py` — STRATEGY=ensemble dispatch
- `src/polymarket_bot/strategies/ensemble_wrapper.py` (NEW) — the
  wrapper that runs v2 then LLM gates
- `src/polymarket_bot/_paper/decision_log.py` — extend `record_fired`
  to include ensemble vote payload
- `tests/strategies/test_ensemble_wrapper.py` (NEW)
- `runbooks/scripts/ensemble_shadow_rollup.py` (NEW)
- `runbooks/decisions/phase-5-llm-ensemble-2026-05-10.md` — operator's
  approval + revert direction with my recorded objection

## Decision (recorded)

Operator overrode my recommendation to **keep** `ev_min=0.05` for the
v2-tight soak. Operator's reasoning: maximum data collection from wide
firing + LLM as the new gate is preferable to slow drip-feed. My
recorded objection: the 292-fire audit showed the "edge" is
specifically in `ev≥0.05` trades; wide firing relies entirely on the
LLM ensemble to recover that lost selectivity. Operator accepted the
risk of the bleed window (~3 days × $23/day = -$70) in exchange for
faster Phase 5 validation.

This document is the operator's signed-off plan. Per CLAUDE.md rule
#1 (design doc before code), all subsequent commits in this phase
reference this file.
