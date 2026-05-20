"""Tests for polymarket_bot._paper.mm_runner.

Covers MmDecisionLog write/read, bankroll replay, MmRunner end-to-end
behaviors (place, cancel, halt sentinel, drain, on_fill_confirmed,
on_resolution, multi-market isolation), and a queue-doesn't-overflow
proxy via a 1000-tick burst.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from polymarket_bot._live.clob_orders import (
    MockClobOrderClient,
    Orderbook,
    OrderbookLevel,
)
from polymarket_bot._paper.mm_runner import (
    MmDecisionLog,
    MmRunner,
    read_mm_jsonl,
    replay_bankroll,
)
from polymarket_bot.strategies.j7_priors import J7Priors, TierStats
from polymarket_bot.strategies.market_maker import (
    MarketMakerStrategy,
    RiskCaps,
    RiskGate,
    Side,
)


def _priors() -> J7Priors:
    return J7Priors(
        tiers={
            "<15%": TierStats(n=722, wr=0.137, per_trade_pnl=8.83),
            "15-30%": TierStats(n=3167, wr=0.25, per_trade_pnl=0.11),
            "30-50%": TierStats(n=14802, wr=0.454, per_trade_pnl=1.17),
            "50-70%": TierStats(n=39681, wr=0.631, per_trade_pnl=0.95),
            "70-85%": TierStats(n=28674, wr=0.78, per_trade_pnl=0.40),
            "85-100%": TierStats(n=14916, wr=0.917, per_trade_pnl=0.65),
        },
        source_path=Path("test"),
        max_bet_usd=100.0,
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


def _make_runner(
    tmp_path: Path,
) -> tuple[MmRunner, MockClobOrderClient, MarketMakerStrategy, MmDecisionLog]:
    client = MockClobOrderClient()
    strategy = MarketMakerStrategy(
        priors=_priors(),
        bankroll_getter=lambda: 1000.0,
        gate=RiskGate(caps=RiskCaps()),
        blocklist=frozenset(),  # isolate runner mechanics from default blocklist
    )
    log = MmDecisionLog(root=tmp_path / "mm-decisions")
    runner = MmRunner(
        strategy=strategy,
        client=client,
        decision_log=log,
        halt_sentinel_path=tmp_path / "halt.sentinel",
        dry_run=True,
    )
    return runner, client, strategy, log


# ---------------- MmDecisionLog ----------------


def test_decision_log_writes_and_reads(tmp_path: Path) -> None:
    log = MmDecisionLog(root=tmp_path / "logs")
    log.record("place_succeeded", {"order_id": "abc", "price": 0.45})
    log.record("resolve", {"realized_pnl_usd": 1.23})
    log.close()
    files = list((tmp_path / "logs").glob("*.jsonl"))
    assert len(files) == 1
    records = list(read_mm_jsonl(files[0]))
    assert len(records) == 2
    assert records[0]["kind"] == "place_succeeded"
    assert records[1]["realized_pnl_usd"] == 1.23


def test_decision_log_close_rejects_further_writes(tmp_path: Path) -> None:
    log = MmDecisionLog(root=tmp_path / "logs")
    log.record("place_succeeded", {"order_id": "abc"})
    log.close()
    with pytest.raises(RuntimeError, match="closed"):
        log.record("resolve", {"realized_pnl_usd": 0})


# ---------------- replay_bankroll ----------------


def test_replay_bankroll_empty_root_returns_starting(tmp_path: Path) -> None:
    assert replay_bankroll(tmp_path / "no-such-dir", starting_bankroll=500.0) == 500.0


def test_replay_bankroll_sums_resolve_records(tmp_path: Path) -> None:
    root = tmp_path / "mm-decisions"
    root.mkdir()
    (root / "2026-05-20.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"kind": "resolve", "realized_pnl_usd": 10.0}),
                json.dumps({"kind": "place_succeeded", "order_id": "abc"}),
                json.dumps({"kind": "resolve", "realized_pnl_usd": -3.0}),
            ]
        )
        + "\n"
    )
    assert replay_bankroll(root, starting_bankroll=1000.0) == pytest.approx(1007.0)


# ---------------- MmRunner.on_book_update ----------------


async def test_runner_on_book_update_places_ladder(tmp_path: Path) -> None:
    runner, client, _strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    executed = await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    assert len(executed) >= 1
    assert client.n_orders_placed >= 1


async def test_runner_post_only_rejection_is_soft_skip(tmp_path: Path) -> None:
    """Forcing a post-only rejection should not raise; the runner logs + drops."""
    runner, client, _strategy, _log = _make_runner(tmp_path)
    # Ask is 0.40; LadderPlanner will try L1 at 0.35, L2 at 0.30, L3 at 0.20.
    # All three should sit below the ask and post fine.
    # We override by seeding a much tighter book where ladder levels cross.
    # Simplest: pre-seed the book with best_ask=0.20 so L1 at 0.15 crosses
    # nothing but L2 at 0.10 would clip the floor anyway. Use injection.
    client.set_orderbook(_book("t1", best_ask=0.40))
    # Force the next place to reject regardless of price.
    from polymarket_bot._live.clob_orders import PostOnlyRejected

    client.raise_on_next_place = PostOnlyRejected
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    # The rejection should have been logged but not raised.
    log_files = list((tmp_path / "mm-decisions").glob("*.jsonl"))
    assert log_files
    records = list(read_mm_jsonl(log_files[0]))
    kinds = [r["kind"] for r in records]
    assert "place_rejected" in kinds


async def test_runner_halt_sentinel_short_circuits(tmp_path: Path) -> None:
    runner, client, _strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    # Write the sentinel.
    (tmp_path / "halt.sentinel").write_text("{}")
    executed = await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    assert executed == []
    assert client.n_orders_placed == 0


async def test_runner_drain_cancels_all_orders(tmp_path: Path) -> None:
    runner, client, strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    assert len(strategy.open_orders) >= 1
    n = await runner.drain()
    assert n >= 1
    assert client.open_orders_count() == 0
    assert len(strategy.open_orders) == 0


# ---------------- MmRunner.on_fill_confirmed + on_resolution ----------------


async def test_runner_on_fill_confirmed_drains_in_flight(tmp_path: Path) -> None:
    runner, client, strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    # Pick any open order and confirm a fill against it.
    order_id = next(iter(strategy.open_orders.keys()))
    order = strategy.open_orders[order_id]
    pos_before = strategy.tracker.position("m1", Side.UP)
    in_flight_before = pos_before.in_flight_usd
    await runner.on_fill_confirmed(
        order_id=order_id,
        fill_price=order.level.price,
        fill_size_shares=order.level.size_shares,
    )
    pos_after = strategy.tracker.position("m1", Side.UP)
    assert order_id not in strategy.open_orders
    # in_flight should have decreased.
    assert pos_after.in_flight_usd <= in_flight_before


async def test_runner_on_resolution_writes_record(tmp_path: Path) -> None:
    runner, client, strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    # Seed an UP position by directly mutating tracker (faster than going
    # through place + on_book_update flow for this targeted test).
    strategy.tracker.confirm_in_flight("m1", Side.UP, 5.0, 12.5)
    result = await runner.on_resolution(market_id="m1", winning_side=Side.UP)
    # winning_side=UP: realized = shares - cost = 12.5 - 5.0 = +7.5
    assert result.realized_pnl_usd == pytest.approx(7.5)
    log_files = list((tmp_path / "mm-decisions").glob("*.jsonl"))
    records = list(read_mm_jsonl(log_files[0]))
    assert any(r["kind"] == "resolve" for r in records)


# ---------------- multi-market isolation ----------------


async def test_runner_multi_market_isolation(tmp_path: Path) -> None:
    runner, client, strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    client.set_orderbook(_book("t2", best_ask=0.45))
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.UP,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    await runner.on_book_update(
        market_id="m2",
        token_id="t2",
        side=Side.UP,
        best_ask=0.45,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    # Resolving m1 must not touch m2 inventory.
    m2_gross_before = strategy.tracker.gross_exposure_for_market("m2")
    await runner.on_resolution(market_id="m1", winning_side=Side.UP)
    m2_gross_after = strategy.tracker.gross_exposure_for_market("m2")
    assert m2_gross_before == m2_gross_after


# ---------------- queue-doesn't-overflow proxy ----------------


async def test_runner_handles_burst_of_ticks(tmp_path: Path) -> None:
    """1000 book updates in a tight loop; no exception + decision log
    write rate keeps up. Proxy for the queue-doesn't-overflow discipline
    from memory/feedback_test_under_load."""
    runner, client, _strategy, _log = _make_runner(tmp_path)
    client.set_orderbook(_book("t1", best_ask=0.40))
    for _ in range(1000):
        await runner.on_book_update(
            market_id="m1",
            token_id="t1",
            side=Side.UP,
            best_ask=0.40,
            tick_size="0.01",
            min_order_size_shares=5.0,
            seconds_remaining=200.0,
        )
    # No exception thrown. After 1000 ticks at no book-move, no new orders
    # placed after the first ladder (move=0 < l1_repost_threshold).
    assert client.n_orders_placed <= 10  # initial ladder only


# ---------- Edge 4 prep: metadata_getter (audit §2 Edge 4) ----------


async def test_metadata_getter_appended_to_every_record(tmp_path: Path) -> None:
    """When metadata_getter is set, its dict is merged into every
    decision-log record so Day-7 audit can group fills by MMD label."""
    runner, client, _strategy, _log = _make_runner(tmp_path)
    captured_calls: list[None] = []

    def _mmd_metadata() -> dict[str, str | float]:
        captured_calls.append(None)
        return {"mmd_label": "MIXED", "mmd_conf": 0.62}

    runner.metadata_getter = _mmd_metadata
    client.set_orderbook(_book("t1", best_ask=0.40))
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.DOWN,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    log_files = list((tmp_path / "mm-decisions").glob("*.jsonl"))
    records = list(read_mm_jsonl(log_files[0]))
    assert records, "expected at least one decision-log record"
    for r in records:
        assert r.get("mmd_label") == "MIXED"
        assert r.get("mmd_conf") == 0.62
    assert captured_calls, "metadata_getter must be called at least once"


async def test_metadata_getter_none_means_no_extra_fields(tmp_path: Path) -> None:
    """Default (metadata_getter=None) preserves the bare schema — no
    extra fields appear in the record. Backward-compat."""
    runner, client, _strategy, _log = _make_runner(tmp_path)
    assert runner.metadata_getter is None
    client.set_orderbook(_book("t1", best_ask=0.40))
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.DOWN,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    log_files = list((tmp_path / "mm-decisions").glob("*.jsonl"))
    records = list(read_mm_jsonl(log_files[0]))
    assert records
    for r in records:
        assert "mmd_label" not in r
        assert "mmd_conf" not in r


async def test_metadata_getter_exception_does_not_crash_record(tmp_path: Path) -> None:
    """If the getter raises (e.g. MMD detector down), the record is
    still written without metadata — observability data is best-effort,
    safety + accounting records are authoritative."""
    runner, client, _strategy, _log = _make_runner(tmp_path)

    def _broken_getter() -> dict[str, str]:
        raise RuntimeError("mmd detector unreachable")

    runner.metadata_getter = _broken_getter
    client.set_orderbook(_book("t1", best_ask=0.40))
    # Must NOT raise.
    await runner.on_book_update(
        market_id="m1",
        token_id="t1",
        side=Side.DOWN,
        best_ask=0.40,
        tick_size="0.01",
        min_order_size_shares=5.0,
        seconds_remaining=200.0,
    )
    log_files = list((tmp_path / "mm-decisions").glob("*.jsonl"))
    records = list(read_mm_jsonl(log_files[0]))
    assert records, "record should still be written even when getter fails"
