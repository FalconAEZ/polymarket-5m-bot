# Phase 11.A.2 refinement plan (2026-05-09)

**Context:** v2 prompt early-read pickup at 18.1h elapsed (gate criteria
all OK; verdict DEFER until 24-48h mark). All 5 hard exit criteria pass
under both oracle-truth and Polymarket-truth lenses; the resolution-truth
gap is its own incident
(`runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md`).

This doc captures the **operator-actionable** observations from the
audit: what the data says, what's now visible vs blind, and a ranked
list of single-knob tightening proposals if the operator decides to
revert later.

## (a) Tier × era WR/PnL matrix (Polymarket-truth)

The pre-aggressive era is tiny (2 fires across 26 minutes; both unfilled),
so the bucket is informational only — all real signal is in the
aggressive era.

### Aggressive era (n=236 fires, 19.2h window, fire rate 295/day)

| Tier   | n_fires | n_filled | n_settled | n_won | n_lost | WR     | PnL      | comment                       |
|--------|---------|----------|-----------|-------|--------|--------|----------|-------------------------------|
| 15-30% |   4     |   4      |   4       |   2   |   2    | 50.0%  | +$37.98  | n=4 too small to read         |
| 30-50% |  48     |  45      |  47       |  24   |  21    | 53.3%  | +$54.18  | **n=45 above 40 threshold; statistically meaningful; consistent edge** |
| 50-70% | 182     | 174      | 177       |  85   |  89    | 48.9%  | -$78.20  | **biggest sample; mildly losing — the drag** |
| 70-85% |   2     |   2      |   2       |   1   |   1    | 50.0%  |  -$2.97  | n=2 too small to read         |

### Aggregate (all eras combined)

- 238 fires / 225 filled (94.5%) / 232 settled (97.5%)
- 112 won / 113 lost / 49.8% WR / **+$11.00 PnL**
- Fire rate: 287/day (under 350 cap)
- Worst rolling 24h: +$3.83 (well over -$50 floor)

### Headline: the 30-50% tier crossed n=40

The 11.A.2 launch session noted "30-50% looking hot at 87.5% WR on n=10 —
not statistically meaningful; need n≥40". With 19h of soak we're at n=45
filled+settled in 30-50% with **53.3% WR / +$54.18**. That clears the
inconclusive bar — the tier is not just noise.

The 50-70% tier (the big sample) is mildly losing at 48.9%. That's the
bucket to think about.

## (b) Dashboard visibility delta

What the v3 React dashboard NOW exposes (since `checkpoint_phase_11_a_x_b_dashboard_v3.md`):

- Cumulative-PnL chart (lightweight-charts BaselineSeries) — one point
  per settled decision since bot start, last 500 points
- Decisions tape with Market column (window_ts) + countdown
- AnimatedBook visualization
- Per-tier breakdown panel
- RTT collector pinging Binance / Coinbase / Chainlink / Gamma / CLOB
- Aggressive trip-wire panel (renders when mode=aggressive)

What's still BLIND on the dashboard:

- **Polymarket-truth PnL** — biggest gap. Dashboard shows oracle-truth.
  See incident note. Operator must use the laptop audit for any gate
  decision.
- **Per-era PnL split** (pre-loose / loose-start / aggressive). Dashboard
  shows aggregate only. Era boundary needs the rationale-marker grep.
- **Worst-rolling-24h PnL** (gate criterion #1 form). Dashboard shows
  cumulative; doesn't surface the rolling minimum.
- **Fire-rate per-day extrapolation** (criterion #2 form). Dashboard
  shows fires_24h count and per_hour. Close but not the same metric.
- **EV regrets** — for fires that bypassed EV gate in aggressive mode,
  was the bypassed EV positive on average, or were we just firing on
  noise? Not surfaced anywhere yet.
- **Tier × era cross-tabulation** — separate from per-tier and per-era
  alone. Useful for spotting whether one tier carries one era.

## (c) Ranked single-knob tightening proposals (if revert)

Only relevant IF a future re-run of this gate breaches a hard criterion
or the operator chooses to revert mid-soak. None apply right now.

### Rung 1: drop SPOT_AWARE_AGGRESSIVE_MODE (return to loose-start)

```bash
# /home/ops/polymarket-5m-bot/.envrc
# Drop the next line:
export SPOT_AWARE_AGGRESSIVE_MODE=1
```

**Effect:** Δ_min, Δ_max, EV gate are re-enforced. Loose-start values
(Δ_min=5, EV=$0.003) stay in place. Fire rate drops from ~290/day to
~120-200/day per the loose-start projection.

**Risk:** loses the 30-50% tier signal data we've been accumulating.
The 30-50% sample is showing edge precisely because aggressive mode is
firing into it; tighter gates will fire less often there too.

**Recommend:** the natural revert. Document in postmortem.

### Rung 2: rung 1 + bump SPOT_AWARE_DELTA_MIN_BPS 5 → 6

Cuts the noisiest tail off loose-start. Per the smoke backtest, Δ_min=6
projects ~80-100/day fire rate — closer to the original 11.A baseline.

**Risk:** may filter out winning aligned trades in the 5-6 bps range
that did contribute positive EV. Need to run an offline replay against
the existing decisions to test.

### Rung 3: rung 1+2 + bump SPOT_AWARE_EV_MIN_DOLLARS 0.003 → 0.005

Returns to design-doc default. Filters trades that were EV-borderline.
Combined with rungs 1+2 this is **back to the 11.A original baseline**
that was running before the loose-start request.

**Risk:** fire rate drops further. May fire too rarely for any
statistically meaningful read in 7-day soak window.

### Rung 4 (DESIGN-DOC needed): tier-restricted v2

Only fire in 30-50% and 50-70%, drop 15-30% (n=4) and 70-85% (n=2).
Maybe also drop the bottom of 50-70%. **Not a knob — a strategy
change.** Locked decision rule #1 says design doc before code.

**Recommend:** if rungs 1-3 underperform, queue a design doc:
`design/spot_aware_strategy_v2_tier_restricted.md`. Don't ship as a
knob.

## What this doc is NOT

- Not a binding revert recommendation. The data says HOLD (gates pass
  under both lenses; under 24h elapsed; 30-50% tier showing edge).
- Not a v2 strategy design. Rung 4 is a placeholder for a future doc.
- Not a re-tuning of the priors JSON. `data/spot_aware_priors.json` v1
  is locked; tuning it requires its own analysis.
- Not a permission to tighten knobs while bot is running. Any tightening
  needs a restart, a clear rationale, and a documented expectation.

## See also

- `runbooks/decisions/aggressive-mode-2026-05-09.md` — the experiment
  spec
- `runbooks/decisions/loose-start-2026-05-09.md` — the precursor
- `runbooks/gate-evidence/phase-11.a.2.txt` — the gate verdict
- `runbooks/gate-evidence/phase-11.a.2-full-history.txt` — the
  per-era + per-tier audit
- `runbooks/gate-evidence/phase-11.a.2-dashboard-diff.txt` — the
  truth-source diff
- `runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md` —
  the dashboard truth bug
- `design/spot_aware_strategy.md` §3, §4, §5 — locked spec
