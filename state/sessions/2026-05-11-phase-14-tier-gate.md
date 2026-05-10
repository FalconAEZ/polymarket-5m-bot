# Phase 14 — TIER_GATE_ENABLED + TIER_GATE_BLOCKLIST + EnsembleWrapper pre-fire filter

**Session start:** 2026-05-10 UTC at HEAD `c66fc07` (one above 73c8fc5)
**Branch:** `claude/hopeful-mcnulty-b81585` (worktree) — fast-forwarded `claude/jovial-hermann-7e103f` to `b6b3599`
**Bot state at start:** active on bot-staging since 2026-05-10 16:31:15 UTC, ENSEMBLE_MODE=gate, 5 defense layers live.
**Phase 13 verdict carried over:** NULL result — no lift shipped, advance.

## What landed

Two commits onto `claude/jovial-hermann-7e103f`:

1. `d4f3fde docs(phase-13): NULL result — audit shows no tractable lift target`
2. `b6b3599 feat(phase-14): TIER_GATE_ENABLED + TIER_GATE_BLOCKLIST env + EnsembleWrapper pre-fire filter`

Pushed to GitHub on both `claude/jovial-hermann-7e103f` and `claude/hopeful-mcnulty-b81585`.

### Files (Phase 13)

- `scripts/audit_unfilled_v2.py` — gap-bucketed never-fill audit (counterfactual W + Wilson CI per bucket)
- `state/sessions/2026-05-11-phase-13-fill-rate-lift.md` — audit doc with operator-confirmed null verdict

### Files (Phase 14)

- `src/polymarket_bot/tiers.py` (NEW) — top-level canonical `PRICE_TIER_BUCKETS` + `tier_label_for_price`. Placed at top level (not under `strategies/`) so the dashboard can import without violating the `dashboard → strategies` import-linter contract.
- `src/polymarket_bot/dashboard/loaders.py` — re-exports tier constants from `polymarket_bot.tiers`. Single source of truth.
- `src/polymarket_bot/strategies/ensemble_wrapper.py` — new `tier_blocklist` constructor arg (default empty); pre-mode-dispatch refusal path emits `kind="tier_abstained"` JSONL records; LLM call is short-circuited on blocked tier (saves Haiku + Sonnet spend on blocked windows).
- `scripts/run_paper.py` — `TIER_GATE_ENABLED` (bool) + `TIER_GATE_BLOCKLIST` (CSV) envs with startup validation. Unknown tier labels raise ValueError at boot.
- `tests/test_tiers.py` (NEW) — 14 parametric boundary tests on `tier_label_for_price`.
- `tests/strategies/test_ensemble_wrapper.py` — 5 new tests:
  - empty blocklist = zero behavior change (regression guard)
  - gate-mode blocked tier → no LLM call (specialist + meta `call_count == 0`)
  - shadow-mode blocked tier → still refuses (gate is mode-independent)
  - unlisted tier → passes through + LLM consulted
  - constructor rejects unknown label with `ValueError`
  - 100 evals < 500ms (queue-overflow no-overhead guard per `feedback_test_under_load`)
- `design/phase-14-tier-gate.md` (NEW) — design doc per anti-vibe rule #1.
- `scripts/audit_per_tier_wr.py` (NEW) — re-runnable per-tier WR audit (mirrors dashboard binning).

### Gates

- `ruff check src/ tests/ scripts/` — green
- `mypy --strict src/` — 64 source files, no issues
- `pytest` — **481 passed** (was 457 at session start → +24 new tests across two phases)
- `lint-imports` — 3/3 contracts kept (dashboard→strategies forbidden remains satisfied via the top-level `polymarket_bot.tiers` module)

## Audit evidence (motivating the dark-ship choice)

`scripts/audit_per_tier_wr.py` on 3 days of VPS data (2026-05-08 .. 2026-05-10, n=467 fires aggregate):

| tier      | n_fired | n_settled | WR    | 95% CI         | PnL ($) | gate-flag |
|-----------|--------:|----------:|------:|:--------------:|--------:|:----------|
| <15%      |      37 |        25 | 48.0% | [30.0, 66.5]   | 2450.73 | n<30 (insufficient) — phantom-fill class needs separate handling |
| 15-30%    |       8 |         8 | 75.0% | [40.9, 92.9]   |  121.57 | n<30 |
| **30-50%** |     78 |        75 | **49.3%** | [38.3, 60.4] | **+65.21** | **BLOCK criterion met BUT positive PnL** |
| 50-70%    |     285 |       277 | 50.9% | [45.0, 56.7]   |  -64.44 | — |
| 70-85%    |      19 |        18 | 77.8% | [54.8, 91.0]   |    4.79 | n<30 |
| 85-100%   |      41 |         2 | 50.0% | [ 9.5, 90.5]   |   -4.74 | n<30 — fill rate problem (only 5% fill at this tier) |

Only the 30-50% tier triggers the master-plan's WR<50%+n≥30 gate. But its PnL is +$65 over 3 days — the asymmetric payoff at 30-50¢ entry covers the sub-50% WR. **Blocking that tier today would lift WR ~0.5pp and cost ~$22/day in real PnL.** Honest pushback: ship the infrastructure (so operator can flip it on a longer-sample audit later), don't populate the blocklist now.

## Deploy status — DEFERRED

VPS `claude/jovial-hermann-7e103f` has 80+ uncommitted lines on `src/polymarket_bot/dashboard/loaders.py` (adding systemd MainPID integration: `_systemd_unit_for`, `_systemctl_path`, `_from_systemd`) plus modifications to `dashboard/theme.py` and `state/token_side_index.json`, plus 10+ untracked dashboard files (`bankroll.py`, `components.py`, `gamma_resolver.py`, `markets.py`, `pipeline_latency.py`, `profit_pace.py`, `provider_rtt.py`, `rtt_collector.py`, `rtt_loader.py`, `streaks.py`, `dashboard_server/`, etc.). Clearly a parallel dashboard build-out track.

Per `feedback_defer_deploys_to_natural_restart` + `feedback_vps_deploy_verify_late` + the CLAUDE.md "investigate before deleting or overwriting" rule, NOT touching the VPS. Phase 14 ships dark by definition (env defaults to `false`/empty), so the deploy adds zero value today.

**Next deploy bundles Phase 14 + the dashboard track + whatever Phase 15 lands.** Operator merges + restarts once.

## Bot state — unchanged

bot-staging.service still active since 2026-05-10 16:31:15 UTC. Strategy = ensemble + ENSEMBLE_MODE=gate + ENSEMBLE_BASE_STRATEGY=wide_fire. Five defense layers (background-settle, instant-settle, periodic-orphan-recovery, post-hoc gamma retry, ensemble timeout) all running.

Bot HEAD `c66fc07` (no change). When operator next restarts: `git pull` will fast-forward to `b6b3599`, env stays at defaults, no behavior change.

## What's next

Phase 15 — regime gate wired to ensemble. Per master plan §4. Same audit→design→implement→test→ship-dark pattern. Next-session prompt at `phase-prompts/phase-15-regime-gate-2026-05-12.txt` (to be drafted at session end).

## Honest pushback recorded

1. **Phase 13 lift** rejected because 46.2% counterfactual W on unfilled 1-2¢ bucket is below the bot's overall WR — forcing fills would dilute, not lift.
2. **Phase 14 blocklist auto-population** rejected because the only triggering tier (30-50%) has positive PnL.
3. **VPS deploy** deferred because parallel uncommitted dashboard work exists nowhere else in git history.

All three judgments aligned with operator preferences (`feedback_no_vibe_coding`, `feedback_honest_pushback`, `feedback_defer_deploys_to_natural_restart`).
