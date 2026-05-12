---
title: Phase H — v2.1 implementation (Kelly + multi-fire + filter changes)
tags: [phase, strategy, v2-1, kelly, multi-fire, compounding]
status: H.2 code SHIPPED 2026-05-13 (810f841); H.5 deploy deferred to next session
---

# Phase H — v2.1 implementation

The pivot. Phase G discovered the winning cell + the Kelly + multi-fire + compounding architectural improvements; Phase H ships them as v2.1.

## Sub-phase status

| Sub | What | Status |
|-----|------|--------|
| H.1 | Strategic plan PDF (10 sections) | ✅ shipped 2026-05-12 (commit `0bab305`) |
| H.FINAL | Engineering spec PDF (18 sections, 22 tests, 14 defenses) | ✅ shipped 2026-05-13 (commit `ef31746`) |
| H.2.0 | `design/spot_aware_v2_1.md` design doc lock | ✅ shipped 2026-05-13 (commit `4f218b1`) |
| H.2.1 | KellyConfig + 8 tests | ✅ shipped 2026-05-13 (in `810f841`) |
| H.2.2 | BankrollTracker + 6 tests | ✅ shipped 2026-05-13 (in `810f841`) |
| H.2.3 | _RunnerState multi-fire refactor + 6 regression tests | ✅ shipped 2026-05-13 (in `810f841`) |
| H.2.4 | SpotAwareStrategyV2_1 + 17 tests | ✅ shipped 2026-05-13 (in `810f841`) |
| H.2.5 | `run_paper.py` dispatch + bankroll-getter wire | ✅ shipped 2026-05-13 (in `810f841`) |
| H.2.6 | Commit + push | ✅ pushed to origin 2026-05-13 |
| H.5 | VPS deploy + +5/30/24h verify | ⏳ **deferred — operator chose ship-only this session** |
| H.6 | +7d soak gate → PROMOTE / EXTEND / ROLLBACK | ⏳ future (after H.5) |

## H.2 ship summary

- Branch `claude/jovial-hermann-7e103f` advanced `73dcc73 → 4f218b1 → 810f841`
- `make verify` exit 0: ruff clean (src/+tests/), mypy --strict clean (83 files), **618 tests pass** (baseline 581 + 37 new)
- 16 files touched (5 NEW src/test, 2 EDIT src/script, 9 ride-along ruff fixes + .gitignore housekeeping)
- 37 new tests across 4 files (8 KellyConfig + 17 v2.1 strategy + 6 BankrollTracker + 6 multi-fire regression)

## CH3 honest pushback (deferred follow-up)

v2 enforces a priors-table hit (no fallback). Current priors table starts at `|Δ|=5`, so CH3's tier-specific floor relaxation alone won't fire on the Phase G winning cell in production. **Necessary-but-not-sufficient.** Operator decision needed before H.5 deploy expects exploitation:
- (a) Extend `data/spot_aware_priors.json` v1 with a `[1, 5]` bucket using empirical p_win from PG §6.2, OR
- (b) Plumb `tier_relax_p_win_fallback` parameter through `SpotAwareStrategyV2_1`.

Unit tests use a stub priors so the floor-relax logic is locked under regression; the production-cell-exploitation assertion is unverified until the priors follow-up lands.

## v2.1 changes (CH1-CH8)

**Filter changes (eliminate confirmed losers, exploit confirmed winners):**
- CH1 Reject Δ_bps = 0 (L1)
- CH2 Reject EV ∈ [0.02, 0.05) (L2)
- CH3 Tier-specific Δ floor (0 bps for 15-30% + 30-50%; 5 bps for 70-85%)
- CH4 Optional regime gate (deferred to operator Q2; default OFF)

**Sizing changes (Kelly + compounding):**
- CH5 Kelly bet = clamp(bankroll × kelly_mult × kelly_f, min=$1, max=$500)
- CH6 BankrollTracker in PaperRunner (live state, replay-from-JSONL on startup)

**Multi-fire changes:**
- CH7 Lift `fired_for_window` invariant for v2.1
- CH8 Cap 2 fires per window (operator Q3 default)

## Architectural findings beyond H.1 (from reading actual source)

1. **Bankroll lives dashboard-side** (`dashboard/bankroll.py::load_bankroll`). PaperRunner doesn't track it. v2.1 needs `BankrollTracker` added to PaperRunner with `apply_settle` + `apply_correction` (Phase 15.5 overlay support).
2. **Multi-fire requires PaperRunner changes**, not just a new strategy file. Singular `pending_decision` at `runner.py:448` blocks 2nd fire. v2.1 needs `_RunnerState` refactor to `pending_decisions: list[PendingDecision]` with backward-compat property.

## Files touched in v2.1 ship

| File | Action | Why |
|------|--------|-----|
| `src/polymarket_bot/strategies/spot_aware_v2_1.py` | NEW | the new strategy |
| `src/polymarket_bot/strategies/kelly_config.py` | NEW | KellyConfig + bet math |
| `src/polymarket_bot/_paper/runner.py` | EDIT | BankrollTracker + multi-fire support |
| `scripts/run_paper.py` | EDIT | dispatch + bankroll-getter wire |
| `tests/strategies/test_spot_aware_v2_1.py` | NEW | filters + Kelly + rationale |
| `tests/strategies/test_kelly_config.py` | NEW | 5 Kelly math tests |
| `tests/paper/test_bankroll_tracker.py` | NEW | recovery + correction overlay |
| `tests/paper/test_runner_multi_fire.py` | NEW | _on_decision relaxation regression |
| `design/spot_aware_v2_1.md` | NEW | locked design doc (anti-vibe rule #1) |

## Operator open questions (Q1-Q5)

Defaults documented in spec §16 and prompt:

- Q1 Hour gate: **NO** (sample thin)
- Q2 Regime gate: **A** no gate (start simple)
- Q3 Multi-fire cap: **2** per window
- Q4 Kelly multiplier: **0.10×** (smoother)
- Q5 Live promotion threshold: **$2k** (locked decision #12)

Operator signs off (or overrides) at the start of H.2 session.

## Past-incident defense matrix (spec §14)

v2.1 has explicit defenses for: v3 rationale-inheritance · per-side state pollution · LLM queue overflow · instant-settle queue overflow · FD orphan · phantom-fill · chainlink-vs-polymarket · cross-restart double-fire · VPS timestamp drift · Phase 15.5 truth-pass · pending_decision singular invariant · OSError on disk-full · aggressive-mode high variance · wide_fire negative selection.

## H.6 soak gate criteria (spec §15)

**PROMOTE** (all of):
- WR ≥ 52% on n ≥ 100 settled fires
- daily_pnl_min ≥ −$10 over 7 days
- fires/day ≥ 30 (multi-fire 2× expected)
- queue_overflow_incidents == 0
- bankroll ≥ $1,500 (50% gain sanity check)

**ROLLBACK** (any of):
- WR < 45% over 48h
- daily_pnl < −$30 any day
- bankroll ≤ $500 (50% drawdown)
- 3 consecutive losing days

## Projected outcome if PROMOTE

Per Phase G Conservative scenario Monte Carlo:
- +7d median bankroll: $3,701 · +30d: $34,851 · +90d: $116,115
- P(≥$2k within 90d): 100%
- Phase 6 readiness threshold ($2k hardware wallet trigger) reachable in **7-14 days**

## Risk

Kelly variance is real. The 58% backtest WR is from a 5-day window — if it doesn't generalize, Scenario C downside shows 97% of paths hit catastrophic drawdown. Mitigations: 0.10× (not 0.25×) start, $500 bet cap, multi-fire 2× (not 3×), hard ROLLBACK gate.

## Related

- [[../sessions/2026-05-13-phase-G-edge-discovery-and-phase-H-planning|Session note]]
- [[phase-G-edge-discovery|Phase G (analytical predecessor)]]
- [[phase-F-architecture-audit|Phase F (cut chain that preceded G)]]
- `pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf` — engineering spec (source of truth)
- `pdfs/PHASE_H_v2_1_IMPLEMENTATION.pdf` — strategic plan (lighter)
- `phase-prompts/phase-H-2-code-v2_1-2026-05-13.txt` — next-session prompt
- `memory/checkpoint_phase_H.md` (durable summary)
