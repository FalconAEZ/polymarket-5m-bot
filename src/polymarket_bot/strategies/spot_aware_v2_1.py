"""SpotAwareStrategyV2_1 — v2 + Kelly + multi-fire + cell-exploitation filters.

Locked spec: design/spot_aware_v2_1.md and
pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf §3-7. Phase G's
truth-corrected 5-day audit found v2 has zero net edge (50.0% WR /
-$18.96), driven by two confirmed loser sub-groups and one winning
cell that v2's `delta_min=5` currently rejects. v2.1 fixes the filter
at the strategy level, then layers fractional Kelly sizing + a 2x per-
window multi-fire cap to exploit the now-included cell at scale.

Four filter changes (cite Phase G PDF sections):

  * CH1 — reject Δ=0 (PG §4.3: 38 fires, -$0.62/trade, no-skew loser).
    Enforced before super() so the multi-fire counter doesn't tick.
  * CH2 — reject EV ∈ [0.02, 0.05) (PG §5.1: 71 fires, -$0.43/trade,
    marginal-positive-EV trap).
  * CH3 — tier-specific Δ floor (PG §6.2: tier 30-50% x |Δ|<5 is the
    audit's largest positive cell at +$0.65/trade). Relaxed to 0 for
    tiers in `tier_relax_delta` (default {'15-30%', '30-50%'}); other
    tiers keep v2's inherited 5 bps floor.
  * CH4 — abstain when Kelly bet < min_bet_abs. Treats "no edge" as
    a real abstain so the window can re-evaluate on a later tick.

Kelly + multi-fire (CH5-CH8): bet sizing reads the live
BankrollTracker via a `bankroll_getter` callback at fire time (CH5/CH6
in spec). Per-window cap=2 default (CH7); PaperRunner refactor lifted
the singular pending_decision invariant to admit it (CH8 / spec §6).

Rationale self-tags as `strategy=spot_aware_v2_1` at construction
(spec §7.1) — avoids the v3 inheritance bug that mis-attributed v3
fires to v2 in 2026-05-12 audit tooling.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace as dc_replace

from polymarket_bot.backtest.types import Decision, MarketEvent, Side, WindowBoundary
from polymarket_bot.strategies.kelly_config import KellyConfig
from polymarket_bot.strategies.spot_aware import delta_bps
from polymarket_bot.strategies.spot_aware_priors import SpotAwarePriors
from polymarket_bot.strategies.spot_aware_v2 import SpotAwareStrategyV2
from polymarket_bot.tiers import tier_label_for_price

# Default tier labels whose delta-floor is relaxed to 0 bps. Phase G
# §6.2 identifies tier 30-50% x |Δ|<5 as the audit's largest positive
# cell (+$0.65/trade); tier 15-30% is included by symmetry (low-price
# entries have the same asymmetric-payoff favorable to a 50% WR).
DEFAULT_TIER_RELAX_V2_1: tuple[str, ...] = ("15-30%", "30-50%")

# Default EV-rejection band. EV ∈ [0.02, 0.05) was a -$0.43/trade trap
# in the 71-fire audit (PG §5.1). Strict-inequality on the upper end
# preserves the 5¢-and-above clean-positive cells.
DEFAULT_EV_BAD_BUCKET_V2_1: tuple[float, float] = (0.02, 0.05)

# Default per-window cap. Operator Q3 default = 2.
DEFAULT_MULTI_FIRE_CAP_V2_1: int = 2


# Rationale-parsing + self-tagging regex. Word boundaries prevent
# accidental rewrites of substrings; matches v2's exact format
# (`spot_aware_v2.py:_rationale_v2`).
_RE_STRATEGY = re.compile(r"\bstrategy=spot_aware_v2\b")
_RE_MODE = re.compile(r"\bmode=tier_restricted\b")
_RE_EV = re.compile(r"\bev=([+-]?\d+\.?\d*)")
_RE_P_WIN = re.compile(r"\bp_win=([0-9]+\.?[0-9]*)")


def _parse_ev(rationale: str) -> float | None:
    """Extract `ev=<float>` from a v2 rationale string; None if absent."""
    m = _RE_EV.search(rationale)
    if m is None:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_p_win(rationale: str) -> float | None:
    """Extract `p_win=<float>` from a v2 rationale string; None if absent."""
    m = _RE_P_WIN.search(rationale)
    if m is None:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _rewrite_rationale_v2_1(
    rationale: str,
    *,
    kelly_f: float,
    bet_usd: float,
    bankroll: float,
    fire_n: int,
    cap: int,
) -> str:
    """Rewrite v2's rationale to self-tag as v2.1 + append Kelly telemetry."""
    new = _RE_STRATEGY.sub("strategy=spot_aware_v2_1", rationale)
    new = _RE_MODE.sub("mode=kelly_multi", new)
    return (
        f"{new} kelly_f={kelly_f:.3f} bet_usd={bet_usd:.2f} "
        f"bankroll={bankroll:.2f} fire_n={fire_n}/{cap}"
    )


class SpotAwareStrategyV2_1(SpotAwareStrategyV2):
    """v2 + Kelly + multi-fire + cell-exploitation filters.

    Inherits all v2 state lifecycle: priors lookup, tier rejection,
    price-limit cap below reject band, oracle-gap filter,
    fire-once-per-window flag (relaxed here via multi-fire cap), and
    every constructor knob v2 exposes (passed through via **v2_kwargs).
    """

    name: str = "spot_aware_v2_1"

    def __init__(
        self,
        *,
        priors: SpotAwarePriors,
        bankroll_getter: Callable[[], float],
        kelly: KellyConfig | None = None,
        multi_fire_cap: int = DEFAULT_MULTI_FIRE_CAP_V2_1,
        tier_relax_delta: tuple[str, ...] = DEFAULT_TIER_RELAX_V2_1,
        ev_bad_bucket: tuple[float, float] = DEFAULT_EV_BAD_BUCKET_V2_1,
        **v2_kwargs: object,
    ) -> None:
        super().__init__(priors=priors, **v2_kwargs)  # type: ignore[arg-type]
        if multi_fire_cap < 1:
            raise ValueError(f"multi_fire_cap must be >= 1; got {multi_fire_cap}")
        lo, hi = ev_bad_bucket
        if not (0.0 <= lo < hi):
            raise ValueError(f"ev_bad_bucket must satisfy 0 <= lo < hi; got ({lo}, {hi})")
        self._bankroll_getter = bankroll_getter
        self._kelly = kelly if kelly is not None else KellyConfig()
        self._multi_fire_cap = multi_fire_cap
        self._tier_relax = frozenset(tier_relax_delta)
        self._ev_bad_lo, self._ev_bad_hi = ev_bad_bucket
        self._fires_this_window: int = 0

    @property
    def kelly(self) -> KellyConfig:
        """Read-only handle on the Kelly config (used by tests + telemetry)."""
        return self._kelly

    @property
    def multi_fire_cap(self) -> int:
        return self._multi_fire_cap

    def set_bankroll_getter(self, getter: Callable[[], float]) -> None:
        """Rebind the bankroll-getter callback after construction.

        The strategy is built in ``_build_strategy`` with a placeholder
        getter; the runner's ``BankrollTracker`` doesn't exist until
        ``PaperRunner.__init__``. ``main()`` calls this method post-
        construction to wire the real getter. Public so the run_paper
        dispatch doesn't reach into ``_bankroll_getter`` directly.
        """
        self._bankroll_getter = getter

    def reset(self) -> None:
        super().reset()
        self._fires_this_window = 0

    def _on_boundary(self, event: WindowBoundary) -> Decision | None:
        # Chain to v2's boundary handling (resets `_window_open_spot`
        # and `_fired_for_window` on open) and additionally clear the
        # v2.1 multi-fire counter so each window starts fresh.
        result = super()._on_boundary(event)
        if event.kind == "open":
            self._fires_this_window = 0
        return result

    def _maybe_fire(self, now_ts_utc_ns: int) -> Decision | None:
        # CH7 — multi-fire cap. Once the cap is reached for this window,
        # subsequent ticks are dropped at the strategy level (defense
        # in depth — the runner also enforces a cap).
        if self._fires_this_window >= self._multi_fire_cap:
            return None
        if self._spot_now is None or self._window_open_spot is None:
            return None

        d_bps = delta_bps(spot_now=self._spot_now, window_open_spot=self._window_open_spot)

        # CH1 — reject Δ=0 (PG §4.3). Short-circuit before super() so
        # the multi-fire counter doesn't tick and no telemetry rationale
        # is built. (v2 also returns None on Δ=0 internally, so the
        # super() call would return None anyway; CH1 makes the abstain
        # explicit and saves the work.)
        if d_bps == 0.0:
            return None

        # CH3 — tier-specific Δ floor. Determine the candidate side's
        # tier from its current best_ask snapshot and relax the floor
        # to 0 if the tier is in the relax set.
        side_guess: Side = "UP" if d_bps > 0 else "DOWN"
        ask_guess = self._best_ask_for_side.get(side_guess)
        if ask_guess is None:
            return None
        tier = tier_label_for_price(ask_guess)

        # v2's `_maybe_fire` reads `self._delta_min` directly. We swap
        # it for this fire only (single-threaded event loop → safe).
        # Restore on every exit path via try/finally.
        saved_delta_min = self._delta_min
        if tier in self._tier_relax:
            self._delta_min = 0.0
        try:
            base_decision = super()._maybe_fire(now_ts_utc_ns)
        finally:
            self._delta_min = saved_delta_min

        if base_decision is None:
            return None

        # CH2 — reject EV ∈ [ev_bad_lo, ev_bad_hi). Parse from the v2
        # rationale (v2 always emits `ev=<float>`). Reset
        # `_fired_for_window` so a later qualifying tick in the same
        # window can re-evaluate — mirrors v3's regime-gate reset
        # pattern.
        ev = _parse_ev(base_decision.rationale)
        if ev is not None and self._ev_bad_lo <= ev < self._ev_bad_hi:
            self._fired_for_window = None
            return None

        # CH5/CH6 — Kelly sizing replaces v2's flat size_usd. Read the
        # current bankroll AT FIRE TIME so compounding is live.
        bankroll = self._bankroll_getter()
        p_win = _parse_p_win(base_decision.rationale)
        if p_win is None:
            # Defensive: if v2's rationale schema ever drifts, fall
            # through with v2's size + the v2 rationale. Hard-failing
            # the fire would lose alpha for a downstream change.
            return base_decision
        bet = self._kelly.bet_size(bankroll=bankroll, p_win=p_win, price=base_decision.price_limit)

        # CH4 — Kelly says abstain (bet under floor / no edge). Reset
        # the per-window flag so the next tick can re-evaluate; do NOT
        # tick the multi-fire counter (this was not a fire).
        if bet < self._kelly.min_bet_abs:
            self._fired_for_window = None
            return None

        # Successful fire. Build the v2.1 rationale, tick the counter,
        # and clear `_fired_for_window` if there's still cap headroom
        # so the next qualifying tick in this same window can also fire.
        self._fires_this_window += 1
        new_rationale = _rewrite_rationale_v2_1(
            base_decision.rationale,
            kelly_f=self._kelly.last_kelly_f,
            bet_usd=bet,
            bankroll=bankroll,
            fire_n=self._fires_this_window,
            cap=self._multi_fire_cap,
        )
        if self._fires_this_window < self._multi_fire_cap:
            self._fired_for_window = None
        return dc_replace(base_decision, size_usd=bet, rationale=new_rationale)

    async def on_event(self, event: MarketEvent) -> Decision | None:
        # Inherit v2's dispatch verbatim — no async I/O added in the
        # fire path (defense L3 against the LLM queue-overflow class
        # of incidents).
        return await super().on_event(event)
