"""Strategy protocol — `async def on_event(event) -> Decision | None`.

Pinned by design/backtest.md §3. Async signature so LLM strategies in
Phase 3.2 fit the same interface. reset() clears state at the start of
each walk-forward fold so a stateful strategy doesn't leak training
information into the test fold.
"""

from __future__ import annotations

from typing import Protocol

from polymarket_bot.backtest.types import Decision, MarketEvent


class Strategy(Protocol):
    """Every concrete strategy implements this. See design/backtest.md §3."""

    name: str

    async def on_event(self, event: MarketEvent) -> Decision | None: ...

    def reset(self) -> None: ...
