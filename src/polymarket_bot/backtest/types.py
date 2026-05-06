"""Backtest type definitions — MarketEvent sum type + Decision dataclass.

Pinned shapes consumed by every Strategy implementation under
polymarket_bot.strategies. The replay engine in Phase 3.1.5 produces
MarketEvents from captured Parquet files; the live runtime in Phase 6
will produce the same types from real WS streams. Strategies see one
interface either way. See design/backtest.md §2 for the full pin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["UP", "DOWN"]
SpotSource = Literal["binance", "coinbase"]
BoundaryKind = Literal["open", "close"]


@dataclass(frozen=True, slots=True)
class SpotTick:
    """A spot trade event from Binance or Coinbase. price is float USD."""

    ts_utc_ns: int
    source: SpotSource
    price: float


@dataclass(frozen=True, slots=True)
class OracleUpdate:
    """A Chainlink BTC/USD AnswerUpdated event on Polygon.

    price is the int256 'current' field decoded with Chainlink's 8-decimal
    BTC/USD scaling (so 60_000_00000000 → 60000.00). round_id is the
    aggregator round number; updated_at_s is the on-chain updatedAt
    field (unix seconds), distinct from ts_utc_ns which is our local
    receive time as nanoseconds.
    """

    ts_utc_ns: int
    price: float
    round_id: int
    updated_at_s: int


@dataclass(frozen=True, slots=True)
class BookUpdate:
    """A Polymarket WS book/price_change/last_trade_price event for one asset.

    side is the canonical UP or DOWN outcome the asset_id resolves to.
    The strategy needs both the asset_id (to place orders against) and
    the side (to know which direction we're betting). best_bid/best_ask
    are top-of-book in cents (0.01-0.99); None if the book is empty
    on that side.
    """

    ts_utc_ns: int
    asset_id: str
    side: Side
    best_bid: float | None
    best_ask: float | None
    bid_size_top: float | None
    ask_size_top: float | None


@dataclass(frozen=True, slots=True)
class WindowBoundary:
    """Synthesised by the replay engine at every 300s mark.

    NOT a real upstream event — purely a strategy-side convenience so the
    deterministic baseline (and the LLM agents in 3.2) can latch on
    window-open spot/oracle without computing window arithmetic
    themselves. window_ts is the start of the 5m window per
    polymarket_bot.resolver.active_window_ts.
    """

    ts_utc_ns: int
    window_ts: int
    kind: BoundaryKind


MarketEvent = SpotTick | OracleUpdate | BookUpdate | WindowBoundary


@dataclass(frozen=True, slots=True)
class Decision:
    """A strategy's decision to place an order. Consumed by the fill simulator.

    side is hardcoded "BUY" because we always buy outcome shares —
    selling short on Polymarket means buying the opposite outcome
    instead, which the strategy expresses by choosing the asset_id
    rather than the side. ttl_s is the limit-order time-to-live; per
    locked decision #6 ttl_s ∈ [10, 30].
    """

    ts_utc_ns: int
    asset_id: str
    side: Literal["BUY"]
    size_usd: float
    price_limit: float
    ttl_s: int
    rationale: str


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated fill from the FillSimulator. Phase 3.1.5 implementation."""

    ts_utc_ns: int
    asset_id: str
    size_filled: float
    price_filled: float
    fee_usd: float
