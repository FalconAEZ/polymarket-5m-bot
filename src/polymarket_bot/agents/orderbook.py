"""Orderbook microstructure specialist (Haiku 4.5).

Reads top-of-book + book imbalance and votes UP/DOWN/ABSTAIN. Prompt is in
prompts/orderbook.md (versioned in git). Anti-vibe rule #6: tests inject a
fake adapter, no real Anthropic calls in unit tests.
"""

from __future__ import annotations

from pathlib import Path

from polymarket_bot.agents._base import load_prompt
from polymarket_bot.agents.anthropic_client import AnthropicAdapter
from polymarket_bot.agents.cache import cache_blocks
from polymarket_bot.agents.protocol import AgentContext, AgentVote

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256
PROMPT_NAME = "orderbook"


class OrderbookAgent:
    """Specialist 1: orderbook microstructure."""

    def __init__(
        self,
        adapter: AnthropicAdapter,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        prompt_path: str | Path | None = None,
    ) -> None:
        self._adapter = adapter
        self.name: str = "orderbook"
        self.model: str = model
        self._max_tokens = max_tokens
        self._system = cache_blocks(load_prompt(PROMPT_NAME, prompt_path))

    async def vote(self, ctx: AgentContext) -> AgentVote | None:
        user_json = ctx.model_dump_json()
        result, _usage = await self._adapter.parse(
            model=self.model,
            system=self._system,
            user=user_json,
            output_format=AgentVote,
            max_tokens=self._max_tokens,
        )
        return result if isinstance(result, AgentVote) else None
