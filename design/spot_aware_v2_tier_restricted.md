# SpotAwareStrategy v2 — tier-restricted, no-fallback (2026-05-09)

> **Status:** PROPOSED — author this doc, get operator approval, THEN implement.
> Per CLAUDE.md rule #1.

## Why this exists

The 21.4h aggressive-mode soak (Phase 11.A.2, audited at
`runbooks/research/edge-discovery-2026-05-09.md`) revealed three
structural problems in v1 + aggressive mode that are washing out a real
edge:

1. **Tier 50-70% is a structural loss** — 195 fires, 49.2% WR, **-$76.73**.
   The asymmetric payoff at this price band means even at near-50% WR
   you bleed (winners pay less than losers cost). Same logic that
   previously closed the 85-100% tier (Slow-Minute trap) applies here.
2. **The `p_win=0.54` aggressive-mode fallback is a false EV signal
   factory** — the EV [0.02, 0.05) bucket was the WORST performer at
   -$60.06 / 38.2% WR / n=57. These trades looked positive-EV under
   the fallback but lost money systematically.
3. **Aggressive mode fires 95% of the time on |Δ|<2 bps** (244 of 256
   fires). The bot can't beat fees long-term in pure-noise zone.

If we'd applied "drop tier 50-70%" alone to the existing 256 fires,
counterfactual PnL would be **+$75.93** instead of -$0.80 (per
audit §7).

## What v2 changes

| Gate | v1 (aggressive_mode=ON) | v2 (proposed) |
|---|---|---|
| Δ_min check | bypassed | **enforced ≥ 5 bps** (loose-start floor; matches priors table coverage) |
| Δ_max check (50 bps) | bypassed | **enforced** |
| Δ ≠ 0 alignment | enforced | enforced |
| Aligned-side-only | enforced | enforced |
| Tier ∈ [0.15, 0.85] | enforced | enforced |
| Tier 85-100% rejected | yes | yes (unchanged) |
| Tier <15% skipped | yes | yes (unchanged) |
| **Tier 50-70% rejected** | **no** | **YES — new** |
| Prior lookup hit required | falls back to `p_win=0.54` | **REQUIRED — no fallback** |
| EV gate | bypassed | **enforced ≥ $0.005/share** (design-doc default) |
| Fire-once-per-window | enforced | enforced |

Three things that DON'T change:

- Decision interface is unchanged (same `Decision(...)` returned to
  the runner; same rationale string format with `strategy=spot_aware_v2`
  marker for telemetry).
- Priors table (`data/spot_aware_priors.json` v1) unchanged — v2
  just consults it more strictly.
- Fire-once-per-window invariant — capital management unchanged.

## What v2 will fire on

Concrete prediction based on the audited data: v2 would have fired in
**~50 of the 256 aggressive-mode windows** (the `tier 30-50 + EV ≥ 0`
filter row of the audit's §7), with:

- WR ≈ 50% (matches 30-50% tier observation)
- Per-trade ≈ +$0.79 (matches 30-50% tier observation)
- **Cumulative PnL ≈ +$40** (vs -$0.80 actual under aggressive)
- Fire rate ≈ **45-60/day** (vs 250/day aggressive)

This is a **fire-rarely / win-often** posture — the opposite of
aggressive mode's "fire-on-every-window" experiment.

## Implementation

### New class — `src/polymarket_bot/strategies/spot_aware_v2.py`

```python
class SpotAwareStrategyV2:
    """Tier-restricted, no-fallback variant of SpotAwareStrategy.

    Same MarketEvent interface as v1; same Decision emission. Three
    structural changes vs v1:
      1. Tier 50-70% is REJECTED (not just admitted-with-discipline).
      2. No p_win=0.54 fallback — priors-table miss = no fire.
      3. Re-enforces delta_min/delta_max + EV gate (no aggressive
         bypass available).
    """
```

Reuses `SpotAwarePriors` — but extends `is_tier_admitted` semantics by
adding a v2-specific "rejected_tiers" check. Cleanest: subclass or
compose. Implementation choice: **compose** — pass an explicit
`rejected_tiers={(0.50, 0.70)}` to the constructor, leaving v1 priors
untouched.

### New env var — `STRATEGY=spot_aware_v2`

`scripts/run_paper.py::_build_strategy` adds a third branch:

```python
elif name == "spot_aware_v2":
    return SpotAwareStrategyV2(priors=load_priors(), ...)
```

The existing `SPOT_AWARE_*` env vars still apply for parameter
overrides; v2 ignores `SPOT_AWARE_AGGRESSIVE_MODE` (always rejects
the bypass).

### Tests — `tests/strategies/test_spot_aware_v2.py`

Mirror the 9 v1 tests + add v2-specific ones:

1. `test_v2_rejects_tier_50_70_explicitly` — tier 0.55 with a
   priors-hit and positive EV → returns None
2. `test_v2_rejects_priors_miss` — tier 0.40 with no priors-row
   match → returns None (no fallback)
3. `test_v2_rejects_low_delta` — |Δ|=3 bps → returns None
4. `test_v2_rejects_negative_ev` — EV=$0.001 (< 0.005 default)
   → returns None
5. `test_v2_fires_on_priors_hit_in_30_50` — happy path: tier 0.40,
   |Δ|=8 bps with priors hit, EV > 0.005 → returns Decision
6. `test_v2_ignores_aggressive_mode_env` — passing
   `aggressive_mode=True` to v2 should be a no-op (or rejected
   constructor arg)
7. `test_v2_rationale_marks_strategy_v2` — emitted Decision rationale
   contains `strategy=spot_aware_v2`

### What v2 is NOT

- Not a multi-market strategy (Phase 11.D, deferred)
- Not a tier 15-30% bonanza — keeps it admitted at the same priors-hit
  bar as v1 (small samples; n=4 in current data)
- Not a new priors table (v1 priors are unchanged; we just consult
  them strictly)
- Not a real-money go/no-go (Phase 11.B, separate decision)
- Not a different signal — still the spot-Δ alignment edge from the
  Bonereaper 30d analysis

## Rollout plan

1. **Land this design doc + the v2 implementation in PR #X.**
2. **Wait for the 48h gate verdict on v1-aggressive** (`runbooks/gates/spot-aware-paper.sh`).
3. **At the gate, regardless of pass/fail**: revert aggressive flag.
   - If gate passes numerically → still revert per the edge-discovery
     evidence; document as Branch C "conditional revert" in the gate
     prompt.
   - If gate breaches → revert per the script's exit code.
4. **Switch to v2** by setting `STRATEGY=spot_aware_v2` in
   `/home/ops/polymarket-5m-bot/.envrc` on the VPS, restart
   `bot-staging.service`.
5. **Re-soak v2 for 7 days** at the same paper-soak cadence.
6. **Re-run the gate script** with the v2 data after 7 days. Promote
   v2 if it clears the same 5 hard exit criteria + a per-trade-PnL
   floor (proposed: ≥ +$0.30/trade across the soak).

## Risk + mitigation

**Risk**: v2 fires so rarely that 7-day soak yields too small a
sample for confidence (45-60/day × 7 = ~315-420 fires; n=315 is
acceptable but tight).

**Mitigation**: extend soak to 14 days if 7-day n < 300 settled+filled.

**Risk**: dropping the priors-fallback means v2 misses some
plausibly-edged trades that just don't have a priors row.

**Mitigation**: monitor "missed because no prior" count via a new
rationale field (`fired=false reason=no_prior`). If meaningful, v2.1
extends the priors table with the missing buckets.

**Risk**: the aggressive-mode 21h sample showed positive EV in some
windows by accident (n is small). v2's filter projection of +$0.79/trade
might not hold up at scale.

**Mitigation**: the 7-day re-soak IS the test. If v2 doesn't reproduce
the +$0.79/trade, we revisit (don't promote, write a v3 or
postmortem).

## Locked decisions touched

None. v2 is fully consistent with:
- Decision #6 (composite ≥ 0.6 deterministic) — v2 enforces a stricter
  composite (priors-hit + Δ≥5 + EV≥0.5¢ + tier ∈ {15-30, 30-50, 70-85}).
- Decision #19 (Bonereaper cloning aborted) — v2 uses the
  spot-Δ-alignment edge from Bonereaper 30d analysis, not wallet
  copying.
- The Slow-Minute trap research that closed 85-100% — v2 extends the
  same logic to 50-70% based on this session's data.

## See also

- `runbooks/research/edge-discovery-2026-05-09.md` — the audit that
  motivates v2
- `runbooks/decisions/aggressive-mode-2026-05-09.md` — the v1
  experiment v2 supersedes
- `runbooks/decisions/phase-11.a.2-refinement-plan-2026-05-09.md` —
  rung 4 placeholder where v2 was first proposed
- `design/spot_aware_strategy.md` — v1 spec
- `runbooks/research/scout-final-comparison-2026-05-08.md` — the
  Slow-Minute -$3,964/7d study whose logic v2 extends
