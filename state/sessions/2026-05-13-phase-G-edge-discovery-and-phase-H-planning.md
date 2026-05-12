---
title: Phase G full edge discovery + Phase H v2.1 planning
date: 2026-05-13
phase: G + H.1 + H.FINAL
status: complete (analysis-only); H.2 code work deferred to next session
---

# Phase G full edge discovery + Phase H v2.1 planning

Marathon analytical session continuing from the Phase F cut chain (2026-05-12).
Bot stayed on v2 (PHASE-F-4, MainPID 593311, ActiveEnter 15:42:38 UTC 2026-05-12)
throughout — read-only research session, no restarts.

## What shipped

### Phase G — Full edge-discovery deep dive

**Headline:** the bot has **zero edge** in its 5-day production universe (633 settled fires, exactly 50.0% WR, -$18.96 net). BUT one statistically-real winning cell exists that v2 currently **rejects**: tier 30-50% × |Δ_bps|<5, n=83, 48% WR, **+$0.65/trade, +$54.17 total** (the asymmetric payoff carries it).

Deliverables (commit `5801c41`, `2f68748`, `397d876`):
- [scripts/build_edge_dataset.py](scripts/build_edge_dataset.py) — 635 fires × 17 dimensions, truth-corrected
- [scripts/analyze_edge_full.py](scripts/analyze_edge_full.py) — single-dim + cross-tab + counterfactual + Monte Carlo
- [scripts/build_phase_g_charts.py](scripts/build_phase_g_charts.py) — 5 matplotlib charts
- [scripts/analyze_kelly_compounding.py](scripts/analyze_kelly_compounding.py) — Kelly + compounding + multi-fire + 3 scenarios
- [pdfs/build_phase_g_edge_discovery_pdf.py](pdfs/build_phase_g_edge_discovery_pdf.py) — reportlab builder
- [pdfs/PHASE_G_EDGE_DISCOVERY.pdf](pdfs/PHASE_G_EDGE_DISCOVERY.pdf) — **629K, 14 sections**, on operator's Desktop
- [state/research/phase-G-fires-dataset.csv](state/research/phase-G-fires-dataset.csv) — master dataset
- [state/research/phase-G-analysis.json](state/research/phase-G-analysis.json) — structured findings
- [state/research/phase-G-kelly-analysis.json](state/research/phase-G-kelly-analysis.json) — Kelly trajectories
- 8 matplotlib PNGs at `state/research/phase-G-charts/`
- [runbooks/research/phase-G-edge-discovery-2026-05-12.md](runbooks/research/phase-G-edge-discovery-2026-05-12.md) — markdown source
- [phase-prompts/phase-G-full-edge-discovery-2026-05-12.txt](phase-prompts/phase-G-full-edge-discovery-2026-05-12.txt)

### Phase G — Kelly + compounding addendum

Operator-directed: factor in confidence per trade + Kelly sizing + multi-fire + cumulative compounding + $10k aspirational bankroll scenario. Three Monte Carlo scenarios with bet caps ($500/$1000) for Polymarket liquidity realism:

| Scenario | Start | WR | Fires/day | +30d median | +90d median |
|---|---|---|---|---|---|
| Conservative | $1,006 | 58.2% (real backtest pool n=91) | 16 | **$34,851** | **$116,115** |
| Aspirational | $10,000 | 55% target | 32 (multi-fire 2×) | $82,972 | **$300,934** |
| Downside | $1,006 | 50% (regression) | 16 | $2,084 | $10,565 (P_ruin=97.4%) |

Downside shows the Kelly variance signature: median grows but most paths hit catastrophic drawdown. That's the case for **0.10× fractional Kelly** (not 0.25×) in production.

### Phase H — v2.1 implementation planning (3 PDFs, 2 prompts)

The pivot session: from "the bot has no edge" to "the bot is firing in the wrong cells; v2.1 fixes that."

**Three planning artifacts on the operator's Desktop:**
- [pdfs/PHASE_H_v2_1_IMPLEMENTATION.pdf](pdfs/PHASE_H_v2_1_IMPLEMENTATION.pdf) — strategic plan (17K, 10 sections)
- [pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf](pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf) — **engineering spec (39K, 18 sections, 22 tests, 14 past-incident defenses)**
- [phase-prompts/phase-H-2-code-v2_1-2026-05-13.txt](phase-prompts/phase-H-2-code-v2_1-2026-05-13.txt) — next-session prompt (15K)

**Two architectural findings from reading actual source** that the H.1 strategic plan missed:
1. **Bankroll lives dashboard-side** (`dashboard/bankroll.py::load_bankroll`). PaperRunner doesn't track it. Spec §5 adds a `BankrollTracker` to PaperRunner with replay-from-JSONL on startup.
2. **Multi-fire requires PaperRunner changes**, not just a new strategy. Singular `pending_decision` at `runner.py:448` blocks 2nd fire. Spec §6 details the `_RunnerState` refactor to `pending_decisions: list[PendingDecision]` with backward-compat property.

### Edges inventory (final, from PHASE_H_v2_1_IMPLEMENTATION.pdf §2)

**Confirmed winners (5):** tier 30-50%×|Δ|<5 (W1), tier 70-85% (W2), regime=trending (W3), EV ∈ [0.05, 0.20) (W4), Δ ≠ 0 (W5).
**Confirmed losers (6):** Δ=0 (L1), EV ∈ [0.02, 0.05) (L2), tier 50-70% ✓already rejected (L3), tier 85-100% ✓already rejected (L4), wide_fire+ensemble ✓already removed (L5), aggressive_mode ✓already off (L6).
**Suggestive (2):** hour-of-day, spot-direction — deferred for more data.
**Architectural (4):** Kelly sizing, multi-fire, compounding, tier-specific Δ floor — all NEW in v2.1.

### v2.1 filter changes (4)

- **CH1** Reject Δ_bps = 0 (eliminates 187-fire loser cluster)
- **CH2** Reject EV ∈ [0.02, 0.05) (eliminates 77-fire loser cluster)
- **CH3** Tier-specific Δ floor: 0 bps for tier 15-30% + 30-50%, 5 bps for tier 70-85%
- **CH4** Optional regime gate (defer to operator Q2; default OFF)

### v2.1 sizing changes (Kelly + compounding)

- **CH5** Per-trade size = clamp(bankroll × kelly_mult × kelly_f, min=$1, max=$500)
  where kelly_f = max(0, (p_win − price) / (1 − price)), kelly_mult = 0.10 default
- **CH6** Live bankroll tracking via BankrollTracker in PaperRunner

### v2.1 multi-fire changes

- **CH7** Lift `fired_for_window` invariant for v2.1
- **CH8** Cap at 2 fires per window (operator Q3; default 2)

## Open questions for operator (Q1-Q5)

Before H.2 code begins:

| Q | Question | Default |
|---|----------|---------|
| Q1 | Hour-of-day gate (S1)? | NO (sample thin) |
| Q2 | Regime gate (W3)? | A: no gate (start simple) |
| Q3 | Multi-fire cap? | 2 per window |
| Q4 | Kelly multiplier? | 0.10× (smoother trajectory) |
| Q5 | Live-trading promotion threshold? | $2k (locked decision #12) |

## Commit chain

`5801c41` (Phase G dataset + analysis + baseline) →
`2f68748` (Phase G PDF + Monte Carlo) →
`397d876` (Kelly addendum + 3 scenarios) →
`0bab305` (Phase H.1 strategic plan PDF) →
`ef31746` (Phase H.FINAL engineering spec PDF) →
`9566f30` (Phase H.2 next-session prompt)

All on `claude/jovial-hermann-7e103f`, all pushed.

## What changed about the bot

**Nothing on the bot itself.** This was a 100% analytical + planning session. The bot has been running v2 (`spot_aware_v2`) under PHASE-F-4 (since 2026-05-12 15:42:38 UTC) the entire time. No restarts, no env changes, no code changes deployed.

## What's next

**Phase H.2 (next session, ~2-3h):** ship v2.1 code per the spec.

The next-session prompt at [phase-prompts/phase-H-2-code-v2_1-2026-05-13.txt](phase-prompts/phase-H-2-code-v2_1-2026-05-13.txt) drives it. Recommended outcome: ship code (H.2.0-H.2.6), defer deploy (H.5) to a separate session.

After H.2 ships:
- **H.5** VPS deploy + 3-stage verify (+5min, +30min, +24h)
- **H.6** 7-day soak gate → PROMOTE / EXTEND / ROLLBACK
- **If PROMOTE:** Phase I = live-trading readiness review

## Session totals

- 6 commits today (analysis + 3 PDFs + 2 prompts)
- 4 new Python scripts (~1500 LOC of analysis code)
- 3 PDFs generated (629K + 17K + 39K, total ~700K)
- 1 master CSV dataset (635 fires × 17 dims)
- 8 matplotlib charts
- 22 tests specified for next-session code work
- 14 past-incident defenses documented
- 17 open analytical hypotheses tested
- 0 lines of bot runtime code changed

## Operator quote of the session

> "this is the moment you shine in this case! this work that you will produce
> now will actually pivot the bot's actual income and win rate and fill rate!"

The pivot is identified (tier 30-50%×|Δ|<5 + Kelly). v2.1 will execute it.
