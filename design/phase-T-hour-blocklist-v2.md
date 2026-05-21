# design/phase-T-hour-blocklist-v2 — extend J.2 to per-(tier, hour) pairs

**Phase:** T (directional revival), Improvement #1.
**Author:** 2026-05-21.
**Status:** locked.
**Anti-vibe rule #1:** this doc precedes the src/ change.

---

## §1. Why

`spot_aware_v2_1.py:381-393` implements J.2 as a 2D intersection: a fire abstains iff `hour ∈ hour_blocklist_utc AND tier ∈ hour_blocklist_tiers`. Configurable via env vars `SPOT_AWARE_HOUR_BLOCKLIST_UTC` + `SPOT_AWARE_HOUR_BLOCKLIST_TIERS`. Both default empty.

Current shipped config (per `DEFAULT_HOUR_BLOCKLIST_*` + H.5 audit 2026-05-13):
> tier `70-85%` × hours `{22, 23, 0}` UTC

Phase N forensic ([runbooks/research/phase-N-forensic-summary.md:79-94](../runbooks/research/phase-N-forensic-summary.md)) identified an additional bleed band:
> tier `30-50%` × hours `{05, 06, 17, 21, 23, 0}` UTC, summing to **−$1,748 across 5 days** (n=131)

The two bands share `{23, 0}` but otherwise have disjoint hours. **The current intersection structure cannot express this:** adding `30-50%` to the tier set + adding `{05, 06, 17, 21}` to the hour set would also block tier `70-85%` in `{05, 06, 17, 21}`, which the H.5 data shows is profitable (e.g. 21Z × 70-85% was +$2.13/tr). A side-effect-free extension requires a true per-(tier, hour) pair structure.

## §2. The change — minimal-surface

Replace the intersection check at `spot_aware_v2_1.py:392` with a set-membership check on `(hour, tier)` tuples.

**New canonical param:**
```python
hour_blocklist_pairs: tuple[tuple[int, str], ...] = ()
# e.g. ((23, "70-85%"), (0, "70-85%"), (5, "30-50%"), (21, "30-50%"))
```

**New canonical env var:**
```bash
SPOT_AWARE_HOUR_BLOCKLIST_PAIRS="23:70-85%,0:70-85%,5:30-50%,21:30-50%"
# format: "<hour>:<tier>" comma-separated; whitespace tolerated; canonical tier labels
```

**Backwards compatibility:**
- The two existing params `hour_blocklist_utc` + `hour_blocklist_tiers` stay accepted at the constructor.
- At init time, if either is set, expand to all `(h, t)` combinations and merge into `_hour_blocklist_pairs`.
- The two existing env vars stay parsed for the same reason.
- Validation: cross-param consistency (hours in [0, 23], tiers from canonical set) preserved; existing ValueErrors raised by the same logic, plus a new ValueError for malformed `PAIRS` strings.

**Check logic (replaces lines 390-393):**
```python
if self._hour_blocklist_pairs:
    hour = _dt.datetime.fromtimestamp(now_ts_utc_ns / 1_000_000_000, tz=_dt.UTC).hour
    if (hour, tier) in self._hour_blocklist_pairs:
        return None
```

## §3. Default value — Phase T Improvement #1 ships *only* the data structure

Per the Phase T plan §4 task 6: ship the structural change first, leave the defaults empty. Operator opts in via env var. **Reason:** code change is small and reviewable in isolation; behavior change (the actual hours-to-block) is a config decision that lives in `runbooks/systemd/bot-staging.service` or wherever the operator chooses to wire it. Separating structure from value lets us land the structural commit with high confidence and gate the value change on operator review of the prevented-loss numbers (§4).

The blocklist this enables (proposed by Phase N, validated by data — operator wires when re-deploying):

```bash
SPOT_AWARE_HOUR_BLOCKLIST_PAIRS=\
"22:70-85%,23:70-85%,0:70-85%,5:30-50%,6:30-50%,17:30-50%,21:30-50%,23:30-50%,0:30-50%"
```

This expresses both the existing H.5 block + the Phase N extension as 9 explicit pairs. No accidental cross-contamination.

## §4. Prevented-loss quantification — already in the forensic

From [runbooks/research/phase-N-forensic-summary.md:81-90](../runbooks/research/phase-N-forensic-summary.md):

| Hour | Tier 30-50% n | WR | PnL |
|---|---:|---:|---:|
| 05 UTC | 14 | 35.7% | −$266 |
| 06 UTC | 16 | 37.5% | −$251 |
| 17 UTC | 20 | 20.0% | −$259 |
| 21 UTC | 28 | 28.6% | **−$516** |
| 23 UTC | 30 | 33.3% | −$288 |
| 00 UTC | 23 | 34.8% | −$168 |
| **Total** | **131** | — | **−$1,748** |

5-day window, n=131 affected fires. **Total prevented loss: ~$1,748** if all 6 hours blocked. Far exceeds the Phase T prompt §4 task 5 threshold of "≥+$500 prevention" required to ship.

Caveat: the 5-day window is small. The hour pattern could regime-shift over time (Phase K-M was a single market regime). Phase T Improvement #2 (SURV-cell-flip detector, rolling WR) addresses that orthogonally; this improvement assumes the hour pattern is sticky enough to be worth blocking until a better mechanism arrives.

## §5. What we are NOT doing in this change

- **Not adding boost multipliers** for win-hours. Per Phase T prompt §3 #5b: block-only first, no boost.
- **Not** introducing rolling-WR adaptation (that's Improvement #2, separate commit).
- **Not changing** the canonical tier labels (CANONICAL_TIERS in tier_labels.py).
- **Not removing** the existing `hour_blocklist_utc` / `hour_blocklist_tiers` params (backward-compat preserved).
- **Not enabling** the blocklist by default (`DEFAULT_HOUR_BLOCKLIST_PAIRS = ()` ; operator wires via env).

## §6. Tests required

Extends the existing 5 tests at `tests/strategies/test_spot_aware_v2_1.py:685-790`:

1. `test_v2_1_blocks_at_pair_blocklist` — pair `(23, "70-85%")` blocks; otherwise identical to the existing line-687 test.
2. `test_v2_1_pair_blocks_only_exact_match` — pair `(23, "70-85%")` does NOT block at `(23, "30-50%")` even though both elements are present in different pairs configured.
3. `test_v2_1_pair_does_not_block_outside_pair` — pair `(23, "70-85%")` does NOT block at `(12, "70-85%")`.
4. `test_v2_1_old_envvar_back_compat` — setting `hour_blocklist_utc=(23,) + hour_blocklist_tiers=("70-85%", "30-50%")` expands to pairs `{(23, "70-85%"), (23, "30-50%")}`; both 23Z fires abstain; behavior identical to the old code path.
5. `test_v2_1_pairs_env_var_parsing` — parses `"23:70-85%,5:30-50%"` into the right pair set; rejects malformed strings; rejects out-of-range hours.
6. `test_v2_1_pairs_and_old_params_merge` — both `pairs=(...)` AND `hour_blocklist_utc/tiers=...` set → pairs are the union.
7. (regression) all 5 existing J.2 tests still pass unchanged.

## §7. Acceptance

- All 674 existing tests still pass (no regressions)
- 5+ new tests for the pair structure pass
- `mypy --strict src/` clean
- `ruff check` clean
- Module docstring at `spot_aware_v2_1.py` updated to reference the new param
- Commit message cites this design doc + the Phase N forensic table
- No live deploy — Phase T stays dormant per prompt §1

## §8. Out-of-scope (future improvements)

- **Improvement #5** (per-cell-per-hour 3D edge table with boost multipliers) generalizes this to `dict[(int, str), float]` mapping `(hour, tier) → multiplier`. The pair-set structure here is the natural subset (multiplier=0 = blocked, absent = pass-through).
- **Improvement #2** (SURV-cell-flip detector) will use rolling-WR per (tier, |Δbps| bucket); orthogonal to this change.
- **Per-side hour blocklist** (e.g. block UTC 21 × 30-50% × side=UP only) is not in this change; the Phase N data is per-tier not per-tier-side, so we'd be guessing.
