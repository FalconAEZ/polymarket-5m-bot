# SpotAwareStrategy v2.1 — Kelly + multi-fire + cell-exploitation filters (2026-05-13)

> **Status:** LOCKED — operator sign-off received this session.
> Anti-vibe rule #1: this doc precedes the code (`src/polymarket_bot/strategies/spot_aware_v2_1.py`).
> Engineering ground truth: `pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf` (18 sections).
> Strategic context: `pdfs/PHASE_G_EDGE_DISCOVERY.pdf` (Phase G 5-day deep dive) and
> `pdfs/PHASE_H_v2_1_IMPLEMENTATION.pdf` (Phase H.1 strategic plan).

## Why this exists

Phase G's truth-corrected audit (635 fires, 17 dimensions, 5 trading days
2026-05-08 … 2026-05-12) found that **v2 in production has zero net
edge**: 50.0% WR / −$18.96 net across the soak. The cause is not random
— Phase G isolated two confirmed loser sub-groups inside v2's fire
universe, and one confirmed winning cell that v2 currently *rejects*:

| Phase G finding | n | per-trade | direction |
|---|---|---|---|
| Δ=0 (no skew at fire time) | 38 | −$0.62 | **LOSER — eliminate** |
| EV ∈ [0.02, 0.05) | 71 | −$0.43 | **LOSER — eliminate** |
| Tier 30-50% × \|Δ\|<5 bps | 83 | **+$0.65** | **WINNER — currently rejected by v2's `delta_min=5`** |

v2.1 fixes all three at the strategy level, then layers Kelly sizing
(decision #9 already authorized this) and a 2× multi-fire cap (each
window can now produce up to 2 independent decisions) on top so the
positive-EV cell is exploited at scale once the WR signal confirms.

## What does NOT change

- The `Strategy` protocol — v2.1 returns `Decision | None` the same way.
- The v2 priors table (`data/spot_aware_priors.json` v1) — v2.1 reads it.
- The v2 tier-rejection list — tier 50-70% and 85-100% remain rejected.
- The oracle-gap filter — defaults stay off, env override unchanged.
- The decision log JSONL schema for backward-compat fields. New fields
  (kelly_f, bet_usd, bankroll_at_fire, fire_n_in_window, multi_fire_cap)
  are *additive*; downstream tooling that doesn't know them ignores
  them.
- The instant-settle / orphan-recovery / post-hoc-gamma-retry plumbing
  in `_paper/runner.py`. v2.1's runner edits are *additive*: a new
  `BankrollTracker` and a `pending_decision → pending_decisions: list`
  refactor with a backward-compat property.

## Inheritance

```
Strategy (Protocol)                           protocol.py
└── SpotAwareStrategy                         spot_aware.py
    └── SpotAwareStrategyV2                   spot_aware_v2.py
        ├── SpotAwareStrategyV3   (SHELVED post-Phase F; v2+regime gate)
        └── SpotAwareStrategyV2_1 ★ NEW       spot_aware_v2_1.py
            (v2 + CH1–CH4 filters + Kelly + multi-fire)
```

**v2.1 extends v2 directly, not v3.** Reason: v3's regime gate is
*optional* per operator Q2=A (no regime gate, start simple). If a
future operator sign-off enables regime gating, v2.1 can compose
`RegimeDetector` the same way v3 does — but layering it always would
shrink the fire rate the multi-fire cap was designed to expand.

## Filter changes (CH1–CH4)

All four cite specific Phase G evidence. Citations track section
numbers in `pdfs/PHASE_G_EDGE_DISCOVERY.pdf` ("PG §X.Y").

### CH1 — Reject Δ=0 windows

**Change:** if `delta_bps(spot_now, window_open_spot) == 0.0`, return
`None` *before* calling the parent. (v2 already returns None on this
exact condition; v2.1 enforces the check *first* so the multi-fire
counter doesn't tick.)

**Why (PG §4.3):** 38 historical Δ=0 fires, −$0.62/trade, 39% WR.
"No skew at fire time" predictably loses to fees.

### CH2 — Reject EV ∈ [0.02, 0.05)

**Change:** after the parent fires, parse EV from the rationale; if
`0.02 ≤ ev < 0.05`, drop the fire AND reset `_fired_for_window` so a
later qualifying tick in the same window can still re-evaluate.

**Why (PG §5.1):** EV-bucket audit found this band is a 71-fire
−$0.43/trade trap — the "marginal positive EV" range where the
priors-table edge is too thin to clear fees + slippage. Strict
inequality on the upper end (5¢ EV is fine) is intentional.

### CH3 — Tier-specific Δ floor

**Change:** before invoking parent logic, compute the tier label of the
candidate side's `best_ask`. If the tier ∈ `tier_relax_delta`
(default `{'15-30%', '30-50%'}`), allow any `|Δ| > 0`. Otherwise enforce
the inherited `_delta_min` (5 bps). The relaxation is achieved by
inlining v2's body (sharing constants) — see spec §3.3.

**Why (PG §6.2 winning-cell isolation):** tier 30-50% × |Δ|<5 cell
has n=83, +$0.65/trade, +$54 cumulative — the largest positive cell
in the whole audit, and v2 currently rejects it (`delta_min=5` cuts
exactly this region). Tier 15-30% is included by symmetry (its same-cell
sample is smaller but directionally identical and the payoff asymmetry
favors low-price entries). Tier 70-85% explicitly retains the 5 bps
floor — same-cell n=21, no positive signal.

### CH4 — Kelly-bet-too-small abstain

**Change:** after Kelly sizing, if `bet_usd < kelly.min_bet_abs`
(default $1), drop the fire and reset `_fired_for_window`. Treats "the
math says don't bet" as a real abstain, not a degenerate $0 fire.

**Why:** Kelly returns 0 when `p_win ≤ price` (no edge). Without CH4
the runner sees `size_usd=0` and emits a phantom record. CH4 makes the
abstain explicit and frees the window for re-evaluation. Phase G §7.4
on min-bet floor.

## Kelly sizing (CH5–CH6)

### CH5 — `KellyConfig` dataclass

New file `src/polymarket_bot/strategies/kelly_config.py` (spec §4).
Standard fractional-Kelly with hard absolute and percentage caps:

```python
@dataclass(slots=True)
class KellyConfig:
    kelly_mult: float = 0.10        # fractional Kelly (Q4 default)
    max_bet_pct: float = 0.10       # never more than 10% bankroll
    max_bet_abs: float = 500.0      # Polymarket retail liquidity cap
    min_bet_abs: float = 1.00       # below this, drop the fire
```

`kelly_f(p_win, price) = (p_win - price) / (1 - price)` clamped to 0
when `p_win ≤ price`. `bet_size(bankroll, p_win, price)` returns the
clamped bet (or 0 if below floor) and writes `last_kelly_f` for the
rationale builder.

### CH6 — Bankroll-getter injection

v2.1's constructor accepts `bankroll_getter: Callable[[], float]`.
The strategy calls it at fire time (NOT at construction) so each
fire compounds against the *current* bankroll. The runner exposes
`BankrollTracker.current` as the getter (§5 below).

## Multi-fire (CH7–CH8)

### CH7 — Strategy-level cap

v2.1 tracks `_fires_this_window: int`, reset on `WindowBoundary(kind='open')`,
incremented on each successful fire. Once `>= multi_fire_cap` (default 2)
the strategy returns None regardless of signals. The inherited
`_fired_for_window` flag is *not* set on every fire (v2.1 overrides
its semantics so the cap is the gate, not the boolean flag).

### CH8 — PaperRunner refactor

Single biggest risk in this ship: lifting the singular
`pending_decision` invariant in `_paper/runner.py`. Per spec §6.2:

```python
@dataclass
class _RunnerState:
    window_ts: int | None = None
    pending_decisions: list[PendingDecision] = field(default_factory=list)
    multi_fire_cap: int = 1   # v2 keeps 1; v2.1 sets 2 from env

    @property
    def pending_decision(self) -> Decision | None:
        # Backward-compat read for v1/v2/v3 / wide_fire / existing tests.
        return self.pending_decisions[0].decision if self.pending_decisions else None
```

`_on_decision` accepts up to `multi_fire_cap` decisions per window
(rejects the (cap+1)th with a log line). The settle loop iterates all
pending decisions, settling each independently. Per
`project_per_side_state_pollution_pattern.md`, each `PendingDecision`
carries its own `asset_id`; the multi-fire counter is keyed by
`window_ts`, not by side.

## BankrollTracker (the Kelly feedback loop)

New `BankrollTracker` (~30 LOC) in `_paper/runner.py`:

```python
@dataclass(slots=True)
class BankrollTracker:
    starting_usd: float = 1000.0    # locked decision #10
    realized_pnl_usd: float = 0.0

    def current(self) -> float:
        return self.starting_usd + self.realized_pnl_usd

    def apply_settle(self, pnl_usd: float) -> None:
        self.realized_pnl_usd += pnl_usd

    def apply_correction(self, original_pnl: float, corrected_pnl: float) -> None:
        # Phase 15.5 settled_correction overlay support.
        self.realized_pnl_usd += (corrected_pnl - original_pnl)
```

**Startup recovery:** on `PaperRunner.__init__`, the tracker walks
recent `state/decisions/*.jsonl` and replays `settled` + `settled_correction`
records to derive the current bankroll. Mirrors the orphan-fire-recovery
pattern already present. Test coverage in `test_bankroll_tracker.py`
includes the cross-day + phantom-fill edge cases (per Phase 15.5
truth-pass and post-hoc retry corrections).

The runner exposes `self._bankroll.current` as the callable the
v2.1 strategy reads. Dashboard's `load_bankroll()` (JSONL-derived) and
the runner's BankrollTracker (in-memory + replay-on-start) converge by
construction; the dashboard remains operator-facing source of truth.

## Rationale format (self-tagging at the source)

Past incident: v3 inherited v2's rationale unchanged, breaking
downstream `four_day_audit.py` and the watcher (fix: commit 74f7541).
v2.1 self-tags **at construction time**, not via post-hoc regex rewrite
of a parent-built string — though for sub-fields produced by v2's
`_rationale_v2` we still do a word-boundary regex sub. Reason: the
parent's rationale builder is the only place `p_win`, `ev`, and
`ttl_s` are formatted; rewriting the leading marker keeps single
source of truth for those fields.

```
v2:   strategy=spot_aware_v2 mode=tier_restricted delta_bps=+5.02 p_win=0.400 ev=+0.1650 ttl=30s side=UP
v2.1: strategy=spot_aware_v2_1 mode=kelly_multi delta_bps=+5.02 p_win=0.400 ev=+0.1650 ttl=30s side=UP kelly_f=0.357 bet_usd=89.50 bankroll=1006.01 fire_n=1/2
```

## Test surface (22 tests)

Mirrors spec §9. One file per concern; each test names a behavior the
prompt's H.6 gates depend on.

| File | Tests | What it locks |
|---|---|---|
| `tests/strategies/test_kelly_config.py` | 5 | Kelly math, clamps, min-bet floor |
| `tests/strategies/test_spot_aware_v2_1.py` | 13 | CH1–CH4 filter chain + Kelly substitution + rationale self-tag + multi-fire counter |
| `tests/paper/test_runner_multi_fire.py` | 5 | `_RunnerState` refactor preserves v2/v3 backward-compat AND admits the 2nd v2.1 fire AND rejects the 3rd |
| `tests/paper/test_bankroll_tracker.py` | 4 | Startup replay, settle deltas, correction overlay (Phase 15.5), phantom-fill neutralization |

Backward-compat is a hard gate: after H.2.3 the full `tests/` suite
must stay green (581 tests as of baseline 2026-05-13 ≥ prompt's
"553+ expected").

## Past-incident defense matrix

Drawn from spec §14 — each entry maps a confirmed historical bug class
to v2.1's specific guard:

- L1 (v3 rationale-inheritance, 2026-05-12): v2.1 rewrites the strategy
  marker at fire time; tests assert `'strategy=spot_aware_v2_1' in
  rationale` and absence of bare `'spot_aware_v2 '`.
- L2 (per-side state pollution, 16.B.4 2026-05-12): v2.1 keys its
  multi-fire counter by `window_ts`. `PendingDecision` carries
  `asset_id` explicitly.
- L3 (LLM queue overflow, 2026-05-10): v2.1 has NO async I/O in the
  fire path. Kelly is sync; `bankroll_getter` is sync.
- L4 (Instant-settle queue overflow, 2026-05-09): no inline awaits
  added; `BankrollTracker.apply_settle` is sync.
- L5 (FD orphan / dashboard, 2026-05-09): v2.1 doesn't touch the
  decision-log writer; PaperRunner's inode-stable append is unchanged.
- L6 (Phantom-fill, Phase 11.A): v2.1 inherits v2's tier rejection +
  the limit-price cap below reject-band; phantom-fill detection in
  the post-hoc retry continues to neutralize pnl correctly.
- L7 (Chainlink-vs-polymarket truth disagreement, 2026-05-10): v2.1
  doesn't touch resolution; gamma retry + correction overlay
  unchanged. BankrollTracker.apply_correction handles the overlay.
- L8 (Wide_fire ensemble negative selection, 2026-05-11): v2.1 doesn't
  use the LLM ensemble; Phase F cut intact.
- L9 (Cross-restart double-fire, 2026-05-10): multi-fire CAP scoped
  to a single `window_ts`; restart resets `_fires_this_window`. The
  existing `_prime_active_window_state` hardens against the cross-
  restart pathway.
- L10 (VPS timestamp drift, 2026-05-12): no logic depends on
  computed timestamps; deploy runbook uses `$(date +%s)` on the VPS.
- L11 (Phase 15.5 truth pass): `settled_correction` records flow
  through `BankrollTracker.apply_correction`. Tested explicitly.
- L12 (pending_decision singular invariant): the
  `pending_decision → pending_decisions: list` refactor + property
  preserves all existing call-site reads.
- L13 (OSError on disk-full): preserved try/except in `_on_decision`.
- L14 (Aggressive-mode high variance): Kelly 0.10× cap + $500 abs
  cap + multi-fire 2× (not 3×) = max ~6.4% bankroll deployed per
  window. H.6 ROLLBACK at WR<45% / 48h is the safety net.

## Rollback path

Two layers:

**Code-level rollback** (within this session, pre-deploy): revert the
single H.2.6 commit; no .envrc changes have landed yet, nothing on
VPS. `git revert -n HEAD && git commit`.

**VPS-level rollback** (after Phase H.5, if it ever ships): per
spec §15. The .envrc backup convention is
`.envrc.phase-H-pre-v2_1-backup-YYYYMMDD-HHMMSS`. Rollback is
`cp $BACKUP .envrc && systemctl restart bot-staging.service` —
PHASE-F-4 (`STRATEGY=spot_aware_v2`) resumes.

**H.6 soak triggers for ROLLBACK over the 7-day window:**

- WR < 45% over any 48h continuous slice
- daily_pnl < −$30 on any single day
- bankroll drops below $500 (50% drawdown from start)
- 3 consecutive losing days (Bonferroni-corrected α ≈ 1.5%)

## Operator sign-off (this session)

| Q | Decision | This session |
|---|---|---|
| Q1 | Hour gate | NO (default) — sample too thin |
| Q2 | Regime gate | A (default) — no gate, start simple |
| Q3 | Multi-fire cap | 2 (default) — conservative |
| Q4 | Kelly multiplier | 0.10× (default) — smoother trajectory |
| Q5 | Live-trading promotion | $2k (locked decision #12) |

Code is parameterized: any future override changes env vars only
(`KELLY_MULT`, `MULTI_FIRE_CAP`, `KELLY_MAX_BET_ABS`,
`PMB_STARTING_BANKROLL`), no recompile.

## Deferred to next session

H.5 deployment to VPS is **deferred** this session per operator call
(option B: ship code, no deploy). Reason: v2 has only ~5h of soak
since PHASE-F-4 (2026-05-12 15:42:38 UTC); the prompt's "WR ≥ 52% on
n ≥ 30" gate passes the letter (52.8% on day) but the spirit is "is
v2 working over a full day," and the true PnL is negative on the day.
Wait for overnight data before layering Kelly compounding on top.

H.6 7-day soak gate criteria stand as spec §15.
