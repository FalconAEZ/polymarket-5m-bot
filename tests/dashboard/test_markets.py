"""Tests for polymarket_bot.dashboard.markets.

Phase 11.A.X ships with BTC only; this test guards the design contract
that the loaders are parameterized for multi-market expansion in Phase
11.B-F. Per design/dashboard-v2.md §9.
"""

from __future__ import annotations

import pytest

from polymarket_bot.dashboard.markets import MARKETS, market_by_id


def test_btc_is_present() -> None:
    btc = market_by_id("BTC")
    assert btc.market_id == "BTC"
    assert btc.slug_prefix == "btc-updown-5m"


def test_unknown_market_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        market_by_id("DOGE")


def test_phase_11a_ships_btc_only() -> None:
    assert [m.market_id for m in MARKETS] == ["BTC"]
