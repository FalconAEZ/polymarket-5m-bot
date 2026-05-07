"""NullAlertSink — drops every Alert silently. Default in tests + backtest.

Used by every code path that doesn't have a real Redis. design/alerter.md §3.2
mandates synchronous, never-raises semantics for any AlertSink; this is the
trivial implementation. The dashboard, every backtest replay, and every unit
test that constructs PaperRunner without explicitly wiring a sink end up with
this — by design, so observability is opt-in, not accidental.
"""

from __future__ import annotations

from polymarket_bot.alerts.types import Alert


class NullAlertSink:
    def publish(self, alert: Alert) -> None:
        return None

    def close(self) -> None:
        return None
