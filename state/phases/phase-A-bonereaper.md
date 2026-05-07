---
title: Phase A — Bonereaper pre-flight audit
date-closed: 2026-05-06
status: closed-abort
result: ABORT (operator chose option A — drop the cloning research stream entirely)
tags: [phase, study, bonereaper, closed, abort]
---

# Phase A — Bonereaper pre-flight audit

## What it was

Pre-flight gate for the parallel bonereaper research stream described in `pdfs/BONEREAPER_STUDY.pdf`. The premise: clone a high-conviction-edge wallet to bootstrap the main bot's strategy. Phase A's job: validate the premise before designing Phases B–G.

Target wallet: **`0xeebde7a0e019a63e6b476eb425505b7b3e6eba30`** (bonereaper).

## What we found

Three independent measurements all failed the locked **60% win-rate gate**:

| Method | Window | Trades | Win-rate | Verdict |
|---|---|---|---|---|
| Polymarket Data API (user-trades, offset-paginated) | last ~3 h (capped at 3,500 rows) | 1,083 resolved | 50.6% | suggestive ABORT |
| Goldsky orderbook subgraph | Apr 28–29, 1.5 d | 0 BTC 5m | n/a | wrong exchange |
| Per-market enumeration (Gamma + Data API combined filter) | last 7 days | **56,972** resolved | **52.65%** (95% CI [52.24%, 53.06%]) | **canonical ABORT** |

Bonereaper IS profitable (~$31k gross over $2.3M weekly notional, ~52.65% win-rate). His edge is real — the 95% CI excludes 50%. But he's a **slim-edge high-volume market-maker**, not the high-conviction directional trader the cloning study assumed.

## Why the ABORT held

Per [[../runbooks/README#anti-vibe-rule-21-no-gate-softening|anti-vibe rule #21]]: gate criteria written before measurement are not retroactively softened. The 60% gate was set in `pdfs/BONEREAPER_STUDY.pdf` p. 9. The measurement came in at 52.65%. Lowering the gate to fit would be exactly the gate-softening the rule prohibits.

## The user's discipline check that actually worked

The first audit pass declared ABORT after 3 hours of data. The user pushed back: *"why dont you check their win rate over 1 week ?"* That's the right discipline check. The 7-day measurement was implemented (via the per-market enumeration recipe) and confirmed — with much higher confidence — the same conclusion.

Lesson: when a data window is narrower than the gate window calls for, **say so loudly** *before* declaring an abort. The 3-hour result was statistically tight (1,083 trades) but rhetorically over-confident given the operator's question presupposed a 30-day frame.

## What survived the abort

1. **The audit pipeline** — `scripts/research/{quick_audit,weekly_audit,_api,_subgraph}.py`. Reusable on any wallet in ~10 min for $0.
2. **The data-source map** — see [[../research/data-sources-map]].
3. **A clean record** of bonereaper's actual strategy shape — high-volume slim-edge market-making.
4. **The `make study-A` gate** — runs the full audit + verifies artifacts.

## What's locked because of this

- [[../decisions/README#decision-19|Decision #19]]: cloning research stream dropped; Phases B–G of `BONEREAPER_STUDY.pdf` not designed.
- The optional 4th `behavioral_mimic` ensemble agent is **out**. Ensemble stays at 3 agents + meta only ([[../decisions/README#decision-5|decision #5]]).
- Main-bot plan (`MASTERPLAN.md` + `RUNBOOK.md` + `pdfs/BUILD_SPEC.pdf`) **unchanged**.

## Artifacts

- `runbooks/study/preflight-decision.md` (project root) — final consolidated decision
- `runbooks/study/weekly-audit.md` — 7-day report
- `runbooks/study/quick-audit.html` — HTML charts from initial pass
- `runbooks/gate-evidence/study-A.txt` — gate evidence
- [[../research/bonereaper-study-postmortem]] — vault postmortem
- `state/research/bonereaper/*` (gitignored) — 56k+ raw fills, 2,015 markets
- Tags: `study-A-final` (commit dbc33a4) and `study-A-abort` (commit 3430d06)

## Connections

- Concept: [[../concepts/window-delta]] — the canonical signal we use *instead* of trying to clone bonereaper
- Concept: [[../concepts/tier-3-deterministic]] — the strategy that doesn't depend on any cloning target
- Research: [[../research/audit-pipeline-recipe]] — how the audit pipeline works (reusable)
- Research: [[../research/data-sources-map]] — Polymarket data source taxonomy
- Postmortem: [[../research/bonereaper-study-postmortem]]
- Session: [[../sessions/2026-05-06]]
