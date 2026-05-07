"""Protocols for the alerts producer side: AlertSink and Clock.

`AlertSink` is the surface every bot runtime publishes through. Implementations
MUST be synchronous and MUST NOT raise — alerts are best-effort observability
and the trading hot path must never block on Redis being slow or down. The
`Clock` protocol exists so tests can inject a deterministic ns clock; the
default in production is `time.time_ns`.
"""

from __future__ import annotations

from typing import Protocol

from polymarket_bot.alerts.types import Alert


class AlertSink(Protocol):
    def publish(self, alert: Alert) -> None: ...

    def close(self) -> None: ...


class Clock(Protocol):
    def __call__(self) -> int: ...
