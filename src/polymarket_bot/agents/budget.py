"""BudgetTracker — counts Anthropic spend, raises BudgetExceeded at the cap.

Per locked decision #14: Phase 3 hard cap is $35 per backtest pass, $50
cumulative across 4 passes for the whole phase. The tracker accepts a
`hard_limit_usd` and a softer `alarm_at_usd` (logs a warning, doesn't
raise). Costs are computed from the per-model unit prices in PRICING_USD;
if a model isn't in the table the tracker raises rather than silently
mispricing — the operator must add the model deliberately.
"""

from __future__ import annotations

import logging
from typing import Final

from polymarket_bot.agents.protocol import TokenUsage

LOG = logging.getLogger("polymarket_bot.agents.budget")

# USD per million tokens — keep in sync with shared/models.md (cached) and
# the live pricing on platform.claude.com. Tuple is (input, output, cache_read).
# Cache writes are 1.25x input (5min TTL); we don't break that out here —
# `record()` charges cache_creation at 1.25 * input rate.
PRICING_USD: Final[dict[str, tuple[float, float, float]]] = {
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    "claude-opus-4-7": (5.00, 25.00, 0.50),
    "claude-opus-4-6": (5.00, 25.00, 0.50),
}

CACHE_WRITE_MULTIPLIER: Final[float] = 1.25  # 5-minute TTL


class BudgetExceeded(RuntimeError):
    """Raised when cumulative spend exceeds hard_limit_usd."""


class BudgetTracker:
    """Per-pass spend tracker. Thread-safety: not required (single event loop)."""

    def __init__(
        self,
        *,
        hard_limit_usd: float = 35.0,
        alarm_at_usd: float | None = None,
    ) -> None:
        if hard_limit_usd <= 0:
            raise ValueError(f"hard_limit_usd must be > 0, got {hard_limit_usd}")
        # Default alarm to 85% of the hard limit so it scales with the cap.
        # Callers can pass an explicit value; setting it above hard_limit is
        # nonsensical and rejected.
        effective_alarm = alarm_at_usd if alarm_at_usd is not None else hard_limit_usd * 0.85
        if effective_alarm > hard_limit_usd:
            raise ValueError(
                f"alarm_at_usd ({effective_alarm}) must be <= hard_limit_usd ({hard_limit_usd})"
            )
        self._hard_limit = hard_limit_usd
        self._alarm = effective_alarm
        self._spent_usd = 0.0
        self._calls = 0
        self._calls_by_model: dict[str, int] = {}
        self._tokens_by_model: dict[str, TokenUsage] = {}
        self._alarmed = False

    def record(self, model: str, usage: TokenUsage) -> None:
        """Add the cost of one Anthropic call. Raises BudgetExceeded if over cap."""
        if model not in PRICING_USD:
            raise ValueError(f"unknown model {model!r}; add to PRICING_USD before using")
        in_rate, out_rate, cache_read_rate = PRICING_USD[model]
        cost = (
            usage.input_tokens * in_rate / 1_000_000
            + usage.output_tokens * out_rate / 1_000_000
            + usage.cache_read_input_tokens * cache_read_rate / 1_000_000
            + usage.cache_creation_input_tokens * in_rate * CACHE_WRITE_MULTIPLIER / 1_000_000
        )
        self._spent_usd += cost
        self._calls += 1
        self._calls_by_model[model] = self._calls_by_model.get(model, 0) + 1

        prev = self._tokens_by_model.get(model, TokenUsage())
        self._tokens_by_model[model] = TokenUsage(
            input_tokens=prev.input_tokens + usage.input_tokens,
            output_tokens=prev.output_tokens + usage.output_tokens,
            cache_creation_input_tokens=prev.cache_creation_input_tokens
            + usage.cache_creation_input_tokens,
            cache_read_input_tokens=prev.cache_read_input_tokens + usage.cache_read_input_tokens,
        )

        if self._spent_usd >= self._hard_limit:
            raise BudgetExceeded(
                f"spend ${self._spent_usd:.4f} exceeded hard_limit ${self._hard_limit:.2f}"
            )
        if self._spent_usd >= self._alarm and not self._alarmed:
            LOG.warning(
                "budget alarm: spend $%.4f crossed alarm threshold $%.2f " "(hard limit $%.2f)",
                self._spent_usd,
                self._alarm,
                self._hard_limit,
            )
            self._alarmed = True

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def hard_limit_usd(self) -> float:
        return self._hard_limit

    @property
    def calls(self) -> int:
        return self._calls

    def remaining_usd(self) -> float:
        return max(0.0, self._hard_limit - self._spent_usd)

    def report(self) -> dict[str, object]:
        return {
            "spent_usd": round(self._spent_usd, 6),
            "hard_limit_usd": self._hard_limit,
            "alarm_at_usd": self._alarm,
            "alarmed": self._alarmed,
            "calls": self._calls,
            "calls_by_model": dict(self._calls_by_model),
            "tokens_by_model": {m: u.model_dump() for m, u in self._tokens_by_model.items()},
        }
