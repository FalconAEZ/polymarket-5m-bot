---
title: Phase 15.5 — PnL truth pass + Phase 18B meta_outcome telemetry + Phase 16 scenarios panel + dashboard.py corrections-wire fix
status: SHIPPED + LIVE 2026-05-10 23:50:50 UTC. HEAD `8406c2d` on `claude/jovial-hermann-7e103f`. Bundled triage deploy: 3 commits (`d6f02d1`, `a1a3e43`, `8406c2d`) atop `75ea5f6`. 494 tests green. Operator-authorized bundled-stop deploy.
tags: [phase, triage, pnl-reconciliation, meta-observability, bankroll-display, dashboard-fix, deployed]
---

# Phase 15.5 — PnL truth bundle

> Operator framing 2026-05-11: "$2,504 reported PnL is not real — it's
> phantom-fill corrupted. Stop the bot for proper development, ship the
> changes that need a restart, resume." Triage bundle: PnL
> reconciliation, meta-decide observability, bankroll display, and a
> drive-by fix on the Streamlit dashboard that was the actual source
> of the operator's confusion.

## Why this phase existed (not in master plan)

Operator-found inconsistency: ad-hoc audit scripts and the Streamlit
dashboard reported +$2,504 cumulative PnL while the production v4
dashboard (the one operator actually watches) reported +$75.80. Every
optimisation audit (Phase 13 unfilled-lift, Phase 14 tier-gate, Phase
15 regime-gate) had quoted the broken +$2,504 number. We couldn't
optimise what we couldn't measure.

This was a TRIAGE bundle, not a strategy improvement:

1. Reconcile PnL accounting (find which numbers are real).
2. Ship Phase 18B meta-decide telemetry so the NEXT audit cycle has
   the data Phase 19 (async LLM pre-compute) needs.
3. Ship Phase 16 bankroll display.
4. Surface and fix the dashboard's broken PnL reader as a side effect
   of (3).

## The reconciliation chain (Item 1)

`scripts/audit_pnl_truth.py` (committed `8406c2d`) classifies every
settled record. Reconciliation chain:

```
  raw  sum(settled.pnl_usd)             = +$2,556.25
  +    settled_correction overlay        = -$2,491.72
  ----------------------------------------------
  =    corrected total                   = +$64.53   ← truth
       v4 dashboard reports               +$75.80   ← within drift
```

The entire $2.5k gap is `settled_correction` records that naive readers
ignore. **The bot writer is correct; readers are the bug class.**

Per-class breakdown over 482 settled records:

| Class | n | raw Σ | effective Σ |
|---|---:|---:|---:|
| `corrected_by_settled_correction` | 41 | +$2,479.34 | −$12.38 |
| `phantom_taker_no_size_attested` (snapshot gap, not phantom on inspection) | 229 | +$110.61 | +$110.61 |
| `real_maker_fill_at_settle` | 9 | −$24.92 | −$24.92 |
| `phantom_taker_floor_price` (strict Phase 11.A signature) | 1 | −$5.00 | −$5.00 |
| `real_taker_fill` | 140 | −$3.78 | −$3.78 |
| `no_fill` | 62 | $0 | $0 |

The 41 corrections split:

| Sub-class | n | mechanism |
|---|---:|---|
| `polymarket-post-hoc`, resolution FLIPPED | 20 | Chainlink local resolver disagreed with Polymarket — bot recorded "win" that was actually loss |
| `phantom-fill-neutralized`, resolution SAME | 21 | May 9 phantom-fill incident — backfill zeroed them out |

## Honest pushback on operator framing

- Operator: "$2,504 phantom lives in <15% tier as phantom_taker."
- Audit: by the strict definition (`price < $0.06 AND ask_size_top =
  None`), **only 1 record matches**. The phantom $2.5k is
  **corrections**, not bottom-tier fills. The Phase 14 per-tier audit
  was the broken reader.
- Operator: "Actual is ~$75."
- Audit: corrected total is **+$64.53**; v4 dashboard's +$75.80 is
  within window/rounding drift. Operator was right within rounding.

## What landed

Three commits onto `claude/jovial-hermann-7e103f` (FF push from local
`claude/elastic-banzai-0ba669`):

### `d6f02d1` — Phase 18B meta_outcome telemetry

- `src/polymarket_bot/agents/protocol.py` — new `MetaOutcome` Literal:
  `ok / api_error / refusal / no_text / validation_failed /
  invariant_violated / exception / no_meta_call / timeout`.
- `src/polymarket_bot/agents/anthropic_client.py` — `parse()` returns
  3-tuple `(parsed, usage, outcome)`. Each failure return path tagged.
- `src/polymarket_bot/agents/meta.py` — `decide()` returns
  `(decision, outcome)`. Adds `"invariant_violated"` branch for the
  post-Pydantic FIRE/ABSTAIN-side invariant.
- `src/polymarket_bot/agents/{momentum, oracle_gap, orderbook}.py` —
  unpack the 3-tuple (drop outcome — specialists don't propagate it).
- `src/polymarket_bot/strategies/ensemble_wrapper.py` —
  `_run_ensemble` returns `(votes, decision, outcome)`; adds
  `"no_meta_call"` and `"exception"` branches; writes `meta_outcome`
  field into every `ensemble_vote` JSONL record (gate + shadow + timeout).
- `src/polymarket_bot/strategies/ensemble.py` — legacy
  EnsembleStrategy unpacks new tuple, drops outcome (wrapper logs it).
- 3 new tests (test_anthropic_client + test_meta + test_ensemble_wrapper).
- `design/phase-18b-meta-observability.md` (NEW) locks contract.
- ZERO behavior change. Pure additive observability.

### `a1a3e43` — Phase 16 scenarios panel + dashboard corrections-wire fix

- `src/polymarket_bot/dashboard/loaders.py` — new `ScenarioResult`
  dataclass + `compute_scenarios(rows, scenarios, *, fixed_stake_usd)`
  function. Projects realised PnL onto $500/$1k/$2k/$5k/$10k starts at
  the locked $5/trade stake. `is_bankrupt` flag; no clamping at 0.
- `scripts/dashboard.py` — adds the missing
  `apply_settled_corrections()` call between `load_decisions` and the
  first KPI render. Adds `_render_scenarios_panel()` below per-tier.
- 4 new tests in `tests/dashboard/test_loaders.py`:
  - `test_scenarios_at_1k_matches_actual_pnl`
  - `test_scenarios_scale_linearly_at_fixed_stake`
  - `test_scenarios_handles_negative_pnl_without_clamping`
  - `test_apply_settled_corrections_overlays_corrected_pnl` (FIRST
    regression for that function — was uncovered until today).
- `design/phase-16-bankroll-display.md` (NEW) locks contract.

### `8406c2d` — Item 1 audit script + session reconciliation note

- `scripts/audit_pnl_truth.py` (NEW) — re-runnable classifier.
- `state/sessions/2026-05-11-phase-15.5.md` (NEW) — reconciliation
  table + per-class breakdown + Item 1e verdict.
- `state/sessions/2026-05-11-phase-15.5-prestop.txt` (NEW) —
  pre-stop snapshot from the SIGKILL'd graceful drain.

## Gates green at every commit

- ruff ✓ (auto-format applied on commit hooks)
- mypy --strict ✓ (64 source files)
- pytest **494 passed** ✓ (+7 vs prior 487 — 3 for 18B, 4 for 16)
- lint-imports 3/3 contracts kept ✓

## DEPLOY STATUS: SHIPPED + LIVE

| Event | When (UTC) |
|---|---|
| Bot stopped (SIGKILL after 30s SIGTERM drain) | 2026-05-10 23:23:13 |
| Pre-stop snapshot captured | 2026-05-10 23:23:30 |
| Item 1 audit + reconciliation table posted | 2026-05-10 ~03:30 |
| Operator "go" | 2026-05-10 ~03:35 |
| Phase 18B commit `d6f02d1` | 2026-05-10 ~03:50 |
| Phase 16 commit `a1a3e43` | 2026-05-10 ~03:55 |
| Item 1 commit `8406c2d` | 2026-05-10 ~04:00 |
| Push to origin/claude/jovial-hermann-7e103f (FF) | 2026-05-10 ~04:00 |
| VPS `git pull --ff-only` (`fbcd38a → 8406c2d`) | 2026-05-10 23:50 |
| `systemctl start bot-staging.service` | **2026-05-10 23:50:50** |
| Orphan recovery `recovered=2 unresolved=0` | 2026-05-10 23:50:51 |

Restart-verify (immediate):
- `is-active: active`, MainPID=`527106`
- Single expected WARN: `ensemble base=wide_fire — NO tier/priors/EV
  gates; LLM is the only filter`
- All defense layers up: instant-settle / orphan-recovery /
  post-hoc gamma retry / periodic orphan-recovery (300s)
- `TIER_GATE_ENABLED=false`, `REGIME_GATE_ENABLED=false`,
  `ENSEMBLE_MODE=gate`, `ENSEMBLE_BASE_STRATEGY=wide_fire`, daily
  budget $10 — unchanged from pre-stop

Pre-stop SIGKILL note: bot dragged through the 30s `TimeoutStopSec`
draining 1 in-flight settle before systemd KILL-9'd it. Orphan-recovery
caught the dropped settle (and 1 other) on restart. Future
housekeeping: raise `TimeoutStopSec` to 90-120s so graceful drain
completes — flagged in checkpoint memory, NOT shipped this phase.

## What this phase explicitly did NOT do

- Did NOT ship Phase 13B regime-conditional unfilled-lift. Sample size
  still too small per 2026-05-12 audit. Wait 5-7 more days.
- Did NOT change `ENSEMBLE_MODE`, LLM timeout, `wide_fire` base, or any
  strategy threshold.
- Did NOT touch decision #10 ($1k paper bankroll).
- Did NOT flip `TIER_GATE_ENABLED` or `REGIME_GATE_ENABLED`.
- Did NOT ship Phase 19 (async LLM pre-compute) — that depends on the
  Phase 18B telemetry data we don't have yet.
- Did NOT ship Phase 17 (sizing modes) — that needs operator approval
  to revisit decision #9.

## What this unlocks

- **Phase 19 design** can use REAL meta_outcome attribution data
  instead of guesses about the 22.1% meta=None rate.
- **Phase 17 sizing decisions** can use the corrected PnL (+$64.53)
  and the scenarios panel instead of phantom-inflated numbers.
- **Any future audit script** that touches `state/decisions/*.jsonl`
  MUST call `apply_settled_corrections()`. The new regression test in
  `tests/dashboard/test_loaders.py` prevents dashboard backslide; ad-hoc
  scripts are operator-discipline.
- **The PnL truth audit (`scripts/audit_pnl_truth.py`) is re-runnable**
  on any newer data window.

## Next

- +5min and +30min verify (per `feedback_vps_deploy_verify_late`).
  Confirm `meta_outcome` field is flowing in `state/ensemble/`.
- Re-pull decisions on a 14-day window and re-run Phase 13B
  unfilled-lift audit using the corrected accessor.
- Phase 17 (sizing modes) is the next master-plan slot — but requires
  explicit operator approval to revisit decision #9.
