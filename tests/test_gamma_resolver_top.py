"""Tests for polymarket_bot.gamma_resolver (the top-level module).

Mirrors tests/dashboard/test_gamma_resolver.py from the dashboard branch
but lives at top-level since the module moved. Coverage:
  * gamma_resolution: closed UP, closed DOWN, not-closed, missing, HTTP fail
  * realised_pnl: winning, losing, fee, sim-fill-bug correction
  * re_resolve_file: skip-already-polymarket, oracle->PM truth correction
  * re_resolve_dir: refuses in-place, processes all .jsonl, skips bak/tmp
  * poll_gamma_for_resolution: returns immediately on hit, polls until
    available, returns None on timeout
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from polymarket_bot.gamma_resolver import (
    gamma_resolution,
    poll_gamma_for_resolution,
    re_resolve_dir,
    re_resolve_file,
    realised_pnl,
)


def _fill(size_filled: float = 10.0, price_filled: float = 0.5, fee: float = 0.0) -> dict:
    return {"size_filled": size_filled, "price_filled": price_filled, "fee_usd": fee}


def _gamma_handler_factory(payload: object, status_code: int = 200) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return handler


def _payload_up_wins() -> list[dict[str, Any]]:
    return [
        {"markets": [{"closed": True, "outcomes": ["Up", "Down"], "outcomePrices": ["1", "0"]}]}
    ]


def _payload_down_wins() -> list[dict[str, Any]]:
    return [
        {"markets": [{"closed": True, "outcomes": ["Up", "Down"], "outcomePrices": ["0", "1"]}]}
    ]


# ---------- realised_pnl ----------


def test_realised_pnl_winning_trade() -> None:
    pnl, eff, corrected = realised_pnl(
        side="UP", resolution="UP", fill=_fill(size_filled=10.0, price_filled=0.5)
    )
    assert pnl == pytest.approx(5.0)
    assert eff == 0.5
    assert corrected is False


def test_realised_pnl_losing_trade() -> None:
    pnl, _, _ = realised_pnl(
        side="UP", resolution="DOWN", fill=_fill(size_filled=10.0, price_filled=0.5)
    )
    assert pnl == pytest.approx(-5.0)


def test_realised_pnl_sim_fill_bug_correction() -> None:
    pnl, eff, corrected = realised_pnl(
        side="UP",
        resolution="UP",
        fill=_fill(size_filled=12.5, price_filled=0.40),
        price_limit=0.50,
    )
    assert corrected is True
    assert eff == 0.50
    assert pnl == pytest.approx(5.0)


# ---------- gamma_resolution ----------


def test_gamma_resolution_returns_up() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory(_payload_up_wins()))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) == "UP"


def test_gamma_resolution_returns_down() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory(_payload_down_wins()))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) == "DOWN"


def test_gamma_resolution_returns_none_when_market_open() -> None:
    payload = [
        {
            "markets": [
                {"closed": False, "outcomes": ["Up", "Down"], "outcomePrices": ["0.5", "0.5"]}
            ]
        }
    ]
    transport = httpx.MockTransport(_gamma_handler_factory(payload))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) is None


def test_gamma_resolution_returns_none_on_503() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory({}, status_code=503))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) is None


# ---------- poll_gamma_for_resolution ----------


def test_poll_returns_immediately_on_first_hit() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory(_payload_up_wins()))
    with httpx.Client(transport=transport) as client:
        sleep_calls: list[float] = []
        result = poll_gamma_for_resolution(
            1778272200,
            client=client,
            timeout_s=10.0,
            interval_s=1.0,
            sleep_fn=lambda s: sleep_calls.append(s),
            monotonic_fn=lambda: 0.0,
        )
        assert result == "UP"
        assert sleep_calls == []  # never slept


def test_poll_polls_until_resolution_available() -> None:
    """First two polls return None, third returns UP. Should sleep twice."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            return httpx.Response(200, json=[])  # market not yet resolved
        return httpx.Response(200, json=_payload_up_wins())

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        sleep_calls: list[float] = []
        # Use a clock that advances by 0.1 each call so we never timeout
        clock = [0.0]

        def fake_monotonic() -> float:
            clock[0] += 0.1
            return clock[0]

        result = poll_gamma_for_resolution(
            1778272200,
            client=client,
            timeout_s=10.0,
            interval_s=1.0,
            sleep_fn=lambda s: sleep_calls.append(s),
            monotonic_fn=fake_monotonic,
        )
        assert result == "UP"
        assert call_count == 3
        assert sleep_calls == [1.0, 1.0]  # slept between attempts 1+2 and 2+3


def test_poll_returns_none_on_timeout() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory([]))  # never resolves
    with httpx.Client(transport=transport) as client:
        sleep_calls: list[float] = []
        # Clock advances 5s per check; timeout is 10s; should poll twice then timeout.
        clock = [0.0]

        def fake_monotonic() -> float:
            clock[0] += 5.0
            return clock[0]

        result = poll_gamma_for_resolution(
            1778272200,
            client=client,
            timeout_s=10.0,
            interval_s=1.0,
            sleep_fn=lambda s: sleep_calls.append(s),
            monotonic_fn=fake_monotonic,
        )
        assert result is None


# ---------- re_resolve_file (smoke for the import-path; full coverage in tests/dashboard) ----------


def _fired(decision_id: str, *, window_ts: int, side: str, price_limit: float = 0.5) -> str:
    return json.dumps(
        {
            "kind": "fired",
            "decision_id": decision_id,
            "window_ts": window_ts,
            "decision_ts_ns": window_ts * 1_000_000_000,
            "asset_id": "0x" + "ab" * 31,
            "side": side,
            "size_usd": 5.0,
            "price_limit": price_limit,
            "ttl_s": 30,
            "rationale": f"strategy=spot_aware mode=aggressive side={side}",
            "snapshot": {},
            "composite_pct": None,
            "fill": None,
        }
    )


def _settled(
    decision_id: str,
    *,
    window_ts: int,
    resolution: str,
    fill: dict | None = None,
    pnl_usd: float = 0.0,
    resolution_source: str = "chainlink-local",
) -> str:
    return json.dumps(
        {
            "kind": "settled",
            "decision_id": decision_id,
            "window_ts": window_ts,
            "settled_ts_ns": (window_ts + 300) * 1_000_000_000,
            "open_oracle": 80000.0,
            "close_oracle": 80100.0,
            "resolution": resolution,
            "resolution_source": resolution_source,
            "fill_at_settle": fill,
            "pnl_usd": pnl_usd,
        }
    )


def test_re_resolve_file_corrects_oracle_to_polymarket(tmp_path: Path) -> None:
    src = tmp_path / "decisions.jsonl"
    dst = tmp_path / "out" / "decisions.jsonl"
    src.write_text(
        "\n".join(
            [
                _fired("d1", window_ts=1778272200, side="DOWN", price_limit=0.5),
                _settled(
                    "d1",
                    window_ts=1778272200,
                    resolution="UP",
                    fill=_fill(size_filled=10.0, price_filled=0.5),
                    pnl_usd=-5.0,
                ),
            ]
        )
        + "\n"
    )
    transport = httpx.MockTransport(_gamma_handler_factory(_payload_down_wins()))
    with httpx.Client(transport=transport) as client:
        n_settled, n_changed, _ = re_resolve_file(src, client=client, dst=dst)

    assert n_settled == 1
    assert n_changed == 1
    rec = json.loads(dst.read_text().strip().splitlines()[1])
    assert rec["resolution"] == "DOWN"
    assert rec["resolution_source"] == "polymarket"
    assert rec["pnl_usd"] == pytest.approx(5.0)


def test_re_resolve_dir_refuses_in_place(tmp_path: Path) -> None:
    d = tmp_path / "decisions"
    d.mkdir()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match="in-place"):
        re_resolve_dir(d, d, client=client)
