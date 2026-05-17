# 2026-05-17 — Phase N Session 2 (PDF study + falsifiers)

## Context handoff

Continued same UTC day from Session 1. Operator asked to "make a full pdf
study please of what went wrong going from +1.2k+ profit to below −300$
based on this current phase that we are in now and previous phases."

Scope locked via 3-question dialog (synthesis + M.5/M.1a falsifiers,
ranked Phase O recommendation, jovial-hermann-7e103f worktree).

## Work delivered

### Extended forensic audit (N.3a/b/c/d)
- M.5 activation simulator (replay all 5 days, two restart modes)
- M.1a v1 inversion test (tier × regime cross-tab + |Δbps| proxy on n=755)
- Fire-stream gap detection (restart proxy)
- Daily PnL × tier × side breakdown
- Re-ran `phase_n_forensic_audit.py` → re-wrote
  `runbooks/research/phase-N-forensic-output-2026-05-17.txt`

### Chart pipeline (NEW)
- `scripts/research/phase_n_charts.py` — 14 PNGs via matplotlib
- Output: `state/research/phase-N-charts/{01..14}_*.png`

### PDF deliverable (NEW)
- `pdfs/build_phase_n_forensic_audit_pdf.py` — reportlab builder, dark-terminal
  style matching `build_phase_g_edge_discovery_pdf.py`
- `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` — 22 pp, 1.3 MB, 14 embedded charts

## Falsifier results (the new evidence)

### F1: M.5 design is CORRECT — but shipped 3 days late
- 237 Path-A fires across 5 days
- M.5 first crossed n≥20 threshold at **2026-05-14 05:55:25Z**
- WITHOUT restart resets (idealized): would have been active for 217 fires,
  abstained 105/107, counterfactual **+$352.92 avoided**
- WITH restart resets at gaps >60min (bot-actual): active for 157, abstained
  59, counterfactual **+$330.51 avoided**
- In M.5's actual 58-min live window: 1 Path-A fire (the M.5-would-have at
  11:31Z, before M.5 ship at 11:44Z) — M.5 was active (n=20, WR=70.0%,
  thr=75.8%, ABSTAIN), counterfactual saved $39.34

### F2: M.1a v1 inversion contradicted on n=755
- Annotated subset (n=83): chop n=23 WR 60.9% (+$31) vs mixed n=58 WR 44.8%
  (−$296) — suggestive inversion
- |Δbps| proxy on n=755: chop-like (|Δ|<2.5) WR 35.7%, flat (2.5-5) WR 33.8%,
  active (5-10) WR 60.5%, trending (10+) WR 71.4% — **monotonically increasing**
- The M.1a vol-ratio classifier and |Δbps|-based edge structure don't align
- M.1a v1 was activated on n=23 of evidence — too small to ship

### F3: 19 likely restarts in 5 days
- Fire-stream gaps >30 min: 19 events
- Notable: 2026-05-17 02:46:44Z = 177-min gap (operator's manual L.5 sentinel clear)
- Weekend has 5+ restarts on each of 05-16/17 (Phase M layer ships)
- Operational implication: M.5 / M.1a v0 rolling state lost on every restart

### F4: Tier 70-85% Path A = the slow secondary bleeder
- 5-day net: 237 fires, WR 74.3%, −$368
- Daily Path-A: 05-15 −$151 / 05-16 −$66 / 05-17 **−$325**
- Break-even ~77.5%; the bot's 74.3% sits 4pp below

### F5: Tier 30-50% UP/DN daily decomposition shows multi-cell drift
| date | 30-50% UP | 30-50% DN | 70-85% DN | total |
|---|---|---|---|---|
| 05-13 | +$63 | +$302 | +$132 | +$497 |
| 05-14 | −$72 | +$183 | +$42 | +$153 |
| 05-15 | +$138 | −$21 | −$151 | −$35 |
| 05-16 | −$190 | −$332 | −$66 | −$587 |
| 05-17 | −$86 | +$56 | −$325 | −$355 |

## Honest pushback in the PDF

- L1: 4.2-day window is statistically small; can't tell regime-mean-reversion
  from structural break
- L2: No spot tick capture; M.1a vol-ratio re-validation requires data we
  don't have; |Δbps| proxy is a directional approximation
- L3: M.2 v0 annotated only 3 fires (all `too_thin`) before halt — un-evaluable
- L4: M.5 verdict comes from simulator, not production observation
- L5: Phase N assumes the current shipped config as baseline; doesn't validate
  alternative pathways (e.g., what if cap=2 had stayed)

## Phase O ranked recommendation (PDF §7)

1. PRIMARY: clear sentinel, re-resume with **M.5 active + M.1a v1 disabled**
2. SECONDARY: ship M.5 window persistence (small src/ change + tests)
3. TERTIARY: extend J.2 hour-blocklist to tier 30-50% bleed hours
4. NOT YET: Kelly demotion 0.15→0.10 (variance-only; not edge-restoring)
5. NOT YET: strategy class flip (discards Phase H/J/L/M working defenses)

Expected 5-day PnL improvement: floor +$355 (M.5 alone) to point +$1,229
(if hour-of-day pattern fully holds).

## Bot state — UNCHANGED

- HEAD `e72142c` on `claude/jovial-hermann-7e103f`
- bot-staging.service `inactive`
- halt.sentinel reason `operator-cooldown`
- No commits this session — 7 untracked files (audit script, chart script,
  PDF builder, 14 PNGs, PDF, vault entries) pending operator review

## Files written this session (additive to Session 1)

- `scripts/research/phase_n_forensic_audit.py` (EXTENDED — added N.3a/b/c/d)
- `scripts/research/phase_n_charts.py` (NEW — 400 LOC)
- `pdfs/build_phase_n_forensic_audit_pdf.py` (NEW — 460 LOC)
- `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` (NEW — 22 pp, 1.3 MB)
- `state/research/phase-N-charts/*.png` (NEW — 14 files)
- `state/sessions/2026-05-17-phase-N-session-2-pdf-study.md` (this file)

## Next session

Operator decides:
- Accept PDF + start Phase O on the ranked recommendation? OR
- Do N.5/N.6/N.7 (regime classifier validity + shift detection + Kelly
  counterfactual) before any Phase O code?

The PDF's §6 hypothesis-attribution table marks H6 (basis broke) un-testable
and N.5/N.6/N.7 as Future Work; Phase O can start without them but they'd
raise confidence on the M.1a v1 disable decision.
