"""MMB paper-mode entry script — drives MmRunner against a Mock CLOB.

Phase S Session 3 deliverable. Smoke-tests the strategy → runner → client
plumbing end-to-end without spending real money. Generates a synthetic
book-update stream + window resolutions so we can prove decision log writes,
heartbeat task wiring, and halt sentinel detection.

Env config:
  MM_STARTING_BANKROLL    — paper bankroll, default 1000
  MM_DURATION_S           — duration of paper run, default 60
  MM_TICK_INTERVAL_S      — synthetic book-update cadence, default 1.0
  MM_DECISION_LOG_ROOT    — path for state/mm-decisions/ jsonl, default
                            state/mm-decisions
  MM_HALT_SENTINEL_PATH   — path for halt sentinel, default state/halt.sentinel
  MM_KILL_SWITCH          — if set to "true", drain immediately and exit

NOT included: live CLOB swap, USDC.e allowance check, websocket feed —
those land in S.4+ when LiveClobOrderClient gets its empirical probes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# After sys.path manipulation.
from polymarket_bot._live.clob_orders import (  # noqa: E402
    MockClobOrderClient,
    Orderbook,
    OrderbookLevel,
)
from polymarket_bot._live.mm_heartbeat import (  # noqa: E402
    mm_heartbeat_loop,
    write_halt_sentinel_async,
)
from polymarket_bot._paper.mm_runner import (  # noqa: E402
    MmDecisionLog,
    MmRunner,
    replay_bankroll,
)
from polymarket_bot.strategies.j7_priors import J7Priors  # noqa: E402
from polymarket_bot.strategies.market_maker import (  # noqa: E402
    MarketMakerStrategy,
    RiskCaps,
    RiskGate,
    Side,
)

LOG = logging.getLogger("polymarket_bot.scripts.run_mm_paper")


# Synthetic markets for paper-mode shakedown — 3 markets, 2 tokens each.
@dataclass(slots=True, frozen=True)
class SyntheticMarket:
    market_id: str
    token_up: str
    token_dn: str
    best_ask_up_start: float
    best_ask_dn_start: float


SYNTHETIC_MARKETS: tuple[SyntheticMarket, ...] = (
    SyntheticMarket("mock_m1", "mock_t1_up", "mock_t1_dn", 0.42, 0.62),
    SyntheticMarket("mock_m2", "mock_t2_up", "mock_t2_dn", 0.55, 0.48),
    SyntheticMarket("mock_m3", "mock_t3_up", "mock_t3_dn", 0.38, 0.65),
)

WINDOW_SECONDS = 300  # 5-minute BTC up/down windows
TICK_SIZE = "0.01"
MIN_ORDER_SIZE_SHARES = 5.0


def _make_book(token_id: str, best_ask: float, ts_ns: int) -> Orderbook:
    """Build a simple synthetic orderbook with a 2-cent spread + a few levels."""
    best_bid = max(0.01, best_ask - 0.02)
    return Orderbook(
        token_id=token_id,
        bids=(
            OrderbookLevel(price=best_bid, size_shares=200.0),
            OrderbookLevel(price=max(0.01, best_bid - 0.01), size_shares=400.0),
        ),
        asks=(
            OrderbookLevel(price=best_ask, size_shares=200.0),
            OrderbookLevel(price=min(0.99, best_ask + 0.01), size_shares=400.0),
        ),
        tick_size=TICK_SIZE,
        min_order_size_shares=MIN_ORDER_SIZE_SHARES,
        neg_risk=False,
        ts_ns=ts_ns,
    )


async def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )

    starting_bankroll = float(os.environ.get("MM_STARTING_BANKROLL", "1000"))
    duration_s = float(os.environ.get("MM_DURATION_S", "60"))
    tick_interval_s = float(os.environ.get("MM_TICK_INTERVAL_S", "1.0"))
    decision_log_root = Path(os.environ.get("MM_DECISION_LOG_ROOT", "state/mm-decisions"))
    halt_sentinel_path = Path(os.environ.get("MM_HALT_SENTINEL_PATH", "state/halt.sentinel"))
    kill_switch = os.environ.get("MM_KILL_SWITCH", "false").lower() == "true"

    # If halt sentinel pre-exists, refuse to start. Sync check is fine
    # here — script startup, before the event loop is hot.
    if halt_sentinel_path.exists():
        LOG.warning(
            "halt sentinel present at startup; refusing to start. remove %s and try again",
            halt_sentinel_path,
        )
        return 2
    if kill_switch:
        LOG.warning("MM_KILL_SWITCH=true at startup; writing halt sentinel + exiting")
        await write_halt_sentinel_async("operator_kill_switch_startup", path=halt_sentinel_path)
        return 0

    # Bankroll replay
    bankroll = replay_bankroll(decision_log_root, starting_bankroll=starting_bankroll)
    LOG.info("replayed bankroll: $%.2f (starting=$%.2f)", bankroll, starting_bankroll)

    priors = J7Priors.load()
    LOG.info("loaded priors from %s", priors.source_path)

    gate = RiskGate(caps=RiskCaps())

    def _bankroll_getter() -> float:
        return bankroll

    strategy = MarketMakerStrategy(
        priors=priors,
        bankroll_getter=_bankroll_getter,
        gate=gate,
    )

    client = MockClobOrderClient()
    decision_log = MmDecisionLog(root=decision_log_root)

    runner = MmRunner(
        strategy=strategy,
        client=client,
        decision_log=decision_log,
        halt_sentinel_path=halt_sentinel_path,
        dry_run=True,
    )

    # Seed orderbooks
    now_ns = time.time_ns()
    for m in SYNTHETIC_MARKETS:
        client.set_orderbook(_make_book(m.token_up, m.best_ask_up_start, now_ns))
        client.set_orderbook(_make_book(m.token_dn, m.best_ask_dn_start, now_ns))

    # Start heartbeat task in background
    heartbeat_task = asyncio.create_task(
        mm_heartbeat_loop(
            client=client,
            halt_writer=lambda reason: write_halt_sentinel_async(reason, path=halt_sentinel_path),
            interval_s=5.0,
        )
    )

    rng = random.Random(42)  # noqa: S311  deterministic paper-mode sim (not crypto)
    start_ts = time.time()
    deadline = start_ts + duration_s
    n_ticks = 0
    window_starts: dict[str, float] = {m.market_id: start_ts for m in SYNTHETIC_MARKETS}

    LOG.info("paper run starting; duration=%.0fs tick=%.1fs", duration_s, tick_interval_s)

    while time.time() < deadline:
        if runner.halt_sentinel_present():
            LOG.warning("halt sentinel detected mid-run; draining")
            break

        now = time.time()
        ts_ns = time.time_ns()
        for m in SYNTHETIC_MARKETS:
            window_age = now - window_starts[m.market_id]
            seconds_remaining = max(0.0, WINDOW_SECONDS - window_age)

            # Mutate the synthetic book by a small random tick
            for side_label, token_id in (
                (Side.UP, m.token_up),
                (Side.DOWN, m.token_dn),
            ):
                cur_book = await client.get_orderbook(token_id)
                if cur_book is None or cur_book.best_ask is None:
                    continue
                delta = rng.uniform(-0.01, 0.01)
                new_ask = round(max(0.05, min(0.95, cur_book.best_ask + delta)), 2)
                client.set_orderbook(_make_book(token_id, new_ask, ts_ns))

                await runner.on_book_update(
                    market_id=m.market_id,
                    token_id=token_id,
                    side=side_label,
                    best_ask=new_ask,
                    tick_size=TICK_SIZE,
                    min_order_size_shares=MIN_ORDER_SIZE_SHARES,
                    seconds_remaining=seconds_remaining,
                )

            # Resolve window if expired
            if seconds_remaining <= 0:
                winning_side = Side.UP if rng.random() < 0.5 else Side.DOWN
                await runner.on_resolution(market_id=m.market_id, winning_side=winning_side)
                window_starts[m.market_id] = now

        n_ticks += 1
        await asyncio.sleep(tick_interval_s)

    # Shutdown
    LOG.info("paper run ending; draining; ticks=%d", n_ticks)
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass

    n_drained = await runner.drain()
    decision_log.close()

    LOG.info(
        "paper run complete: ticks=%d orders_placed=%d cancels=%d post_only_rejects=%d drained=%d",
        n_ticks,
        client.n_orders_placed,
        client.n_orders_cancelled,
        client.n_post_only_rejections,
        n_drained,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
