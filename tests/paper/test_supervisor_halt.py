"""Halt-watcher in scripts/run_paper.py: sentinel sets stop_event within 1s."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _load_run_paper() -> object:
    """Load scripts/run_paper.py as a module; can't use a package import."""
    spec = importlib.util.spec_from_file_location(
        "run_paper_for_test",
        ROOT / "scripts" / "run_paper.py",
    )
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.asyncio
async def test_halt_watcher_sets_stop_when_sentinel_appears(tmp_path: Path) -> None:
    run_paper = _load_run_paper()
    sentinel = tmp_path / "halt.sentinel"
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_paper._halt_watcher(stop, sentinel=sentinel, interval_s=0.05)  # type: ignore[attr-defined]
    )
    # No sentinel yet; watcher must keep going.
    await asyncio.sleep(0.15)
    assert not stop.is_set()

    # Drop the sentinel; watcher must observe it within ~1 tick.
    sentinel.write_text('{"halted_at_ns": 1, "halted_by": "test", "reason": "x"}')
    await asyncio.wait_for(stop.wait(), timeout=1.0)
    assert stop.is_set()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_halt_watcher_treats_corrupt_json_as_halt(tmp_path: Path) -> None:
    run_paper = _load_run_paper()
    sentinel = tmp_path / "halt.sentinel"
    sentinel.write_text("not-json{{{")
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_paper._halt_watcher(stop, sentinel=sentinel, interval_s=0.05)  # type: ignore[attr-defined]
    )
    # Even with corrupt content, presence is the signal.
    await asyncio.wait_for(stop.wait(), timeout=1.0)
    assert stop.is_set()
    await asyncio.wait_for(task, timeout=1.0)


@pytest.mark.asyncio
async def test_halt_watcher_exits_when_stop_set_externally(tmp_path: Path) -> None:
    run_paper = _load_run_paper()
    sentinel = tmp_path / "halt.sentinel"
    stop = asyncio.Event()
    task = asyncio.create_task(
        run_paper._halt_watcher(stop, sentinel=sentinel, interval_s=0.05)  # type: ignore[attr-defined]
    )
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
