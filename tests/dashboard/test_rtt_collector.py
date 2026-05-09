"""Tests for polymarket_bot.dashboard.rtt_collector.

Tests run on the rotation logic and the file-write tick — the actual
HTTP pings are exercised end-to-end on the VPS at deploy time. Per
design/dashboard-v2.md §10.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from polymarket_bot.dashboard.provider_rtt import PROVIDERS
from polymarket_bot.dashboard.rtt_collector import _rotate, _tick


def test_rotate_keeps_only_last_n(tmp_path: Path) -> None:
    f = tmp_path / "provider_rtt.jsonl"
    f.write_text("\n".join(f"line-{i}" for i in range(100)) + "\n")
    _rotate(f, keep_lines=10)
    lines = f.read_text().splitlines()
    assert len(lines) == 10
    assert lines[-1] == "line-99"
    assert lines[0] == "line-90"


def test_rotate_handles_missing_file(tmp_path: Path) -> None:
    f = tmp_path / "missing.jsonl"
    _rotate(f, keep_lines=10)
    assert not f.exists()


@pytest.mark.asyncio
async def test_tick_writes_one_line_per_provider(tmp_path: Path) -> None:
    out = tmp_path / "provider_rtt.jsonl"
    fake_client = AsyncMock()
    with patch(
        "polymarket_bot.dashboard.rtt_collector._ping_one",
        new=AsyncMock(return_value=(123.4, 200)),
    ):
        await _tick(fake_client, out)
    lines = out.read_text().strip().split("\n")
    assert len(lines) == len(PROVIDERS)
    parsed = [json.loads(line) for line in lines]
    assert {p["provider"] for p in parsed} == {p.name for p in PROVIDERS}
    for p in parsed:
        assert p["rtt_ms"] == 123.4
        assert p["status_code"] == 200
        assert p["ok"] is True


@pytest.mark.asyncio
async def test_tick_records_failures_as_ok_false(tmp_path: Path) -> None:
    out = tmp_path / "provider_rtt.jsonl"
    fake_client = AsyncMock()
    with patch(
        "polymarket_bot.dashboard.rtt_collector._ping_one",
        new=AsyncMock(return_value=(None, None)),
    ):
        await _tick(fake_client, out)
    parsed = [json.loads(line) for line in out.read_text().strip().split("\n")]
    for p in parsed:
        assert p["rtt_ms"] is None
        assert p["status_code"] is None
        assert p["ok"] is False


@pytest.mark.asyncio
async def test_tick_appends_not_overwrites(tmp_path: Path) -> None:
    out = tmp_path / "provider_rtt.jsonl"
    out.write_text("preexisting\n")
    fake_client = AsyncMock()
    with patch(
        "polymarket_bot.dashboard.rtt_collector._ping_one",
        new=AsyncMock(return_value=(50.0, 200)),
    ):
        await _tick(fake_client, out)
    lines = out.read_text().splitlines()
    assert lines[0] == "preexisting"
    assert len(lines) == 1 + len(PROVIDERS)
