"""CLI entry — `uv run python -u scripts/run_paper.py` starts paper-mode trading.

Wires the four real WS feeds (Binance, Coinbase, Chainlink oracle, Polymarket)
into a PaperRunner driving the deterministic Strategy. ShadowBook simulates
fills against the latest book per asset_id; DecisionLog writes JSONL to
state/decisions/<UTC-date>.jsonl. A background warmer task keeps the
TokenSideIndex pre-resolved ~1 hour ahead so the SideResolver answers
synchronously when polymarket BookUpdates flow through. SIGTERM/SIGINT
trigger graceful shutdown — drain queue, close files. PID written to
state/paper.pid by the launcher (runbooks/paper-monitor.md), not by this
script.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polymarket_bot._live.feeds.oracle import OracleFeed  # noqa: E402
from polymarket_bot._live.feeds.polymarket import GammaClient, PolymarketFeed  # noqa: E402
from polymarket_bot._live.feeds.spot_binance import BinanceTradeFeed  # noqa: E402
from polymarket_bot._live.feeds.spot_coinbase import CoinbaseMatchFeed  # noqa: E402
from polymarket_bot._paper.decision_log import DecisionLog  # noqa: E402
from polymarket_bot._paper.runner import PaperRunner  # noqa: E402
from polymarket_bot._paper.shadow_book import ShadowBook  # noqa: E402
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.feeds.protocols import Feed  # noqa: E402
from polymarket_bot.resolver import WINDOW_SECONDS, active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import (  # noqa: E402
    DEFAULT_THRESHOLD_PCT,
    DeterministicStrategy,
)

LOG = logging.getLogger("polymarket_bot.scripts.run_paper")
WARM_LOOKAHEAD_WINDOWS = 12  # ~1 hour of windows pre-resolved
WARMER_INTERVAL_S = 60.0


def _configure_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(log_path),
    ]
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _default_feeds() -> list[Feed]:
    return [
        BinanceTradeFeed(),
        CoinbaseMatchFeed(),
        OracleFeed(),
        PolymarketFeed(),
    ]


async def _warmer(
    index: TokenSideIndex, *, stop: asyncio.Event, lookahead: int = WARM_LOOKAHEAD_WINDOWS
) -> None:
    """Periodically warm the side index for the next `lookahead` windows.

    Runs every WARMER_INTERVAL_S until `stop` is set. Each tick computes
    the current window from wall-clock time and warms current + lookahead
    consecutive windows (TokenSideIndex skips already-warmed windows
    internally). Gamma misses are logged but never crash the runner.
    """
    LOG.info("warmer started; lookahead=%d windows", lookahead)
    while not stop.is_set():
        try:
            current = active_window_ts(int(time.time()))
            windows = [current + i * WINDOW_SECONDS for i in range(lookahead + 1)]
            n_new = await index.warm(windows)
            if n_new > 0:
                LOG.info(
                    "warmer: fetched %d new windows; total tokens=%d",
                    n_new,
                    index.n_known_tokens,
                )
        except Exception:
            LOG.exception("warmer iteration failed; retrying after interval")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=WARMER_INTERVAL_S)


async def main() -> int:
    log_path = Path("state/paper.log")
    _configure_logging(log_path)
    LOG.info("paper-mode runtime starting")

    gamma = GammaClient()
    side_index = TokenSideIndex(
        fetch_fn=gamma.fetch_event,
        cache_path=Path("state/token_side_index.json"),
    )
    # Initial warm so the very first BookUpdate has a side mapping ready.
    current = active_window_ts(int(time.time()))
    initial_windows = [current + i * WINDOW_SECONDS for i in range(WARM_LOOKAHEAD_WINDOWS + 1)]
    n = await side_index.warm(initial_windows)
    LOG.info(
        "initial warm: %d new windows; %d tokens mapped overall",
        n,
        side_index.n_known_tokens,
    )

    feeds = _default_feeds()
    strategy = DeterministicStrategy(threshold_pct=DEFAULT_THRESHOLD_PCT)
    decision_log = DecisionLog(root="state/decisions")
    runner = PaperRunner(
        feeds=feeds,
        strategy=strategy,
        side_resolver=side_index,
        shadow_book=ShadowBook(),
        decision_log=decision_log,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    warmer_task = asyncio.create_task(_warmer(side_index, stop=stop_event), name="warmer")
    runner_task = asyncio.create_task(runner.run(stop=stop_event), name="paper-runner")

    LOG.info("paper-mode runtime up; waiting for SIGTERM/SIGINT")
    await stop_event.wait()
    LOG.info("shutdown signal received")
    runner.stop()
    await asyncio.gather(runner_task, warmer_task, return_exceptions=True)
    LOG.info("shutdown complete; dropped_records=%d", runner.dropped_records_total)
    return 0


def cli() -> None:
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
