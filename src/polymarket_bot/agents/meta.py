"""Meta-decider (Sonnet 4.6, effort=medium, no adaptive thinking).

Synthesises 3 specialist votes plus the deterministic composite into a
final FIRE/ABSTAIN action. Prompt is in prompts/meta.md.

Per the Anthropic API skill: Sonnet 4.6 supports adaptive thinking + the
effort parameter. Originally used `thinking={"type": "adaptive"}` +
`effort="medium"` but the audit 2026-05-10 14:38 UTC showed 2/3 of
gate-mode LLM votes timing out at the runner's 2.5s budget — adaptive
thinking adds ~2-3s of inference time per call. Disabling it brings
typical Sonnet-medium round-trips into the 1-2s range so gate-mode
actually delivers LLM gating instead of perpetually falling back to
base. Effort=medium is preserved (fast enough for 5m cadence, deep
enough to synthesise across 3 specialists + composite).
"""

from __future__ import annotations

import json
from pathlib import Path

from polymarket_bot.agents._base import load_prompt
from polymarket_bot.agents.anthropic_client import AnthropicAdapter
from polymarket_bot.agents.cache import cache_blocks
from polymarket_bot.agents.protocol import (
    AgentContext,
    AgentVote,
    MetaDecision,
    MetaOutcome,
)

DEFAULT_MODEL = "claude-sonnet-4-6"
# Meta only emits a small JSON object (action + side + confidence + rationale).
# Even with adaptive thinking, 512 output tokens is more than enough for the
# rationale (max ~500 chars) plus the structured fields. Cut from 1024 -> 512
# to shave latency. Per audit 2026-05-10, dropping unused output budget
# noticeably reduces P95 response time.
DEFAULT_MAX_TOKENS = 512
DEFAULT_EFFORT = "medium"
PROMPT_NAME = "meta"


class MetaDecider:
    """Synthesise specialist votes + deterministic composite into a final action."""

    def __init__(
        self,
        adapter: AnthropicAdapter,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        effort: str | None = DEFAULT_EFFORT,
        adaptive_thinking: bool = False,
        prompt_path: str | Path | None = None,
    ) -> None:
        self._adapter = adapter
        self.name: str = "meta"
        self.model: str = model
        self._max_tokens = max_tokens
        self._effort = effort
        self._thinking: dict[str, object] | None = (
            {"type": "adaptive"} if adaptive_thinking else None
        )
        self._system = cache_blocks(load_prompt(PROMPT_NAME, prompt_path))

    async def decide(
        self, ctx: AgentContext, votes: dict[str, AgentVote]
    ) -> tuple[MetaDecision | None, MetaOutcome]:
        """Run the meta-decider. Returns (decision, outcome).

        ``outcome`` is the MetaOutcome tag from the adapter, EXCEPT when
        the adapter returned a parsed MetaDecision that then failed the
        post-Pydantic FIRE/ABSTAIN-side invariant — those flip the tag to
        ``"invariant_violated"`` so the ensemble log can attribute that
        class separately from API/parse failures.
        """
        user_payload = {
            "context": ctx.model_dump(),
            "votes": [
                {
                    "agent": agent_name,
                    "side": vote.side,
                    "confidence": vote.confidence,
                    "rationale": vote.rationale,
                }
                for agent_name, vote in sorted(votes.items())
            ],
        }
        user_json = json.dumps(user_payload, sort_keys=True, default=str)
        result, _usage, outcome = await self._adapter.parse(
            model=self.model,
            system=self._system,
            user=user_json,
            output_format=MetaDecision,
            thinking=self._thinking,
            effort=self._effort,
            max_tokens=self._max_tokens,
        )
        if not isinstance(result, MetaDecision):
            return None, outcome
        # Schema-level invariant the prompt also commits to.
        if result.action == "FIRE" and result.side is None:
            return None, "invariant_violated"
        if result.action == "ABSTAIN" and result.side is not None:
            return None, "invariant_violated"
        return result, "ok"
