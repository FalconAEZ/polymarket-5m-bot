"""Producer types: Alert dataclass shape + Level enum encoding."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from polymarket_bot.alerts import Alert, Level


def test_level_is_str_enum_with_lowercase_values() -> None:
    assert str(Level.INFO) == "info"
    assert str(Level.WARN) == "warn"
    assert str(Level.ERROR) == "error"
    assert str(Level.CRITICAL) == "critical"
    # JSON-encodable directly because it's a StrEnum.
    assert json.dumps(Level.CRITICAL) == '"critical"'


def test_alert_is_frozen() -> None:
    a = Alert(level=Level.WARN, message="x", ts_ns=1, source="t", fields={})
    with pytest.raises(FrozenInstanceError):
        a.message = "y"  # type: ignore[misc]


def test_alert_default_fields_is_empty_mapping() -> None:
    a = Alert(level=Level.INFO, message="hi", ts_ns=1, source="t")
    assert dict(a.fields) == {}


def test_alert_fields_preserve_str_int_float() -> None:
    a = Alert(
        level=Level.ERROR,
        message="x",
        ts_ns=2,
        source="t",
        fields={"reason": "boom", "count": 3, "ratio": 0.5},
    )
    assert a.fields["count"] == 3
    assert a.fields["ratio"] == 0.5
    assert a.fields["reason"] == "boom"
