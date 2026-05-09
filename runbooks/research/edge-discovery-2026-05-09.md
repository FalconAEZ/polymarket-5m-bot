# Edge-discovery deep-dive — Phase 11.A.2 mid-soak (2026-05-09)

**Generated:** 2026-05-09 18:01 UTC, 21.4h after aggressive-mode launch.
**Data:** 256 fires / 250 settled (Polymarket-truth resolved via
`runbooks/scripts/sync_staging.sh`).
**Script:** `runbooks/scripts/edge_discovery_audit.py`
**Raw output:** `runbooks/research/edge-discovery-2026-05-09-output.txt`
**Operator ask:** "what was our highs and lows ... I'm pretty sure we're
missing something here! a real edge that we already have but didn't
fully bring it to life."

## TL;DR — verdict

**The operator is right.** The strategy has a real edge that aggressive
mode is washing out by firing too much in the wrong tier.

- Bot peaked at **+$133.88** at 2026-05-09 05:30 UTC (~7h after launch).
- It's currently at **-$0.80** — a **-$134.68 drawdown from peak** caused
  by trading the 50-70% tier into the ground.
- **If we'd never fired in the 50-70% tier**, current PnL would be
  **+$75.93** (a $76 swing on the same data).
- The 30-50% tier is a quiet performer: **+$40.92 / +$0.79 per trade
  / 50% WR / n=54** — real edge, statistically meaningful (n>40 per
  the launch-session threshold).

**Recommendation:** revert aggressive mode at the 24h or 48h gate
(criteria still pass numerically, but the data shows we're trading
unprofitable size). Author a design doc for **`spot_aware_v2_tier_restricted`**
that drops the 50-70% tier and the EV-bypass behavior.

## 1. Highs and lows since bot start

| Metric | Value | When |
|---|---|---|
| **PEAK cumulative PnL** | **+$133.88** | 2026-05-09 05:30 UTC |
| **TROUGH cumulative PnL** | -$14.91 | 2026-05-09 16:55 UTC |
| Current cumulative | -$0.80 | now |
| Drawdown from peak | **-$134.68** | over the next 11.5h |
| Best single trade | +$28.11 | UP / tier 15-30% / Δ=+1.9bps |
| Worst single trade | -$5.00 | UP / tier 50-70% / Δ=+0.0bps |
| Best hour | +$42.21 | 2026-05-09 03:00 UTC (75% WR, n=12) |
| Worst hour | -$39.78 | 2026-05-09 08:00 UTC (17% WR, n=12) |
| Best win streak | 7 | — |
| Worst loss streak | 7 | — |

**Per-day PnL:**
- 2026-05-08 (pre + launch evening): **+$9.48** on 39 fires
- 2026-05-09 (full day so far): **-$10.28** on 217 fires

The bot was a winner the first 7 hours and has been giving it back ever
since. That's not coin-flip noise — that's a real signal that something
about the post-peak trades is structurally different from the pre-peak.

## 2. Tier breakdown — the headline finding

| Tier | Fires | Filled | WR | PnL | per-trade |
|---|---|---|---|---|---|
| 15-30% | 4 | 4 | 50.0% | **+$37.98** | +$9.50 |
| **30-50%** | **54** | **52** | **50.0%** | **+$40.92** | **+$0.787** |
| **50-70%** | **195** | **185** | **49.2%** | **-$76.73** | **-$0.415** |
| 70-85% | 3 | 2 | 50.0% | -$2.97 | -$1.49 |

**The 50-70% tier holds 76% of all fires (195/256) but loses money on a
per-trade basis** even at near-50% WR — because winning trades in this
tier pay less than losing trades cost (the price-tier asymmetry).

The 30-50% tier with the same 50% WR makes +$0.79/trade because winners
pay more there. **It's the same WR but the payoff structure is
fundamentally different across tiers.**

## 3. |Δ_bps| × tier cross-tab — where the edge concentrates

```
tier ↓  Δ→  0-2 bps           2-5 bps         5-10 bps
15-30%      n=4  WR=50%  +$37.98     —              —
30-50%      n=47 WR=53%  +$55.05     n=5  WR=20% -$14.14    —
50-70%      n=182 WR=49% -$80.44     n=3  WR=67%  +$3.70    —
70-85%      n=1  WR=100% +$2.03      n=1  WR=0%   -$5.00    —
```

**Critical observation:** 244 of 256 fires (95%) are in the |Δ|<2 bps
bucket. Aggressive mode bypasses the Δ_min check, so the bot is firing
on **noise-level deltas** — exactly what we suspected.

But the |Δ|<2 bucket isn't catastrophic in 30-50% (+$55 on n=47, 53%
WR). It's catastrophic in 50-70% (-$80 on n=182). **The problem isn't
the small Δ — it's the small Δ × wrong tier combination.**

## 4. EV bucket paradox — the priors fallback is misleading

| EV bucket | n | filled | WR | PnL | per-trade |
|---|---|---|---|---|---|
| EV negative | 114 | 107 | **56.1%** | **+$1.40** | +$0.013 |
| EV [0, 0.02) | 37 | 36 | 41.7% | -$33.79 | -$0.94 |
| **EV [0.02, 0.05)** | **57** | **55** | **38.2%** | **-$60.06** | **-$1.09** |
| EV [0.05, 0.10) | 25 | 23 | **65.2%** | +$51.57 | +$2.24 |
| EV ≥ 0.10 | 23 | 22 | 40.9% | +$40.08 | +$1.82 |

**Counterintuitive findings:**
- **EV-negative trades are profitable** (56.1% WR, +$1.40). These are
  trades the bot fires anyway because aggressive mode bypasses the EV
  gate. They're not making money — they're just not losing.
- **The EV [0.02, 0.05) bucket is the WORST PERFORMER** (-$60.06 on
  n=57, 38.2% WR). These are "thin positive EV" trades — exactly what
  the EV gate exists to admit. The EV calc is **systematically
  misclassifying** here.

**Root cause hypothesis:** the fallback `p_win = 0.54` (used when the
priors table doesn't have a match) is producing false-positive EV
signals. The priors table is queried per-tier-per-Δ-bucket; aggressive
mode trades in the |Δ|<5 zone fall outside the table and use 0.54. But
0.54 over-estimates real win-rate in the marginal-positive-EV bucket.

This is the second hidden edge: **the priors table's fallback default
is contaminating EV signals.** A v2 should require a real prior hit
(no fallback) before firing.

## 5. Per-side imbalance — UP wins, DOWN loses

| Side | Fires | Filled | WR | PnL |
|---|---|---|---|---|
| UP | 149 | 144 | 50.7% | **+$39.36** |
| DOWN | 107 | 99 | 47.5% | **-$40.17** |

Real but n is moderate. Could be artifact of BTC trending up during
this window (a one-direction market would favor UP-buyers). **Don't
filter on side until we have multiple-direction days of data.**

## 6. Hour-of-day pattern — strong but n=1 cycle

| Hour (UTC) | Fires | WR | PnL | Pattern |
|---|---|---|---|---|
| 00-03 | 48 | 56-75% | **+$95.83** | Asia hours = gold |
| 04-05 | 24 | 58% | +$12.83 | OK |
| 06-08 | 36 | 17-42% | **-$64.28** | Europe pre-open = trash |
| 09-12 | 48 | 50% | $0.43 | Flat |
| 13-15 | 37 | 36-42% | -$38.77 | Bad |
| 16 | 12 | 25% | -$30.42 | Worst |
| 17 | 12 | 64% | +$14.11 | Good |
| 22-23 | 27 | 33-58% | +$5.65 | Mixed |

**One pass through 24h is statistically thin.** Could be BTC-action
artifact. **Need ≥3 days before claiming a time-of-day pattern.** Filing
as a watch item, not an action item.

## 7. What-if filtered backtests — counterfactual PnL

The killer table. If we'd applied each filter retroactively to the
existing 256 fires, what would PnL look like?

| Filter | Fires | WR | PnL | per-trade | vs baseline |
|---|---|---|---|---|---|
| baseline (no filter) | 256 | 49.4% | -$0.80 | -$0.003 | — |
| `|Δ|≥5` (loose-start floor) | 2 | 0% | $0.00 | $0.000 | (almost no fires admitted) |
| `EV ≥ 0` (positive-EV only) | 142 | 44.1% | -$2.20 | -$0.016 | -$1 (EV gate doesn't help) |
| **tier 30-50 ONLY** | **54** | **50%** | **+$40.92** | **+$0.787** | **+$41.72** |
| tier 30-50 + 50-70 | 249 | 49.4% | -$35.82 | -$0.151 | -$35 (50-70 is the drag) |
| **DROP tier 50-70** | **61** | **50%** | **+$75.93** | **+$1.309** | **+$76.73** |

**The `DROP tier 50-70` filter is the single most powerful action.**
- Goes from -$0.80 to +$75.93 on the same data (a $76 swing)
- Per-trade PnL: -$0.003 → +$1.31 (a 400x improvement)
- Fires drop from 256 → 61 (76% reduction in trade count → 76%
  reduction in fee burn)

The `|Δ|≥5` filters are useless because almost no aggressive-mode
fires had |Δ|≥5 — the bot spent 95% of its fires in the noise zone.

**Combination filters are bad** in our data because adding `|Δ|≥5` to
any tier filter zeros out the sample. The data is simply too
concentrated in |Δ|<2 to test combination filters.

## 8. Fill quality — getting good fills, not the issue

- p10 slippage: -1.90¢ (better than limit)
- p50: -1.00¢ (better)
- p90: -1.00¢ (better)
- Mean: -1.53¢ (better)

**The fill simulator is giving us 1¢ of price improvement on average.**
Real CLOB execution will likely be worse than simulator, but we're not
losing on entry quality in paper. Fill quality is not the problem.

## Edge thesis (operator was right)

**The hidden edge is the 30-50% tier × |Δ|≥0 (any Δ).** It's been
quietly profitable across every audit:
- v2 audit (18.1h): +$54.18 / 53.3% WR / n=45
- 17:11 (post first deploy): +$44.18 / 51.1% WR / n=47
- 17:30 (post pnl_by_day): +$75.74 / 55.1% WR / n=49
- now (18:01): +$40.92 / 50% WR / n=54

That's **actual edge with 50%+ WR across n>50 settled trades** at +$0.79
per trade. Aggressive mode hides this by drowning it in 195 losing
50-70% trades.

The **second edge** is **avoiding the 50-70% tier entirely.** The
asymmetric payoff structure means even at 49% WR you lose money
there. This was the locked decision #6 / Slow-Minute trap research
that we *did* respect (not opening 85-100% tier) but applied
inconsistently (kept 50-70% open for fires).

**A third candidate edge** is the **EV [0.05, 0.10) bucket** (n=25, 65%
WR, +$51.57). Suggests the priors table is reasonably calibrated WHEN
it returns a real value but breaks down with the 0.54 fallback. A v2
should require a real prior hit.

## Recommended next actions (in priority order)

### Action 1 — Author design doc for `spot_aware_v2_tier_restricted`

**Per CLAUDE.md rule #1: design doc before code.** Don't ship as a knob.
The doc should:
- Drop tier 50-70% entirely (justification: -$77 on n=185 in live data)
- Drop the `p_win=0.54` fallback (justification: EV [0.02, 0.05) bucket
  was -$60 on n=55 — fallback over-estimates win rate)
- Keep tier 30-50% as primary (justification: +$41 on n=54, real edge)
- Keep tier 15-30% as opportunistic (justification: +$38 on n=4, big
  payoff per win)
- Re-instate the Δ_min ≥ 8 check (or whatever the priors table actually
  covers) — the |Δ|<2 zone is where most of the noise lives
- File as `design/spot_aware_v2.md` per the design-doc convention

### Action 2 — Revert aggressive mode at the 24h or 48h gate

Even though all 5 hard exit criteria still numerically pass, the data
shows the strategy is structurally losing money on a per-trade basis
in the dominant tier. The "PROMOTE" verdict at 48h would be technically
correct but practically wrong — promoting a strategy whose edge is
hiding under 76% useless trades.

Recommended branch C from the original gate prompt: **CONDITIONAL
REVERT + design follow-up.** Document this in a postmortem at
`runbooks/postmortems/aggressive-mode-bust-2026-05-10.md`.

### Action 3 — Validate the 30-50% tier edge with 7 more days

Before promoting v2, run it for 7 days at the same paper-soak cadence.
n=54 is past the "looks hot but n=10" threshold but still thin enough
that another 100+ trades would tighten the confidence interval.

### Action 4 — Defer time-of-day + side filters

n=1 cycle per hour is too thin. Hour-03 +$42 / hour-08 -$40 could be
real but could equally be artifacts of BTC's specific path during
those hours. **Need ≥3 days before any time-of-day filter design.**

## What this is NOT

- **Not a knob change.** The operator should not just SSH in and
  `unset SPOT_AWARE_AGGRESSIVE_MODE` based on this analysis alone. The
  current bot is passing all 5 hard exit criteria; let it run to the
  48h gate, then revert + write the v2 design doc.
- **Not a time-of-day filter recommendation.** Hour patterns are
  suggestive but n is too small.
- **Not a Δ_min ≥ X recommendation.** The data is too concentrated
  in |Δ|<2 to backtest this filter against live data.
- **Not opening tier 85-100%.** That stays REJECTED per the
  Slow-Minute trap research (locked decision territory).

## Files

- This doc: `runbooks/research/edge-discovery-2026-05-09.md`
- Audit script: `runbooks/scripts/edge_discovery_audit.py`
- Raw output: `runbooks/research/edge-discovery-2026-05-09-output.txt`
- Cross-refs:
  - `design/spot_aware_strategy.md` §3, §4 (locked spec)
  - `runbooks/decisions/aggressive-mode-2026-05-09.md` (the experiment
    being audited)
  - `runbooks/decisions/phase-11.a.2-refinement-plan-2026-05-09.md`
    (rung 4 placeholder for tier-restricted v2 — this audit is the
    evidence backing it)
  - `runbooks/research/scout-final-comparison-2026-05-08.md` (the
    Slow-Minute -$3,964/7d study that locked the 85-100% tier closed —
    same logic now applies to 50-70% tier per this analysis)
