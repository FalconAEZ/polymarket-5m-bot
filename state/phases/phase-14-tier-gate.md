---
title: Phase 14 — entry-price tier blocklist (TIER_GATE_ENABLED + TIER_GATE_BLOCKLIST)
status: Infrastructure DARK-SHIPPED 2026-05-10. Commit `b6b3599` on `claude/jovial-hermann-7e103f`, pushed to GitHub. VPS DEPLOY DEFERRED — parallel uncommitted dashboard track. Default behavior unchanged (env off + empty blocklist = zero-overhead pass-through). 481 tests green.
tags: [phase, tier-gate, kill-switch, dark-ship]
---

# Phase 14 — TIER_GATE_ENABLED + TIER_GATE_BLOCKLIST

> Kill-switched entry-price tier blocklist that refuses fires whose `price_limit` falls into operator-specified tier buckets, applied BEFORE the LLM ensemble (saves Haiku+Sonnet round-trip on blocked windows). Second executable phase from the [[../sessions/2026-05-11-phase-12-master-plan|Phase 12 master plan]]. Shipped as infrastructure-only after honest pushback on the auto-blocklist proposal.

## Why this phase existed

Master plan §4 → Phase 14: codify the dashboard's per-tier WR breakdown into an enforceable filter. Tiers with low historical WR + sufficient n should be blockable via env, no code release required to A/B them.

## What the audit found (the actual story)

`scripts/audit_per_tier_wr.py` (committed) on 3 days of VPS data (n=467 fires aggregate):

| tier | n_fired | n_settled | WR | PnL ($) | gate-flag |
|---|---:|---:|---:|---:|:---|
| <15% | 37 | 25 | 48.0% | +2450.73 | n<30 — also phantom-fill class |
| 15-30% | 8 | 8 | 75.0% | +121.57 | n<30 |
| **30-50%** | **78** | **75** | **49.3%** | **+65.21** | **WR<50% n≥30 — but PnL positive** |
| 50-70% | 285 | 277 | 50.9% | **−64.44** | WR>50% but PnL negative — the real leak |
| 70-85% | 19 | 18 | 77.8% | +4.79 | n<30 |
| 85-100% | 41 | 2 | 50.0% | −4.74 | n<30 — only 5% fill rate |

Two surprising findings:

1. **30-50% triggers the gate criterion on paper but bleeds positively.** Asymmetric payoff at 30-50¢ entry (paying 35¢ to win 100¢) covers sub-50% WR. Blocking it today loses real money for a 0.5pp cosmetic WR lift.
2. **50-70% is the actual PnL leak.** WR is just above 50%, but at 60¢ entry you need ~62% WR to overcome fees. It's 61% of all fires (277/455 settled), so blocking it isn't viable — it would gut volume. The fix is more surgical: see if a sub-filter (regime, tier×regime crossing) can isolate the bleeding subset.

→ **Operator decision: ship infrastructure with kill-switch off, empty blocklist. Don't auto-populate.**

## What landed

Two commits onto `claude/jovial-hermann-7e103f`:

- `d4f3fde docs(phase-13): NULL result — audit shows no tractable lift target`
- `b6b3599 feat(phase-14): TIER_GATE_ENABLED + TIER_GATE_BLOCKLIST env + EnsembleWrapper pre-fire filter`

### Code

- **`src/polymarket_bot/tiers.py` (NEW)** — canonical `PRICE_TIER_BUCKETS` + `tier_label_for_price`. **At TOP level** (not under `strategies/`) so the dashboard can import without violating the `dashboard → strategies` import-linter contract. The location matters.
- **`src/polymarket_bot/dashboard/loaders.py`** — re-exports tier constants from `polymarket_bot.tiers`. Single source of truth.
- **`src/polymarket_bot/strategies/ensemble_wrapper.py`** — new `tier_blocklist` constructor arg (default empty); pre-mode-dispatch refusal path; emits `kind="tier_abstained"` JSONL records; LLM call short-circuited on block.
- **`scripts/run_paper.py`** — `TIER_GATE_ENABLED` + `TIER_GATE_BLOCKLIST` envs with startup validation.

### Tests

- `tests/test_tiers.py` (NEW, 14 parametric boundary tests)
- `tests/strategies/test_ensemble_wrapper.py` — 5 new tests:
  - empty blocklist = zero behavior change (regression)
  - gate-mode blocked tier → no LLM call (call_count == 0)
  - shadow-mode blocked tier → still refuses (gate is mode-independent)
  - unlisted tier → passes through + LLM consulted
  - constructor rejects unknown label (`ValueError`)
  - **100 evaluations <500ms** (queue-overflow no-overhead guard per `feedback_test_under_load`)

### Audit + docs

- `design/phase-14-tier-gate.md` — locked design per anti-vibe rule #1
- `scripts/audit_per_tier_wr.py` — re-runnable audit
- [[../sessions/2026-05-11-phase-14-tier-gate|Session note 2026-05-11-phase-14-tier-gate.md]]

### Gates at close

| gate | result |
|---|---|
| ruff | ✅ clean |
| mypy --strict (64 src files) | ✅ no issues |
| pytest | ✅ **481 passed** (+24 vs prior 457) |
| lint-imports | ✅ 3/3 contracts kept |

## Deploy status — DEFERRED

VPS `claude/jovial-hermann-7e103f` still at `c66fc07`. Cannot fast-forward because:

- ~80 uncommitted lines on `src/polymarket_bot/dashboard/loaders.py` (adding systemd `MainPID` integration: `_systemd_unit_for`, `_systemctl_path`, `_from_systemd`)
- Uncommitted modifications to `dashboard/theme.py` + `state/token_side_index.json`
- 10+ untracked dashboard files in `src/polymarket_bot/dashboard/` (bankroll.py, components.py, gamma_resolver.py, markets.py, pipeline_latency.py, profit_pace.py, provider_rtt.py, rtt_collector.py, rtt_loader.py, streaks.py) + new `src/polymarket_bot/dashboard_server/`

Parallel "dashboard v4" build-out. Per `feedback_defer_deploys_to_natural_restart` + CLAUDE.md "investigate before deleting or overwriting" + `feedback_vps_deploy_verify_late`: VPS not touched. Phase 14 ships dark by definition, so deploy adds zero value today. Bundle into the next natural restart when the dashboard track lands.

## How it plays to our side

1. **Pattern establishment** — audit → kill-switched env → operator-controlled flip. The conventions (CSV env, canonical-label validation, `*_abstained` JSONL kind, design-doc-first) are now the template Phases 15/17/19/20/21 reuse.
2. **LLM-spend saver** when populated — every blocked tier saves a 4-call ensemble round-trip.
3. **Surfaces the real leak** — the audit IS the deliverable. We now know 50-70% bleeds, not 30-50% as the master plan hypothesized.

## What's NOT included

- `TIER_GATE_BLOCKLIST` is empty by default. No tier is blocked in production at deploy time.
- No changes to dashboard panel — the existing per-tier WR view is already the operator's signal.
- No new tier definitions — reuses the existing six buckets.

## What's next

[[phase-15-regime-gate|Phase 15 — regime gate wired to ensemble]]. Same audit→design→implement→test→ship-dark pattern. Goal: chop-regime ABSTAIN. Prompt staged at `phase-prompts/phase-15-regime-gate-2026-05-12.txt`.

## Cross-references

- Master plan: [[../sessions/2026-05-11-phase-12-master-plan]] §4 → Phase 14
- Memory: `memory/checkpoint_phase_14_tier_gate.md`
- Phase 13 (prereq null result): [[phase-13-fill-rate]]
- Session note: [[../sessions/2026-05-11-phase-14-tier-gate]]
- Design doc: `design/phase-14-tier-gate.md`
