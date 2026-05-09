"""Multi-market constants for the v2 top-strip market switcher.

Phase 11.A.X ships with BTC only. Phase 11.B will append ETH; later
phases append additional markets. The top-strip tab control reads from
MARKETS; loaders take a market_id parameter that defaults to BTC. Per
design/dashboard-v2.md §9.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketConfig:
    market_id: str  # "BTC", "ETH", ...
    display_name: str
    slug_prefix: str  # "btc-updown-5m" — combines with window_ts


MARKETS: tuple[MarketConfig, ...] = (
    MarketConfig(market_id="BTC", display_name="BTC", slug_prefix="btc-updown-5m"),
)


def market_by_id(market_id: str) -> MarketConfig:
    for m in MARKETS:
        if m.market_id == market_id:
            return m
    raise KeyError(f"unknown market_id: {market_id!r}; known: {[m.market_id for m in MARKETS]}")
