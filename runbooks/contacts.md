# Operational contacts

> Where each operator-facing channel lives. Update when accounts change. Do not commit secrets here — only handles, IDs, and channel descriptions.

## Telegram

- **Bot username:** see `.envrc` (not committed; the bot was created via @BotFather on 2026-05-06)
- **Bot token:** `TELEGRAM_BOT_TOKEN` env var
- **Operator chat ID:** `TELEGRAM_CHAT_ID` env var
- **Use:** all CRITICAL bot alerts (kill-switch trips, drawdown breaches, recon drift, oracle stale). Inbound `/halt` command will be wired in Phase 5 (VPS) for remote kill from phone.

## GitHub

- **Repo:** `FalconAEZ/polymarket-5m-bot` (private)
- **Default branch:** `main`
- **CI:** GitHub Actions (`.github/workflows/ci.yml`)
- **Deploy keys / tokens:** added per-need; never paste in chat

## Anthropic

- **Console:** [console.anthropic.com](https://console.anthropic.com)
- **API key env var:** `ANTHROPIC_API_KEY`
- **Tier:** 1 (≥$50 credit balance loaded). Top up to $150 before Phase 4, $300 before Phase 6.

## Polygon RPC

- **Provider:** Alchemy free tier
- **Env var:** `POLYGON_RPC_URL` (WebSocket URL — `wss://polygon-mainnet.g.alchemy.com/v2/...`)
- **Use:** Phase 2+ — Chainlink BTC/USD AnswerUpdated subscription. Phase 4+ — bonereaper-style on-chain queries (the cloning study is archived, but the audit pipeline survives for any-wallet auditing).

## Polymarket

- **Profile (operator's wallet, set up Phase 1):** TBD
- **API:** `clob.polymarket.com` (REST), `wss://ws-subscriptions-clob.polymarket.com/ws/market` (market WS), `wss://ws-subscriptions-clob.polymarket.com/ws/user` (user WS)
- **Auth:** L1 EIP-712 derives L2 HMAC creds; see `~/.claude/skills/agent-skills/authentication.md`.
