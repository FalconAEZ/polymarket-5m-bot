---
date: 2026-05-19
session: phase-S-session-1
duration_h: 1.5
branch: claude/phase-S-market-maker
base_commit: 9516f39
tags: [session-note, phase-S, kickoff]
---

# Phase S Session 1 kickoff — market-maker bot research + design lock

## What we set out to do

Operator-supplied Phase S prompt: ship a parallel market-maker bot (MMB) modelled on bonereaper's observed mechanics (multi-order maker-limit ladders, 100% BUY orders, both UP and DOWN tokens, deep depths $0.05-$0.20, holds to window resolve). $3k bankroll, parallel to the existing directional bot. 6-session plan.

Session 1 scope: research + design lock + Session 2 prompt. No code.

## What we found

### State verification (before executing)

The operator's prompt named several artifacts I needed to confirm exist before sizing Session 1 deliverables:

| Claimed | Verified |
|---|---|
| Branch base `9516f39` | ✅ `fix(dashboard): honor PMB_STARTING_BANKROLL + BANKROLL_REPLAY_ENABLED` on `claude/phase-P-hard-reset` |
| Phase Q live + killer cell config | ✅ Single commit `599b5ff feat(phase-Q-aggressive): MMD_ABSTAIN_BY_SIDE` — env-flag activated runtime config |
| Bonereaper 30d corpus | ✅ [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](../../runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md) + [runbooks/research/bonereaper-microstructure-30d-2026-05-08.md](../../runbooks/research/bonereaper-microstructure-30d-2026-05-08.md) (n=306,997) |
| "Aligned WR 67.4% n=101,962" | ✅ Cited correctly; the 30d audit produces exactly that number |
| Fresh 2026-05-19 weekly data | ❌ Not on disk at session start; ran `scripts/research/weekly_audit.py` → refreshed (21,630 trades, WR 50.93%, stable) |
| J.7 priors sketch | ✅ [design/bonereaper_blended_priors.md](../../design/bonereaper_blended_priors.md) (257 lines) — exists from Phase J Session 1 |
| "Killer cell +$5.15/tr backtest" | ❌ Phase Q commit message says **+$3.16/tr on n=226** — operator confirmation needed on the +$5.15 figure source |
| "$760k cumulative bankroll" | ❌ $766k is the WEEKLY TRADED NOTIONAL (not bankroll); cumulative wallet PnL ~$700k per J.7 sketch |

The "PROPOSED — pending operator sign-off" prompt header was honored: operator answered two clarifying questions (Phase Q state location: "check obsidian vault" → vault empty for Q → proceed under "author fresh in Session 1"; data refresh: "Pull fresh data as Session 1 task").

### What was already in place

Decision #19 (cloning study abort) was correctly framed in the prompt as NOT a blocker for MMB. The postmortem itself opens the door:

> "If the operator ever wants to revisit market-making as a separate project, the data is on disk: 56,976 labelled fills, 2,015 markets, full P&L reconstructable."

The carve-out from #19 was captured in `memory/project_decisions.md` decision #22 (Phase S build-not-copy carve-out) — does not relitigate #19; defines MMB as a structurally different deployment class.

The J.7 sketch (Phase J Session 1, commit `83fe119`) is the closest existing prior work. J.7 uses bonereaper's aligned-WR table as a Bayesian prior anchor INTO THE DIRECTIONAL BOT. MMB uses the same data corpus as a strategy-class proof point — different consumer, different runtime, different bot. Both can coexist; J.7 stays sleep, MMB ships in parallel.

## What we shipped

### Branch + data

- Cut `claude/phase-S-market-maker` from `9516f39`.
- Refreshed bonereaper 7-day data (`state/research/bonereaper/weekly_{events,trades}_2026-05-19.json`) — direct WR 50.93% on n=21,630, gross +$11,024 on $766k notional. Confirms the 30d baseline (51.7% direct WR) is current within statistical noise.

### Design docs

- `design/S.1-market-maker-bot.md` — full design lock for Sessions 2-6.
  - §1 J.7 vs MMB distinction
  - §1.2 Honest decomposition of bonereaper's edge (aligned vs contrarian vs flat WR — MMB's effective WR will be ≈51.7%, not the headline 67.4%)
  - §1.3 Phase Q link + +$3.16/tr vs +$5.15/tr factual flag
  - §2 Module layout + ladder + sizing + risk caps + exit + restart
  - §3 Backtest plan + cross-validation gate
  - §4 R1-R6 risks (edge non-transferability, cross-side exposure, throttling, capital concentration, Phase Q isolation, capital exposure)
  - §5 Open research items (Polymarket fees, maker semantics, cancel latency, rate limits, NegRisk routing)
  - §6 Sign-off gates
- `design/j7_priors.json` — machine-readable priors for `J7Priors` loader (Session 2).
- `design/j7_priors.md` — human companion + change log + operator-correction notes.

### Memory

- `memory/project_decisions.md` decisions #22 (Phase S carve-out from #19) + #23 (capital exposure addendum: $1k → $3k+$3k = $6k operator-level; HW wallet trigger crossed on both bots).
- `memory/MEMORY.md` index updated to "23 locked decisions".

### Vault

- `state/phases/phase-S-market-maker.md` ledger.
- `state/sessions/2026-05-19-phase-S-kickoff.md` (this file).

## What we did NOT ship this session

- ~~`runbooks/S-mmb-research-2026-05-19.md` (5 open research items)~~ → **CLOSED 2026-05-20** at [runbooks/S-mmb-research-2026-05-20.md](../../runbooks/S-mmb-research-2026-05-20.md).
- `memory/checkpoint_phase_S_session_1.md` — written 2026-05-19, updated 2026-05-20 for $1k pivot.
- `phase-prompts/phase-S-session-2-core.md` — written 2026-05-19, updated 2026-05-20 for $1k pivot + S.1.1 closure.
- PHASE_S_KICKOFF.pdf — deferred to S.1 follow-up. The design + j7_priors + this session note + the project_decisions entries + the S.1.1 runbook are the durable record; a PDF would be a packaging exercise.
- No code shipped (per Session 1 scope = research + design only).

## 2026-05-20 addendum — operator pivots + S.1.1 closure

This session note was authored 2026-05-19. Three pivots landed on 2026-05-20 before Session 2 starts; the note's body is preserved above for the historical record but the *current state* is:

**Pivot 1 — Bankroll: $3k → $1k.** Operator chose $1k for MMB. Matches decision #10 baseline exactly. Decision #23 revised to reflect $1k total operator exposure (decision #12 $2k HW wallet trigger no longer crossed). All risk caps in design §2.4 + Session 2 prompt recalibrated to $1k scale (MAX_INV $25, MAX_GROSS $50, MAX_DAILY_LOSS $50 for live-micro).

**Pivot 2 — Paper is fake for market-makers.** Operator pushback: MMB's queue position + book presence ARE the edge; a simulator that doesn't place real orders cannot reproduce them. Session 5 "shadow soak" replaced with "live-micro soak" at minimum size ($5/level × 3 × 2 = $30 max gross/window). Session 2 backtest reframed as plumbing-only sanity check, not edge predictor. Cross-validation gate widened to ±50% (from ±20%).

**Pivot 3 — Directional bot + all VPS services OFF.** 2026-05-19 20:48 UTC operator halted bot-staging.service via halt.sentinel; 2026-05-20 operator halted + disabled all 6 project services (bot, bot-staging, dashboard-server, litestream, rtt-collector, tg-alerter). VPS is dormant. halt.sentinel written back as belt-and-suspenders stay-off brake. Phase S now ships into a clean VPS — no parallel-bot interference, no shared-Signer concerns to resolve.

**S.1.1 closure.** All 5 Polymarket-mechanics questions answered in `runbooks/S-mmb-research-2026-05-20.md`. 3/5 definitive (post-only semantics, NegRisk-vs-CTF for BTC 5m = CTF, signing path), 2/5 deferred to Session 3 empirical probes (maker fee rate, cancel latency, rate limits). 5 cross-cutting findings surfaced as Session 2 hard requirements: heartbeat-mandatory, post-only-always, neg_risk=False, per-market tick + min size enforcement, in-flight = provisional inventory.

## Open questions for operator review

1. **+$3.16/tr vs +$5.15/tr** — which Phase Q audit slice did the +$5.15/tr figure come from? If it's a different cell (e.g., MMD=MIXED × DOWN × specific |Δ| bucket), I should reference it in the priors table.
2. **Hardware wallet wiring before S.6** — decision #12 is now firmly crossed. Want to schedule HW wallet wiring as part of S.5 or earlier?
3. **Signer wallet split** — directional + MMB on same Signer today. Split before S.6 or keep on one? S.1.1 will surface the answer from the Polymarket fee/auth research.
4. **+$41 directional bot PnL** — for the Session 1 ledger, want to capture this anywhere on-disk (it's currently only in operator framing, not in `state/decisions/` or any session note)?

## Next session

- `phase-prompts/phase-S-session-2-core.md` (next file in this session's deliverables).
- Goal: ship `MarketMakerStrategy` + `LadderPlanner` + `InventoryTracker` + `RiskGate` + `PayoutResolver` + `J7Priors` loader + 30+ tests + backtest harness running on 13-day data.
- Acceptance: ≥30 tests pass, mypy strict + ruff + import-linter green, backtest shows positive $/window on ≥5 of 7 days, cross-validation within ±20% of bonereaper's actual per-day PnL.

## Notes for the next-session agent

- Branch is `claude/phase-S-market-maker`. Stay on it. Don't merge to main yet.
- `design/S.1-market-maker-bot.md` is the locked design — do not re-litigate it in Session 2. If something is wrong, raise a doc fix before changing strategy.
- `design/j7_priors.json` is the priors source for `J7Priors` loader. The runtime fallback path (`state/research/bonereaper/aligned_priors_30d.json`) is the daily-refresh slot — not populated yet; Session 2 builds the refresh script.
- Do NOT touch `bot-staging.service` or any directional-bot state. MMB is fully separate.
- `MM_*` env namespace ONLY. No collisions with `SPOT_AWARE_*` / `MMD_*` / `KELLY_*` env vars used by the directional bot.
