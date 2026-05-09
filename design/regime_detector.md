# Regime detector design (v3 strategy layer)

> **Status:** PROPOSED — design doc draft. Will validate against the
> existing 256-trade dataset BEFORE implementation, then implement and
> deploy after the v2 7-day re-soak completes (Phase 4 of
> design/bot_v3_roadmap.md).

## Why this exists

Per `runbooks/research/regime-shift-investigation-2026-05-09.md`:

- Pre-peak window (22:00-05:30 UTC, 7.5h, drift regime): 106 trades, 61.5% WR, +$133.88
- Post-peak window (06:00-17:00 UTC, 12h, chop regime): 150 trades, 41.5% WR, -$134.68

**Same trades. Same strategy. Same priors. 20pp WR swing across two large samples.** The pattern was uniform across every dimension (every tier, side, Δ bucket got 10-25pp worse). Tier mix barely shifted (76% → 76% in 50-70%). The signal itself stopped working.

Spot-Δ alignment is regime-dependent: it works in trending markets and fails in chop. v2 (tier-restricted) reduces the absolute swing but doesn't address the regime sensitivity. **Without a regime detector, v2 will continue to net out near-zero across drift+chop cycles.**

## What v3 changes (just the regime layer)

| Gate | v2 (no regime) | v3 (with regime) |
|---|---|---|
| All v2 gates (Δ≥5, real priors, EV≥0.005, tier ∈ {15-30, 30-50, 70-85}, etc.) | enforced | enforced |
| **Regime classifier == "trending"** | n/a | **NEW — required** |

If regime is "trending" → v3 fires per v2 logic.
If regime is "chop" or "mixed" → v3 abstains (no fire, no alert).

## The classifier

**Hypothesis**: BTC's 5-min realized volatility relative to its 10-min realized volatility is a regime classifier.

```
realized_vol_5m  = std(spot ticks in last 300s) / mean(spot ticks in last 300s)
realized_vol_10m = std(spot ticks in last 600s) / mean(spot ticks in last 600s)
ratio = realized_vol_5m / realized_vol_10m

regime = "trending"  if ratio > 1.20  (5m more volatile than baseline)
regime = "chop"      if ratio < 0.80  (5m quieter than baseline = oscillation)
regime = "mixed"     if 0.80 ≤ ratio ≤ 1.20
```

**Intuition**: in a trending market, recent ticks have larger absolute moves than the 10-min baseline (price is going somewhere). In chop, recent ticks are oscillating around a level so 5-min std looks similar or smaller than 10-min std (back-and-forth cancels out).

### Alternative classifiers considered

1. **Hurst exponent** (rolling, 5-min window). H > 0.55 = trending; H < 0.45 = mean-reverting; in between = random walk. **Rejected**: Hurst is computationally expensive and unstable on n<30 samples.
2. **ADX** (Average Directional Index, 14-period). Standard TA classifier. **Rejected**: requires OHLC bars; we have raw ticks. Could compute synthetic 30s bars but adds complexity.
3. **Spot-direction persistence** over the last 30 seconds. % of consecutive same-sign moves. **Rejected**: too noisy at our tick frequency; requires careful smoothing.
4. **Vol-of-vol** (variance of the realized vol). Higher when chop is interspersed with bursts. **Rejected**: more complex; harder to interpret; preserves no clear edge over the simple ratio.

**The 5m/10m vol ratio is the simplest classifier that captures the trending-vs-chop distinction.** Picking simplest first; fall back to alternatives if validation fails.

### Thresholds

The 1.20 / 0.80 thresholds are starting estimates. Actual cutpoints get tuned on the validation data (see below) — likely they'll move but the structure stays the same.

## Validation BEFORE implementation

Per CLAUDE.md rule #1 + the "no vibe coding" feedback memory: validate the classifier hypothesis against the existing 256-trade dataset BEFORE writing any production code.

### Validation script

`runbooks/scripts/regime_classifier_validation.py`:

1. Load `state/staging/decisions/*.jsonl` (the 256-trade dataset)
2. For each fired decision, compute the 5m/10m vol ratio at decision time using captured spot ticks (from `state/ticks/binance/*.parquet`)
3. Bucket trades by regime (trending / chop / mixed) using the proposed ratio thresholds
4. Compute WR + per-trade PnL per bucket
5. Compute "what if v3 had only fired in trending" counterfactual

### Validation gate (binary)

- (a) Trending bucket WR is **≥ 8pp higher than chop bucket WR** AND counterfactual filter (fire only in trending) shows **≥ +$0.50 per-trade improvement** over v2 baseline → **HYPOTHESIS CONFIRMED** → implement
- (b) Trending vs chop WR difference < 8pp → **HYPOTHESIS NOT CONFIRMED** → try alternative classifier (Hurst, ADX, spot-persistence) before abandoning
- (c) Both classifiers fail → **REGIME DETECTION DOESN'T WORK FOR THIS STRATEGY** → revisit signal entirely (decision point in Phase 4 of roadmap)

## Implementation (post-validation)

### New module `src/polymarket_bot/strategies/regime_detector.py`

```python
class RegimeDetector:
    """Classifies the current spot regime as trending / chop / mixed
    based on 5m/10m realized volatility ratio."""

    def __init__(
        self,
        *,
        window_5m_s: int = 300,
        window_10m_s: int = 600,
        trending_threshold: float = 1.20,
        chop_threshold: float = 0.80,
    ) -> None:
        ...

    def observe_spot(self, ts_ns: int, price: float) -> None:
        """Buffer spot ticks for vol computation."""
        ...

    def classify(self, now_ns: int) -> Literal["trending", "chop", "mixed", "unknown"]:
        """Return regime at now_ns. 'unknown' if buffer < 10m."""
        ...
```

Memory-cheap (rolling buffer, max ~600 ticks at 1Hz tick rate = ~5KB).
No I/O, no async. Pure deterministic function over recent spot ticks.

### Wrapping v2 strategy

Modify `SpotAwareStrategyV2` (or subclass into `SpotAwareStrategyV3`):

```python
class SpotAwareStrategyV3(SpotAwareStrategyV2):
    name = "spot_aware_v3"

    def __init__(self, *, regime_detector: RegimeDetector, **kwargs) -> None:
        super().__init__(**kwargs)
        self._regime = regime_detector

    async def on_event(self, event: MarketEvent) -> Decision | None:
        if isinstance(event, SpotTick):
            self._regime.observe_spot(event.ts_utc_ns, event.price)
        # let v2 do its work
        decision = await super().on_event(event)
        if decision is None:
            return None
        # v3: gate on regime — only fire if classifier says trending
        regime = self._regime.classify(event.ts_utc_ns)
        if regime != "trending":
            return None
        return decision
```

### Selectable via `STRATEGY=spot_aware_v3` env var

Same dispatch pattern as v2 (modify `scripts/run_paper.py::_build_strategy`).

### Tests

`tests/strategies/test_spot_aware_v3.py`:

1. Test regime detector with synthetic trending spot history → ratio > 1.20 → "trending"
2. Test regime detector with synthetic chop spot history → ratio < 0.80 → "chop"
3. Test v3 strategy fires when v2 would AND regime=trending
4. Test v3 strategy abstains when v2 would fire BUT regime=chop
5. Test v3 strategy abstains when regime=unknown (buffer cold)

## Gating + rollout

### Phase 4 deploy gate

Re-soak v3 for 7 days with regime filter enabled. Compare per-trade PnL vs Phase 3 v2-alone baseline:

- (a) v3 per-trade PnL ≥ +$0.50 (vs v2's expected ~+$0.30) → **REGIME DETECTOR WORKS** → keep enabled, proceed to Phase 5 (3-agent ensemble)
- (b) v3 per-trade PnL ~ same as v2 → **REGIME DETECTOR NEUTRAL** → drop, revert to v2, proceed to Phase 5 anyway
- (c) v3 per-trade PnL < v2 → **REGIME CLASSIFIER WRONG** → try alternative classifier OR drop the layer

## What this is NOT

- **Not a multi-signal ensemble** — that's Phase 5 (decision #5: orderbook + oracle-gap + momentum + Sonnet meta).
- **Not variable sizing** — that's Phase 6, gated on this.
- **Not a strategy rewrite** — v3 = v2 + a single boolean gate. Same priors, same tier filter, same EV gate. Just an additional "is the market trending?" check.
- **Not a chop-trading strategy** — v3 abstains in chop. We don't try to PROFIT from chop; we just don't lose money there.
- **Not a time-of-day filter** — the regime-shift investigation showed Asia hours had the trend regime, but that's a 1-cycle observation. v3 uses the structural regime classifier (vol ratio), not a calendar-based filter.

## Constraints + considerations

### Spot tick storage

The detector needs the last 10 min of spot ticks. Currently the strategy keeps `_spot_now` and `_window_open_spot` only — no buffer. New: a deque with TTL=600s. ~5KB memory at 1Hz tick rate.

### Cold-start

For the first 10 minutes after restart, the buffer is partial. `classify()` returns "unknown" → v3 abstains. Acceptable: better to skip 10 min of fires than fire on garbage.

### Latency

Computing vol ratio is O(buffer_size) ≈ 600 floats. Negligible (<1ms).

### Backtest equivalence

The validation script must use the SAME tick history that the strategy would have observed at decision time. Use the captured `state/ticks/binance/*.parquet` (per Phase 2 capture).

## Open design questions (for operator review)

1. **5m/10m windows correct?** Could try 3m/6m (faster reaction) or 5m/15m (more stable baseline). Validation script can A/B these.
2. **Mixed regime: abstain or fire?** Current proposal: abstain. Alternative: fire with reduced confidence (which would feed sizing in Phase 6). For Phase 4, simplest = abstain.
3. **Regime hysteresis?** If we cross the 1.20 threshold every 30 seconds, we'd flicker. Add hysteresis: once "trending", stay "trending" until ratio drops below 1.05 (and vice versa for chop).
4. **Should the detector also block at "spot too quiet" (vol < $X)?** A dead market has tiny moves that don't have signal even in "trending". Maybe add an absolute vol floor.

## See also

- `runbooks/research/regime-shift-investigation-2026-05-09.md` — the data motivating this design
- `runbooks/research/edge-discovery-2026-05-09.md` — companion finding (per-tier edge)
- `design/spot_aware_v2_tier_restricted.md` — what v3 builds on
- `design/bot_v3_roadmap.md` Phase 4 — context for this in the broader plan
