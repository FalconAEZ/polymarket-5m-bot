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
- [[phase-14-tier-gate]] — **infra dark-shipped** 2026-05-10. `TIER_GATE_ENABLED` + `TIER_GATE_BLOCKLIST` envs in `EnsembleWrapper` + `scripts/run_paper.py`, default OFF. Commit `b6b3599`. **DEPLOYED via Phase 15 bundle** 2026-05-10 21:58:44 UTC. 481 tests green.
- [[phase-15-regime-gate]] — **infra dark-shipped** 2026-05-10. `REGIME_GATE_ENABLED` + `REGIME_GATE_ABSTAIN_REGIMES` envs added; default OFF. Commit `fbcd38a`. Bundled VPS deploy with Phase 14 + dashboard track. Audit (n=477) found chop MARGINAL but PnL-dominant — infra-only ship per honest pushback, abstain set empty. 487 tests green.
- [[phase-15.5-pnl-truth-bundle]] — **SHIPPED + LIVE** 2026-05-11. Triage bundle of Phase 15.5 (PnL truth pass) + Phase 18B (`meta_outcome` telemetry) + Phase 16 (bankroll scenarios) + v3 dashboard recovery. Naive sum +$2,556 → corrected +$75.26; entire gap = 41 `settled_correction` records (20 polymarket-flips + 21 phantom-neutralized). Commits `d6f02d1 → f0ee20d` (10 total). 487 tests green + React build clean. **Streamlit dashboard fully deleted** per operator directive.

## Live operation

- **bot-staging.service** active since **2026-05-10 23:50:50 UTC** on VPS at HEAD `831c756` (Phase 15.5 deploy chain). MainPID stable; orphan-recovery primed at startup.
- **dashboard-server.service** (v3 FastAPI + React) active since **2026-05-11 06:25:15 UTC** on VPS at HEAD `f0ee20d`. Bound to `127.0.0.1:8505`; access via SSH local-port-forward. `/api/state.scenarios` returns 5-row bankroll projection. `decisions_truth_source=polymarket`.
- Strategy: `ensemble` (`ENSEMBLE_MODE=gate`, `ENSEMBLE_BASE_STRATEGY=wide_fire`).
- Edge (live, 2026-05-11): `agg.total_pnl_usd=$75.26` over 428 settled; aligned with the Phase 15.5 Item 1 reconciliation prediction. 70 post-restart `ensemble_vote` records with `meta_outcome` populated: 97.1% `ok`, 2.9% `invariant_violated`.
- Phase 14 + 15 default behavior unchanged on production — both kill-switches dark (env unset / `=false`).

## In progress / next

- [[phase-16b-every-window-mode|**Phase 16.B**]] — every-window mode with signal-driven router. 🟢 **16.B.4 + 16.B.5 SHIPPED + LIVE 2026-05-11/12.** Wrapper wire deployed `2eb54fd`; `EVERY_WINDOW_SHADOW=true` flipped 18:02:05 UTC 2026-05-11; shadow soak underway. wide_fire phantom-zone fix shipped in two iterations (`3875d3c` per-side BUGGY → `7a5b19e` per-asset_id CORRECT) — see phase ledger §"2026-05-12" for the saga. Phantom-fill backfill applied (3 records). Remaining: 16.B.6 7-day soak gate → PROMOTE/ROLLBACK.
- [[phase-19-llm-async-precompute|**Phase 19**]] — LLM async pre-compute. Design doc LOCKED 2026-05-12 (`design/phase-19-llm-async-precompute.md`). Awaiting operator sign-off + implementation. Targets 8.8% gate-timeout rate → ≤0.5%; eliminates 119K-record queue-overflow class. Default-OFF via `LLM_PRECOMPUTE_ENABLED`. Implementation (Phase 19.1) is ~3h next-session work.
- ~~Phase 17 (sizing modes scaffolding)~~ — **SUBSUMED by Phase 16.B**.
- ~~Phase 18 (Kelly sizing)~~ — **SUBSUMED by Phase 16.B** (`sizing.py` ships there).

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
