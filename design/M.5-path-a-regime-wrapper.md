# Design — M.5 Path A Regime-Aware Wrapper (Phase M Session 6)

> Purpose: surgically gate Path A (tier 70-85% x DOWN side) fires by the
> DYNAMIC break-even computed from realized prices of recent Path A fires.
> When rolling WR drops below the dynamic break-even, Path A self-disables.
> Recovers when rolling WR climbs back above break-even.
>
> Note: this design doc was reconstructed after the M.5 code commit
> (84d33b1) because the original write call was lost mid-session. The code
> already matches this spec — verify with `git show 84d33b1` against §4-6.

## 1. The problem

Path A in the 4-day Phase K soak:
- Total: n=183, WR 77.6%, $/tr -$0.28
- Break-even: mean price 0.738 → 73.8% required WR for $0/tr
- 3.8pp above break-even (thin margin)
- 20-fire rolling windows ranged 60-95%; window #121-140 hit 60% WR contributing -$233

When Path A's recent WR drops below the dynamic break-even, every Path A fire is negative-EV. The bot keeps firing because the strategy doesn't know its own historical outcomes. M.5 fixes that.

## 2. The gate

```
path_a_active = (rolling_wr_n30 >= mean_price_n30 + MARGIN) OR (n_settled < MIN_SAMPLES)

  rolling_wr_n30 = wins / n_settled over the last 30 settled Path A fires
  mean_price_n30 = mean(price_limit) over the same fires (= break-even WR)
  MARGIN         = 0.02   (2pp safety)
  MIN_SAMPLES    = 20     (don't gate before evidence accumulates)
```

If gate evaluates false at fire-decision time → abstain (return None).

## 3. Why dynamic break-even (not fixed 78%)

- Path A's actual mean price was 0.738, not 0.78
- Real break-even at 0.738 = 73.8%
- Measured WR 77.6% is 3.8pp ABOVE the real break-even (not below a wrong 78% threshold)

Dynamic break-even adapts as tier distribution shifts.

## 4. Public surface

### 4.1 NEW src/polymarket_bot/strategies/path_a_wr_metrics.py

```python
@dataclass(frozen=True)
class PathAMetrics:
    rolling_wr: float | None
    mean_price: float | None
    n_settled: int
    n_total_in_buffer: int

def compute_path_a_metrics(
    decisions_root: Path,
    *,
    lookback_n: int = 30,
    min_samples: int = 20,
    now_ns: int,
    lookback_days: int = 5,
) -> PathAMetrics: ...
```

Reads state/decisions/*.jsonl, filters to Path A (tier 70-85% x DOWN), joins with settled + settled_correction (correction priority). Returns empty metrics on I/O error. Sync; cached 60s in run_paper.py.

### 4.2 Strategy hookup (spot_aware_v2_1.py)

Three new kwargs:
- `path_a_wr_getter: Callable[[], PathAMetrics] | None = None` (default → gate off)
- `path_a_wr_min_samples: int = 20`
- `path_a_wr_break_even_margin: float = 0.02`

In `_maybe_fire` after tier+side computed, after block_up/block_down checks, BEFORE super()._maybe_fire:

```python
if (
    self._path_a_wr_getter is not None
    and tier == "70-85%"
    and side_guess == "DOWN"
):
    metrics = self._path_a_wr_getter()
    if (
        metrics.rolling_wr is not None
        and metrics.mean_price is not None
        and metrics.n_settled >= self._path_a_wr_min_samples
        and metrics.rolling_wr < metrics.mean_price + self._path_a_wr_break_even_margin
    ):
        return None
```

### 4.3 Runner wiring (scripts/run_paper.py)

```python
if _env_bool("REGIME_M5_PATH_A_GATE_ENABLED", False):
    _cache = {"metrics": None, "ts_ns": 0}
    def _getter() -> PathAMetrics:
        if cached and not expired (60s TTL): return cached
        fresh = compute_path_a_metrics(...)
        return fresh
    v21_path_a_wr_getter = _getter
```

## 5. Env-vars (DARK ship)

| name | default | role |
|---|---|---|
| REGIME_M5_PATH_A_GATE_ENABLED | false | Master switch |
| REGIME_M5_LOOKBACK_N | 30 | Recent Path A fires to average |
| REGIME_M5_MIN_SAMPLES | 20 | Don't gate before this n |
| REGIME_M5_BREAK_EVEN_MARGIN | 0.02 | Require WR >= break-even + this |

## 6. Tests (11 in tests/strategies/test_spot_aware_v2_1.py)

Strategy (8): gate_disabled_no_change, gate_above_break_even_fires, gate_below_break_even_abstains, gate_cold_start_passes_through, gate_does_not_apply_to_30_50, gate_does_not_apply_to_up_side, gate_margin_is_respected, gate_margin_zero_strict_breakeven.

Module compute_path_a_metrics (3): handles_empty_log, filters_to_path_a_only, applies_corrections.

## 7. Promote gate (5 days live)

- Path A fire rate drops during edge-decay periods (sanity)
- Path A WR over 5 days > mean_price + margin (gate held)
- Cum-PnL uplift >= +$100 vs prior baseline

## 8. Rollback

env-flip REGIME_M5_PATH_A_GATE_ENABLED=true → false + restart. 30s. Reverts to H.2.12 block_up only.

## 9. Honest pushback

- P1: disk I/O cached 60s; negligible
- P2: 30-fire lookback may be noisy; mitigated by 2pp margin + min=20
- P3: mean(price) ≈ break-even WR only for narrow ranges (Path A 0.72-0.79 OK)
- P4: trailing gate not leading — bleeds 5-10 fires during regime transition before gate triggers
- P5: cold-start (n<20) passes through; mitigated by startup log replay
- P6: M.1a v1 chop-abstain may overlap — complementary signals (classifier vs realized-edge)

## 10. Out of scope

- Mirror gate for tier 30-50% (M.5.b)
- Predictive WR (M.4 territory)
