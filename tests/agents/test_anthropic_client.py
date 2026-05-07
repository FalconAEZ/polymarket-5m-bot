"""Tests for polymarket_bot.agents.anthropic_client.AnthropicAdapter.

Inject a mock Anthropic client (no real API). Verify: usage extraction,
budget recording, refusal handling, schema-validation failure handling,
and that BudgetExceeded propagates synchronously.
"""

from __future__ import annotations

from typing import Any

import pytest

from polymarket_bot.agents.anthropic_client import AnthropicAdapter
from polymarket_bot.agents.budget import BudgetExceeded, BudgetTracker
from polymarket_bot.agents.protocol import AgentVote


class _FakeUsage:
    def __init__(
        self,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_creation_input_tokens: int = 0,
        cache_read_input_tokens: int = 0,
    ) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = cache_creation_input_tokens
        self.cache_read_input_tokens = cache_read_input_tokens


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _FakeResponse:
    def __init__(
        self,
        text: str | None = None,
        stop_reason: str = "end_turn",
        usage: _FakeUsage | None = None,
    ) -> None:
        self.content = [_FakeBlock(text)] if text is not None else []
        self.stop_reason = stop_reason
        self.usage = usage if usage is not None else _FakeUsage()


class _FakeMessages:
    def __init__(
        self, response: _FakeResponse | None = None, raises: BaseException | None = None
    ) -> None:
        self._response = response
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        if self._response is None:
            raise RuntimeError("FakeMessages: no response queued")
        return self._response


class _FakeAnthropicClient:
    def __init__(self, messages: _FakeMessages) -> None:
        self.messages = messages


async def test_parses_valid_response_into_pydantic_model() -> None:
    fake = _FakeMessages(
        _FakeResponse(
            text='{"side": "UP", "confidence": 0.8, "rationale": "test"}',
            usage=_FakeUsage(input_tokens=100, output_tokens=50),
        )
    )
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=10.0),
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    parsed, usage = await adapter.parse(
        model="claude-haiku-4-5",
        system=[{"type": "text", "text": "system"}],
        user="ctx",
        output_format=AgentVote,
    )
    assert isinstance(parsed, AgentVote)
    assert parsed.side == "UP"
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert adapter.budget.spent_usd > 0


async def test_returns_none_on_refusal() -> None:
    fake = _FakeMessages(
        _FakeResponse(
            text='{"side": "UP", "confidence": 0.5, "rationale": "x"}',
            stop_reason="refusal",
        )
    )
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=10.0),
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    parsed, _usage = await adapter.parse(
        model="claude-haiku-4-5",
        system=[{"type": "text", "text": "system"}],
        user="ctx",
        output_format=AgentVote,
    )
    assert parsed is None


async def test_returns_none_on_schema_failure() -> None:
    fake = _FakeMessages(
        _FakeResponse(text='{"side": "MAYBE", "confidence": 0.5, "rationale": "x"}')
    )
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=10.0),
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    parsed, _usage = await adapter.parse(
        model="claude-haiku-4-5",
        system=[{"type": "text", "text": "system"}],
        user="ctx",
        output_format=AgentVote,
    )
    assert parsed is None


async def test_returns_none_on_no_text_content() -> None:
    fake = _FakeMessages(_FakeResponse(text=None))
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=10.0),
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    parsed, _usage = await adapter.parse(
        model="claude-haiku-4-5",
        system=[{"type": "text", "text": "system"}],
        user="ctx",
        output_format=AgentVote,
    )
    assert parsed is None


async def test_returns_none_on_api_exception() -> None:
    import anthropic

    err = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    fake = _FakeMessages(raises=err)
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=10.0),
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    parsed, usage = await adapter.parse(
        model="claude-haiku-4-5",
        system=[{"type": "text", "text": "system"}],
        user="ctx",
        output_format=AgentVote,
    )
    assert parsed is None
    assert usage.input_tokens == 0  # no tokens charged on API-error path


async def test_propagates_budget_exceeded() -> None:
    fake = _FakeMessages(
        _FakeResponse(
            text='{"side": "UP", "confidence": 0.5, "rationale": "x"}',
            usage=_FakeUsage(output_tokens=1_000_000),
        )
    )
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=1.0),  # 1M output * $5 = $5 > $1
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    with pytest.raises(BudgetExceeded):
        await adapter.parse(
            model="claude-haiku-4-5",
            system=[{"type": "text", "text": "s"}],
            user="ctx",
            output_format=AgentVote,
        )


async def test_schema_sent_to_anthropic_has_additional_properties_false() -> None:
    """Anthropic structured-output rejects schemas missing additionalProperties:
    false on object types with HTTP 400 (`output_config.format.schema: For
    'object' type, 'additionalProperties' must be explicitly set to false`).
    Pydantic doesn't emit this by default, so AnthropicAdapter must inject it
    before sending. Regression for the 3.3 LLM A/B failure on 2026-05-07."""
    from polymarket_bot.agents.protocol import AgentContext, MetaDecision

    for output_format in (AgentVote, AgentContext, MetaDecision):
        fake = _FakeMessages(
            _FakeResponse(
                text='{"side": "UP", "confidence": 0.5, "rationale": "x"}',
            )
        )
        adapter = AnthropicAdapter(
            BudgetTracker(hard_limit_usd=10.0),
            client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
        )
        await adapter.parse(
            model="claude-haiku-4-5",
            system=[{"type": "text", "text": "s"}],
            user="ctx",
            output_format=output_format,
        )
        sent = fake.calls[0]["output_config"]["format"]["schema"]
        # Walk every "object" type in the schema and check the flag.
        _assert_strict(sent)


_REJECTED_KEYWORDS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "contains",
    "title",
    "default",
}


def _assert_strict(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            assert (
                node.get("additionalProperties") is False
            ), f"object schema missing additionalProperties=false: {node}"
        forbidden_present = _REJECTED_KEYWORDS.intersection(node.keys())
        assert (
            not forbidden_present
        ), f"schema contains keys Anthropic rejects: {forbidden_present} in {node}"
        for v in node.values():
            _assert_strict(v)
    elif isinstance(node, list):
        for v in node:
            _assert_strict(v)


async def test_passes_thinking_and_effort_through() -> None:
    fake = _FakeMessages(_FakeResponse(text='{"side": "UP", "confidence": 0.5, "rationale": "x"}'))
    adapter = AnthropicAdapter(
        BudgetTracker(hard_limit_usd=10.0),
        client=_FakeAnthropicClient(fake),  # type: ignore[arg-type]
    )

    await adapter.parse(
        model="claude-sonnet-4-6",
        system=[{"type": "text", "text": "s"}],
        user="ctx",
        output_format=AgentVote,
        thinking={"type": "adaptive"},
        effort="medium",
    )
    call = fake.calls[0]
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
