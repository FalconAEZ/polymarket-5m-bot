"""PaperRunner — live-feed fan-in -> Strategy -> ShadowBook -> DecisionLog.

Phase 4 paper-trading runtime per design/paper.md §4.2. Subscribes to a
sequence of live Feed instances (production passes the four real WS feeds
from polymarket_bot._live.feeds; tests pass FakeFeed). Each Record is
decoded into MarketEvents via polymarket_bot.backtest.replay.decode_record
(reused so paper and backtest share the decoder). WindowBoundary events
are synthesised at every 300s rollover. Decisions returned by the
Strategy are queued and tried against ShadowBook on each subsequent
matching BookUpdate within decision.ttl_s. At window close, P&L is
realised against the oracle samples seen at open and close, and a
`settled` line is written to DecisionLog. One pending decision per
window — Phase 3 strategy invariant; relaxed in Phase 8 if needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import httpx

from polymarket_bot._paper.decision_log import DecisionLog
from polymarket_bot._paper.shadow_book import ShadowBook
from polymarket_bot.alerts import Alert, AlertSink, Level, NullAlertSink
from polymarket_bot.backtest.replay import SideResolver, decode_record
from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    Fill,
    MarketEvent,
    OracleUpdate,
    Side,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.feeds.protocols import Feed, Record
from polymarket_bot.gamma_resolver import poll_gamma_for_resolution
from polymarket_bot.resolver import (
    WINDOW_SECONDS,
    active_window_ts,
    actual_resolution,
)
from polymarket_bot.strategies.protocol import Strategy

LOG = logging.getLogger("polymarket_bot._paper.runner")

DEFAULT_QUEUE_SIZE = 1024
# Instant-settle defaults — see design/instant_settlement.md. Gamma poll
# typically resolves within 1-3s of T+300; 30s timeout is the operator-
# configurable upper bound before falling back to Chainlink-local. The bot
# blocks during settle (no decisions to make at the exact moment between
# windows), so a 1-3s block here is acceptable.
DEFAULT_INSTANT_SETTLE_TIMEOUT_S = 30.0
DEFAULT_INSTANT_SETTLE_INTERVAL_S = 1.0


class PaperRunner:
    """Drive a Strategy over live feeds, simulating fills + writing decision_log."""

    def __init__(
        self,
        *,
        feeds: Sequence[Feed],
        strategy: Strategy,
        side_resolver: SideResolver,
        shadow_book: ShadowBook | None = None,
        decision_log: DecisionLog | None = None,
        clock_ns: Callable[[], int] | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        alert_sink: AlertSink | None = None,
        alert_source: str = "bot-staging",
        # Instant-settle: when enabled, _settle_current_window polls
        # Polymarket Gamma for the truth resolution before falling back to
        # the local Chainlink-derived actual_resolution(). Disabled by
        # default to preserve legacy behavior; enabled in production via
        # scripts/run_paper.py reading INSTANT_SETTLE_* env vars.
        # gamma_client is injected for testability (MockTransport in tests);
        # production passes a real httpx.Client with timeouts.
        instant_settle_enabled: bool = False,
        gamma_client: httpx.Client | None = None,
        instant_settle_timeout_s: float = DEFAULT_INSTANT_SETTLE_TIMEOUT_S,
        instant_settle_interval_s: float = DEFAULT_INSTANT_SETTLE_INTERVAL_S,
    ) -> None:
        if not feeds:
            raise ValueError("PaperRunner requires at least one Feed")
        self._feeds: list[Feed] = list(feeds)
        self._strategy = strategy
        self._side_resolver = side_resolver
        self._shadow = shadow_book if shadow_book is not None else ShadowBook()
        self._log = decision_log if decision_log is not None else DecisionLog()
        self._clock_ns: Callable[[], int] = clock_ns if clock_ns is not None else time.time_ns
        self._queue_size = queue_size
        self._stop = asyncio.Event()
        self._dropped = 0
        self._state = _RunState()
        self._alerts: AlertSink = alert_sink if alert_sink is not None else NullAlertSink()
        self._alert_source = alert_source
        self._instant_settle_enabled = instant_settle_enabled
        self._gamma_client = gamma_client
        self._instant_settle_timeout_s = instant_settle_timeout_s
        self._instant_settle_interval_s = instant_settle_interval_s
        self._gamma_timeout_count = 0

    def _alert(self, level: Level, message: str, **fields: str | int | float) -> None:
        try:
            self._alerts.publish(
                Alert(
                    level=level,
                    message=message,
                    ts_ns=self._clock_ns(),
                    source=self._alert_source,
                    fields=fields,
                )
            )
        except Exception:
            # AlertSink contract says publish never raises, but defend anyway —
            # the trading hot path must not break if a sink misbehaves.
            LOG.exception("alert publish raised; suppressed")

    @property
    def dropped_records_total(self) -> int:
        return self._dropped

    def stop(self) -> None:
        self._stop.set()
        for feed in self._feeds:
            feed.stop()

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        external_stop = stop
        queue: asyncio.Queue[Record | None] = asyncio.Queue(self._queue_size)

        async def pump(feed: Feed) -> None:
            try:
                async for record in feed.stream():
                    if self._stop.is_set() or (
                        external_stop is not None and external_stop.is_set()
                    ):
                        break
                    try:
                        queue.put_nowait(record)
                    except asyncio.QueueFull:
                        self._dropped += 1
                        with contextlib.suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                        with contextlib.suppress(asyncio.QueueFull):
                            queue.put_nowait(record)
                        if self._dropped == 1 or self._dropped % 100 == 0:
                            self._alert(
                                Level.WARN,
                                f"paper-runner queue overflow; dropped={self._dropped}",
                                dropped_total=self._dropped,
                            )
            except asyncio.CancelledError:
                raise
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(pump(f), name=f"paper-pump-{f.name}") for f in self._feeds]
        active = len(tasks)
        try:
            while active > 0:
                if external_stop is not None and external_stop.is_set():
                    break
                if self._stop.is_set():
                    break
                record = await queue.get()
                if record is None:
                    active -= 1
                    continue
                await self._on_record(record)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._log.close()

    async def _on_record(self, record: Record) -> None:
        events = decode_record(record, self._side_resolver)
        for event in events:
            await self._on_event(event)

    async def _on_event(self, event: MarketEvent) -> None:
        await self._maybe_emit_boundaries(event.ts_utc_ns)

        if isinstance(event, BookUpdate):
            self._shadow.update(event)
            self._state.observe_book(event)
            self._try_fill_pending(event.ts_utc_ns)
        elif isinstance(event, OracleUpdate):
            self._state.observe_oracle(event)
        elif isinstance(event, SpotTick):
            self._state.observe_spot(event)

        decision = await self._strategy.on_event(event)
        if decision is not None:
            self._on_decision(decision)

    async def _maybe_emit_boundaries(self, now_ts_ns: int) -> None:
        now_s = now_ts_ns // 1_000_000_000
        new_window_ts = active_window_ts(now_s)
        current = self._state.window_ts
        if current is None:
            self._state.start_window(new_window_ts)
            await self._strategy.on_event(
                WindowBoundary(
                    ts_utc_ns=new_window_ts * 1_000_000_000,
                    window_ts=new_window_ts,
                    kind="open",
                )
            )
            return
        if new_window_ts == current:
            return
        # Crossed at least one boundary. Settle the current window first
        # (close), then open the new one. If we skipped multiple windows
        # (no traffic for >5m — shouldn't happen, but guarded), only the
        # most recent close+open pair is emitted; intermediate windows
        # never had decisions to settle.
        await self._strategy.on_event(
            WindowBoundary(
                ts_utc_ns=(current + WINDOW_SECONDS) * 1_000_000_000,
                window_ts=current,
                kind="close",
            )
        )
        await self._settle_current_window()
        self._state.start_window(new_window_ts)
        await self._strategy.on_event(
            WindowBoundary(
                ts_utc_ns=new_window_ts * 1_000_000_000,
                window_ts=new_window_ts,
                kind="open",
            )
        )

    def _on_decision(self, decision: Decision) -> None:
        # Phase-3 strategy invariant: at most one Decision per window.
        # Defensive guard: if a strategy ever fires twice, the second is
        # dropped with a log line.
        if self._state.window_ts is None:
            LOG.warning("decision arrived before window boundary; dropping")
            self._alert(Level.WARN, "decision arrived before window boundary; dropped")
            return
        if self._state.pending_decision is not None or self._state.settled_fill is not None:
            LOG.warning(
                "second decision in window %s; dropping",
                self._state.window_ts,
            )
            self._alert(
                Level.WARN,
                f"second decision in window {self._state.window_ts}; dropped",
                window_ts=self._state.window_ts,
            )
            return
        side = _side_from_rationale(decision.rationale)
        if side is None:
            LOG.warning(
                "decision rationale missing side= marker; dropping (asset=%s)",
                decision.asset_id,
            )
            self._alert(
                Level.WARN,
                "decision rationale missing side= marker; dropped",
                asset_id=decision.asset_id,
            )
            return
        # Try immediate fill against the latest book in the shadow book.
        # Taker path — we're crossing the existing book at decision time.
        fill = self._shadow.attempt_fill(decision, decision.ts_utc_ns, is_taker=True)
        snapshot = self._snapshot_for_log(decision)
        composite = _composite_from_rationale(decision.rationale)
        # OSError guard: per audit 2026-05-10, an uncaught DecisionLog write
        # exception (disk full, NFS unmount, permissions) would propagate up
        # the async stack and kill the entire runner. We catch + alert + drop
        # the decision rather than crash. The bot keeps running; the operator
        # gets a CRITICAL page; the next decision retries the write.
        try:
            decision_id = self._log.record_fired(
                decision=decision,
                side=side,
                window_ts=self._state.window_ts,
                snapshot=snapshot,
                composite_pct=composite,
                fill=fill,
            )
        except OSError as exc:
            LOG.critical("decision_log.record_fired raised OSError: %s", exc)
            self._alert(
                Level.CRITICAL,
                f"decision_log.record_fired raised OSError; decision dropped: {exc}",
                asset_id=decision.asset_id,
                window_ts=self._state.window_ts,
            )
            return
        self._state.record_decision(decision, side, decision_id, fill)

    def _try_fill_pending(self, now_ts_ns: int) -> None:
        pending = self._state.pending_decision
        if pending is None:
            return
        # Maker path — our limit is resting; an incoming seller crosses the
        # spread to hit it. Fill at our limit (price-improvement to maker),
        # NOT at the new (potentially much lower) ask. See fills.py docstring
        # for the simulator-bug postmortem this guards against.
        fill = self._shadow.attempt_fill(pending, now_ts_ns, is_taker=False)
        if fill is None:
            return
        self._state.settled_fill = fill
        self._state.pending_decision = None

    async def _settle_current_window(self) -> None:
        # State-mutation invariant (per audit 2026-05-10): this method
        # awaits via asyncio.to_thread for the gamma poll, so other
        # coroutines CAN run during the await. However, the runner's
        # event-pump is SINGLE-TASKED through `await self._on_record(record)`
        # in `run()` -- no other coroutine on this runner mutates `self._state`.
        # The ONLY mutator paths (`_on_event`, `_maybe_emit_boundaries`,
        # `_on_decision`, `_state.start_window`) all run sequentially under
        # the same `_on_record` await chain. Therefore reading state here
        # while awaiting is safe by construction. If this invariant is
        # ever violated by adding a parallel mutator (e.g., a separate
        # task that touches _state), this method will need explicit
        # synchronization.
        s = self._state
        if s.window_ts is None or s.decision_id is None:
            return
        resolution: Side | None = None
        resolution_source: str | None = None

        # Instant-settle path — try Polymarket Gamma first if enabled.
        # Per design/instant_settlement.md: 30x faster than the Chainlink-
        # local fallback (60s -> 1-3s typical). Falls through to Chainlink
        # if Gamma times out or instant-settle is disabled.
        #
        # CRITICAL: poll_gamma_for_resolution is synchronous (sleep+http).
        # It MUST be wrapped in asyncio.to_thread so the runner's event
        # loop keeps processing incoming market events for the NEXT window
        # while we wait for Gamma. Without this, the bot freezes for up to
        # ``timeout_s`` seconds at every window boundary.
        if self._instant_settle_enabled and self._gamma_client is not None:
            truth = await asyncio.to_thread(
                poll_gamma_for_resolution,
                s.window_ts,
                client=self._gamma_client,
                timeout_s=self._instant_settle_timeout_s,
                interval_s=self._instant_settle_interval_s,
            )
            if truth in ("UP", "DOWN"):
                resolution = truth
                resolution_source = "polymarket"
            else:
                # Gamma didn't resolve in time. Increment counter; emit a
                # WARN alert every Nth failure so the operator notices a
                # degraded state without spamming on every single timeout.
                self._gamma_timeout_count += 1
                if self._gamma_timeout_count == 1 or self._gamma_timeout_count % 10 == 0:
                    LOG.warning(
                        "instant-settle gamma timeout #%d for window %s; "
                        "falling back to chainlink-local",
                        self._gamma_timeout_count,
                        s.window_ts,
                    )
                    self._alert(
                        Level.WARN,
                        f"instant-settle gamma timeout x{self._gamma_timeout_count}; "
                        "falling back to chainlink-local",
                        gamma_timeout_total=self._gamma_timeout_count,
                        window_ts=s.window_ts,
                    )

        # Chainlink-local fallback — also the legacy behavior when
        # instant-settle is disabled.
        if resolution is None and s.open_oracle is not None and s.close_oracle is not None:
            resolution = actual_resolution(s.window_ts, s.open_oracle, s.close_oracle)
            # Mark the source so dashboards / postmortems know this was
            # the fallback, not the primary truth path. Only set when the
            # instant-settle path was actually attempted -- otherwise leave
            # source=None for backward compat with legacy callers.
            if self._instant_settle_enabled:
                resolution_source = "chainlink-local-fallback"

        fill = s.settled_fill
        pnl = 0.0
        if fill is not None and resolution is not None and s.side is not None:
            pnl = _realised_pnl(fill, resolution == s.side)
        # OSError guard: same rationale as _on_decision (audit 2026-05-10).
        # The settled record can be regenerated post-hoc from the fired
        # record's data via gamma_resolver, so dropping a settle write on
        # OSError loses less than dropping a fired write. Still alerted.
        try:
            self._log.record_settled(
                decision_id=s.decision_id,
                window_ts=s.window_ts,
                settled_ts_ns=self._clock_ns(),
                open_oracle=s.open_oracle,
                close_oracle=s.close_oracle,
                resolution=resolution,
                fill_at_settle=fill,
                pnl_usd=pnl,
                resolution_source=resolution_source,
            )
        except OSError as exc:
            LOG.critical("decision_log.record_settled raised OSError: %s", exc)
            self._alert(
                Level.CRITICAL,
                f"decision_log.record_settled raised OSError; settle dropped: {exc}",
                decision_id=s.decision_id,
                window_ts=s.window_ts,
            )

    def _snapshot_for_log(self, decision: Decision) -> dict[str, float | None]:
        s = self._state
        book = self._shadow.latest(decision.asset_id)
        return {
            "spot_now": s.last_spot,
            "window_open_spot": s.window_open_spot,
            "oracle_last": s.last_oracle,
            "open_oracle": s.open_oracle,
            "best_bid": book.best_bid if book is not None else None,
            "best_ask": book.best_ask if book is not None else None,
            "ask_size_top": book.ask_size_top if book is not None else None,
        }


@dataclass
class _RunState:
    """Per-window scratch state for the runner. Not part of the public API."""

    window_ts: int | None = None
    open_oracle: float | None = None
    close_oracle: float | None = None
    last_oracle: float | None = None
    last_spot: float | None = None
    window_open_spot: float | None = None
    pending_decision: Decision | None = None
    decision_id: str | None = None
    side: Side | None = None
    settled_fill: Fill | None = None

    def start_window(self, window_ts: int) -> None:
        # Carry last_oracle / last_spot forward as the open values; clear
        # decision state.
        self.window_ts = window_ts
        self.open_oracle = self.last_oracle
        self.close_oracle = None
        self.window_open_spot = self.last_spot
        self.pending_decision = None
        self.decision_id = None
        self.side = None
        self.settled_fill = None

    def observe_oracle(self, event: OracleUpdate) -> None:
        self.last_oracle = event.price
        self.close_oracle = event.price
        if self.window_ts is not None and self.open_oracle is None:
            self.open_oracle = event.price

    def observe_book(self, event: BookUpdate) -> None:
        # Books don't carry prices we use for resolution; tracked here only
        # so future logic can latch top-of-book at window-open if needed.
        return

    def observe_spot(self, event: SpotTick) -> None:
        self.last_spot = event.price
        if self.window_open_spot is None and self.window_ts is not None:
            self.window_open_spot = event.price

    def record_decision(
        self,
        decision: Decision,
        side: Side,
        decision_id: str,
        immediate_fill: Fill | None,
    ) -> None:
        self.side = side
        self.decision_id = decision_id
        if immediate_fill is not None:
            self.settled_fill = immediate_fill
            self.pending_decision = None
        else:
            self.pending_decision = decision


def _side_from_rationale(rationale: str) -> Side | None:
    if "side=UP" in rationale:
        return "UP"
    if "side=DOWN" in rationale:
        return "DOWN"
    return None


def _composite_from_rationale(rationale: str) -> float | None:
    """Parse the leading 'composite=<float>pct' marker emitted by DeterministicStrategy."""
    marker = "composite="
    idx = rationale.find(marker)
    if idx < 0:
        return None
    tail = rationale[idx + len(marker) :]
    end = 0
    while end < len(tail) and (tail[end].isdigit() or tail[end] in "+-.eE"):
        end += 1
    if end == 0:
        return None
    try:
        return float(tail[:end])
    except ValueError:
        return None


def _realised_pnl(fill: Fill, won: bool) -> float:
    """Mirrors backtest.fills.realised_pnl_usd. Inlined so paper has no
    backwards reach into backtest internals beyond decode_record + types."""
    cost = fill.size_filled * fill.price_filled
    payout = fill.size_filled if won else 0.0
    return payout - cost - fill.fee_usd
