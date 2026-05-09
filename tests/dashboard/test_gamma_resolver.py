"""Unit tests for polymarket_bot.dashboard.gamma_resolver.

The functions are pure given an httpx.Client — we use httpx.MockTransport
to avoid any real network I/O. Coverage:
  * realised_pnl winning + losing + sim-fill-bug-correction paths
  * gamma_resolution: closed UP, closed DOWN, not-closed, missing market,
    HTTP error
  * re_resolve_file: skips already-polymarket records, corrects oracle
    truth → polymarket truth, recomputes pnl, atomic write to dst dir
  * re_resolve_dir: refuses in-place writes (orphan-FD-decisions defense)
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from polymarket_bot.dashboard.gamma_resolver import (
    gamma_resolution,
    re_resolve_dir,
    re_resolve_file,
    realised_pnl,
)

# ---------- realised_pnl ----------


def _fill(size_filled: float = 10.0, price_filled: float = 0.5, fee: float = 0.0) -> dict:
    return {"size_filled": size_filled, "price_filled": price_filled, "fee_usd": fee}


def test_realised_pnl_winning_trade_no_fee() -> None:
    pnl, eff_price, corrected = realised_pnl(
        side="UP", resolution="UP", fill=_fill(size_filled=10.0, price_filled=0.5)
    )
    # 10 shares * $1 payout - 10 * $0.5 cost = $5
    assert pnl == pytest.approx(5.0)
    assert eff_price == 0.5
    assert corrected is False


def test_realised_pnl_losing_trade_no_fee() -> None:
    pnl, _eff_price, corrected = realised_pnl(
        side="UP", resolution="DOWN", fill=_fill(size_filled=10.0, price_filled=0.5)
    )
    # 0 payout - 10 * $0.5 cost = -$5
    assert pnl == pytest.approx(-5.0)
    assert corrected is False


def test_realised_pnl_includes_fee() -> None:
    pnl, _, _ = realised_pnl(
        side="UP",
        resolution="UP",
        fill=_fill(size_filled=10.0, price_filled=0.5, fee=0.01),
    )
    assert pnl == pytest.approx(5.0 - 0.01)


def test_realised_pnl_sim_fill_bug_correction_triggers_above_threshold() -> None:
    # logged price (0.40) is more than 5¢ below limit (0.50) → correct to limit
    pnl, eff_price, corrected = realised_pnl(
        side="UP",
        resolution="UP",
        fill=_fill(size_filled=12.5, price_filled=0.40),
        price_limit=0.50,
    )
    # Stake preserved at $5; corrected size = 5/0.5 = 10; payout = 10; pnl = 5
    assert eff_price == 0.50
    assert corrected is True
    assert pnl == pytest.approx(5.0)


def test_realised_pnl_does_not_correct_within_threshold() -> None:
    # 0.48 is only 2¢ below 0.50 — under the 5¢ threshold; leave as-is.
    pnl, eff_price, corrected = realised_pnl(
        side="UP",
        resolution="UP",
        fill=_fill(size_filled=10.0, price_filled=0.48),
        price_limit=0.50,
    )
    assert corrected is False
    assert eff_price == 0.48
    # 10 shares * $1 - 10 * $0.48 = $5.20
    assert pnl == pytest.approx(5.20)


# ---------- gamma_resolution ----------


def _gamma_handler_factory(payload: object, status_code: int = 200) -> callable:
    """Returns an httpx.MockTransport handler that replies with payload."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return handler


def test_gamma_resolution_returns_up_when_up_outcome_priced_one() -> None:
    payload = [
        {
            "markets": [
                {
                    "closed": True,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["1", "0"],
                }
            ]
        }
    ]
    transport = httpx.MockTransport(_gamma_handler_factory(payload))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) == "UP"


def test_gamma_resolution_returns_down_when_down_outcome_priced_one() -> None:
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
    transport = httpx.MockTransport(_gamma_handler_factory(payload))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) == "DOWN"


def test_gamma_resolution_returns_none_when_market_not_closed() -> None:
    payload = [
        {
            "markets": [
                {
                    "closed": False,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["0.5", "0.5"],
                }
            ]
        }
    ]
    transport = httpx.MockTransport(_gamma_handler_factory(payload))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) is None


def test_gamma_resolution_returns_none_when_no_market_found() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory([]))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) is None


def test_gamma_resolution_returns_none_on_non_200() -> None:
    transport = httpx.MockTransport(_gamma_handler_factory({}, status_code=503))
    with httpx.Client(transport=transport) as client:
        assert gamma_resolution(1778272200, client=client) is None


# ---------- re_resolve_file ----------


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


def test_re_resolve_file_skips_already_polymarket_resolved(tmp_path: Path) -> None:
    """If resolution_source is 'polymarket' AND there's no fill to recompute,
    we should not hit Gamma at all."""
    src = tmp_path / "decisions.jsonl"
    dst = tmp_path / "out" / "decisions.jsonl"
    src.write_text(
        "\n".join(
            [
                _fired("d1", window_ts=1778272200, side="UP"),
                _settled(
                    "d1",
                    window_ts=1778272200,
                    resolution="UP",
                    fill=None,
                    resolution_source="polymarket",
                ),
            ]
        )
        + "\n"
    )

    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json=[])

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        n_settled, n_changed, n_unresolvable = re_resolve_file(src, client=client, dst=dst)

    assert n_settled == 1
    assert n_changed == 0
    assert n_unresolvable == 0
    assert call_count == 0  # never hit Gamma


def test_re_resolve_file_corrects_oracle_to_polymarket_truth(tmp_path: Path) -> None:
    """Oracle says UP, Polymarket says DOWN; resolution + pnl get rewritten."""
    src = tmp_path / "decisions.jsonl"
    dst = tmp_path / "out" / "decisions.jsonl"
    fill = _fill(size_filled=10.0, price_filled=0.5, fee=0.0)
    src.write_text(
        "\n".join(
            [
                _fired("d1", window_ts=1778272200, side="DOWN", price_limit=0.5),
                _settled(
                    "d1",
                    window_ts=1778272200,
                    resolution="UP",
                    fill=fill,
                    pnl_usd=-5.0,  # the wrong oracle PnL
                ),
            ]
        )
        + "\n"
    )

    payload = [
        {
            "markets": [
                {
                    "closed": True,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["0", "1"],  # DOWN won
                }
            ]
        }
    ]
    transport = httpx.MockTransport(_gamma_handler_factory(payload))
    with httpx.Client(transport=transport) as client:
        n_settled, n_changed, n_unresolvable = re_resolve_file(src, client=client, dst=dst)

    assert n_settled == 1
    assert n_changed == 1
    assert n_unresolvable == 0

    # Read back the corrected JSONL
    out_lines = dst.read_text().strip().splitlines()
    settled_rec = json.loads(out_lines[1])
    assert settled_rec["kind"] == "settled"
    assert settled_rec["resolution"] == "DOWN"
    assert settled_rec["resolution_source"] == "polymarket"
    assert settled_rec["resolution_oracle_local"] == "UP"
    # Side was DOWN, resolution now DOWN → pnl positive
    assert settled_rec["pnl_usd"] == pytest.approx(5.0)


def test_re_resolve_file_handles_no_fill(tmp_path: Path) -> None:
    """Unfilled trade: resolution still gets corrected; pnl untouched (0.0)."""
    src = tmp_path / "decisions.jsonl"
    dst = tmp_path / "out" / "decisions.jsonl"
    src.write_text(
        "\n".join(
            [
                _fired("d1", window_ts=1778272200, side="UP"),
                _settled(
                    "d1",
                    window_ts=1778272200,
                    resolution="DOWN",  # oracle wrong
                    fill=None,
                    pnl_usd=0.0,
                ),
            ]
        )
        + "\n"
    )
    payload = [
        {
            "markets": [
                {
                    "closed": True,
                    "outcomes": ["Up", "Down"],
                    "outcomePrices": ["1", "0"],  # UP won
                }
            ]
        }
    ]
    transport = httpx.MockTransport(_gamma_handler_factory(payload))
    with httpx.Client(transport=transport) as client:
        _n_settled, n_changed, _ = re_resolve_file(src, client=client, dst=dst)

    out_lines = dst.read_text().strip().splitlines()
    settled_rec = json.loads(out_lines[1])
    assert settled_rec["resolution"] == "UP"
    assert settled_rec["resolution_source"] == "polymarket"
    assert settled_rec["pnl_usd"] == 0.0
    assert n_changed == 1


# ---------- re_resolve_dir ----------


def test_re_resolve_dir_refuses_in_place(tmp_path: Path) -> None:
    """src_dir == dst_dir is the orphan-FD-decisions failure mode."""
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "x.jsonl").write_text("")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as client, pytest.raises(ValueError, match="in-place"):
        re_resolve_dir(d, d, client=client)


def test_re_resolve_dir_processes_all_jsonl(tmp_path: Path) -> None:
    src = tmp_path / "raw"
    dst = tmp_path / "cooked"
    src.mkdir()
    for i, day in enumerate(("2026-05-08", "2026-05-09")):
        (src / f"{day}.jsonl").write_text(
            "\n".join(
                [
                    _fired(f"d{i}", window_ts=1778272200 + i, side="UP"),
                    _settled(
                        f"d{i}",
                        window_ts=1778272200 + i,
                        resolution="UP",
                        fill=None,
                        resolution_source="polymarket",
                    ),
                ]
            )
            + "\n"
        )
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as client:
        n_settled, n_changed, _ = re_resolve_dir(src, dst, client=client)

    assert n_settled == 2
    assert n_changed == 0
    assert (dst / "2026-05-08.jsonl").exists()
    assert (dst / "2026-05-09.jsonl").exists()


def test_re_resolve_dir_skips_bak_and_tmp_files(tmp_path: Path) -> None:
    src = tmp_path / "raw"
    dst = tmp_path / "cooked"
    src.mkdir()
    (src / "real.jsonl").write_text("")
    (src / "real.jsonl.bak").write_text("garbage")
    (src / "real.jsonl.tmp").write_text("garbage")
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[]))
    with httpx.Client(transport=transport) as client:
        n_settled, _, _ = re_resolve_dir(src, dst, client=client)
    assert n_settled == 0  # only real.jsonl, which has no settled records
    assert (dst / "real.jsonl").exists()
    assert not (dst / "real.jsonl.bak").exists()
    assert not (dst / "real.jsonl.tmp").exists()
