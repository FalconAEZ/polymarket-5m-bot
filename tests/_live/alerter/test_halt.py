"""Halt sentinel: atomic write + presence check."""

from __future__ import annotations

import json
from pathlib import Path

from polymarket_bot._live.alerter.halt import halt_sentinel_present, write_halt_sentinel


def test_write_creates_sentinel(tmp_path: Path) -> None:
    target = tmp_path / "halt.sentinel"
    assert not halt_sentinel_present(target)
    write_halt_sentinel("operator request", 12345, path=target)
    assert halt_sentinel_present(target)
    payload = json.loads(target.read_text())
    assert payload["halted_at_ns"] == 12345
    assert payload["reason"] == "operator request"
    assert payload["halted_by"] == "telegram-/halt"


def test_atomic_rename_no_tmp_left(tmp_path: Path) -> None:
    target = tmp_path / "halt.sentinel"
    write_halt_sentinel("op", 1, path=target)
    tmp = target.with_suffix(target.suffix + ".tmp")
    # tmp file must not linger after a successful atomic rename
    assert not tmp.exists()
    assert target.exists()


def test_overwrite_replaces_existing(tmp_path: Path) -> None:
    target = tmp_path / "halt.sentinel"
    write_halt_sentinel("first", 1, path=target)
    write_halt_sentinel("second", 2, path=target)
    payload = json.loads(target.read_text())
    assert payload["halted_at_ns"] == 2
    assert payload["reason"] == "second"
