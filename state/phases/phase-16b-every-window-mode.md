---
title: Phase 16.B — every-window mode with signal-driven router
status: PAUSED 2026-05-12 by Phase F cut. Router architecture relies on LLM signal (W_LLM=0.25) which Phase F removed from production. Code intact; `EVERY_WINDOW_SHADOW=true` env commented. Revival requires no-LLM router redesign.
tags: [phase, every-window, signal-router, decision-6-revisit, decision-9-revisit, kelly, phase-17-merged, phase-18-merged, paused]
---

> **PAUSED 2026-05-12 per [[phase-F-architecture-audit]].** Router design depends on `W_LLM=0.25` blended into composite scoring. With the LLM cut from production, the router's signal mix is unbalanced. Code + shadow soak infra preserved. If we ever return to it, redesign as no-LLM router: `W_DET=0.30, W_REG=0.30, W_TIER=0.20, W_KELLY=0.20`. That would be a different phase.

# Phase 16.B — every-window mode with signal-driven router

> Operator thesis (2026-05-11): "We already have so many gates and filters and ways to know if a trade will win or lose. Fire on EVERY window, use those gates as best-side / right-tier / right-size pickers instead of FIRE-or-ABSTAIN binary gates. Make this work with max edge and WR."

Operator-authorized revisit of locked decisions **#6** (composite ≥0.6 hard gate) and **#9** (partial — fractional Kelly down-shape, $5-$30 range). **Subsumes Phase 17 (sizing modes) + Phase 18 (Kelly).**

## Anchor documents

- [[../research/phase-16b-every-window-study|Research study]] — 12 sections; signal inventory + counterfactual + risk
- [[../research/2026-05-11-router-counterfactual|Counterfactual audit]] — first-cut projection on 517 historical fires
- `design/phase-16b-every-window-mode.md` (project root) — LOCKED spec
- `phase-prompts/phase-16b-every-window-mode-2026-05-11.txt` — 6 sub-phase plan
- `phase-prompts/phase-16b-4-wrapper-wire-2026-05-12.txt` — next-session prompt (Phase 16.B.4 + .5)

## Why this phase exists

After Phase 15.5 closed (PnL truth + 18B + 16 + v3 dashboard recovery), operator observed:

1. **<15% tier trades are mostly unfilled** (45% fill rate today)
2. **85-100% tier is even worse** (4.5% fill rate)
3. **28% of windows are being skipped** by wide_fire abstain + LLM gate

Honest pushback recorded — "trade every window" was previously flagged as a losing class. But operator framing is more sophisticated: the bot has **8 strong signals** that today drive 5 binary FIRE/ABSTAIN gates. Turn the same signals into a **router** that picks `(side, size, ttl, fill_style)` for every window.

## The 5 confidence inputs (locked weights)

| Input | Weight | What it scores |
|---|---:|---|
| `det` | 0.25 | `|delta_bps|` step function: 0/0.25/0.50/0.85/1.0 at 0-1/1-2/2-5/5-10/≥10 bps |
| `reg` | 0.20 | Regime: trending 1.0 / mixed 0.7 / chop 0.4 / unknown 0.5 |
| `tier` | 0.15 | Tier WR×payoff: 15-30%=1.0, 30-50%=0.85, **50-70%=0.25** (tightened per counterfactual leak finding), 70-85%=0.75, extremes=0.50 |
| `llm` | 0.25 | meta.action+confidence × specialist consensus |
| `kelly` | 0.15 | Normalized half-Kelly suggestion (3% bankroll cap) |

```
confidence = sum(weight × score)
size_usd = max(5.0, min(30.0, 5.0 + 25.0 × confidence)) if confidence ≥ 0.30
        = 5.0                                            if confidence < 0.30 (kink)
```

Hard vetoes (rare): `phantom_fill_defense`, `catastrophic_ev`, `cold_start`.

## Counterfactual projection (Phase 16.B.1)

| Metric | Actual | Router projected | Δ |
|---|---:|---:|---:|
| 3-day PnL | +$60.26 | +$404.18 | **+$343.92** |
| Avg size | $5.00 | $13.67 | +$8.67 |
| New fills (taker fallback) | 0 actual | 0 (snapshotter gap; live WS will differ) | — |

Conservative projection: live router likely produces $400-$700 over the same window. Confidence-bucket 0.4-0.6 (the workhorse) shows +$382 net delta — the size shaping is paying off there.

## Sub-phase status

| Sub-phase | Status | Commit |
|---|---|---|
| 16.B.0 — Research study + signal inventory | ✅ done | `e1b9a6b` |
| 16.B.1 — Counterfactual audit script + report | ✅ done | `a36e241` |
| 16.B.2 — Design doc locked | ✅ done | `707786c` |
| 16.B.3 — Router primitives + sizing.py + 49 tests | ✅ done | `707786c` |
| **16.B.4 — Wire into EnsembleWrapper (env-gated)** | ⏳ pending | — |
| 16.B.5 — VPS dark deploy + 24h shadow mode | ⏳ pending | — |
| 16.B.6 — 7-day soak gate → PROMOTE or ROLLBACK | ⏳ pending | — |

## Sub-phase 16.B.3 — what landed (commit `707786c`)

```
src/polymarket_bot/strategies/
    sizing.py                          # NEW — half-Kelly with 3% cap
    every_window/
        __init__.py                    # public API
        types.py                       # RouterContext + RouterDecision (frozen)
        config.py                      # RouterConfig (env-driven thresholds)
        router.py                      # Router.decide(ctx) → RouterDecision

tests/strategies/
    test_sizing.py                     # 11 tests (Kelly math)
    test_every_window_router.py        # 38 tests (pick_side, size_for, ttl_for,
                                       # fill_style, vetoes, breakdown, perf)

design/phase-16b-every-window-mode.md  # LOCKED spec
```

Pure-function additions. Zero call-site changes. **Default behavior unchanged on VPS.** All 4 gates green: ruff + mypy --strict (80 src files) + pytest (525 passed, +49) + lint-imports (3 contracts kept).

## Locked-decision impacts

| Decision | Status |
|---|---|
| #6 (composite ≥0.6 hard gate) | REVISED on PROMOTE — composite magnitude feeds confidence; sign still picks base side |
| #9 ($5 flat for first 100 trades, then fractional Kelly) | REVISED on PROMOTE — $5-$30 confidence-weighted hybrid-Kelly. Past 100-trade trigger (~543 fired), Kelly transition within original-locked plan. |
| #10 ($1k paper bankroll) | UNTOUCHED |
| #5 (3 specialists + meta) | UNTOUCHED (LLM confidence becomes size-scaler input) |
| Phase 17 (sizing modes) | **MERGED** — size_for replaces standalone POSITION_SIZING_MODE |
| Phase 18 (Kelly) | **MERGED** — sizing.py ships here |

Revisits to `memory/project_decisions.md` happen only on PROMOTE (16.B.6).

## Kill-switches (locked behavior)

| Layer | Trigger | Action |
|---|---|---|
| Master | `EVERY_WINDOW_MODE=false` env flip | Reverts to current strategy. Zero code change. |
| Shadow | `EVERY_WINDOW_SHADOW=true,_MODE=false` | Router logs decisions only; base strategy still drives |
| Auto-WR | Rolling-100-trade WR < 48% | Auto-flip MODE=false + Telegram alert |
| Auto-PnL | Daily PnL < −$100 | Auto-flip MODE=false + Telegram alert |
| Per-tier | Tier 24h loss < −$30 | Cap that tier's size to $5 floor for 24h |

Rollback is a single env flip — no code change required.

## Soak gate criteria (Phase 16.B.6)

After 7 days of `EVERY_WINDOW_MODE=true`:

```
PROMOTE if:
  rolling_wr_at_d7 >= baseline_wr + 0.01
  AND pnl_per_trade_at_d7 >= baseline_pnl_per_trade * 1.20
  AND min_daily_pnl >= -30.0
```

Otherwise ROLLBACK (env flip).

## Operational state at 2026-05-11 17h soak

- bot-staging.service active since 2026-05-10 23:50:50 UTC, MainPID 527106, NRestarts=0
- Cumulative PnL: +$39.03 (down from +$75 yesterday)
- Today's PnL: −$42.85 over 58 settled (rough day — possibly chop regime per 2026-05-09 case study)
- Phase 18B `meta_outcome` telemetry: 206 votes, 98.1% `ok`, 1.9% `invariant_violated`
- Disk: 7% used. Anthropic spend: ~$2.68 since restart (~$0.16/h)

**Today's downturn is exactly what the router was designed to dampen** — regime-aware size shaping would halve stake in chop. Worth shipping 16.B.4 + 16.B.5 sooner than later so we have shadow-mode data tomorrow.

## 2026-05-11 PM update — 16.B.4 + 16.B.5 SHIPPED + SHADOW SOAK UNDERWAY

| Sub-phase | State | Commit | Live? |
|---|---|---|---|
| 16.B.4 wrapper wire | ✅ **shipped** | `2eb54fd` | yes (since 17:56:22 UTC) |
| 16.B.5 dark deploy + 24h shadow | ⏳ **underway** | env flip only | yes (since 18:02:05 UTC) |
| 16.B.6 7-day soak gate | ⏳ pending | — | next-next session |

`EVERY_WINDOW_MODE=false` (default — no behavior change); `EVERY_WINDOW_SHADOW=true` (audit mode); router runs as observer, logs `router_shadow` records to `state/router/<UTC-date>.jsonl`. 18 records in first 1h25m, rate matches the 12-13 candidate windows/hour wide_fire produces.

24h shadow audit window closes ~2026-05-12 18:02 UTC.

## 2026-05-11 PM sidebar — wide_fire phantom-zone fix (`3875d3c`)

Mid-session, operator flagged "many unfilled trades." Fill-rate audit on today's 70 fires:

- 36 filled (51.4%), 34 unfilled
- WR on filled trades: **50.0%** (matches baseline; the dashboard's 26.8% counted unfilled-at-$0 as losses)
- **100% of unfilled fires** caught by `FillSimulator._refuse_for_no_depth` (Phase 11.A defense) — `ask_size_top=None AND best_ask <= $0.05`
- **0 genuine maker misses or TTL expiries**

Implication for Phase 16.B: the router's `taker_fallback` design (§3.8) for `<15%` tier solves the WRONG failure mode. Phantom defense triggers on the depth signal, not the price-cross. Right fix is upstream: abstain in the strategy when the simulator would refuse.

Shipped `3875d3c` — adds `if ask_size_top is None AND ask <= $0.05: return None` to `WideFireStrategy._maybe_fire`. **NOT deployed** (defer per `feedback_defer_deploys_to_natural_restart`). PnL impact = $0 (those 35 fires would have settled at $0 anyway); operational hygiene only.

Updated `taker_fallback` prescription for Phase 16.B: still valid *in principle* but unobserved in today's data; would only matter if `<15%` tier books develop depth signals during the shadow soak. For the dominant failure mode today (phantom-zone), `wide_fire` abstention is the cleaner fix.

## 2026-05-12 — phantom-zone fix v2 (per-asset_id) + backfill

Post-deploy of `3875d3c` (v1, per-side cache), a fire on window 1778583000 still emitted with the phantom-zone pattern. Root cause: the warmer keeps ~12 forward windows' tokens subscribed; BookUpdates for FUTURE-window UP-side tokens polluted `_ask_size_for_side["UP"]` via last-write-wins, even though the strategy's chosen asset_id (current-window UP token) had `ask_size_top=None`.

Fix v2 (`7a5b19e`): replace per-side caches with `_book_by_token: dict[asset_id, ...]`. `best_ask` is sticky (depth-only updates don't clobber); `ask_size_top` always written. Fire-time lookup by asset_id isolates pollution. Two new tests including a reproduction of the v1 bypass.

Phantom-fill backfill applied to live decision log (3 corrections written as `settled_correction` records):
- Window 1778480100 — -$5.00 → $0.00
- Window 1778487900 — -$5.00 → $0.00
- Window 1778551200 — **+$119.999 → $0.00** (the headline phantom)

Dashboard bankroll moved $1,120.62 → **$1,010.62 (+$10.62)** — truth-corrected.

Residual: `_token_for_side` is still per-side. In an extreme ordering the strategy could fire for a future-window's token; the new per-asset_id book lookup makes this MOSTLY harmless. A proper window-scoped token tracker is a follow-up.

## Related

- [[../runbooks/README|Runbooks]]
- [[../decisions/README|Decisions index]] (revisits to #6 + #9 land here on PROMOTE)
- [[../sessions/README|Sessions ledger]]
- `pdfs/PHASE_12_MASTER_PLAN.pdf` — Phase 17 + 18 subsumed by this phase
