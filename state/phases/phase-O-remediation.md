# Phase O — Remediation

**Status:** OPEN (Session 1 complete 2026-05-17)
**Predecessor:** Phase N forensic audit (PHASE_N_FORENSIC_AUDIT.pdf)
**Opened on operator sign-off:** 2026-05-17 (full plan steps 1-6)

Phase O is the actionable phase after Phase N's investigation. It ships
data-grounded remediations to the bleed identified in Phase N (peak
+$1,235 → −$327 over 45h on 2026-05-15 → 2026-05-17).

## Session roadmap

| session | scope | status |
|---|---|---|
| 1 | Disable M.1a v1, enable SURV canary, keep M.5 active. Bot resume. | **DONE 2026-05-17** |
| 2 | J.2 hour-blocklist redesign (per-tier hours); SURV canary obs | pending (after 1-2d data) |
| 3 | N.5 regime classifier validity test (if obs data motivates) | pending |
| 4 | If bleed continues: Kelly demotion 0.15→0.10 (PDF §7.4) | conditional |
| ... | Phase H/J/L/M defenses stay; strategy class flip is LAST RESORT | |

## Phase O Session 1 deliverables

- Commit `16e8f38`
- `design/O.0-phase-n-m5-persistence-null.md` — M.5 persistence is moot
- `design/O.1-surv-cell-shift-canary.md` — canary spec
- `src/polymarket_bot/strategies/surv_canary_metrics.py` (NEW)
- 11 new tests in `tests/strategies/test_spot_aware_v2_1.py`
- Bot LIVE on VPS at `16e8f38` since 2026-05-17 16:25:24 UTC

## Locked rules for Phase O

1. Every remediation must trace to a falsifiable Phase N finding.
2. No new feature ships without back-testing on n=755 forensic data.
3. No env flip on VPS without a `.envrc` backup + dated comment.
4. L.5 daily-PnL auto-halt stays active throughout (the safety net).
5. If a re-soak day bleeds > −$30 (L.5 trip), HALT and review.

## What unlocks Phase P

- 5-day re-soak with new config showing net-positive PnL
- M.5 actively gating Path-A fires (verify via decision-log abstain count)
- SURV canary not over-firing (verify via WARNING-level log frequency)
- Operator decision on next remediation tier

## Cross-references

- Phase N PDF: `pdfs/PHASE_N_FORENSIC_AUDIT.pdf`
- Phase N ledger: `state/phases/phase-N-forensic-audit.md`
- Session note: `state/sessions/2026-05-17-phase-O-session-1-bot-resumed.md`
- Phase M ledger: `state/phases/phase-M-pre-live-edge-stacking.md` (paused)
