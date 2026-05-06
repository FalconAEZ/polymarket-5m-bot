"""Thin HTTP adapter for Polymarket Data + Gamma APIs.

Single-purpose helpers around `httpx` so the audit script body stays focused on
analysis. All functions are pure-ish: identical inputs produce identical
outputs (modulo upstream changes), and they cache nothing themselves — caching
is the caller's responsibility (see `quick_audit.py`).
"""

from __future__ import annotations

import time
from typing import Any

import httpx

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"

DEFAULT_TIMEOUT = httpx.Timeout(15.0, read=15.0)


def fetch_market_by_condition_id(
    condition_id: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """Resolve a single conditionId to its market record via the Gamma API.

    Returns None if the condition isn't known (rare). The Gamma API doesn't
    support batched condition_ids reliably; iterate one-at-a-time with a
    thread pool for parallelism.
    """
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    resp = cli.get(f"{GAMMA_API}/markets", params={"condition_ids": condition_id})
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return dict(rows[0])


def fetch_user_trades(
    address: str,
    *,
    limit: int = 500,
    offset: int = 0,
    client: httpx.Client | None = None,
) -> list[dict[str, Any]]:
    """Pull one page of trades for a Polymarket user (proxy wallet) address.

    The Data API returns up to 500 records per call, newest first. Use
    `offset` to paginate. Returns an empty list when no more records exist.
    Raises on non-200 to fail the audit loud rather than silently skip.
    """
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    url = f"{DATA_API}/trades"
    params = {"user": address, "limit": str(limit), "offset": str(offset)}
    resp = cli.get(url, params=params)
    resp.raise_for_status()
    return list(resp.json())


def fetch_event_by_slug(
    slug: str,
    *,
    client: httpx.Client | None = None,
) -> dict[str, Any] | None:
    """Pull a single event (with markets[]) by its URL slug.

    Returns None if the slug doesn't resolve to anything (rare — usually
    means the event was removed). The Gamma API returns a list; we always
    take the first match because slugs are globally unique on Polymarket.
    """
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    url = f"{GAMMA_API}/events"
    resp = cli.get(url, params={"slug": slug})
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return None
    return dict(rows[0])


def paginate_user_trades(
    address: str,
    *,
    page_size: int = 500,
    max_pages: int = 200,
    sleep_between_pages_s: float = 0.2,
    client: httpx.Client | None = None,
    progress: bool = True,
) -> list[dict[str, Any]]:
    """Walk the Data API trades endpoint until exhausted or `max_pages` hit.

    Caller is responsible for filtering / saving. The hard cap of 200 pages
    x 500 trades = 100,000 trades is well above any realistic single-wallet
    history but prevents runaway loops if the upstream paginator misbehaves.
    """
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    out: list[dict[str, Any]] = []
    for page in range(max_pages):
        offset = page * page_size
        try:
            chunk = fetch_user_trades(address, limit=page_size, offset=offset, client=cli)
        except httpx.HTTPStatusError as e:
            # Polymarket Data API rejects pagination beyond ~3500 trades with 400.
            # Treat that as "end of available history" and continue with what we have.
            if 400 <= e.response.status_code < 500:
                if progress:
                    print(
                        f"  page {page + 1} (offset={offset}): {e.response.status_code} — "
                        "API max-offset reached; using observable history"
                    )
                break
            raise
        if not chunk:
            break
        out.extend(chunk)
        if progress:
            print(f"  page {page + 1}: +{len(chunk)} trades  (cumulative: {len(out)})")
        if len(chunk) < page_size:
            break  # last page
        time.sleep(sleep_between_pages_s)
    return out
