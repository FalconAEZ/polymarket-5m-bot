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
import os
import os.path
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
from polymarket_bot.alerts import AlertSink, NullAlertSink, RedisAlertSink  # noqa: E402
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.feeds.protocols import Feed  # noqa: E402
from polymarket_bot.resolver import WINDOW_SECONDS, active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import (  # noqa: E402
    DEFAULT_THRESHOLD_PCT,
    DeterministicStrategy,
)
from polymarket_bot.strategies.protocol import Strategy  # noqa: E402
from polymarket_bot.strategies.spot_aware import SpotAwareStrategy  # noqa: E402
from polymarket_bot.strategies.spot_aware_priors import load_priors  # noqa: E402
from polymarket_bot.strategies.spot_aware_v2 import SpotAwareStrategyV2  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_paper")
WARM_LOOKAHEAD_WINDOWS = 12  # ~1 hour of windows pre-resolved
WARMER_INTERVAL_S = 60.0
HALT_SENTINEL_PATH = Path("state/halt.sentinel")
HALT_POLL_INTERVAL_S = 1.0

# Strategy selection (Phase 11.A: spot_aware deployed solo per
# design/spot_aware_strategy.md §"Concurrency + state isolation"). Override
# via STRATEGY env var = "deterministic" | "spot_aware". Default = spot_aware
# now that phase-5-pass is in.
DEFAULT_STRATEGY_NAME = "spot_aware"


def _configure_logging() -> None:
    # nohup-style launchers redirect stdout/stderr to state/paper.log; a
    # second FileHandler would duplicate every line. StreamHandler only.
    Path("state").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _default_feeds() -> list[Feed]:
    return [
        BinanceTradeFeed(),
        CoinbaseMatchFeed(),
        OracleFeed(),
        PolymarketFeed(),
    ]


def _sentinel_present(sentinel_str: str) -> bool:
    """Sync wrapper around os.path.exists.

    Kept sync (and out of any async function) because ruff's ASYNC240 flags
    pathlib/os.path calls inside async defs. The check is a microsecond
    stat() — pushing it to a worker thread would cost more than the syscall.
    """
    return os.path.exists(sentinel_str)


async def _halt_watcher(
    stop: asyncio.Event,
    *,
    sentinel: Path = HALT_SENTINEL_PATH,
    interval_s: float = HALT_POLL_INTERVAL_S,
) -> None:
    """Poll for the halt sentinel; on presence, set the runner stop_event.

    Per design/alerter.md §4.4: the bot reads the sentinel as opaque presence.
    Corrupt JSON inside still halts. The poll interval is 1s, well below any
    operator-perceptible delay between `/halt` and the bot exiting.
    """
    sentinel_str = str(sentinel)
    while not stop.is_set():
        if _sentinel_present(sentinel_str):
            LOG.warning("halt sentinel detected at %s; setting stop_event", sentinel)
            stop.set()
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)


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


def _env_float(name: str, default: float | None) -> float | None:
    """Read an optional float-valued env var. Returns default on missing/empty."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"env var {name}={raw!r} is not a float") from e


def _env_bool(name: str, default: bool = False) -> bool:
    """Read an optional bool env var. '1', 'true', 'yes' (case-insensitive) → True."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _build_strategy(name: str) -> Strategy:
    if name == "deterministic":
        return DeterministicStrategy(threshold_pct=DEFAULT_THRESHOLD_PCT)
    if name == "spot_aware":
        # Optional env overrides for the loose-start exploratory mode
        # documented in runbooks/decisions/loose-start-2026-05-09.md.
        # Unset → strategy uses its own defaults (Δ_min=8, EV_min=0.5¢).
        kwargs: dict[str, float] = {}
        d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
        if d_min is not None:
            kwargs["delta_min_bps"] = d_min
        d_max = _env_float("SPOT_AWARE_DELTA_MAX_BPS", None)
        if d_max is not None:
            kwargs["delta_max_bps"] = d_max
        ev_min = _env_float("SPOT_AWARE_EV_MIN_DOLLARS", None)
        if ev_min is not None:
            kwargs["ev_min_dollars_per_share"] = ev_min
        limit_buf = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
        if limit_buf is not None:
            kwargs["limit_buffer_usd"] = limit_buf
        aggressive = _env_bool("SPOT_AWARE_AGGRESSIVE_MODE", False)
        # Mypy needs the bool kwarg typed separately from the float dict.
        if kwargs or aggressive:
            LOG.warning(
                "spot_aware overrides: delta_min=%s delta_max=%s ev_min=%s aggressive=%s",
                kwargs.get("delta_min_bps"),
                kwargs.get("delta_max_bps"),
                kwargs.get("ev_min_dollars_per_share"),
                aggressive,
            )
        return SpotAwareStrategy(priors=load_priors(), aggressive_mode=aggressive, **kwargs)
    if name == "spot_aware_v2":
        # v2 = tier-restricted, no-fallback variant of spot_aware. Locked
        # spec: design/spot_aware_v2_tier_restricted.md. Drops tier 50-70%
        # explicitly, requires a real priors-table hit (no p_win=0.54
        # fallback), and re-enforces delta_min/max + EV gate. Same env-var
        # overrides as v1 but ignores SPOT_AWARE_AGGRESSIVE_MODE (v2 cannot
        # be put into aggressive bypass mode).
        v2_kwargs: dict[str, float] = {}
        d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
        if d_min is not None:
            v2_kwargs["delta_min_bps"] = d_min
        d_max = _env_float("SPOT_AWARE_DELTA_MAX_BPS", None)
        if d_max is not None:
            v2_kwargs["delta_max_bps"] = d_max
        ev_min = _env_float("SPOT_AWARE_EV_MIN_DOLLARS", None)
        if ev_min is not None:
            v2_kwargs["ev_min_dollars_per_share"] = ev_min
        limit_buf = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
        if limit_buf is not None:
            v2_kwargs["limit_buffer_usd"] = limit_buf
        if v2_kwargs:
            LOG.warning("spot_aware_v2 overrides: %s", v2_kwargs)
        return SpotAwareStrategyV2(priors=load_priors(), **v2_kwargs)
    raise ValueError(
        f"unknown STRATEGY env value {name!r}; pick deterministic | spot_aware | spot_aware_v2"
    )


def _build_alert_sink() -> AlertSink:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        LOG.info("REDIS_URL not set; using NullAlertSink (alerts dropped)")
        return NullAlertSink()
    LOG.info("RedisAlertSink wired to %s", redis_url)
    return RedisAlertSink(url=redis_url, source="bot-staging")


async def main() -> int:
    _configure_logging()
    LOG.info("paper-mode runtime starting")

    if _sentinel_present(str(HALT_SENTINEL_PATH)):
        LOG.critical(
            "halt sentinel %s present at startup; refusing to run. "
            "Remove it manually before restarting bot-staging.",
            HALT_SENTINEL_PATH,
        )
        return 1

    alert_sink = _build_alert_sink()

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
    strategy = _build_strategy(os.environ.get("STRATEGY", DEFAULT_STRATEGY_NAME))
    LOG.info("active strategy: %s", strategy.name)
    decision_log = DecisionLog(root="state/decisions")

    # Instant-settle: optional Polymarket Gamma poll at T+300+1s before
    # falling back to the local Chainlink-derived resolution. Per
    # design/instant_settlement.md. Disabled by default (legacy behavior);
    # set INSTANT_SETTLE_ENABLED=1 in .envrc to enable. Reduces settle
    # latency from ~60s to ~1-3s. Owns its own httpx.Client so the runner
    # doesn't share the polymarket-feed client.
    import httpx as _httpx

    instant_settle_enabled = _env_bool("INSTANT_SETTLE_ENABLED", False)
    instant_settle_timeout_s = _env_float("INSTANT_SETTLE_GAMMA_TIMEOUT_S", 30.0) or 30.0
    instant_settle_interval_s = _env_float("INSTANT_SETTLE_GAMMA_POLL_INTERVAL_S", 1.0) or 1.0
    gamma_client_for_settle = _httpx.Client() if instant_settle_enabled else None
    if instant_settle_enabled:
        LOG.info(
            "instant-settle ENABLED: gamma poll timeout=%ss interval=%ss",
            instant_settle_timeout_s,
            instant_settle_interval_s,
        )

    runner = PaperRunner(
        feeds=feeds,
        strategy=strategy,
        side_resolver=side_index,
        shadow_book=ShadowBook(),
        decision_log=decision_log,
        alert_sink=alert_sink,
        instant_settle_enabled=instant_settle_enabled,
        gamma_client=gamma_client_for_settle,
        instant_settle_timeout_s=instant_settle_timeout_s,
        instant_settle_interval_s=instant_settle_interval_s,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    warmer_task = asyncio.create_task(_warmer(side_index, stop=stop_event), name="warmer")
    runner_task = asyncio.create_task(runner.run(stop=stop_event), name="paper-runner")
    halt_task = asyncio.create_task(_halt_watcher(stop_event), name="halt-watcher")

    LOG.info("paper-mode runtime up; waiting for SIGTERM/SIGINT or halt sentinel")
    await stop_event.wait()
    LOG.info("shutdown signal received")
    runner.stop()
    await asyncio.gather(runner_task, warmer_task, halt_task, return_exceptions=True)
    alert_sink.close()
    LOG.info("shutdown complete; dropped_records=%d", runner.dropped_records_total)
    return 0


def cli() -> None:
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
