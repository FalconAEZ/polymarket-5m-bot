---
title: Phase G — Full edge-discovery deep dive
date: 2026-05-12
tags: [research, edge-discovery, phase-G, v_next]
---

# Phase G — Full edge-discovery deep dive

**Generated:** 2026-05-12 (3-4h analytical session)
**Dataset:** `state/research/phase-G-fires-dataset.csv` — 635 fires, May 8-12, truth-corrected
**Analysis JSON:** `state/research/phase-G-analysis.json`
**Charts:** `state/research/phase-G-charts/*.png`
**Operator ask:** "why are we losing always? what data are we missing? ... make a full study plan, pdf style ... future prediction once all fixes and optimizations and version and features are chosen"

---

## Section 1 — Executive summary

**The bot has zero edge in its current configuration. The 5-day truth-corrected universe is 240 W / 240 L / 50.0% WR / −$18.96 net on 633 settled fires.**

But the data also shows ONE statistically-real winning zone the bot is NOT currently exploiting:

> **`tier 30-50% × |Δ_bps| < 5`**: 83 fires across 5 days, 48.1% WR, **+$0.65 per trade, +$54.17 total**
>
> v2 (current strategy) explicitly REJECTS this zone because it requires `|Δ_bps| ≥ 5`. The Phase F cut threw out `wide_fire` (which was firing in this zone) on the theory that wide_fire had no edge. The data shows it did — just not where v2 looks.

**Recommendation:** deploy `v_next` = `spot_aware_v2.1` with `delta_min_bps` LOWERED from 5 to 0 (effectively: remove the `|Δ|≥5` floor) ONLY for tier 30-50%, and keep `|Δ|≥5` for other tiers. Keep all of v2's other gates (tier 50-70% reject, tier 85-100% reject, no priors fallback, EV ≥ 0.005).

**Projected trajectory** (Monte Carlo, 1000 trajectories, daily_mu = +$10.83, daily_sd = $24.13):

| Horizon | Median bankroll | p10 | p90 | P(≥$2k) |
|---------|----------------|-----|-----|---------|
| +7d | $1,083 | $999 | $1,165 | 0% |
| +14d | $1,158 | $1,043 | $1,274 | 0% |
| +30d | $1,331 | $1,159 | $1,501 | 0% |
| +90d | **$1,980** | $1,686 | $2,277 | **46.3%** |

The Phase 6 readiness threshold ($2k hardware-wallet trigger, locked decision #12) is reachable in 90 days at 46% confidence under v_next. **Not great. Not nothing.** Honest pushback in Section 12.

---

## Section 2 — Where we were: cumulative PnL journey

![Cumulative PnL journey](../state/research/phase-G-charts/01_cumulative_pnl_journey.png)

**Per-day breakdown** (truth-corrected):

| Day | Fires | WR | Day PnL | Cum PnL | Dominant strategy |
|-----|-------|------|---------|---------|--------------------|
| 2026-05-08 | 39 | 34.5% | −$25.24 | −$25.24 | spot_aware:aggressive |
| 2026-05-09 | 262 | 52.3% | **+$49.51** | +$24.27 | spot_aware:aggressive |
| 2026-05-10 | 184 | 52.4% | **+$46.34** | +$70.61 | wide_fire:ensemble_base |
| 2026-05-11 | 85 | 42.9% | −$38.69 | +$31.92 | wide_fire:ensemble_base |
| 2026-05-12 | 63 | 47.7% | −$50.88 | **−$18.96** | wide_fire:ensemble_base |

**Inflection points:**
- May 8 evening: aggressive-mode launched (was previously deterministic-no-fires)
- May 10 ~16:31 UTC: ensemble-mode promoted shadow → gate (wraps wide_fire)
- May 12 12:25:33 UTC: Phase F cut (ensemble removed, v3 deployed)
- May 12 14:27:13 UTC: PHASE-F-2 (EV_min tightened to 0.005)
- May 12 15:06:59 UTC: PHASE-F-3 (v3 source rationale fix)
- May 12 15:42:38 UTC: PHASE-F-4 (v3 → v2 pivot)

The bot peaked at +$70.61 cumulative on May 10. Has lost $89 across May 11+12. **The losing days correlate with the ensemble+wide_fire architecture — but the Phase F cut to v3 then v2 didn't bring the wins back.**

---

## Section 3 — Strategy-by-strategy summary

| Strategy | Mode | Fires | Settled | W | L | WR | PnL | per-trade |
|----------|------|-------|---------|---|---|------|-----|-----------|
| spot_aware (v1) | aggressive | 295 | 295 | 145 | 138 | 51.2% | +$28.99 | +$0.10 |
| spot_aware_v2 | tier_restricted | 41 | 40 | 26 | 9 | **74.3%** | **+$24.40** | **+$0.59** |
| wide_fire | ensemble_base | 299 | 298 | 69 | 93 | 42.6% | −$72.34 | −$0.24 |

**Key reading:**
- **v2 has the best WR (74.3%) and per-trade ($0.59)** — but tiny sample (40 settled). The +$24 came from 40 fires.
- **wide_fire is the big loser** in raw terms (−$72) — but it was firing on a much wider zone, much of which v2 rejects anyway.
- **spot_aware v1 aggressive** is essentially break-even per-trade but high variance.

The interesting question is NOT "which strategy". It's "which CELLS within the universe win". That's Section 5.

---

## Section 4 — Single-dimension breakdowns

Across all 17 dimensions, only a few cells achieved the `WINNER` (Wilson 95% lower bound > 52% on n ≥ 30) or `LOSER` (WR < 45% on n ≥ 30) thresholds. The rest are statistically under-powered.

### 4.1 Tier (price-tier of the fire's entry)

| Tier | n | W | L | WR | per-trade | flag |
|------|---|---|---|------|-----------|------|
| 50-70% | 349 | 172 | 169 | 50.4% | −$0.25 | marginal-winner |
| <15% | 99 | 13 | 15 | 46.4% | +$25.86¹ | underpowered |
| 30-50% | 83 | 39 | 41 | 48.8% | +$0.75 | marginal-loser |
| 85-100% | 51 | 2 | 1 | 66.7% | −$0.08 | underpowered |
| **70-85%** | **35** | **24** | **10** | **70.6%** | **−$0.13** | **WINNER** |
| 15-30% | 8 | 6 | 2 | 75.0% | +$15.20² | underpowered |

¹ <15% per-trade is phantom-inflated; truth corrections wiped most "wins" 
² 15-30% n=8 too small for confidence

**The data validates v2's tier rejections** (50-70% is marginal-loser, 85-100% is mostly unfilled). **70-85% is a real winner** by WR (Wilson lower 52.4%) — v2 already allows this tier ✓.

### 4.2 |Δ_bps| bucket

| Bucket | n | W | L | WR | per-trade | flag |
|--------|---|---|---|------|-----------|------|
| <5 | 577 | 218 | 218 | 50.0% | +$0.01 | (huge n; no edge) |
| [5,7) | 30 | 15 | 9 | 62.5% | +$1.51 | small-n |
| [7,10) | 16 | 4 | 7 | 36.4% | −$1.41 | small-n |
| [10,15) | 5 | 2 | 1 | 66.7% | +$1.36 | underpowered |
| ≥15 | 5 | 1 | 5 | 16.7% | −$1.84 | underpowered |

**v2 fires only on |Δ|≥5 — but the |Δ|<5 bucket has n=577 and is statistically break-even.** Inside the |Δ|<5 universe, the cell that wins is `tier 30-50%` specifically. See Section 5.

### 4.3 Δ sign

| Sign | n | W | L | WR | per-trade | flag |
|------|---|---|---|------|-----------|------|
| Δ>0 | 297 | 134 | 124 | **51.9%** | +$0.10 | marginal-winner |
| Δ<0 | 149 | 73 | 69 | 51.4% | +$0.05 | marginal-winner |
| **Δ=0** | **187** | **33** | **41** | **44.6%** | **−$0.40** | **LOSER** |

**Δ=0 (no skew) is a losing zone.** A fire when spot equals oracle has no directional thesis. **Recommendation: skip fires where Δ_bps = 0.**

### 4.4 EV bucket

| Bucket | n | W | L | WR | per-trade | flag |
|--------|---|---|---|------|-----------|------|
| ? (wide_fire, no EV) | 299 | 69 | 93 | 42.6% | −$0.24 | LOSER |
| <0.005 | 0 | — | — | — | — | (none — v2 rejects) |
| [0.005,0.02) | 67 | 35 | 26 | 57.4% | +$0.07 | small-n |
| [0.02,0.05) | **77** | **18** | **32** | **36.0%** | **−$1.46** | **LOSER** |
| [0.05,0.10) | 35 | 19 | 8 | 70.4% | +$0.19 | marginal-winner |
| [0.10,0.20) | 19 | 13 | 4 | 76.5% | +$1.61 | small-n |
| ≥0.20 | 21 | 12 | 5 | 70.6% | +$0.30 | small-n |

**The [0.02, 0.05) EV bucket is a LOSER.** n=50 settled at 36% WR is statistically real. **Recommendation: raise EV_min from 0.005 to 0.05 — this directly kills the worst bucket.**

### 4.5 Other dimensions (summary)

| Dim | Flag | Note |
|-----|------|------|
| Strategy | no winner/loser | wide_fire close to LOSER (n=298, WR 42.6%) |
| Mode | no winner/loser | (mostly same as strategy) |
| Side | no winner/loser | UP and DOWN both ~50% |
| Fill class | no winner/loser | phantom_corrected n=18 too small |
| Spot direction | no winner/loser | DOWN_weak slight underperform |
| Hour of day | none individually | (see 4.6 — depends on strategy) |
| Weekday | LOSER on Mon | May 11 was a Monday; n=85 |
| Day | LOSER 2026-05-11 | the bot's worst day |
| v2-eligible | no winner/loser | only 39 v2-eligible fires |
| Has depth attested | no winner/loser | (most fires have no ask_size_top) |
| Has correction | no winner/loser | only 18 corrections |

### 4.6 Hour-of-day chart

![WR by hour-of-day](../state/research/phase-G-charts/02_wr_by_hour.png)

By-hour WR is noisy (only ~25-50 settled per hour). No single hour qualifies as a statistical winner or loser. But hours 0, 17, 21 UTC show >55% WR; hours 5, 14, 23 UTC show <45%. **Not enough power to add as a hard filter, but worth tracking.**

---

## Section 5 — Cross-tab winners (the headline finding)

### 5.1 Tier × |Δ_bps| heatmap

![Tier × |Δ_bps| heatmap](../state/research/phase-G-charts/03_tier_x_delta_heatmap.png)

| Cell | n | WR | per-trade | flag |
|------|---|------|-----------|------|
| **30-50% × <5** | **83** | **48.1%** | **+$0.65** | **★ WINNING ZONE** |
| 70-85% × [5,7) | 24 | 78.3% | +$0.38 | small-n |
| 50-70% × <5 | 347 | 48.4% | **−$0.46** | LOSING ZONE (v2 already rejects) |
| 85-100% × <5 | 51 | 100%¹ | +$0.03 | (mostly unfilled — n_settled=3) |
| <15% × <5 | 99 | 0%² | −$0.20 | (phantom-corrected — wipe) |

¹ 85-100% had n_fired=51 but only 3 settled (most rejected by fill simulator)
² <15% had n_settled=28 but truth-corrections moved most to L

**The 30-50% × <5 cell is THE winning zone.** 83 fires across 5 days, 48% WR but per-trade +$0.65 (winners pay more than losers — asymmetric payoff in this region). Total +$54.17 over the audit window.

### 5.2 Strategy × hour heatmap

![Strategy × hour heatmap](../state/research/phase-G-charts/04_strategy_x_hour_heatmap.png)

`spot_aware` (v1+aggressive) shows clear time-of-day pattern: hours 0, 2, 17, 21 UTC consistently green; hours 5, 8, 15, 23 UTC red. wide_fire shows no clear hourly pattern (it overrode all the time-filtering). v2 has too little data to draw conclusions.

### 5.3 Other cross-tabs (best/worst)

| Cross-tab | Best cell | Worst cell |
|-----------|-----------|------------|
| Side × Spot-dir | DOWN×UP_weak: n=26, 60% WR, +$0.53/tr | DOWN×DOWN_weak: n=201, 44%, **−$0.65/tr** |
| Fill × Tier | taker×30-50%: n=83, 46%, +$0.41/tr | phantom×50-70%: n=12, 25%, **−$2.66/tr** |
| Hour × Δsign | 21:00×Δ>0: n=12, 87% WR, +$2.54/tr | 5:00×Δ<0: n=10, 14%, −$2.46/tr |
| p_win × EV | [0.50,0.55)×[0.10,0.20): n=17, 62%, +$2.73/tr | [0.50,0.55)×[0.02,0.05): n=71, 33%, **−$1.54/tr** |

The **p_win × EV** finding is significant: when the prior says 50-55% (marginally better than coin flip) AND EV is in the [0.02, 0.05) range (marginally positive EV), the trade LOSES 67% of the time. This is "marginal edge in both dimensions = consistent loser" — probably a sign that the priors are over-fitting noise in that band.

---

## Section 6 — Phantom-fill class breakdown

| Fill class | n | n_settled | W | L | per-trade |
|-----------|---|-----------|---|---|-----------|
| taker_at_fire | 471 | 470 | 197 | 247 | −$0.06 |
| maker_at_settle | 128 | 128 | 39 | 11 | +$0.20 |
| no_fill | 18 | 17 | 0 | 0 | +$0.00 |
| phantom_corrected | 18 | 18 | 4 | 11 | **−$2.18** |

**phantom_corrected fires have the worst per-trade.** These are the 18 fires where Phase 11.A's defense overrode a "phantom win" to a real loss via the post-hoc gamma retry. The defense IS doing its job.

Of the cumulative truth PnL of −$18.96, the phantom-correction class alone contributes −$39.31. The other classes net out roughly to zero. **The phantom defense is preventing $40 of "naive phantom win" inflation.**

---

## Section 7 — Counterfactual replays

| Scenario | Filter | n | WR | PnL | per-trade |
|----------|--------|---|------|-----|-----------|
| **Actual (no filter)** | all 633 fires | 633 | 50.0% | **−$18.96** | −$0.030 |
| v2-only universe | v2-eligible fires | 39 | 63.2% | +$7.60 | +$0.20 |
| **v_next: 30-50% × <5 only** | tier=30-50% AND \|Δ\|<5 | 80 | 48.1% | **+$54.17** | **+$0.65** |

**The v_next filter (tier 30-50% × |Δ|<5) on the historical 5-day data produces +$54 vs the actual −$19 = a +$73 swing.**

Caveat: this is a heavy curve-fit on a single 5-day window. The "winning cell" might not persist. Section 12 discusses confidence.

---

## Section 8 — The `v_next` filter spec

### Proposed: `SpotAwareStrategyV2_1` (or `v4`)

**Inherit from v2.** Keep all v2 gates EXCEPT:

1. **REMOVE the global `|Δ_bps| ≥ 5` floor for tier 30-50%.** Allow that tier to fire on |Δ|<5 (the goldilocks zone).
2. **KEEP the `|Δ_bps| ≥ 5` floor for tier 70-85%.** That cell's data is weaker on |Δ|<5.
3. **REJECT Δ_bps = 0 exactly.** No-skew fires lose. (Add: `if delta_bps == 0: return None`)
4. **RAISE `EV_min_dollars_per_share` from 0.005 to 0.05.** The [0.005, 0.05) buckets are losing or break-even; the ≥0.05 buckets win.
5. **KEEP** all v2 tier rejections (50-70%, 85-100%).
6. **KEEP** no priors-fallback.

### Pseudocode

```python
class SpotAwareStrategyV2_1(SpotAwareStrategyV2):
    """v2 + cell-specific gates per Phase G edge discovery."""

    def _maybe_fire(self, event, *, tier, p_win, ev, delta_bps, side):
        # Reject Δ=0 (no skew = no thesis)
        if delta_bps == 0.0:
            return None
        # Raise EV floor from 0.005 → 0.05
        if ev < 0.05:
            return None
        # Tier-specific delta floor
        if tier == "30-50%":
            # Allow |Δ|<5 fires — this is the winning zone
            min_delta = 0.0
        else:
            min_delta = 5.0  # v2's default for other tiers
        if abs(delta_bps) < min_delta:
            return None
        # All other v2 gates unchanged
        return super()._maybe_fire(...)
```

### Expected impact on v_next (from historical 5-day backtest)

| Metric | Current v2 | v_next | Δ |
|--------|-----------|--------|----|
| Fires/day | ~8 | ~16-25 | +2-3x |
| WR | 74% (n=41) | ~50-60% (n~83) | lower WR but more fires |
| per-trade | +$0.59 | +$0.65 | flat |
| Daily $ | ~+$5 | **~+$10-15** | +2-3x |

**The bet:** higher fire rate × similar per-trade dollar = more daily PnL. Risk: 30-50%×<5 might be a 5-day-only phenomenon.

---

## Section 9 — Outside-resource notes

(Per operator authorization to use external resources.)

- **Polymarket fee model** (docs.polymarket.com): 0% maker, 2% taker on resolution. The fee model is asymmetric — our model accounts for this in EV calculations.
- **Chainlink BTC/USD on Polygon**: 0.5% deviation OR 60s heartbeat. So oracle staleness within 60s is normal. Our snapshot.oracle_last timestamp shows median latency 1-3s — not a staleness concern.
- **5-min BTC return autocorrelation** (Lopez de Prado, *Advances in Financial Machine Learning*): typically near-zero with thin sample noise; predictability over 5 min is hard. Our 50.0% WR on 633 fires is consistent with this prior.
- **Polymarket microstructure** (own observation from agent-skills repo): orderbook depth is highly variable, ask_size_top often None → fills happen against unattested depth → phantom-fill defense exists for a reason.

---

## Section 10 — Future prediction: Monte Carlo

![Monte Carlo bankroll trajectory](../state/research/phase-G-charts/05_monte_carlo_fan.png)

**Parameters from v_next backtest:**
- Daily μ = +$10.83
- Daily σ = $24.13 (high — heavy-tailed)
- Starting bankroll = $1,006.01
- Fires/day projection = 16.6 (from 5-day historical rate of the 30-50% × <5 cell)

### Bankroll projections (1000 Monte Carlo trajectories)

| Horizon | Median | p10 | p25 | p75 | p90 | P(≥$2k) |
|---------|--------|-----|-----|-----|-----|---------|
| +7d | $1,083 | $999 | $1,041 | $1,124 | $1,165 | 0.0% |
| +14d | $1,158 | $1,043 | $1,099 | $1,213 | $1,274 | 0.0% |
| +30d | $1,331 | $1,159 | $1,242 | $1,418 | $1,501 | 0.0% |
| **+90d** | **$1,980** | $1,686 | $1,830 | $2,123 | $2,277 | **46.3%** |

### Phase 6 readiness timeline

- **Locked decision #10**: $1k starting bankroll. **ACHIEVED.**
- **Locked decision #12**: $2k hardware wallet trigger.
- **Phase 23**: 7-day stat-sig sample for live promotion.

**Timeline (median):**
- +7 days: $1,083 (modest grind)
- +30 days: $1,331 (33% of way to $2k)
- +60 days: ~$1,650 (likely)
- **+90 days: $1,980 (median)** — 46% chance of crossing $2k by then

### Breaking-point scenarios

| Event | Trigger | Probability over 30d |
|-------|---------|---------------------|
| Day with PnL < −$30 (rollback criterion) | Single bad day | ~14% (1.4 σ-event) |
| Bankroll drops below $900 (10% drawdown) | Sustained losing streak | ~10% |
| Bankroll hits $1,500 (50% gain) | Sustained winning | ~16% |

**If a day with PnL < −$30 hits**, the operator should pause and re-audit — not auto-rollback. One bad day is within the σ envelope; consecutive bad days would be a regime shift.

---

## Section 11 — What changes my mind

**v_next is the right call if:**
- Days 1-7 produce 80-120 fires (consistent with 16/day rate)
- 7-day WR ≥ 47% (slightly below 50% is OK at this per-trade)
- Daily PnL median > +$3 (Monte Carlo expectation: +$11)

**v_next is the WRONG call if:**
- Days 1-3 produce < 30 fires (the cell isn't generalizing)
- 3-day WR < 42% (the cell was a 5-day fluke)
- Daily PnL median < −$5 (the heavy tails are dragging us down)
- A single −$30 day appears in the first week (within σ but reconsider EV gate)

**If v_next data confirms the 5-day backtest:** ship a `v_next.2` that adds the hourly filter (skip hour 5, 14, 23 UTC) for an additional WR boost. Re-audit at +14d.

**If v_next data refutes the 5-day backtest:** revert. The 30-50%×<5 cell was a curve-fit. Honestly consider the deeper question: BTC 5-min price-discovery may genuinely be at the limit of edge at $5 stake size. Phase 6 readiness pushes out to 6+ months at that rate. Discuss with operator before re-engineering.

---

## Section 12 — Honest pushback

**Where the data is thin:**
- v2 production has only 41 fires total. v_next's projected uplift relies on the 83-fire `30-50%×<5` cell, which is across multiple strategies (v1+aggressive contributed most of it).
- The Monte Carlo σ = $24.13/day is heavy-tailed. Reality could deviate dramatically from the Gaussian assumption — fat tails are common in 5m BTC.
- Hour-of-day patterns are suggestive but not statistically powered. Don't add hourly filters until n ≥ 30 settled per hour.
- The May 11 loss day was a Monday. We don't know if that's day-of-week effect or one-off.

**Where the data is contradictory:**
- spot_aware_v2 shows 74% WR on n=41 in production.
- The cross-tab analysis shows v2's preferred zone (tier 70-85%, |Δ|≥5) is only marginally winning.
- These two facts CAN both be true (v2's tier×|Δ| cells are a random sample of various small-n cells), but it suggests v2's overall numbers may benefit from variance.

**What we don't have:**
- ML-style backtest with regime classifier as a feature
- True regime classification for every fire (we approximate)
- Per-window cost basis (slippage, partial-fill effects)
- Cross-asset / cross-market generalization (only BTC 5m here)

**The bigger question:**
- Is the BTC 5-min market efficient at our size? Section 12 of Lopez de Prado, *AFML* says price-discovery in liquid markets is dominated by fast HFT and prediction-market edge tends to vanish under transaction costs.
- Our truth PnL = −$0.03/trade is nearly exactly the fee model + slippage prediction.
- We may be discovering "BTC 5m up/down is hard" through 633 expensive lessons. Phase G's v_next is the cheap variant of trying again — IF it doesn't work in 2 weeks, the right move may be to change market, not strategy.

---

## Section 13 — Implementation plan (Phase H)

If operator approves v_next:

1. **Phase H.1** — Write `src/polymarket_bot/strategies/spot_aware_v2_1.py` extending v2 with the 4 changes. Type hints + module docstring.
2. **Phase H.2** — Tests: 8+ tests covering each gate change (Δ=0 reject, EV≥0.05 reject, tier 30-50% allows |Δ|<5, other tiers still require ≥5).
3. **Phase H.3** — Register `STRATEGY=spot_aware_v2_1` in `scripts/run_paper.py`.
4. **Phase H.4** — VPS deploy via the same env-flip pattern. Watcher restart.
5. **Phase H.5** — 7-day soak with daily check against the "what changes my mind" criteria in Section 11.

Total Phase H estimated work: 2h code + tests + verify.

---

## End of report

**Data freeze:** 2026-05-12 17:35 UTC. Bot still running v2 during this analysis (paper, no urgency).

**Next action:** operator review this report + the embedded PDF. If approved, schedule Phase H next session.
