"""Phase 16.B every-window router — the strategy that fires on every 5-min window.

Replaces the old FIRE/ABSTAIN-gate composition with a confidence-driven
router that picks (side, size, ttl, fill_style) for every window unless
a safety veto trips. See ``design/phase-16b-every-window-mode.md`` for
the locked spec.

Public API:
  - ``Router``: the router class
  - ``RouterConfig``: tunable thresholds (env-driven)
  - ``RouterContext``: input dataclass
  - ``RouterDecision``: output dataclass
"""

from polymarket_bot.strategies.every_window.config import RouterConfig
from polymarket_bot.strategies.every_window.router import Router
from polymarket_bot.strategies.every_window.types import (
    RouterContext,
    RouterDecision,
)

__all__ = ["Router", "RouterConfig", "RouterContext", "RouterDecision"]
