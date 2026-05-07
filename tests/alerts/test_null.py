"""NullAlertSink is a literal no-op."""

from __future__ import annotations

from polymarket_bot.alerts import Alert, Level, NullAlertSink


def test_null_sink_publish_is_noop() -> None:
    sink = NullAlertSink()
    sink.publish(Alert(level=Level.CRITICAL, message="x", ts_ns=0, source="t"))
    sink.close()
    # No assertion target other than: nothing raised, nothing observable.


def test_null_sink_many_publishes_never_raise() -> None:
    sink = NullAlertSink()
    for i in range(100):
        sink.publish(Alert(level=Level.INFO, message=f"m{i}", ts_ns=i, source="t"))
    sink.close()
