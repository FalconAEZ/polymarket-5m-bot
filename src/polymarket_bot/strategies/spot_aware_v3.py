"""SpotAwareStrategyV3 — v2 wrapped with a regime-detector gate.

Per design/regime_detector.md §"Wrapping v2 strategy". v3 == v2 plus
one additional check: only fire when the 5m/10m vol-ratio classifier
labels the current spot regime as "trending". Same priors, same tier
filter, same EV gate — just one new boolean upstream of the fire.

Validation evidence (runbooks/gate-evidence/regime-classifier-validation.txt
2026-05-10): on the 299-fire dataset, gating to trending only would
have improved per-trade pnl from +$0.02 (current) to +$1.75
(counterfactual), with WR 70.59% on the trending bucket vs 47.40% on
chop. Verdict (a): IMPLEMENT.

Trade-off the operator should understand: trending is rare (~6% of
windows). v3 fires much LESS frequently than v2, but each fire is
much MORE likely to win. Absolute weekly $ at $5/trade size will be
small; the value is in path-to-scaling — once v3 proves itself, sizing
unlocks (Phase 5/6).
"""

from __future__ import annotations

import re
from dataclasses import replace as dc_replace

from polymarket_bot.backtest.types import Decision, MarketEvent, SpotTick
from polymarket_bot.strategies.regime_detector import RegimeDetector
from polymarket_bot.strategies.spot_aware_v2 import SpotAwareStrategyV2

# Pre-compiled regexes for rewriting v2's rationale string to self-tag as v3.
# Why: v2 builds the rationale inside its own _maybe_fire path; v3 calls
# super().on_event(event) which returns v2's Decision unchanged. Without
# this rewrite, every v3 fire's rationale reads `strategy=spot_aware_v2
# mode=tier_restricted ...`, which (a) misleads anyone reading the log
# and (b) breaks downstream tooling that attributes strategy by parsing
# the rationale tag (scripts/four_day_audit.py, scripts/watch_first_v3_fire.py
# both had to be patched 2026-05-12 to compensate via --since-ts-ns and
# --strategy-override). This rewrite removes the workaround need going
# forward — fires self-tag correctly at the source.
_RE_STRATEGY = re.compile(r"\bstrategy=spot_aware_v2\b")
_RE_MODE = re.compile(r"\bmode=tier_restricted\b")


class SpotAwareStrategyV3(SpotAwareStrategyV2):
    """SpotAwareStrategyV2 + regime-gate. Fires only when the regime
    detector classifies the moment as 'trending'."""

    name: str = "spot_aware_v3"

    def __init__(
        self,
        *,
        regime_detector: RegimeDetector | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._regime: RegimeDetector = (
            regime_detector if regime_detector is not None else RegimeDetector()
        )

    @property
    def regime_detector(self) -> RegimeDetector:
        """Read-only accessor — used by tests and observability tooling."""
        return self._regime

    async def on_event(self, event: MarketEvent) -> Decision | None:
        # Feed every spot tick into the regime detector BEFORE letting
        # v2 do its work, so when v2's _maybe_fire path inspects the
        # regime we already have the latest tick incorporated.
        if isinstance(event, SpotTick):
            self._regime.observe_spot(event.ts_utc_ns, event.price)

        decision = await super().on_event(event)
        if decision is None:
            return None

        # v2 wants to fire. Gate on regime: only "trending" passes.
        # "chop" and "mixed" abstain (the high-WR slice is trending only).
        # "unknown" abstains too (better to skip 10 min of cold-start
        # fires than fire on a buffer that hasn't filled).
        regime = self._regime.classify(event.ts_utc_ns)
        if regime != "trending":
            # Reset v2's per-window fire-flag so a future tick in this
            # same window can still re-evaluate. v2 set the flag inside
            # _maybe_fire when constructing the decision; we have to
            # undo it because v3 is filtering AFTER v2's commit. Without
            # this reset, v3 would silently drop v2's fire AND prevent
            # any later same-window re-evaluation if the regime flips
            # mid-window.
            self._fired_for_window = None
            return None

        # Rewrite the rationale so this fire self-tags as v3 (see module-
        # level note on _RE_STRATEGY for the why). Word-boundary regex so
        # we don't accidentally rewrite a v2 substring that appears inside
        # some other token in the future. If v2's format ever changes and
        # the patterns no longer match, the rewrite becomes a no-op and we
        # fall back to v2's tag — graceful degradation, not a hard fail.
        new_rationale = _RE_STRATEGY.sub("strategy=spot_aware_v3", decision.rationale)
        new_rationale = _RE_MODE.sub("mode=trending_only", new_rationale)
        new_rationale = f"{new_rationale} regime=trending"
        return dc_replace(decision, rationale=new_rationale)
