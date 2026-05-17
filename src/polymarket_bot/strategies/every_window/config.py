"""RouterConfig — tunable thresholds, defaults match design/phase-16b-every-window-mode.md.

All numeric defaults match the locked design doc §3.4-3.8. Production
overrides via env vars in ``scripts/run_paper.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Locked defaults from design/phase-16b-every-window-mode.md §3.3
DEFAULT_REGIME_SCORE: dict[str, float] = {
    "trending": 1.00,
    "mixed": 0.70,
    "chop": 0.40,
    "unknown": 0.50,
}

DEFAULT_TIER_SCORE: dict[str, float] = {
    "<15%": 0.50,
    "15-30%": 1.00,
    "30-50%": 0.85,
    "50-70%": 0.25,
    "70-85%": 0.75,
    "85-100%": 0.50,
}

DEFAULT_TIER_PER_TRADE_CAP_USD: dict[str, float] = {
    "<15%": 10.0,
    "85-100%": 10.0,
}

DEFAULT_TAKER_FALLBACK_TIERS: tuple[str, ...] = ("<15%", "85-100%")


@dataclass(frozen=True, slots=True)
class RouterConfig:
    """Locked router thresholds — defaults from design doc §3.4-3.8."""

    # Confidence weights (sum should equal 1.0)
    w_det: float = 0.25
    w_reg: float = 0.20
    w_tier: float = 0.15
    w_llm: float = 0.25
    w_kelly: float = 0.15

    # Size shaping
    size_floor_usd: float = 5.0
    size_cap_usd: float = 30.0
    confidence_kink: float = 0.30

    # Kelly
    kelly_fraction: float = 0.5
    kelly_max_pct: float = 0.03
    bankroll_usd: float = 1000.0

    # TTL tuning
    ttl_default_s: int = 30
    ttl_chop_s: int = 90
    ttl_trending_s: int = 20
    ttl_extreme_floor_s: int = 90

    # Veto thresholds
    phantom_fill_price_floor: float = 0.05
    catastrophic_ev_floor_usd: float = -0.50

    # Per-tier scoring + caps (constructed lazily to keep dataclass hashable-friendly)
    regime_score: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_REGIME_SCORE))
    tier_score: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_TIER_SCORE))
    tier_per_trade_cap_usd: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_TIER_PER_TRADE_CAP_USD)
    )
    taker_fallback_tiers: tuple[str, ...] = DEFAULT_TAKER_FALLBACK_TIERS
