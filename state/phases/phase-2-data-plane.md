---
title: Phase 2 — Read-only data plane
status: in-design (prompt ready, dev session not yet started)
tags: [phase, data, feeds, planned]
---

# Phase 2 — Read-only data plane

> Stand up three reliable, well-archived data feeds (BTC spot, Chainlink BTC/USD oracle on Polygon, Polymarket 5m BTC market). Capture seven calendar days of clean tick data. Then run the **oracle-behavior verification gate** that the entire thesis depends on.

## Why this is the thesis-validation phase

The strategy hinges on a specific Chainlink BTC/USD heartbeat behavior on Polygon: ~60s heartbeat with no gaps > 180s and no sub-30s deviation triggers. If the actual oracle behaves differently in any of those four ways, the strategy as designed cannot work and Phase 3 backtests would be malpractice. **Phase 2 is the place we discover whether the thesis is real or wrong.**

See [[../concepts/oracle-gap]] and [[../concepts/window-delta]] for the signal mechanics; [[../concepts/chainlink-on-polygon]] for the upstream details we're relying on.

## Three natural cuts

Phase 2 has three sub-sessions because of the wall-clock shape:

| # | Cut | Wall-clock | Who |
|---|---|---|---|
| 1 | Dev session: tasks 2.0 → 2.4b code + tests + tmux launch | 1 focused session (~3-4 hours) | Claude |
| 2 | 7-day capture | 7 calendar days | Operator (daily checks) |
| 3 | Analysis session: task 2.6 + gate | 1 focused session (~1 hour) | Claude |

The operator owns cut 2 (it's wall-clock, not Claude-clock). Daily check is `cat state/feeds_health.json | jq` and `ls -lh ticks/$(date -u +%F)/`.

## Tasks

- 2.0 — `design/data_plane.md` (architecture: 3 async feeds + shared queue + Parquet writer + reconnect/backpressure policy + `Feed` protocol)
- 2.1 — `src/polymarket_bot/_live/feeds/{spot_binance,spot_coinbase,spot_aggregator}.py` + tests with `FakeWSClient`
- 2.2 — `src/polymarket_bot/_live/feeds/oracle.py` (Chainlink `AnswerUpdated` events on aggregator `0xc907...F6f` via Polygon WSS)
- 2.3 — `src/polymarket_bot/_live/feeds/polymarket.py` (5m BTC up/down market via `wss://ws-subscriptions-clob.polymarket.com/ws/market`; deterministic slug `btc-updown-5m-<window_ts>`)
- 2.4 — `src/polymarket_bot/resolver.py` (`hypothetical_now()` and `actual_resolution()` distinct)
- 2.4b — `src/polymarket_bot/_live/{storage,health,runtime}.py` + `scripts/run_capture.py` (wires it together; tmux-launchable; SIGTERM-graceful)
- 2.5 — operator launches the 7-day capture in tmux session `pmbot-capture`
- 2.6 — after 7 days: `scripts/analyze_oracle.py` against captured oracle parquet, gate `runbooks/gates/phase-2.sh`

## Gate (in design — runs after 7-day capture)

`runbooks/gates/phase-2.sh` asserts:
1. `make verify` green (mypy --strict, ruff, pytest).
2. `lint-imports` green (boundary between `_live/` and paper-mode code).
3. `ls ticks/` shows ≥ 7 dated directories, each with the four expected `.parquet` files.
4. `uv run python scripts/analyze_oracle.py --days 7` reports all four pass criteria green.
5. Cross-feed sanity: oracle update timestamps within ±2s of expected 60s cadence on any randomly chosen 5-minute window AND align with spot tick coverage on the same window.

**Pass criteria for #4 (the thesis-validation gate):**
- Median inter-update gap ∈ [55s, 65s].
- Zero sub-30s updates (deviation triggers — would shrink the lag window dangerously).
- Sub-60s updates < 5% of total (small jitter is fine).
- Zero gaps > 180s (a Chainlink outage we'd need to design for).

If any criterion fails, **stop**. Open `runbooks/incidents/oracle-behavior-N.md` and escalate to the operator. The thesis may need a different aggregator (e.g. Chainlink Data Streams instead of Price Feeds) or a fundamentally different strategy. Anti-vibe rule #21 (no gate softening) applies.

## Pre-flight

Before the dev session can start:
- [ ] Phase 1A gate green (`git tag -l | grep phase-1a-pass`) — ✅ done at `1537a18`.
- [ ] `POLYGON_RPC_URL` exposes a **WSS** variant on the same Alchemy app. Phase 0 set it to HTTPS for the chain-id smoke test; Phase 2's `eth_subscribe` needs WSS. **Operator must verify and update `.envrc` before the oracle code is written.**
- [ ] Chainlink BTC/USD aggregator on Polygon is currently `0xc907E116054Ad103354f2D350FD2514433D57F6f`. Verify at https://data.chain.link/feeds/polygon/mainnet/btc-usd before coding.
- [ ] `make verify` green at HEAD.

## Branch strategy

Default: continue on `claude/bold-galileo-2d56ca` (the Phase 1A branch). Keeps tags linear (`phase-0-pass` → `phase-1a-pass` → `phase-2-pass`) on a single feature branch, mergeable to `main` in one PR when the operator is ready.

Alternative: branch from `phase-1a-pass` if Phase 2 wants independent review. Decide before any code is written.

## Anticipated runtime deps

`pyproject.toml` already has `eth-account`, `py-clob-client`. Phase 2 will likely add (decided pre-session 2026-05-07):
- `httpx` — for the Gamma API slug→token_id lookup
- `polars` — Parquet writer (also already a dev dep)
- `pyarrow` — Polars Parquet backend
- `websockets` — async WS client for the three feeds
- `web3` — Polygon WSS provider for the Chainlink subscription

All pinned via `uv add <pkg>` with `uv.lock` committed.

## Connections

- Phase before: [[phase-1-wallet-auth]] (1A closed)
- Phase after: Phase 3 — backtest harness + LLM A/B (out of scope until Phase 2 gate green)
- Concepts: [[../concepts/oracle-gap]], [[../concepts/window-delta]], [[../concepts/chainlink-on-polygon]], [[../concepts/polymarket-data-sources]]
- Decisions: [[../decisions/README#decision-15|#15 UTC everywhere]], [[../decisions/README#decision-3|#3 NautilusTrader engine + py-clob-client]] (the engine isn't used in Phase 2 — direct WS — but the data-plane shape must be NautilusTrader-compatible for Phase 4)
- External prompt: `~/Desktop/phase-2-prompt.txt` — the full Claude Code dev-session prompt, written 2026-05-07
- Anti-vibe: rule #21 (no gate softening) is load-bearing for the four oracle pass-criteria
