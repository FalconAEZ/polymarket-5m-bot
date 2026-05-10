---
title: Phase 13 — fill-rate audit + tractable price-limit lift
status: NULL result, closed 2026-05-10. Operator-confirmed option (1) defer to Phase 14. No code shipped. Commit `d4f3fde` on `claude/jovial-hermann-7e103f` carries the audit script + session note for the trail.
tags: [phase, fill-rate, audit, null-result]
---

# Phase 13 — fill-rate audit + tractable price-limit lift

> First executable phase from the [[../sessions/2026-05-11-phase-12-master-plan|Phase 12 master plan]]. Goal was to add `SPOT_AWARE_LIMIT_LIFT_BPS` env to raise fire-time `price_limit` by N basis points so the bot fills the tractable subset of unfilled fires. The audit closed it as a null result.

## Why this phase existed

Operator-flagged in the [[../sessions/2026-05-10-phase-5-settle-resolution-bug|2026-05-10 settle-resolution session]]: "more than fifteen trades that has not been filled." Phase 13 was to bucket the never-fills by ask-gap and ship a kill-switched lift env for the tractable bucket.

## What the audit measured

`scripts/audit_unfilled_v2.py` (committed) joins `kind=fired` and `kind=settled` records by decision_id, classifies each as `filled_at_fire` / `filled_at_settle` / `never_filled` / `no_settle`, and bucket the never-filled fires by `gap = best_ask - price_limit`:

| bucket | n | counterfactual W | 95% CI (Wilson) | verdict |
|---|---:|---:|:---:|:---|
| **0-1c** | 0 | n/a | — | **bucket EMPTY — no lift target** |
| **1-2c** | 39 | **46.2%** | [31.6, 61.4] | **FAILS the ≥50% gate** |
| 2-5c | 0 | — | — | empty |
| >5c | 0 | — | — | empty |
| floor_guard | 12 | 66.7% | [39.1, 86.2] | leave alone — phantom-fill defense |

On the 3 days of available VPS data (2026-05-08, 09, 10 → n=467 fires aggregate; the 1-2c bucket is from 2026-05-10's wide_fire run, the only homogeneous dataset).

## Why null

1. The 0-1c bucket is **empty** — the price grid doesn't produce gaps in that range. Spot-derived limits either land ~2¢ above the ask (taker-cross) or ~1-2¢ below it (rest, miss).
2. The 1-2c bucket counterfactual W = **46.2%**, BELOW the bot's 52.0% overall WR. The market correctly priced our side as worse-than-even on these windows. Forcing them in via `SPOT_AWARE_LIMIT_LIFT_BPS=100` would have diluted WR ~6pp on the marginal trades.
3. The floor_guard subset is the correct-refusal class (the phantom-fill defense from the 2026-05-09 incident). Lifting these would re-enable the bug.

## Operator decision

**Option (1) — defer Phase 13, advance to Phase 14 in same session.** Per the Phase 13 prompt's session boundary (c): "Audit shows no tractable subset → write null result, defer Phase 13, advance to Phase 14. 🛑 (this is success, not failure — honest pushback in action)."

## Deliverables

- [[../sessions/2026-05-11-phase-13-fill-rate-lift|Session note 2026-05-11-phase-13-fill-rate-lift.md]] — full audit doc + verdict.
- `scripts/audit_unfilled_v2.py` — re-runnable audit, ruff + mypy --strict clean. Re-use it if a future operator wants to re-evaluate after 7+ days of post-gate-mode data.

## What's NOT shipping

- No `SPOT_AWARE_LIMIT_LIFT_BPS` env var.
- No code change to `spot_aware_v2.py` or `ensemble_wrapper.py` for lift.
- No scaffold-with-default=0 either — anti-vibe rule says don't build for hypothetical future requirements. Audit is cheap to re-run.

## Cross-references

- Master plan: [[../sessions/2026-05-11-phase-12-master-plan]] §4 → Phase 13
- Memory: `memory/checkpoint_phase_13_null.md`
- Commit: `d4f3fde` on `claude/jovial-hermann-7e103f` + `claude/hopeful-mcnulty-b81585`
