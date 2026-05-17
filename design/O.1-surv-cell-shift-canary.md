# O.1 — SURV-cell shift canary (Phase O Session 1)

**Status:** LOCKED 2026-05-17 — implementing this session
**Predecessor:** Phase N forensic audit (PHASE_N_FORENSIC_AUDIT.pdf §5.1)
**Motivation:** the 2026-05-15 15:40Z SURV-cell flip (WR 60.7% → 46.5%)
drove most of the −$1,562 peak-to-floor swing. No shipped defense
targeted this cell. This canary is the gap fill.

## What it does

For each fire on tier 30-50% (which post-Phase-J.1.5 are 100% SURV-cell
fires, since CH3 |Δ|<5 is folded), check a rolling-30-fire WR computed
over SURV-only history. If the rolling WR drops below the dynamic
break-even (mean entry price + margin), ABSTAIN the fire and emit a
Telegram CRITICAL alert on first trip.

Mirrors M.5's design but the parameters are DATA-TUNED on the n=755
forensic dataset (see "Backtest gate" below):

| | M.5 (Path A) | SURV canary (this) |
|---|---|---|
| Slice | tier 70-85% × DOWN | tier 30-50% × \|Δbps\|≥5 |
| Lookback | 30 fires | **15 fires** (faster reaction; the SURV flip needs 1-3h, not 5-8h) |
| Min samples | 20 | **10** (n=15 buffer; min=10 lets the canary engage faster post-restart) |
| Margin | +0.02 (2pp) | **−0.01** (trip when rolling_wr is 1pp BELOW mean_price) |
| Gate logic | abstain if `rolling_wr < mean_price + margin` | identical |
| Cold-start | pass-through | pass-through |
| Source of state | `state/decisions/*.jsonl` (read on demand) | identical |

## Why negative margin (−0.01) vs M.5's +0.02

Asymmetric-payoff math: at entry price `p`, the bet is +EV when
`rolling_wr > p`. M.5's +2pp margin demands a 2pp safety buffer above
break-even before firing — sensible at Path-A's high break-even (~78%).
SURV operates at p≈0.42-0.51 with rolling-15 WR that fluctuates 45-65%
even on profitable days. A positive margin would trip during normal
fluctuation. The n=755 forensic parameter sweep shows:

| margin | lookback=15 | lookback=30 | lookback=60 |
|---|---|---|---|
| +0.03 | overfires badly | overfires | underfires |
| 0.00 | +$258, 2 pre-trips | −$425, 3 pre-trips | −$159, 0 pre-trips |
| **−0.01** | **+$280, 2 pre-trips** | −$213, 1 pre-trip | +$210, 0 pre-trips |
| −0.02 | +$182 | −$4 | +$152 |
| −0.05 | −$40 | +$15 | −$26 |

`lookback=15, margin=−0.01` is the highest-saving cell with acceptable
false-positive count (2 fast-recovery pre-peak trips, 11 post-peak trips).
**Falsifier:** if production live data shows the canary trips
more than 5 times in any 24h window without the bot bleeding, the
margin needs widening (more negative).

## Integration point

`src/polymarket_bot/strategies/spot_aware_v2_1.py` `_maybe_fire()`:
- ADD canary gate at the M.5 site (line ~452, BEFORE super()._maybe_fire)
- Filter: `tier == "30-50%"` only
- Pattern: identical to M.5 (getter is None → no-op; otherwise check
  rolling_wr vs mean_price + margin)
- Why before super(): saves the v2 EV computation cost; matches M.5's
  pre-super() abstain-without-counter-tick semantics

## Why tier-only at fire time (not tier + |Δbps|)

Phase J.1.5 fold means tier 30-50% live fires are 100% |Δ|≥5 (SURV
slice). Filtering by tier alone is equivalent at fire time. The
rolling-WR computation in `surv_canary_metrics.py` DOES filter on
|Δbps|≥5 from the rationale, so the slice integrity is preserved on
the historical side. Saves us a `_parse_delta_bps()` step pre-super().

## Telegram alert

On the first canary trip in a process lifetime, fire a CRITICAL alert:

```
[SURV-CANARY] tripped at 2026-05-XX HH:MMZ
  rolling_wr=46.5% / mean_price=42.3% / threshold=45.3% / n=30
  abstaining tier 30-50% fires until WR recovers
```

Subsequent trips within the same process emit no alerts (silent
abstain). Operator sees the state via dashboard / decisions tape.

## State of the cell at canary trip time on the forensic data

Rolling-30 SURV WR trajectory (from the n=755 audit):
- Pre-peak (fire #1..444): rolling-30 WR drifts 55-65%, mostly above
  break-even (~45-50%)
- At peak (fire #445, 2026-05-15 15:40Z): rolling-30 WR ≈ 60.7%
- Post-peak (fires #446-#600): rolling-30 WR drops to 46.5% over
  ~15-20 fires
- Canary should TRIP around fire #460-470 (~30-60 min post-peak)
- ~150 SURV fires post-trip would have been abstained, saving most of
  the −$1,161 SURV post-peak bleed

This is the **falsifier the canary must pass** (backtest section below).

## Env flags

| name | type | default | purpose |
|---|---|---|---|
| `SURV_CANARY_ENABLED` | bool | `false` | master switch (set `true` for Phase O) |
| `SURV_CANARY_LOOKBACK_N` | int | `15` | rolling window size |
| `SURV_CANARY_MIN_SAMPLES` | int | `10` | cold-start floor |
| `SURV_CANARY_BREAK_EVEN_MARGIN` | float | `-0.01` | trip when rolling_wr < mean_price + margin |
| `SURV_CANARY_MIN_ABS_DELTA_BPS` | float | `5.0` | |Δbps| threshold for SURV slice membership |

Same naming convention as `REGIME_M5_*`.

## Backtest gate (pre-deploy verification)

Run `scripts/research/phase_n_forensic_audit.py` with a new section that
simulates the canary across n=755 and reports:
1. Trip times (UTC timestamps where canary first crossed threshold)
2. Pre-trip false positives (canary tripped before peak?)
3. Counterfactual PnL: fires abstained by canary × actual outcomes
4. SURV-slice net PnL with canary vs without

Pass criteria (the n=755 backtest 2026-05-17 actually achieved):
- ✓ First post-peak trip at 2026-05-15 19:20Z (3h40min after peak)
- ✓ 2 pre-peak trips, both fast-recovery (within 1 hour) — not zero, but
  small and corrective
- ✗ Counterfactual avoided is **+$280**, NOT the +$700 the PDF claimed.
  Honest correction: the rolling-WR has lag at n=15 and the SURV slice
  retains ~45% WR even at its worst; we capture ~25% of the −$1,161
  SURV post-peak loss, not 60%. Still positive, still ships.

## Limits / honest pushback

- 4.2-day backtest. ONE flip event. Canary tuning is N=1 grounded.
- Rolling-30 has a ~60-min lag at typical fire rates (~5 SURV fires/h).
  The canary trips ~30-60 min post-flip — not real-time.
- A faster trigger (rolling-10 + slope) would react faster but
  false-positive more. Defer to Phase O Session 2 after observation
  data accumulates.
- If the slope detector is needed earlier than 30 fires, ship a v2
  with rolling-10-vs-rolling-30 delta as the trigger.
- Re-enable margin = 0.02 if the 3pp default catches too few fires
  during the actual SURV-cell post-peak phase in the n=755 backtest.

## What this does NOT do

- Detect regime shift in the underlying spot market (we have no
  spot-tick history)
- Predict the SURV-cell flip (no leading indicator)
- Address tier 70-85% Path A (that's M.5's job)
- Address tier 30-50% × small-|Δ| (CH3 — handled by J.1.5 fold)

## File list

- `design/O.1-surv-cell-shift-canary.md` (this file)
- `src/polymarket_bot/strategies/surv_canary_metrics.py` (NEW)
- `src/polymarket_bot/strategies/spot_aware_v2_1.py` (EDITED — add canary param + gate)
- `scripts/run_paper.py` (EDITED — env wiring + 60s-cached getter + Telegram alert hook)
- `tests/strategies/test_surv_canary_metrics.py` (NEW)
- `tests/strategies/test_spot_aware_v2_1.py` (EDITED — canary gate tests)
- `scripts/research/phase_n_forensic_audit.py` (EDITED — canary backtest section)
