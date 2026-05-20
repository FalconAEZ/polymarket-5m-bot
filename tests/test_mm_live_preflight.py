"""Tests for scripts/run_mm_live.py preflight checks.

These are sync, pure helpers — exercise them without spinning up the
asyncio main loop or any CLOB I/O. The full live entrypoint is
operator-supervised in S.5; this gives us coverage on the gates that
prevent it from going live by accident.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

# Make scripts/ importable as a package. The importlib indirection below
# avoids E402-triggering module-level import-after-statement; sys.path
# must be mutated before the load.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
run_mm_live = __import__("run_mm_live")


def test_env_confirm_default_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MM_LIVE_CONFIRM", raising=False)
    assert run_mm_live._check_env_confirm() is False


def test_env_confirm_explicit_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM_LIVE_CONFIRM", "yes")
    assert run_mm_live._check_env_confirm() is True


def test_env_confirm_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MM_LIVE_CONFIRM", "YES")
    assert run_mm_live._check_env_confirm() is True


def test_env_confirm_rejects_other_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("true", "1", "y", "confirm"):
        monkeypatch.setenv("MM_LIVE_CONFIRM", v)
        assert run_mm_live._check_env_confirm() is False, v


def test_halt_sentinel_present_blocks(tmp_path: Path) -> None:
    sentinel = tmp_path / "halt.sentinel"
    sentinel.write_text("{}")
    assert run_mm_live._check_halt_sentinel(sentinel) is False


def test_halt_sentinel_absent_passes(tmp_path: Path) -> None:
    sentinel = tmp_path / "halt.sentinel"
    assert run_mm_live._check_halt_sentinel(sentinel) is True


def test_allowance_missing_audit_file_fails(tmp_path: Path) -> None:
    assert run_mm_live._check_allowance(tmp_path / "no-such-file.json") is False


def test_allowance_stale_audit_fails(tmp_path: Path) -> None:
    """Audit older than 24h is rejected even if it showed sufficient."""
    audit = tmp_path / "mm-allowance.json"
    payload = {
        "ts_unix": int(time.time()) - 100_000,  # 27.7h ago
        "snapshot": {"allowance_usd": 10_000.0},
    }
    audit.write_text(json.dumps(payload))
    assert run_mm_live._check_allowance(audit) is False


def test_allowance_recent_sufficient_passes(tmp_path: Path) -> None:
    audit = tmp_path / "mm-allowance.json"
    payload = {
        "ts_unix": int(time.time()) - 60,  # 1 min ago
        "snapshot": {"allowance_usd": 5_000.0},
    }
    audit.write_text(json.dumps(payload))
    assert run_mm_live._check_allowance(audit, min_usd=1_000.0) is True


def test_allowance_recent_insufficient_fails(tmp_path: Path) -> None:
    audit = tmp_path / "mm-allowance.json"
    payload = {
        "ts_unix": int(time.time()),
        "snapshot": {"allowance_usd": 50.0},
    }
    audit.write_text(json.dumps(payload))
    assert run_mm_live._check_allowance(audit, min_usd=100.0) is False


def test_clob_creds_all_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE", "PK_SIGNER", "POLY_FUNDER"):
        monkeypatch.setenv(k, "test-value")
    assert run_mm_live._check_clob_creds() is True
    # Drop any one → fail.
    monkeypatch.delenv("PK_SIGNER", raising=False)
    assert run_mm_live._check_clob_creds() is False


def test_preflight_aggregates_all_checks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Each missing requirement returns its specific reason; success is unanimous."""
    sentinel = tmp_path / "halt.sentinel"
    audit = tmp_path / "mm-allowance.json"

    # 1) Default: MM_LIVE_CONFIRM not set.
    monkeypatch.delenv("MM_LIVE_CONFIRM", raising=False)
    ok, reason = run_mm_live._preflight(sentinel, audit)
    assert ok is False
    assert "MM_LIVE_CONFIRM" in reason

    # 2) Confirm set but sentinel present.
    monkeypatch.setenv("MM_LIVE_CONFIRM", "yes")
    sentinel.write_text("{}")
    ok, reason = run_mm_live._preflight(sentinel, audit)
    assert ok is False
    assert "halt sentinel" in reason

    # 3) Sentinel removed but no allowance audit.
    sentinel.unlink()
    ok, reason = run_mm_live._preflight(sentinel, audit)
    assert ok is False
    assert "allowance" in reason

    # 4) Allowance audit + missing creds.
    audit.write_text(
        json.dumps(
            {
                "ts_unix": int(time.time()),
                "snapshot": {"allowance_usd": 10_000.0},
            }
        )
    )
    monkeypatch.delenv("CLOB_API_KEY", raising=False)
    ok, reason = run_mm_live._preflight(sentinel, audit)
    assert ok is False
    assert "creds" in reason

    # 5) All requirements met → ok=True.
    for k in ("CLOB_API_KEY", "CLOB_API_SECRET", "CLOB_API_PASSPHRASE", "PK_SIGNER", "POLY_FUNDER"):
        monkeypatch.setenv(k, "test-value")
    ok, reason = run_mm_live._preflight(sentinel, audit)
    assert ok is True
    assert reason == "ok"
