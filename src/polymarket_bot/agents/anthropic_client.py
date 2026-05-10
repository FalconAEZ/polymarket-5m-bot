"""AnthropicAdapter — wraps anthropic.AsyncAnthropic with budget + cache discipline.

Uses client.messages.create() with output_config.format set from a pydantic
schema, then validates the response text against the same schema. We don't
use messages.parse() directly because we want full control over the failure
path — refusals, schema mismatches, and BudgetExceeded errors all surface
as `(None, usage)` so callers can fall back to the deterministic Tier-3.

Tests inject a FakeAdapter (see polymarket_bot.agents.fakes) that returns
canned responses; production calls Anthropic with the API key from
ANTHROPIC_API_KEY (already in .envrc since Phase 0).
"""

from __future__ import annotations

import copy
import logging
from typing import Any

import anthropic
from pydantic import BaseModel, ValidationError

from polymarket_bot.agents.budget import BudgetExceeded, BudgetTracker
from polymarket_bot.agents.protocol import TokenUsage

LOG = logging.getLogger("polymarket_bot.agents.anthropic_client")


class AnthropicAdapter:
    """Async wrapper around anthropic.AsyncAnthropic for the agent layer.

    Single source of truth for Anthropic calls: pydantic-typed structured
    outputs, prompt-cache breakpoints honoured, every call's usage recorded
    against a BudgetTracker. Returns (None, usage) on any failure path so
    the EnsembleStrategy's Tier-3 fallback (decision #6) can take over.
    """

    def __init__(
        self,
        budget: BudgetTracker,
        *,
        api_key: str | None = None,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self._budget = budget
        if client is not None:
            self._client = client
        else:
            self._client = anthropic.AsyncAnthropic(api_key=api_key)

    @property
    def budget(self) -> BudgetTracker:
        return self._budget

    async def parse(
        self,
        *,
        model: str,
        system: list[dict[str, object]],
        user: str,
        output_format: type[BaseModel],
        thinking: dict[str, object] | None = None,
        effort: str | None = None,
        max_tokens: int = 1024,
    ) -> tuple[BaseModel | None, TokenUsage]:
        """Call Anthropic with a JSON-schema output constraint and validate.

        Returns (validated_pydantic_instance, usage) on success;
        (None, usage) on refusal, schema fail, or API error. Always records
        usage against the budget tracker after the call returns — even on
        failure paths, since Anthropic still charges for those tokens. May
        raise BudgetExceeded synchronously if the call's cost crosses the
        hard cap.
        """
        schema = _strict_object_schema(output_format.model_json_schema())
        output_config: dict[str, object] = {"format": {"type": "json_schema", "schema": schema}}
        if effort is not None:
            output_config["effort"] = effort

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": output_config,
        }
        if thinking is not None:
            kwargs["thinking"] = thinking

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.APIError as e:
            LOG.warning("anthropic API error: %s: %s", type(e).__name__, e)
            return None, TokenUsage()

        usage = _extract_usage(response)
        # Charge the budget even on refusal / schema failure — Anthropic
        # billed for the call. BudgetExceeded then prevents the *next* call.
        try:
            self._budget.record(model, usage)
        except BudgetExceeded:
            raise

        if getattr(response, "stop_reason", None) == "refusal":
            LOG.info("anthropic refusal on model %s", model)
            return None, usage

        text = _extract_first_text(response)
        if text is None:
            LOG.info("anthropic returned no text content")
            return None, usage

        try:
            parsed: BaseModel = output_format.model_validate_json(text)
        except ValidationError as e:
            # Belt-and-suspenders: if the only validation errors are
            # `string_too_long`, truncate the offending fields and re-validate.
            # This recovers the vote when the LLM is wordy without losing the
            # actual verdict (side/confidence/action). Audit 2026-05-10:
            # 18 specialist + meta votes were lost to string_too_long today
            # alone; recovering those should restore ~14% of trades that
            # gate-mode was silently dropping.
            recovered = _try_truncate_and_revalidate(text, e, output_format)
            if recovered is not None:
                LOG.info(
                    "anthropic response had string_too_long; truncated "
                    "rationale and recovered (%s)",
                    output_format.__name__,
                )
                return recovered, usage
            LOG.info("anthropic response failed schema validation: %s", e)
            return None, usage
        return parsed, usage


# JSON Schema keywords Anthropic's structured-output API rejects (mirrors
# OpenAI's strict-mode subset). Pydantic emits these from Field constraints
# (`ge=`, `le=`, `max_length=`, ...) and `title`/`default` decoration. Strip
# them before sending. Per shared/structured-outputs Anthropic skill doc:
#   Not supported: numerical constraints (minimum/maximum/multipleOf),
#   string constraints (minLength/maxLength/pattern), complex array
#   constraints, additionalProperties != false.
_UNSUPPORTED_KEYWORDS: frozenset[str] = frozenset(
    {
        # numerical
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        # string
        "minLength",
        "maxLength",
        "pattern",
        # array
        "minItems",
        "maxItems",
        "uniqueItems",
        "contains",
        # decorative / unsupported metadata
        "title",
        "default",
    }
)


def _strict_object_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a pydantic-emitted JSON schema acceptable to Anthropic structured outputs.

    Two transforms applied recursively to a deep copy:
      1. Inject ``additionalProperties: false`` on every object subschema
         (Anthropic requires it; pydantic doesn't emit it).
      2. Strip ``_UNSUPPORTED_KEYWORDS`` (minimum/maximum/maxLength/title/...
         that Anthropic rejects with HTTP 400).

    Regression test in ``tests/agents/test_anthropic_client.py``.
    """
    out = copy.deepcopy(schema)
    _walk_strict(out)
    return out


def _try_truncate_and_revalidate(
    text: str, err: ValidationError, output_format: type[BaseModel]
) -> BaseModel | None:
    """If `err` is purely `string_too_long`, truncate offending fields + retry.

    Returns the validated model on success, None if the error class is
    different (or truncation still doesn't validate). Tight scope: only
    handles top-level string fields. Nested-object truncation isn't worth
    the complexity for the agent schemas (all string fields are top-level).
    """
    import json as _json

    errors = err.errors()
    if not errors or any(e.get("type") != "string_too_long" for e in errors):
        return None
    try:
        payload = _json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    # Each error has loc=('field_name',) and ctx={'max_length': N}
    for e in errors:
        loc = e.get("loc")
        if not loc or not isinstance(loc[0], str):
            return None
        field = loc[0]
        ctx = e.get("ctx") or {}
        max_len = ctx.get("max_length")
        if not isinstance(max_len, int) or max_len <= 0:
            return None
        val = payload.get(field)
        if not isinstance(val, str):
            return None
        # Truncate with an ellipsis marker so the rationale visibly says
        # "this was clipped"; safe because the consumer only reads the
        # first chars for logging.
        ellipsis = "..."
        keep = max(1, max_len - len(ellipsis))
        payload[field] = val[:keep] + ellipsis
    try:
        return output_format.model_validate(payload)
    except ValidationError:
        return None


def _walk_strict(node: object) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object":
            node.setdefault("additionalProperties", False)
        for key in list(node.keys()):
            if key in _UNSUPPORTED_KEYWORDS:
                del node[key]
        for v in node.values():
            _walk_strict(v)
    elif isinstance(node, list):
        for v in node:
            _walk_strict(v)


def _extract_usage(response: object) -> TokenUsage:
    """Pull token usage from an Anthropic response, defaulting fields to 0."""
    usage_obj = getattr(response, "usage", None)
    if usage_obj is None:
        return TokenUsage()
    return TokenUsage(
        input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
        output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
        cache_creation_input_tokens=getattr(usage_obj, "cache_creation_input_tokens", 0) or 0,
        cache_read_input_tokens=getattr(usage_obj, "cache_read_input_tokens", 0) or 0,
    )


def _extract_first_text(response: object) -> str | None:
    """Find the first text content block in an Anthropic response."""
    content = getattr(response, "content", None)
    if not isinstance(content, list):
        return None
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", None)
            if isinstance(text, str):
                return text
    return None
