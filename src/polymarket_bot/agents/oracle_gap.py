"""Oracle-gap specialist (Haiku 4.5) — spot vs latest Chainlink reading.

Aware of the empirical 33s heartbeat (locked decision #21). Prompt is in
prompts/oracle_gap.md.
"""

from __future__ import annotations

from pathlib import Path

from polymarket_bot.agents._base import load_prompt
from polymarket_bot.agents.anthropic_client import AnthropicAdapter
from polymarket_bot.agents.cache import cache_blocks
from polymarket_bot.agents.protocol import AgentContext, AgentVote

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256
PROMPT_NAME = "oracle_gap"


class OracleGapAgent:
    """Specialist 2: spot-vs-oracle gap."""

    def __init__(
        self,
        adapter: AnthropicAdapter,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        prompt_path: str | Path | None = None,
    ) -> None:
        self._adapter = adapter
        self.name: str = "oracle_gap"
        self.model: str = model
        self._max_tokens = max_tokens
        self._system = cache_blocks(load_prompt(PROMPT_NAME, prompt_path))

    async def vote(self, ctx: AgentContext) -> AgentVote | None:
        user_json = ctx.model_dump_json()
        result, _usage, _outcome = await self._adapter.parse(
            model=self.model,
            system=self._system,
            user=user_json,
            output_format=AgentVote,
            max_tokens=self._max_tokens,
        )
        return result if isinstance(result, AgentVote) else None
