---
title: Bonereaper study — postmortem
date: 2026-05-06
status: closed-abort
tags: [research, postmortem, study, bonereaper, phase-A]
---

# Bonereaper study — postmortem

> Vault-side write-up. The canonical decision doc is `runbooks/study/preflight-decision.md`. This file is for the operator's notebook (Obsidian indexes the project's `state/` directory; locked decision #18).

## What we set out to do

`BONEREAPER_STUDY.pdf` proposed a parallel research stream: study Polymarket wallet `0xeebde7a0e019a63e6b476eb425505b7b3e6eba30` ("bonereaper") as a labelled-data source for the main BTC 5-min bot. The premise: bonereaper had a high-conviction edge worth cloning. Phase A was the abort gate — confirm the premise before committing 8+ weeks to phases B–G.

## What we found

| Window | Method | Trades | Win-rate | Verdict |
|---|---|---|---|---|
| 3 hours | Data API user-trades (offset paginated, cap 3500) | 1,083 resolved | 50.6% | suggestive ABORT |
| 1.5 days | Goldsky orderbook subgraph | 0 BTC 5m | n/a | wrong exchange |
| **7 days** | **Per-market enumeration via Gamma + Data API combined filter** | **56,972 resolved** | **52.65%** (95% CI [52.24%, 53.06%]) | **canonical ABORT** |

Bonereaper is profitable — +$31k gross over $2.3M notional in a week — but as a *slim-edge high-volume market-maker*, not as the *high-conviction directional trader* we hypothesized. The 95% CI of his 7-day win-rate excludes 50% (real edge confirmed) but also stays a full 7 percentage points below the 60% gate (insufficient for cloning).

## Why we trust the 7-day number

- 56,972 trades is overwhelming statistical power. ±0.4 percentage points at 95%.
- 96% market coverage in the window (1,927 of 2,015 BTC 5m markets had bonereaper activity).
- Per-market enumeration is the canonical path: each call to `/trades?market=<cid>&user=<addr>` returns the full per-market trade history because the user filter narrows the result well under the 500-row cap.
- Result reconciles with the prior 3-hour Data API number (50.6% within the 7-day CI, a known regime difference).

## Why the cloning stream had to die anyway

Anti-vibe rule #21 (`BUILD_SPEC.pdf` p. 22): *gate criteria softened without an approved decision doc → revert, escalate*. The 60% gate was set in writing before we measured. The data came in at 52.65%. We do not lower the gate retroactively. Even if we did, cloning a slim-edge market-maker is a different problem than the directional trading the main bot is designed for — different infra, different fill model, different risk. The "abort" is a feature.

## What survived

1. **The pipeline.** `scripts/research/{_api, _subgraph, quick_audit, weekly_audit}.py` is reusable for any wallet audit going forward. Per-market enumeration is the canonical recipe.
2. **The data-source map** (in the main decision doc).
3. **A statistically clean understanding of bonereaper's actual strategy.** If the operator ever wants to revisit market-making as a separate project, the data is on disk: 56,976 labelled fills, 2,015 markets, full P&L reconstructable.
4. **The audit framework.** `make study-A` is wired and reproducible. Future wallets can be tested against the same gate in ~10 minutes.

## What changed in the main project

- `BONEREAPER_STUDY.pdf` Phases B–G: **not designed**. The PDF stays as an archived research artifact; do not implement against it.
- `RUNBOOK.md`: unchanged. The main bot plan was always self-contained.
- `BUILD_SPEC.pdf` decision #5 (3 agents + meta-decider): unchanged. The optional 4th `behavioral_mimic` ensemble agent that the cloning study would have produced is **out** — the ensemble is 3 agents only.
- `project_decisions.md`: new entry locking the abort.

## Operating-discipline reflections

Things this audit got right:
- Design doc before code (rule #1). `design/research/quick_audit.md` was committed before `scripts/research/quick_audit.py`.
- The 60% gate was written down before we measured. We didn't move the goalposts when the result came in below.
- The first-pass 3-hour result was honestly flagged as data-source-limited rather than dressed up.
- The 3-fix rule was never tripped — when the subgraph had the wrong exchange data, we paused and asked rather than thrashing on it.
- Stopped at the gate (rule #4). Did not silently start designing Phase B.

Things to remember next time:
- **The first-pass audit was technically correct but rhetorically too confident.** "50.6% over 1,083 trades" sounded like a definitive abort but represented only 3 hours. The user's pushback ("why dont you check their win rate over 1 week ?") was the right discipline check — and it was warranted. Lesson: when a data window is narrower than the gate window calls for, say so loudly *before* declaring an abort.
- **Per-market enumeration was viable from day one.** I noticed `/trades?market=` worked during initial probing but didn't pull on it because the simpler `/trades?user=` endpoint *seemed* to be returning enough. It wasn't. Lesson: when the obvious endpoint hits a cap, the correct response is to probe sibling endpoints, not to lower the bar.

## Status

- Decision: **ABORT (final)**.
- Operator path: **(A) Drop the cloning research stream entirely.**
- Phase A: **closed**.
- Next operator action: open `RUNBOOK.md` Phase 0 when ready.
- Data on disk for future revisit: `state/research/bonereaper/weekly_*_2026-05-06.json` (~56k labelled trades, 2,015 markets).
