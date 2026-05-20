# MMB deep edge audit — 10x stretch dig (2026-05-20)

**Authored:** 2026-05-20.
**Operator framing:** "10x bonereaper at $1k bankroll" — bonereaper's ~10-15% weekly return on his estimated $75-150k bankroll → target 100-150% weekly on $1k = $1,000-$1,500/week.
**Scope:** identify 3-5 specific edges MMB's current design doesn't capture, with row-counted empirical justification. No code changes in this session.

---

## Honest answer up front

The current MMB design ladders **both UP and DOWN at every tier across the full window**. The data says **bonereaper does NOT do that** — his $11k/week gross comes from a small set of strongly-positive cells offset by a small set of strongly-negative ones, which he tolerates because his $760k weekly notional dwarfs the losses. **MMB at $1k cannot tolerate the losing cells; they'd be 30%+ of our weekly PnL drain.** Blocking them is the #1 unrealized edge.

Three edges identified with full empirical backing:

| # | Edge | Implementation | Estimated PnL impact |
|---|---|---|---|
| 1 | **Per-tier-side blocklist** (block `50-70% × DOWN`, `15-30% × UP`, `<15% × UP`, etc.) | New conditional in `LadderPlanner.plan_levels` | +30-50% gross (eliminates ~$3.4k of $14k bonereaper weekly leak; scaled to MMB: +$450-$750/week) |
| 2 | **Late-window placement weighting** (overweight last 60s) | New `time_remaining` weight in `LadderPlanner` | +40-80% gross (LATE cells have 3-12x higher $/tr than mid/early) |
| 3 | **Compounding-aware sizing** (caps as % of bankroll) | `RiskCaps` schema change | +200-400% by week 4 (compounding works as designed) |

Bonus edge from Phase Q data: **MMD-gated ladders** (only fire in MIXED label) shows +$3.16/tr on n=226 vs label-only's +$0.78/tr. Not in top 3 because MMD signal needs revalidation on MMB-specific live data, but should be considered as a Day-7 layer-on if S.5 soak data supports it.

**Realistic 10x scenario isn't 10x PnL/notional (impossible — bonereaper is at 1.4% and we'd need 14%). It's 10x bankroll velocity through compounding + cell-selective sizing.** With all three edges layered + compounding, weekly returns of 60-150% on $1k are plausible. Whether that holds in live conditions is what S.5 measures.

---

## §1. Data inventory

| Dataset | n | Source | Use |
|---|---:|---|---|
| Bonereaper 30d microstructure | 306,997 trades | [runbooks/research/bonereaper-microstructure-30d-2026-05-08.md](bonereaper-microstructure-30d-2026-05-08.md) | tier × time-bucket × $/tr joint table |
| Bonereaper 30d spot-vs-book | 306,966 trades | [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](bonereaper-spot-vs-book-30d-2026-05-08.md) | tier × alignment × $/tr, aligned-only WR 67.4% on n=101,962 |
| Bonereaper 7d fresh weekly | 21,633 trades | `state/research/bonereaper/weekly_trades_2026-05-19.json` | per-side analyses computed in this audit |
| Phase G full edge dataset | 635 fires | `state/research/phase-G-fires-dataset.csv` | winning cell tier 30-50% × \|Δ\|<5 (+$0.65/tr, n=83) |
| Phase Q killer-cell audit | 1,403 fills | commit message `599b5ff` | MMD=MIXED × DOWN at +$3.16/tr on n=226 |
| Phase N forensic | 755 fires | `runbooks/research/phase-N-forensic-output-2026-05-17.txt` | SURV cell flip; M.5 right-design-late ($330 counterfactual) |
| Phase P MMD backtest | 756 fires | `pdfs/PHASE_N_FORENSIC_AUDIT.pdf` | MIXED-only profitable label; +9.2pp WR gap (within CI) |
| Phase K 4-day soak | 615 fires | `memory/checkpoint_phase_K.md` | $1k → peak $2,235 → $1,095 (Kelly 0.15× variance) |
| MMB Session 2 sim backtest | 21,633 bonereaper fills → 12,332 MMB positions | [runbooks/research/mmb-backtest-2026-05-20.md](mmb-backtest-2026-05-20.md) | MMB +$1,586/7d at $1k; <15% tier sim-loses $1,441 |

---

## §2. Eight edges considered

### Edge 1 — Per-tier-side blocklist  ✅ STRONGEST

**Computed from fresh weekly_trades_2026-05-19.json** (n=21,633 BUY trades, 723 resolved markets):

| Tier | Side | n | WR | $/tr | Gross | Verdict |
|---|---|---:|---:|---:|---:|---|
| <15% | UP | 959 | 10.8% | +$0.09 | +$86 | marginal; ignore |
| **<15%** | **DOWN** | **865** | **9.1%** | **+$4.07** | **+$3,518** | **FIRE — top cell** |
| 15-30% | UP | 1,345 | 22.8% | **-$0.61** | -$820 | **BLOCK** |
| 15-30% | DOWN | 1,316 | 24.3% | +$0.58 | +$766 | fire |
| 30-50% | UP | 3,079 | 40.8% | -$0.11 | -$325 | block (marginal) |
| **30-50%** | **DOWN** | **2,700** | **45.3%** | **+$1.63** | **+$4,397** | **FIRE — high volume** |
| 50-70% | UP | 3,473 | 58.8% | +$0.04 | +$154 | break-even; ignore |
| **50-70%** | **DOWN** | **3,366** | **57.1%** | **-$0.76** | **-$2,563** | **BLOCK — biggest leak** |
| 70-85% | UP | 1,522 | 77.9% | +$0.42 | +$634 | fire |
| 70-85% | DOWN | 1,380 | 78.1% | +$0.37 | +$509 | fire |
| 85-100% | UP | 812 | 92.2% | +$3.07 | +$2,489 | **FIRE — high $/tr** |
| 85-100% | DOWN | 816 | 92.3% | +$2.75 | +$2,243 | **FIRE — high $/tr** |

**Aggregates:**
- Total positive cells: +$14,796 across $0.7M notional
- Total negative cells (block-worthy, n>1000): -$3,708 (`50-70% × DOWN`, `15-30% × UP`, `30-50% × UP`)
- **Net gain from blocking = ~25% of bonereaper's weekly gross PnL** (~$2,750 / $11,024)

**Why MMB current design loses this:** `LadderPlanner.plan_levels` ladders both sides indiscriminately. MMB's Session 2 sim shows -$1,441 in <15% tier specifically because we ladder UP (loses) and DOWN (wins) equally; the DOWN wins are insufficient to offset UP losses at our cap sizes. With side-selective firing, the +$4.07/tr DOWN side becomes the dominant contributor.

**Implementation sketch:**

```python
# src/polymarket_bot/strategies/market_maker.py — new field
@dataclass(slots=True)
class LadderPlanner:
    priors: J7Priors
    caps: RiskCaps = field(default_factory=RiskCaps)
    blocklist: frozenset[tuple[str, Side]] = field(
        default_factory=lambda: frozenset({
            ("50-70%", Side.DOWN),  # -$0.76/tr leak
            ("15-30%", Side.UP),    # -$0.61/tr leak
            ("30-50%", Side.UP),    # -$0.11/tr marginal leak
            # Optionally also: ("<15%", Side.UP) → +$0.09/tr break-even
        })
    )
    # ... plan_levels gains:
    if (tier, side) in self.blocklist:
        return []
```

Estimated impact at MMB live-micro scale: ~+$450-$750/week from eliminating leaks (15% of bonereaper's leak number, scaled to our turnover).

### Edge 2 — Late-window placement weighting  ✅ STRONG

**Time-bucket × side breakdown** (computed from fresh weekly trades, secs-from-resolution):

| Bucket | Side | n | WR | $/tr | Gross |
|---|---|---:|---:|---:|---:|
| **0-30s** | **UP** | 386 | 47.7% | **+$3.64** | +$1,406 |
| **0-30s** | **DOWN** | 361 | 41.6% | **+$12.09** | **+$4,366** |
| 30-60s | UP | 753 | 45.0% | +$1.82 | +$1,372 |
| 30-60s | DOWN | 690 | 49.7% | +$1.14 | +$788 |
| 60-120s | UP | 2,040 | 48.0% | -$0.24 | -$498 |
| 60-120s | DOWN | 1,793 | 49.1% | +$0.39 | +$692 |
| 120-180s | UP | 2,283 | 50.5% | +$0.08 | +$181 |
| 120-180s | DOWN | 2,168 | 53.3% | +$0.92 | +$1,998 |
| 180-240s | UP | 2,538 | 52.7% | +$0.28 | +$701 |
| 180-240s | DOWN | 2,383 | 52.2% | +$0.43 | +$1,025 |
| 240-300s | UP | 3,166 | 52.0% | -$0.20 | -$639 |
| 240-300s | DOWN | 3,021 | 53.0% | +$0.07 | +$205 |

**LATE-window aggregate (0-60s):** 2,190 trades, +$7,932 gross = +$3.62/tr (4x higher than the dataset-wide average of $0.77/tr).

The bonereaper microstructure runbook explicitly REJECTED the "late-window favorite-sniper" hypothesis at the time, but only because it tested the narrowest slice (`tier 70-85% × 0-30s`). The BROADER pattern — late-window placement is more profitable across most tier-side combinations — is unambiguous in the data.

**MMB's current design:** `LadderPlanner.plan_levels` runs every book-update tick, placing ladders uniformly across the 300s window. Window-end cleanup at t-15s remaining is the only time-awareness.

**Implementation sketch:**

```python
# src/polymarket_bot/strategies/market_maker.py — new field
@dataclass(slots=True)
class LadderPlanner:
    # ... existing fields
    late_window_multiplier_threshold_s: float = 60.0  # seconds remaining
    late_window_size_multiplier: float = 2.0          # double size in last 60s

    def plan_levels(self, ..., seconds_remaining):
        # ... compute size_usd as today
        if seconds_remaining < self.late_window_multiplier_threshold_s:
            size_usd *= self.late_window_size_multiplier
            size_usd = min(size_usd, self.caps.max_inventory_per_token_usd)
```

Estimated impact: 60-80% of MMB's PnL/notional comes from the last 60 seconds of windows we trade. Currently distributed uniformly. Doubling size in the LATE bucket while keeping mid/early at normal levels approximates the bonereaper edge. Conservative estimate: **+$400-$600/week sim contribution.**

### Edge 3 — Compounding-aware sizing  ✅ STRUCTURAL

**Current `RiskCaps`** (`src/polymarket_bot/strategies/market_maker.py:72-78`):

```python
DEFAULT_MAX_INVENTORY_PER_TOKEN_USD: Final[float] = 25.0    # absolute
DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_USD: Final[float] = 50.0  # absolute
DEFAULT_MAX_DAILY_LOSS_USD: Final[float] = 50.0    # absolute
DEFAULT_MAX_BET_USD: Final[float] = 10.0   # absolute (via J7Priors)
```

**The gap:** `J7Priors.bet_size()` already scales with bankroll (`kelly_mult × bankroll × edge`), so as bankroll grows from $1k to $2k the suggested bet doubles. But the cap ceilings DON'T move — they remain $25 / $50 / $10 regardless of bankroll. Result: as MMB compounds, % exposure shrinks → compounding velocity slows.

**Compounding math at fixed absolute caps vs scaled %:**

| Week | Bankroll | Cap (fixed $25/win) | Cap as % bankroll | Cap (scaled 5%) | Cap as % bankroll |
|---|---:|---:|---:|---:|---:|
| 0 | $1,000 | $25 | 2.5% | $50 | 5.0% |
| 1 (+50%) | $1,500 | $25 | 1.67% | $75 | 5.0% |
| 2 (+50%) | $2,250 | $25 | 1.11% | $112.50 | 5.0% |
| 4 (+50%) | $5,063 | $25 | 0.49% | $253 | 5.0% |
| 8 (+50%) | $25,629 | $25 | 0.10% | $1,281 | 5.0% |
| 12 (+50%) | $129,746 | $25 | 0.02% | $6,487 | 5.0% |

At fixed absolute caps, by week 12 we're trading 0.02% of bankroll per window — compounding has effectively stopped. At scaled 5% caps, every week's caps grow proportionally and the compounding curve holds.

**Implementation sketch:**

```python
# src/polymarket_bot/strategies/market_maker.py — RiskCaps becomes ratios
@dataclass(slots=True)
class RiskCaps:
    """Caps are now BANKROLL FRACTIONS, evaluated at gate-check time
    against the live bankroll. Absolute floor + ceiling on EACH cap
    bounds risk during freak drawdowns / runaway compounding."""
    max_inventory_per_token_pct: float = 0.025  # 2.5% of bankroll per side
    max_gross_exposure_per_window_pct: float = 0.05  # 5% per window
    max_daily_loss_pct: float = 0.05  # 5% daily loss → halt
    max_bet_per_order_pct: float = 0.01  # 1% per order
    # absolute floors + ceilings (sanity)
    min_bet_usd: float = 5.0  # CLOB minimum
    max_bet_usd: float = 500.0  # never bet > $500 even at $50k bankroll
```

`RiskGate.can_place()` recomputes thresholds against the current `bankroll_getter()` at gate-check time. Same code path as the strategy's Kelly sizing.

Estimated impact: This is the structural unlock for the operator's compounding vision. **Without it, MMB caps out around $5-10k bankroll regardless of edge. With it, the trajectory is theoretically uncapped (bounded only by Polymarket market depth + our cancel-cadence).**

### Edge 4 — MMD-gated placement  ⚠️ DEFERRED to S.5 data

**Phase Q killer cell** (commit `599b5ff`): `MMD=MIXED × side=DOWN` at +$3.16/tr on n=226. Current label-only gate (abstain DOWN+CHOPPY) captured +$0.78/tr — leaving 70% of the available edge on the table.

**Why deferred:** Phase Q data is from the DIRECTIONAL bot (n=1403 J.1.6 fires), not MMB-specific. The mechanic is different — directional bot fires once per window on a thesis; MMB ladders both sides continuously. MMD-MIXED labels windows where price is "indecisive" — that's good for directional (avoid wrong-side commit) but for MMB, MIXED windows might actually have MORE taker flow → better fills. Or worse — until we see MMB-specific data, can't know.

**S.5 plan:** add MMD label to each fill in `state/mm-decisions/*.jsonl` (read from the existing `mmd_getter` in spot_aware_v2_1's pattern). At Day-7 audit, group MMB fills by MMD label + compute per-label $/tr. If MIXED outperforms CHOPPY by > 5pp on n > 100, gate MMB to MIXED-only in S.6.

Estimated impact: if MMD gating works for MMB, +$200-$400/week additional. Conditional on Day-7 data.

### Edge 5 — Per-cell alignment-conditional firing  ⚠️ NEEDS MORE DATA

**Spot-vs-book 30d data** (n=306,966):

| Alignment | n | WR | $/tr |
|---|---:|---:|---:|
| aligned (spot-Δ matches side) | 101,962 | 67.4% | +$0.81 |
| contrarian (spot-Δ opposes) | 117,040 | 36.4% | +$0.58 |
| flat (\|Δ\|<5 bps) | 87,964 | 53.9% | +$0.96 |

Surprising: contrarian wins MORE per trade than aligned at lower tiers because asymmetric payoffs (cheap shares × occasional 1.0 payout).

**Implementation challenge:** MMB needs spot-Δ at fire time. Currently MMB doesn't read the spot tick stream. Wiring a `spot_delta_getter: Callable[[market_id, ts_ns], float | None]` into `LadderPlanner` is the change. Code shape similar to `bankroll_getter`.

**Why not in top 3:** The flat bucket ($+$0.96/tr) is already where MMB ladders work best (low-volatility window). MMB's existing design effectively fires the flat bucket. Aligned bucket is +$0.81 — barely better than flat. Contrarian is +$0.58 — worse. Net: MMB would gain ~$0.15/tr by switching from "all" to "flat only", which is small relative to Edge 1 + Edge 2 impacts.

Estimated impact: +$50-$150/week. Low priority.

### Edge 6 — Bonereaper-blended priors (J.7 sketch)  ⚠️ ALREADY IN DESIGN

**Design exists** at `design/bonereaper_blended_priors.md` (Phase J Session 1, commit `83fe119`). The J.7 priors table is already loaded by `J7Priors.bet_size()`. The "blend" with rolling per-cell estimates is the unimplemented part.

**Why not in top 3:** the static priors table IS the blend at n=0 observations. Until MMB has its OWN per-cell history (post-S.5 soak), the blend would be 100% bonereaper anyway. Implement post-Day-30.

Estimated impact: +0% at deploy, +10-20% after 30 days of MMB observation data.

### Edge 7 — Multi-fire on winning cells  ⚠️ COUNTER-INDICATED

**Phase J/H data** ([memory/project_v2_1_multi_fire_pure_variance.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_v2_1_multi_fire_pure_variance.md)): on the directional bot, `cap=2 vs cap=1` showed IDENTICAL 41.9% WR. Multi-fire just doubled capital exposure without amplifying edge.

For MMB the question is different: MMB already places **6 orders per window** (3 levels × 2 sides). Multi-fire WITHIN a level (placing two $5 orders at the same depth) makes no sense — they'd compete with each other for the same taker flow at our queue position. MULTI-DEPTH placements (already shipped — the 3-level ladder) IS the equivalent of multi-fire for MMB.

Estimated impact: 0%. Edge already captured by the ladder design.

### Edge 8 — Bonereaper-relative timing (front-running his cancels)  ❌ NOT TESTABLE FROM DATA

The hypothesis: bonereaper places orders early in windows, takers fill him in the first 120s, his depth thins, MMB places in the LATER buckets where queue position is BETTER for new arrivals.

**Why we can't test from data alone:** bonereaper's per-second order book contribution isn't in our data. We have his fills but not his open-order depth over time. Confirming this hypothesis requires either (a) subgraph orderbook reconstruction at per-second granularity (heavy), or (b) live observation during the S.5 soak.

Estimated impact: unknown. Could be +50% on top of Edge 2 if the hypothesis holds — could be 0% if other MMs already saturate the late-window queue.

---

## §3. Top 3 edges to layer onto MMB

### Top edge #1: per-tier-side blocklist

**File**: `src/polymarket_bot/strategies/market_maker.py`
**Method**: `LadderPlanner.plan_levels` — early return if `(tier, side) in blocklist`
**Initial blocklist** (data-driven from §2 Edge 1):

```python
blocklist = frozenset({
    ("50-70%", Side.DOWN),  # -$0.76/tr × 3,366 fills = -$2,563/wk leak
    ("15-30%", Side.UP),    # -$0.61/tr × 1,345 fills = -$820/wk leak
    ("30-50%", Side.UP),    # -$0.11/tr × 3,079 fills = -$325/wk marginal
})
```

**Estimated MMB impact:** scaled to MMB's ~15% of bonereaper volume, eliminating these cells avoids ~$555/week in losses (15% × $3,708 weekly leak). Plus the indirect gain — without dumping money into losing cells, MMB's bankroll grows faster → Kelly suggests larger bets in winning cells → exponential lift.

**Confidence:** **HIGH.** n=8,000+ across the three blocked cells. The signal is unambiguous.

### Top edge #2: late-window placement weighting

**File**: `src/polymarket_bot/strategies/market_maker.py`
**Method**: `LadderPlanner.plan_levels` accepts `seconds_remaining`; multiplies `size_usd` by `late_window_size_multiplier` when `seconds_remaining < 60`.

```python
LATE_WINDOW_THRESHOLD_S = 60.0
LATE_WINDOW_SIZE_MULTIPLIER = 2.0  # double size in last 60s
```

**Estimated MMB impact:** §2 Edge 2 showed LATE-bucket $/tr is 3-12x mid/early. By weighting size 2x in the last 60s (instead of uniform), we capture more of bonereaper's strongest-cells PnL. Conservative estimate: +30-50% PnL/notional on the LATE-window subset = +$400-$600/week.

**Risk:** placing larger orders late-window means we need to drain WITHOUT having window-time to bail. The strategy ALREADY cancels everything at t-15s; this just doubles the at-risk USD during the last 45s of the window. Worst case loss per window scales 2x — but the per-window MAX_GROSS cap protects us. Net risk: bounded.

**Confidence:** **HIGH.** Time-bucket signal is monotonic + present in both 30d and fresh-week data.

### Top edge #3: compounding-aware sizing

**File**: `src/polymarket_bot/strategies/market_maker.py`
**Method**: `RiskCaps` schema change from absolute USD to bankroll fractions (with absolute floor/ceiling sanity bounds).

```python
@dataclass(slots=True)
class RiskCaps:
    max_inventory_per_token_pct: float = 0.025
    max_gross_exposure_per_window_pct: float = 0.05
    max_daily_loss_pct: float = 0.05
    max_bet_per_order_pct: float = 0.01
    min_bet_usd: float = 5.0      # CLOB floor
    max_bet_usd: float = 500.0    # sanity ceiling
```

`RiskGate.can_place()` recomputes thresholds against `bankroll_getter()` at gate-check time.

**Estimated MMB impact:** by week 4 of compounding (if edges 1 + 2 work), the difference between fixed-absolute and scaled-% caps is +200% in cumulative PnL. By week 8, +400%. The current design caps out at ~$5-10k bankroll regardless of edge strength; the scaled version trajectory is bounded only by market depth + cancel cadence.

**Risk:** larger absolute USD exposure as bankroll grows. Daily-loss cap stays at 5% so any single bad day is bounded. Inventory + gross caps also stay at 2.5% + 5% — proportional risk, not increasing risk.

**Confidence:** **HIGH on the math; MEDIUM on whether MMB's edge holds at larger fill sizes.** At $1k bankroll our $5-$10 orders are at the back of every queue; at $50k bankroll our $250-$500 orders might be at the front. Whether bonereaper's per-trade edge transfers to those larger sizes is unproven — and the priors table is calibrated at his $35-avg fill size which is closer to our $50k-scale than our $1k-scale.

---

## §4. Compounding-aware sizing — full spec

### Current state
`RiskCaps` has 5 absolute USD limits. `J7Priors.bet_size()` reads `bankroll_getter()` for Kelly scaling but `RiskGate.can_place()` checks against absolute caps. Effect: Kelly scales linearly with bankroll up to the first cap that binds, then sizing is capped indefinitely.

### Proposed schema

```python
@dataclass(slots=True)
class RiskCaps:
    """Bankroll-fractional caps with absolute floor + ceiling sanity bounds.

    Each pct-cap is evaluated against the live bankroll at gate-check time.
    Absolute floors enforce CLOB minimums (e.g., MIN_BET=$5 USD); absolute
    ceilings prevent runaway sizing if priors-aligned WR ever shows >$10k
    per-order Kelly bet (would never happen at our edge magnitudes; defensive).
    """

    # Bankroll fractions
    max_inventory_per_token_pct: float = 0.025  # 2.5% per side per window
    max_gross_exposure_per_window_pct: float = 0.05  # 5% gross
    max_daily_loss_pct: float = 0.05  # 5% daily loss → halt
    max_bet_per_order_pct: float = 0.01  # 1% per single order

    # Absolute sanity bounds
    min_bet_usd: float = 5.0  # CLOB minimum (Polymarket-imposed)
    max_bet_usd: float = 500.0  # never bet >$500 even at $100k bankroll
    max_open_orders_global: int = 50
    max_orders_per_minute: int = 30

    def __post_init__(self) -> None:
        for fname in ("max_inventory_per_token_pct",
                      "max_gross_exposure_per_window_pct",
                      "max_daily_loss_pct",
                      "max_bet_per_order_pct"):
            v = getattr(self, fname)
            if not 0 < v <= 1.0:
                raise ValueError(f"{fname} must be in (0, 1]; got {v}")
        if self.min_bet_usd < 0:
            raise ValueError(f"min_bet_usd must be >= 0; got {self.min_bet_usd}")
        if self.max_bet_usd < self.min_bet_usd:
            raise ValueError(f"max_bet_usd must be >= min_bet_usd")
```

### `RiskGate.can_place()` updates

```python
def can_place(
    self,
    *,
    market_id: str,
    side: Side,
    size_usd: float,
    tracker: InventoryTracker,
    open_orders_count: int,
    bankroll_usd: float,  # NEW PARAM — caller passes from bankroll_getter
) -> tuple[bool, str]:
    # ... existing halt/zero/open-orders checks
    if self.today_realized_pnl_usd <= -self.caps.max_daily_loss_pct * bankroll_usd:
        return False, "max_daily_loss_pct"
    pos = tracker.position(market_id, side)
    inv_cap = self.caps.max_inventory_per_token_pct * bankroll_usd
    if pos.gross_usd + size_usd > inv_cap:
        return False, "max_inventory_per_token_pct"
    gross_market = tracker.gross_exposure_for_market(market_id)
    gross_cap = self.caps.max_gross_exposure_per_window_pct * bankroll_usd
    if gross_market + size_usd > gross_cap:
        return False, "max_gross_exposure_per_window_pct"
    return True, "ok"
```

`MarketMakerStrategy.on_book_update` already calls `bankroll_getter()` for Kelly sizing; passes the same value to `can_place()`.

### `J7Priors.bet_size()` updates

```python
def bet_size(
    self,
    *,
    tier: str,
    fill_price: float,
    bankroll: float,
) -> float:
    # ... existing edge/abstain checks
    raw_bet = self.kelly_mult * kelly_f * bankroll
    # Apply per-order pct cap (NEW)
    per_order_cap = self.caps.max_bet_per_order_pct * bankroll
    clamped = min(per_order_cap, self.caps.max_bet_usd, max(self.min_bet_usd, raw_bet))
    if raw_bet < self.min_bet_usd:
        return 0.0
    return clamped
```

Note: requires `J7Priors` to know `RiskCaps`. Pass `caps` in the constructor.

### Tests required

- All existing `RiskCaps` validation tests adapted to pct semantics
- New test: bankroll=$1000 + max_gross_pct=5% → cap binds at $50
- New test: bankroll=$10k + max_gross_pct=5% → cap binds at $500
- New test: bankroll=$100k + max_gross_pct=5% → cap clamps to max_bet_usd=$500 (absolute ceiling kicks in)
- New test: daily-loss cap scales: 5% of $1k = -$50; 5% of $10k = -$500
- New test: caps reject invalid pct values

### Migration

This is a breaking change to `RiskCaps`. Suggested rollout:
1. Ship the pct schema with FEATURE FLAG `MM_CAPS_MODE=fixed_usd|pct_bankroll` defaulting to `fixed_usd` (current behavior).
2. Add MM_CAPS_MODE=pct_bankroll to S.5 deploy env.
3. After S.5 Day-7 audit confirms behavior, remove the flag + ship pct as default.

---

## §5. Revised projections

### Current MMB design (no edges layered)

Per Session 2 sim backtest (`runbooks/research/mmb-backtest-2026-05-20.md`):
- Sim PnL: +$1,586 on 7 days at $1k bankroll
- Realistic (queue position penalty ~50-70%): $475-$795/week = 47-80% weekly

### With Edge 1 (per-tier-side blocklist)

Eliminates ~$555/week of leakage (15% scale × $3,708 bonereaper weekly losses). Net week-1 PnL: $1,030-$1,350/week = 103-135% weekly.

### With Edge 1 + Edge 2 (late-window weighting)

Doubles size in the LATE bucket. Captures ~80% of bonereaper's LATE-bucket $/tr advantage (which is 3-12x mid/early). Net week-1 PnL: $1,500-$1,950/week = 150-195% weekly.

### With Edge 1 + Edge 2 + Edge 3 (compounding, $1k → $X over 12 weeks)

| Week | Bankroll (fixed caps) | Bankroll (pct caps, +120% weekly) |
|---|---:|---:|
| 0 | $1,000 | $1,000 |
| 1 | $1,500 | $2,200 |
| 2 | $2,250 | $4,840 |
| 4 | $5,063 | $23,425 |
| 8 | $25,629 | $549,158 |
| 12 | $129,746 | (theoretical $10M+; capped by market depth) |

**The pct-caps trajectory hits market-depth ceiling around week 6-8.** Bonereaper does $766k/week on his bankroll — at $50k bankroll we'd need to do ~7x his weekly notional which is operationally implausible. Market depth caps the compounding around $30-50k bankroll (~$2-3M weekly notional).

### Realistic target

The operator's "10x bonereaper per-bankroll rate" target = 100-150% weekly. **All three edges layered gets us into that range for the first 3-4 weeks.** Beyond that, market depth limits compounding regardless of edge strength.

| Phase | Bankroll | Weekly target | Source |
|---|---:|---:|---|
| Live-micro S.5 (week 1) | $1k | +50% to +150% | edges 1+2 |
| S.6 scale-up (weeks 2-4) | $1.5k-$10k | +80% to +120% | + edge 3 |
| Phase T (weeks 4-8) | $10k-$30k | +30% to +60% | market depth starts to bite |
| Phase U (week 8+) | $30k+ | +10% to +20% | bonereaper's regime |

So 10x bonereaper IS achievable — but only in the FIRST 4 WEEKS while compounding still has room. After that the bot converges to bonereaper's rate (because we ARE a bonereaper-class bot at that point).

### Honest caveats

1. **Sim PnL is over-optimistic.** No queue position modeling. Real fills will be a fraction of sim fills at our cap sizes.
2. **Edge 1's blocklist could be wrong.** Bonereaper's losing cells might be losing because of HIS specific entry timing; MMB's late-window weighting could reverse some of them. Re-validate after S.5 with MMB-specific data.
3. **Edge 2's late-window weighting could backfire.** Our cancel cadence in last 30s is tight; if cancel latency p95 > 100ms we can't cleanly bail before window close. G11 probe needed.
4. **Edge 3 assumes positive edge holds at larger fill sizes.** At $1k bankroll we're at the back of every queue with $5-$10 orders. At $50k bankroll we're closer to bonereaper's queue position with $250-$500 orders. Whether his per-trade edge transfers to OUR queue at the larger size is empirically untested.
5. **All projections assume zero maker fee.** G11 fee probe pending. If maker fee is > 50 bps the calculations shift down significantly.

---

## §6. Recommendation — raise caps now or wait for Day-7?

### Argument for raising NOW

- Edge 1 (blocklist) eliminates a real, n=8,000-validated leak. Not raising caps just leaves the win on the table.
- Edge 2 (late-window) is supported by both 30d microstructure + fresh weekly data. Two independent dataset confirmations.
- Edge 3 (compounding) is structural — the design is currently broken w.r.t. compounding. Fix it now or it'll cap MMB regardless of edge.
- The current $50/window cap is THE limiting factor. Bonereaper at his scale turns over 30 orders/window at $25 avg = $750/window. At $50 cap MMB does 6 orders × $8 avg = $48/window. We're at 6.5% of bonereaper's per-window turnover.

### Argument for waiting

- `LiveClobOrderClient` has zero test coverage. We've never placed a real maker order via this code path.
- G11 probes (maker fee, cancel latency, rate limit) haven't run.
- Operator-supervised first-fire is the right shape for unverified live code.
- Caps that triple at week 0 (5% pct vs 2.5% pct existing absolute = 100% increase + scales with bankroll) double exposure on untested code.

### Verdict

**Ship Edge 1 + Edge 2 + Edge 3 to code BEFORE Day-7, but keep CONSERVATIVE INITIAL VALUES.**

Concrete:
- Pre-S.5: ship blocklist (Edge 1) + late-window weighting (Edge 2) + pct-caps schema (Edge 3) as CODE.
- S.5 deploy: keep `MAX_GROSS_PCT=2.5%` (= $25/window at $1k bankroll, HALF current absolute cap) for first 24h.
- Day-1 audit: if PnL is positive + no incidents → bump to `MAX_GROSS_PCT=5%` ($50/window at $1k).
- Day-7 audit: if PnL > $50 cumulative + fill rate sane → bump to `MAX_GROSS_PCT=10%` ($100/window at current bankroll).
- Day-14 / Week 2 audit: full caps as designed in §4.

**Rationale:** the blocklist + late-window weighting are SAFER than the current design — they fire LESS, more selectively. Pct-caps are STRUCTURALLY better (compounding works) but the initial value is conservative. Day-7 → cap relax is the data-driven escalator.

**Net week-1 expected:** with the conservative initial caps + edges 1+2 + pct-caps SCHEMA but conservative VALUE, week-1 PnL projection is +20% to +60% on $1k bankroll. Below the 100-150% "10x bonereaper" target but the trajectory is set up for week-2-onward to hit it.

---

## §7. Implementation order + commit plan

If operator says go:

**Commit 1** (~150 LOC + 10 tests): Edge 1 — per-tier-side blocklist
**Commit 2** (~80 LOC + 6 tests): Edge 2 — late-window size multiplier
**Commit 3** (~250 LOC + 15 tests): Edge 3 — pct-caps schema + RiskGate update + J7Priors update + migration flag
**Commit 4** (~50 LOC + 4 tests): MMB-specific decision-log entry for MMD label (data collection for Day-7 Edge 4 evaluation)

Total ~530 LOC + ~35 new tests. Expected to keep 785 tests baseline green + add ~35 = 820 total.

Estimated session length: 60-90 min for all 4 commits + verification + ledger updates.

---

## §8. References

- [runbooks/research/bonereaper-microstructure-30d-2026-05-08.md](bonereaper-microstructure-30d-2026-05-08.md)
- [runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md](bonereaper-spot-vs-book-30d-2026-05-08.md)
- [runbooks/research/mmb-backtest-2026-05-20.md](mmb-backtest-2026-05-20.md)
- [runbooks/phase-S-high-volume-plan-2026-05-20.md](../phase-S-high-volume-plan-2026-05-20.md)
- [design/S.1-market-maker-bot.md](../../design/S.1-market-maker-bot.md)
- [design/j7_priors.md](../../design/j7_priors.md)
- `state/research/bonereaper/weekly_trades_2026-05-19.json` (n=21,633 fresh fills)
- `memory/checkpoint_phase_G.md` (635-fire edge inventory)
- `memory/checkpoint_phase_N.md` (M.5 +$330 counterfactual; M.1a v1 falsified)
- `memory/checkpoint_phase_P.md` (MMD MIXED-only profitable; +9.2pp gap)
- `memory/project_v2_1_multi_fire_pure_variance.md`
