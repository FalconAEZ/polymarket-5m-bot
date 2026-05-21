# design/phase-T-per-cell-fire — fire-per-cell semantics

**Phase:** T (directional revival), Improvement #1.5.
**Author:** 2026-05-21.
**Status:** locked.
**Anti-vibe rule #1:** this doc precedes the src/ change.

---

## §1. Why

Current behavior: `multi_fire_cap` (default 1, operator-set to 1 on VPS) caps total fires per window REGARDLESS of which cell each fire targets. Once the cap binds, subsequent ticks abstain even if they identify a DIFFERENT, independent edge.

Per `memory/project_v2_1_multi_fire_pure_variance.md`: raising the cap naively (cap=2 vs cap=1) showed identical 41.9% WR on live H.5 data — pure variance amplification, NOT edge addition. The reason: the second fire was usually on the SAME cell as the first, so it just doubled capital exposure without diversifying.

This change adds **per-cell semantics**: at most 1 fire per `(tier, side, |Δbps| bucket)` cell per window. A second fire is only allowed if it targets a DIFFERENT cell. The outer `multi_fire_cap` stays as a hard circuit breaker.

Operator framing 2026-05-21: "if edge found in same 5 min window again enter trade" — concretely interpreted as: a NEW edge on a DIFFERENT cell within the same window should fire, not just be discarded because the cap binds.

## §2. Cell-key formula — includes side (differs from Improvement #2)

`{tier}|{side}|{'hi' if |Δbps|≥5 else 'lo'}`. Example: `30-50%|UP|hi`, `70-85%|DOWN|lo`.

This DIFFERS from Improvement #2 (cell-flip detector) which uses side-agnostic `{tier}|{lo|hi}`. Two different keys for two different purposes:

- **#2 cell-flip detector**: tracks rolling per-tier-bucket WR to abstain on regime shifts. Side-agnostic because the Phase N forensic data was per-tier-bucket with sides combined.
- **#1.5 per-cell fire**: allows independent fires on UP vs DOWN within a window because they're orthogonal opportunities (one can have edge while the other does too).

Both keys coexist without conflict.

## §3. The change — minimal-surface

```python
# Constructor:
per_cell_fire_enabled: bool = False  # default OFF (legacy behavior)

# State:
self._fires_per_cell_this_window: dict[str, int] = {}

# Reset on WindowBoundary open (alongside existing _fires_this_window=0):
if event.kind == "open":
    self._fires_per_cell_this_window.clear()

# Gate in _maybe_fire — AFTER tier/d_bps computed, BEFORE H.2.12 + Phase T#2 detector:
if self._per_cell_fire_enabled:
    cell_key_with_side = f"{tier}|{side_guess}|{'hi' if abs(d_bps) >= 5 else 'lo'}"
    if cell_key_with_side in self._fires_per_cell_this_window:
        return None  # this cell already fired this window

# After successful fire (in the final return path):
if self._per_cell_fire_enabled:
    self._fires_per_cell_this_window[cell_key_with_side] = 1
    # Always reset _fired_for_window so the NEXT tick can try OTHER cells,
    # not just at cap-headroom time.
    self._fired_for_window = None
```

Interaction with `multi_fire_cap` (UNCHANGED):
- The legacy `_fires_this_window >= self._multi_fire_cap` check still binds at the top of `_maybe_fire`.
- Operator should raise `MULTI_FIRE_CAP` from 1 to a higher value (e.g. 4) when enabling per-cell, otherwise the outer cap still throttles to 1 total fire.
- Together: at most `multi_fire_cap` fires across at most `multi_fire_cap` distinct cells.

## §4. Why this isn't the H.5 "variance amplifier" finding

The H.5 measurement (cap=2 vs cap=1 → identical 41.9% WR) tested the LEGACY cap-only mechanism, where the second fire was free to land on the same cell (typically the same tier × side because tier doesn't change much within a window). Per-cell semantics make that variance-amplification mode impossible by construction.

The remaining question — "does firing a DIFFERENT cell add real edge?" — is not answered by the H.5 data. Anti-vibe pushback noted: this is a theoretical improvement, not an empirically validated one. **Phase T soak gate measures whether it works in practice.** If per-cell fires net negative cumulative over 14 days, revert.

## §5. Default value — opt-in only

`per_cell_fire_enabled=False` by default. Operator opts in via env `SPOT_AWARE_PER_CELL_FIRE_ENABLED=true`. Legacy strategies + existing tests + Phase P-era VPS deploy unchanged.

When enabled, operator also raises `MULTI_FIRE_CAP` from 1 to a number that makes per-cell meaningful (≥4 recommended for the 4-cell space of `{30-50%, 70-85%} × {UP, DOWN}` in active markets after J.1.5 + tier-50-70% filtering).

## §6. Tests required (5+)

1. `test_v2_1_per_cell_disabled_legacy_unchanged` — `per_cell_fire_enabled=False`, multi_fire_cap=2: 2 fires on the same cell allowed (the H.5 legacy behavior); 3rd blocked by outer cap.
2. `test_v2_1_per_cell_same_cell_2nd_fire_abstain` — `per_cell_fire_enabled=True`, multi_fire_cap=4: fire on `30-50%|UP|hi`, then attempt same cell → abstain. Outer cap not yet binding.
3. `test_v2_1_per_cell_different_cell_2nd_fire_allowed` — same setup, fire on `30-50%|UP|hi`, then `30-50%|DOWN|hi` → both fire.
4. `test_v2_1_per_cell_outer_cap_still_binds` — `per_cell_fire_enabled=True`, multi_fire_cap=2: fires on 2 distinct cells, attempt 3rd distinct cell → outer cap blocks.
5. `test_v2_1_per_cell_window_open_resets` — fire on a cell, WindowBoundary close + open of next window → same cell can fire again (state cleared).
6. `test_v2_1_per_cell_side_in_key` — fire on `30-50%|UP|hi` does NOT block `30-50%|DOWN|hi` (validates side is part of the key).

## §7. Acceptance

- Existing 694 tests still pass (no regressions)
- 6+ new tests pass
- mypy --strict clean
- ruff + import-linter clean
- Default behavior unchanged (`per_cell_fire_enabled=False`)
- Env-var `SPOT_AWARE_PER_CELL_FIRE_ENABLED` opts in

## §8. Out of scope

- Per-cell sizing (each cell could have its own Kelly multiplier) — defer
- Per-cell rolling history (already covered by Improvement #2)
- Cross-window per-cell rate-limit (e.g. "no more than 3 fires/hour per cell") — defer

## §9. Related

- [phase-prompts/phase-T-directional-revival-2026-05-20.md](../phase-prompts/phase-T-directional-revival-2026-05-20.md) §3 (the 6 improvements; #1.5 was added later as a Session 2 ask)
- [design/phase-T-cell-flip-detector.md](phase-T-cell-flip-detector.md) — Improvement #2 (different cell-key formula)
- [design/phase-T-hour-blocklist-v2.md](phase-T-hour-blocklist-v2.md) — Improvement #1 (per-(hour, tier) pair semantics; this is the same "per-cell" pattern applied at a different gate)
- `memory/project_v2_1_multi_fire_pure_variance.md` — why naive cap raise doesn't add edge; this design specifically addresses that finding
