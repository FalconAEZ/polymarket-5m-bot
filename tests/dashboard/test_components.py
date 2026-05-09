"""Smoke tests for polymarket_bot.dashboard.components.

Validates that each component returns a well-formed HTML string with
the expected pmb-* class names. Visual rendering is not tested — that
falls out of scope for unit tests; the screenshots in
runbooks/research/dashboard-v2-screenshots/ serve that role.
Per design/dashboard-v2.md §6.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polymarket_bot.dashboard.components import (
    PipelineStage,
    TapeEvent,
    bankroll_chip,
    kpi_satellite,
    live_tape,
    market_tabs,
    orderbook_from_ctf,
    orderbook_panel,
    pipeline_strip,
    pixel_display,
    spot_orderbook_widget,
    tape_event_inline,
    tape_events_from_decisions,
    tradingview_chart,
)
from polymarket_bot.dashboard.loaders import DecisionRow
from polymarket_bot.dashboard.polymarket_orderbook import CTFBookSnapshot, OrderbookRow

ASSET = "0x" + "ab" * 31


def test_pixel_display_emits_hero_class() -> None:
    out = pixel_display("$39.51", sign="+", glow="good")
    assert "pmb-hero" in out
    assert "pmb-hero--good" in out
    assert "$39.51" in out
    assert "+" in out


def test_pixel_display_no_sign() -> None:
    out = pixel_display("$0.00", sign=None, glow="neutral")
    assert "pmb-hero__sign" not in out


def test_bankroll_chip_positive_delta_is_good() -> None:
    out = bankroll_chip(1000.0, 1039.51)
    assert "pmb-bankroll--good" in out
    assert "$1,039.51" in out
    assert "+" in out


def test_bankroll_chip_negative_delta_is_bad() -> None:
    out = bankroll_chip(1000.0, 950.0)
    assert "pmb-bankroll--bad" in out


def test_kpi_satellite_with_tone() -> None:
    out = kpi_satellite(label="FIRE RATE", value="14.2/hr", subtitle="341/d", tone="warn")
    assert "pmb-kpi--warn" in out
    assert "FIRE RATE" in out
    assert "14.2/hr" in out


def test_live_tape_empty_state() -> None:
    out = live_tape([])
    assert "pmb-tape--empty" in out


def test_live_tape_renders_events_doubled() -> None:
    ev = TapeEvent(glyph="▲", label="WIN +$5.88", tone="good", age_s=12.0)
    out = live_tape([ev])
    # Doubled for seamless scroll → label appears twice.
    assert out.count("WIN +$5.88") == 2


def test_tape_event_inline_escapes_label() -> None:
    out = tape_event_inline(TapeEvent("▲", "<script>", "good", 1.0))
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_tape_events_from_decisions_filters_to_settled() -> None:
    now = datetime.now(tz=UTC)
    rows = [
        DecisionRow(
            decision_id="d1",
            window_ts=1_700_000_000,
            decision_dt_utc=now - timedelta(minutes=1),
            asset_id=ASSET,
            side="UP",
            size_usd=5.0,
            price_limit=0.5,
            ttl_s=18,
            composite_pct=0.6,
            strategy="spot_aware",
            mode="aggressive",
            delta_bps=12.0,
            p_win=0.55,
            ev_dollars=0.05,
            fill_price=0.5,
            fee_usd=0.001,
            resolution="UP",
            pnl_usd=5.88,
        ),
        DecisionRow(
            decision_id="d2",
            window_ts=1_700_000_300,
            decision_dt_utc=now - timedelta(minutes=2),
            asset_id=ASSET,
            side="UP",
            size_usd=5.0,
            price_limit=0.5,
            ttl_s=18,
            composite_pct=0.6,
            strategy="spot_aware",
            mode="aggressive",
            delta_bps=12.0,
            p_win=0.55,
            ev_dollars=0.05,
            fill_price=None,  # not filled — should be skipped
            fee_usd=None,
            resolution="UP",
            pnl_usd=None,
        ),
    ]
    events = tape_events_from_decisions(rows, n=12)
    assert len(events) == 1
    assert events[0].tone == "good"
    assert "WIN" in events[0].label


def test_pipeline_strip_renders_all_stages() -> None:
    stages = [
        PipelineStage(
            name="CAPTURE",
            detail="4 feeds",
            latency_ms=118.0,
            status="alive",
            is_active=True,
        ),
        PipelineStage(
            name="STRATEGY",
            detail="spot_aware",
            latency_ms=None,
            status="alive",
            is_active=False,
        ),
    ]
    out = pipeline_strip(stages)
    assert "pmb-stage--alive" in out
    assert "pmb-stage--active" in out
    # Stage names render in Title case; CSS upper-cases them visually.
    assert "Capture" in out
    assert "Strategy" in out
    # Numbered prefix in the new Bloomberg-style layout
    assert ">01<" in out
    assert ">02<" in out
    assert "118ms" in out


def test_orderbook_panel_offline_renders_offline_marker() -> None:
    out = orderbook_panel(
        side="spot",
        rows_ask=[],
        rows_bid=[],
        mid=None,
        title="BTC SPOT",
        subtitle="—",
        offline=True,
    )
    assert "FEED OFFLINE" in out


def test_orderbook_panel_with_rows_includes_mid() -> None:
    out = orderbook_panel(
        side="spot",
        rows_ask=[OrderbookRow(price=77502.34, size=95.0, cumulative_size=95.0)],
        rows_bid=[OrderbookRow(price=77502.16, size=173.0, cumulative_size=173.0)],
        mid=77502.25,
        title="BTC SPOT",
        subtitle="Binance",
    )
    assert "$77,502.25" in out
    assert "$77,502.34" in out


def test_orderbook_from_ctf_none_renders_offline() -> None:
    out = orderbook_from_ctf(None)
    assert "FEED OFFLINE" in out


def test_orderbook_from_ctf_with_snap() -> None:
    snap = CTFBookSnapshot(
        market_slug="btc-updown-5m-1700000000",
        up_token_id="0xabc",
        down_token_id="0xdef",
        side="UP",
        rows_ask=(OrderbookRow(price=0.572, size=1200.0, cumulative_size=1200.0),),
        rows_bid=(OrderbookRow(price=0.562, size=600.0, cumulative_size=600.0),),
        mid=0.567,
        asof=datetime.now(tz=UTC),
        rtt_ms=120.5,
    )
    out = orderbook_from_ctf(snap)
    assert "FEED OFFLINE" not in out
    assert "OUR MARKET" in out
    assert "0.5670" in out


def test_tradingview_chart_includes_symbol() -> None:
    out = tradingview_chart()
    assert "BINANCE:BTCUSDT" in out
    assert "tv.js" in out


def test_spot_orderbook_widget_includes_ws_url() -> None:
    out = spot_orderbook_widget()
    assert "wss://stream.binance.com" in out
    assert "btcusdt@depth20@100ms" in out


def test_market_tabs_active_btc() -> None:
    out = market_tabs(active="BTC")
    assert "pmb-mtabs__tab--active" in out
    assert "BTC" in out
