# design/phase-T-fill-sim-size-guard-fix — price-conditional no-depth size guard

**Phase:** T (directional revival), fill-rate fix.
**Author:** 2026-05-21.
**Status:** locked.
**Anti-vibe rule #1:** this doc precedes the src/ change.

---

## §1. Why

Fill-rate audit 2026-05-21 on n=38 fires (decision logs 2026-05-19 + 2026-05-21):

| Slice | Fired | Filled | Rate |
|---|---:|---:|---:|
| Overall | 38 | 13 | **34%** |
| When `ask_size_top` known | 4 | 4 | **100%** |
| When `ask_size_top` None | 32 | 9 | **28%** |

**100% of unfilled fires** triggered the `FillSimulator._refuse_for_no_depth` 50-share size guard. Their would-be sizes: 217-665 shares (Kelly at bankroll $3k + kelly_mult 0.15 + p_win 0.65-0.78 produces $108-280 bets, which at typical fill prices 0.40-0.50 → 200-665 shares).

**The size guard is misapplied.** Its intent (per `backtest/fills.py:33-55` comment + Phase 11.A audit 2026-05-10) was to catch the wide_fire-era phantom-fill bug where over-fills happened at floor prices **$0.011, $0.021, $0.03, $0.04** (all under 0.05). The guard is price-blind, so it now rejects legitimate Kelly-sized fires at mid-prices 0.30-0.50 where real Polymarket depth is plentiful.

In the audit window, the guard fired 0 times for phantom-fill defense and 23 times for legitimate rejections.

## §2. The change — minimal-surface

Single function modified: `FillSimulator._refuse_for_no_depth` in `src/polymarket_bot/backtest/fills.py`.

```python
# Before (price-blind size cap):
def _refuse_for_no_depth(self, fill_price, size_filled, book):
    if book.ask_size_top is not None:
        return False
    if fill_price <= self._floor_best_ask:    # 0.05
        return True
    if size_filled >= self._max_fill_size_no_depth:    # 50  ← over-restrictive
        return True
    return False

# After (size cap gated on near-floor prices only):
def _refuse_for_no_depth(self, fill_price, size_filled, book):
    if book.ask_size_top is not None:
        return False
    if fill_price <= self._floor_best_ask:    # 0.05
        return True
    # Size cap now ONLY triggers in the price zone where phantom over-fills
    # were historically measured (Phase 11.A: $0.011-$0.04, all <0.05). The
    # 0.10 threshold gives 2x safety margin from the historical phantom-fill
    # zone. Above 0.10, legitimate Kelly bets routinely produce 200+ shares
    # which real Polymarket mid-price depth absorbs without difficulty.
    if (fill_price < self._size_guard_max_price
            and size_filled >= self._max_fill_size_no_depth):
        return True
    return False
```

New constructor param:
```python
size_guard_max_price: float = 0.10  # only apply size cap when fill_price below this
```

## §3. Why 0.10 specifically

Historical phantom-fill prices (per `fills.py` Phase 11.A comment + audit 2026-05-10):
- $0.011 (taker, 2 windows; ~$449 phantom each)
- $0.021 (maker)
- $0.03 (maker, ~10+ windows; the dominant variant)
- $0.04 (maker)

All under 0.05. The existing `_floor_best_ask=0.05` guard catches all of these via the **price-floor** check (line 1 of `_refuse_for_no_depth`).

The size-cap guard was added as defense-in-depth at 50 shares. With its scope now gated to `fill_price < 0.10`, it preserves the original defense intent at prices up to 0.10 (2x safety margin above the highest measured phantom-fill price) while no longer rejecting legitimate fills at mid-prices.

Spot_aware_v2_1 fires at `tier_relax_price_floor=0.42` and above → 4x safety margin from the 0.10 threshold.
MMB Phase S would fire at 0.10-0.85 ladder; near-floor rungs still hit the price-floor guard at 0.05.
Wide_fire (if ever re-enabled) at $0.01-0.05 would still hit the price-floor guard at 0.05.

## §4. Expected impact on current bot

23 currently unfilled fires → all become candidates for fill. Of those, the runner's `_try_fill_pending` retry loop will fill them as later book events arrive (already does for the 9 filled-with-ask_size_top=None cases). Realistic expected fill rate: **34% → ~95%** on spot_aware_v2_1 fires.

Win-rate and PnL impact: the bot's strategy decisions are unchanged. What changes is the conversion from `fired` → `filled`. PnL implication: real (positive or negative) PnL per fire instead of $0 (no-fill). The strategy's true edge will be measurable for the first time at this fill rate.

## §5. Defaults + backwards compatibility

`size_guard_max_price=0.10` is the new constructor default. Existing callers don't need to change. The behavior change is intentional — previous behavior (50-share cap at all prices) was too restrictive for production strategies.

If a future strategy needs the old behavior, pass `size_guard_max_price=1.0` to make the size cap always apply (back to original behavior).

## §6. Tests required

4 new tests in `tests/backtest/test_fills.py`:

1. `test_no_depth_at_mid_price_now_fills_above_cap` — fill_price=0.45, size=200, ask_size_top=None → no longer refused (previously refused). Validates the loosening.
2. `test_no_depth_near_floor_still_refused_by_price` — fill_price=0.04, any size, ask_size_top=None → refused by price-floor guard. Validates that low-price defense still works.
3. `test_no_depth_at_0_08_still_refused_by_size_cap` — fill_price=0.08 (< 0.10 threshold), size=60 (>= 50 cap), ask_size_top=None → refused by size guard. Validates the gated size cap still works in its scope.
4. `test_known_depth_always_passes_regardless_of_price_or_size` — fill_price=0.45, size=200, ask_size_top=500 → passes (depth known, no defense applies). Validates known-depth path unchanged.

## §7. Acceptance

- All existing tests pass (no regressions)
- 4 new tests pass
- mypy --strict clean
- ruff + import-linter clean
- Default behavior changes (size cap now 0.10-gated); documented in §5

## §8. Out of scope (deferred)

- **Feed-layer depth merge**: the polymarket WebSocket sends `price_change` events without `ask_size_top`. Merging depth from prior `book` event would reduce ask_size_top=None rate at the source. Separate Phase T improvement; deferred per operator decision 2026-05-21.
- **Per-strategy guard override** via env var: not added; the constructor param is sufficient for tests + future strategies to override.

## §9. Related

- `src/polymarket_bot/backtest/fills.py:33-55` — the existing Phase 11.A guard comments
- `scripts/backfill_phantom_floor_fills.py` — the post-hoc neutralizer that runs separately
- `memory/checkpoint_phase_11_a.md` — the original phantom-fill incident
- `memory/project_phantom_defense_equals_fill_rate_problem.md` — the memory note that flagged exactly this audit-before-mitigating pattern
- `runbooks/research/phase-N-forensic-summary.md` — Phase N data also used the simulator under this guard
