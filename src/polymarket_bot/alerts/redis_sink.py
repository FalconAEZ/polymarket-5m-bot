"""RedisAlertSink — LPUSH JSON-encoded Alert onto a Redis list.

Synchronous, never raises. design/alerter.md §3.2 + §3.3: the producer is
on the bot's hot path; a Redis hiccup must not propagate into the trading
loop. On any redis-py exception, the alert is logged at WARN to the bot's
own journal and dropped. The consumer (`_live.alerter` daemon) BRPOPs the
same key. Wire format is `dataclasses.asdict(alert)` minus the StrEnum
indirection (Level is a string at the wire level — covered by the types
module's StrEnum choice).
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from polymarket_bot.alerts.types import Alert

if TYPE_CHECKING:
    from redis import Redis as _RedisClient

LOG = logging.getLogger("polymarket_bot.alerts.redis_sink")

DEFAULT_QUEUE_KEY = "polybot:alerts"


def _alert_to_json(alert: Alert) -> str:
    payload: dict[str, Any] = {
        "level": str(alert.level),
        "message": alert.message,
        "ts_ns": alert.ts_ns,
        "source": alert.source,
        "fields": dict(alert.fields),
    }
    return json.dumps(payload, separators=(",", ":"))


class RedisAlertSink:
    """Publish Alerts to a Redis list. Sync, never raises."""

    def __init__(
        self,
        *,
        url: str,
        queue_key: str = DEFAULT_QUEUE_KEY,
        source: str = "bot",
        client: _RedisClient | None = None,
    ) -> None:
        self._url = url
        self._queue_key = queue_key
        self._source = source
        self._client: _RedisClient | None = client

    def _get_client(self) -> _RedisClient | None:
        if self._client is not None:
            return self._client
        try:
            from redis import Redis

            self._client = Redis.from_url(self._url, socket_timeout=2.0)
            return self._client
        except Exception:
            LOG.warning("RedisAlertSink: failed to construct redis client; alerts dropped")
            return None

    def publish(self, alert: Alert) -> None:
        client = self._get_client()
        if client is None:
            return
        try:
            client.lpush(self._queue_key, _alert_to_json(alert))
        except Exception as exc:
            LOG.warning(
                "RedisAlertSink: drop alert level=%s msg=%r err=%s",
                str(alert.level),
                alert.message,
                exc,
            )

    def close(self) -> None:
        client = self._client
        if client is None:
            return
        try:
            client.close()
        except Exception as exc:
            LOG.debug("redis client close raised: %s", exc)
        self._client = None
