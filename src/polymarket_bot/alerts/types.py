"""Producer-side dataclass + enum for alerts emitted by bot runtimes.

Both `_paper.runner` and the future `_live` runtime publish `Alert` instances
through an `AlertSink`. The dataclass is frozen + slot-friendly so the queue
serializer in `redis_sink.py` has a stable JSON shape (level, message, ts_ns,
source, fields). `Level` is a StrEnum so that JSON serialisation gives
"info"/"warn"/"error"/"critical" directly without a custom encoder. UTC ns is
required at the producer site (locked decision #15 — UTC everywhere).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class Level(StrEnum):
    INFO = "info"
    WARN = "warn"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Alert:
    level: Level
    message: str
    ts_ns: int
    source: str
    fields: Mapping[str, str | int | float] = field(default_factory=dict)
