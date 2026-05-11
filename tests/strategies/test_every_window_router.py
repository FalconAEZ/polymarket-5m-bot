"""Tests for the Phase 16.B every-window router.

Locked spec: design/phase-16b-every-window-mode.md §3 + §7.2.
"""

from __future__ import annotations

import time
from dataclasses import replace

from polymarket_bot.strategies.every_window import (
    Router,
    RouterConfig,
    RouterContext,
)


def _ctx(**overrides: object) -> RouterContext:
    """Build a baseline RouterContext; overrides apply via dataclass.replace."""
    base = RouterContext(
        window_ts=1_715_000_100,
        now_ts_utc_ns=(1_715_000_100 + 280) * 1_000_000_000,
        seconds_to_close=20,
        spot_now=80_000.0,
        window_open_spot=79_900.0,
        oracle_last=79_980.0,
        oracle_age_s=12.0,
        composite_pct=0.5,
        delta_bps=0.5,  # small (below kink)
        best_bid_up=0.45,
        best_ask_up=0.50,
        best_bid_down=0.50,
        best_ask_down=0.55,
        ask_size_top=100.0,
        book_imbalance=0.0,
        regime="mixed",
        tier="30-50%",
        llm_meta_action=None,
        llm_meta_side=None,
        llm_meta_confidence=None,
        llm_consensus=None,
        bankroll_usd=1000.0,
        p_win_prior=None,
        fill_price_estimate=0.50,
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


# ---------- pick_side ----------


def test_pick_side_agreement() -> None:
    r = Router()
    d = r.decide(_ctx(composite_pct=0.5, llm_meta_action="FIRE", llm_meta_side="UP"))
    assert d.fire
    assert d.side == "UP"


def test_pick_side_trending_disagreement_takes_llm() -> None:
    """LLM disagrees in trending regime -> LLM wins (smart-money override)."""
    r = Router()
    d = r.decide(
        _ctx(
            composite_pct=0.5,  # UP base
            llm_meta_action="FIRE",
            llm_meta_side="DOWN",
            llm_meta_confidence=0.8,
            regime="trending",
            delta_bps=3.0,  # big enough that not-low-delta rule
        )
    )
    assert d.side == "DOWN"


def test_pick_side_chop_disagreement_takes_deterministic() -> None:
    """LLM disagrees in chop -> deterministic wins (LLM has no edge in chop)."""
    r = Router()
    d = r.decide(
        _ctx(
            composite_pct=0.5,
            delta_bps=3.0,
            llm_meta_action="FIRE",
            llm_meta_side="DOWN",
            regime="chop",
        )
    )
    assert d.side == "UP"


def test_pick_side_low_delta_disagreement_takes_llm() -> None:
    """|Δbps| < 1 -> deterministic is noise, use LLM."""
    r = Router()
    d = r.decide(
        _ctx(
            composite_pct=0.5,
            delta_bps=0.3,
            llm_meta_action="FIRE",
            llm_meta_side="DOWN",
            regime="mixed",
        )
    )
    assert d.side == "DOWN"


# ---------- size_for (kink + cap) ----------


def test_size_for_floor_at_low_confidence() -> None:
    """All-zero signals -> confidence below kink -> $5 floor."""
    r = Router()
    d = r.decide(_ctx(delta_bps=0.1, regime="chop", tier="<15%"))
    assert d.fire
    assert d.size_usd == 5.0


def test_size_for_kink_below_returns_floor() -> None:
    """Synthetic confidence below kink -> floor."""
    config = RouterConfig(confidence_kink=0.30)
    r = Router(config)
    # Force confidence ~0.25 via small inputs
    d = r.decide(_ctx(delta_bps=0.0, regime="chop", tier="50-70%", llm_meta_action="ABSTAIN"))
    # Manually compute: det=0 + 0.20*0.40 + 0.15*0.25 + 0.25*0.30 + 0.15*0 = 0.193
    assert d.confidence < 0.30
    assert d.size_usd == 5.0


def test_size_for_high_confidence_scales_up() -> None:
    """High signals -> size scales above $5."""
    r = Router()
    d = r.decide(
        _ctx(
            delta_bps=12.0,  # det -> 1.0
            regime="trending",  # reg -> 1.0
            tier="15-30%",  # tier -> 1.0
            llm_meta_action="FIRE",
            llm_meta_confidence=1.0,  # llm -> 1.0
        )
    )
    assert d.confidence > 0.7
    assert d.size_usd > 5.0
    assert d.size_usd <= 30.0


def test_size_for_tier_extreme_capped_at_10() -> None:
    """`<15%` tier capped at $10 even at max confidence."""
    r = Router()
    d = r.decide(
        _ctx(
            delta_bps=12.0,
            regime="trending",
            tier="<15%",
            llm_meta_action="FIRE",
            llm_meta_confidence=1.0,
        )
    )
    assert d.size_usd <= 10.0


# ---------- ttl_for ----------


def test_ttl_for_chop_longer() -> None:
    r = Router()
    d = r.decide(_ctx(regime="chop", tier="30-50%", seconds_to_close=300))
    assert d.fire
    assert d.ttl_s == 90


def test_ttl_for_trending_shorter() -> None:
    r = Router()
    d = r.decide(_ctx(regime="trending", tier="30-50%", seconds_to_close=300))
    assert d.fire
    assert d.ttl_s == 20


def test_ttl_for_tier_extreme_floor_at_90() -> None:
    r = Router()
    d = r.decide(_ctx(regime="trending", tier="<15%", seconds_to_close=300))
    assert d.fire
    # extreme tier overrides trending
    assert d.ttl_s == 90


def test_ttl_for_clamped_by_seconds_to_close() -> None:
    r = Router()
    d = r.decide(_ctx(regime="chop", tier="30-50%", seconds_to_close=15))
    assert d.fire
    # min(90, max(10, 15-5)) = 10
    assert d.ttl_s == 10


# ---------- fill_style ----------


def test_fill_style_tier_extremes_taker_fallback() -> None:
    r = Router()
    d = r.decide(_ctx(tier="<15%"))
    assert d.fill_style == "taker_fallback"
    d = r.decide(_ctx(tier="85-100%"))
    assert d.fill_style == "taker_fallback"


def test_fill_style_normal_tier_maker() -> None:
    r = Router()
    for tier in ("15-30%", "30-50%", "50-70%", "70-85%"):
        d = r.decide(_ctx(tier=tier))  # type: ignore[arg-type]
        assert d.fill_style == "maker", f"tier {tier} should be maker"


# ---------- vetoes ----------


def test_veto_phantom_fill_low_ask_no_depth() -> None:
    """ask < $0.05 + ask_size_top is None -> veto (Phase 11.A regression)."""
    r = Router()
    d = r.decide(_ctx(best_ask_up=0.02, ask_size_top=None))
    assert not d.fire
    assert d.veto_reason == "phantom_fill_defense"


def test_veto_phantom_fill_low_ask_with_depth_no_veto() -> None:
    """Real depth at low price means real liquidity -> NOT a phantom."""
    r = Router()
    d = r.decide(_ctx(best_ask_up=0.02, ask_size_top=500.0))
    assert d.fire


def test_veto_catastrophic_ev() -> None:
    """EV < -$0.50 at $5 hypothetical -> veto."""
    r = Router()
    d = r.decide(
        _ctx(
            p_win_prior=0.10,  # very low
            fill_price_estimate=0.70,  # expensive
        )
    )
    # EV = 5 * (0.10 * ((1-0.70)/0.70) - 0.90) = 5 * (0.0429 - 0.90) = -$4.29
    assert not d.fire
    assert d.veto_reason == "catastrophic_ev"


def test_veto_cold_start() -> None:
    r = Router()
    d = r.decide(_ctx(spot_now=None))
    assert not d.fire
    assert d.veto_reason == "cold_start"


# ---------- breakdown / metadata ----------


def test_confidence_breakdown_returned() -> None:
    r = Router()
    d = r.decide(_ctx(delta_bps=3.0, regime="trending"))
    assert "det" in d.inputs_breakdown
    assert "reg" in d.inputs_breakdown
    assert "tier" in d.inputs_breakdown
    assert "llm" in d.inputs_breakdown
    assert "kelly" in d.inputs_breakdown
    assert d.inputs_breakdown["det"] == 0.50
    assert d.inputs_breakdown["reg"] == 1.00


def test_decision_rationale_contains_strategy_tag() -> None:
    """The rationale must contain `strategy=every_window` so the dashboard
    + decision-log readers can identify router-driven fires."""
    r = Router()
    d = r.decide(_ctx())
    assert "strategy=every_window" in d.rationale


# ---------- queue-overflow performance guard (feedback_test_under_load) ----------


def test_router_100_evals_under_500ms() -> None:
    """100 evaluations must complete < 500ms (hot-path budget).

    The router is on the bot's main loop — slow it down and the queue
    overflow regression from 2026-05-09 returns.
    """
    r = Router()
    ctx = _ctx(
        delta_bps=2.0,
        llm_meta_action="FIRE",
        llm_meta_confidence=0.7,
        llm_consensus=0.7,
        p_win_prior=0.55,
    )
    start = time.perf_counter()
    for _ in range(100):
        r.decide(ctx)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5, f"100 evals took {elapsed*1000:.1f}ms (budget 500ms)"


# ---------- side defaulting + price_limit ----------


def test_side_defaults_up_when_composite_zero() -> None:
    r = Router()
    d = r.decide(_ctx(composite_pct=0.0, llm_meta_side=None))
    assert d.side == "UP"


def test_price_limit_includes_buffer() -> None:
    r = Router()
    d = r.decide(_ctx(best_ask_up=0.55))
    # 0.55 + 0.02 buffer, rounded to 4 decimals
    assert d.fire
    assert abs(d.price_limit - 0.57) < 1e-6


def test_price_limit_capped_at_0_99() -> None:
    r = Router()
    d = r.decide(_ctx(best_ask_up=1.00))
    assert d.fire
    assert d.price_limit == 0.99


# ---------- regime + tier scoring ----------


def test_regime_chop_lower_confidence_than_trending() -> None:
    """Same other inputs, just regime differs -> chop has lower confidence."""
    r = Router()
    trending = r.decide(_ctx(delta_bps=3.0, regime="trending"))
    chop = r.decide(_ctx(delta_bps=3.0, regime="chop"))
    assert trending.confidence > chop.confidence


def test_tier_50_70_lower_confidence_than_30_50() -> None:
    """50-70% (the leak tier) sized smaller than 30-50%."""
    r = Router()
    a = r.decide(_ctx(delta_bps=3.0, tier="50-70%"))
    b = r.decide(_ctx(delta_bps=3.0, tier="30-50%"))
    assert a.confidence < b.confidence
    assert a.size_usd <= b.size_usd


# ---------- pytest sanity ----------


def test_router_default_config_weights_sum_to_one() -> None:
    config = RouterConfig()
    total = config.w_det + config.w_reg + config.w_tier + config.w_llm + config.w_kelly
    assert abs(total - 1.0) < 1e-9
