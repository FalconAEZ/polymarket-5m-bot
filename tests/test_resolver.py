"""Tests for polymarket_bot.resolver — pure functions, no I/O.

Covers active_window_ts/active_slug arithmetic (also exercised by the
polymarket feed tests, but those route through the feed module's
re-export — these tests pin the canonical resolver path) plus the two
resolution helpers. Polymarket tie-resolves UP per market spec, so the
boundary case current_oracle == window_open_oracle yields "UP".
"""

from __future__ import annotations

from polymarket_bot.resolver import (
    active_slug,
    active_window_ts,
    actual_resolution,
    hypothetical_now,
)


def test_active_window_ts_floors_to_300() -> None:
    assert active_window_ts(1_714_999_800) == 1_714_999_800
    assert active_window_ts(1_714_999_801) == 1_714_999_800
    assert active_window_ts(1_715_000_099) == 1_714_999_800
    assert active_window_ts(1_715_000_100) == 1_715_000_100
    assert active_window_ts(0) == 0


def test_active_slug_format() -> None:
    assert active_slug(1_715_000_100) == "btc-updown-5m-1715000100"
    assert active_slug(0) == "btc-updown-5m-0"


def test_hypothetical_now_basic() -> None:
    assert hypothetical_now(60_000.0, 60_001.0) == "UP"
    assert hypothetical_now(60_000.0, 59_999.99) == "DOWN"


def test_hypothetical_now_tie_resolves_up() -> None:
    """Polymarket ties resolve UP; the helper must follow that convention."""
    assert hypothetical_now(60_000.0, 60_000.0) == "UP"
    assert hypothetical_now(0.0, 0.0) == "UP"


def test_actual_resolution_uses_close_vs_open() -> None:
    assert actual_resolution(1_715_000_100, 60_000.0, 60_500.0) == "UP"
    assert actual_resolution(1_715_000_100, 60_500.0, 60_000.0) == "DOWN"


def test_actual_resolution_tie_resolves_up() -> None:
    assert actual_resolution(1_715_000_100, 60_000.0, 60_000.0) == "UP"


def test_resolution_functions_are_distinct_names() -> None:
    """Sanity: hypothetical_now and actual_resolution are truly two functions."""
    assert hypothetical_now is not actual_resolution
