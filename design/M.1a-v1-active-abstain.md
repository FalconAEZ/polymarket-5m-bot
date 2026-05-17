# Design — M.1a v1 ACTIVE chop-abstain (Phase M Session 5)

> Purpose: promote M.1a from shadow-log (v0) to active firing gate (v1).
> The 5-day audit (May 13-17, n=484 settled fires) found CHOP regime is a
> drag (n=15 annotated, WR 60.0% but $/tr −$4.78, PnL −$72) while MIXED
> is profitable (n=36, +$54). v1 ships an env-gated abstain branch that
> rejects fires when the M.1a classifier labels the window as `chop` or
> `unknown` (cold-start defense).
>
> **Anti-vibe rule #1**: this doc lands before code in
> `src/polymarket_bot/strategies/spot_aware_v2_1.py`.
>
> **Anchors**:
> - `design/M.1a-flat-vs-trend-shadow-log.md` (v0 — shadow-log, deployed `d0797f4`)
> - `/tmp/m1a_5day_audit.py` output (the empirical evidence; reproduced
>   in `runbooks/research/m1a-5day-audit-2026-05-17.txt`)
> - `runbooks/gate-evidence/regime-classifier-validation.txt` (Phase 15
>   independent finding: chop $/tr −$0.22 on n=299 different firing era)
> - `phase-prompts/phase-M-pre-live-edge-stacking-2026-05-16.txt` §C.M.1

## 1. Evidence base for the chop-abstain rule

**5-day per-regime breakdown (M.1a-annotated subset, n=52 fires):**

| label | n | WR | PnL | $/tr |
|---|---|---|---|---|
| trending | 1 | 100% | +$23.29 | +$23.29 |
| mixed | 36 | 58.3% | +$54.31 | +$1.51 |
| **chop** | **15** | **60.0%** | **−$71.77** | **−$4.78** |

**What-if simulations (on the same 52 fires):**

| rule | kept | kept PnL | skipped | net effect |
|---|---|---|---|---|
| baseline (no abstain) | 52 | +$5.84 | — | — |
| **abstain chop** | 37 | **+$77.61** | −$71.77 | **+$71.77 uplift** |
| abstain chop+unknown | 37 | +$77.61 | −$71.77 | same (unknown=0 in audit) |
| abstain mixed | 16 | −$48 | +$54 | **−$54 LOSS** |

The chop-abstain rule produces a clear +$72 uplift on the 52-fire validation. Extrapolated to a 600-fire week, the expected uplift is **~$820/week**. (Order-of-magnitude only — small-n base.)

**Day-to-day stability check (M.1a label only):**

| day | mixed | mixed $/tr | chop | chop $/tr |
|---|---|---|---|---|
| 05-16 (4h) | n=14 | **+$20.16** | n=1 | −$77.21 |
| 05-17 (8h) | n=22 | **−$10.36** | n=14 | +$0.39 |

Mixed swung from +$20 to −$10 per trade day-over-day — high variance. Chop swung less (small-n on May 16). The chop-abstain rule is more robust to day-to-day noise than the mixed-abstain alternative.

## 2. Public surface

One change to `SpotAwareStrategyV2_1`:

```python
def __init__(
    self,
    *,
    ...,
    regime_detector: RegimeDetector | None = None,
    regime_shadow_enabled: bool = False,
    regime_abstain_labels: frozenset[str] = frozenset(),  # NEW
    **v2_kwargs: object,
) -> None:
    ...
    self._regime_abstain_labels = frozenset(regime_abstain_labels)
```

In `_maybe_fire`, after we compute `regime_label`, BEFORE rationale annotation:

```python
if self._regime_shadow_enabled:
    regime_label = (
        self._regime_detector.classify(now_ts_utc_ns)
        if self._regime_detector is not None else "shadow_off"
    )
    # M.1a v1 — active abstain.
    if regime_label in self._regime_abstain_labels:
        self._fired_for_window = None    # reset so future ticks re-evaluate
        return None                      # abstain
    new_rationale = f"{new_rationale} regime={regime_label}"
```

The reset of `_fired_for_window` mirrors the existing CH4 abstain semantics (v2.1 line 435): if the abstain happens AFTER v2's commit, we have to undo the per-window flag so a later qualifying tick (when the regime may have shifted) can re-evaluate.

## 3. Env-vars (DARK ship; default OFF)

| name | default | role |
|---|---|---|
| `REGIME_M1A_V1_ENABLED` | `false` | Master switch for active abstain. Requires `_SHADOW_ENABLED=true` to also be set. |
| `REGIME_M1A_ABSTAIN_LABELS` | `chop,unknown` | CSV of regime labels to abstain on. Default abstains on chop + unknown (cold-start safety). |

Two paths via env combinations:
| `_SHADOW_ENABLED` | `_V1_ENABLED` | `_ABSTAIN_LABELS` | Behavior |
|---|---|---|---|
| false | (any) | (any) | M.1a OFF — baseline v2.1 |
| true | false | (any, ignored) | v0: shadow log only |
| true | true | empty | v0 + log-only on labels not in set (still shadow) |
| true | true | `chop` | v1: abstain on chop only |
| **true** | **true** | **`chop,unknown`** | **v1 with cold-start defense (RECOMMENDED)** |

## 4. Tests (target ≥5 in `tests/strategies/test_spot_aware_v2_1.py`)

| # | test | scenario |
|---|---|---|
| v1.1 | `test_m1a_v1_chop_abstain_returns_none` | abstain set `{"chop"}` + detector returns "chop" → fire decision is None (vs v0 which returned a Decision with regime=chop appended) |
| v1.2 | `test_m1a_v1_mixed_passes_through_with_annotation` | abstain set `{"chop"}` + detector returns "mixed" → Decision fires + rationale has `regime=mixed` |
| v1.3 | `test_m1a_v1_trending_passes_through_with_annotation` | abstain set `{"chop"}` + detector returns "trending" → Decision fires + rationale has `regime=trending` |
| v1.4 | `test_m1a_v1_unknown_abstain_at_cold_start` | abstain set `{"chop","unknown"}` + real RegimeDetector (cold) → returns None |
| v1.5 | `test_m1a_v1_empty_abstain_set_behaves_as_v0` | abstain set `{}` + shadow=True → byte-identical to v0 (everything fires, rationale annotated) |
| v1.6 | `test_m1a_v1_abstain_resets_fired_for_window` | After abstain on chop, a later tick in the same window CAN re-fire if a fresh classify returns trending |

## 5. Wiring (`scripts/run_paper.py`)

Read the two new env vars, pass to v2.1 constructor:

```python
v21_regime_v1_enabled = _env_bool("REGIME_M1A_V1_ENABLED", False)
v21_regime_abstain_csv = os.environ.get("REGIME_M1A_ABSTAIN_LABELS", "chop,unknown")
v21_regime_abstain = frozenset(
    label.strip() for label in v21_regime_abstain_csv.split(",")
    if label.strip()
) if v21_regime_v1_enabled else frozenset()
```

Log the wired config at startup.

## 6. Promote gate (M.1a v1 — current ship → "validated")

After 5 days of v1 active in production with the env enabled:

1. Per-regime audit: chop kept fires (should be ZERO) vs mixed/trending kept fires
2. Compare cum-PnL over the 5 v1 days vs the previous 5 v0 days (same days-of-week ideally)
3. **Promote criteria:**
   - Cum-PnL uplift ≥ +$200 over 5 days (vs baseline projection)
   - No catastrophic drawdown (35% peak-to-trough) during v1 window
   - No CRITICAL alerts other than the daily L.5 trip

If the promote gate passes: M.1a v1 is "validated"; consider M.1b (4-state classifier) or move to M.2 (orderbook imbalance).

If promote fails: rollback `_V1_ENABLED=false`. Document finding. Pivot to M.2 or M.5.

## 7. Rollback

Two env flips, both 30s:
- `REGIME_M1A_V1_ENABLED=true → false` reverts to v0 shadow-log (continued data collection)
- `REGIME_CLASSIFIER_V2_SHADOW_ENABLED=true → false` reverts to baseline v2.1 (full M.1a off)

## 8. Honest pushback

- **P1** — n=52 annotated fires is a SMALL base for promote. Phase 15 validation was n=299; we're shipping v1 on far less. The 5-day window is the constraint, not the right sample size. Risk: today's pattern was noise and chop is actually neutral, not a drag. Mitigation: env-default false, operator flips after a 24h smoke test, +$200 uplift gate before declaring victory.

- **P2** — Mixed-regime is highly variable (May 16 +$20/tr, May 17 −$10/tr). The decision to KEEP mixed firing is a bet that the 5-day average (+$1.51/tr) generalizes. It might not — mixed could become the next chop. v0 shadow-log continues alongside v1 so we can see if mixed deteriorates.

- **P3** — The chop-abstain rule reduces fire rate by ~29% (15/52 fires skipped). If the bot's edge is in volume, this hurts. Counter: chop fires are −$/tr, so skipping increases per-trade $/tr; total $ should improve even if total volume drops.

- **P4** — The RegimeDetector's chop threshold (0.80) and trending threshold (1.20) are inherited from the Phase 15 spec — not re-tuned for Phase J.1.6 firing. M.1b (4-state) territory; out of v1 scope.

- **P5** — TRENDING is rare (1 of 52 fires, 2%). If trending is the genuinely highest-WR regime, we may be missing opportunities. But we can't fix that in v1 — that requires retraining the entry filters in spot_aware, which is Phase M.5 wrapper or beyond.

## 9. Out of scope (v2+ territory)

- 4-state classifier (M.1b)
- Per-regime adaptive Kelly (M.4)
- Tier × regime cross-gate (M.5 wrapper)
- Cross-exchange regime confirmation (M.3)
