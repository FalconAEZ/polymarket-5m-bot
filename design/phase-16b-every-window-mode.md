# Phase 16.B — every-window mode with signal-driven router (LOCKED DESIGN)

Status: locked 2026-05-11. Anti-vibe rule #1 — implementation in
Phase 16.B.3 onward references this document verbatim. Changes here
require a new commit + operator sign-off.

Anchor research: `state/research/phase-16b-every-window-study.md` (§4 architecture, §12 v2 scope)
Counterfactual: `state/research/2026-05-11-router-counterfactual.md` (+$344 net delta projected, +7x PnL)
Phase prompt: `phase-prompts/phase-16b-every-window-mode-2026-05-11.txt`

---

## 1. Goal (one sentence)

Fire on **every** 5-minute window with a stake in `[$5, $30]` chosen by a unified confidence score that synthesises 5 inputs (deterministic edge, regime, tier, LLM, half-Kelly), with hard safety vetoes preserved from Phase 11.A.

## 2. Locked-decision impacts

| Decision | Status before | Status after PROMOTE |
|---|---|---|
| **#6** (composite ≥0.6 hard gate) | FIRE/ABSTAIN binary | **REVISED** — composite magnitude is one input to the confidence score (weight `W_DET=0.25`). |
| **#9** ($5 flat for first 100 trades, then fractional Kelly) | $5 flat | **REVISED** — confidence-weighted $5–$30 hybrid-Kelly. Past 480 settled, so the 100-trade gate is closed; Kelly transition is within the original-locked plan. |
| **#10** ($1k paper bankroll) | UNTOUCHED | UNTOUCHED |
| **#5** (3 specialists + meta) | UNTOUCHED | LLM confidence becomes a size input via `W_LLM=0.25`. Ensemble structure unchanged. |
| **Phase 17** (sizing modes) | separate phase | **MERGED into 16.B.** `POSITION_SIZING_MODE` env supplanted by `EVERY_WINDOW_MODE` + the router's size_for function. |
| **Phase 18** (Kelly impl) | separate phase | **MERGED into 16.B.** `sizing.py` ships here. |

Revisits to `memory/project_decisions.md` happen only on PROMOTE (Phase 16.B.6) — not on dark-ship.

## 3. The router contract

### 3.1 Inputs (`RouterContext` dataclass)

```python
@dataclass(frozen=True, slots=True)
class RouterContext:
    """Read-only snapshot of everything the router needs to decide one window."""
    # Deterministic
    window_ts: int
    now_ts_utc_ns: int
    seconds_to_close: int
    spot_now: float
    window_open_spot: float
    oracle_last: float | None
    oracle_age_s: float
    composite_pct: float | None        # signed; sign is base side
    delta_bps: float                    # signed; magnitude feeds W_DET

    # Market
    best_bid_up: float | None
    best_ask_up: float | None
    best_bid_down: float | None
    best_ask_down: float | None
    ask_size_top: float | None          # depth at top of book on chosen side
    book_imbalance: float | None        # (bid - ask) / (bid + ask)

    # Classifications (precomputed by caller)
    regime: Literal["trending", "mixed", "chop", "unknown"]
    tier: Literal["<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%"]

    # LLM signals (optional — may be None if specialists timed out)
    llm_meta_action: Literal["FIRE", "ABSTAIN"] | None
    llm_meta_side: Literal["UP", "DOWN"] | None
    llm_meta_confidence: float | None    # 0..1 if present
    llm_consensus: float | None          # 3-specialist agreement: 1.0 / 0.7 / 0.4 / None

    # Bankroll context for Kelly
    bankroll_usd: float                  # default $1000 (decision #10)
    p_win_prior: float | None            # spot_aware_priors lookup, None if no prior
    fill_price_estimate: float | None    # mid or best_ask
```

### 3.2 Outputs (`RouterDecision` dataclass)

```python
@dataclass(frozen=True, slots=True)
class RouterDecision:
    """The router's verdict for one window."""
    fire: bool                           # only False on veto (catastrophic guard)
    side: Literal["UP", "DOWN"]          # always set when fire=True
    size_usd: float                      # in [$5.00, $30.00] when fire=True
    ttl_s: int                           # 10..120 (per-regime tuning)
    fill_style: Literal["maker", "taker_fallback"]  # taker_fallback only on tier extremes
    price_limit: float                   # base price ± offset
    confidence: float                    # in [0, 1]
    veto_reason: str | None              # if fire=False, why
    rationale: str                       # decision-log rationale string
    inputs_breakdown: dict[str, float]   # w_det, w_reg, w_tier, w_llm, w_kelly contributions
```

### 3.3 The 5 confidence inputs (locked weights)

```python
W_DET = 0.25
W_REG = 0.20
W_TIER = 0.15
W_LLM = 0.25
W_KELLY = 0.15
# Sum = 1.00. Weights are tunable post-soak via env vars, but defaults are LOCKED here.
```

**`det` (deterministic edge magnitude):**
```python
def _det_score(abs_delta_bps: float) -> float:
    # Step-function from study §3.3 + counterfactual §3.3
    if abs_delta_bps < 1.0:  return 0.0
    if abs_delta_bps < 2.0:  return 0.25
    if abs_delta_bps < 5.0:  return 0.50
    if abs_delta_bps < 10.0: return 0.85
    return 1.00
```

**`reg` (regime classifier):**
```python
REGIME_SCORE = {"trending": 1.00, "mixed": 0.70, "chop": 0.40, "unknown": 0.50}
```

**`tier` (historical-WR-weighted, with counterfactual-driven 50-70% tightening):**
```python
TIER_SCORE = {
    "<15%":    0.50,
    "15-30%":  1.00,   # unicorn — $15/trade in current data
    "30-50%":  0.85,   # +$0.81/trade
    "50-70%":  0.25,   # TIGHTENED from 0.40 per counterfactual finding
    "70-85%":  0.75,
    "85-100%": 0.50,
}
```

**`llm` (LLM meta + consensus, blended):**
```python
def _llm_score(meta_action, meta_confidence, consensus):
    if meta_action == "FIRE" and meta_confidence is not None:
        base = max(0.30, min(1.00, meta_confidence))
    elif meta_action == "ABSTAIN":
        base = 0.30                 # router still fires, just small
    else:
        base = 0.50                 # meta=None or no signal (neutral)
    if consensus is not None:
        base = 0.5 * base + 0.5 * consensus   # blend agreement
    return base
```

**`kelly` (half-Kelly suggestion, normalized):**
```python
KELLY_MAX_BANKROLL_PCT = 0.03   # 3% hard cap

def kelly_suggested_size_usd(p_win, fill_price, bankroll, fraction=0.5):
    if p_win is None or fill_price is None: return 0.0
    if p_win <= fill_price or p_win >= 1.0 or fill_price <= 0: return 0.0
    b = (1.0 - fill_price) / fill_price
    f = (p_win * b - (1.0 - p_win)) / b
    f = max(0.0, min(KELLY_MAX_BANKROLL_PCT, f * fraction))
    return round(f * bankroll, 2)

def _kelly_score(kelly_suggested_usd):
    # Normalize suggested $ size to [0, 1]; $22 (2.2% bankroll) maps to 1.0
    return min(1.0, kelly_suggested_usd / 22.0) if kelly_suggested_usd > 0 else 0.0
```

### 3.4 The confidence formula

```python
confidence = (
    W_DET   * _det_score(abs(ctx.delta_bps)) +
    W_REG   * REGIME_SCORE[ctx.regime] +
    W_TIER  * TIER_SCORE[ctx.tier] +
    W_LLM   * _llm_score(ctx.llm_meta_action, ctx.llm_meta_confidence, ctx.llm_consensus) +
    W_KELLY * _kelly_score(kelly_suggested_size_usd(...))
)
# confidence ∈ [0, 1]
```

### 3.5 The size formula (with kink + per-tier cap)

```python
SIZE_FLOOR = 5.0       # decision #9: never below
SIZE_CAP = 30.0        # decision #9 revisit: never above
CONFIDENCE_KINK = 0.30  # below this, force size to floor — prevents low-conviction upshifts
TIER_PER_TRADE_CAP = {
    "<15%":    10.0,    # thin books → cap blast radius
    "85-100%": 10.0,    # same
}

def size_for(confidence, tier):
    if confidence < CONFIDENCE_KINK:
        return SIZE_FLOOR
    raw = SIZE_FLOOR + (SIZE_CAP - SIZE_FLOOR) * confidence
    cap = TIER_PER_TRADE_CAP.get(tier, SIZE_CAP)
    return round(max(SIZE_FLOOR, min(cap, raw)), 2)
```

### 3.6 The side formula

```python
def pick_side(ctx):
    base_side = "UP" if ctx.composite_pct >= 0 else "DOWN"
    if ctx.llm_meta_side is None or ctx.llm_meta_side == base_side:
        return base_side
    # Disagreement: regime decides who's right
    if ctx.regime == "trending":
        return ctx.llm_meta_side       # LLM is smart-money override in trending
    if abs(ctx.delta_bps) < 1.0:
        return ctx.llm_meta_side       # deterministic is noise here
    return base_side                    # else deterministic wins
```

### 3.7 The TTL formula

```python
def ttl_for(regime, tier, seconds_to_close):
    base = 30                           # current default
    if regime == "chop":
        base = 90                       # let maker sit on book longer in chop
    elif regime == "trending":
        base = 20                       # urgency — cross sooner if needed
    if tier in ("<15%", "85-100%"):
        base = max(base, 90)            # extreme-tier maker needs more time
    return min(base, max(10, seconds_to_close - 5))
```

### 3.8 The tier routing (maker vs taker_fallback)

```python
TAKER_FALLBACK_TIERS = ("<15%", "85-100%")
def fill_style_for(tier):
    return "taker_fallback" if tier in TAKER_FALLBACK_TIERS else "maker"
```

`taker_fallback` semantics in the paper runner: place the maker order at `price_limit`; if not filled by `TTL/2`, cancel and re-place as a taker order at `best_ask + slippage_buffer`. (Implementation lives in `_paper/runner.py` — out of scope for this design doc; see runner ADR.)

### 3.9 Hard vetoes (`fire = False` cases)

The router fires on **every window EXCEPT** these catastrophic guards:

```python
def veto_reason(ctx) -> str | None:
    # Preserve Phase 11.A defense — phantom-fill zone
    if ctx.best_ask_up is not None and ctx.best_ask_up < 0.05 and ctx.ask_size_top is None:
        return "phantom_fill_defense"
    if ctx.best_ask_down is not None and ctx.best_ask_down < 0.05 and ctx.ask_size_top is None:
        return "phantom_fill_defense"
    # Catastrophic EV: only fire if expected loss < $0.50
    fp = ctx.fill_price_estimate
    pw = ctx.p_win_prior
    if fp is not None and pw is not None:
        # Use a $5 hypothetical to compute EV
        ev = 5.0 * (pw * ((1 - fp) / fp) - (1 - pw))
        if ev < -0.50:
            return "catastrophic_ev"
    # Cold-start: no spot context — falls through to base wide_fire
    if ctx.spot_now is None or ctx.window_open_spot is None:
        return "cold_start"
    return None
```

Vetoes log to JSONL with `kind="router_vetoed"` for audit.

## 4. Env vars (production knobs)

All envs live in `scripts/run_paper.py` env wiring; default values match this doc's locked numbers.

| Env | Default | Effect |
|---|---|---|
| `EVERY_WINDOW_MODE` | `false` | **MASTER KILL-SWITCH.** Default off = no behavior change. |
| `EVERY_WINDOW_SHADOW` | `false` | If true (and master off), router decisions LOGGED only — base strategy still drives. |
| `EVERY_WINDOW_SIZE_FLOOR_USD` | `5.0` | Hard floor (decision #9 minimum). |
| `EVERY_WINDOW_SIZE_CAP_USD` | `30.0` | Hard cap (decision #9 revisit). |
| `EVERY_WINDOW_CONFIDENCE_KINK` | `0.30` | Below this confidence → size = floor (no upshift). |
| `EVERY_WINDOW_TAKER_FALLBACK_TIERS` | `<15%,85-100%` | CSV; default REQUIRED per operator answer Q2. |
| `EVERY_WINDOW_TIER_PER_TRADE_CAP_USD` | `<15%:10,85-100%:10` | CSV key:value. |
| `EVERY_WINDOW_KELLY_FRACTION` | `0.5` | Half-Kelly default. |
| `EVERY_WINDOW_KELLY_MAX_PCT` | `0.03` | 3% bankroll cap on Kelly suggestion. |
| `EVERY_WINDOW_W_DET` | `0.25` | Confidence weight on deterministic edge. |
| `EVERY_WINDOW_W_REG` | `0.20` | Weight on regime. |
| `EVERY_WINDOW_W_TIER` | `0.15` | Weight on tier. |
| `EVERY_WINDOW_W_LLM` | `0.25` | Weight on LLM. |
| `EVERY_WINDOW_W_KELLY` | `0.15` | Weight on Kelly. |
| `EVERY_WINDOW_BANKROLL_USD` | `1000.0` | For Kelly calc; decision #10 default. |
| `EVERY_WINDOW_DAILY_STAKE_CAP_USD` | `300.0` | 30% of bankroll/day; flips to floor if exceeded. |
| `EVERY_WINDOW_ROLLING_WR_FLOOR` | `0.48` | Auto-revert if rolling-100 WR drops below. |
| `EVERY_WINDOW_DAILY_PNL_FLOOR_USD` | `-100.0` | Auto-revert if daily PnL drops below. |
| `EVERY_WINDOW_PER_TIER_DAILY_LOSS_USD` | `-30.0` | Cap that tier to floor if it loses >$30 in 24h. |

## 5. Kill-switches (locked behaviour)

Five layers, each automatic:

1. **`EVERY_WINDOW_MODE=false`** — master switch. Operator can flip via `.envrc` + restart. (Existing pattern.)
2. **`EVERY_WINDOW_SHADOW=true` + `EVERY_WINDOW_MODE=false`** — router runs in parallel, logs only. Used for the 24h Phase 16.B.5 validation.
3. **Rolling-100-trade WR < 48%** — automatic env flip + Telegram alert. Implemented as a periodic in-process check in the runner.
4. **Daily PnL < −$100** — automatic env flip + Telegram alert. Same in-process check.
5. **Per-tier 24h loss < −$30** — that tier's size capped at $5 for next 24h. Other tiers unaffected.

Layers 3-5 are runtime; they don't require a service restart, just a config update via the in-process state holder.

## 6. Module layout

```
src/polymarket_bot/strategies/
    sizing.py              # NEW — kelly_suggested_size_usd
    every_window/
        __init__.py        # exports Router, RouterContext, RouterDecision
        types.py           # RouterContext, RouterDecision dataclasses
        config.py          # env-driven thresholds (RouterConfig dataclass)
        router.py          # Router class with pick_side, size_for, ttl_for, veto_reason, decide
    ensemble_wrapper.py    # MODIFIED — wires EVERY_WINDOW_MODE/SHADOW

tests/strategies/
    test_sizing.py             # NEW — Kelly math tests
    test_every_window_router.py # NEW — 12+ router tests
    test_ensemble_wrapper.py    # MODIFIED — 7 new tests for the env wire
```

## 7. Test plan

### 7.1 `tests/strategies/test_sizing.py`

| Test | What it asserts |
|---|---|
| `test_kelly_zero_when_no_edge` | `p_win ≤ fill_price → 0.0` |
| `test_kelly_zero_when_p_win_one` | edge cases don't divide-by-zero |
| `test_kelly_half_at_60_40_even_odds` | `p=0.6, fp=0.5 → ≈ $5` (small positive Kelly at half-fraction) |
| `test_kelly_capped_at_3pct_bankroll` | hard cap holds at extreme edge |
| `test_kelly_capped_at_zero_below_floor` | never negative |

### 7.2 `tests/strategies/test_every_window_router.py`

| Test | What it asserts |
|---|---|
| `test_pick_side_agreement` | LLM agrees with composite → use composite |
| `test_pick_side_trending_disagreement_takes_llm` | LLM disagrees in trending → use LLM |
| `test_pick_side_chop_disagreement_takes_deterministic` | LLM disagrees in chop → use composite |
| `test_pick_side_low_delta_disagreement_takes_llm` | `|Δbps|<1` + disagreement → LLM |
| `test_size_for_floor_at_5` | confidence=0 → $5 |
| `test_size_for_cap_at_30` | confidence=1 → $30 |
| `test_size_for_kink_below_0_3` | confidence=0.29 → $5 (kink) |
| `test_size_for_kink_at_0_3` | confidence=0.30 → $5 + 25×0.30 = $12.50 |
| `test_size_for_tier_extreme_capped_at_10` | `<15%` with confidence=1 → $10 (per-tier cap) |
| `test_ttl_for_chop_longer` | regime=chop → 90s (vs 30s default) |
| `test_ttl_for_trending_shorter` | regime=trending → 20s |
| `test_ttl_for_tier_extreme_floor_at_90` | `<15%` → at least 90s |
| `test_fill_style_tier_extremes_taker_fallback` | `<15%` / `85-100%` → taker_fallback |
| `test_veto_phantom_fill_low_ask_no_depth` | ask<0.05 + ask_size_top=None → veto |
| `test_veto_catastrophic_ev` | EV < -$0.50 → veto |
| `test_veto_cold_start` | no spot → veto (falls through to base in caller) |
| `test_confidence_breakdown_returned` | inputs_breakdown dict populated |
| `test_router_100_evals_under_500ms` | queue-overflow guard |

### 7.3 `tests/strategies/test_ensemble_wrapper.py` (additions)

| Test | What it asserts |
|---|---|
| `test_every_window_mode_off_no_behavior_change` | `EVERY_WINDOW_MODE=false` produces identical fired-record stream as today |
| `test_every_window_mode_emits_on_every_window` | `EVERY_WINDOW_MODE=true` fires every event-batch eligible window |
| `test_every_window_mode_uses_router_confidence` | size matches `router.decide(ctx).size_usd` |
| `test_every_window_shadow_logs_only` | `_SHADOW=true,_MODE=false` writes JSONL but base strategy still drives |
| `test_every_window_mode_kill_switch_wr_floor` | rolling WR < 48% → flips MODE=false at next decision |
| `test_every_window_mode_kill_switch_daily_pnl` | daily PnL < -$100 → flips MODE=false |
| `test_every_window_mode_preserves_phantom_fill_defense` | Phase 11.A regression — phantom fills still vetoed |

All gates must pass: `ruff + mypy --strict + pytest + lint-imports`.

## 8. Soak gate (Phase 16.B.6 promote criteria)

After 7 days of `EVERY_WINDOW_MODE=true` on VPS:

```python
def promote_decision(soak_stats):
    return (
        soak_stats.rolling_wr_at_d7 >= soak_stats.baseline_wr + 0.01 AND
        soak_stats.pnl_per_trade_at_d7 >= soak_stats.baseline_pnl_per_trade * 1.20 AND
        soak_stats.min_daily_pnl >= -30.0
    )
```

If PROMOTE: write the locked-decision revisit to `memory/project_decisions.md`. Update `state/phases/README.md`.

If ROLLBACK: flip `EVERY_WINDOW_MODE=false` on VPS. Restart. Vault note: ROLLBACK reason + the per-cohort PnL deltas that drove the decision.

## 9. Rollback plan

Single env flip — `EVERY_WINDOW_MODE=false` — reverts to current strategy with **zero code change**. The wrapper has a clean `if env_off: return base_strategy_decision` short-circuit at the top of `_run_ensemble`.

If the wrapper code itself has a bug that breaks the off path: `git revert <commit>` and force-push to `claude/jovial-hermann-7e103f`. The current strategy is untouched in the unchanged-code paths.

## 10. Non-goals (explicit out-of-scope for Phase 16.B)

- ❌ Touching decision #10 ($1k paper bankroll)
- ❌ Adding a 4th LLM specialist (decision #5)
- ❌ Sub-5-minute latency optimization (Phase 19)
- ❌ Adding new market-data feeds (Phase 21)
- ❌ Changing the kill-switch infrastructure (Phase 14 + 15 envs untouched)
- ❌ Modifying the resolver_loop or settled-correction overlay
- ❌ Auto-tuning the W_* weights via ML (out — these are tuned manually post-soak)

## 11. Implementation order (Phase 16.B.3 → 16.B.4)

1. `sizing.py` (Kelly) + `test_sizing.py` — commit
2. `every_window/types.py` + `every_window/config.py` (env wiring) — commit (pure boilerplate)
3. `every_window/router.py` + `test_every_window_router.py` — commit (the core)
4. Wire into `ensemble_wrapper.py` + 7 new tests in `test_ensemble_wrapper.py` — commit
5. Run all 4 gates green at every commit
6. Push to `claude/jovial-hermann-7e103f`

Then Phase 16.B.5 is operations: VPS pull + restart + shadow-mode env flip + 24h audit.

---

This design is locked. Code in Phase 16.B.3 onward implements it verbatim.
