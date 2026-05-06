"""Prompt-cache layout helper for Anthropic agents.

Per the Anthropic prompt caching guide: caching is a prefix match — any byte
change anywhere in the prefix invalidates everything downstream. The static
system prompt must therefore precede every byte that varies per call.

cache_blocks(static_prompt) returns a list[dict] suitable for the SDK's
`system=` field with a single ephemeral cache_control breakpoint at the end
of the static block. The dynamic per-window context goes in the `messages`
list AFTER the breakpoint, so it does not invalidate the cache.
"""

from __future__ import annotations

CACHE_CONTROL_EPHEMERAL = {"type": "ephemeral"}


def cache_blocks(static_prompt: str) -> list[dict[str, object]]:
    """Wrap a static prompt as a single cacheable system block.

    The SDK's `system=` field accepts either a bare string or a list of
    typed blocks. The list form is required to attach `cache_control` to a
    specific block. We always emit a single block — multi-block system
    prompts are an optimisation Phase 3.3 can revisit if needed.
    """
    if not static_prompt.strip():
        raise ValueError("cache_blocks: static_prompt is empty")
    return [
        {
            "type": "text",
            "text": static_prompt,
            "cache_control": CACHE_CONTROL_EPHEMERAL,
        }
    ]
