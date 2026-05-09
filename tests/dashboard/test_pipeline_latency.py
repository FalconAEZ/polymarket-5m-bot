"""Tests for polymarket_bot.dashboard.pipeline_latency.

Covers: empty rows + no snap (everything None), snap age becomes
capture_ms, pending settlement countdown, fully resolved rows.
Per design/dashboard-v2.md §7.4.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from polymarket_bot.dashboard.loaders import DecisionRow, FeedSnapshot, HealthSnapshot
from polymarket_bot.dashboard.pipeline_latency import (
    WINDOW_DURATION_S,
    derive_pipeline_latencies,
)

ASSET = "0x" + "12" * 31

NOW = datetime(2026, 5, 9, 12, 0, tzinfo=UTC)


def _row(*, window_ts: int, resolution: str | None = None) -> DecisionRow:
    return DecisionRow(
        decision_id=f"d-{window_ts}",
        window_ts=window_ts,
        decision_dt_utc=datetime.fromtimestamp(window_ts, tz=UTC) + timedelta(seconds=15),
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
        resolution=resolution,  # type: ignore[arg-type]
        pnl_usd=5.0 if resolution else None,
    )


def _snap(age_s: float, *, path: Path | None = None) -> HealthSnapshot:
    return HealthSnapshot(
        feeds=[
            FeedSnapshot(
                name="binance",
                msgs_seen=1234,
                healthy=True,
                reconnects=0,
                last_error="",
                last_seen_ns=0,
            )
        ],
        snapshot_path=path if path is not None else Path("feeds_health.json"),
        snapshot_mtime_utc=NOW - timedelta(seconds=age_s),
    )


def test_empty_state_all_none() -> None:
    lat = derive_pipeline_latencies([], None, now=NOW)
    assert lat.capture_ms is None
    assert lat.persist_ms is None
    assert lat.settle_wait_s is None


def test_snap_age_becomes_capture_ms() -> None:
    lat = derive_pipeline_latencies([], _snap(age_s=0.4), now=NOW)
    assert lat.capture_ms is not None
    assert 350.0 <= lat.capture_ms <= 450.0


def test_persist_constant_when_rows_present() -> None:
    rows = [_row(window_ts=int((NOW - timedelta(minutes=2)).timestamp()))]
    lat = derive_pipeline_latencies(rows, None, now=NOW)
    assert lat.persist_ms == 3.0


def test_pending_settlement_countdown() -> None:
    """Window started 2m ago → ~3m remaining."""
    window_open = NOW - timedelta(minutes=2)
    rows = [_row(window_ts=int(window_open.timestamp()))]
    lat = derive_pipeline_latencies(rows, None, now=NOW)
    assert lat.settle_wait_s is not None
    assert 170.0 <= lat.settle_wait_s <= 190.0  # ~180s remaining


def test_resolved_rows_no_settle_countdown() -> None:
    rows = [
        _row(
            window_ts=int((NOW - timedelta(minutes=10)).timestamp()),
            resolution="UP",
        )
    ]
    lat = derive_pipeline_latencies(rows, None, now=NOW)
    assert lat.settle_wait_s is None


def test_settle_wait_clamps_at_zero_when_window_closed() -> None:
    window_open = NOW - timedelta(seconds=WINDOW_DURATION_S + 30)
    rows = [_row(window_ts=int(window_open.timestamp()))]
    lat = derive_pipeline_latencies(rows, None, now=NOW)
    assert lat.settle_wait_s == 0.0
