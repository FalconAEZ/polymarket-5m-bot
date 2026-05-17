---
title: Phase 15 — regime gate wired to ensemble (REGIME_GATE_ENABLED + REGIME_GATE_ABSTAIN_REGIMES)
status: Infrastructure DEPLOYED dark 2026-05-10 21:58:44 UTC. Commit `fbcd38a` on `claude/jovial-hermann-7e103f`. VPS bundled-deploy with Phase 14 + dashboard track. Default behavior unchanged (env off + empty abstain set = zero-overhead pass-through). 487 tests green.
tags: [phase, regime-gate, kill-switch, dark-ship, deployed]
---

# Phase 15 — REGIME_GATE_ENABLED + REGIME_GATE_ABSTAIN_REGIMES

> Kill-switched regime-classifier gate that refuses fires when the current spot regime (5m/10m vol-ratio classifier) is in an operator-specified abstain set. Applied BEFORE the LLM ensemble (saves Haiku+Sonnet round-trip on blocked windows). Third executable phase from the [[../sessions/2026-05-11-phase-12-master-plan|Phase 12 master plan]]. Shipped as infrastructure-only after the audit reproduced Phase 14's PnL paradox.

## Why this phase existed

Master plan §4 → Phase 15: the existing `RegimeDetector` (`src/polymarket_bot/strategies/regime_detector.py`) was wired into `SpotAwareStrategyV3` only — NOT into the active `ensemble` strategy. The 2026-05-10 validation evidence (`runbooks/gate-evidence/regime-classifier-validation.txt`) showed trending bucket WR=70.59% vs chop=47.40% (+23.19pp) on a 256-trade research dataset. Wiring the same classifier into `EnsembleWrapper` adds a structural filter at near-zero implementation cost (the math is done).

## What the audit found (the actual story)

`scripts/audit_regime_wr.py` (NEW, committed) on 3 days of VPS data (n=477 fires / 412 settled):

| regime    | n_settled |   WR   | 95% CI       | PnL ($)  | avg/trade | gate-criterion (master plan)        |
|-----------|----------:|-------:|:------------:|---------:|----------:|:------------------------------------|
| trending  |        27 |  59.3% | [40.7, 75.5] |  +329.41 |   +$12.20 |                                     |
| mixed     |       136 |  50.7% | [42.4, 59.0] |  +450.35 |    +$3.31 |                                     |
| chop      |       249 | **51.4%** | [45.2, 57.5] | **+1725.12** |    +$6.93 | **MARGINAL** (50-55% band)         |

**Counterfactuals:**

- abstain={chop}: WR **+0.45pp**, total **-$1725.12** (60% of bot earnings lost), 249 fires dropped (60%)
- abstain={chop, mixed} (trending-only gate): WR +7.56pp, total **-$2175** (87% of bot earnings lost), sample n=27 — Wilson CI too wide [40.7, 75.5] to act on

**Three surprising findings:**

1. **Same PnL paradox as Phase 14.** Chop is technically MARGINAL on WR but generates 69% of total bot PnL (+$1725 of +$2504). Auto-populating ABSTAIN_REGIMES=chop per master plan default would lose ~$575/day.
2. **The historical 23.19pp WR delta has narrowed.** Phase 14 was 256-trade research data — the 2026-05-12 audit on 477 current bot fires shows trending WR=59.3% vs chop=51.4% — a 7.9pp delta, not 23pp. Classifier still separates but less starkly than the v3 validation suggested.
3. **2026-05-10 is the dominant data day.** 37% of fires, 99% of total PnL. The 2026-05-09 picture (small ±$40 across all buckets) doesn't separate buckets at all. Single-day outlier dominance — a permanent gate decision shouldn't be made on this distribution.

→ **Operator decision: ship infrastructure with kill-switch off, empty abstain set. Don't auto-populate.**

## What landed

Single commit onto `claude/jovial-hermann-7e103f` (FF from `claude/thirsty-poincare-2046a0`):

- `fbcd38a feat(phase-15): REGIME_GATE_ENABLED + REGIME_GATE_ABSTAIN_REGIMES env + EnsembleWrapper pre-fire regime filter`

### Code

- **`src/polymarket_bot/strategies/ensemble_wrapper.py`** — new `regime_detector: RegimeDetector | None` + `abstain_regimes: Iterable[str]` constructor args (both default empty/None). New `REGIME_GATE_LABELS` constant (`{trending, chop, mixed}` — `"unknown"` explicitly excluded to prevent cold-start blackout via operator typo). Spot-tick observation added in `_update_context()` when detector supplied. Refusal branch slotted AFTER Phase 14 tier-gate and BEFORE off/shadow/gate mode dispatch (same pattern, cheaper filter first). Emits `kind="regime_abstained"` JSONL records with `regime`, `abstain_regimes`, `window_ts`, `base_rationale`, `decision_id_hint`.
- **`scripts/run_paper.py`** — `REGIME_GATE_ENABLED` (bool, default false) + `REGIME_GATE_ABSTAIN_REGIMES` (CSV, default empty). When enabled, instantiates a `RegimeDetector()` with module defaults (5m/10m windows, trending>1.20 / chop<0.80). Detector is SEPARATE instance from spot_aware_v3's — strategies are runtime-exclusive but detector is logically per-strategy state.

### Tests

- `tests/strategies/test_ensemble_wrapper.py` — 6 new tests:
  - empty abstain set = zero behavior change (detector observed but classify never called)
  - gate-mode chop classifier → refusal + no LLM call (specialist + meta `call_count == 0`)
  - gate-mode trending classifier → normal LLM flow + LLM consulted
  - refusal emits exactly one `kind="regime_abstained"` JSONL line with all expected fields
  - constructor rejects unknown regime label + rejects `"unknown"` specifically (`ValueError`)
  - **100 evaluations <500ms** (queue-overflow no-overhead guard per `feedback_test_under_load`)

### Audit + docs

- `design/phase-15-regime-gate.md` — locked design per anti-vibe rule #1
- `scripts/audit_regime_wr.py` (NEW) — re-runnable per-regime audit using the live `RegimeDetector` against binance 1m klines (raw VPS ticks not retained on disk)
- [[../sessions/2026-05-12-phase-15-regime-gate|Session note 2026-05-12-phase-15-regime-gate.md]]

### Gates at close

| gate | result |
|---|---|
| ruff | ✅ All checks passed |
| mypy --strict (64 src files) | ✅ no issues |
| pytest | ✅ **487 passed** (+6 vs prior 481) |
| lint-imports | ✅ 3/3 contracts kept |

## Deploy status — SHIPPED + LIVE

Bundled deploy with Phase 14 + dashboard track on 2026-05-10:

1. Local FF push `claude/thirsty-poincare-2046a0:claude/jovial-hermann-7e103f` (fbcd38a)
2. VPS dashboard track preserved (tarball `/home/ops/dashboard-track-backup-2026-05-12/dashboard-track-20260510T215745Z.tar.gz` + `git stash@{0}`)
3. VPS `git pull --ff-only`: HEAD `c66fc07` → `fbcd38a`
4. `.envrc` appended:
   ```bash
   export TIER_GATE_ENABLED=false
   export TIER_GATE_BLOCKLIST=
   export REGIME_GATE_ENABLED=false
   export REGIME_GATE_ABSTAIN_REGIMES=
   ```
5. `sudo systemctl restart bot-staging.service` — clean boot **2026-05-10 21:58:44 UTC**
6. +5min verify @ 22:03 UTC: CLEAN (service still active, no errors, fires + fills continuing)
7. Dashboard work later re-applied on VPS via `git stash pop` — auto-merged cleanly on `loaders.py` (Phase 14 refactor + operator's MainPID additions touched different sections)

## How it plays to our side

1. **Pattern reuse from Phase 14** — same audit→design→implement→test→ship-dark template. Both kill-switches now ship + behave identically when disabled (zero overhead).
2. **LLM-spend saver** when populated — every blocked regime saves a 4-call ensemble round-trip.
3. **Seeds Phases 19 + 20** — the regime-gate pattern (pre-fire ABSTAIN by structural prior) is the template for Phase 19 (LLM async pre-compute filter) and Phase 20 (fear-greed daily scalar).
4. **Honest pushback on master plan** — the audit explicitly rejected the master plan's `REGIME_GATE_ABSTAIN_REGIMES=chop` deploy default. Empirical data on the current bot's distribution says don't.

## What's NOT included

- `REGIME_GATE_ABSTAIN_REGIMES` is empty by default. No regime is blocked in production at deploy time.
- `"unknown"` regime is REJECTED as an abstain target (would block all cold-start fires after every restart).
- No changes to the dashboard panel — regime classification is opaque to operator view this phase.
- No new regime labels — reuses `RegimeDetector`'s existing `trending | chop | mixed | unknown` literal.

## What's next

[[phase-16-bankroll-display|Phase 16 — Bankroll display experiment (read-only scenarios panel)]]. Operator wants to model alternative starting bankrolls for Phase 6 sizing planning. Locked decision #10 fixes paper at $1,000 — this phase does NOT change that, it adds a read-only scenarios panel. Prompt to be drafted at `phase-prompts/phase-16-bankroll-display-2026-05-13.txt`.

## Cross-references

- Master plan: [[../sessions/2026-05-11-phase-12-master-plan]] §4 → Phase 15
- Memory: `memory/checkpoint_phase_15_regime_gate.md`
- Phase 14 (sibling kill-switch): [[phase-14-tier-gate]]
- Session note: [[../sessions/2026-05-12-phase-15-regime-gate]]
- Design doc: `design/phase-15-regime-gate.md`
- Audit script: `scripts/audit_regime_wr.py`
- Detector design: `design/regime_detector.md` (v3 strategy)
- Validation evidence (historical): `runbooks/gate-evidence/regime-classifier-validation.txt`
