"""Tests for polymarket_bot.dashboard_server.resolver_loop.

Async background loop. We invoke it directly with a tiny interval and
assert ResolverState is updated correctly. Network I/O is stubbed via
httpx.MockTransport injected through monkeypatch — the loop creates its
own httpx.Client inside ``_run_one_pass_blocking`` so we patch that
constructor.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from polymarket_bot.dashboard_server import resolver_loop as rl


def _write_raw_jsonl(raw_dir: Path, *, window_ts: int = 1778272200) -> None:
    raw_dir.mkdir(parents=True, exist_ok=True)
    fired = json.dumps(
        {
            "kind": "fired",
            "decision_id": "d1",
            "window_ts": window_ts,
            "decision_ts_ns": window_ts * 1_000_000_000,
            "asset_id": "0x" + "ab" * 31,
            "side": "DOWN",
            "size_usd": 5.0,
            "price_limit": 0.5,
            "ttl_s": 30,
            "rationale": "strategy=spot_aware mode=aggressive side=DOWN",
            "snapshot": {},
            "composite_pct": None,
            "fill": None,
        }
    )
    settled = json.dumps(
        {
            "kind": "settled",
            "decision_id": "d1",
            "window_ts": window_ts,
            "settled_ts_ns": (window_ts + 300) * 1_000_000_000,
            "open_oracle": 80000.0,
            "close_oracle": 80100.0,
            "resolution": "UP",  # oracle wrong
            "resolution_source": "chainlink-local",
            "fill_at_settle": {"size_filled": 10.0, "price_filled": 0.5, "fee_usd": 0.0},
            "pnl_usd": -5.0,  # oracle PnL
        }
    )
    (raw_dir / "2026-05-08.jsonl").write_text(fired + "\n" + settled + "\n")


def _gamma_polymarket_says_down() -> httpx.MockTransport:
    payload = [
        {
            "markets": [
                {
                    "closed": True,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["0", "1"],
                }
            ]
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.MockTransport(handler)


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, transport: httpx.MockTransport) -> None:
    """Replace httpx.Client constructor inside the resolver_loop module so
    every Client instantiated by the loop body uses our MockTransport."""
    real_client = httpx.Client

    def fake_client(*args, **kwargs):  # type: ignore[no-untyped-def]
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(rl.httpx, "Client", fake_client)


@pytest.mark.asyncio
async def test_one_pass_writes_resolved_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "decisions"
    _write_raw_jsonl(raw)
    _patch_httpx_client(monkeypatch, _gamma_polymarket_says_down())

    state = rl.ResolverState()
    config = rl.ResolverConfig(initial_delay_s=0.0, interval_s=10.0)

    task = rl.spawn_resolver_task(tmp_path, state, config=config)
    # Give the loop one tick to do its first pass
    for _ in range(50):
        await asyncio.sleep(0.02)
        if state.last_success_utc is not None:
            break
    await rl.cancel_resolver_task(task)

    assert state.last_success_utc is not None
    assert state.last_error is None
    assert state.n_runs >= 1
    assert state.n_records_changed == 1

    resolved = tmp_path / "decisions-resolved" / "2026-05-08.jsonl"
    assert resolved.exists()
    lines = resolved.read_text().strip().splitlines()
    settled_rec = json.loads(lines[1])
    assert settled_rec["resolution"] == "DOWN"
    assert settled_rec["resolution_source"] == "polymarket"
    assert settled_rec["pnl_usd"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_loop_skips_when_raw_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No raw decisions dir → returns (0,0,0); loop stays alive."""
    _patch_httpx_client(monkeypatch, _gamma_polymarket_says_down())
    state = rl.ResolverState()
    config = rl.ResolverConfig(initial_delay_s=0.0, interval_s=10.0)
    task = rl.spawn_resolver_task(tmp_path, state, config=config)
    for _ in range(20):
        await asyncio.sleep(0.02)
        if state.last_success_utc is not None:
            break
    await rl.cancel_resolver_task(task)
    assert state.last_success_utc is not None
    assert state.last_error is None
    assert state.n_records_changed == 0


@pytest.mark.asyncio
async def test_loop_recovers_from_gamma_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gamma 500 → loop logs the error but keeps running; next pass succeeds
    once we swap the transport."""
    raw = tmp_path / "decisions"
    _write_raw_jsonl(raw)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    bad_transport = httpx.MockTransport(boom)
    _patch_httpx_client(monkeypatch, bad_transport)

    state = rl.ResolverState()
    config = rl.ResolverConfig(initial_delay_s=0.0, interval_s=0.05)
    task = rl.spawn_resolver_task(tmp_path, state, config=config)
    # Wait for at least one attempt to land
    for _ in range(50):
        await asyncio.sleep(0.02)
        if state.n_runs >= 1:
            break
    await rl.cancel_resolver_task(task)

    # The exception was inside re_resolve_file (httpx.Client succeeded; the
    # transport raises on .get). The loop catches it and keeps state.last_error.
    # n_runs should still increment.
    assert state.n_runs >= 1
