# Aggressive-mode test for SpotAwareStrategy (2026-05-09)

**Decision:** ship a deliberately-loose `aggressive_mode` flag on
`SpotAwareStrategy` and run it in paper-soak as a 24-48h experiment to
get a real fire-rate-vs-PnL curve. Operator request, 2026-05-09 UTC,
after observing 1 fire in ~30min of soak under loose-start mode.

This is **`Phase 11.A.2`** — an experiment that follows the
loose-start (`runbooks/decisions/loose-start-2026-05-09.md`), runs in
parallel with the original soak data, and ends with a clear gate
decision (revert or promote).

## What aggressive mode does

When `aggressive_mode=True` is set on the strategy:

| Gate | Production | Loose-start | **Aggressive** |
|---|---|---|---|
| Δ_min check (lower bound) | ≥ 8 bps | ≥ 5 bps | **bypassed** |
| Δ_max check (50 bps ceiling) | enforced | enforced | **bypassed** |
| Δ ≠ 0 (alignment defined) | enforced | enforced | enforced |
| Aligned-side-only | enforced | enforced | enforced |
| Tier ∈ [0.15, 0.85] | enforced | enforced | **enforced** |
| Tier 85-100% rejected | yes | yes | **yes** |
| Prior lookup hit required | required | required | falls back to `p_win=0.54` |
| EV gate (`p_win - (ask+fees) > min`) | enforced | enforced | **bypassed** |
| Fire-once-per-window | enforced | enforced | enforced |

**Three things that DON'T change**, even in aggressive mode:

1. **Tier 85-100% stays REJECTED.** This is the documented Slow-Minute
   money-loser (`runbooks/research/scout-final-comparison-2026-05-08.md`,
   -$3,964 / 7d at 96.6% WR). It's not a tuning knob; it's a guardrail.
2. **Tier <15% stays SKIPPED.** Sample too small to trust per design doc
   §13.
3. **Fire-once-per-window invariant holds.** No multi-fire-per-window
   capital-management surprises.

## Fallback `p_win = 0.54`

Sourced from the 30-day Bonereaper spot-vs-book join, "flat" alignment
bucket (|Δ|<5bps): WR 53.9%, $+0.96/trade across 87,964 trades
(`runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md`). Rounded
DOWN to 0.54 for honesty — we don't get full Bonereaper edge at our
$5 stake size, only the bit that survives.

Used **only** for aligned-direction trades that landed outside the
priors table. Contrarian and pure-flat (Δ=0) trades never fire.

## Honest forecast

```
Win-rate scenario     Fires/day    Per-trade gross    NET PnL/day
-----------------     ---------    ---------------    -----------
Bonereaper-class 51.7%   ~280       +$0.05            +$1 to +$5
Coin-flip 50%            ~280       $0                -$7  (just fees)
Slightly bad 48%         ~280       -$0.10            -$36 (bankroll wipe ~33d)
```

The math at $5 stake × 280 trades/day × 0.5% fees = **$7/day in fees
alone**. Net PnL is win-rate minus 0.5% per trade.

## Mechanism

Implemented as env var read by `scripts/run_paper.py`:

```bash
# /home/ops/polymarket-5m-bot/.envrc on the VPS:
export SPOT_AWARE_AGGRESSIVE_MODE=1
```

Plus the existing loose-start knobs stay set:

```bash
export SPOT_AWARE_DELTA_MIN_BPS=5
export SPOT_AWARE_EV_MIN_DOLLARS=0.003
```

(In aggressive mode these become near-redundant since both are bypassed,
but leaving them set means a one-line revert path.)

To disable: `unset SPOT_AWARE_AGGRESSIVE_MODE` in `.envrc`, restart
`bot-staging.service`. No code change.

## Hard exit criteria

**This experiment AUTO-ENDS on any of these.** The operator OR the
session-handoff Claude is responsible for noticing and acting:

1. **Cumulative PnL drops below -$50 in any rolling 24h** → revert
   immediately to loose-start (drop `SPOT_AWARE_AGGRESSIVE_MODE`).
   Postmortem at `runbooks/postmortems/aggressive-mode-bust-<date>.md`.
2. **Fire rate exceeds 350/day** → strategy is firing on near-every
   window plus duplicates from a bug; halt and investigate.
3. **48 hours elapsed** → automatic gate review regardless of PnL.
   Either promote (loose values become new baseline) or revert.
4. **Net WR drops below 47% in 100+ settled trades** → mathematically
   guaranteed losing; revert.
5. **Operator says "halt"** → halt via `/halt` Telegram or restart-with-
   override-removed.

## Telemetry split

Decisions log a `mode=aggressive` marker in the rationale. The 48h
review pulls per-mode stats:

```python
# Rough one-liner the gate audit will run:
groupby_mode_stats = decisions.group_by(
    lambda d: "aggressive" if "mode=aggressive" in d.rationale else "spot_aware"
)
```

## What this is NOT

- **Not a permanent strategy change.** Aggressive mode is the
  experiment, not the new baseline. The 48h review either promotes or
  reverts.
- **Not removing tier discipline.** 85-100% stays rejected. <15% stays
  skipped.
- **Not multi-fire-per-window.** Still one fire per 5-min window.
- **Not multi-market.** BTC 5m only. Multi-market (Phase 11.D in design
  doc §11) remains its own future scope.
- **Not lowering the priors table.** `data/spot_aware_priors.json` v1
  unchanged.

## What we'll learn

After 24-48h of aggressive-mode data alongside the existing loose-start
sample:

- **Real fire rate** at this configuration (predicted ~250-280/day).
- **Per-trade NET** with fees applied — does the fallback p_win = 0.54
  actually hold up live, or is it 0.50, or 0.55?
- **Fill rate** at higher volume — does the queue-position math change
  when we're firing every window?
- **Tier distribution of fires** — are we mostly in 0.30-0.70 (sweet
  spot) or pushing 0.70-0.85?
- Comparison vs the smoke-backtest projections.

## References

- `design/spot_aware_strategy.md` §3 (Δ_min space), §5 (EV floor),
  §"What this doc does NOT do" (tier 85-100% off-limits).
- `runbooks/decisions/loose-start-2026-05-09.md` (precursor, still in
  effect).
- `runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md` (source
  of the 0.54 fallback).
- `runbooks/research/scout-final-comparison-2026-05-08.md` (why 85-100%
  is non-negotiable).
