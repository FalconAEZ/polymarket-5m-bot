"""Router — confidence-driven decision function for every 5-min window.

Pure function from ``RouterContext`` -> ``RouterDecision``. Implements
the locked spec at ``design/phase-16b-every-window-mode.md`` §3.

Composition of 5 confidence inputs (locked weights, tunable via
RouterConfig env knobs):
    confidence = W_DET*det + W_REG*reg + W_TIER*tier + W_LLM*llm + W_KELLY*kelly

Then:
    size = lerp_with_kink_and_tier_cap(confidence, tier)
    side = pick_side(composite, llm_meta, regime)
    ttl  = ttl_for(regime, tier, seconds_to_close)
    fill = "taker_fallback" if tier in extreme else "maker"

Safety vetoes (RARE — preserve Phase 11.A defense + catastrophic EV):
    - phantom_fill_defense: price < $0.05 AND ask_size_top is None
    - catastrophic_ev: hypothetical EV at $5 < -$0.50
    - cold_start: no spot context (caller falls through to base)

Anti-vibe: every veto reason is logged; the router NEVER silently
abstains.  Every fire records its confidence breakdown for audit.
"""

from __future__ import annotations

from polymarket_bot.strategies.every_window.config import RouterConfig
from polymarket_bot.strategies.every_window.types import (
    FillStyle,
    RouterContext,
    RouterDecision,
    Side,
)
from polymarket_bot.strategies.sizing import kelly_suggested_size_usd


def _det_score(abs_delta_bps: float) -> float:
    """Map ``|delta_bps|`` to ``[0, 1]`` using observed predictive ranges.

    From study §3.3 measurements on 513 fires:
      0-1 bps : 50.2% WR / -$0.09 per trade -> 0.0 (coinflip noise)
      1-2 bps : 48.7% WR / +$0.14 per trade -> 0.25 (small edge)
      2-5 bps : 55.0% WR / +$0.63 per trade -> 0.50 (real edge)
      5-10 bps: 78.9% WR / +$1.67 per trade -> 0.85 (high edge)
      >=10 bps: extrapolated -> 1.00 (max signal)
    """
    if abs_delta_bps < 1.0:
        return 0.0
    if abs_delta_bps < 2.0:
        return 0.25
    if abs_delta_bps < 5.0:
        return 0.50
    if abs_delta_bps < 10.0:
        return 0.85
    return 1.0


def _llm_score(
    meta_action: str | None,
    meta_confidence: float | None,
    consensus: float | None,
) -> float:
    """Blend LLM meta action+confidence with specialist consensus.

    - FIRE w/ confidence: clip to [0.3, 1.0]
    - ABSTAIN: 0.30 (router still fires, just small)
    - meta=None or no signal: 0.50 (neutral)
    - If consensus given: blend 50/50 with base
    """
    if meta_action == "FIRE" and meta_confidence is not None:
        base = max(0.30, min(1.0, meta_confidence))
    elif meta_action == "ABSTAIN":
        base = 0.30
    else:
        base = 0.50
    if consensus is not None:
        base = 0.5 * base + 0.5 * consensus
    return base


def _kelly_score(kelly_suggested_usd: float) -> float:
    """Normalize half-Kelly $ size to [0, 1]; $22 -> 1.0 (2.2% bankroll).

    The 3% cap in sizing.py means $30 is theoretical max at $1k bankroll;
    we normalize to $22 so a 2.2% bankroll Kelly suggestion saturates the
    score (the remaining 0.8% is asymptotic).
    """
    if kelly_suggested_usd <= 0:
        return 0.0
    return min(1.0, kelly_suggested_usd / 22.0)


def _pick_side(ctx: RouterContext) -> Side:
    """Pick side per design §3.6:

    - Agreement: use deterministic (= base)
    - Disagreement in trending: use LLM (smart-money override)
    - Disagreement with |delta_bps| < 1: use LLM (deterministic is noise)
    - Else: use deterministic
    """
    base_side: Side = "UP" if (ctx.composite_pct or 0.0) >= 0 else "DOWN"
    if ctx.llm_meta_side is None or ctx.llm_meta_side == base_side:
        return base_side
    if ctx.regime == "trending":
        return ctx.llm_meta_side
    if abs(ctx.delta_bps) < 1.0:
        return ctx.llm_meta_side
    return base_side


def _ttl_for(regime: str, tier: str, seconds_to_close: int, config: RouterConfig) -> int:
    """TTL by regime + tier per design §3.7."""
    if regime == "chop":
        base = config.ttl_chop_s
    elif regime == "trending":
        base = config.ttl_trending_s
    else:
        base = config.ttl_default_s
    if tier in ("<15%", "85-100%"):
        base = max(base, config.ttl_extreme_floor_s)
    return min(base, max(10, seconds_to_close - 5))


def _fill_style_for(tier: str, config: RouterConfig) -> FillStyle:
    return "taker_fallback" if tier in config.taker_fallback_tiers else "maker"


def _size_for(confidence: float, tier: str, config: RouterConfig) -> float:
    """Size by confidence per design §3.5 (with kink + per-tier cap)."""
    if confidence < config.confidence_kink:
        return config.size_floor_usd
    raw = config.size_floor_usd + (config.size_cap_usd - config.size_floor_usd) * confidence
    cap = config.tier_per_trade_cap_usd.get(tier, config.size_cap_usd)
    return round(max(config.size_floor_usd, min(cap, raw)), 2)


def _veto_reason(ctx: RouterContext, config: RouterConfig) -> str | None:
    """Hard safety vetoes per design §3.9."""
    if ctx.spot_now is None or ctx.window_open_spot is None:
        return "cold_start"
    floor = config.phantom_fill_price_floor
    if ctx.best_ask_up is not None and ctx.best_ask_up < floor and ctx.ask_size_top is None:
        return "phantom_fill_defense"
    if ctx.best_ask_down is not None and ctx.best_ask_down < floor and ctx.ask_size_top is None:
        return "phantom_fill_defense"
    fp = ctx.fill_price_estimate
    pw = ctx.p_win_prior
    if fp is not None and pw is not None and fp > 0:
        ev = 5.0 * (pw * ((1.0 - fp) / fp) - (1.0 - pw))
        if ev < config.catastrophic_ev_floor_usd:
            return "catastrophic_ev"
    return None


class Router:
    """Phase 16.B every-window router. Pure function, single ``decide`` method.

    Construct once with a ``RouterConfig`` (env-driven defaults); call
    ``decide(ctx)`` per window. No mutation between calls.
    """

    def __init__(self, config: RouterConfig | None = None) -> None:
        self._config = config or RouterConfig()

    @property
    def config(self) -> RouterConfig:
        return self._config

    def decide(self, ctx: RouterContext) -> RouterDecision:
        """Return the router's verdict for one window."""
        config = self._config

        # 1. Veto check (rare — catastrophic guards)
        veto = _veto_reason(ctx, config)
        if veto is not None:
            return RouterDecision(
                fire=False,
                side="UP",  # placeholder; not used when fire=False
                size_usd=0.0,
                ttl_s=0,
                fill_style="maker",
                price_limit=0.0,
                confidence=0.0,
                veto_reason=veto,
                rationale=f"router=veto reason={veto} regime={ctx.regime} tier={ctx.tier}",
                inputs_breakdown={},
            )

        # 2. Confidence inputs
        det = _det_score(abs(ctx.delta_bps))
        reg = config.regime_score.get(ctx.regime, 0.50)
        tier = config.tier_score.get(ctx.tier, 0.50)
        llm = _llm_score(ctx.llm_meta_action, ctx.llm_meta_confidence, ctx.llm_consensus)
        kelly_suggested = kelly_suggested_size_usd(
            p_win=ctx.p_win_prior,
            fill_price=ctx.fill_price_estimate,
            bankroll_usd=ctx.bankroll_usd,
            fraction=config.kelly_fraction,
            max_bankroll_pct=config.kelly_max_pct,
        )
        kelly = _kelly_score(kelly_suggested)

        confidence = (
            config.w_det * det
            + config.w_reg * reg
            + config.w_tier * tier
            + config.w_llm * llm
            + config.w_kelly * kelly
        )
        confidence = max(0.0, min(1.0, confidence))

        # 3. Pick side, size, ttl, fill style
        side = _pick_side(ctx)
        size_usd = _size_for(confidence, ctx.tier, config)
        ttl_s = _ttl_for(ctx.regime, ctx.tier, ctx.seconds_to_close, config)
        fill_style = _fill_style_for(ctx.tier, config)

        # 4. Price limit: use the side's best_ask + slippage_buffer (existing default)
        if side == "UP":
            best = ctx.best_ask_up if ctx.best_ask_up is not None else 0.50
        else:
            best = ctx.best_ask_down if ctx.best_ask_down is not None else 0.50
        price_limit = round(min(0.99, best + 0.02), 4)  # 2c buffer matches spot_aware

        rationale = (
            f"strategy=every_window confidence={confidence:.3f} regime={ctx.regime} "
            f"tier={ctx.tier} delta_bps={ctx.delta_bps:+.2f} side={side} "
            f"size=${size_usd:.2f} ttl={ttl_s}s fill={fill_style}"
        )

        return RouterDecision(
            fire=True,
            side=side,
            size_usd=size_usd,
            ttl_s=ttl_s,
            fill_style=fill_style,
            price_limit=price_limit,
            confidence=confidence,
            veto_reason=None,
            rationale=rationale,
            inputs_breakdown={
                "det": det,
                "reg": reg,
                "tier": tier,
                "llm": llm,
                "kelly": kelly,
                "kelly_suggested_usd": kelly_suggested,
            },
        )
