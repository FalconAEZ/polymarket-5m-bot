"""Top-level alerts package — producer surface for bot runtimes.

Public API: Alert + Level (types), AlertSink + Clock (protocols), NullAlertSink
+ RedisAlertSink (implementations). The consumer daemon at
`polymarket_bot._live.alerter` BRPOPs the same Redis list this package's
RedisAlertSink LPUSHes onto. Both `_paper` and `_live` may import this
package; import-linter contract names "production never imports paper"
remains satisfied because this package is top-level (not under either).
"""

from polymarket_bot.alerts.null import NullAlertSink
from polymarket_bot.alerts.protocols import AlertSink, Clock
from polymarket_bot.alerts.redis_sink import DEFAULT_QUEUE_KEY, RedisAlertSink
from polymarket_bot.alerts.types import Alert, Level

__all__ = [
    "DEFAULT_QUEUE_KEY",
    "Alert",
    "AlertSink",
    "Clock",
    "Level",
    "NullAlertSink",
    "RedisAlertSink",
]
