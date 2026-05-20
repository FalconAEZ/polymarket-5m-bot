"""MmRunner — coordinates MarketMakerStrategy + ClobOrderClient + decision log.

Phase S Session 3 deliverable. Per design/S.1-market-maker-bot.md §2 and
the Session 3 prompt: a stateful coordinator that takes book-update,
fill, and resolution events and threads them through:

   strategy.on_book_update -> [PlaceOrder / CancelOrder actions]
                            -> client.place_maker_limit / client.cancel
                            -> mm_decision_log JSONL write

   strategy.on_fill         -> inventory tracker mutation
                            -> mm_decision_log JSONL write

   strategy.on_resolution   -> realized PnL + bankroll update
                            -> mm_decision_log JSONL write

The runner does NOT own the asyncio event loop. The script
(`scripts/run_mm_paper.py` for paper, future `scripts/run_mm_live.py`
for live) is responsible for: subscribing to a book-update source
(synthetic in paper, WebSocket in live), invoking the runner's coroutines
in order, running the heartbeat task in parallel, and polling the halt
sentinel.

Hard requirements honored:
  - PostOnlyRejected → soft skip + log (drop the level, don't retry).
  - In-flight fills count toward inventory caps via strategy.on_fill(LIVE).
  - On halt sentinel detected: drain open orders + stop accepting actions.
  - Bankroll replay: read prior days' JSONL on startup to rebuild
    `MarketMakerStrategy.bankroll_getter` state if requested.

The runner stays asyncio-friendly (every CLOB call is awaited) but its
public surface is simple methods + a stop() flag, not an internal loop.
The script wires the loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from polymarket_bot._live.clob_orders import (
    ClobOrderClient,
    ClobOrderError,
    PostOnlyRejected,
)
from polymarket_bot.strategies.market_maker import (
    CancelOrder,
    LadderAction,
    MarketMakerStrategy,
    OpenOrder,
    OrderStatus,
    PlaceOrder,
    Side,
    WindowPnl,
)

AlertCallback = Callable[[dict[str, Any]], Awaitable[None]]
"""Async callback invoked when MmRunner emits an MMB alert payload.
Production wires this to the alerter Redis queue; tests pass a mock
that records payloads for assertion. None disables alerting entirely."""

MetadataGetter = Callable[[], dict[str, Any]]
"""Edge 4 prep (audit §2 Edge 4): synchronous callback returning a dict
of contextual metadata to merge into every decision-log record. Typical
fields: `mmd_label`, `mmd_conf`, `regime`. None = no metadata appended
(decision-log records contain only the kind-specific fields)."""

LOG = logging.getLogger("polymarket_bot._paper.mm_runner")

DEFAULT_DECISION_LOG_ROOT: Path = Path("state/mm-decisions")


# ---------------- decision log ----------------


@dataclass(slots=True)
class MmDecisionLog:
    """Append-only JSONL writer for MMB events.

    One file per UTC date at `<root>/<YYYY-MM-DD>.jsonl`. Mirrors the
    inode-stability defense from `_paper/decision_log.py`: handle is
    held open, flushed after every write, atomic line semantics. Schema
    is by event kind:

      kind=place_attempt    — strategy emitted PlaceOrder + we tried
      kind=place_succeeded  — CLOB accepted, order_id returned
      kind=place_rejected   — soft skip (post_only collision) — recorded
                              for diagnostics but no further action
      kind=cancel_attempt   — strategy emitted CancelOrder
      kind=cancel_result    — CLOB confirmed cancel
      kind=fill             — fill notification (in-flight or confirmed)
      kind=resolve          — window resolution: realized PnL
    """

    root: Path = field(default_factory=lambda: DEFAULT_DECISION_LOG_ROOT)
    _handles: dict[str, Any] = field(default_factory=dict, init=False)
    _closed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, payload: dict[str, Any], *, ts_ns: int | None = None) -> None:
        if self._closed:
            raise RuntimeError("MmDecisionLog is closed")
        ts = ts_ns if ts_ns is not None else time.time_ns()
        line: dict[str, Any] = {
            "kind": kind,
            "ts_ns": ts,
            **payload,
        }
        self._write(ts, line)

    def close(self) -> None:
        for handle in self._handles.values():
            handle.flush()
            handle.close()
        self._handles.clear()
        self._closed = True

    def _write(self, ts_ns: int, line: dict[str, Any]) -> None:
        date_key = datetime.fromtimestamp(ts_ns / 1_000_000_000, tz=UTC).strftime("%Y-%m-%d")
        handle = self._handles.get(date_key)
        if handle is None:
            path = self.root / f"{date_key}.jsonl"
            handle = path.open("a", encoding="utf-8")
            self._handles[date_key] = handle
        handle.write(json.dumps(line, separators=(",", ":")) + "\n")
        handle.flush()


def read_mm_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield records from an MMB decision-log JSONL file."""
    with path.open("r", encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()
            if not stripped:
                continue
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                yield obj


def replay_bankroll(
    root: Path,
    *,
    starting_bankroll: float = 1000.0,
    lookback_days: int = 30,
) -> float:
    """Reconstruct current bankroll by summing realized PnL from prior
    resolve records. Used by MmRunner.start() so a restart picks up
    where the prior run left off.
    """
    if not root.exists():
        return starting_bankroll
    bankroll = starting_bankroll
    files = sorted(root.glob("*.jsonl"))[-lookback_days:]
    for path in files:
        for rec in read_mm_jsonl(path):
            if rec.get("kind") == "resolve":
                bankroll += float(rec.get("realized_pnl_usd", 0.0))
    return bankroll


# ---------------- runner ----------------


@dataclass(slots=True)
class MmRunner:
    """Orchestrates one MMB tick: book-update → strategy → client → log.

    The runner is NOT thread-safe; its public methods must be called
    from a single asyncio event loop. The script driving the runner
    owns the loop + the schedule of book updates + the heartbeat task.

    `dry_run`: when True (paper-mode default) the runner still calls
    `client.place_maker_limit` and `client.cancel`, but the client
    is expected to be a `MockClobOrderClient`. Set False only when
    swapping in `LiveClobOrderClient` + funded Signer + USDC.e allowance.
    """

    strategy: MarketMakerStrategy
    client: ClobOrderClient
    decision_log: MmDecisionLog
    halt_sentinel_path: Path = field(default_factory=lambda: Path("state/halt.sentinel"))
    dry_run: bool = True
    alert_callback: AlertCallback | None = None
    metadata_getter: MetadataGetter | None = None
    _halt_engaged: bool = field(default=False, init=False)
    _sentinel_written: bool = field(default=False, init=False)

    def _record(self, kind: str, payload: dict[str, Any], *, ts_ns: int | None = None) -> None:
        """Edge 4 prep wrapper around decision_log.record — merges metadata_getter
        output into the payload so Day-7 audit can group fills by MMD label,
        regime, etc. without code changes at each callsite."""
        merged: dict[str, Any] = dict(payload)
        if self.metadata_getter is not None:
            try:
                merged.update(self.metadata_getter())
            except Exception:
                LOG.exception("metadata_getter raised; logging without metadata")
        self.decision_log.record(kind, merged, ts_ns=ts_ns)

    def halt_sentinel_present(self) -> bool:
        """Returns True if the halt sentinel exists on disk OR if the
        strategy's RiskGate has self-halted (e.g., daily loss cap)."""
        return self.halt_sentinel_path.exists() or self.strategy.gate.halted

    async def on_book_update(
        self,
        *,
        market_id: str,
        token_id: str,
        side: Side,
        best_ask: float,
        tick_size: str,
        min_order_size_shares: float,
        seconds_remaining: float,
    ) -> list[LadderAction]:
        """Process one book tick. Returns the actions taken (place +
        cancel) for caller observability + testing."""
        if self.halt_sentinel_present():
            self._halt_engaged = True
            return []

        actions = self.strategy.on_book_update(
            market_id=market_id,
            token_id=token_id,
            side=side,
            best_ask=best_ask,
            tick_size=tick_size,
            min_order_size_shares=min_order_size_shares,
            seconds_remaining=seconds_remaining,
        )
        executed: list[LadderAction] = []
        for action in actions:
            if isinstance(action, CancelOrder):
                ok = await self._do_cancel(action.order_id)
                if ok:
                    executed.append(action)
                continue
            if isinstance(action, PlaceOrder):
                placed = await self._do_place(action)
                if placed:
                    executed.append(action)
        return executed

    async def _do_place(self, action: PlaceOrder) -> bool:
        lvl = action.level
        try:
            result = await self.client.place_maker_limit(
                token_id=lvl.token_id,
                price=lvl.price,
                size_shares=lvl.size_shares,
                tick_size="0.01",  # market-level tick passed in; default 0.01 for BTC 5m
                neg_risk=False,
            )
        except PostOnlyRejected as exc:
            self._record(
                "place_rejected",
                {
                    "market_id": lvl.market_id,
                    "token_id": lvl.token_id,
                    "side": lvl.side.value,
                    "price": lvl.price,
                    "size_usd": lvl.size_usd,
                    "size_shares": lvl.size_shares,
                    "reason": "post_only_rejected",
                    "error_code": exc.error_code,
                },
            )
            LOG.info("post-only rejected: %s @ %.4f", lvl.token_id, lvl.price)
            return False
        except ClobOrderError as exc:
            self._record(
                "place_failed",
                {
                    "market_id": lvl.market_id,
                    "token_id": lvl.token_id,
                    "side": lvl.side.value,
                    "price": lvl.price,
                    "size_usd": lvl.size_usd,
                    "size_shares": lvl.size_shares,
                    "error": str(exc),
                    "error_code": exc.error_code,
                },
            )
            LOG.warning("place_maker_limit raised %s: %s", type(exc).__name__, exc)
            return False

        self.strategy.open_orders[result.order_id] = OpenOrder(
            order_id=result.order_id,
            level=lvl,
            status=result.status,
            placed_ts_ns=result.placed_ts_ns,
        )
        # Count as in-flight inventory immediately (provisional).
        self.strategy.on_fill(
            market_id=lvl.market_id,
            side=lvl.side,
            size_usd=lvl.size_usd,
            size_shares=lvl.size_shares,
            status=OrderStatus.LIVE,
        )
        self._record(
            "place_succeeded",
            {
                "market_id": lvl.market_id,
                "token_id": lvl.token_id,
                "side": lvl.side.value,
                "price": lvl.price,
                "size_usd": lvl.size_usd,
                "size_shares": lvl.size_shares,
                "order_id": result.order_id,
                "status": result.status.value,
            },
        )
        return True

    async def _do_cancel(self, order_id: str) -> bool:
        result = await self.client.cancel(order_id)
        if not result.cancelled:
            LOG.debug("cancel returned not-cancelled for order_id=%s", order_id)
            return False
        order = self.strategy.open_orders.pop(order_id, None)
        if order is not None:
            self.strategy.on_fill(
                market_id=order.level.market_id,
                side=order.level.side,
                size_usd=order.level.size_usd,
                size_shares=order.level.size_shares,
                status=OrderStatus.CANCELLED,
            )
        self._record(
            "cancel_result",
            {
                "order_id": order_id,
                "cancelled": True,
                "market_id": order.level.market_id if order else None,
                "side": order.level.side.value if order else None,
            },
        )
        return True

    async def on_fill_confirmed(
        self,
        *,
        order_id: str,
        fill_price: float,
        fill_size_shares: float,
        ts_ns: int | None = None,
    ) -> None:
        """External confirmation that an in-flight order's fill has
        reached CONFIRMED terminal state. Caller pops it from open_orders
        + drains in-flight into filled."""
        order = self.strategy.open_orders.pop(order_id, None)
        if order is None:
            LOG.warning("on_fill_confirmed: unknown order_id=%s", order_id)
            return
        self.strategy.on_fill(
            market_id=order.level.market_id,
            side=order.level.side,
            size_usd=fill_price * fill_size_shares,
            size_shares=fill_size_shares,
            status=OrderStatus.CONFIRMED,
        )
        self._record(
            "fill",
            {
                "order_id": order_id,
                "market_id": order.level.market_id,
                "side": order.level.side.value,
                "fill_price": fill_price,
                "fill_size_shares": fill_size_shares,
                "status": OrderStatus.CONFIRMED.value,
            },
            ts_ns=ts_ns,
        )

    async def on_resolution(
        self,
        *,
        market_id: str,
        winning_side: Side,
        ts_ns: int | None = None,
    ) -> WindowPnl:
        result = self.strategy.on_resolution(market_id=market_id, winning_side=winning_side)
        self._record(
            "resolve",
            {
                "market_id": market_id,
                "winning_side": winning_side.value,
                "realized_pnl_usd": result.realized_pnl_usd,
                "gross_traded_usd": result.gross_traded_usd,
            },
            ts_ns=ts_ns,
        )
        # If the gate self-halted on this resolution (daily loss cap), write
        # the on-disk sentinel + push a CRITICAL alert. The in-process gate
        # state is invisible to other processes (alerter, dashboard) without
        # the sentinel file.
        if self.strategy.gate.halted and not self._sentinel_written:
            await self._engage_halt_from_gate()
        return result

    async def _engage_halt_from_gate(self) -> None:
        """Bridge in-process RiskGate halt to filesystem sentinel + alerter."""
        from polymarket_bot._live.alerter.halt import write_halt_sentinel
        from polymarket_bot._live.mm_alerts import mm_daily_loss_tripped_alert

        reason = "mm_daily_loss_cap"
        await asyncio.to_thread(
            write_halt_sentinel,
            reason,
            time.time_ns(),
            path=self.halt_sentinel_path,
        )
        self._sentinel_written = True
        LOG.error(
            "MMB gate halted on daily loss; sentinel written at %s",
            self.halt_sentinel_path,
        )
        if self.alert_callback is not None:
            payload = mm_daily_loss_tripped_alert(
                realized_pnl_usd=self.strategy.gate.today_realized_pnl_usd,
                cap_usd=self.strategy.gate.caps.max_daily_loss_usd,
            )
            try:
                await self.alert_callback(payload)
            except Exception:
                LOG.exception("alert_callback raised during daily-loss halt")

    async def drain(self) -> int:
        """Cancel ALL open orders. Called at shutdown OR when halt
        sentinel detected. Returns count cancelled."""
        n = await self.client.cancel_all()
        cancelled_ids = list(self.strategy.open_orders.keys())
        for order_id in cancelled_ids:
            order = self.strategy.open_orders.pop(order_id, None)
            if order is None:
                continue
            self.strategy.on_fill(
                market_id=order.level.market_id,
                side=order.level.side,
                size_usd=order.level.size_usd,
                size_shares=order.level.size_shares,
                status=OrderStatus.CANCELLED,
            )
        self._record(
            "drain",
            {"n_cancelled": n, "n_local_open_dropped": len(cancelled_ids)},
        )
        return n


def new_decision_id() -> str:
    """Convenience: produce a uuid4 hex (compat with the directional bot's
    decision-log id shape)."""
    return uuid.uuid4().hex
