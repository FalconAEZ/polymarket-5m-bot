"""Safety circuit tests for MmRunner — the end-to-end halt chain.

Verifies that in-process RiskGate self-halts (daily-loss cap) and
operator-driven halts (kill switch path) both reach the filesystem
sentinel + alert callback. Without this bridge, alerter + dashboard
+ peer processes would never know the bot stopped.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from polymarket_bot._live.alerter.halt import write_halt_sentinel
from polymarket_bot._live.clob_orders import (
    MockClobOrderClient,
    Orderbook,
    OrderbookLevel,
)
from polymarket_bot._paper.mm_runner import MmDecisionLog, MmRunner
from polymarket_bot.strategies.j7_priors import J7Priors, TierStats
from polymarket_bot.strategies.market_maker import (
    MarketMakerStrategy,
    RiskCaps,
    RiskGate,
    Side,
)


def _book(token_id: str, best_ask: float) -> Orderbook:
    return Orderbook(
        token_id=token_id,
        bids=(OrderbookLevel(price=max(0.01, best_ask - 0.02), size_shares=100.0),),
        asks=(OrderbookLevel(price=best_ask, size_shares=100.0),),
        tick_size="0.01",
        min_order_size_shares=5.0,
        neg_risk=False,
        ts_ns=time.time_ns(),
    )


def _priors() -> J7Priors:
    return J7Priors(
        tiers={
            "30-50%": TierStats(n=14802, wr=0.454, per_trade_pnl=1.17),
            "50-70%": TierStats(n=39681, wr=0.631, per_trade_pnl=0.95),
        },
        source_path=Path("test"),
        max_bet_usd=100.0,
    )


def _make_runner_with_low_loss_cap(
    tmp_path: Path,
    alert_calls: list[dict[str, Any]],
) -> tuple[MmRunner, MarketMakerStrategy]:
    async def _capture(payload: dict[str, Any]) -> None:
        alert_calls.append(payload)

    strategy = MarketMakerStrategy(
        priors=_priors(),
        bankroll_getter=lambda: 1000.0,
        gate=RiskGate(caps=RiskCaps(max_daily_loss_usd=10.0)),
    )
    runner = MmRunner(
        strategy=strategy,
        client=MockClobOrderClient(),
        decision_log=MmDecisionLog(root=tmp_path / "mm-decisions"),
        halt_sentinel_path=tmp_path / "halt.sentinel",
        alert_callback=_capture,
    )
    return runner, strategy


# ---------------- daily-loss cap → sentinel + alert ----------------


async def test_resolution_triggers_sentinel_write_on_daily_loss_trip(tmp_path: Path) -> None:
    alert_calls: list[dict[str, Any]] = []
    runner, strategy = _make_runner_with_low_loss_cap(tmp_path, alert_calls)

    # Seed enough losing inventory to trip the $10 daily-loss cap when
    # resolved against. Buy 50 DOWN shares at $0.30 each → $15 cost; if UP
    # wins, realized PnL = -$15 < -$10 cap.
    strategy.tracker.confirm_in_flight("m1", Side.DOWN, 15.0, 50.0)
    result = await runner.on_resolution(market_id="m1", winning_side=Side.UP)

    assert result.realized_pnl_usd == pytest.approx(-15.0)
    # Sentinel file should be on disk.
    assert (tmp_path / "halt.sentinel").exists()
    # Alert callback was invoked with a CRITICAL daily-loss-tripped payload.
    assert len(alert_calls) == 1
    payload = alert_calls[0]
    assert payload["level"] == "critical"
    assert payload["source"] == "mm-bot"
    assert "daily loss" in payload["message"].lower()


async def test_sentinel_written_once_idempotent(tmp_path: Path) -> None:
    """A second halt-triggering resolution does NOT re-write the sentinel
    or re-fire the alert (one-shot semantics)."""
    alert_calls: list[dict[str, Any]] = []
    runner, strategy = _make_runner_with_low_loss_cap(tmp_path, alert_calls)

    strategy.tracker.confirm_in_flight("m1", Side.DOWN, 15.0, 50.0)
    await runner.on_resolution(market_id="m1", winning_side=Side.UP)
    sentinel_mtime_1 = (tmp_path / "halt.sentinel").stat().st_mtime_ns
    n_alerts_1 = len(alert_calls)

    # Trigger another resolution that would also halt.
    strategy.tracker.confirm_in_flight("m2", Side.DOWN, 15.0, 50.0)
    await runner.on_resolution(market_id="m2", winning_side=Side.UP)
    sentinel_mtime_2 = (tmp_path / "halt.sentinel").stat().st_mtime_ns
    n_alerts_2 = len(alert_calls)

    assert sentinel_mtime_2 == sentinel_mtime_1
    assert n_alerts_2 == n_alerts_1


async def test_runner_short_circuits_after_sentinel_write(tmp_path: Path) -> None:
    """After the gate halts + sentinel writes, on_book_update must return []
    and place 0 new orders even if the book moves significantly."""
    runner, strategy = _make_runner_with_low_loss_cap(tmp_path, [])
    strategy.tracker.confirm_in_flight("m1", Side.DOWN, 15.0, 50.0)
    await runner.on_resolution(market_id="m1", winning_side=Side.UP)

    runner.client.set_orderbook(_book("t1", best_ask=0.45))
    actions = await runner.on_book_update(
        market_id="m2",
        token_id="t1",
        side=Side.UP,
        best_ask=0.45,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    assert actions == []


# ---------------- pre-existing sentinel respected on startup ----------------


def test_pre_existing_sentinel_blocks_via_halt_present(tmp_path: Path) -> None:
    """The runner's halt_sentinel_present() reflects on-disk state, so a
    pre-existing sentinel (operator wrote it) is honored without any
    code-path-specific check."""
    sentinel = tmp_path / "halt.sentinel"
    write_halt_sentinel("operator-cli", time.time_ns(), path=sentinel)
    runner, _strategy = _make_runner_with_low_loss_cap(tmp_path, [])
    assert runner.halt_sentinel_present() is True


# ---------------- alert callback robustness ----------------


async def test_alert_callback_exception_does_not_crash_runner(tmp_path: Path) -> None:
    """If the operator's alerter pipe is broken (Redis down, etc.) the
    runner must still write the sentinel + continue functioning. The
    alert is best-effort; the sentinel is authoritative."""

    async def _broken(_payload: dict[str, Any]) -> None:
        raise RuntimeError("redis down")

    strategy = MarketMakerStrategy(
        priors=_priors(),
        bankroll_getter=lambda: 1000.0,
        gate=RiskGate(caps=RiskCaps(max_daily_loss_usd=10.0)),
    )
    runner = MmRunner(
        strategy=strategy,
        client=MockClobOrderClient(),
        decision_log=MmDecisionLog(root=tmp_path / "mm-decisions"),
        halt_sentinel_path=tmp_path / "halt.sentinel",
        alert_callback=_broken,
    )
    strategy.tracker.confirm_in_flight("m1", Side.DOWN, 15.0, 50.0)
    # Should NOT raise.
    await runner.on_resolution(market_id="m1", winning_side=Side.UP)
    assert (tmp_path / "halt.sentinel").exists()


# ---------------- systemd unit sanity ----------------


def test_bot_mm_service_unit_file_present_and_valid() -> None:
    """Sanity check the bot-mm.service unit file parses as expected
    (basic ini-format sections present + ExecStart references
    scripts/run_mm_paper.py)."""
    unit_path = Path("runbooks/systemd/bot-mm.service")
    assert unit_path.exists()
    text = unit_path.read_text()
    assert "[Unit]" in text
    assert "[Service]" in text
    assert "[Install]" in text
    assert "scripts/run_mm_paper.py" in text
    # Hardening defaults — match bot-staging.service.
    assert "NoNewPrivileges=true" in text
    assert "PrivateTmp=true" in text
