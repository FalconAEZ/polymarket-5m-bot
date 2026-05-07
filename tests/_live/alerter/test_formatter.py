"""Formatter: INFO drops; WARN/ERROR/CRITICAL render; coalesce path."""

from __future__ import annotations

from polymarket_bot._live.alerter.formatter import (
    COALESCE_THRESHOLD,
    CRITICAL_PREFIX,
    ERROR_PREFIX,
    WARN_PREFIX,
    format_alert,
    format_coalesced,
)


def _payload(level: str, message: str = "x", source: str = "bot-staging") -> dict[str, object]:
    return {"level": level, "message": message, "ts_ns": 1, "source": source, "fields": {}}


def test_info_returns_none() -> None:
    assert format_alert(_payload("info")) is None


def test_warn_renders_with_prefix() -> None:
    out = format_alert(_payload("warn", "binance reconnect"))
    assert out is not None
    assert out.startswith(WARN_PREFIX)
    assert "binance reconnect" in out


def test_error_renders_with_prefix() -> None:
    out = format_alert(_payload("error", "feed crashed"))
    assert out is not None
    assert out.startswith(ERROR_PREFIX)


def test_critical_renders_with_prefix() -> None:
    out = format_alert(_payload("critical", "shutdown imminent"))
    assert out is not None
    assert out.startswith(CRITICAL_PREFIX)
    assert "shutdown imminent" in out


def test_unknown_level_returns_none() -> None:
    assert format_alert(_payload("trace")) is None


def test_malformed_payload_returns_none() -> None:
    assert format_alert({"level": 5, "message": "x"}) is None  # type: ignore[arg-type]
    assert format_alert({"message": "x"}) is None
    assert format_alert({"level": "warn"}) is None


def test_format_coalesced_threshold() -> None:
    payloads = [_payload("warn", f"m{i}") for i in range(COALESCE_THRESHOLD)]
    out = format_coalesced(payloads, window_ms=5000)
    assert "3 alerts" in out
    assert "5000ms" in out
    assert "decision log" in out
