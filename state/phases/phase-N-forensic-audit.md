# Phase N — Forensic Audit

**Status:** OPEN (Session 1 complete 2026-05-17)
**Predecessor:** Phase M (PAUSED — 5 M.* layers live, bot halted)
**Successor:** Phase O — remediation (not yet scoped)
**Opened on prompt:** `phase-N-forensic-audit-2026-05-17.txt`

Investigation-only. No code ships to the bot. Bot stays halted via
`state/halt.sentinel` (reason `operator-cooldown`) until Phase O.

## Mission

Investigate the 2026-05-15 15:40Z → 2026-05-17 12:43Z bankroll bleed
($2,235 → $673; -$1,562; -70% peak-to-trough) and determine why the
five Phase M edge-defense layers (L.5, M.1a v0+v1, M.5, M.2 v0) did
not stem it. Output a forensic report and a Phase O remediation plan.

## Sub-tasks

| step  | description                                                    | status            |
|-------|----------------------------------------------------------------|-------------------|
| N.0   | Audit infrastructure setup (data pull, audit script extension) | DONE (Session 1)  |
| N.1   | Peak-to-floor forensic                                         | DONE (Session 1)  |
| N.2   | Tier 30-50% deep dive                                          | DONE (Session 1)  |
| N.3   | Feature audit — did each M.* layer do its job?                 | PARTIAL Session 2 (M.5 + M.1a v1 falsifiers; M.2 unevaluable) |
| N.4   | Feature interaction matrix                                     | pending Session 3 |
| N.5   | Regime classifier validity test                                | pending Session 2-3 |
| N.6   | Volatility + regime shift detection                            | pending Session 3 |
| N.7   | Strategy class counterfactual (vanilla v2, $5-flat, Kelly 0.10) | pending Session 3-4 |
| N.8   | Synthesis + Phase O remediation plan                           | pending Session 4 |

## Session roadmap

- **Session 1 (DONE 2026-05-17)** — N.0 + N.1 + N.2; vault + ledger; operator review.
- **Session 2 (proposed)** — N.3 (M.* feature audit) + N.2-followup (SURV cell decomposition).
- **Session 3 (proposed)** — N.5 + N.6 (regime validity + shift detection).
- **Session 4 (proposed)** — N.7 + N.8 (counterfactuals + Phase O plan).
- **PDF deliverable** — `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` after Session 4.

## Session 1 outputs

- [`scripts/research/phase_n_forensic_audit.py`](../../scripts/research/phase_n_forensic_audit.py) (NEW; extended in Session 2)
- [`runbooks/research/phase-N-forensic-output-2026-05-17.txt`](../../runbooks/research/phase-N-forensic-output-2026-05-17.txt)
- [`runbooks/research/phase-N-forensic-summary.md`](../../runbooks/research/phase-N-forensic-summary.md)
- [`state/sessions/2026-05-17-phase-N-kickoff.md`](../sessions/2026-05-17-phase-N-kickoff.md)

## Session 2 outputs (the PDF study)

- [`scripts/research/phase_n_charts.py`](../../scripts/research/phase_n_charts.py) (NEW; 14-chart matplotlib pipeline)
- [`pdfs/build_phase_n_forensic_audit_pdf.py`](../../pdfs/build_phase_n_forensic_audit_pdf.py) (NEW; 460 LOC reportlab builder)
- [`pdfs/PHASE_N_FORENSIC_AUDIT.pdf`](../../pdfs/PHASE_N_FORENSIC_AUDIT.pdf) (NEW; **22 pp / 1.3 MB / 14 charts**)
- [`state/research/phase-N-charts/`](../research/phase-N-charts/) (NEW; 14 PNGs)
- [`state/sessions/2026-05-17-phase-N-session-2-pdf-study.md`](../sessions/2026-05-17-phase-N-session-2-pdf-study.md)

Falsifier headline: **M.5 worked correctly but shipped 3 days late** (would
have saved $330-$353 over 5 days). **M.1a v1 inversion contradicted on n=755**
(|Δbps| proxy says chop-like loses, not wins). 19 likely restarts erode any
rolling-state defense.

## Locked rules for Phase N

1. No bot code changes; bot stays halted via halt.sentinel.
2. No env flips on VPS.
3. No restart of bot-staging.service.
4. Phase N script lives under `scripts/research/` (research-only, not in
   bot import-graph; CI gates don't apply).
5. Investigate before deciding. Per N-P7: resist "just ship a fix"
   mid-forensic.
