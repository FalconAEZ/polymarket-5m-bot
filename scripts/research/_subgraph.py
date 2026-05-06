"""GraphQL adapter for Polymarket's Goldsky orderbook subgraph.

Provides paginated access to `orderFilledEvents` (the canonical on-chain trade
record) without the Polymarket Data API's 3500-offset cap. Pagination uses a
descending timestamp cursor so we walk newest → oldest in O(N) calls.

Caveat: the orderbook subgraph indexes the original CTF Exchange contract only.
Trades on the NegRisk CTF Exchange (newer markets) don't appear here. The
audit script documents this limitation in the report.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import httpx

GOLDSKY_PROJECT = "project_cl6mb8i9h0003e201j6li0diw"
SUBGRAPH_ORDERBOOK = (
    f"https://api.goldsky.com/api/public/{GOLDSKY_PROJECT}"
    f"/subgraphs/orderbook-subgraph/0.0.1/gn"
)

DEFAULT_TIMEOUT = httpx.Timeout(30.0, read=30.0)
PAGE_SIZE = 500  # subgraph max is 1000 but smaller pages avoid Postgres statement-timeout


def _gql(
    query: str,
    variables: dict[str, Any] | None = None,
    *,
    client: httpx.Client | None = None,
    endpoint: str = SUBGRAPH_ORDERBOOK,
) -> dict[str, Any]:
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    payload: dict[str, Any] = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = cli.post(endpoint, json=payload)
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"subgraph GraphQL errors: {body['errors']}")
    return dict(body.get("data") or {})


def subgraph_meta(client: httpx.Client | None = None) -> dict[str, Any]:
    """Return the subgraph indexer state (`block.number`, `block.timestamp`)."""
    data = _gql(
        "{ _meta { block { number timestamp } hasIndexingErrors } }",
        client=client,
    )
    return dict(data.get("_meta") or {})


def fetch_user_fills(
    address: str,
    *,
    role: str = "maker",
    cutoff_unix: int = 0,
    client: httpx.Client | None = None,
    progress: bool = True,
) -> list[dict[str, Any]]:
    """Pull all fills for `address` in the given `role` ('maker' or 'taker').

    Walks newest → oldest using `timestamp_lt` cursor. Stops when an empty page
    is returned or when oldest fill in page < `cutoff_unix`. Returns the raw
    event records (no buy/sell interpretation).
    """
    if role not in ("maker", "taker"):
        raise ValueError(f"role must be 'maker' or 'taker', got {role!r}")
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    out: list[dict[str, Any]] = []
    cursor = 10**12  # higher than any plausible unix ts
    page = 0
    # Bound the query with both upper (cursor) and lower (cutoff) timestamp
    # filters so subgraph doesn't scan rows it'll discard. Without lower bound,
    # deep cursors hit Postgres statement-timeouts.
    floor_ts = max(cutoff_unix - 1, 0)
    while True:
        page += 1
        q = f"""
          query Fills($addr: String!, $cursor: BigInt!, $floor: BigInt!, $first: Int!) {{
            orderFilledEvents(
              first: $first,
              orderBy: timestamp,
              orderDirection: desc,
              where: {{ {role}: $addr, timestamp_lt: $cursor, timestamp_gt: $floor }}
            ) {{
              id
              transactionHash
              timestamp
              orderHash
              maker
              taker
              makerAssetId
              takerAssetId
              makerAmountFilled
              takerAmountFilled
              fee
            }}
          }}
        """
        params = {
            "addr": address.lower(),
            "cursor": str(cursor),
            "floor": str(floor_ts),
            "first": PAGE_SIZE,
        }
        # Retry transient subgraph timeouts with exponential backoff.
        for attempt in range(4):
            try:
                data = _gql(q, params, client=cli)
                break
            except (httpx.HTTPError, RuntimeError) as e:
                if attempt == 3:
                    raise
                wait = 2**attempt
                if progress:
                    print(
                        f"  [{role}] page {page} attempt {attempt + 1} failed "
                        f"({type(e).__name__}); backing off {wait}s"
                    )
                time.sleep(wait)
        rows = data.get("orderFilledEvents") or []
        if not rows:
            break
        oldest_ts = int(rows[-1]["timestamp"])
        out.extend(rows)
        if progress and (page <= 5 or page % 20 == 0):
            print(
                f"  [{role}] page {page}: +{len(rows)}  (cumulative: {len(out)}, "
                f"oldest: {oldest_ts})"
            )
        if oldest_ts <= cutoff_unix:
            break
        if len(rows) < PAGE_SIZE:
            break
        cursor = oldest_ts
        time.sleep(0.1)
    return out


def fetch_market_data_batch(
    token_ids: list[str],
    *,
    client: httpx.Client | None = None,
    chunk: int = 100,
) -> dict[str, dict[str, Any]]:
    """Resolve outcome-token IDs to (conditionId, outcomeIndex) via the subgraph.

    The subgraph's MarketData entity is keyed by the ERC1155 token id. Returns a
    dict keyed by token_id. Token ids the subgraph doesn't know are absent from
    the returned dict (caller decides how to handle).
    """
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    result: dict[str, dict[str, Any]] = {}
    distinct = sorted(set(token_ids))
    for i in range(0, len(distinct), chunk):
        batch = distinct[i : i + chunk]
        ids_arg = ", ".join(f'"{t}"' for t in batch)
        q = (
            f"{{ marketDatas(first: {len(batch)}, where: {{ id_in: [{ids_arg}] }}) "
            "{ id condition outcomeIndex } }"
        )
        data = _gql(q, client=cli)
        for row in data.get("marketDatas") or []:
            result[row["id"]] = {
                "condition": row.get("condition"),
                "outcomeIndex": row.get("outcomeIndex"),
            }
        time.sleep(0.05)
    return result


def iter_paged_user_fills(
    address: str,
    *,
    cutoff_unix: int = 0,
    client: httpx.Client | None = None,
) -> Iterator[dict[str, Any]]:
    """Convenience iterator yielding fills from both maker and taker roles."""
    cli = client or httpx.Client(timeout=DEFAULT_TIMEOUT)
    for role in ("maker", "taker"):
        yield from fetch_user_fills(address, role=role, cutoff_unix=cutoff_unix, client=cli)
