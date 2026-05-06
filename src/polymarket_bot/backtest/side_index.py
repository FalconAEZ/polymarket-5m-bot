"""Token-side index — resolves Polymarket asset_id (token_id) to UP/DOWN.

The replay engine emits BookUpdate(side=...) per design/backtest.md §4, but
the captured Parquet payload only carries asset_id. The mapping
asset_id → "UP" | "DOWN" is window-specific: each 5m BTC up/down market has
two CTF tokens (one per outcome), with the assignment recorded in Gamma's
event response (`markets[0].clobTokenIds[i]` aligns with `outcomes[i]`).

TokenSideIndex implements the SideResolver protocol from replay.py. It
warms its in-memory dict by calling a Gamma fetch_fn per window, with
optional persistence to a JSON cache so subsequent backtests don't
re-call Gamma. Tests inject a synthetic fetch_fn.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from pathlib import Path
from typing import Any, cast

from polymarket_bot.backtest.types import Side
from polymarket_bot.resolver import active_slug

LOG = logging.getLogger("polymarket_bot.backtest.side_index")

GammaFetchFn = Callable[[str], Awaitable[dict[str, Any] | None]]
"""Async function: takes a slug, returns the first matching Gamma event or None."""


def extract_side_map(event: dict[str, Any]) -> dict[str, Side]:
    """Pure parser: Gamma event dict → {token_id: "UP" | "DOWN"}.

    Gamma stores both `clobTokenIds` and `outcomes` as JSON-encoded strings;
    each is a 2-element array, with `outcomes[i]` naming the side that
    `clobTokenIds[i]` represents. Returns an empty dict if either field is
    missing, malformed, or the outcomes don't match the canonical
    {"Up", "Down"} pair.
    """
    markets = event.get("markets")
    if not isinstance(markets, list) or not markets:
        return {}
    market = markets[0]
    if not isinstance(market, dict):
        return {}
    tokens = _decode_string_array(market.get("clobTokenIds"))
    outcomes = _decode_string_array(market.get("outcomes"))
    if len(tokens) != 2 or len(outcomes) != 2:
        return {}
    out: dict[str, Side] = {}
    for tid, outcome in zip(tokens, outcomes, strict=True):
        side = _outcome_to_side(outcome)
        if side is None:
            return {}
        out[tid] = side
    if set(out.values()) != {"UP", "DOWN"}:
        return {}  # both must be present, distinct sides
    return out


def _decode_string_array(value: object) -> list[str]:
    """Gamma's clobTokenIds and outcomes can be either a JSON-encoded string
    or an actual list. Handle both."""
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return [v for v in decoded if isinstance(v, str)]
    return []


def _outcome_to_side(outcome: str) -> Side | None:
    norm = outcome.strip().upper()
    if norm == "UP":
        return "UP"
    if norm == "DOWN":
        return "DOWN"
    return None


class TokenSideIndex:
    """Async-warmable, sync-callable resolver. Implements SideResolver."""

    def __init__(
        self,
        *,
        fetch_fn: GammaFetchFn,
        cache_path: str | Path | None = None,
    ) -> None:
        self._fetch = fetch_fn
        self._cache_path = Path(cache_path) if cache_path is not None else None
        self._map: dict[str, Side] = {}
        self._warmed_windows: set[int] = set()
        if self._cache_path is not None and self._cache_path.exists():
            self._load_cache()

    def __call__(self, token_id: str) -> Side | None:
        return self._map.get(token_id)

    @property
    def map(self) -> dict[str, Side]:
        return dict(self._map)

    @property
    def n_known_tokens(self) -> int:
        return len(self._map)

    async def warm(self, windows: Iterable[int]) -> int:
        """Fetch each window's slug from Gamma and merge the side map.

        Skips windows already warmed in this instance. Returns the number
        of windows newly fetched. A Gamma miss (None or malformed event)
        is logged and skipped — no side info is added for that window.
        """
        new = 0
        for window_ts in windows:
            if window_ts in self._warmed_windows:
                continue
            slug = active_slug(window_ts)
            try:
                event = await self._fetch(slug)
            except Exception as e:
                LOG.warning("gamma-warm: %s fetch failed: %s", slug, e)
                self._warmed_windows.add(window_ts)
                continue
            if not isinstance(event, dict):
                self._warmed_windows.add(window_ts)
                continue
            mapping = extract_side_map(event)
            if not mapping:
                LOG.info("gamma-warm: %s has no usable side map", slug)
            self._map.update(mapping)
            self._warmed_windows.add(window_ts)
            new += 1
        if new > 0 and self._cache_path is not None:
            self._save_cache()
        return new

    def _load_cache(self) -> None:
        if self._cache_path is None:
            return
        try:
            data = json.loads(self._cache_path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        tokens = data.get("tokens") if isinstance(data, dict) else None
        if isinstance(tokens, dict):
            for tid, side in tokens.items():
                if isinstance(side, str) and side in ("UP", "DOWN"):
                    self._map[tid] = cast(Side, side)
        warmed = data.get("warmed_windows") if isinstance(data, dict) else None
        if isinstance(warmed, list):
            for w in warmed:
                if isinstance(w, int):
                    self._warmed_windows.add(w)

    def _save_cache(self) -> None:
        if self._cache_path is None:
            return
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tokens": dict(self._map),
            "warmed_windows": sorted(self._warmed_windows),
        }
        tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self._cache_path)
