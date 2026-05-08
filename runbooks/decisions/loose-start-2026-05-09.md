# Loose-start exploratory paper-soak (2026-05-09)

**Decision:** for the first phase of the SpotAwareStrategy paper-soak, deploy
with relaxed trigger parameters: **Δ_min = 5 bps** (vs design-doc default 8)
and **EV floor = $0.003 / share** (vs design-doc default $0.005). Tighten
back as data accumulates.

## Why

Operator request, 2026-05-08 ~20:35 UTC, after observing 1 fire in the
first 40 minutes of live soak (a sample-size-1 reading). Quote: *"we can
set everything a bit lose for the start then start tightening stuff down
as more data accumulates."*

Honest framing: we were not under-firing per the smoke projection (~80/day
at Δ_min=8 → ~36/day pace at the time of observation, n=1 has huge
variance), but the operator wants a fatter sample early to read fill rate
and per-tier WR sooner. Both knobs lowered are inside the design doc's
declared candidate space:

- §3 of `design/spot_aware_strategy.md` says "Δ_min candidate space: [5,
  10] bps" — 5 is the lower endpoint, not a violation.
- §5 says EV floor is "intentional friction" at 0.5¢; lowering to 0.3¢
  preserves positive-EV-required while accepting thinner edges.
- §4 tier filter is **NOT changed** — 85-100% stays REJECTED. This is
  not a "loose" knob; it's the documented Slow-Minute money-losing trap
  (`runbooks/research/scout-final-comparison-2026-05-08.md`,
  -$3,964 / 7 days at 96.6% WR). Cannot be opened.

## Mechanism

Implemented as env vars read by `scripts/run_paper.py::_build_strategy`:

```bash
# /home/ops/polymarket-5m-bot/.envrc on the VPS:
export SPOT_AWARE_DELTA_MIN_BPS=5
export SPOT_AWARE_EV_MIN_DOLLARS=0.003
```

Unset → strategy uses its own design-doc defaults. To tighten back:
remove the env vars (or change values) and `sudo systemctl restart
bot-staging.service`. No code redeploy required.

## Expected effect on fire rate

Smoke backtest at Δ_min=8 / EV=0.5¢ produced 89 fires across 316 windows
(~28% / ~80/day). Lowering Δ_min to 5 admits the 5-7 bps tail that the
smoke discarded. The 30-day Bonereaper data shows the 5-10 bps bucket as
a single homogeneous unit (per-tier WR is computed across the whole
bucket); we already have priors covering it. Lowering EV floor by $0.002
is marginal; lifts a small additional tail of borderline trades.

Best estimate: **fire rate ~1.5-2.5x previous projection**, i.e.,
**~120-200/day**. That puts us near the upper end of gate A1's 30-200/day
band — by design, "loose start" rides the upper band for a faster sample.

## Tightening plan (the "tighten as data accumulates" half)

Re-evaluate at three checkpoints:

| Checkpoint | Decision rule |
|---|---|
| **Day 2 (~48h soak)** | If fire rate > 200/day → bump Δ_min to 6 immediately (gate A1 violation). If WR < 50% → tighten everything back to design-doc defaults. |
| **Day 4** | First per-bucket WR comparison vs priors. Adjust priors JSON if any bucket drifts >5pp from observed WR with ≥50 trades. |
| **Day 7 (gate)** | Run `runbooks/gates/spot-aware-paper.sh` (to be written). If gate passes, lock the loose values as the new baseline. If fails, postmortem + retry at design-doc defaults. |

## What this is NOT

- Not un-archiving locked decision #19 (Bonereaper cloning).
- Not opening tier 85-100% (scout-validated money-loser).
- Not removing fire-once-per-window (would compromise capital management).
- Not changing the Δ_max ceiling of 50 bps.
- Not changing the priors JSON (`data/spot_aware_priors.json` v1) — those
  numbers come from 30d Bonereaper analysis and don't move on operator
  instinct.

## References

- `design/spot_aware_strategy.md` §3, §5 (parameter spaces).
- `runbooks/research/scout-final-comparison-2026-05-08.md` (why tier is
  off-limits).
- `runbooks/gate-evidence/spot-aware-smoke-backtest-2026-05-09.txt`
  (baseline projection).
