"""Tests for polymarket_bot._live.mm_alerts payload constructors.

Each constructor must produce a dict that the existing alerter formatter
(`polymarket_bot._live.alerter.formatter.format_alert`) renders correctly
(prefix + source + message). Level + source fields drive the formatter's
prefix selection; message content is what reaches Telegram.
"""

from __future__ import annotations

from polymarket_bot._live.alerter.formatter import format_alert
from polymarket_bot._live.mm_alerts import (
    ALERT_SOURCE,
    mm_daily_loss_tripped_alert,
    mm_first_fill_confirmed_alert,
    mm_halt_engaged_alert,
    mm_heartbeat_missed_alert,
    mm_kill_switch_alert,
    mm_place_failed_alert,
)


def test_heartbeat_missed_is_critical() -> None:
    p = mm_heartbeat_missed_alert(consecutive_misses=2)
    assert p["level"] == "critical"
    assert p["source"] == ALERT_SOURCE
    assert "2x" in p["message"]
    formatted = format_alert(p)
    assert formatted is not None
    assert "CRITICAL" in formatted
    assert ALERT_SOURCE in formatted


def test_daily_loss_tripped_is_critical_and_includes_amounts() -> None:
    p = mm_daily_loss_tripped_alert(realized_pnl_usd=-55.0, cap_usd=50.0)
    assert p["level"] == "critical"
    # `${value:+.2f}` formats negative values as `$-55.00` (sign after $).
    assert "$-55.00" in p["message"]
    assert "$50.00" in p["message"]
    formatted = format_alert(p)
    assert formatted is not None
    assert "CRITICAL" in formatted


def test_kill_switch_is_critical_and_includes_reason() -> None:
    p = mm_kill_switch_alert(reason="operator-cli")
    assert p["level"] == "critical"
    assert "operator-cli" in p["message"]


def test_halt_engaged_is_error_not_critical() -> None:
    """Operator-initiated halts are ERROR severity, not CRITICAL — the bot
    is stopping deliberately, not on a circuit trip."""
    p = mm_halt_engaged_alert(reason="manual restart")
    assert p["level"] == "error"
    formatted = format_alert(p)
    assert formatted is not None
    assert "ERROR" in formatted


def test_place_failed_is_warn() -> None:
    p = mm_place_failed_alert(
        market_id="m1",
        side="UP",
        price=0.40,
        error_code="INVALID_ORDER_MIN_TICK_SIZE",
        error_msg="tick must be 0.01",
    )
    assert p["level"] == "warn"
    assert "INVALID_ORDER_MIN_TICK_SIZE" in p["message"]


def test_first_fill_confirmed_is_warn() -> None:
    """First fill is informational-but-important — WARN level so it reaches
    Telegram (INFO is dropped by the formatter)."""
    p = mm_first_fill_confirmed_alert(
        market_id="m1",
        side="UP",
        fill_price=0.40,
        fill_size_shares=25.0,
    )
    assert p["level"] == "warn"
    formatted = format_alert(p)
    assert formatted is not None
    assert "WARN" in formatted
    assert "first fill" in formatted.lower()


def test_all_payloads_have_mmbot_source() -> None:
    """Every MMB alert must carry source=mm-bot so operators can filter."""
    payloads = [
        mm_heartbeat_missed_alert(consecutive_misses=2),
        mm_daily_loss_tripped_alert(realized_pnl_usd=-55.0, cap_usd=50.0),
        mm_kill_switch_alert(reason="x"),
        mm_halt_engaged_alert(reason="x"),
        mm_place_failed_alert(market_id="m", side="UP", price=0.1, error_code="x", error_msg="x"),
        mm_first_fill_confirmed_alert(
            market_id="m", side="UP", fill_price=0.1, fill_size_shares=1.0
        ),
    ]
    for p in payloads:
        assert p["source"] == "mm-bot"
        assert p["level"] in ("critical", "error", "warn")
