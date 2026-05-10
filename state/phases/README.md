---
title: Phase ledger
tags: [moc, phases]
---

# Phase ledger

Chronological + status. Each phase has its own note when work begins; tags are pinned in git when the gate passes. Optimization phases (13-25 per the master plan) don't carry git tags by design — only structural milestones do.

## Closed

- [[phase-A-bonereaper]] — research-stream pre-flight audit. **ABORT** at 60% gate. Tag `study-A-final`.
- [[phase-0-foundations]] — toolchain, accounts, repo. **GREEN**. Tag `phase-0-pass`.
- [[phase-1-wallet-auth|Phase 1A — Wallet & Auth (no-money)]] — wallet generation + L2 auth + signing-flow proof. **GREEN**. Tag `phase-1a-pass` at `1537a18`. Cost: $0. Funder=`0x512D…5d22`, Signer=`0x8d97…2B4A`. One incident → [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]].
- [[phase-2-data-plane]] — read-only data plane (capture process, JSONL schema). Closed 2026-05-07 evening.
- Phase 3 (LLM A/B) — closed 2026-05-07 at `3cd4a70`, tag `phase-3-pass`. OD-5 verdict: CUT ensemble (latency + cost gates fail decision #16). Spend: $0.405. Ensemble retained for Phase 4 re-run.
- Phase 4 (paper runtime) — closed 2026-05-07 at `43f64af`. Mac run died on laptop sleep; restarted on VPS as part of Phase 5.7 staging.
- Phase 4.5 (operations dashboard) — closed 2026-05-07 evening at `c1ff257`.
- [[phase-5-vps]] — VPS provisioning + 24h staging on AWS Lightsail Dublin (`5m-Polymarket-bot`, `108.132.51.116`). Tag `phase-5-pass` at 2026-05-08 19:20 UTC. Five defense layers live (background-settle, instant-settle, periodic-orphan-recovery, post-hoc gamma retry, ensemble timeout).
- [[phase-11-spot-aware|Phase 11.A SpotAware soak]] — superseded by Phase 5 LLM-ensemble experiment 2026-05-10. Bot promoted shadow→gate at 2026-05-10 16:31:15 UTC after operator-confirmed +4.1pp WR uplift.
- Phase 12 (master plan) — planning artifact only; `pdfs/PHASE_12_MASTER_PLAN.pdf` (36 pages) drafted 2026-05-10. Locks the 12-phase optimization roadmap targeting fill-rate 85%+ and 60% WR Phase-23 gate.
- [[phase-13-fill-rate]] — **NULL result** 2026-05-10. Audit closed by operator choice; no `SPOT_AWARE_LIMIT_LIFT_BPS` env, no code change. Commit `d4f3fde`.
- [[phase-14-tier-gate]] — **infra dark-shipped** 2026-05-10. `TIER_GATE_ENABLED` + `TIER_GATE_BLOCKLIST` envs in `EnsembleWrapper` + `scripts/run_paper.py`, default OFF. Commit `b6b3599`. **VPS deploy DEFERRED** — parallel dashboard track on VPS has ~80 uncommitted lines on `loaders.py` + 10 untracked dashboard files. 481 tests green.

## Live operation

- **bot-staging.service** active since 2026-05-10 16:31:15 UTC on VPS at HEAD `c66fc07`.
- Strategy: `ensemble` (`ENSEMBLE_MODE=gate`, `ENSEMBLE_BASE_STRATEGY=wide_fire`).
- Edge: 52.0% WR / +$76.79 / 402 settled / 12.5% LLM timeout rate / 62.5% effective fire rate (2026-05-10).
- Phase 14 default behavior unchanged on production until env is flipped on (or until VPS pull arrives, then no behavior change with default false).

## In progress / next

- **Phase 15** — regime gate wired to ensemble (`REGIME_GATE_ENABLED` + `REGIME_GATE_ABSTAIN_REGIMES`). Same audit→design→implement→test→ship-dark pattern as Phase 14. Prompt at `phase-prompts/phase-15-regime-gate-2026-05-12.txt`. Next session.

## Master-plan phases 16-25 (planned)

Per [[../sessions/2026-05-11-phase-12-master-plan]] §4:

| # | Phase | ETA | Kill-switch env |
|---|---|---|---|
| 16 | Bankroll display experiment | 1h | dashboard-only |
| 17 | Position sizing modes scaffolding | 3h | `POSITION_SIZING_MODE` |
| 18 | Kelly sizing implementation | 3h | (revisits decision #9) |
| 19 | LLM async pre-compute | 4h | `LLM_PRECOMPUTE_ENABLED` |
| 20 | Fear-greed daily input | 2h | disable cron |
| 21 | WS depth plumbing | 3h | `DEPTH_GUARD_HONOR_TRACKER` |
| 22 | Dashboard observability for gates | 2h | dashboard-only |
| 23 | 7-day soak + statistical significance gate | monitoring | n/a |
| 24 | Phase 6 live-deployment readiness review | 3h | decision-gated |
| 25 (opt) | 4th ensemble specialist | 4h | (revisits decision #5) |

Phases 17 and 25 are locked-decision revisits and require explicit operator approval before execution.

## Hard deferred

- **Phase 1B** — wallet funding + first gasless order. ⏸ deferred to head of Phase 6 per [[../decisions/README#decision-20\|decision #20]].
- **Phase 6** — live deployment. ⏸ gated on Phase 23 statistical-significance gate + decision #12 ($2k bankroll trigger for hardware wallet).
- **Phases 7, 8** — scale / hardening. ⏸ post-Phase 6.

## Cross-cutting notes

- All gates use `bash runbooks/gates/phase-N.sh` exiting 0; evidence captured to `runbooks/gate-evidence/phase-N.txt` (where gates exist — optimization phases 13-25 use audit doc + design doc instead).
- Memory checkpoints at `~/.claude/projects/.../memory/checkpoint_phase_N.md`.
- Anti-vibe rule #4 is religious: **no phase advance without the gate command exiting 0 in the operator's terminal** (for structural phases). For optimization phases: audit + design + tests green + operator sign-off.
- Optimization phases ship dark-by-default (kill-switched env, default OFF). Operator flips after empirical validation, not on first audit.

## Related

- [[../runbooks/README|Operational runbooks]]
- [[../decisions/README|Locked decisions]]
- [[../sessions/README|Sessions ledger]]
- `RUNBOOK.md` (project root) — the canonical execution document
- `pdfs/PHASE_12_MASTER_PLAN.pdf` — 12-phase optimization roadmap (the spec for phases 13-25)
