---
title: Sessions ledger
tags: [moc, sessions]
---

# Sessions ledger

Daily session logs (anti-vibe operating rule #5: end every session with a 2-line note in `state/sessions/<utc-date>.md`).

## Logs

### 2026-05-06
- [[2026-05-06]] — bootstrap finished, Phase A closed (ABORT), Phase 0 closed (GREEN), decision #20 (Phase 1 1A/1B split), vault built; Phase 1A code shipped (8 commits 80df145..eb9d4d5).

### 2026-05-07
- [[2026-05-07]] — Phase 1A gate green at `1537a18`, tag `phase-1a-pass` pushed; env-req-rtf incident + postmortem; Phase 2 prompt staged.
- [[2026-05-07-evening]] — Phase 2 dev tasks 2.0-2.5 closed; capture launched on Mac (33s heartbeat measured, decision #21 added).
- [[2026-05-07-vps-provisioned]] — Phase 5 started: AWS Lightsail Ubuntu 24.04 in Dublin provisioned; vault → git (decision #18 revised).
- [[2026-05-07-phase-5.1-pass]] — Phase 5 Task 5.1 (SSH lockdown) GREEN: port 2222, key-only, no root, UFW + Lightsail console firewall.
- [[2026-05-07-phase-5.2-pass-5.3-blocked]] — 5.2 runtime install green, 5.3 CLOB latency measured.
- [[2026-05-07-phase-5.4-systemd-pass-5.5-design]] — 5.4 systemd units green; 5.5 alerter designed.
- [[2026-05-07-phase-5.5-chunk1-grafana-live]] — 5.5 chunk 1 green; bot-staging live on 4 feeds; grafana-agent pushing.
- [[2026-05-07-phase-5.5-chunk2-pass]] — 5.5 chunk 2 (Telegram alerter) green; e2e smoke-tested.

### 2026-05-08
- [[2026-05-08]] — Phase 5.7 staging clock; 24h paper soak data flowing.
- [[2026-05-08-phase-5-pass]] — Phase 5 GREEN; `phase-5-pass` tagged; litestream → S3 eu-west-1 + restore drill md5-identical.

### 2026-05-09
- [[2026-05-09-spot-aware-aggressive-launch]] — Phase 11.A.2 aggressive-mode launch (Δ_min/Δ_max/EV bypassed; tier discipline retained).
- [[2026-05-09-spot-aware-deep-dive]] — analysis of aggressive-mode WR + per-tier breakdown.
- [[2026-05-09-spot-aware-gate-early-read]] — 48h checkpoint early read.

### 2026-05-10
- [[2026-05-10-spot-aware-v2-postincident-fix]] — post-incident fixes after the 2026-05-09 instant-settle queue overflow.
- [[2026-05-10-phase-5-llm-ensemble]] — Phase 5 LLM ensemble shadow-mode deployed at `54fa0d5`; two queue-overflow incidents identified + fixed; economic-gate prompts validated.
- [[2026-05-10-phase-5-settle-resolution-bug]] — extended session: 4 phantom-fill variants + Chainlink wrong-resolution + ENSEMBLE_MODE shadow→gate promotion + LLM latency tuning (12s timeout) + periodic orphan-recovery. HEAD `73c8fc5`; 16 commits.
- [[2026-05-10-phase-12-planning]] — master plan drafted; 12-phase optimization roadmap; @antpalkin X-post folded in.
- [[2026-05-11-phase-12-master-plan]] — markdown equivalent of `pdfs/PHASE_12_MASTER_PLAN.pdf`; the spec for phases 13-25.
- [[2026-05-11-phase-13-fill-rate-lift]] — **Phase 13 NULL result.** Audit showed 1-2¢ unfilled subset W=46.2% (below bot's 52% WR); 0-1¢ bucket empty. Operator chose option (1) defer. Commit `d4f3fde`.
- [[2026-05-11-phase-14-tier-gate]] — **Phase 14 infra dark-shipped.** `TIER_GATE_ENABLED` + `TIER_GATE_BLOCKLIST` envs added to `EnsembleWrapper` as a pre-fire filter. Default OFF. 481 tests green. Commit `b6b3599`. Deployed via Phase 15 bundle.
- [[2026-05-11-phase-15.5]] — **Phase 15.5 SHIPPED + LIVE.** Triage bundle: PnL truth pass (naive +$2,556 → corrected +$75.26) + Phase 18B `meta_outcome` telemetry (`d6f02d1`) + Phase 16 bankroll scenarios + `apply_settled_corrections` wired into v3 dashboard (`90ba46a`) + Item 1 audit script (`8406c2d`) + +5h45min soak verify (70 ensemble_votes, 97% `ok` + 2 `invariant_violated`). **v3 dashboard source recovery** (50+ files) from `claude/dashboard-pm-truth-fix-7e103f` after the original Phase 15.5 pull silently deleted `dashboard_server/` from VPS. **Streamlit dashboard fully deleted** per operator directive. Latest commit `f0ee20d`.
- [[2026-05-11-phase-16b]] — **Phase 16.B research + design + router primitives.** Operator-authorized revisit of locked decisions #6 + #9 (Kelly subsumed; Phases 17 + 18 merged into 16.B). Shipped: comprehensive research study, counterfactual audit (+$344 projected delta), design doc locked, router primitives (`sizing.py` + `every_window/`) + 49 tests. 4 gates green at every commit (525 pytest passes). **No VPS deploy yet — env-gated default OFF.** Commits `e1b9a6b → 707786c`. Next session: 16.B.4 wrapper wire + 16.B.5 VPS dark deploy + 24h shadow.
- [[2026-05-11-phase-16b-4-and-phantom-zone-fix]] — **Phase 16.B.4 wrapper wire SHIPPED + DEPLOYED + 16.B.5 shadow soak underway. Sidebar: wide_fire phantom-zone fix.** `2eb54fd` wires router into EnsembleWrapper (env-gated default off) + 7 new tests; deployed to VPS 17:56:22 UTC; `EVERY_WINDOW_SHADOW=true` flipped 18:02:05 UTC; first `router_shadow` records flowing. Separately, fill-rate audit on operator's "many unfilled" report: **100% of today's 35 unfilled fires were phantom-defended at simulator level (not maker miss)**. Router's `taker_fallback` for `<15%` tier solves the wrong problem here — right fix is upstream at strategy. Shipped `3875d3c` wide_fire phantom-zone abstain + 3 tests; NOT deployed (defer per `feedback_defer_deploys_to_natural_restart`). 535 pytest passes. 16.B.6 + audit scripts deferred to next session.

### 2026-05-12
- [[2026-05-12-phase-19-design-and-arch-audit-prep]] — **3 deploys (`c32f1e5` + `3875d3c` + `7a5b19e`), 1 backfill, 1 design lock, 1 architecture-audit prompt drafted.** wide_fire phantom-zone fix shipped in two iterations: v1 per-side BUGGY (`3875d3c` deployed 11:16 UTC) bypassed by warmer's forward-window BookUpdates; v2 per-asset_id CORRECT (`7a5b19e` deployed 11:31 UTC) — replaces per-side caches with `_book_by_token`. Phantom-fill backfill applied to live decision log: 3 corrections wrote, dashboard bankroll $1,120.62 → $1,010.62 (truth). Phase 19 design doc LOCKED (`design/phase-19-llm-async-precompute.md`) — async LLM pre-compute, deferred implementation to next session. Self-correction: caught a timestamp-arithmetic error mid-session that produced a false "fix failed" alarm. 537 pytest passes. Operator surfaced architecture-overcomplication concern at session close → architecture-audit phase prompt drafted for next session.

## Format

Each daily file is one markdown note with frontmatter:

```yaml
---
date: YYYY-MM-DD
phase: <current phase>
status: <closed-N | in-progress | blocked>
tags: [session, ...]
---

# YYYY-MM-DD — <one-line headline>

## What shipped today
- ...

## What's next
- ...

## Anti-vibe rule notes
- ...
```

Sessions accumulate. Don't delete past entries — they're the trail of how the project actually evolved (vs how the plan said it would).

## See also

- [[../phases/README|Phase ledger]] — what got done at the macro level
- [[../postmortems/README|Postmortems]] — incident write-ups (different from sessions)
- [[../runbooks/README|Operational runbooks]] — daily operational procedures
