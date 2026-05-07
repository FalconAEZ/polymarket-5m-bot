---
title: Polymarket data sources map (deep version)
tags: [research, methodology, infrastructure]
---

# Polymarket data sources map (deep)

> The full taxonomy with caveats, caps, and best-use guides. The concept-level summary is at [[../concepts/polymarket-data-sources]]; this note is the operational reference.

## Quick lookup

| Source | Endpoint | Auth | Cap | Best for |
|---|---|---|---|---|
| Gamma API | `gamma-api.polymarket.com` | None | None reliable | Market metadata, slugs, resolutions |
| Data API user-trades | `data-api.polymarket.com/trades?user=` | None | **offset 3,500** | Recent ~3h on high-frequency wallets |
| Data API combined filter | `data-api.polymarket.com/trades?market=&user=` | None | None practical | Historical user analysis ⭐ |
| Data API positions | `data-api.polymarket.com/positions?user=` | None | ~30 open | Current positions |
| Data API activity | `data-api.polymarket.com/activity?user=` | None | offset 3,000 | Same as trades + non-trade events |
| CLOB REST | `clob.polymarket.com` | L2 for trade endpoints | None | Orderbook, prices, midpoints |
| CLOB WS market | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | None | None | Real-time orderbook, last-trade prints |
| CLOB WS user | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | API creds in msg | None | Own-fill notifications |
| Goldsky orderbook subgraph | `api.goldsky.com/.../orderbook-subgraph/...` | None | Postgres timeout on deep cursors | **Legacy CTF Exchange ONLY** |
| Polygon RPC (Alchemy) | `wss://polygon-mainnet.g.alchemy.com/v2/...` | API key | 300M CU/month free | Direct on-chain reads |

## Detailed notes

### Gamma API — `/events?slug=`

Reliable, fast, no auth. Returns event objects with a `markets[]` array. Each market has:
- `conditionId` (the on-chain condition hash)
- `outcomes` (e.g. `["Up", "Down"]`)
- `outcomePrices` (e.g. `["1", "0"]` — `"1"` is the winner for closed markets)
- `clobTokenIds` (the two ERC1155 token IDs for the binary outcomes)
- `closed`, `closedTime`, `umaResolutionStatus`
- `feeSchedule` (V2: ~7.2 bps taker)
- `negRisk` (whether on the NegRisk CTF Exchange)

**`condition_ids=` batch filter does NOT reliably work.** Iterate with concurrency.

**`clob_token_ids=` filter is unreliable** (returns 0 rows or unfiltered defaults).

### Data API combined filter — `/trades?market=&user=`

This is the unsung hero. Combining `market=<conditionId>` and `user=<addr>` returns every trade by that user on that market. Per-market user footprints are tens of trades, well under the 500-row default.

For a 7-day audit on BTC 5-min:
- 2,016 candidate slugs (deterministic generation)
- 2,015 closed markets after Gamma resolution
- 1,927 markets where bonereaper traded (96% coverage)
- 56,976 individual trades, 56,972 labellable
- ~3 minutes total (concurrency 16)

This was the recipe that unlocked the [[../phases/phase-A-bonereaper|Phase A 7-day audit]].

### Goldsky orderbook subgraph

GraphQL endpoint, paginatable by timestamp cursor. **Critical limitation: indexes only the original CTF Exchange (`0x4bFb…982E`).** The newer NegRisk CTF Exchange (`0xC5d5…f80a`) does NOT appear here.

Bonereaper had been on the NegRisk Exchange for the last week+ when audited; subgraph showed zero BTC 5m fills despite his obvious current activity.

The `_meta.block.timestamp` field tells you how fresh the subgraph is — it stays current for the legacy exchange, but if your target wallet has moved exchanges, you won't see their recent activity.

Use cases that DO work:
- Historical analysis on wallets that traded the legacy CTF Exchange
- Market-data lookup via `marketDatas(id_in: [...])` to map ERC1155 token ids → conditionIds
- Trade volume / counts on legacy markets

Use cases that DON'T work:
- Anything on the NegRisk Exchange
- Recent activity for wallets that have migrated

### Polygon RPC (Alchemy)

The canonical source for everything on-chain. We use it for [[../concepts/chainlink-on-polygon|Chainlink BTC/USD events]] in Phase 2. Could also be used to filter `OrderFilled` events directly from the NegRisk Exchange contract — that's the fallback if the per-market enumeration recipe ever stops working.

Alchemy free tier (300M CU/month) is more than enough for the bot's lifetime. Subscribe via the `wss://` URL for real-time event streams; HTTP for one-shot calls.

### CLOB API

For Phase 6 live trading. Not used in Phase A or earlier audits. L2 HMAC auth required for trade endpoints; read endpoints (orderbook, prices) are public.

WebSocket market channel is the canonical real-time orderbook source — used in Phase 2 for capture and Phase 6 for live decisions.

## Cache strategies

All four major sources have aggressive caching opportunities:

| Source | Cache TTL | Cache key |
|---|---|---|
| Gamma `/events?slug=` | Until market closes | slug |
| Data API combined filter | Until next trade on that market | (conditionId, user) |
| Goldsky subgraph | Until next event from that wallet | (wallet, role, timestamp_window) |
| Polygon RPC events | Until next block | (contract, topic, block_range) |

For the Phase A audit, we cached on a per-UTC-day basis under `state/research/bonereaper/` — same-day re-runs are instant. See `scripts/research/weekly_audit.py` for the implementation.

## See also

- [[../concepts/polymarket-data-sources]] — concept-level summary
- [[audit-pipeline-recipe]] — the recipe that uses these sources
- [[bonereaper-study-postmortem]] — what we learned by hammering each
- `~/.claude/skills/agent-skills/market-data.md` — Polymarket's official reference
