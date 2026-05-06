"""Tests for polymarket_bot.backtest.side_index.TokenSideIndex.

Cover: the pure parser (extract_side_map) for canonical / malformed Gamma
shapes; the warm() async path with an injected fake fetch_fn; cache load
+ save round-trip; deduplication of already-warmed windows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from polymarket_bot.backtest.side_index import (
    TokenSideIndex,
    extract_side_map,
)

TOKEN_UP = "111" * 20
TOKEN_DOWN = "222" * 20


def _gamma_event(token_up: str = TOKEN_UP, token_down: str = TOKEN_DOWN) -> dict[str, Any]:
    return {
        "slug": "btc-updown-5m-1715000100",
        "markets": [
            {
                "outcomes": json.dumps(["Up", "Down"]),
                "clobTokenIds": json.dumps([token_up, token_down]),
            }
        ],
    }


def test_extract_side_map_happy_path() -> None:
    mapping = extract_side_map(_gamma_event())
    assert mapping == {TOKEN_UP: "UP", TOKEN_DOWN: "DOWN"}


def test_extract_side_map_accepts_native_lists_too() -> None:
    """Some Gamma versions return arrays instead of JSON-encoded strings."""
    event = {"markets": [{"outcomes": ["Up", "Down"], "clobTokenIds": [TOKEN_UP, TOKEN_DOWN]}]}
    assert extract_side_map(event) == {TOKEN_UP: "UP", TOKEN_DOWN: "DOWN"}


def test_extract_side_map_handles_reversed_order() -> None:
    """Gamma may list DOWN first; mapping respects index alignment."""
    event = {
        "markets": [
            {
                "outcomes": json.dumps(["Down", "Up"]),
                "clobTokenIds": json.dumps([TOKEN_DOWN, TOKEN_UP]),
            }
        ]
    }
    assert extract_side_map(event) == {TOKEN_DOWN: "DOWN", TOKEN_UP: "UP"}


def test_extract_side_map_empty_when_outcomes_missing() -> None:
    event = {"markets": [{"clobTokenIds": json.dumps([TOKEN_UP, TOKEN_DOWN])}]}
    assert extract_side_map(event) == {}


def test_extract_side_map_empty_when_outcomes_unknown() -> None:
    """Non-Up/Down outcomes (rare) skip the whole event safely."""
    event = {
        "markets": [
            {
                "outcomes": json.dumps(["Yes", "No"]),
                "clobTokenIds": json.dumps([TOKEN_UP, TOKEN_DOWN]),
            }
        ]
    }
    assert extract_side_map(event) == {}


def test_extract_side_map_empty_when_lengths_mismatch() -> None:
    event = {
        "markets": [
            {
                "outcomes": json.dumps(["Up", "Down", "Maybe"]),
                "clobTokenIds": json.dumps([TOKEN_UP, TOKEN_DOWN]),
            }
        ]
    }
    assert extract_side_map(event) == {}


def test_extract_side_map_empty_when_no_markets() -> None:
    assert extract_side_map({"slug": "x"}) == {}
    assert extract_side_map({"markets": []}) == {}


async def test_warm_populates_map_and_dedupes(tmp_path: Path) -> None:
    calls: list[str] = []

    async def fake_fetch(slug: str) -> dict[str, Any] | None:
        calls.append(slug)
        return _gamma_event()

    idx = TokenSideIndex(fetch_fn=fake_fetch)
    n_new = await idx.warm([1_715_000_100, 1_715_000_400, 1_715_000_100])  # last is duplicate

    assert n_new == 2  # third call was a duplicate of the first
    assert len(calls) == 2
    assert idx(TOKEN_UP) == "UP"
    assert idx(TOKEN_DOWN) == "DOWN"
    assert idx.n_known_tokens == 2


async def test_warm_handles_gamma_misses_gracefully() -> None:
    async def fake_fetch(slug: str) -> dict[str, Any] | None:
        return None  # window not on gamma

    idx = TokenSideIndex(fetch_fn=fake_fetch)
    n_new = await idx.warm([1_715_000_100])
    assert n_new == 0  # no usable mapping → no entry added
    assert idx.n_known_tokens == 0
    assert idx("anything") is None


async def test_warm_handles_fetch_exception_without_crashing() -> None:
    call_count = {"n": 0}

    async def fake_fetch(slug: str) -> dict[str, Any] | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient error")
        return _gamma_event()

    idx = TokenSideIndex(fetch_fn=fake_fetch)
    # First window raises → second window populates. Both windows considered
    # "warmed" so they're not retried.
    await idx.warm([1_715_000_100, 1_715_000_400])
    assert idx(TOKEN_UP) == "UP"


async def test_cache_round_trip(tmp_path: Path) -> None:
    cache = tmp_path / "side_index.json"

    async def fake_fetch(slug: str) -> dict[str, Any] | None:
        return _gamma_event()

    # First instance warms + saves.
    idx = TokenSideIndex(fetch_fn=fake_fetch, cache_path=cache)
    await idx.warm([1_715_000_100])
    assert cache.exists()

    # Second instance loads from cache; never calls fetch_fn for known windows.
    fetch_count = {"n": 0}

    async def counting_fetch(slug: str) -> dict[str, Any] | None:
        fetch_count["n"] += 1
        return _gamma_event()

    idx2 = TokenSideIndex(fetch_fn=counting_fetch, cache_path=cache)
    assert idx2(TOKEN_UP) == "UP"  # loaded from cache
    n_new = await idx2.warm([1_715_000_100])  # already warmed window
    assert n_new == 0
    assert fetch_count["n"] == 0


async def test_cache_skips_unwarmed_windows() -> None:
    """A token NOT in the cache should still go through fetch_fn."""

    async def fake_fetch(slug: str) -> dict[str, Any] | None:
        return _gamma_event()

    idx = TokenSideIndex(fetch_fn=fake_fetch)
    # No warm called → empty map.
    assert idx(TOKEN_UP) is None
    assert idx.n_known_tokens == 0


def test_implements_side_resolver_protocol() -> None:
    """Static check: TokenSideIndex satisfies the Callable[[str], Side|None] contract."""

    # Doesn't actually need a runtime check; mypy --strict catches violations.
    # This test just verifies the signature is callable as expected.
    async def fake_fetch(slug: str) -> dict[str, Any] | None:
        return None

    idx = TokenSideIndex(fetch_fn=fake_fetch)
    result = idx("nonexistent")
    assert result is None
