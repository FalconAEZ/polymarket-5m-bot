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
  * CH3 — tier-specific Δ floor + priors fallback (PG §6.2: tier
    30-50% x |Δ|<5 is the audit's largest positive cell at +$0.65/
    trade). Δ floor relaxed to 0 for tiers in `tier_relax_delta`
    (default {'15-30%', '30-50%'}); other tiers keep v2's inherited
    5 bps floor. When the inherited priors table misses at low |Δ|
    AND tier is in tier_relax, a `tier_relax_p_win_fallback` synthesises
    a p_win value so the winning cell fires (default 0.48 = PG §5.1
    empirical historical WR; below the 0.582 backtest projection per
    H.1 §1 honest-pushback Conservative scenario).
  * CH4 — abstain when Kelly bet < min_bet_abs. Treats "no edge" as
    a real abstain so the window can re-evaluate on a later tick.

Kelly + multi-fire (CH5-CH8): bet sizing reads the live
BankrollTracker via a `bankroll_getter` callback at fire time (CH5/CH6
in spec). Per-window cap=2 default (CH7); PaperRunner refactor lifted
the singular pending_decision invariant to admit it (CH8 / spec §6).

Path A side-direction block (H.2.12, post-Phase-G operator
follow-up): live data 2026-05-13 showed tier 70-85% UP fires netted
-$5.06/trade (n=41) while DOWN at +$0.13/trade (n=31) — the UP side
was the catastrophic bleeder. `block_up_in_tiers` and
`block_down_in_tiers` operator-tunable env vars surgically reject
side/tier combinations before super() runs. Defaults are empty
tuples (no blocking).

Rationale self-tags as `strategy=spot_aware_v2_1` at construction
(spec §7.1) — avoids the v3 inheritance bug that mis-attributed v3
fires to v2 in 2026-05-12 audit tooling.
"""

from __future__ import annotations

import datetime as _dt
import re
from collections.abc import Callable
from dataclasses import replace as dc_replace

from polymarket_bot.backtest.types import Decision, MarketEvent, Side, WindowBoundary
from polymarket_bot.strategies.cell_flip_detector import CellFireHistory, CellFlipDetector
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

# Default fallback p_win for the CH3 winning cell when the shipped
# priors table misses. Phase G §5.1 historical empirical WR for the
# 30-50% x |Δ|<5 cell was 48.1% (n=83); 0.48 is one tick conservative,
# below the 58.2% backtest projection (H.1 §1) so Kelly sizing stays
# disciplined relative to the data. Set to None to disable the fallback
# entirely; then v2.1 behaves exactly like spec-literal CH3 (cell won't
# fire until the priors data ships a [1, 5] bucket). Operator override
# via SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK env var.
DEFAULT_TIER_RELAX_P_WIN_FALLBACK: float | None = 0.48

# Default price floor for tier_relax (CH3) fires. Phase J.1 — H.3 audit
# 2026-05-13 measured n=111 CH3 cell fires; price distribution
# min=0.180 / median=0.420 / max=0.460. Fires BELOW 0.42 lose at
# 25.5% WR / -$5.70/trade (n=51); fires AT-OR-ABOVE 0.42 win at 56.7%
# WR / +$1.77/trade (n=60). The floor (NOT a ceiling) blocks the
# losing subset and keeps the winners. Direction is inverted from the
# H.3 spec's original "price_cap" framing based on live data; the
# spec hypothesis (cap above 0.45) would have removed the winners.
# Set to 0.0 to disable (kill-switch); 0.40 conservative; 0.43
# aggressive. Operator override via SPOT_AWARE_TIER_RELAX_PRICE_FLOOR.
DEFAULT_TIER_RELAX_PRICE_FLOOR: float = 0.42

# Default hour-of-day blocklist (UTC) — Phase J.2. Empty by default
# (no blocking). Wired via SPOT_AWARE_HOUR_BLOCKLIST_UTC env (comma-list
# of integers 0-23) + SPOT_AWARE_HOUR_BLOCKLIST_TIERS (comma-list of
# canonical tier labels). H.3 audit 2026-05-13 H.5 era recommended
# tier 70-85% x (22, 23, 0) UTC based on retrospective historical save
# of ~$152-$233 across the affected hours.
DEFAULT_HOUR_BLOCKLIST_UTC: tuple[int, ...] = ()
DEFAULT_HOUR_BLOCKLIST_TIERS: tuple[str, ...] = ()

# Phase T Improvement #1 — extend J.2 to per-(hour, tier) pairs. The
# legacy `*_UTC` x `*_TIERS` form is a 2D intersection: it can express
# tier-70-85% x {22,23,0} but NOT tier-30-50% x {05,06,17,21,23,0} on
# the same instance (would cross-contaminate). The new pairs form is a
# set of explicit (hour, tier) tuples. Empty by default; operator wires
# via SPOT_AWARE_HOUR_BLOCKLIST_PAIRS env as "<hour>:<tier>,..." e.g.
# "22:70-85%,23:70-85%,0:70-85%,5:30-50%,6:30-50%,17:30-50%,21:30-50%,
# 23:30-50%,0:30-50%" (the Phase N forensic blocklist; quantified
# -$1,748 prevented loss over 5 days). The legacy params remain
# accepted: at init, they expand to all (h, t) combinations and merge
# into the pair set. See design/phase-T-hour-blocklist-v2.md.
DEFAULT_HOUR_BLOCKLIST_PAIRS: tuple[tuple[int, str], ...] = ()


class _PriorsFallback:
    """Wraps the real ``SpotAwarePriors`` and synthesises a p_win for
    the CH3 winning cell when the inherited table misses.

    Trigger conditions (ALL must hold):
      1. The real priors lookup returns None (table miss).
      2. The price's tier is in ``tier_relax`` (default {'15-30%',
         '30-50%'}).
      3. The |Δ| is below ``delta_floor`` (v2's inherited 5 bps),
         i.e., the relaxed-floor zone CH3 opened up.

    All three together mean: "this is the Phase G winning cell that
    v2.1's CH3 explicitly intends to fire on, but the priors data
    doesn't cover it yet". The fallback returns ``p_win_fallback``
    (operator-tuned; default 0.48 per PG §5.1 historical empirical).

    For any other miss (e.g., tier 70-85% at |Δ|=3, or tier 50-70%
    rejected, or large |Δ| outside the table), this fallback returns
    None — preserving v2's strict no-fallback semantics for everything
    outside CH3's intended scope.

    Duck-typed: matches ``SpotAwarePriors``'s public surface
    (``lookup`` + ``fee_estimate_pct``). Constructed per-fire as a
    temp-swap in ``SpotAwareStrategyV2_1._maybe_fire`` so v2's super()
    body sees the fallback transparently.
    """

    def __init__(
        self,
        *,
        real: SpotAwarePriors,
        p_win_fallback: float,
        tier_relax: frozenset[str],
        delta_floor: float,
    ) -> None:
        self._real = real
        self._p_win_fallback = p_win_fallback
        self._tier_relax = tier_relax
        self._delta_floor = delta_floor
        # Mirror the real priors' fee so v2's super() body reads it identically.
        self.fee_estimate_pct = real.fee_estimate_pct

    def lookup(self, *, price: float, abs_delta_bps: float) -> float | None:
        hit = self._real.lookup(price=price, abs_delta_bps=abs_delta_bps)
        if hit is not None:
            return hit
        # Real priors missed. Apply the fallback ONLY for the CH3 cell.
        tier = tier_label_for_price(price)
        if tier in self._tier_relax and abs_delta_bps < self._delta_floor:
            return self._p_win_fallback
        return None


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
        tier_relax_p_win_fallback: float | None = DEFAULT_TIER_RELAX_P_WIN_FALLBACK,
        # H.2.12 path A - per-tier side-direction block. Operator-tunable
        # via env. Each tuple lists tier labels (e.g. "70-85%") where the
        # corresponding side is REJECTED. Phase-G-data follow-up:
        # tier 70-85% UP fires net -$5.06/trade (n=41) vs DOWN at +$0.13
        # (n=31); blocking UP in that tier eliminates the catastrophic
        # asymmetric-payoff bleeder. Symmetric block_down option is the
        # mirror case (e.g. block DOWN in 15-30% if a future audit
        # surfaces the same pattern on the low end).
        block_up_in_tiers: tuple[str, ...] = (),
        block_down_in_tiers: tuple[str, ...] = (),
        tier_relax_price_floor: float = DEFAULT_TIER_RELAX_PRICE_FLOOR,
        hour_blocklist_utc: tuple[int, ...] = DEFAULT_HOUR_BLOCKLIST_UTC,
        hour_blocklist_tiers: tuple[str, ...] = DEFAULT_HOUR_BLOCKLIST_TIERS,
        # Phase T Improvement #1 — explicit (hour, tier) pair blocklist.
        # If both this param AND the legacy utc/tiers params are set, the
        # final pair set is the union. See design/phase-T-hour-blocklist-v2.md.
        hour_blocklist_pairs: tuple[tuple[int, str], ...] = DEFAULT_HOUR_BLOCKLIST_PAIRS,
        # Phase P Session 3 — Market Mode Detector (MMD) wiring.
        # design/P.1-market-mode-detector-integration.md. When mmd_getter
        # is set, every fire decision gains `mmd=<label> mmd_conf=<conf>`
        # in the rationale. If mmd_mode=="gate" AND the label is in
        # mmd_labels_to_abstain (and not "UNKNOWN" — UNKNOWN is always
        # pass-through), the fire is dropped. Session 3 ships SHADOW
        # only — operator promotes shadow→gate at Phase Q after Day-5
        # re-soak data.
        mmd_getter: Callable[[], object] | None = None,
        mmd_mode: str = "shadow",
        mmd_labels_to_abstain: tuple[str, ...] = (),
        # Phase Q aggressive: side-specific MMD gate. Tuples of (label, side)
        # pairs; when the MMD reading matches `label` AND the fire's `side`
        # matches, the fire is abstained (gate mode only). Targets the
        # MIXED+side=DOWN killer cell (+$3.16/tr on n=226 across 8 days)
        # by setting MMD_ABSTAIN_BY_SIDE=MIXED:UP — keep firing DOWN-side
        # in MIXED regime, abstain UP-side. UNKNOWN remains pass-through.
        mmd_abstain_by_side: tuple[tuple[str, str], ...] = (),
        # Phase T Improvement #2 — cell-flip detector. Both detector +
        # history must be supplied together (consistency check at init).
        # Default None → detector disabled. When enabled, after H.2.12
        # and before super()._maybe_fire runs, a per-cell rolling-WR
        # check abstains if WR has dropped below break-even by more
        # than detector.abstain_threshold_pp. History is strategy-owned
        # (NOT runner-owned per design deviation — see commit message);
        # cross-restart persistence NOT implemented. Settlement
        # feedback comes via on_settle() called by the runner after
        # bankroll.apply_settle.
        cell_flip_detector: CellFlipDetector | None = None,
        cell_fire_history: CellFireHistory | None = None,
        # Phase T Improvement #1.5 — per-cell fire mechanism. When True,
        # at most 1 fire per (tier, side, |Δbps| bucket) cell per window;
        # second fire on the same cell is abstained even if the outer
        # multi_fire_cap has headroom. A second fire on a DIFFERENT cell
        # is allowed (subject to the outer cap). Default False = legacy
        # cap-only behavior. See design/phase-T-per-cell-fire.md.
        per_cell_fire_enabled: bool = False,
        **v2_kwargs: object,
    ) -> None:
        super().__init__(priors=priors, **v2_kwargs)  # type: ignore[arg-type]
        if multi_fire_cap < 1:
            raise ValueError(f"multi_fire_cap must be >= 1; got {multi_fire_cap}")
        lo, hi = ev_bad_bucket
        if not (0.0 <= lo < hi):
            raise ValueError(f"ev_bad_bucket must satisfy 0 <= lo < hi; got ({lo}, {hi})")
        if tier_relax_p_win_fallback is not None and not 0.0 < tier_relax_p_win_fallback < 1.0:
            raise ValueError(
                f"tier_relax_p_win_fallback must be in (0, 1) or None; "
                f"got {tier_relax_p_win_fallback}"
            )
        if not 0.0 <= tier_relax_price_floor < 1.0:
            raise ValueError(
                f"tier_relax_price_floor must be in [0.0, 1.0); " f"got {tier_relax_price_floor}"
            )
        for h in hour_blocklist_utc:
            if not 0 <= h <= 23:
                raise ValueError(f"hour_blocklist_utc entries must be in [0, 23]; got {h}")
        if hour_blocklist_utc and not hour_blocklist_tiers:
            raise ValueError(
                "hour_blocklist_tiers must be non-empty when hour_blocklist_utc "
                "is non-empty (no-tier-scope = block-all is not supported; "
                "set both to empty tuples to disable)"
            )
        # Phase T Improvement #1 — validate explicit pairs. Each entry must
        # be a (hour, tier) tuple with hour in [0, 23] and a non-empty tier
        # string. Tier-label canonicality is enforced downstream by the
        # set-membership check against tier_label_for_price(ask); a bogus
        # tier here just never matches. Distinct loop variable name from
        # the MMD-pair loop below so mypy doesn't narrow the type across
        # loops.
        for ht_pair in hour_blocklist_pairs:
            if not isinstance(ht_pair, tuple) or len(ht_pair) != 2:
                raise ValueError(
                    f"hour_blocklist_pairs entries must be (hour, tier) tuples; got {ht_pair!r}"
                )
            ph, pt = ht_pair
            if not isinstance(ph, int) or not 0 <= ph <= 23:
                raise ValueError(f"hour_blocklist_pairs hour must be int in [0, 23]; got {ph!r}")
            if not isinstance(pt, str) or not pt:
                raise ValueError(f"hour_blocklist_pairs tier must be a non-empty str; got {pt!r}")
        if mmd_mode not in ("shadow", "gate"):
            raise ValueError(f"mmd_mode must be one of 'shadow'|'gate'; got {mmd_mode!r}")
        for pair in mmd_abstain_by_side:
            if len(pair) != 2 or pair[1] not in ("UP", "DOWN"):
                raise ValueError(
                    f"mmd_abstain_by_side entries must be (label, 'UP'|'DOWN') tuples; got {pair!r}"
                )
        # Phase T #2 — detector + history consistency. Either both set or
        # both None; supplying only one is a misconfiguration that would
        # silently disable the feature.
        if (cell_flip_detector is None) != (cell_fire_history is None):
            raise ValueError(
                "cell_flip_detector and cell_fire_history must be supplied together "
                "(both set to enable, both None to disable). "
                f"Got detector={cell_flip_detector is not None}, "
                f"history={cell_fire_history is not None}."
            )
        self._bankroll_getter = bankroll_getter
        self._kelly = kelly if kelly is not None else KellyConfig()
        self._multi_fire_cap = multi_fire_cap
        self._tier_relax = frozenset(tier_relax_delta)
        self._ev_bad_lo, self._ev_bad_hi = ev_bad_bucket
        self._tier_relax_p_win_fallback = tier_relax_p_win_fallback
        self._block_up_in_tiers = frozenset(block_up_in_tiers)
        self._block_down_in_tiers = frozenset(block_down_in_tiers)
        self._tier_relax_price_floor = tier_relax_price_floor
        self._hour_blocklist_utc = frozenset(hour_blocklist_utc)
        self._hour_blocklist_tiers = frozenset(hour_blocklist_tiers)
        # Phase T Improvement #1 — union of:
        #   (a) explicit pairs from hour_blocklist_pairs
        #   (b) cartesian product of legacy utc x tiers (backward-compat)
        # The check at fire-time is a single membership test against this
        # union; legacy params keep working with byte-identical semantics.
        _pairs_from_legacy: frozenset[tuple[int, str]] = frozenset(
            (h, t) for h in hour_blocklist_utc for t in hour_blocklist_tiers
        )
        self._hour_blocklist_pairs: frozenset[tuple[int, str]] = (
            frozenset(hour_blocklist_pairs) | _pairs_from_legacy
        )
        self._mmd_getter = mmd_getter
        self._mmd_mode = mmd_mode
        self._mmd_labels_to_abstain = frozenset(mmd_labels_to_abstain)
        self._mmd_abstain_by_side = frozenset(mmd_abstain_by_side)
        self._cell_flip_detector = cell_flip_detector
        self._cell_fire_history = cell_fire_history
        # Phase T Improvement #1.5 — per-cell fire mechanism state. The
        # dict tracks which (tier, side, |Δ| bucket) cells have already
        # fired in the current window. Cleared on every WindowBoundary
        # open event in _on_boundary.
        self._per_cell_fire_enabled = per_cell_fire_enabled
        self._fires_per_cell_this_window: dict[str, int] = {}
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

    def set_mmd_getter(self, getter: Callable[[], object] | None) -> None:
        """Rebind the MMD-getter callback after construction (Phase P S3).

        The MMD's poller task is created in ``main()`` after the strategy
        already exists. Public so run_paper.py can wire the live getter
        without reaching into ``_mmd_getter`` directly.
        """
        self._mmd_getter = getter

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
            # Phase T Improvement #1.5 — reset per-cell fire tracking on
            # each new window. Always clear (not gated on enabled) so the
            # state stays clean if operator flips the env mid-run.
            self._fires_per_cell_this_window.clear()
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

        # J.2 — hour-of-day blocklist. Operator-scoped abstain by (UTC
        # hour, tier label). H.3 audit 2026-05-13 H.5 era: tier 70-85% x
        # (22, 23, 0) UTC was the catastrophic bleed band (23Z WR 0% /
        # -$18.32/tr, 00Z -$7.02/tr). 21Z x 70-85% was profitable
        # (+$2.13/tr) — the scope is intentionally narrow. Phase T
        # Improvement #1 (2026-05-21) extends to tier 30-50% x
        # {05, 06, 17, 21, 23, 0} UTC per Phase N forensic F5 (n=131,
        # -$1,748 over 5 days). The check is a single membership test
        # against the union pair-set (which absorbs legacy utc/tiers
        # via cartesian expansion). Empty pair set → noop. Abstain
        # BEFORE the multi-fire counter ticks; the window stays free
        # for a later qualifying tick after the hour rolls over (though
        # in practice a 5-min window spans no hour boundary).
        if self._hour_blocklist_pairs:
            hour = _dt.datetime.fromtimestamp(now_ts_utc_ns / 1_000_000_000, tz=_dt.UTC).hour
            if (hour, tier) in self._hour_blocklist_pairs:
                return None

        # Phase T Improvement #1.5 — per-cell fire mechanism. Cell key
        # INCLUDES side (differs from #2 detector's side-agnostic key).
        # Abstain if THIS exact (tier, side, |Δ| bucket) cell has already
        # fired in this window; allow if a different cell. The outer
        # multi_fire_cap still binds as a hard ceiling on TOTAL fires.
        # Default off — operator opts in via SPOT_AWARE_PER_CELL_FIRE_ENABLED.
        # See design/phase-T-per-cell-fire.md.
        per_cell_key: str | None = None
        if self._per_cell_fire_enabled:
            per_cell_key = f"{tier}|{side_guess}|{'hi' if abs(d_bps) >= 5 else 'lo'}"
            if per_cell_key in self._fires_per_cell_this_window:
                return None

        # H.2.12 path A — per-tier side-direction block. Operator can
        # disable specific side/tier combinations via env. Default
        # empty sets pass through unchanged. Surgical: abstain BEFORE
        # the multi-fire counter ticks and BEFORE any super() work,
        # so the window remains free for a later qualifying tick.
        if side_guess == "UP" and tier in self._block_up_in_tiers:
            return None
        if side_guess == "DOWN" and tier in self._block_down_in_tiers:
            return None

        # Phase T Improvement #2 — cell-flip detector. Compute cell-key
        # from (tier, |Δbps|≥5) and check rolling per-cell WR against
        # break-even (= fill_price). Abstain if rolling_wr has dropped
        # > abstain_threshold_pp below break-even on >= min_samples
        # observations. Default (both None) is pass-through. See
        # design/phase-T-cell-flip-detector.md §2 + §5.
        if self._cell_flip_detector is not None and self._cell_fire_history is not None:
            cell_key = CellFireHistory.cell_key_for(tier=tier, abs_d_bps=abs(d_bps))
            recent = self._cell_fire_history.recent_wins(cell_key)
            abstain, reason = self._cell_flip_detector.should_abstain(
                fill_price=ask_guess,
                recent_wins=recent,
            )
            if abstain:
                # Log to stderr-ish — operator audit trail without polluting
                # the decision-log (which only records fires, not abstains).
                # The reason string is machine-parseable per design doc §2.
                import logging as _log

                _log.getLogger(__name__).info("cell-flip abstain: cell=%s %s", cell_key, reason)
                return None

        # v2's `_maybe_fire` reads `self._delta_min` and `self._priors`
        # directly. We swap both for this fire only (single-threaded
        # event loop → safe). The priors swap installs a `_PriorsFallback`
        # for tier_relax tiers so the CH3 winning cell can fire even
        # when the shipped priors table misses at low |Δ|. Restore on
        # every exit path via try/finally.
        saved_delta_min = self._delta_min
        saved_priors = self._priors
        if tier in self._tier_relax:
            self._delta_min = 0.0
            if self._tier_relax_p_win_fallback is not None:
                self._priors = _PriorsFallback(  # type: ignore[assignment]
                    real=saved_priors,
                    p_win_fallback=self._tier_relax_p_win_fallback,
                    tier_relax=self._tier_relax,
                    delta_floor=saved_delta_min,
                )
        try:
            base_decision = super()._maybe_fire(now_ts_utc_ns)
        finally:
            self._delta_min = saved_delta_min
            self._priors = saved_priors

        if base_decision is None:
            return None

        # J.1 — CH3 price floor in tier_relax cells. H.3 audit 2026-05-13
        # on n=111 live CH3 fires showed BELOW 0.42 lose at 25.5% WR /
        # -$5.70/trade (n=51) and ABOVE 0.42 win at 56.7% WR / +$1.77/
        # trade (n=60). Direction is FLOOR (block below) — inverted from
        # the H.3 spec's original ceiling framing per measured data.
        # Surgical: applies ONLY in tier_relax cells (CH3 scope). Other
        # tiers are unaffected. Reset _fired_for_window so a later
        # qualifying tick in the same window can re-evaluate (mirrors
        # CH2 + CH4 abstain semantics). Set price_floor=0.0 to disable.
        if (
            self._tier_relax_price_floor > 0.0
            and tier in self._tier_relax
            and base_decision.price_limit < self._tier_relax_price_floor
        ):
            self._fired_for_window = None
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

        # Phase P Session 3 — MMD annotation + (optional) gate. Read the
        # current MMD label, append `mmd=<label> mmd_conf=<conf>` to the
        # rationale, and (in gate mode only) abstain if the label is in
        # the operator-configured abstain set. UNKNOWN is ALWAYS pass-
        # through (no abstain), even in gate mode — that's the
        # design §6 failure-mode contract: a degraded MMD never blocks
        # firing. Any exception in the getter is treated as UNKNOWN.
        mmd_label = "UNKNOWN"
        mmd_conf = 0.0
        if self._mmd_getter is not None:
            try:
                reading = self._mmd_getter()
                # Duck-typed — strategy doesn't import MmdReading to keep
                # the dependency one-way (strategies → typing only).
                mmd_label = str(getattr(reading, "label", "UNKNOWN")) or "UNKNOWN"
                mmd_conf = float(getattr(reading, "confidence", 0.0))
            except Exception:
                mmd_label = "UNKNOWN"
                mmd_conf = 0.0
            if (
                self._mmd_mode == "gate"
                and mmd_label != "UNKNOWN"
                and mmd_label in self._mmd_labels_to_abstain
            ):
                # Reset per-window flag so a later tick in the same window
                # can re-evaluate. Do not tick the multi-fire counter.
                self._fired_for_window = None
                return None
            # Phase Q aggressive side-specific gate: (label, bet-side) pairs.
            # `bet-side` is the UP/DOWN bet direction (from `side_guess`),
            # NOT Decision.side which is BUY/SELL (order direction).
            # E.g., MMD_ABSTAIN_BY_SIDE=MIXED:UP abstains UP-side fires in
            # MIXED regime while keeping DOWN-side firing — targets the
            # MIXED+DOWN cell (+$3.16/tr on n=226). UNKNOWN remains
            # pass-through here too.
            if (
                self._mmd_mode == "gate"
                and mmd_label != "UNKNOWN"
                and (mmd_label, side_guess) in self._mmd_abstain_by_side
            ):
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
        # Append MMD annotation when the getter is wired (any label,
        # incl. UNKNOWN — Phase N audit needs to bucket fires by
        # "MMD-available" vs "MMD-unavailable" to compute the
        # promote-to-gate counterfactual).
        if self._mmd_getter is not None:
            new_rationale = f"{new_rationale} mmd={mmd_label} mmd_conf={mmd_conf:.2f}"
        # Phase T Improvement #1.5 — if per-cell is enabled, ALWAYS reset
        # _fired_for_window so subsequent ticks can try OTHER cells, not
        # just when the outer cap has headroom. The per-cell dict + outer
        # cap together throttle the firing; the legacy single-fire flag
        # would otherwise block all subsequent ticks once cap is hit.
        # If per-cell is disabled, keep the legacy semantics exactly.
        if self._per_cell_fire_enabled or self._fires_this_window < self._multi_fire_cap:
            self._fired_for_window = None
        # Phase T Improvement #1.5 — register this cell as fired for the
        # current window so a same-cell re-attempt this window abstains.
        if self._per_cell_fire_enabled and per_cell_key is not None:
            self._fires_per_cell_this_window[per_cell_key] = 1
        final_decision = dc_replace(base_decision, size_usd=bet, rationale=new_rationale)
        # Phase T Improvement #2 — register the pending fire for the
        # cell-flip detector. window_ts + asset_id uniquely identifies
        # the fire across the strategy/runner boundary; the runner calls
        # on_settle() with the same key after settlement. cell_key was
        # computed above at the abstain check; recompute here on the
        # final path (cheap; avoids carrying state across the super()
        # call which may swap _priors).
        if self._cell_fire_history is not None and self._window_ts is not None:
            ck = CellFireHistory.cell_key_for(tier=tier, abs_d_bps=abs(d_bps))
            self._cell_fire_history.register_pending(
                window_ts=self._window_ts,
                asset_id=final_decision.asset_id,
                cell_key=ck,
            )
        return final_decision

    def on_settle(self, *, window_ts: int, asset_id: str, won: bool) -> None:
        """Phase T Improvement #2 — settlement feedback for the cell-flip
        detector. Runner calls this after bankroll.apply_settle. Looks up
        the cell_key registered at fire time, appends the win/loss outcome
        to that cell's rolling history. No-op if the detector is disabled
        or no pending entry exists for this (window_ts, asset_id) — the
        latter happens after a bot restart (pending state is lost; the
        cell history catches up over the next ~min_samples fires)."""
        if self._cell_fire_history is None:
            return
        cell_key = self._cell_fire_history.pop_pending(window_ts=window_ts, asset_id=asset_id)
        if cell_key is None:
            return
        self._cell_fire_history.apply_settle(cell_key=cell_key, won=won)

    async def on_event(self, event: MarketEvent) -> Decision | None:
        # Inherit v2's dispatch verbatim — no async I/O added in the
        # fire path (defense L3 against the LLM queue-overflow class
        # of incidents).
        return await super().on_event(event)
