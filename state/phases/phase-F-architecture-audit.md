---
title: Phase F — Final-stage architecture audit + convergence
tags: [phase, optimization, architecture-audit]
status: items-1-2-shipped-soak-underway
---

# Phase F — Final-stage architecture audit + convergence

The curation pass that converges the 4-day experiment surface into the simplest profitable bot. Not another optimization phase.

## Decision (operator-signed via auto-resume "execute")

Accept the prompt's audit (`phase-prompts/phase-F-final-stage-architecture-audit-2026-05-13.txt`) verbatim:

**KEEP**: spot_aware family, spot_aware_v3 + regime detector, Phase 11.A phantom-fill defense, Phase 14 tier-gate infra (dark), Phase 15 regime-gate infra (dark), Phase 15.5 truth-pass + corrections overlay, Phase 18B `meta_outcome` telemetry, PaperRunner defense-in-depth, wide_fire's per-asset_id pattern lesson.

**REMOVE** (env-disabled, code intact for revival): `ENSEMBLE_MODE=gate`, `wide_fire` as production base, `SPOT_AWARE_AGGRESSIVE_MODE=1`.

**SIMPLIFY** (paused, not deleted): Phase 16.B every-window router promotion, Phase 19 LLM async pre-compute implementation, Phase 14 + 15 kill-switches.

## Items shipped 2026-05-12

- **Item 1** — Operator review + sign-off. ✅
- **Item 2** — Strategy cut deployed at HEAD `d1510bd`, MainPID `581764` since 12:25:33 UTC. ✅
  - `DEFAULT_STRATEGY_NAME` flipped to `spot_aware_v3` in `scripts/run_paper.py`
  - VPS `.envrc` updated (4 surgical edits, `# PHASE-F 2026-05-13` markers, rollback = one-line revert)
  - Backup at `.envrc.phase-F-backup-20260512-122500`
  - +5min check: see session note

## Items pending

- **Item 3** — 48-72h spot_aware_v3 soak with PROMOTE / ROLLBACK criteria. Passive; check at +48h via `scripts/four_day_audit.py`. Audit doc → `phase-prompts/phase-F-3-spot-aware-v3-soak-audit-2026-05-14.txt`.
- **Item 4** — Phase 6 readiness review (deferred Phase 24 from master plan). Gated on Item 3 PROMOTE + extended soak sample.

## Production architecture after this cut

```
SpotAwareStrategyV3 (regime-aware base)
    │  fires when: |Δ_bps| ≥ delta_min ∧ regime == "trending"
    │              ∧ priors hit + EV ≥ ev_min ∧ tier ∉ {<15%, 85-100%}
    ▼
PaperRunner (Phase 11.A phantom defense + instant-settle + orphan-recovery
              + post-hoc gamma retry + settled_correction overlay)
    ▼
DecisionLog (state/decisions/) → dashboard-server v3 (apply_settled_corrections)
```

No EnsembleWrapper. No wide_fire base. No router shadow in fire path. All removed-from-production code stays in repo.

## Promote / rollback criteria (Item 3 gate)

PROMOTE if over 48-72h:
- `rolling_wr_at_72h >= 0.52`
- `daily_pnl_min >= -10.0`
- `fires_per_day >= 50`
- `queue_overflow_incidents == 0`

ROLLBACK if:
- WR < 0.45 over 48h
- OR daily_pnl < −30 on any day
- OR fires_per_day < 20

Rollback path: `ssh ... 'cd /home/ops/polymarket-5m-bot && cp .envrc.phase-F-backup-20260512-122500 .envrc && sudo systemctl restart bot-staging.service'`.

## What this phase explicitly does NOT advance

- ❌ Phase 19 implementation (latency problem dissolves when LLM exits fire path; design doc kept as research)
- ❌ Phase 16.B promotion (router depends on LLM signal; paused)
- ❌ Any locked decision (#4 / #5 / #6 / #9 / #10 all stand)
- ❌ Phase 6 launch (gated on Item 3 PROMOTE + Phase 23 stat-sig)

## Cross-phase impact

If Item 3 PROMOTES, **Phases 19, 20, 21, 22, 25 ALL become deferrable.** Phase 6 (live trading) becomes the next concrete phase.

## Related

- `phase-prompts/phase-F-final-stage-architecture-audit-2026-05-13.txt` — source prompt
- `scripts/four_day_audit.py` — the audit script
- `memory/checkpoint_phase_F.md` — durable cross-session pointer
- `state/sessions/2026-05-12-phase-F-arch-audit-execute.md` — session note
