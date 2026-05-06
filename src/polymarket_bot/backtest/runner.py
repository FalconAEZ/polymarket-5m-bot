"""BacktestRunner — single-pass orchestrator: replay x strategy x fills x P&L.

Wires a ReplayEngine through a Strategy, attempts to fill each Decision
against the next compatible BookUpdate inside its TTL, and computes per-
window P&L using actual_resolution() against the oracle samples at the
window's open and close. Returns a list[WindowResult] suitable for
Metrics.aggregate(). The walk-forward harness in walk_forward.py wraps
multiple BacktestRunner passes for the Phase 3.3 A/B comparison.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from polymarket_bot.backtest.fills import FillSimulator, realised_pnl_usd
from polymarket_bot.backtest.replay import ReplayEngine
from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    Fill,
    OracleUpdate,
    Side,
    WindowBoundary,
)
from polymarket_bot.resolver import active_window_ts, actual_resolution
from polymarket_bot.strategies.protocol import Strategy


@dataclass(frozen=True, slots=True)
class WindowResult:
    """Outcome of one 5-min window in a backtest pass."""

    window_ts: int
    fired: bool
    side: Side | None
    fill: Fill | None
    resolution: Side | None
    pnl_usd: float
    rationale: str


class BacktestRunner:
    """Drive a Strategy over a ReplayEngine and emit per-window results.

    Decision lifecycle inside a window:
      1. Strategy.on_event yields a Decision.
      2. Runner queues it; on the next BookUpdate matching its asset_id
         within ttl_s seconds, FillSimulator attempts a fill.
      3. At window close (next WindowBoundary or end of stream), runner
         settles: resolution from actual_resolution(open_oracle,
         close_oracle); P&L from realised_pnl_usd(fill, won).

    Strategies that fire late (TTL extends past window close) get a
    no-fill outcome. Strategies that don't fire produce fired=False results.
    """

    def __init__(self, replay: ReplayEngine, simulator: FillSimulator | None = None) -> None:
        self._replay = replay
        self._sim = simulator if simulator is not None else FillSimulator()

    async def run(self, strategy: Strategy) -> list[WindowResult]:
        results: list[WindowResult] = []
        state = _RunState()
        async for event in self._replay.stream():
            if isinstance(event, WindowBoundary) and event.kind == "open":
                self._close_window(state, results)
                state.start_window(event.window_ts, event.ts_utc_ns)
            if isinstance(event, OracleUpdate):
                state.observe_oracle(event)
            if isinstance(event, BookUpdate):
                state.observe_book(event)
                self._try_fill(state)
            decision = await strategy.on_event(event)
            if decision is not None:
                state.record_decision(decision)
        self._close_window(state, results)
        return results

    def _try_fill(self, state: _RunState) -> None:
        if state.pending_decision is None:
            return
        if state.last_book is None:
            return
        # Only attempt against books that arrived within the decision's TTL.
        elapsed_s = (state.last_book.ts_utc_ns - state.pending_decision.ts_utc_ns) / 1e9
        if elapsed_s < 0 or elapsed_s > state.pending_decision.ttl_s:
            return
        fill = self._sim.attempt_fill(state.pending_decision, state.last_book)
        if fill is not None:
            state.fill = fill
            state.pending_decision = None  # one-shot; do not re-attempt after fill

    def _close_window(self, state: _RunState, results: list[WindowResult]) -> None:
        if state.window_ts is None:
            return
        # Snapshot the close oracle reading *before* we settle: the most
        # recent oracle update we've seen is the close-time price (true
        # resolution would be exactly at T+300, but for the paper backtest
        # the latest pre-boundary value is within the heartbeat).
        state.close_oracle = state.last_oracle
        rationale = ""
        d_for_side = state.decision_after_fill or state.pending_decision
        side = _side_from_rationale(d_for_side.rationale) if d_for_side is not None else None
        if d_for_side is not None:
            rationale = d_for_side.rationale

        resolution: Side | None = None
        pnl = 0.0
        if state.open_oracle is not None and state.close_oracle is not None:
            resolution = actual_resolution(state.window_ts, state.open_oracle, state.close_oracle)
        if state.fill is not None and resolution is not None and side is not None:
            won = resolution == side
            pnl = realised_pnl_usd(state.fill, won)
        results.append(
            WindowResult(
                window_ts=state.window_ts,
                fired=state.decision_after_fill is not None or state.pending_decision is not None,
                side=side,
                fill=state.fill,
                resolution=resolution,
                pnl_usd=pnl,
                rationale=rationale,
            )
        )


@dataclass
class _RunState:
    """Per-window runner scratch; not part of the public API."""

    window_ts: int | None = None
    open_oracle: float | None = None
    close_oracle: float | None = None
    last_oracle: float | None = None
    last_book: BookUpdate | None = None
    pending_decision: Decision | None = None
    decision_after_fill: Decision | None = None
    fill: Fill | None = None

    def start_window(self, window_ts: int, ts_utc_ns: int) -> None:
        self.window_ts = window_ts
        self.open_oracle = self.last_oracle
        self.close_oracle = None
        self.pending_decision = None
        self.decision_after_fill = None
        self.fill = None

    def observe_oracle(self, event: OracleUpdate) -> None:
        self.last_oracle = event.price
        if self.window_ts is not None and self.open_oracle is None:
            self.open_oracle = event.price

    def observe_book(self, event: BookUpdate) -> None:
        self.last_book = event

    def record_decision(self, decision: Decision) -> None:
        if self.window_ts is None:
            return
        if active_window_ts(decision.ts_utc_ns // 1_000_000_000) != self.window_ts:
            return
        if self.fill is not None:
            return  # already filled; ignore late decisions
        if self.pending_decision is None:
            self.pending_decision = decision
        # Track the "winning" decision for side reporting even after fill.
        self.decision_after_fill = decision


def _side_from_rationale(rationale: str) -> Side | None:
    """Recover side from the rationale string (the runner doesn't have a
    typed side field on Decision because Decision.side is hardcoded BUY)."""
    if "side=UP" in rationale:
        return "UP"
    if "side=DOWN" in rationale:
        return "DOWN"
    return None


def aggregate_metrics(results: Sequence[WindowResult]) -> dict[str, Any]:
    """Compute basic metrics across a list of WindowResults.

    Keys: n_windows, n_fired, n_filled, n_won, win_rate, total_pnl_usd,
    avg_pnl_usd. win_rate is computed over filled trades only.
    """
    n = len(results)
    fired = [r for r in results if r.fired]
    filled = [r for r in results if r.fill is not None]
    won = [r for r in filled if r.side == r.resolution and r.resolution is not None]
    total_pnl = sum(r.pnl_usd for r in results)
    return {
        "n_windows": n,
        "n_fired": len(fired),
        "n_filled": len(filled),
        "n_won": len(won),
        "win_rate": (len(won) / len(filled)) if filled else 0.0,
        "total_pnl_usd": total_pnl,
        "avg_pnl_usd_per_filled": (total_pnl / len(filled)) if filled else 0.0,
    }
