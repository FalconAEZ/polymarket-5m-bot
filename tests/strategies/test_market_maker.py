"""Tests for polymarket_bot.strategies.market_maker.

Coverage per design/S.1-market-maker-bot.md §2.1-§2.6 + Session 2 prompt
test list. Pure unit tests (no IO outside tmp paths, no asyncio, no network).

Sections:
  1. round_to_tick + tier_for_price utilities
  2. LadderPlanner.plan_levels — full ladder, skips, sizing
  3. LadderPlanner.plan_update — book-move thresholds, window-end cleanup
  4. InventoryTracker — add / confirm / drop / gross / resolve
  5. RiskGate — each cap, halt, daily-loss
  6. PayoutResolver — UP win, DOWN win, cross-side inventory
  7. MarketMakerStrategy — integration + reset + multi-market
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from polymarket_bot.strategies.j7_priors import J7Priors
from polymarket_bot.strategies.market_maker import (
    DEFAULT_PRICE_FLOOR,
    DEFAULT_TIER_SIDE_BLOCKLIST,
    CancelOrder,
    InventoryTracker,
    LadderPlanner,
    MarketMakerStrategy,
    OpenOrder,
    OrderStatus,
    PayoutResolver,
    PlaceOrder,
    RiskCaps,
    RiskGate,
    Side,
    round_to_tick,
    tier_for_price,
)

# Fixture priors covering all 6 tiers so tests can pick any depth.
FULL_PRIORS_DATA = {
    "schema_version": 1,
    "name": "test",
    "source": {"n_trades_joined": 306966},
    "tiers": {
        "<15%": {"aligned": {"n": 722, "wr": 0.137, "per_trade_pnl": 8.83}},
        "15-30%": {"aligned": {"n": 3167, "wr": 0.250, "per_trade_pnl": 0.11}},
        "30-50%": {"aligned": {"n": 14802, "wr": 0.454, "per_trade_pnl": 1.17}},
        "50-70%": {"aligned": {"n": 39681, "wr": 0.631, "per_trade_pnl": 0.95}},
        "70-85%": {"aligned": {"n": 28674, "wr": 0.780, "per_trade_pnl": 0.40}},
        "85-100%": {"aligned": {"n": 14916, "wr": 0.917, "per_trade_pnl": 0.65}},
    },
}


@pytest.fixture
def priors(tmp_path: Path) -> J7Priors:
    path = tmp_path / "j7.json"
    path.write_text(json.dumps(FULL_PRIORS_DATA))
    # Use a generous max_bet so ladder levels can vary instead of all
    # clipping to the live-micro $10 ceiling, which would hide planner bugs.
    return J7Priors.load(refresh_path=path, bootstrap_path=path, max_bet_usd=100.0)


# ---------- 1. utilities ----------


def test_round_to_tick_rounds_down() -> None:
    """Tick 0.01: 0.555 → 0.55 (not 0.56). Round DOWN keeps ladders safe."""
    assert round_to_tick(0.555, "0.01") == 0.55
    assert round_to_tick(0.50, "0.01") == 0.50
    assert round_to_tick(0.99, "0.01") == 0.99


def test_round_to_tick_honors_coarser_tick() -> None:
    """Tick 0.1: 0.55 → 0.5; 0.95 → 0.9."""
    assert round_to_tick(0.55, "0.1") == 0.5
    assert round_to_tick(0.95, "0.1") == 0.9


def test_round_to_tick_rejects_bad_tick() -> None:
    with pytest.raises(ValueError, match="tick_size must be > 0"):
        round_to_tick(0.5, "0.0")


def test_tier_for_price_boundaries() -> None:
    """Boundaries inclusive-lower / exclusive-upper per design/j7_priors.md."""
    assert tier_for_price(0.10) == "<15%"
    assert tier_for_price(0.149) == "<15%"
    assert tier_for_price(0.15) == "15-30%"
    assert tier_for_price(0.50) == "50-70%"  # 0.50 is the boundary, falls in upper bucket
    assert tier_for_price(0.499) == "30-50%"
    assert tier_for_price(0.85) == "85-100%"
    assert tier_for_price(0.999) == "85-100%"


def test_tier_for_price_returns_none_on_degenerate() -> None:
    assert tier_for_price(0.0) is None
    assert tier_for_price(1.0) is None
    assert tier_for_price(-0.1) is None


# ---------- 2. LadderPlanner.plan_levels ----------


def test_plan_levels_full_ladder_at_mid_ask(priors: J7Priors) -> None:
    """best_ask=$0.40: levels at $0.35, $0.30, $0.20 — all in +EV tiers."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t_up",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=5.0,
    )
    assert len(levels) == 3
    prices = sorted([lvl.price for lvl in levels])
    assert prices == pytest.approx([0.20, 0.30, 0.35])
    # Each level lives in a real tier with positive priors → positive size.
    for lvl in levels:
        assert lvl.size_usd > 0
        assert lvl.size_shares > 0


def test_plan_levels_skips_side_when_ask_too_low(priors: J7Priors) -> None:
    """best_ask < $0.10 → entire side skipped (every depth clips the floor)."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.08,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=5.0,
    )
    assert levels == []


def test_plan_levels_skips_individual_level_below_floor(priors: J7Priors) -> None:
    """best_ask=$0.20: -$0.05=0.15 OK; -$0.10=0.10 OK; -$0.20=0.00 below floor → skip."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.20,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    # The L3 level (-$0.20) lands at 0.00 < DEFAULT_PRICE_FLOOR ($0.05) → skipped.
    assert all(lvl.price >= DEFAULT_PRICE_FLOOR for lvl in levels)


def test_plan_levels_skips_when_below_min_order_size(priors: J7Priors) -> None:
    """If size_shares < min_order_size_shares, skip the level."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    # min_order_size_shares of 1000 will reject any level whose Kelly bet
    # in shares is below 1000 — at $5-$10 sizes that's everything.
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1000.0,
    )
    assert levels == []


def test_plan_levels_skip_when_negative_ev(tmp_path: Path) -> None:
    """If post-tick price >= p_win, the level is -EV → planner skips it."""
    # Craft a priors fixture where p_win=0.50 in 30-50% tier.
    bad = {
        "schema_version": 1,
        "source": {"n_trades_joined": 1},
        "tiers": {
            "30-50%": {"aligned": {"n": 1, "wr": 0.40, "per_trade_pnl": 0.0}},
        },
    }
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad))
    priors = J7Priors.load(refresh_path=bad_path, bootstrap_path=bad_path)
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    # All ladder levels in 30-50% tier will price > p_win=0.40 → -EV.
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.55,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    # 0.50 and 0.45 are both > p_win=0.40 → skip. 0.35 is in 30-50% but < 0.40 = OK.
    for lvl in levels:
        assert lvl.price < 0.40


# ---------- 3. LadderPlanner.plan_update ----------


def test_plan_update_initial_places_full_ladder(priors: J7Priors) -> None:
    """First book update (no previous_ask) → place all 3 levels."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    actions = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        current_best_ask=0.40,
        previous_best_ask=None,
        open_orders=[],
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    place_actions = [a for a in actions if isinstance(a, PlaceOrder)]
    assert len(place_actions) == 3


def test_plan_update_no_op_when_book_stable(priors: J7Priors) -> None:
    """Small book move (< l1_repost_threshold) → no actions."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    # Open orders representing an active ladder.
    open_orders = [
        OpenOrder(
            order_id=f"o{i}",
            level=planner.plan_levels(
                market_id="m1",
                token_id="t",
                side=Side.UP,
                best_ask=0.40,
                bankroll_usd=1000.0,
                tick_size="0.01",
                min_order_size_shares=1.0,
            )[i],
            status=OrderStatus.LIVE,
            placed_ts_ns=0,
        )
        for i in range(3)
    ]
    actions = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        current_best_ask=0.405,  # +0.005 move, below 0.02 threshold
        previous_best_ask=0.40,
        open_orders=open_orders,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    assert actions == []


def test_plan_update_cancels_L1_only_on_small_move(priors: J7Priors) -> None:
    """Move > 0.02 but < 0.05 → cancel L1, place fresh L1, leave L2+L3."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    base_levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    open_orders = [
        OpenOrder(order_id=f"o{i}", level=base_levels[i], status=OrderStatus.LIVE, placed_ts_ns=0)
        for i in range(3)
    ]
    actions = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        current_best_ask=0.43,  # +0.03 move
        previous_best_ask=0.40,
        open_orders=open_orders,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    cancels = [a for a in actions if isinstance(a, CancelOrder)]
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    assert len(cancels) == 1
    assert len(places) == 1
    # The L1 (smallest depth_from_ask) is the one cancelled.
    cancelled_id = cancels[0].order_id
    cancelled_order = next(o for o in open_orders if o.order_id == cancelled_id)
    assert cancelled_order.level.depth_from_ask_usd == 0.05


def test_plan_update_cancels_all_on_big_move(priors: J7Priors) -> None:
    """Move > 0.05 → cancel all 3 + repost full ladder."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    base_levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    open_orders = [
        OpenOrder(order_id=f"o{i}", level=base_levels[i], status=OrderStatus.LIVE, placed_ts_ns=0)
        for i in range(3)
    ]
    actions = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        current_best_ask=0.48,  # +0.08 move
        previous_best_ask=0.40,
        open_orders=open_orders,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    cancels = [a for a in actions if isinstance(a, CancelOrder)]
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    # Big move (> 0.05): the planner cancels ALL existing orders and
    # reposts whatever fresh ladder levels are +EV at the new best_ask.
    # Place count depends on which levels survive the priors filter; the
    # test's invariant is just "cancel all + some fresh ladder posted".
    assert len(cancels) == 3
    assert len(places) >= 1


def test_plan_update_window_end_cancels_all_no_replace(priors: J7Priors) -> None:
    """Seconds-remaining < 15 → cancel ALL, place NOTHING (no carry into resolve)."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    base_levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    open_orders = [
        OpenOrder(order_id=f"o{i}", level=base_levels[i], status=OrderStatus.LIVE, placed_ts_ns=0)
        for i in range(3)
    ]
    actions = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        current_best_ask=0.40,
        previous_best_ask=0.40,
        open_orders=open_orders,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=10.0,  # < 15
    )
    cancels = [a for a in actions if isinstance(a, CancelOrder)]
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    assert len(cancels) == 3
    assert places == []


# ---------- 4. InventoryTracker ----------


def test_inventory_tracker_add_in_flight_accumulates() -> None:
    t = InventoryTracker()
    t.add_in_flight("m1", Side.UP, 10.0, 25.0)
    t.add_in_flight("m1", Side.UP, 5.0, 10.0)
    pos = t.position("m1", Side.UP)
    assert pos.in_flight_usd == 15.0
    assert pos.in_flight_shares == 35.0
    assert pos.filled_usd == 0.0  # not yet confirmed


def test_inventory_tracker_confirm_drains_in_flight_to_filled() -> None:
    t = InventoryTracker()
    t.add_in_flight("m1", Side.UP, 10.0, 20.0)
    t.confirm_in_flight("m1", Side.UP, 10.0, 20.0)
    pos = t.position("m1", Side.UP)
    assert pos.in_flight_usd == 0.0
    assert pos.filled_usd == 10.0
    assert pos.filled_shares == 20.0


def test_inventory_tracker_drop_does_not_credit_filled() -> None:
    """Drop (cancel/fail) decreases in_flight but doesn't add to filled."""
    t = InventoryTracker()
    t.add_in_flight("m1", Side.UP, 10.0, 20.0)
    t.drop_in_flight("m1", Side.UP, 10.0, 20.0)
    pos = t.position("m1", Side.UP)
    assert pos.in_flight_usd == 0.0
    assert pos.filled_usd == 0.0


def test_inventory_tracker_gross_includes_in_flight() -> None:
    """gross_usd = filled + in_flight so caps catch in-flight bursts."""
    t = InventoryTracker()
    t.add_in_flight("m1", Side.UP, 10.0, 20.0)
    t.confirm_in_flight("m1", Side.UP, 5.0, 10.0)  # half confirmed
    pos = t.position("m1", Side.UP)
    assert pos.gross_usd == 10.0  # 5 in_flight + 5 filled


def test_inventory_tracker_gross_exposure_for_market_sums_both_sides() -> None:
    t = InventoryTracker()
    t.add_in_flight("m1", Side.UP, 10.0, 20.0)
    t.add_in_flight("m1", Side.DOWN, 8.0, 16.0)
    t.add_in_flight("m2", Side.UP, 50.0, 100.0)  # different market
    assert t.gross_exposure_for_market("m1") == 18.0
    assert t.gross_exposure_for_market("m2") == 50.0


def test_inventory_tracker_resolve_window_up_win() -> None:
    """UP wins, bought 20 UP shares at avg $0.40 ($8) and 10 DOWN at $0.60 ($6).
    Realized: UP_win = 20 - 8 = +$12; DOWN_loss = -6. Net = +$6."""
    t = InventoryTracker()
    t.confirm_in_flight("m1", Side.UP, 8.0, 20.0)
    t.confirm_in_flight("m1", Side.DOWN, 6.0, 10.0)
    pnl, gross = t.resolve_window("m1", winning_side=Side.UP)
    assert pnl == pytest.approx(6.0)
    assert gross == pytest.approx(14.0)
    # State drained.
    assert ("m1", Side.UP) not in t.positions
    assert ("m1", Side.DOWN) not in t.positions


def test_inventory_tracker_resolve_window_down_win() -> None:
    """DOWN wins same setup: DOWN_win = 10 - 6 = +$4; UP_loss = -8. Net = -$4."""
    t = InventoryTracker()
    t.confirm_in_flight("m1", Side.UP, 8.0, 20.0)
    t.confirm_in_flight("m1", Side.DOWN, 6.0, 10.0)
    pnl, _ = t.resolve_window("m1", winning_side=Side.DOWN)
    assert pnl == pytest.approx(-4.0)


# ---------- 5. RiskGate ----------


def test_riskgate_allows_when_under_caps() -> None:
    g = RiskGate(caps=RiskCaps(max_inventory_per_token_usd=50.0))
    t = InventoryTracker()
    allowed, reason = g.can_place(
        market_id="m1", side=Side.UP, size_usd=10.0, tracker=t, open_orders_count=0
    )
    assert allowed
    assert reason == "ok"


def test_riskgate_rejects_zero_size() -> None:
    g = RiskGate()
    t = InventoryTracker()
    allowed, reason = g.can_place(
        market_id="m1", side=Side.UP, size_usd=0.0, tracker=t, open_orders_count=0
    )
    assert not allowed
    assert reason == "zero_size"


def test_riskgate_rejects_when_halted() -> None:
    g = RiskGate()
    g.force_halt()
    t = InventoryTracker()
    allowed, reason = g.can_place(
        market_id="m1", side=Side.UP, size_usd=5.0, tracker=t, open_orders_count=0
    )
    assert not allowed
    assert reason == "halted"


def test_riskgate_rejects_when_open_orders_at_cap() -> None:
    g = RiskGate(caps=RiskCaps(max_open_orders_global=20))
    t = InventoryTracker()
    allowed, reason = g.can_place(
        market_id="m1", side=Side.UP, size_usd=5.0, tracker=t, open_orders_count=20
    )
    assert not allowed
    assert reason == "max_open_orders"


def test_riskgate_rejects_when_inventory_cap_breached() -> None:
    g = RiskGate(caps=RiskCaps(max_inventory_per_token_usd=20.0))
    t = InventoryTracker()
    t.confirm_in_flight("m1", Side.UP, 15.0, 30.0)
    allowed, reason = g.can_place(
        market_id="m1", side=Side.UP, size_usd=10.0, tracker=t, open_orders_count=0
    )
    assert not allowed
    assert reason == "max_inventory_per_token"


def test_riskgate_rejects_when_gross_exposure_cap_breached() -> None:
    g = RiskGate(
        caps=RiskCaps(
            max_inventory_per_token_usd=100.0,
            max_gross_exposure_per_window_usd=30.0,
        )
    )
    t = InventoryTracker()
    t.confirm_in_flight("m1", Side.UP, 15.0, 30.0)
    t.confirm_in_flight("m1", Side.DOWN, 10.0, 20.0)
    allowed, reason = g.can_place(
        market_id="m1", side=Side.UP, size_usd=10.0, tracker=t, open_orders_count=0
    )
    assert not allowed
    assert reason == "max_gross_exposure"


def test_riskgate_record_realized_pnl_triggers_halt_at_cap() -> None:
    """Daily loss exceeding cap auto-halts the gate."""
    g = RiskGate(caps=RiskCaps(max_daily_loss_usd=50.0))
    g.record_realized_pnl(-30.0)
    assert not g.halted
    g.record_realized_pnl(-25.0)  # total -55 > -50 cap
    assert g.halted


# ---------- 6. PayoutResolver ----------


def test_payout_resolver_records_realized_pnl_into_gate() -> None:
    """Resolver pushes realized PnL through the gate's daily-loss counter."""
    t = InventoryTracker()
    g = RiskGate(caps=RiskCaps(max_daily_loss_usd=20.0))
    resolver = PayoutResolver(tracker=t, gate=g)
    t.confirm_in_flight("m1", Side.UP, 20.0, 25.0)  # UP cost $20, has 25 shares
    # If DOWN wins, UP loses entire $20 → realized -$20.
    result = resolver.resolve(market_id="m1", winning_side=Side.DOWN)
    assert result.realized_pnl_usd == pytest.approx(-20.0)
    assert result.market_id == "m1"
    # Gate received it.
    assert g.today_realized_pnl_usd == pytest.approx(-20.0)


# ---------- 7. MarketMakerStrategy integration ----------


def test_strategy_on_book_update_places_initial_ladder(priors: J7Priors) -> None:
    """First tick: strategy returns the full ladder as PlaceOrder actions.
    Passes blocklist=frozenset() to bypass the default tier-side filter
    so this test isolates the placement mechanic (blocklist behavior has
    dedicated tests below)."""
    strat = MarketMakerStrategy(
        priors=priors, bankroll_getter=lambda: 1000.0, blocklist=frozenset()
    )
    actions = strat.on_book_update(
        market_id="m1",
        token_id="t_up",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    assert len(places) == 3


def test_strategy_rejects_places_after_inventory_cap(priors: J7Priors) -> None:
    """Inventory already at cap → RiskGate filters out place actions."""
    # Cap UP at $10 — well below the ladder's natural $30+ total.
    gate = RiskGate(caps=RiskCaps(max_inventory_per_token_usd=10.0))
    strat = MarketMakerStrategy(priors=priors, bankroll_getter=lambda: 1000.0, gate=gate)
    # Pre-fill UP inventory above the cap so further placements are rejected.
    strat.tracker.confirm_in_flight("m1", Side.UP, 10.0, 20.0)
    actions = strat.on_book_update(
        market_id="m1",
        token_id="t_up",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    assert places == []  # all filtered out by the gate


def test_strategy_on_resolution_credits_pnl_and_drains_state(priors: J7Priors) -> None:
    """on_resolution drains the market's inventory and returns the WindowPnl."""
    strat = MarketMakerStrategy(priors=priors, bankroll_getter=lambda: 1000.0)
    strat.tracker.confirm_in_flight("m1", Side.UP, 8.0, 20.0)
    strat.tracker.confirm_in_flight("m1", Side.DOWN, 6.0, 10.0)
    result = strat.on_resolution(market_id="m1", winning_side=Side.UP)
    # UP win: realized = (20 - 8) + (-6) = +6
    assert result.realized_pnl_usd == pytest.approx(6.0)
    assert result.gross_traded_usd == pytest.approx(14.0)
    assert ("m1", Side.UP) not in strat.tracker.positions


def test_strategy_reset_clears_all_state(priors: J7Priors) -> None:
    """reset() drops inventory, halts state, previous_best_ask, open_orders."""
    strat = MarketMakerStrategy(priors=priors, bankroll_getter=lambda: 1000.0)
    strat.tracker.confirm_in_flight("m1", Side.UP, 5.0, 10.0)
    strat.previous_best_ask[("m1", Side.UP)] = 0.5
    strat.gate.force_halt()
    strat.reset()
    assert strat.tracker.positions == {}
    assert strat.previous_best_ask == {}
    assert not strat.gate.halted


def test_strategy_multi_market_isolation(priors: J7Priors) -> None:
    """Inventory on m1 must not affect placement on m2 (gross_exposure is per-market)."""
    gate = RiskGate(caps=RiskCaps(max_gross_exposure_per_window_usd=50.0))
    strat = MarketMakerStrategy(
        priors=priors, bankroll_getter=lambda: 1000.0, gate=gate, blocklist=frozenset()
    )
    # Saturate m1 to its gross cap.
    strat.tracker.confirm_in_flight("m1", Side.UP, 25.0, 50.0)
    strat.tracker.confirm_in_flight("m1", Side.DOWN, 25.0, 50.0)
    # m2 should still be open.
    actions = strat.on_book_update(
        market_id="m2",
        token_id="t_up",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    assert len(places) > 0


def test_strategy_in_flight_counts_toward_cap(priors: J7Priors) -> None:
    """A MATCHED order (in_flight) counts toward MAX_INVENTORY_PER_TOKEN."""
    gate = RiskGate(caps=RiskCaps(max_inventory_per_token_usd=12.0))
    strat = MarketMakerStrategy(priors=priors, bankroll_getter=lambda: 1000.0, gate=gate)
    # Simulate a recently-matched but not-yet-confirmed fill.
    strat.on_fill(
        market_id="m1",
        side=Side.UP,
        size_usd=10.0,
        size_shares=20.0,
        status=OrderStatus.MATCHED,
    )
    # Cap is $12; in-flight is $10; a $5 PlaceOrder would push to $15 → reject.
    allowed, reason = strat.gate.can_place(
        market_id="m1",
        side=Side.UP,
        size_usd=5.0,
        tracker=strat.tracker,
        open_orders_count=0,
    )
    assert not allowed
    assert reason == "max_inventory_per_token"


# ---------- 8. Blocklist (Edge 1, audit 2026-05-20) ----------


def test_default_blocklist_contains_audited_cells() -> None:
    """The default blocklist must contain the 3 cells the audit identified
    as statistically-negative-$/tr from n=8,000+ fresh weekly fills."""
    assert ("50-70%", "DOWN") in DEFAULT_TIER_SIDE_BLOCKLIST
    assert ("15-30%", "UP") in DEFAULT_TIER_SIDE_BLOCKLIST
    assert ("30-50%", "UP") in DEFAULT_TIER_SIDE_BLOCKLIST


def test_blocklist_skips_levels_in_blocked_tier_side(priors: J7Priors) -> None:
    """At best_ask=0.40 UP-side, all 3 ladder depths land in tiers
    (30-50%, 30-50%, 15-30%) that are blocked for UP. Expect no levels."""
    planner = LadderPlanner(priors=priors)  # default blocklist active
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    assert levels == []


def test_blocklist_allows_non_blocked_side_at_same_ask(priors: J7Priors) -> None:
    """Same best_ask=0.40 but Side.DOWN — 30-50% x DOWN is NOT in the
    default blocklist (only 30-50% x UP is). Expect at least one level."""
    planner = LadderPlanner(priors=priors)  # default blocklist active
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    assert len(levels) >= 1
    for lvl in levels:
        # No level should be in a (tier, "DOWN") blocked cell.
        from polymarket_bot.strategies.market_maker import tier_for_price

        tier = tier_for_price(lvl.price)
        assert (tier, "DOWN") not in DEFAULT_TIER_SIDE_BLOCKLIST


def test_blocklist_blocks_50_70_down_at_high_ask(priors: J7Priors) -> None:
    """At best_ask=0.55 DOWN-side, L1 (0.50) and L2 (0.45) are at the
    50-70%/30-50% boundary; L3 (0.35) is in 30-50% which is allowed for
    DOWN AND has enough Kelly edge to size above MIN_BET. The 0.50 level
    falls in 50-70% which is blocked for DOWN. Expect L3 placed."""
    planner = LadderPlanner(priors=priors)  # default blocklist active
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.55,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    # At least one level survives at < 0.50 (in 30-50% allowed for DOWN);
    # nothing in 50-70% blocked cell.
    for lvl in levels:
        # No surviving level lands in the 50-70% x DOWN blocked cell.
        assert lvl.price < 0.50, f"level price {lvl.price} should be in 30-50% tier"
    assert len(levels) >= 1, "expected at least the L3 level at 0.35 in 30-50%"


def test_empty_blocklist_restores_full_ladder(priors: J7Priors) -> None:
    """Explicit empty blocklist disables the filter — original ladder
    behavior returns."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    assert len(levels) == 3


def test_custom_blocklist_can_extend_default(priors: J7Priors) -> None:
    """Operator can extend the default blocklist with additional cells."""
    custom = DEFAULT_TIER_SIDE_BLOCKLIST | frozenset({("<15%", "UP")})
    planner = LadderPlanner(priors=priors, blocklist=custom)
    # best_ask=0.20 with UP → L1=0.15 (15-30% UP blocked default),
    # L2=0.10 (<15% UP, blocked by custom extension), L3 would clip floor.
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.UP,
        best_ask=0.20,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    assert levels == []


def test_strategy_blocklist_passthrough_to_planner(priors: J7Priors) -> None:
    """MarketMakerStrategy passes its blocklist through to the
    LadderPlanner it builds in __post_init__."""
    custom = frozenset({("85-100%", "UP")})
    strat = MarketMakerStrategy(priors=priors, bankroll_getter=lambda: 1000.0, blocklist=custom)
    assert strat.planner.blocklist == custom


def test_strategy_default_blocklist_matches_module_default(priors: J7Priors) -> None:
    """Strategy without an explicit blocklist uses the module default."""
    strat = MarketMakerStrategy(priors=priors, bankroll_getter=lambda: 1000.0)
    assert strat.planner.blocklist == DEFAULT_TIER_SIDE_BLOCKLIST


# ---------- 9. Late-window size multiplier (Edge 2, audit 2026-05-20) ----------


def test_late_window_multiplier_doubles_size(priors: J7Priors) -> None:
    """Same ladder, seconds_remaining=30 (LATE) → sizes 2x vs no-multiplier."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    # Baseline (no seconds_remaining passed = no multiplier).
    base_levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    # LATE-window placement (seconds_remaining < 60).
    late_levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=30.0,
    )
    assert len(base_levels) == len(late_levels)
    # Each level in late_levels should be sized larger (up to the
    # max_inventory_per_token cap which is the multiplier ceiling).
    cap = planner.caps.max_inventory_per_token_usd
    for base, late in zip(
        sorted(base_levels, key=lambda lvl: lvl.price),
        sorted(late_levels, key=lambda lvl: lvl.price),
        strict=True,
    ):
        # If base size is below half the cap, late should be exactly 2x.
        if base.size_usd * 2 <= cap:
            assert late.size_usd == pytest.approx(base.size_usd * 2)
        else:
            # Otherwise clamped to the cap.
            assert late.size_usd == pytest.approx(cap)


def test_late_window_multiplier_inactive_outside_threshold(priors: J7Priors) -> None:
    """seconds_remaining=120 (>60s, MID-window) → no multiplier applied."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    base = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
    )
    mid = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=120.0,
    )
    for b, m in zip(
        sorted(base, key=lambda lvl: lvl.price), sorted(mid, key=lambda lvl: lvl.price), strict=True
    ):
        assert m.size_usd == pytest.approx(b.size_usd)


def test_late_window_multiplier_capped_by_inventory_limit(priors: J7Priors) -> None:
    """Boosted size cannot exceed max_inventory_per_token_usd."""
    caps = RiskCaps(max_inventory_per_token_usd=15.0)
    planner = LadderPlanner(priors=priors, caps=caps, blocklist=frozenset())
    levels = planner.plan_levels(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        best_ask=0.40,
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=10.0,
    )
    for lvl in levels:
        assert lvl.size_usd <= 15.0


def test_plan_update_threads_seconds_remaining_through(priors: J7Priors) -> None:
    """plan_update must pass seconds_remaining to plan_levels so Edge 2
    fires when the book-move-triggered placement also lands in LATE."""
    planner = LadderPlanner(priors=priors, blocklist=frozenset())
    # First call places ladder, seconds_remaining=30 (LATE).
    actions = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        current_best_ask=0.40,
        previous_best_ask=None,
        open_orders=[],
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=30.0,
    )
    places = [a for a in actions if isinstance(a, PlaceOrder)]
    # Compare to a no-late call.
    actions_no_late = planner.plan_update(
        market_id="m1",
        token_id="t",
        side=Side.DOWN,
        current_best_ask=0.40,
        previous_best_ask=None,
        open_orders=[],
        bankroll_usd=1000.0,
        tick_size="0.01",
        min_order_size_shares=1.0,
        seconds_remaining=200.0,
    )
    places_no_late = [a for a in actions_no_late if isinstance(a, PlaceOrder)]
    assert len(places) == len(places_no_late)
    # LATE-window places should be sized larger.
    total_late = sum(p.level.size_usd for p in places)
    total_no_late = sum(p.level.size_usd for p in places_no_late)
    assert total_late > total_no_late
