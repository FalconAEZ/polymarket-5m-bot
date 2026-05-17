# Phase 16 — bankroll-display scenarios panel

Status: locked — anti-vibe #1 design-doc-before-code.
Author: Phase 15.5 session, 2026-05-11.
Implements: `phase-prompts/phase-16-bankroll-display-2026-05-13.txt`.

## Problem (one paragraph)

Operator needs to see what today's realised PnL would look like if the
starting bankroll were $500 / $1k / $2k / $5k / $10k rather than the
locked-decision-#10 $1,000. The bot's stake is fixed at $5 per trade
(locked decision #9), so the realised PnL is a constant independent of
starting bankroll; the scenarios panel just adds that constant to each
starting amount and shows the end balance. The panel is read-only and
the bankroll-locked-decision is NOT changed — operator stays at $1k
paper while modelling alternatives for Phase 17/18 sizing planning.

## Hidden requirement carried over from Phase 15.5 Item 1

Item 1's reconciliation pass found that `scripts/dashboard.py` (the
Streamlit dashboard the operator launches locally) calls
`load_decisions(...)` and then `aggregate_pnl(...)` directly — it
**never invokes** `apply_settled_corrections(...)`. The function has
existed in `dashboard/loaders.py` since the May 9 incident fix but the
Streamlit script never wired it in. That's why the Phase 14 per-tier
audit and any other ad-hoc reader quotes the broken +$2,504 number
while the production v4 dashboard (which applies corrections via the
VPS-side `runbooks/patches/dashboard_state__apply_corrections.py`
overlay) correctly reports ~$75.

Phase 16's scenarios panel CANNOT consume the naïve PnL — it would
project phantom money. So this phase also lands the missing
`apply_settled_corrections` call in `scripts/dashboard.py`, plus the
first regression test for that function (currently uncovered).

## Scope

1. New: `ScenarioResult` dataclass + `compute_scenarios()` helper in
   `src/polymarket_bot/dashboard/loaders.py`. Pure function.
2. New: `_render_scenarios_panel(rows, ...)` Streamlit fragment in
   `scripts/dashboard.py` rendering the 5 buckets as a horizontal strip.
3. Fix: `scripts/dashboard.py` calls `apply_settled_corrections(rows,
   state_dir / DECISIONS_SUBDIR, since_utc_date=since or None)` between
   `load_decisions` and the first KPI render, so KPI + chart + tier +
   scenarios panels all see corrected PnL.
4. New: `tests/dashboard/test_loaders.py` adds (a) 3 `compute_scenarios`
   tests per the prompt, (b) 1 regression test for
   `apply_settled_corrections` (no test exists today — this gap is what
   let the Phase 14 audit go uncaught).

Out of scope:
- Decision #10 ($1k bankroll). NOT changing.
- The bot trading path. ZERO bot-touching code.
- Phase 17 sizing modes — handled separately.
- A new dashboard service. The VPS-side dashboard already applies
  corrections; the Streamlit script is the one missing them.

## `compute_scenarios()` shape

```python
@dataclass(frozen=True, slots=True)
class ScenarioResult:
    start_bankroll_usd: float
    end_bankroll_usd: float
    realized_pnl_usd: float
    n_settled: int
    fixed_stake_usd: float
    is_bankrupt: bool        # end_bankroll_usd <= 0

def compute_scenarios(
    rows: Iterable[DecisionRow],
    scenarios: Sequence[float] = (500, 1000, 2000, 5000, 10000),
    *,
    fixed_stake_usd: float = 5.0,
) -> list[ScenarioResult]:
    ...
```

PnL aggregation matches `aggregate_pnl(rows)["total_pnl_usd"]` so the
$1k scenario equals the headline KPI exactly when the same rows are
passed. Caller is expected to pass corrections-applied rows; the
function does not double-apply.

Naïve scaling: end_bankroll = start + realized_pnl. Linear in start at
fixed stake. **Will go negative** if PnL is heavily negative — the
`is_bankrupt` flag surfaces that to the panel; the panel must show the
negative number as-is (don't clamp), and styling marks it red.

## Test plan

Three required by the master plan + one regression:

1. `test_scenarios_at_1k_matches_actual_pnl` — for a synthetic row set
   with realised PnL = $X, the $1000 scenario reports
   `end_bankroll_usd == 1000 + X`.
2. `test_scenarios_scale_linearly_at_fixed_stake` — at fixed stake the
   delta (end - start) is the same for all scenarios.
3. `test_scenarios_handles_negative_pnl_without_clamping` — if PnL
   pushes a small bankroll below 0, the result reflects that and
   `is_bankrupt` is True.
4. **REGRESSION** `test_apply_settled_corrections_overlays_corrected_pnl`
   — write a synthetic JSONL with a `fired` + `settled` (resolution=UP,
   pnl=+$5) + a `settled_correction` (corrected_resolution=DOWN,
   corrected_pnl=−$5). After `load_decisions + apply_settled_corrections`
   the row's `pnl_usd` is −$5, NOT +$5. This is the safety net that
   would have caught the Phase 14 per-tier audit's broken framing.

## Test-under-load

`compute_scenarios` is a tight Python loop over a list ≤ 1k rows. No
I/O. The Streamlit panel re-runs on each dashboard refresh
(`refresh_s ≥ 2`). Cost is irrelevant; no benchmark needed.

## Gate

`uv run ruff check src/ tests/ scripts/ && uv run mypy --strict src/ &&
uv run pytest -q && uv run lint-imports`. All four green before commit.

## Commit message

`feat(phase-16): bankroll-display scenarios panel + corrections wire on
dashboard.py`
