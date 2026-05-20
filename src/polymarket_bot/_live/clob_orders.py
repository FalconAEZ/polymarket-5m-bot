"""CLOB order client — Protocol + Mock + Live skeleton for MarketMakerStrategy.

Phase S Session 3 deliverable. Per design/S.1-market-maker-bot.md §2.1 and
the Session 3 prompt: a clean Protocol for MMB's order surface, an in-memory
Mock for tests + paper-mode shakedown, and a Live skeleton that wraps
py-clob-client for the real CLOB.

Hard requirements enforced by every concrete client:

  * `post_only=True` ALWAYS on maker-limit BUY orders (S.1.1 §Q2). Without
    this a limit at best_ask executes as taker; we want maker-only.
  * `neg_risk=False` as the default for BTC 5m markets (S.1.1 §Q5
    verified on live Gamma 2026-05-19).
  * Errors classified per agent-skills/order-patterns.md §Error Codes:
      INVALID_POST_ONLY_ORDER       → soft skip (log + drop, no retry).
      INVALID_ORDER_MIN_TICK_SIZE   → raise (our bug; we should have
                                      rounded via round_to_tick).
      INVALID_ORDER_MIN_SIZE        → raise (our bug; LadderPlanner
                                      should have filtered).
      INVALID_ORDER_NOT_ENOUGH_BALANCE → raise (operator funding issue).
      EXECUTION_ERROR / ORDER_DELAYED → log + treat as PENDING (retry by
                                       caller if appropriate).

The Live client is a skeleton in v1 — its surface matches the Mock so a
straight swap works, but full integration testing requires a funded Signer
+ live CLOB + USDC.e allowance (deferred to Session 4 with the empirical
probes per the phase plan). The Mock fully drives the paper-mode runner.

py-clob-client is synchronous. The Live client wraps each call in
`asyncio.to_thread(...)` so the runner's event loop stays unblocked.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Final, Protocol

from polymarket_bot.strategies.market_maker import OrderStatus

LOG = logging.getLogger("polymarket_bot._live.clob_orders")

# Default order TTL on the CLOB for resting maker limits. Polymarket
# Time-In-Force defaults to GTC (resting until cancelled or window-end);
# MMB owns its own cancel discipline via window-end cleanup.
DEFAULT_FEE_RATE_BPS: Final[int] = 0  # MMB places maker orders only; taker pays per Q1.


# ---------------- exception classes ----------------


class ClobOrderError(RuntimeError):
    """Base for all CLOB order errors. Carries the raw response field for triage."""

    def __init__(
        self, message: str, *, error_code: str | None = None, raw: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.raw = raw


class PostOnlyRejected(ClobOrderError):
    """The order would have crossed the spread; with post_only=True the CLOB
    rejects it. Caller treats this as a soft skip (log + drop the level)."""


class OrderTickViolation(ClobOrderError):
    """Order price did not align to the market's tick size. This is our bug
    (LadderPlanner should round via round_to_tick before submission)."""


class OrderSizeViolation(ClobOrderError):
    """Order size below the market's minimum. LadderPlanner should have
    filtered this level before submission."""


class InsufficientBalance(ClobOrderError):
    """Funder doesn't have enough USDC.e allowance or balance. Operator
    funding issue — halt MMB and surface to Telegram."""


# ---------------- data shapes ----------------


@dataclass(slots=True, frozen=True)
class OrderbookLevel:
    """One level of the order book — price + aggregated size in shares."""

    price: float
    size_shares: float


@dataclass(slots=True, frozen=True)
class Orderbook:
    """Snapshot of a token's order book at a point in time.

    Sorted: bids descending by price (best bid first), asks ascending by
    price (best ask first). `tick_size` and `min_order_size_shares` are
    market metadata read from `client.get_tick_size()` / `client.get_market()`.
    """

    token_id: str
    bids: tuple[OrderbookLevel, ...]
    asks: tuple[OrderbookLevel, ...]
    tick_size: str
    min_order_size_shares: float
    neg_risk: bool
    ts_ns: int

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None


@dataclass(slots=True, frozen=True)
class PlaceOrderResult:
    """Result of place_maker_limit. `status` reflects the CLOB's initial
    response — `LIVE` for resting, `MATCHED` if marketable, etc. The actual
    fill notification comes asynchronously via the user channel or polling."""

    order_id: str
    status: OrderStatus
    placed_ts_ns: int


@dataclass(slots=True, frozen=True)
class CancelResult:
    """Result of cancel(). `cancelled` is True if the CLOB accepted the
    cancel; False if the order was already filled or unknown."""

    order_id: str
    cancelled: bool


# ---------------- Protocol ----------------


class ClobOrderClient(Protocol):
    """Async interface MMB calls into. Implementations: MockClobOrderClient
    (in-memory, deterministic for tests + paper soak) and LiveClobOrderClient
    (real py-clob-client). Same surface so MmRunner can swap them via env."""

    async def get_orderbook(self, token_id: str) -> Orderbook | None: ...
    async def place_maker_limit(
        self,
        *,
        token_id: str,
        price: float,
        size_shares: float,
        tick_size: str,
        neg_risk: bool = False,
    ) -> PlaceOrderResult: ...
    async def cancel(self, order_id: str) -> CancelResult: ...
    async def cancel_all(self) -> int: ...
    async def post_heartbeat(self, heartbeat_id: str = "") -> str: ...


# ---------------- Mock implementation ----------------


@dataclass(slots=True)
class _MockBookState:
    """In-memory state for a single token: book + open MMB orders."""

    book: Orderbook
    mmb_orders: dict[str, PlaceOrderResult] = field(default_factory=dict)


@dataclass(slots=True)
class MockClobOrderClient:
    """Deterministic in-memory CLOB for tests + paper-mode shakedown.

    Books are seeded via `set_orderbook()`. Place semantics: post-only is
    honored (rejected if the order would cross the seeded best_ask). Cancel
    semantics: removes the order from the local state. Heartbeat: tracks
    monotonic id; raises if not called within `heartbeat_timeout_s`.

    Fill simulation: not auto-fill. Use `simulate_fill()` from tests to
    drive specific (order_id, status) transitions. This keeps the mock
    deterministic — no random fill behavior leaks into tests.
    """

    books: dict[str, _MockBookState] = field(default_factory=dict)
    heartbeat_id_counter: int = 0
    heartbeat_last_ts_ns: int = 0
    n_orders_placed: int = 0
    n_orders_cancelled: int = 0
    n_post_only_rejections: int = 0
    raise_on_next_place: type[ClobOrderError] | None = None

    def set_orderbook(self, ob: Orderbook) -> None:
        """Seed or update the orderbook for a token. Existing MMB orders
        for the token remain in place (they sit outside the seeded book)."""
        existing = self.books.get(ob.token_id)
        mmb_orders = existing.mmb_orders if existing else {}
        self.books[ob.token_id] = _MockBookState(book=ob, mmb_orders=mmb_orders)

    async def get_orderbook(self, token_id: str) -> Orderbook | None:
        state = self.books.get(token_id)
        return state.book if state is not None else None

    async def place_maker_limit(
        self,
        *,
        token_id: str,
        price: float,
        size_shares: float,
        tick_size: str,
        neg_risk: bool = False,
    ) -> PlaceOrderResult:
        if self.raise_on_next_place is not None:
            err_cls = self.raise_on_next_place
            self.raise_on_next_place = None
            raise err_cls("mock raised by test")
        state = self.books.get(token_id)
        if state is None:
            raise ClobOrderError(
                f"no orderbook seeded for token_id={token_id}",
                error_code="MOCK_NO_BOOK",
            )
        book = state.book
        if book.best_ask is not None and price >= book.best_ask:
            # post_only enforcement: order would cross the spread.
            self.n_post_only_rejections += 1
            raise PostOnlyRejected(
                f"limit {price} >= best_ask {book.best_ask} would cross spread",
                error_code="INVALID_POST_ONLY_ORDER",
            )
        if size_shares < book.min_order_size_shares:
            raise OrderSizeViolation(
                f"size {size_shares} < min {book.min_order_size_shares}",
                error_code="INVALID_ORDER_MIN_SIZE",
            )
        # Light tick check: price must be representable to the tick precision.
        tick = float(tick_size)
        if tick > 0:
            quanta = round(price / tick)
            if abs(quanta * tick - price) > 1e-9:
                raise OrderTickViolation(
                    f"price {price} does not align to tick {tick_size}",
                    error_code="INVALID_ORDER_MIN_TICK_SIZE",
                )
        order_id = uuid.uuid4().hex
        result = PlaceOrderResult(
            order_id=order_id,
            status=OrderStatus.LIVE,
            placed_ts_ns=time.time_ns(),
        )
        state.mmb_orders[order_id] = result
        self.n_orders_placed += 1
        return result

    async def cancel(self, order_id: str) -> CancelResult:
        for state in self.books.values():
            if order_id in state.mmb_orders:
                del state.mmb_orders[order_id]
                self.n_orders_cancelled += 1
                return CancelResult(order_id=order_id, cancelled=True)
        return CancelResult(order_id=order_id, cancelled=False)

    async def cancel_all(self) -> int:
        count = 0
        for state in self.books.values():
            count += len(state.mmb_orders)
            state.mmb_orders.clear()
        self.n_orders_cancelled += count
        return count

    async def post_heartbeat(self, heartbeat_id: str = "") -> str:
        # Echo back a rotated id so the caller can pass it next time.
        self.heartbeat_id_counter += 1
        self.heartbeat_last_ts_ns = time.time_ns()
        return f"hb-{self.heartbeat_id_counter}"

    # ---------------- test helpers (not part of Protocol) ----------------

    def open_orders_count(self) -> int:
        """Total open MMB orders across all books — used by tests + runner caps."""
        return sum(len(state.mmb_orders) for state in self.books.values())

    def has_open_order(self, order_id: str) -> bool:
        return any(order_id in state.mmb_orders for state in self.books.values())


# ---------------- Live skeleton ----------------


@dataclass(slots=True)
class LiveClobOrderClient:
    """Wraps py-clob-client for real CLOB calls. SKELETON in v1 — interface
    matches MockClobOrderClient so MmRunner can swap via env. Full
    integration testing requires funded Signer + USDC.e allowance +
    live CLOB credentials, all of which land in Session 4-5 of Phase S.

    Construction: pass an already-authenticated `py_clob_client.ClobClient`
    instance. Wallet derivation + L2 credential creation are handled by
    `scripts/derive_creds.py` (Phase 1A); this class only consumes a
    ready-to-trade client.
    """

    inner: Any  # py_clob_client.client.ClobClient — not typed because the
    # package lacks a py.typed marker and Mypy strict cannot resolve it.
    # The mock's surface is the source of truth for the type contract.

    async def get_orderbook(self, token_id: str) -> Orderbook | None:
        raw = await asyncio.to_thread(self.inner.get_order_book, token_id)
        if raw is None:
            return None
        bids = tuple(
            OrderbookLevel(price=float(b["price"]), size_shares=float(b["size"]))
            for b in (raw.get("bids") or [])
        )
        asks = tuple(
            OrderbookLevel(price=float(a["price"]), size_shares=float(a["size"]))
            for a in (raw.get("asks") or [])
        )
        return Orderbook(
            token_id=token_id,
            bids=bids,
            asks=asks,
            tick_size=str(raw.get("tick_size", "0.01")),
            min_order_size_shares=float(raw.get("min_order_size", 5.0)),
            neg_risk=bool(raw.get("neg_risk", False)),
            ts_ns=time.time_ns(),
        )

    async def place_maker_limit(
        self,
        *,
        token_id: str,
        price: float,
        size_shares: float,
        tick_size: str,
        neg_risk: bool = False,
    ) -> PlaceOrderResult:
        # Use 2-step path so post_only=True is explicit on post_order.
        # Imports are local so the module loads in test envs that mock
        # the wrapper out without installing py-clob-client. The package
        # ships no py.typed marker, so mypy strict needs an ignore.
        from py_clob_client.clob_types import OrderArgs, OrderType  # type: ignore[import-untyped]
        from py_clob_client.order_builder.constants import BUY  # type: ignore[import-untyped]

        signed = await asyncio.to_thread(
            self.inner.create_order,
            OrderArgs(token_id=token_id, price=price, size=size_shares, side=BUY),
            options={"tick_size": tick_size, "neg_risk": neg_risk},
        )
        resp = await asyncio.to_thread(
            self.inner.post_order,
            signed,
            OrderType.GTC,
            True,  # post_only — see S.1.1 §Q2
        )
        return _parse_post_order_response(resp)

    async def cancel(self, order_id: str) -> CancelResult:
        resp = await asyncio.to_thread(self.inner.cancel, order_id)
        cancelled = bool(resp) and not (isinstance(resp, dict) and resp.get("error"))
        return CancelResult(order_id=order_id, cancelled=cancelled)

    async def cancel_all(self) -> int:
        resp = await asyncio.to_thread(self.inner.cancel_all)
        if isinstance(resp, dict):
            return int(resp.get("cancelled", 0))
        if isinstance(resp, list):
            return len(resp)
        return 0

    async def post_heartbeat(self, heartbeat_id: str = "") -> str:
        resp = await asyncio.to_thread(self.inner.post_heartbeat, heartbeat_id)
        if isinstance(resp, dict):
            return str(resp.get("heartbeat_id", ""))
        return str(resp)


def _parse_post_order_response(resp: Any) -> PlaceOrderResult:
    """Map py-clob-client's post_order response to our PlaceOrderResult.

    Real response shape: {"success": bool, "errorMsg": "...", "orderID": "...",
    "transactionsHashes": [...], "status": "matched"|"live"|"delayed"|"unmatched"}.
    """
    if not isinstance(resp, dict):
        raise ClobOrderError(f"unexpected post_order response: {resp!r}")
    success = bool(resp.get("success"))
    error_msg = str(resp.get("errorMsg") or "")
    if not success:
        # Classify by error_msg substring (CLOB returns the error code
        # in the message per agent-skills/order-patterns.md §Error Codes).
        code = error_msg.upper()
        if "POST_ONLY" in code or "POST-ONLY" in code:
            raise PostOnlyRejected(error_msg, error_code="INVALID_POST_ONLY_ORDER", raw=resp)
        if "TICK" in code:
            raise OrderTickViolation(error_msg, error_code="INVALID_ORDER_MIN_TICK_SIZE", raw=resp)
        if "MIN_SIZE" in code or "MIN SIZE" in code:
            raise OrderSizeViolation(error_msg, error_code="INVALID_ORDER_MIN_SIZE", raw=resp)
        if "BALANCE" in code or "ALLOWANCE" in code:
            raise InsufficientBalance(
                error_msg, error_code="INVALID_ORDER_NOT_ENOUGH_BALANCE", raw=resp
            )
        raise ClobOrderError(error_msg or "post_order failed", raw=resp)
    order_id = str(resp.get("orderID") or resp.get("order_id") or "")
    status_raw = str(resp.get("status", "live")).lower()
    status_map: dict[str, OrderStatus] = {
        "matched": OrderStatus.MATCHED,
        "live": OrderStatus.LIVE,
        "delayed": OrderStatus.PENDING,
        "unmatched": OrderStatus.LIVE,
    }
    status = status_map.get(status_raw, OrderStatus.PENDING)
    return PlaceOrderResult(
        order_id=order_id,
        status=status,
        placed_ts_ns=time.time_ns(),
    )
