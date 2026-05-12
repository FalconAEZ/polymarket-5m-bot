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

- **bot-staging.service** active since **2026-05-12 15:42:38 UTC** (PHASE-F-4 — honest-pushback pivot to v2 after v3 fired 0 in 36 min; canonical soak clock reset) on VPS at HEAD `af53490`. MainPID `593311`; orphan-recovery primed at startup. **Strategy = `spot_aware_v2`** (no regime gate; matches May 10's proven +$46-day profile). First v2 fire at 15:43:23 UTC (45 sec after deploy). Expected ~184 fires/day, ~52% WR, ~$0.25/trade.
- **dashboard-server.service** (v3 FastAPI + React) active since **2026-05-11 06:25:15 UTC** on VPS at HEAD `f0ee20d`. Bound to `127.0.0.1:8505`; access via SSH local-port-forward. `/api/state.scenarios` returns 5-row bankroll projection. `decisions_truth_source=polymarket`.
- Strategy: **`spot_aware_v3`** (regime-detector gate, no LLM wrapper). Cut 2026-05-12 per [[phase-F-architecture-audit]].
- Pre-cut 5-day audit (truth-corrected): ensemble+wide_fire era (May 11-12) at WR 38-44% / −$0.58/trade vs spot_aware family (May 9-10) at WR 52% / +$0.20/trade. The +4.1pp shadow uplift did not reproduce in gate mode.
- Phase 14 + 15 kill-switches still dark (env unset / `=false`). Phase 18B `meta_outcome` telemetry will be empty post-cut since no ensemble fires.

## In progress / next

- [[phase-F-architecture-audit|Phase F]] — architecture audit + convergence. ✅ **CLOSED 2026-05-12** after 4 restarts. Final state: `STRATEGY=spot_aware_v2` (PHASE-F-4 pivot from v3 after 0 fires in 36 min). Soak underway. Phase F.3 audit superseded by Phase G full study.
- [[phase-G-edge-discovery|**Phase G**]] — full edge-discovery deep dive. ✅ **CLOSED 2026-05-13** analytical-only. 635 fires audited, 17 dimensions, Kelly + Monte Carlo. Headline: tier 30-50% × |Δ|<5 is the winning cell v2 rejects. 629K PDF on operator's Desktop. Feeds Phase H.
- [[phase-H-v2_1|**Phase H — v2.1 implementation**]]. 🟢 **H.2 code SHIPPED 2026-05-13** (`810f841` + design lock `4f218b1`). v2.1 = v2 + CH1-CH4 filter changes + Kelly + multi-fire + BankrollTracker. **618 tests green**, `make verify` exit 0. **H.5 deploy DEFERRED** (~5h v2 soak insufficient; layering Kelly on negative-true-PnL day too risky). **CH3 priors-gap honest-pushback** flagged: floor relaxation alone won't fire on Phase G winning cell without priors data extension. H.6 7-day soak gate after H.5.
- [[phase-16b-every-window-mode|Phase 16.B]] — **PAUSED** (router depends on LLM signal; cut from production via Phase F).
- [[phase-19-llm-async-precompute|Phase 19]] — **SHELVED** (the 12s inline-await latency problem dissolves when LLM exits the fire path per Phase F cut).
- ~~Phase 17 (sizing modes scaffolding)~~ — **SUPERSEDED by Phase H** (Kelly + multi-fire + BankrollTracker ship as part of v2.1).
- ~~Phase 18 (Kelly sizing)~~ — **SUPERSEDED by Phase H** (CH5-CH6 in v2.1 ship).

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
