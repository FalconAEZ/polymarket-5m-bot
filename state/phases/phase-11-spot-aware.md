---
title: Phase 11 — SpotAwareStrategy paper-soak (post phase-5-pass)
status: 11.A.2 active — aggressive_mode soak running on bot-staging since 2026-05-08 22:26:15 UTC; v2 early-read at 18.1h (2026-05-09 16:30 UTC) all gates OK / verdict DEFER (under 24h pickup); 48h committed gate review 2026-05-10 22:26:15 UTC
tags: [phase, spot-aware, paper-soak, aggressive-mode, in-progress]
---

# Phase 11 — SpotAwareStrategy paper-soak

> Following phase-5-pass (2026-05-08), the project's next gate is whether
> the spot-Δ alignment + tier discipline strategy makes money in 7 days
> of single-market paper trading. This is the strategy we designed in
> `design/spot_aware_strategy.md` and the experiment that began at
> 2026-05-08 21:11:27 UTC.

## Why this phase exists

Two converging pressures from the 2026-05-08 session:

1. **Replay calibration showed `DeterministicStrategy` fires zero** at any
   threshold from 0.3pp to 0.6pp on real 5-min BTC tick data. The signal
   itself is too quiet for our window size — we needed a different signal.
2. **The 30-day Bonereaper analysis (306,966 trades) confirmed a +30.9pp
   aligned-vs-contrarian gap on spot-Δ** — a real, scale-stable edge that
   was independent of any single wallet's behavior.

`SpotAwareStrategy` extracts the spot-Δ trigger and adds explicit
price-tier discipline (the lesson from the leaderboard scout —
"high WR without tier discipline = Slow-Minute -$3,964/7d").

## Sub-phases

| # | Phase | Status | Evidence |
|---|---|---|---|
| 11.A | spot_aware paper-soak baseline (Δ_min=8, EV=0.5¢) | ⏸ deferred | superseded by 11.A.1 |
| 11.A.1 | loose-start (Δ_min=5, EV=0.3¢) | ⏸ subsumed by 11.A.2 | `runbooks/decisions/loose-start-2026-05-09.md` |
| **11.A.2** | aggressive-mode test (Δ_min/Δ_max/EV all bypassed; tier discipline intact) | ⏳ **active 2026-05-08 22:26:15 UTC →** | `runbooks/decisions/aggressive-mode-2026-05-09.md` |
| 11.B | post-aggressive baseline (real go/no-go) | ⏸ pending 11.A.2 review | — |
| 11.C+ | sizing scale, multi-market, etc. | ⏸ scope per design doc §11 | — |

## Active experiment: 11.A.2 aggressive-mode test

### Configuration

```bash
# In VPS .envrc (bot-staging.service reads this):
export STRATEGY=spot_aware
export SPOT_AWARE_DELTA_MIN_BPS=5
export SPOT_AWARE_EV_MIN_DOLLARS=0.003
export SPOT_AWARE_AGGRESSIVE_MODE=1
# Default: SPOT_AWARE_LIMIT_BUFFER_USD=0.02
```

### What aggressive mode bypasses + what it can't

| Gate | Production default | Aggressive |
|---|---|---|
| Δ_min check | ≥ 8 bps | **bypassed** |
| Δ_max check (50bps) | enforced | **bypassed** |
| Δ ≠ 0 alignment | enforced | **enforced** (Δ=0 undefined alignment) |
| Aligned-side-only | enforced | **enforced** (contrarian WR is 36.4%) |
| Tier ∈ [0.15, 0.85] | enforced | **enforced** (Slow-Minute trap guardrail) |
| Tier 85-100% rejected | yes | **YES** — non-negotiable |
| Tier <15% skipped | yes | **YES** — sample too small per design doc §13 |
| Prior lookup hit required | required | falls back to `p_win=0.54` (Bonereaper 30d flat-bucket WR) |
| EV gate | enforced | **bypassed** (the discipline knob whose absence makes this an "every window test") |
| Fire-once-per-window | enforced | **enforced** (capital-management invariant) |

### Hard exit criteria (per `runbooks/decisions/aggressive-mode-2026-05-09.md`)

The experiment auto-ends on ANY of:
1. Cumulative PnL drops below **-$50** in any rolling 24h → revert
2. Fire rate exceeds **350/day** → bug suspected, halt
3. **48 hours elapsed** → automatic gate review (promote or revert)
4. Net WR drops below **47% in 100+ settled trades** → revert
5. Operator says halt → halt

## Live data snapshot (18.1h into 11.A.2 — v2 early-read 2026-05-09 16:30 UTC)

**Polymarket-truth (laptop audit after `sync_staging.sh`):**

```
fires:           236 (aggressive only) / 238 (full history)
filled:          225 (95.3%)
settled:         230 (97.5%)
won:             112
lost:            113
WR:              49.8% (n=225 filled+settled)
PnL:            +$11.00
bankroll:       $1,011.00 (paper)
fire rate:       292/day (under 350 cap)
worst rolling 24h PnL: +$3.83 (over -$50 floor)

Per-tier (Polymarket-truth):
  15-30%:   4 fires, 50.0% WR, $+37.98  ← n=4 too small
  30-50%:  48 fires, n=45 settled-fills, 53.3% WR, $+54.18  ← n crossed 40, edge real
  50-70%: 182 fires, n=174 settled-fills, 48.9% WR, $-78.20  ← biggest sample, the drag
  70-85%:   2 fires, 50.0% WR, $-2.97  ← n=2 too small
```

**Dashboard view (VPS `/api/state`, oracle-truth — KNOWN WRONG, see incident):**

```
bankroll.delta_usd: -$43.07
WR (oracle-truth):  47.1%
```

The dashboard reads oracle-truth (Chainlink-local), not Polymarket-truth.
$54 PnL gap. See `runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md`
and the v2 dashboard-vs-truth diff. **For gate decisions, use the laptop
audit only.**

## Live data snapshot (3.8h into 11.A.2 — historical, launch session)

```
fires:           52 (aggressive only)
filled:          43 (83%)
settled:         48
won:             23 (47.9% net WR)
PnL:            +$39.51
bankroll:       $1,039.51

Per-tier:
  30-50%:  10 fires, 8/8 settled-fills won, $+47.03  ← n=10, looks strong but inconclusive
  50-70%:  35 fires, 41% WR, $-37.24             ← biggest sample, underperforms reference
  15-30%:   2 fires, $+23.11                     ← n=2 trivial
  70-85%:   2 fires, $-2.97                      ← n=2 trivial
```

## Lessons from the 11.A.2 launch session (2026-05-09)

Captured in `runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md`
and the full session note. Five bugs caught + fixed mid-session:

1. **Local Chainlink AnswerUpdated samples disagree with Polymarket** on
   ~33% of windows. Local feed is push-based with 1-2 min heartbeat;
   Polymarket reads Chainlink Streams (pull, sub-second) at exact
   T/T+300. Fix: post-hoc Gamma re-resolution (`scripts/resolve_decisions.py`).
2. **FillSimulator phantom $449 trade** — `min(limit, effective_ask)` was
   filling pending orders at much-lower-than-limit prices when ask
   crashed during TTL. Fix: maker/taker distinction in simulator;
   maker fills at limit price.
3. **Dashboard mid-sync flicker** — sync_staging.sh wrote into the
   dashboard's read path, causing alternating corrected/uncorrected
   display. Fix: two-stage sync (decisions.raw/ + decisions/).
4. **Dashboard CPU saturation** — sync_staging processes stacked faster
   than they completed. Fix: 30s throttle + sentinel-touch race fix.
5. **Limit-at-ask never fills** — simulator's impact gate rejected fills
   where price_limit was exactly best_ask. Fix: 2¢ limit buffer + 1¢
   simulator impact cap.

## Path to 11.A.2 close (next session)

1. **Sync staging.** `bash runbooks/scripts/sync_staging.sh` pulls all
   24h+ of decisions data with corrected resolutions.
2. **Run gate audit** — script TBD: `runbooks/gates/spot-aware-paper.sh`,
   parallel structure to `phase-5.sh`. Reports each of the 5 hard exit
   criteria + whether each is OK / BREACHED / GATE-DUE.
3. **Decide:**
   - All criteria OK at 48h → **promote** (lock loose values as new
     baseline, retire aggressive flag); tag `spot-aware-paper-pass`.
   - Any criterion breached → **revert** (drop SPOT_AWARE_AGGRESSIVE_MODE
     in `.envrc`, restart); postmortem at
     `runbooks/postmortems/aggressive-mode-bust-<date>.md`.
   - Mixed signal (e.g., overall PnL bad but one tier good) → **conditional
     revert** + design follow-up; tier-restricted strategy in 11.B.
4. **Vault closeout + memory checkpoint.**
5. **Push.**

## Hard limits

- **Cumulative Anthropic spend:** still $0.405 (Phase 3). Phase 11
  adds $0 (deterministic strategy + simulator code).
- **Bankroll:** $1,000 paper (locked decision #10). Trip wire #1 fires
  at -$150 cumulative drawdown (15% per gate A6).
- **Funder key NEVER goes to the VPS.** Locked decision #11.
- **No new locked decisions added this phase.** All knob adjustments
  are exploratory; revert to design-doc defaults if 11.A.2 fails.

## See also

- `design/spot_aware_strategy.md` + `pdfs/SPOT_AWARE_STRATEGY.pdf` —
  locked spec
- `runbooks/decisions/loose-start-2026-05-09.md` — first relax (subsumed)
- `runbooks/decisions/aggressive-mode-2026-05-09.md` — current experiment
- `runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md` — Chainlink
  vs Polymarket bug
- `runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md` — prior
  table source
- `state/phases/phase-5-vps.md` — predecessor phase (closed)
- `state/sessions/2026-05-09-spot-aware-aggressive-launch.md` — launch
  session full roll-up
