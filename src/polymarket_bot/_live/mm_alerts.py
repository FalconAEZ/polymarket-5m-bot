"""MMB alert payload constructors — render dicts the existing alerter formats.

Phase S Session 4 deliverable. Centralises MMB-specific Telegram message
templates so MmRunner + mm_heartbeat callers don't hand-format strings at
the emission site. The output is a `dict` payload in the shape
`polymarket_bot._live.alerter.formatter.format_alert` already understands:

    {"level": "critical"|"error"|"warn", "source": "mm-bot", "message": "..."}

The alerter formatter prefixes by level (🚨 / ❌ / ⚠️) and stamps the source.
INFO-level alerts are dropped by the formatter; this module never emits INFO.

Caller responsibility: push the dict onto the alerter Redis queue
(`polybot:alerts` per `_live/alerter/redis_queue.py`). The push itself is
left to the caller because (a) MmRunner shouldn't take a hard dependency
on redis-py in unit tests, and (b) heartbeat callers may want to push
synchronously while runner callers push via asyncio.to_thread.

Five alert kinds covered (one constructor per kind). All are CRITICAL or
WARN — MMB never emits INFO, which the formatter would drop anyway.
"""

from __future__ import annotations

from typing import Any, Final, Literal

ALERT_SOURCE: Final[str] = "mm-bot"

AlertPayload = dict[str, Any]
AlertLevel = Literal["critical", "error", "warn"]


def _payload(level: AlertLevel, message: str) -> AlertPayload:
    return {"level": level, "source": ALERT_SOURCE, "message": message}


def mm_heartbeat_missed_alert(*, consecutive_misses: int) -> AlertPayload:
    """CRITICAL: 2+ consecutive heartbeat failures → server will auto-cancel
    all open MMB orders within 5s (10s + 5s buffer per agent-skills)."""
    return _payload(
        "critical",
        f"Heartbeat failed {consecutive_misses}x in a row — halt sentinel written; "
        f"CLOB will auto-cancel open MMB orders within ~5s.",
    )


def mm_daily_loss_tripped_alert(*, realized_pnl_usd: float, cap_usd: float) -> AlertPayload:
    """CRITICAL: realized daily PnL exceeded the loss cap → bot halted."""
    return _payload(
        "critical",
        f"Daily loss cap tripped: realized ${realized_pnl_usd:+.2f} <= -${cap_usd:.2f}. "
        f"Halt sentinel written; MMB drained.",
    )


def mm_kill_switch_alert(*, reason: str) -> AlertPayload:
    """CRITICAL: MM_KILL_SWITCH env flipped (or operator-cli) → bot drained."""
    return _payload(
        "critical",
        f"MMB kill switch engaged ({reason}). Open orders drained; halt sentinel written.",
    )


def mm_halt_engaged_alert(*, reason: str) -> AlertPayload:
    """ERROR: bot is halting for a non-circuit-trip reason (e.g., operator-cli
    sentinel write, restart-during-cooldown). Lower severity than daily-loss
    + heartbeat-miss because it's typically operator-initiated."""
    return _payload(
        "error",
        f"MMB halt engaged: {reason}. New ladder placements suspended.",
    )


def mm_place_failed_alert(
    *,
    market_id: str,
    side: str,
    price: float,
    error_code: str | None,
    error_msg: str,
) -> AlertPayload:
    """WARN: a non-post-only CLOB error (tick, min-size, balance). Post-only
    rejections are NOT alerted — they're soft skips per S.1.1 §Q2."""
    return _payload(
        "warn",
        f"MMB place_failed market={market_id} side={side} price={price:.4f} "
        f"err={error_code or 'unknown'}: {error_msg}",
    )


def mm_first_fill_confirmed_alert(
    *,
    market_id: str,
    side: str,
    fill_price: float,
    fill_size_shares: float,
) -> AlertPayload:
    """WARN: the first confirmed fill of a session — operator wants to see
    this so they know the bot is taking real orders. Subsequent fills are
    NOT alerted to avoid noise."""
    return _payload(
        "warn",
        f"MMB first fill confirmed: market={market_id} side={side} "
        f"price={fill_price:.4f} shares={fill_size_shares:.2f}",
    )


# ---------------- Redis push helper ----------------


DEFAULT_REDIS_URL: Final[str] = "redis://localhost:6379"
DEFAULT_ALERTER_QUEUE: Final[str] = "polybot:alerts"


async def push_to_redis_alerter(
    payload: AlertPayload,
    *,
    redis_url: str = DEFAULT_REDIS_URL,
    queue_key: str = DEFAULT_ALERTER_QUEUE,
) -> None:
    """Best-effort push of an alert payload to the alerter's Redis queue.

    The drain side (tg-alerter.service / `_live/alerter/service.py`) BRPOPs
    from `polybot:alerts` and forwards to Telegram. We LPUSH so newest
    alerts get delivered first (Telegram chats tolerate the order).

    Alerts MUST NOT block trading. On any connection or serialization
    error, we log + swallow the exception. The on-disk halt sentinel is
    the authoritative safety signal; alerting is observability sugar.
    """
    import json
    import logging

    log = logging.getLogger("polymarket_bot._live.mm_alerts.push")
    try:
        # Import locally so unit tests that mock this function don't
        # require redis-py to be installed.
        from redis.asyncio import Redis
    except ImportError:
        log.error("redis-py not installed; cannot push MMB alert")
        return
    try:
        client = Redis.from_url(redis_url)
        # redis-py typing flags lpush as `Awaitable[int] | int`; we know
        # the async client returns the awaitable. Cast suppresses the misc.
        await client.lpush(queue_key, json.dumps(payload))  # type: ignore[misc]
        await client.aclose()
    except Exception:
        log.exception("MMB alert push failed (best-effort)")
