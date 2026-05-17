---
title: Phase H — v2.1 implementation (Kelly + multi-fire + filter changes)
tags: [phase, strategy, v2-1, kelly, multi-fire, compounding, path-a]
status: BOT LIVE on c746db3 with H.2.12 path A; 24h soak in progress to 2026-05-13T21:32:47Z
---

# Phase H — v2.1 implementation

Phase G discovered the winning cell + Kelly + multi-fire + compounding architectural improvements. Phase H ships them as v2.1.

## Sub-phase status

| Sub | What | Status |
|-----|------|--------|
| H.1 | Strategic plan PDF (10 sections) | ✅ shipped 2026-05-12 (`0bab305`) |
| H.FINAL | Engineering spec PDF (18 sections, 22 tests, 14 defenses) | ✅ shipped 2026-05-13 (`ef31746`) |
| H.2.0 | `design/spot_aware_v2_1.md` design doc lock | ✅ `4f218b1` 2026-05-13 |
| H.2.1 | KellyConfig + 8 tests | ✅ `810f841` |
| H.2.2 | BankrollTracker + 6 tests | ✅ `810f841` |
| H.2.3 | _RunnerState multi-fire refactor + 6 regression tests | ✅ `810f841` |
| H.2.4 | SpotAwareStrategyV2_1 + 17 tests | ✅ `810f841` |
| H.2.5 | `run_paper.py` dispatch + bankroll-getter wire | ✅ `810f841` |
| H.2.6 | Commit + push | ✅ `810f841` pushed |
| H.2.7 | CH3 priors-fallback + dashboard `phase H v2.1` label | ✅ `e8c5fb3` |
| H.2.8 | fire_n=N/M badge in decision tape | ✅ `b1d860e` |
| H.2.9 | Bet $ column in decision tape | ✅ `076926a` |
| **H.5** | **VPS deploy + verify** | ✅ **2026-05-12T21:32:47Z (deployed same session)** |
| H.2.10 | gamma timeout 300s → 30s (env-only) | ✅ 2026-05-12T22:04:48Z |
| H.2.11 | multi-fire cap 2 → 1 (env-only; operator throttle) | ✅ 2026-05-13T00:21:12Z |
| H.2.12 | path A: block_up_in_tiers=("70-85%",) + tests | ✅ `c746db3` 2026-05-13T00:56:31Z |
| H.2.13 | multi-fire cap 1 → 2 reactivation (env-only; operator-directed) | ✅ 2026-05-13T01:49:47Z |
| **H.6** | +24h gate + 7d soak gate | ⏳ in progress; +24h gate at 2026-05-13T21:32:47Z |

## H.2 ship summary

- Branch `claude/jovial-hermann-7e103f` advanced `73dcc73 → 4f218b1 → 810f841 → e8c5fb3 → b1d860e → 076926a → c746db3`
- `make verify` exit 0 at every commit: ruff clean, mypy --strict clean (83 files), **628 tests pass** (baseline 581 + 47 new)
- 6 deploys to VPS, all NRestarts=0 clean
- 0 journalctl errors, 0 queue overflow, 0 Anthropic spend
- Total session ship: 6 commits + 5 env-restart cycles

## CH3 honest pushback — RESOLVED via H.2.7

v2 enforces a priors-table hit (no fallback). Current priors table starts at `|Δ|=5`, so CH3's tier-specific floor relaxation alone won't fire on the Phase G winning cell in production.

**Resolution shipped in H.2.7 (`e8c5fb3`):** added `tier_relax_p_win_fallback` parameter to v2.1 + `_PriorsFallback` wrapper. When the real priors table misses AND tier ∈ `tier_relax` AND |Δ| < inherited floor, synthesises p_win = 0.48 (PG §5.1 historical empirical). Operator-tunable via `SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK` env. Default-on for v2.1.

**Live verification:** at H.5 + 3h, the CH3 cell fired 49 times all using the fallback path. WR 50.0%, +$/trade close to Phase G projection (+$0.65). Cell exploitation confirmed working.

## v2.1 changes (CH1-CH8)

**Filter changes:**
- CH1 Reject Δ_bps = 0 (PG §4.3, -$0.62/trade no-skew loser)
- CH2 Reject EV ∈ [0.02, 0.05) (PG §5.1, -$0.43/trade marginal-EV trap)
- CH3 Tier-specific Δ floor + **priors fallback** (PG §6.2 winning cell)
- CH4 Kelly min-bet abstain

**Sizing changes (Kelly + compounding):**
- CH5 Kelly bet = clamp(bankroll × kelly_mult × kelly_f, min=$1, max=$500)
- CH6 BankrollTracker in PaperRunner (live state + replay-from-JSONL)

**Multi-fire changes:**
- CH7 Per-window cap; default 2 (operator Q3 default) — **throttled to 1 in H.2.11**
- CH8 PaperRunner `pending_decision → pending_decisions: list` with backward-compat property

**Post-spec additions (in-session):**
- H.2.12 path A: `block_up_in_tiers` / `block_down_in_tiers` constructor params — operator-tunable per-tier side-direction block (used to silence the catastrophic tier 70-85% UP bleeder)

## Live findings from soak (first ~5 hours)

### Multi-fire is pure capital-variance amplifier (not a WR multiplier)

Live observation: cap=2 vs cap=1 retrospective showed IDENTICAL 41.9% WR. Both fires of a multi-fire window always settle the same way (same window, same direction, same outcome). PnL is mathematically 2× the per-fire PnL.

Operator throttled cap=2 → cap=1 in H.2.11 after observing −17% drawdown.

### Tier 30-50% (CH3 cell) is OUTPERFORMING Phase G projection

Counterfactual (cap=1): tier 30-50% gives 52.2% WR / +$0.79/trade. Phase G projected 48.1% WR / +$0.65/trade. **The winning cell is working as designed.**

### Tier 70-85% is the catastrophic bleeder (path A target)

Full-history forensic (n=72 across all eras): UP-side fires lose −$5.06/trade (n=41); DOWN-side fires net +$0.13/trade (n=31). Path A blocks UP only — preserves the marginal DOWN sample.

Asymmetric-payoff cost: at price 0.78, WR ≥ 78% needed to break even. Phase G measured 72% historically (close but below). Our v2.1 sample saw 13.3% — catastrophic.

### Chainlink/gamma resolution disagreement: ~12% disagreement rate

Phase 11.A historic baseline ~33%. Bot's post-hoc gamma retry catches them via Phase 15.5 `settled_correction` overlay. Working as designed — operator-visible "wrong" display in the 5-min window between chainlink-fallback settle and post-hoc retry.

## Architectural findings (in-session)

1. **`BankrollTracker` lives in `_paper/runner.py`** with `apply_settle` + `apply_correction` (Phase 15.5 overlay). Replays from JSONL on startup so restarts don't reset the compound clock.
2. **Multi-fire requires `_RunnerState` refactor** to `pending_decisions: list[_PendingDecision]` with backward-compat property. Shipped.
3. **`_prime_active_window_state` mid-window multi-fire gap** (Bug E): only re-primes the most-recent unsettled fire after a restart. Periodic orphan-recovery catches the orphan within 5 min. Follow-up needed to fix the primer.
4. **CH1 strict-equality false-alarm pattern** (Bug F): rationale's `%+.2f` format renders very-near-zero Δ as `+0.00`; audit tooling parses this as 0.0 and flags. Real spec invariant holds. Tiny clarity fix in follow-ups.

## Files touched in v2.1 ship

| File | Action | First commit |
|------|--------|-----|
| `src/polymarket_bot/strategies/spot_aware_v2_1.py` | NEW + extensions | `810f841` (base), `e8c5fb3` (CH3 fallback), `c746db3` (path A) |
| `src/polymarket_bot/strategies/kelly_config.py` | NEW | `810f841` |
| `src/polymarket_bot/_paper/runner.py` | EDIT | `810f841` (BankrollTracker + multi-fire) |
| `scripts/run_paper.py` | EDIT | `810f841` (base), `e8c5fb3` (fallback env), `c746db3` (path A env) |
| `apps/dashboard-v3/src/panels/TopStrip.tsx` | EDIT | `e8c5fb3` (phase label) |
| `apps/dashboard-v3/src/panels/DecisionsTape.tsx` | EDIT | `b1d860e` (fire_n badge), `076926a` (Bet column) |
| `apps/dashboard-v3/src/store/types.ts` | EDIT | `b1d860e` |
| `src/polymarket_bot/dashboard/loaders.py` | EDIT | `b1d860e` (fire_n parsing) |
| `src/polymarket_bot/dashboard_server/state.py` | EDIT | `b1d860e` (fire_n in API) |
| 4 test files (8+22+6+6 tests) | NEW | `810f841` (base) + `e8c5fb3` (CH3 fallback) + `c746db3` (path A) |
| `design/spot_aware_v2_1.md` | NEW | `4f218b1` (locked) + `e8c5fb3` (CH3 update) |

## Operator open questions (Q1-Q5) — sign-off

- Q1 Hour gate: **NO** (sample thin) ✓
- Q2 Regime gate: **A** no gate (start simple) ✓
- Q3 Multi-fire cap: **2** at H.5 → throttled to **1** at H.2.11 by operator
- Q4 Kelly multiplier: **0.10×** locked throughout session by operator
- Q5 Live promotion threshold: **$2k** (locked decision #12) ✓

## Past-incident defense matrix (spec §14)

L1-L14 all preserved and operationalized this session:
- L1 v3 rationale-inheritance → v2.1 rewrites at fire time ✓
- L2 per-side state pollution → multi-fire counter keyed by window_ts ✓
- L3/L4 LLM/instant-settle queue overflow → no async I/O added in fire path ✓
- L5 FD orphan dashboard → no decision-log writer changes ✓
- L6 Phantom-fill → tier-rejection + price_limit cap preserved ✓
- L7 chainlink-vs-polymarket → post-hoc retry handled 8 corrections this session ✓
- L8 wide_fire negative selection → no LLM in v2.1 path ✓
- L9 Cross-restart double-fire → multi-fire counter scoped to window_ts; restart resets ✓
- L10 VPS timestamp drift → all deploys captured `$(date +%s)` on VPS ✓
- L11 Phase 15.5 truth-pass → `BankrollTracker.apply_correction` wired ✓
- L12 pending_decision singular invariant → refactor with property ✓
- L13 OSError disk-full → preserved try/except ✓
- L14 Aggressive-mode high variance → 0.10× Kelly + cap=1 throttle ✓

## H.6 soak gate criteria (spec §15)

**PROMOTE → Phase I (live trading prep)** — all of:
- WR ≥ 52% on n ≥ 100 settled fires
- daily_pnl_min ≥ −$10 over 7 days
- fires/day ≥ 30 (multi-fire 2× expected — adjusted target ~15-25 with cap=1)
- queue_overflow_incidents == 0
- bankroll ≥ $1,500 (50% gain sanity check)

**ROLLBACK** — any of:
- WR < 45% over 48h continuous
- daily_pnl < −$30 any UTC day
- bankroll ≤ $500 (50% drawdown)
- 3 consecutive losing days

## Update at +3.8h since H.5 deploy (01:20Z 2026-05-13)

### CH3 cell convergence to Phase G EXACT (validation moment)

At n=52 in the cell: **WR = 48.1%** — exactly matches Phase G's historical projection (48.1% on n=83). Strong validation that the cell-exploitation thesis is real.

But **$/trade = −$0.387** vs Phase G's predicted +$0.65. Diagnosis: bot is firing at cell-average price ≈ 0.50 (top of the 30-50% tier where asymmetric-payoff edge is thinnest); Phase G's historical sample had cell-average ≈ 0.40. The under-performance is a price-distribution issue within the cell, not a WR problem. Possible follow-up: tighten upper price boundary or accept marginal $/trade and rely on volume.

### First fires after H.2.12 path A

All `fire=1/1` (cap=1 working), all DOWN-side (path A invariant holding for 70-85% UP). Kelly bet sizes vary $3-$23 with bankroll-and-edge scaling.

### Expected behaviour going forward

- Fire rate ~240-280/day (cap=1 halved from ~520/day cap=2 baseline)
- WR will likely stay 40-50% (path A removes high-WR-but-negative-$/trade UP fires; WR could drop slightly while PnL improves — counter-intuitive but intended)
- Daily PnL central tendency: **−$10 to +$30** depending on whether CH3 cell stays at current −$0.39 or drifts toward Phase G's +$0.65
- Bankroll: oscillation in $750-$900 range likely; recovery to $1,000 baseline 6-15 days if positive bias holds
- **Phase G $116k/90d off the table** — realistic 90d: $1.5k-$3k median; $2k hardware-wallet trigger ~20-45 days

### +24h gate prediction

**Most likely verdict: EXTEND** (re-soak 7d).
- PROMOTE unlikely (need WR ≥ 52% on n ≥ 100; currently 41-48% n=52)
- ROLLBACK unlikely (drawdown floor $500 is $300+ away)

## Live state snapshot (session boundary 2026-05-13T00:56:31Z)

```
strategy:       spot_aware_v2_1
kelly_mult:     0.10        (operator-locked)
multi_fire_cap: 1           (H.2.11 throttle from 2)
fallback p_win: 0.48        (CH3 priors fallback)
block_up_in:    ("70-85%",) (H.2.12 path A)
gamma timeout:  30s         (H.2.10 from 300s)
bankroll:       $807.28     (runner replay)
peak/trough:    $1148.62 / $734.13 since H.5 deploy
restarts since H.5: 4 (H.2.10, H.2.11, H.2.12); all NRestarts=0
fires since H.5: 60+ (running)
WR observed:    41.9% on n=65 settled (95% CI [30, 54]%)
post-hoc corrections: 8 (~12% disagreement rate, ↓ from Phase 11.A 33% baseline)
soak clock:     +24h gate at 2026-05-13T21:32:47Z
```

## Deferred follow-ups (post-soak)

1. **CH1 strict-equality** → `abs(d_bps) < 0.01` to catch near-zero rationale-render ambiguity
2. **`_prime_active_window_state` multi-fire** → re-prime ALL unsettled fires after mid-window restart
3. **`POST_HOC_GAMMA_RETRY_INITIAL_DELAY_S`** → 300s → 60s to shrink wrong-display window
4. **`feeds_health.json` writer audit** → locate why file is currently missing; fix heartbeat
5. **Priors data low-Δ extension** → add `[1, 5]` `delta_buckets_bps` row from PG §6.2 empirical
6. **TopStrip MODE badge** → flip `SPOT_AWARE` → `SPOT_AWARE_V2_1`
7. **Gamma timeout alert throttle** → every-10th → every-50th if Telegram noise annoys
8. **Tier 70-85% DOWN second look** → if H.6 data confirms marginal, consider rejecting tier entirely

## Related

- [[../sessions/2026-05-13-phase-H-2-code-v2_1|Session note (full chronology)]]
- [[phase-G-edge-discovery|Phase G (analytical predecessor)]]
- [[phase-F-architecture-audit|Phase F (cut chain that preceded G)]]
- `pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf` — engineering spec (source of truth)
- `pdfs/PHASE_H_v2_1_IMPLEMENTATION.pdf` — strategic plan
- `memory/checkpoint_phase_H.md` (durable hand-off)
- `memory/project_v2_1_multi_fire_pure_variance.md` (cap=2 vs cap=1 variance amplifier finding)
