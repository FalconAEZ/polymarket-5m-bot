---
title: Polymarket data sources (taxonomy)
tags: [concept, polymarket, data, infrastructure]
---

# Polymarket data sources

> Five distinct data planes. Each has a shape, a cap, and a use case. Pick the wrong one and you'll waste hours.

## The five sources

| # | Source | Endpoint | Auth | Best use |
|---|---|---|---|---|
| 1 | **Gamma API** | `https://gamma-api.polymarket.com` | None | Event/market metadata, slugs, outcomes, resolutions |
| 2 | **Data API** (user trades) | `https://data-api.polymarket.com/trades?user=` | None | User-facing trade history. **Capped at offset 3,500.** |
| 3 | **Data API** (per-market) | `https://data-api.polymarket.com/trades?market=&user=` | None | All user trades on a specific market. **No practical cap.** ⭐ |
| 4 | **CLOB** | `https://clob.polymarket.com` | L2 HMAC for trade endpoints | Orderbook, prices, midpoint, order submission |
| 5 | **Goldsky orderbook subgraph** | `https://api.goldsky.com/.../orderbook-subgraph/.../gn` | None | Historical on-chain fills. **Indexes only the legacy CTF Exchange.** |
| 6 | **WebSocket (Market)** | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | None | Real-time orderbook + trades |
| 7 | **WebSocket (User)** | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | API creds in message | Real-time own-fill notifications |
| 8 | **Polygon RPC** (Alchemy) | `wss://polygon-mainnet.g.alchemy.com/...` | API key | Direct on-chain reads (Chainlink, exchange events) |

## The traps we hit (Phase A)

1. **Data API user-trades caps at offset 3,500.** Fine for read-only tools. **Useless for historical analysis** on high-frequency wallets like bonereaper (~40k fills/day = 3,500 = ~3 hours).

2. **Goldsky orderbook subgraph indexes only the original CTF Exchange (`0x4bFb…982E`).** The newer NegRisk Exchange (`0xC5d5…f80a`) is NOT covered. Bonereaper's recent BTC 5m activity is on NegRisk, so the subgraph showed 0 BTC 5m fills despite his clear current activity.

3. **Gamma API doesn't reliably batch `condition_ids`.** Each market lookup is one request. Iterate with thread-pool concurrency 8-16; don't try to batch.

4. **The combined filter `?market=&user=` works and has no practical cap.** Per-market user footprints are tens of trades, well under the 500-row limit. This was the recipe that unlocked the [[../research/audit-pipeline-recipe|7-day audit]].

## When to use which

- **Want a market's metadata?** Gamma API by slug.
- **Want a user's recent activity?** Data API user-trades, accept the 3-hour window.
- **Want a user's full historical activity on BTC 5m?** Per-market enumeration: Gamma to list markets, Data API combined-filter per market, aggregate.
- **Want orderbook state right now?** CLOB REST `/book` or WS market channel.
- **Want canonical fill events with timestamps and tx hashes?** Goldsky subgraph (CTF Exchange only) OR direct on-chain via Polygon RPC.
- **Want oracle resolution data?** Polygon RPC subscribed to Chainlink aggregator events. See [[chainlink-on-polygon]].

## See also

- [[../research/audit-pipeline-recipe]] — the per-market enumeration recipe with code references
- [[../research/data-sources-map]] — the same content but one level deeper, including cache strategies
- [[chainlink-on-polygon]] — the oracle source specifically
- `~/.claude/skills/agent-skills/{authentication,gasless,websocket,market-data,order-patterns}.md`
- `references/py-clob-client/README.md`
