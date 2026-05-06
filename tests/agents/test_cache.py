"""Tests for polymarket_bot.agents.cache.cache_blocks."""

from __future__ import annotations

import pytest

from polymarket_bot.agents.cache import CACHE_CONTROL_EPHEMERAL, cache_blocks


def test_cache_blocks_wraps_static_prompt_with_breakpoint() -> None:
    blocks = cache_blocks("hello world")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert blocks[0]["text"] == "hello world"
    assert blocks[0]["cache_control"] == CACHE_CONTROL_EPHEMERAL


def test_cache_blocks_rejects_empty_prompt() -> None:
    with pytest.raises(ValueError, match="empty"):
        cache_blocks("")
    with pytest.raises(ValueError, match="empty"):
        cache_blocks("   \n\t  ")
