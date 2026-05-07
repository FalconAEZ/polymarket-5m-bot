"""Format Alert dicts into human-readable Telegram strings.

design/alerter.md §5.3: INFO never reaches Telegram (drop), WARN/ERROR get a
plain prefix, CRITICAL gets a prominent marker. Coalescing of bursts (≥3
alerts in a short window) collapses into a single "N alerts in Ms — see
decision log" line so the operator's chat doesn't get spammed during a
feed-storm. The function operates on already-decoded dict payloads so the
caller doesn't need to import the producer Alert dataclass — the alerter is
process-local from the producer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

CRITICAL_PREFIX = "🚨 CRITICAL"
ERROR_PREFIX = "❌ ERROR"
WARN_PREFIX = "⚠️ WARN"

COALESCE_THRESHOLD = 3


def format_alert(payload: dict[str, Any]) -> str | None:
    """Render a single Alert dict into Telegram text.

    Returns None for INFO-level (operator-invisible) and for malformed payloads.
    """
    level = payload.get("level")
    message = payload.get("message")
    source = payload.get("source", "?")
    if not isinstance(level, str) or not isinstance(message, str):
        return None
    level_lc = level.lower()
    if level_lc == "info":
        return None
    if level_lc == "critical":
        prefix = CRITICAL_PREFIX
    elif level_lc == "error":
        prefix = ERROR_PREFIX
    elif level_lc == "warn":
        prefix = WARN_PREFIX
    else:
        return None
    return f"{prefix}  [{source}] {message}"


def format_coalesced(payloads: Sequence[dict[str, Any]], window_ms: int) -> str:
    """Render N≥COALESCE_THRESHOLD alerts as a single coalesced message."""
    return f"{len(payloads)} alerts in {window_ms}ms — see decision log"
