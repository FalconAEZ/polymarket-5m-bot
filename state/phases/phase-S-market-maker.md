---
title: Phase S — Market-Maker Bot (MMB)
status: in_progress
session: 1 of 6
started: 2026-05-19
branch: claude/phase-S-market-maker
base: 9516f39 (claude/phase-P-hard-reset HEAD)
tags: [phase-S, market-maker, bonereaper, parallel-bot]
---

# Phase S — Market-Maker Bot (MMB)

## Why this phase

The directional strategy class has reached its expressive limit: Phase Q's killer-cell concentration (MMD=MIXED × side=DOWN at +$3.16/tr on n=226 per commit `599b5ff`) is the surgical end-state for single-fire taker bots. The next structural strategy class is market-making — multi-order maker-limit laddering on BOTH outcome tokens — exemplified by the bonereaper wallet (51.7% direct WR, +$0.66/trade, $234k gross over 30d on $12.1M notional).

Phase S ships MMB as a PARALLEL bot:
- New service unit (`bot-mm.service`), separate from `bot-staging.service` (the directional bot).
- New env namespace (`MM_*`), separate bankroll envelope ($3k).
- Decision-log + dashboard surface separated.
- Directional bot stays live throughout Phase S.

## Sessions

| Session | Scope | Duration | Status |
|---|---|---|---|
| **S.1** | Research + design lock | 3-5d | **CLOSED 2026-05-19, updated 2026-05-20 for $1k pivot** |
| **S.2** | Core strategy + tests + backtest (plumbing-only) | 5-7d | **CLOSED 2026-05-20: 54 tests green + backtest +$1,586/7d sim PnL + 14.3% MMB/BR ratio** |
| S.3 | Order management + paper runner (shakedown-only) | 5-7d | not started |
| S.4 | Dashboard + safety circuits + Telegram kill-switch | 5d | not started |
| S.5 | **Live-micro deploy** ($5/level, $50 max gross, $50/day loss cap) — 7-day live soak | 7d | not started |
| S.6 | Scale-up to full $1k bankroll caps + 5-day soak | 5d+ | not started |

**Pivot 2026-05-20:** original S.5 "VPS shadow deploy" replaced with "live-micro deploy" — operator pushback: paper/shadow cannot validate market-maker mechanics because MMB's queue position + presence are part of the edge. Live-micro at minimum size ($5/level × 3 levels × 2 sides = $30/window max gross) is the smallest configuration that produces honest measurement.

## Session 1 deliverables (this session)

- ✅ `claude/phase-S-market-maker` branch cut from `9516f39`.
- ✅ `state/research/bonereaper/weekly_*_2026-05-19.json` refreshed (direct WR 50.93% on n=21,630 — confirms 30d baseline stable).
- ✅ `design/S.1-market-maker-bot.md` — design lock for Sessions 2-6.
- ✅ `design/j7_priors.json` + `design/j7_priors.md` — per-tier aligned-WR priors.
- ✅ `memory/project_decisions.md` updated with decisions #22 (Phase S carve-out from #19) + #23 (capital exposure addendum to #10/#12).
- 🟦 `state/sessions/2026-05-19-phase-S-kickoff.md` — session note (writing now).
- 🟦 `memory/checkpoint_phase_S_session_1.md` — memory checkpoint.
- 🟦 `phase-prompts/phase-S-session-2-core.md` — next-session prompt.
- 🟦 `runbooks/S-mmb-research-2026-05-19.md` — 5 open research items (S.1.1).
- 🟦 PHASE_S_KICKOFF.pdf — deferred to Session 1 follow-up if context tight.

## Key facts captured this session

| Item | Value |
|---|---|
| Bonereaper 30d (n=306,966) direct WR | 51.7% |
| Bonereaper 30d aligned-only WR | **67.4%** on n=101,962 |
| Bonereaper alignment WR gap | +30.9 pp |
| 7-day refresh (2026-05-19) direct WR | 50.93% on n=21,630 (consistent) |
| Phase Q killer cell ($/trade) | **+$3.16/tr on n=226** (NOT +$5.15/tr as in prompt) |
| MMB bankroll (LOCKED 2026-05-20) | $1,000 (decision #10 baseline aligned) |
| Operator-level exposure post-S.6 | $1k (directional bot OFF as of 2026-05-19 20:48 UTC) |
| HW wallet trigger (decision #12, $2k) | NOT crossed; no HW dep for S.6 |

## Open items for S.1.1 (close this session)

1. Polymarket maker fee structure (NegRisk vs CTF).
2. Maker-only limit semantics (post-as-maker priority).
3. py-clob-client cancel latency.
4. CLOB API rate limits for limit-place specifically.
5. NegRisk vs standard CTF routing for BTC 5m today.

## Related

- [design/S.1-market-maker-bot.md](../../design/S.1-market-maker-bot.md)
- [design/j7_priors.json](../../design/j7_priors.json) + [design/j7_priors.md](../../design/j7_priors.md)
- [design/bonereaper_blended_priors.md](../../design/bonereaper_blended_priors.md) (J.7 sketch, different deployment class)
- [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](../../runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md) (priors source)
- [runbooks/study/weekly-audit.md](../../runbooks/study/weekly-audit.md) (2026-05-19 freshness check)
- [state/research/bonereaper-study-postmortem.md](../research/bonereaper-study-postmortem.md) (Phase A abort context)
