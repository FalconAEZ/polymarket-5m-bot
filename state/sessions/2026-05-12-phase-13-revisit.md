# 2026-05-12 — Phase 13 revisit: regime × gate-mode slice of unfilled fires

**Trigger:** operator request to "revisit Phase 13 + use regime addition" to see if a tractable lift exists when sliced finer than Phase 13's flat counterfactual-W check.

**Method:** new audit script `scripts/audit_unfilled_by_regime_v3.py` extends Phase 13's gap-bucket classifier with two new dimensions:
1. **Gate mode** — pre vs post 2026-05-10 16:31:15 UTC (= ENSEMBLE_MODE=gate promotion)
2. **Regime** — trending / mixed / chop / unknown via live `RegimeDetector` against binance 1m klines (same approach as Phase 15 audit)

## Headline finding — Phase 13 NULL stands, but the SHAPE of a viable lift is now visible

### Fill rate matrix (3-day window, n=477)

| gate | regime | n fired | fill rate |
|---|---|---:|---:|
| pre-gate | trending | 33 | 81.8% |
| pre-gate | mixed | 149 | 89.9% |
| pre-gate | chop | 278 | 86.7% |
| **post-gate** | mixed | 5 | **40.0%** |
| **post-gate** | chop | 12 | **66.7%** |

**Hypothesis 3 from the earlier exchange CONFIRMED in direction (not magnitude — sample too small):** post-gate fill rate is materially lower than pre-gate. Most likely cause: 12s gate-mode LLM blocking allows ask-walks between strategy-emit and shadow-book-fill, dropping a meaningful share of would-be fills into the never_filled bucket.

n=17 post-gate is too small to ship a fix. But the signal direction is consistent with Phase 19 (async LLM pre-compute) being the right structural fix — pre-computing the LLM verdict eliminates the blocking window, which would (per this audit) recover the fill-rate gap.

### Never-filled counterfactual W by gate × regime × gap-bucket

| slice | n | n_res | W | 95% CI | gate decision |
|---|---:|---:|---:|:---:|:---|
| pre-gate **chop** 1-2c | 26 | 26 | **42.3%** | [25.5, 61.1] | ❌ pulls flat-average below 50% — this is the dominant slice killing Phase 13 |
| pre-gate **mixed** 1-2c | 7 | 7 | **57.1%** | [25.0, 84.2] | 🟡 ABOVE 50% but n=7 (need ≥20) |
| pre-gate **trending** 1-2c | 5 | 5 | **60.0%** | [23.1, 88.2] | 🟡 ABOVE 50% but n=5 (need ≥20) |
| pre-gate chop OTHER | 6 | 6 | 50.0% | [18.8, 81.2] | marginal |
| pre-gate chop floor_guard | 5 | 5 | 40.0% | [11.8, 76.9] | phantom-fill defense (do NOT chase) |
| pre-gate mixed OTHER | 3 | 3 | 100.0% | [43.8, 100.0] | n=3 — too tiny |
| pre-gate mixed floor_guard | 5 | 5 | 80.0% | [37.6, 96.4] | phantom-fill defense (do NOT chase) |
| post-gate chop 1-2c | 1 | 1 | 0.0% | [0.0, 79.3] | n=1 |
| post-gate chop floor_guard | 3 | 3 | 100.0% | [43.8, 100.0] | phantom-fill defense |
| post-gate mixed floor_guard | 3 | 3 | 33.3% | [6.1, 79.2] | phantom-fill defense |

**Chop is the entire problem.** 26 of 39 1-2c unfilled records (67%) come from chop regime, with counterfactual W = 42.3%. Forcing those fills would dilute below the bot's 52% baseline.

But mixed + trending unfilled subsets at the same 1-2c gap show W = 57.1% and 60.0% respectively. If those hold above 50% with more samples, a **regime-conditional lift** becomes shippable.

## The conditional-lift design (concept only — not yet implemented)

When n ≥ 20 per non-chop regime slice (suggest 5-7 more days of wide_fire-gate-mode data), the env would look like:

```bash
# Phase 13B candidate envs (NOT yet shipped — design only):
LIFT_BPS=100                              # lift price_limit by 1¢ to taker-cross
LIFT_REGIMES=trending,mixed               # only apply when regime in this set
LIFT_MAX_BPS_FROM_BASELINE=200            # safety cap — never lift more than 2¢
```

The wiring sits in `wide_fire.py` (or a wrapper on it) — apply the lift to the price-limit calc when both:
1. Current regime ∈ LIFT_REGIMES
2. The lift would result in `price_limit > best_ask` (i.e., would have been unfilled at the original)

Tests: regression (lift disabled = no behavior change), conditional firing in each regime, never-fills-in-chop guard.

**This is NOT a phase prompt to write today.** Sample size is too small. The verdict is "wait + re-audit".

## What this audit DID give us

1. **Direction confirmation** — Phase 19 async pre-compute is now better-motivated. Recovered fills × current bot avg PnL/trade = real money.
2. **Regime gate's structural prior is reinforced** — chop is bad for forced fills AND was the marginal-bad regime in Phase 15's gate-WR audit. Same pattern in two independent measurements.
3. **A shippable conditional lift design** exists in concept, waiting for sample size.

## Recommended next action

**Wait. Re-run `scripts/audit_unfilled_by_regime_v3.py` in 5-7 days on the longer window.** If pre-gate mixed/trending 1-2c slices stay above 50% on n ≥ 20, we ship the conditional lift in a Phase 13B re-attempt. If they regress, NULL holds for good and we focus on Phase 19 instead.

In the meantime: Phase 16 (bankroll display), Phase 18B (meta telemetry), Phase 17 (sizing modes) are all higher-information work that doesn't require waiting.

## Files

- `scripts/audit_unfilled_by_regime_v3.py` (NEW) — re-runnable extension of Phase 13's audit
- This session note

No code touching the bot. No env changes. No risk.
