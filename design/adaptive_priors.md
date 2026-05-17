# Adaptive priors v1 (Phase J.3)

**Status:** DESIGN LOCK · 2026-05-13.
**Implementation target:** Session 2 of Phase J (estimated +1-3 days
calendar time after Session 1 kickoff).
**Source-of-truth prompt:** phase-prompts/phase-J-edge-exploitation-2026-05-13.txt §J.3.

## 1.  Why adaptive priors (problem statement)

v2.1's CH3 cell relies on a static `tier_relax_p_win_fallback=0.48`
(Phase G §5.1 historical 48.1% empirical WR for tier 30-50% × |Δ|<5).
The H.3 audit (2026-05-13) shows this is brittle:

- CH3 cell WR trajectory across the H.5 soak DETERIORATED monotonically:
  - +3.8h: WR 48.1% on n=52 ($/tr −$0.39)
  - +6.8h: WR 44.8% on n=105 ($/tr −$0.74)
  - +7.0h: WR 43.1% on n=109 ($/tr −$1.65)

The static prior cannot self-correct. As the cell's true WR drifts
below the static estimate, the EV gate over-admits, fires accumulate
under negative EV, and the bleed compounds.

Adaptive priors replace the static fallback with a **Bayesian-blended
rolling estimator** that pulls each cell's effective p_win toward its
own measured WR while anchoring on the static value when sample size
is thin. The estimator is per-cell and updates every settled fire.

## 2.  Why this beats regime detection

Regime detection (Phase 15 dark-shipped REGIME_GATE_ENABLED, J.5) requires
defining a classifier (5min/10min realized vol ratio). The classifier
is asset-specific (BTC), regime-specific (trending vs chop), and brittle
to regime taxonomy choices. Adaptive priors self-correct across ANY
drift type without needing to NAME the regime.

- Regime detector: "this market is in chop mode → abstain in chop"
- Adaptive priors: "this cell's WR has dropped — lower its p_win until
  it stops firing OR until WR recovers"

Both compose. J.5 vol-regime overlay still ships in Session 3. J.3
provides per-cell self-healing; J.5 provides cross-cell regime gating.

## 3.  Core formula

```
p_win_adaptive(tier, |Δ|_bucket) =
    (w_static × p_win_static + w_rolling × p_win_rolling)
    /
    (w_static + w_rolling)

where:
  p_win_static  = the existing Phase G priors table value
  p_win_rolling = wins / (wins + losses) over the most recent
                  `maxlen` (=100) settled fires in this cell
  w_static      = 50    (Bayesian anchor strength)
  w_rolling     = min(N_observed, w_rolling_cap=100)
```

Limit behavior:

| N_observed | Effective weight ratio | Behavior                          |
|------------|------------------------|-----------------------------------|
| 0          | 50:0 (static-only)     | Identical to current v2.1 static  |
| 10         | 50:10                  | Static dominates ~83%             |
| 50         | 50:50                  | 50/50 blend                       |
| 100        | 50:100 (rolling-twice) | Rolling dominates ~67%            |
| 1000+      | 50:100 (capped)        | Rolling dominates ~67% (capped)   |

The w_rolling_cap at 100 prevents unbounded drift if a cell shifts
regime — even with 1000 observed wins, the static prior retains 33%
weight. This is intentional: regime shifts are detected by J.5, not
by allowing the rolling estimator to fully overwrite history.

## 4.  Architecture

### 4.1  New module: `src/polymarket_bot/strategies/rolling_priors.py`

```python
from collections import deque
from dataclasses import dataclass, field

@dataclass
class CellKey:
    tier: str
    abs_delta_bucket: tuple[float, float]  # e.g., (0.0, 5.0)

    def __hash__(self) -> int:
        return hash((self.tier, self.abs_delta_bucket))


class RollingCellStats:
    """Per-cell rolling window of last N=100 fire outcomes.

    Thread-safe under the runner's single-tasked event loop
    invariant (same model as BankrollTracker).
    """
    def __init__(self, maxlen: int = 100) -> None:
        self._wins: dict[CellKey, deque[bool]] = {}
        self._maxlen = maxlen

    def record(self, cell: CellKey, won: bool) -> None:
        """Append a settled outcome to the cell's rolling window."""
        if cell not in self._wins:
            self._wins[cell] = deque(maxlen=self._maxlen)
        self._wins[cell].append(won)

    def stats(self, cell: CellKey) -> tuple[float, int]:
        """Return (p_win_rolling, n_observed) for this cell.
        n_observed == 0 → returns (NaN, 0); caller should fall back."""
        if cell not in self._wins or not self._wins[cell]:
            return (float("nan"), 0)
        outcomes = self._wins[cell]
        wins = sum(outcomes)
        n = len(outcomes)
        return (wins / n, n)


class AdaptivePriors:
    """Bayesian-blended priors. Combines a static SpotAwarePriors-like
    table with a RollingCellStats. Duck-typed to drop into v2.1's
    `_PriorsFallback` slot.
    """
    def __init__(
        self,
        static: SpotAwarePriors,
        rolling: RollingCellStats,
        *,
        w_static: float = 50.0,
        w_rolling_cap: float = 100.0,
    ) -> None:
        self._static = static
        self._rolling = rolling
        self._w_static = w_static
        self._w_rolling_cap = w_rolling_cap
        self.fee_estimate_pct = static.fee_estimate_pct

    def _cell(self, price: float, abs_delta_bps: float) -> CellKey:
        # Bucket |Δ| into the canonical Phase G buckets (matches static)
        return CellKey(
            tier=tier_label_for_price(price),
            abs_delta_bucket=_delta_bucket_for(abs_delta_bps),
        )

    def lookup(self, *, price: float, abs_delta_bps: float) -> float | None:
        p_static = self._static.lookup(price=price, abs_delta_bps=abs_delta_bps)
        cell = self._cell(price, abs_delta_bps)
        p_rolling, n_obs = self._rolling.stats(cell)

        # SHADOW mode and BOTH-known case: log delta but return static.
        # GATE mode: blend.
        # (Mode is decided at the wrapper layer, not here.)

        if n_obs == 0:
            return p_static  # falls back to static-only behavior

        w_rolling = min(float(n_obs), self._w_rolling_cap)
        if p_static is None:
            # No static value for this cell — fall back to rolling
            # if we have enough sample. (Conservative: require n≥10.)
            return p_rolling if n_obs >= 10 else None

        return (
            self._w_static * p_static + w_rolling * p_rolling
        ) / (self._w_static + w_rolling)
```

### 4.2  Runner integration

`PaperRunner.__init__` builds a `RollingCellStats(maxlen=100)`,
replays the most-recent 100 settled fires per cell from
`state/decisions/<UTC-date>.jsonl` to seed the stats (same replay
pattern as BankrollTracker), then injects an `AdaptivePriors` instance
into the strategy at construction time.

```python
# In _build_strategy for spot_aware_v2_1:
rolling = RollingCellStats(maxlen=ADAPTIVE_MAXLEN)
replay_settled_fires(rolling, decision_log_dir=Path("state/decisions"))
adaptive = AdaptivePriors(
    static=load_priors(),
    rolling=rolling,
    w_static=ADAPTIVE_W_STATIC,
    w_rolling_cap=ADAPTIVE_W_ROLLING_CAP,
)
# Plumbed into v2.1's __init__ via a new `priors_factory` kwarg,
# OR via direct replacement of the priors parameter.
```

The runner's `_on_settled` callback records the outcome via
`rolling.record(cell, won)` after each settled or settled_correction
event. (The correction path uses the final outcome, not the original.)

### 4.3  Modes (`SPOT_AWARE_ADAPTIVE_MODE`)

| Mode    | Behavior                                                       |
|---------|----------------------------------------------------------------|
| `off`   | Default. AdaptivePriors not constructed; pure static path.     |
| `shadow`| AdaptivePriors constructed and logged via decision_log         |
|         | `adaptive_p_win` field, but the strategy's EV gate still reads |
|         | static `p_win`. Used to MEASURE shadow-WR_adaptive vs static.  |
| `gate`  | AdaptivePriors replaces static in the EV gate. The adaptive    |
|         | p_win drives the fire decision. (Promote target after Session 2.)|

## 5.  Tunables (env-vars + defaults)

```
SPOT_AWARE_ADAPTIVE_PRIORS_ENABLED   = false  (DARK SHIP, default off)
SPOT_AWARE_ADAPTIVE_W_STATIC         = 50
SPOT_AWARE_ADAPTIVE_W_ROLLING_CAP    = 100
SPOT_AWARE_ADAPTIVE_MAXLEN           = 100
SPOT_AWARE_ADAPTIVE_MODE             = "off" | "shadow" | "gate"
```

## 6.  Risks + mitigations

### R1: Overfit to recent regime

If `w_static` is too low or `maxlen` too small, the rolling estimator
overfits to a 50-fire recent regime that may not persist. Mitigation:
the 50:100 default split caps rolling weight equal to twice static
even at saturation — strong anchoring prevents 10-fire flips. Budget
Session 2 for empirical tuning across (w_static, maxlen) grid.

### R2: Cell sparsity

Some cells fire <5/day. For those, `n_observed` stays low and the
adaptive value defaults to static. Adaptive kicks in only for the
1-3 high-frequency cells (30-50%, sometimes 70-85% DOWN-only).

### R3: Persistence across restart

Rolling stats must be reconstructed from `state/decisions/<UTC>.jsonl`
on every startup. If the replay fails (file missing, corrupted), the
stats start fresh — adaptive degrades to static for the first N=10
fires per cell. WARNING emitted; no halt.

### R4: Backward compatibility

`SPOT_AWARE_ADAPTIVE_PRIORS_ENABLED=false` is the default. Existing
tests passing the static-only path remain green. The adaptive path is
covered by 8-10 new tests in Session 2.

### R5: Bonereaper-blended priors (J.7) interaction

J.7 adds a third weight `w_bonereaper=100` (from the 306,966-trade
aligned-WR table). The blended formula becomes:

```
p_win_blended =
    (w_static × p_static + w_bonereaper × p_bonereaper + w_rolling × p_rolling)
    /
    (w_static + w_bonereaper + w_rolling)
```

In Session 5 (J.7 ship), w_bonereaper=100 anchors AT the empirical
67.4% aligned ceiling. Adaptive's rolling weight then represents local
correction on top of the bonereaper anchor. Architecture is forward-
compatible; J.3 doesn't need to know J.7 will land.

## 7.  Implementation checklist (Session 2)

- [ ] `src/polymarket_bot/strategies/rolling_priors.py` (CellKey,
      RollingCellStats, AdaptivePriors)
- [ ] `src/polymarket_bot/strategies/rolling_priors_replay.py` (replay
      most-recent 100 settled fires per cell from decision log)
- [ ] 8-10 new tests in `tests/strategies/test_rolling_priors.py`:
  - `test_record_appends_to_cell_window`
  - `test_maxlen_evicts_oldest`
  - `test_stats_returns_nan_when_empty`
  - `test_adaptive_lookup_falls_back_to_static_when_n_zero`
  - `test_adaptive_lookup_blends_at_n_50`
  - `test_adaptive_lookup_caps_rolling_weight_at_w_rolling_cap`
  - `test_adaptive_lookup_handles_static_miss_with_rolling_only`
  - `test_replay_seeds_from_decision_log`
- [ ] `scripts/run_paper.py` env-var wiring (5 envs above)
- [ ] `PaperRunner._on_settled` hook calls `rolling.record(cell, won)`
- [ ] `decision_log.py` schema extension: optional `adaptive_p_win`
      field on fired records (logged in shadow + gate modes)
- [ ] Commit + DARK ship (env-default `off`)
- [ ] 72h shadow soak
- [ ] Audit: shadow-WR_adaptive vs static-WR delta + per-cell

## 8.  Promote gate (Session 2 close)

| Outcome                                       | Action                       |
|-----------------------------------------------|------------------------------|
| shadow-WR_adaptive ≥ static-WR + 2pp on n≥100 | Flip mode to `gate`          |
| shadow-WR within ±1pp                         | Extend soak 7 days; tune     |
| shadow-WR < static-WR − 2pp                   | Kill, archive design, debug  |

Kelly-escalation trigger (J.3 promote unlocks Tier S1):

| Trigger                                        | Effect                       |
|------------------------------------------------|------------------------------|
| J.3 promote AND total live WR ≥ 50% on n≥100  | `KELLY_MULT 0.10 → 0.15`     |
| Above holds with daily PnL ≥ +$10/day for 3d  | `KELLY_MULT 0.15 → 0.20`     |

## 9.  Honest pushback

J-P4 (from Phase J prompt §Honest pushback): adaptive priors CAN
overfit if a regime shifts mid-window-100. The static anchor (w=50)
prevents 10-fire flips but doesn't prevent gradual drift toward a
genuinely-broken regime. J.5 vol-regime overlay is the explicit
defense against regime-shift bias; J.3 is the within-regime correction.

Session 2 must measure shadow vs static cleanly BEFORE promoting to
gate. The 72h soak is non-negotiable — promote on partial data risks
Kelly escalation under a not-yet-validated edge gain.

## 10.  References

- `pdfs/PHASE_G_EDGE_DISCOVERY.pdf` §6.2 — winning cell historical baseline
- `memory/project_ch3_cell_price_distribution_matters.md` — drift evidence
- `memory/project_v2_1_multi_fire_pure_variance.md` — cap=1 hold rationale
- `runbooks/research/edge-discovery-2026-05-09.md` §4 — EV-paradox + fallback contamination
- `design/spot_aware_v2_1.md` — current static path being replaced
- `pdfs/PHASE_J_EDGE_EXPLOITATION.pdf` — Phase J overall plan
