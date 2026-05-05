# Polymarket BTC 5-Min Up/Down Trading Bot — Master Plan

> Started 2026-05-04. Owner: Hamad (UAE-resident, Polymarket-permitted). Style: phased, design-first, no vibe coding.
>
> **This document explains *why* the architecture was chosen.** For *what to do next*, see [`RUNBOOK.md`](./RUNBOOK.md). For locked decisions, see `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`. When this file disagrees with the runbook, the runbook wins.

---

## Locked architecture revisions (after two-pass review)

These supersede earlier sections wherever they conflict:

- **LLM ensemble: Anthropic-only.** No OpenAI fallback. The deterministic Tier-3 (window-delta + oracle-gap, composite ≥ 0.6) catches every LLM failure path.
- **Operator alerts: Telegram bot via BotFather.** Replaces the original Discord webhook plan — Telegram has reliable global push and supports inbound `/halt` commands from the operator's phone.
- **Sizing rule: $5 flat per trade for the first 100 live trades.** Then transition to fractional Kelly only after a real win-rate exists. Initial bankroll **$1,000** (locked decision #10).
- **Wallet topology: Funder/Signer separation from Phase 1.** Funder holds working capital; Signer never holds more than 2 days of bankroll. Hardware wallet for the Funder triggers at $2k bankroll, not day 1.
- **Order submission: Polymarket gasless relayer.** Orders never hit the public Polygon mempool — closes the MEV/front-running attack surface. See `Polymarket/agent-skills/gasless.md`.
- **Phase 1 ordering: derive credentials → test signing → THEN fund.** Never fund a wallet whose L2 auth flow is unverified.
- **Obsidian: laptop-only vault.** Bot writes runbooks/postmortems to `state/` in the git repo; laptop pulls and Obsidian indexes the local copy. The bot never runs Obsidian.
- **Phase 3 LLM-vs-deterministic A/B test.** LLM ensemble retained only if backtest win-rate uplift over the deterministic baseline is ≥ 3 percentage points.
- **Time: UTC everywhere** — logs, DB timestamps, Obsidian daily notes.

---

## 0. The thesis (read first)

Polymarket runs a series of 5-minute binary markets on whether BTC closes higher or lower than its starting price, settled by Chainlink BTC/USD on Polygon. Markets are deterministic: window_ts = `floor(now/300)*300`, slug = `btc-updown-5m-{window_ts}`. Resolution = the Chainlink snapshot at `window_ts + 300`.

**Where the edge comes from (ranked):**

1. **Oracle latency.** Chainlink BTC/USD on Polygon is reported as a **60s heartbeat with no deviation threshold** — time-driven only. Spot can move 0.3–0.5% while the oracle is silent. **PENDING ON-CHAIN VERIFICATION in Phase 2** — claim derived from a Medium article and Chainlink's public dashboard; bot does not advance to Phase 3 until 24h of captured oracle events confirms median heartbeat ∈ [55s, 65s] and zero sub-60s deviation-triggered updates. If verification fails, the entire thesis must be re-evaluated.
2. **Last-10-second dynamics.** ~15–20% of windows are decided in the final 10 seconds. Entering at T-10s lets you read the near-locked outcome before the orderbook fully prices it (tokens still sub-$0.95).
3. **Window delta dominates the strategy.** "Where is BTC now vs window-open?" is the single highest-weight signal — heavier than RSI/EMA/etc. combined.
4. **Maker rebates** (CLOB v2). Resting limit orders close to mid earn daily USDC rebates from 100% of taker fees. Free yield on inventory if you size carefully.
5. **Latency-arb between exchanges and Polymarket.** Spot bots quote-stuff Binance/Coinbase 100ms ahead of Polymarket UI updates.

**Where the edge is NOT:** TA on a 5-minute timeframe (RSI/EMA on 1m candles is mostly noise — the Archetapp post-mortem proves it). Manual trading. Deep-volume markets (the inefficiency lives in thin books).

---

## 1. Tooling layout (decided)

| Layer | Choice | Why |
|---|---|---|
| **Language** | Python 3.11+ | py-clob-client + NautilusTrader native; speed-to-correctness wins over Rust for 5-min cadence |
| **Trading engine** | [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) | Production-grade, deterministic event-driven, official Polymarket adapter, real backtest engine |
| **Order client** | [Polymarket/py-clob-client](https://github.com/Polymarket/py-clob-client) | Official; handles L1+L2 auth & EIP-712 signing |
| **Spot data** | Binance WS (BTC/USDT) + Coinbase WS (BTC/USD) | Free, low-latency, redundant |
| **Oracle truth** | Chainlink aggregator on Polygon, read via Chainstack/Alchemy/QuickNode RPC | The literal source of resolution |
| **Storage** | SQLite for trades/PnL; Parquet for tick history; Obsidian for runbooks/notes | Simple, durable, no external deps |
| **VPS** | AWS Lightsail **eu-west-1 (Dublin)**, 2 vCPU / 4GB / NVMe | Sub-5ms to CLOB (eu-west-2 London), no UK Polymarket geo-block |
| **Memory vault** | Obsidian on laptop only + [iansinnott/obsidian-claude-code-mcp](https://github.com/iansinnott/obsidian-claude-code-mcp) | Vault stays personal on laptop. Bot writes markdown to `state/` in the git repo; laptop pulls; Obsidian indexes the local copy |
| **Backtest data** | [evan-kolberg/prediction-market-backtesting](https://github.com/evan-kolberg/prediction-market-backtesting) | Already-built Polymarket adapter for NautilusTrader's backtest engine |
| **Risk** | $5 flat for first 100 trades → fractional Kelly thereafter; per-window cap; daily loss circuit breaker; rolling-100 win-rate drift detector | Pre-Kelly learning budget; no false confidence from a backtested Kelly fraction |
| **Monitoring** | Prometheus exporter + Grafana Cloud (warn/info) + **Telegram bot via BotFather (critical/escalation, mobile push, inbound `/halt`)** | Telegram is reliable globally and supports remote kill from phone |
| **Secrets** | `direnv` + `.envrc` (gitignored) on VPS, `age` for encrypted backup of private key | No cloud secret manager required at this scale |
| **Process supervisor** | `systemd` unit on the VPS (auto-restart, journalctl logs) | Standard linux, no extra install |

### Claude side

| Tool | Use |
|---|---|
| **Claude Code (this CLI)** | Primary dev environment |
| **Obsidian MCP** (above) | Read/write the memory vault; every research note, runbook, postmortem |
| **`Polymarket/agent-skills`** | Drop the official skills repo into `~/.claude/skills/` so Claude has authenticated knowledge of every Polymarket primitive (auth, orders, WS, token ops, bridging, neg-risk, gasless) |
| **GitHub MCP** (`gh` CLI is fine) | Pulling reference repos (py-clob-client, NautilusTrader, etc.) |
| **`/init`** | Generate the project's CLAUDE.md once layout is on disk |
| **`/security-review`** | Run before each phase that touches signing or fund movement |
| **No autonomous trading via MCP** | All live trading happens from the bot binary on Dublin VPS, not from Claude Code |

### Polymarket bot MCPs (research/paper, NOT live execution)

- [caiovicentino/polymarket-mcp-server](https://github.com/caiovicentino/polymarket-mcp-server) — read state and *paper* trade from chat.
- [artvandelay/polymarket-agents](https://github.com/artvandelay/polymarket-agents) — odds, orderbook, spread, history tools.
- [agent-next/polymarket-paper-trader](https://github.com/agent-next/polymarket-paper-trader) — sim-only, useful for "what would happen if".

> Live trading runs on the bot, on the VPS. The MCPs are for *exploring* and *paper trading* via chat, never for production order flow.

---

## 2. Architecture (one diagram, in words)

```
                Dublin VPS (AWS Lightsail eu-west-1)
                ┌──────────────────────────────────────────┐
                │                                          │
   Binance WS ─►│  spot_feed.py  ──┐                       │
   Coinbase WS ─►│                  │                       │
                │                   ▼                       │
   Polygon RPC ►│  oracle_watcher.py ──► signal_engine.py ──► risk_manager.py ──► order_router.py ──► Polymarket CLOB
                │                                                                       (py-clob-client + NautilusTrader exec)
                │                   ▲                                  ▲                                          ▲
   Polymarket WS►│  market_feed.py ─┘                                   │                                          │
                │                                                       │                                          │
                │  trades.db (SQLite) ◄── PnL & fill log ◄───────────────┘                                          │
                │  ticks/*.parquet    ◄── bar/quote archive                                                         │
                │                                                                                                  │
                │  prom_exporter (9100) ─► Grafana Cloud + Discord alerts                                           │
                └──────────────────────────────────────────┘
                                                                                                                   │
                Laptop (your machine, this Claude Code session)                                                    │
                ┌──────────────────────────────────────────┐                                                       │
                │  Obsidian vault ◄──── obsidian-claude-code-mcp ◄── Claude Code ◄── PR review / paper trades / postmortems
                │  /runbooks/  /research/  /postmortems/  /strategy-notes/                                          │
                └──────────────────────────────────────────┘
```

Three loops:
- **Resolution loop** (per second): pull spot, pull oracle, recompute "what does this market resolve as if it ended now."
- **Execution loop** (T-30s, T-10s, T-5s): fire orders by deadline, never skip.
- **Supervisor loop** (every minute): heartbeat, balance check, kill-switch evaluation.

---

## 3. Phased plan (track here, mirror to Obsidian)

Each phase has a **gate** — concrete criteria you must hit before advancing. No skipping.

### Phase 0 — Foundations (laptop, ~½ day)
- [ ] Install Python 3.11, uv (or poetry), node (for Obsidian MCP).
- [ ] Install Obsidian; create vault `polymarket-bot/`. Folders: `runbooks/`, `research/`, `postmortems/`, `strategy-notes/`, `daily/`.
- [ ] Wire `iansinnott/obsidian-claude-code-mcp` to Claude Code. Verify Claude can read/write notes.
- [ ] Clone reference repos into `references/`: `py-clob-client`, `agent-skills`, `agents`, `poly-market-maker`, `Archetapp/7680adabc48f812a561ca79d73cbac69`, `evan-kolberg/prediction-market-backtesting`, `aulekator/Polymarket-BTC-15-Minute-Trading-Bot`.
- [ ] Drop `Polymarket/agent-skills` into `~/.claude/skills/`.
- [ ] Run `/init` to seed CLAUDE.md.
- **Gate:** Claude Code can read/write a note in Obsidian. All reference repos cloned. CLAUDE.md committed.

### Phase 1 — Wallet & auth (laptop, ~½ day)
- [ ] Create **two** fresh dedicated Polygon EOAs: **Funder** (working capital, key on laptop, never on VPS) and **Signer** (used by bot, key on laptop in Phase 1, will move to VPS in Phase 5).
- [ ] Use `setup_creds.py` pattern from py-clob-client to derive L2 creds for the **Signer** (apiKey, secret, passphrase).
- [ ] Store Signer creds in `.envrc` (gitignored) and back up an `age`-encrypted copy. Funder key in a separate `age`-encrypted file, never on the same machine as the running bot.
- [ ] **Test signing without funding:** issue a signed read-only call against `/info` to verify L2 auth works.
- [ ] **Only after signing verified:** fund Funder wallet with ~$5 MATIC + $50 USDC. Sweep $20 from Funder → Signer for live test.
- [ ] Place a $5 limit order via the **Polymarket gasless relayer** on a non-time-critical market and cancel it.
- **Gate:** can sign requests, read account state, place + cancel orders via gasless relayer end-to-end with $5.

### Phase 2 — Read-only data plane (laptop, 1–2 days)
- [ ] `market_feed.py`: subscribe to the active 5m BTC market via WS, archive snapshots to Parquet.
- [ ] `spot_feed.py`: Binance + Coinbase WS for BTC, archive ticks.
- [ ] `oracle_watcher.py`: subscribe to Chainlink BTC/USD `AnswerUpdated` events on Polygon; archive every update.
- [ ] Sanity check: at any time, you can answer "what does this market resolve to if it ends now" within 50ms of last spot tick.
- **Gate:** 24h of clean data captured for all three streams. No gaps. Cross-validation: oracle update timestamps and spot timestamps line up.

### Phase 3 — Backtest harness + LLM A/B test (laptop, 3–4 days)
- [ ] Wire NautilusTrader's Polymarket adapter (or fork `evan-kolberg/prediction-market-backtesting`) to your captured Parquet data.
- [ ] **Implement deterministic baseline first:** `signal = w1 * (spot_now - window_open) / window_open + w2 * (spot_now - chainlink_last) / chainlink_last`. Fire only when |signal| > 0.6 AND time-to-close ∈ [10s, 30s].
- [ ] Simulate fills using orderbook history (top 5 levels), $4.75 min, slippage model that includes self-impact on $5K-$50K window books.
- [ ] **Top up Anthropic credits to Tier 2 ($200+) before running LLM passes.**
- [ ] Implement the 3-agent ensemble + meta-decider against captured data.
- [ ] **Walk-forward validation**: rolling 7-day train window, 1-day test window, 30 days total.
- [ ] **A/B comparison: deterministic-only vs LLM-augmented.** Report win-rate uplift, latency overhead, $/decision.
- **Gate:** ≥2,500 simulated trades; deterministic win-rate after fees ≥ 53%; **LLM ensemble retained only if uplift ≥ 3pp over deterministic baseline.** If LLMs lose this test, ship the deterministic strategy and revisit ensemble in Phase 8.

### Phase 4 — Paper trading on the live venue (14 days minimum)
- [ ] Add `mode: paper` switch — bot consumes live data, computes signals, places orders into a SQLite shadow book, marks them filled if price would have hit on real fills.
- [ ] **Schema validation + refusal handling** wraps every LLM call (if LLM ensemble survived Phase 3). Invalid responses → agent abstains; <2 valid agents → Tier-3 fires. No `None` reaches the meta-decider.
- [ ] Run for **14 calendar days, must include at least one CPI/FOMC release, one weekend low-volume period, and one >2% BTC daily move.** Extend the window if not covered.
- [ ] **Validate the simulator** against 100 hypothetical fills: compare simulated fill price to actual top-of-book at that moment within 1¢.
- [ ] Compare paper PnL to backtested PnL. Investigate every divergence > 20%.
- **Gate:** paper PnL within 20% of backtest expectation, simulator validated, zero unhandled exceptions over 14 days, all three regime conditions met.

### Phase 5 — VPS provisioning (~½ day)
- [ ] Provision AWS Lightsail eu-west-1 Dublin, 2vCPU/4GB/80GB NVMe. Ubuntu 24.04.
- [ ] Harden: ssh-key only (port 2222), ufw, fail2ban, unattended-upgrades, non-root user, chrony for clock discipline.
- [ ] Install Python 3.11, uv, redis (for inter-process state), prometheus-node-exporter, litestream (for trades.db replication).
- [ ] **Latency check the WS endpoint specifically:** `wscat` round-trip to `wss://ws-subscriptions-clob.polymarket.com/ws/market`. p50 < 5ms, p99 < 15ms.
- [ ] Two systemd units: `bot.service` (production) and `bot-staging.service` (paper-mode against live data, separate port). Promote staging → prod via tagged release + `git pull` + restart.
- [ ] Prometheus → Grafana Cloud (warn/info dashboards). **Telegram bot via BotFather** for critical alerts; configure `/halt` inbound command.
- [ ] Move Signer key to VPS via age-encrypted transfer; confirm secure storage in `.envrc` with mode 0600.
- **Gate:** `systemctl status bot-staging` healthy, paper-mode capturing live data, WS p99 < 15ms confirmed, Telegram alerts test-fired and received on phone, `/halt` inbound command tested.

### Phase 6 — Live with kill-switches (14 days minimum)
- [ ] Initial Funder bankroll: **$1,000**. Signer holds **≤ $100** at any time. Excess sweeps Funder → cold/Funder-hot.
- [ ] **Sizing: $5 flat per trade for the first 100 live trades.** Skip windows where confidence < 0.6 composite. Do not switch to fractional Kelly until 100 trades have produced an empirical win-rate.
- [ ] Daily loss circuit breaker: **-$50 (5%)** → bot exits and pages Telegram. Rolling-100-trade win-rate drift detector: drop below `expected - 2σ` → halt and page.
- [ ] **Five kill-switches:**
  1. Heartbeat: any feed silent > 10s → halt new entries + Telegram alert.
  2. Slippage: avg fill slippage > 2¢ over 10 trades → halt + alert.
  3. Drawdown: **-$50 daily or -$100 cumulative** → systemd stop + Telegram page.
  4. Reconciliation drift: on-chain USDC vs internal bankroll mismatch > $0.50 → halt + alert.
  5. Win-rate drift: rolling-100 win-rate < expected - 2σ → halt + alert.
- [ ] Daily ritual: compare live PnL to paper-mode prediction (running in parallel on staging port); investigate every >$3 divergence; postmortem in `state/postmortems/` for any kill-switch trip.
- **Gate:** 14 calendar days live, all five kill-switches tested at least once (synthetically), zero unexplained losses, ≥100 trades executed with empirical win-rate documented.

### Phase 7 — Scale + maker rebates (ongoing)
- [ ] Scale bankroll only after a positive 7-day live run. Step: $1k → $3k → $10k → $30k. No skipping rungs. Hardware wallet trigger at the $3k rung (resolves OD-6).
- [ ] Add a maker layer: park resting limit orders close to mid on windows where signal is weak — earn the daily rebate while staying flat.
- [ ] Add a second strategy variant in shadow mode (e.g. T-5s flip-on-momentum) and let them compete; winning variant takes capital. Pattern from `ThinkEnigmatic/polymarket-bot-arena`.
- [ ] Quarterly: postmortem in Obsidian; refit weights on last 30 days.

### Phase 8 — Hardening (ongoing)
- [ ] Migrate from USDC.e to native Polymarket-USD as the migration completes (per Polymarket announcement).
- [ ] Second VPS in Frankfurt as warm standby; DB replicates via litestream.
- [ ] Multi-account proxy wallets for size > $50k (per-account exposure caps).
- [ ] On-call rotation (you, with phone alerts).

---

## 4. Risk register (read every phase)

- **Geo-restriction risk.** Polymarket geofences UK + US + several others. Dublin VPS is fine; do not run from `eu-west-2` or US regions. Don't connect personal wallet from blocked geos via the UI.
- **Wallet compromise.** A leaked private key drains everything instantly. Use a *fresh* wallet, age-encrypt the key, never paste it in chat, never check it in.
- **Oracle reorg / stuck oracle.** Polygon reorgs are rare but possible. If Chainlink misses a heartbeat (rare on Polygon, but happens), every market resolves to the *last* answer at end-time — design assumes this.
- **Settlement migration.** USDC.e → native USDC ("Polymarket USD") rollout is in progress; bot must double-write/read during the transition.
- **Adverse-selection.** You are competing with bots running co-located in eu-west-2. Your edge is *not* raw latency — it's signal quality + last-10-second timing. Don't kid yourself you'll out-race them on raw round-trips.
- **Min-order math.** 5-share minimum × $0.95 = $4.75. At $1k bankroll with $5 flat sizing, every window is fundable. Once Kelly transitions, take orders dominate until per-trade size > $20.
- **Tax / regs.** Track every trade for taxes; jurisdiction-dependent.

---

## 5. What to do *right now* (next 60 minutes)

1. **Confirm the plan above is what you want.** Push back on any choice.
2. **Paste the three tweet texts** (the X.com server-side fetch is paywalled — I can't read them). Once you do, I'll fold the specific claims into the right phase.
3. Bankroll cap for Phase 6 = **$1,000** (locked).
4. Decide Obsidian vault location (default: `~/Documents/polymarket-bot-vault/`).

After that: I'll start Phase 0 — clone references, set up Obsidian MCP, scaffold the project — and pause at every phase gate for your sign-off.

---

## Appendix A — Source links

- [Polymarket dev docs](https://docs.polymarket.com/developers/)
- [py-clob-client](https://github.com/Polymarket/py-clob-client) · [agent-skills](https://github.com/Polymarket/agent-skills) · [agents](https://github.com/Polymarket/agents) · [poly-market-maker](https://github.com/Polymarket/poly-market-maker)
- [NautilusTrader Polymarket integration](https://nautilustrader.io/docs/latest/integrations/polymarket/)
- [Archetapp 5m bot reference gist](https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69)
- [Benjamin-Cup Medium: 5-min market edges](https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196)
- [QuantVPS — Polymarket server location](https://www.quantvps.com/blog/polymarket-servers-location)
- [Chainlink BTC/USD on Polygon (60s heartbeat, no deviation)](https://data.chain.link/feeds/polygon/mainnet/btc-usd)
- [Polymarket CLOB v2 + maker rebates](https://help.polymarket.com/en/articles/13364471-maker-rebates-program)
- [iansinnott/obsidian-claude-code-mcp](https://github.com/iansinnott/obsidian-claude-code-mcp)
