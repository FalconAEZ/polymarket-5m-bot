# Phase S — High-volume market-maker bot — phased plan

**Authored:** 2026-05-20.
**Branch:** `claude/phase-S-market-maker` @ `9516f39`.
**Scope:** planning artifact only; no code.
**Source-of-truth design:** [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md).
**Source-of-truth research:** [runbooks/S-mmb-research-2026-05-20.md](S-mmb-research-2026-05-20.md).
**Operator pivots locked 2026-05-20:** $1k bankroll, paper-mode-is-fake → live-micro is the real edge gate, VPS dormant.

"High volume" at our scale = MMB's own throughput ceiling (≈10 markets concurrent × 6 orders × ~12 windows/hour = ~720 orders/hour theoretical max), NOT bonereaper's absolute number. At $1k bankroll with $5–$10 per level we will not match his queue position or his ~30 orders/window — we will produce *enough* fills for the per-trade EV signal to be statistically observable.

---

## 1. Inventory of reusable infrastructure

### 1.1 VPS + ops (Phase 5 — already shipped, currently DORMANT)

| Component | Path | Status for MMB |
|---|---|---|
| Dublin Lightsail eu-west-1 box | `ops@108.132.51.116:2222` | Reuse as-is. 13–17ms app RTT to CLOB. |
| SSH hardening (Phase 5.1) | configured on box | Reuse. Key at `~/Desktop/LightsailDefaultKey-eu-west-1.pem`. |
| Runtime install (Phase 5.2) | `uv`, Python 3.11, venv, deps | Reuse. py-clob-client already in lockfile. |
| systemd unit pattern | `runbooks/systemd/bot.service`, `bot-staging.service`, `tg-alerter.service`, `litestream.service` | Adapt template → new `bot-mm.service`. |
| Latency probe | `runbooks/gate-evidence/phase-5.3-latency.txt` + `scripts/measure_clob_latency.py` | Adapt for cancel-latency probe (Session 3 deferred S.1.1 item). |
| Litestream S3 backup | `runbooks/litestream.yml`, `litestream.service` | Reuse — add MMB sqlite paths if MMB ships any (decision-log is JSONL today, no DB needed initially). |
| grafana-agent → Grafana Cloud | runtime config on box | Reuse for MMB metrics; needs new `bot-mm` metric scope. |
| Halt sentinel mechanism | `state/halt.sentinel` + reader in `_live/alerter/halt.py` + writer pattern | Reuse as-is. Already in place from operator halt 2026-05-20. |

### 1.2 Wallet + auth (Phase 1A — already shipped)

| Component | Detail | Status for MMB |
|---|---|---|
| Funder | `0x512D...5d22` | Reuse. Holds working capital. |
| Signer | `0x8d97...2B4A` | Reuse for MMB — single-signer-for-both-strategy-classes is the default unless operator splits (open question §5). |
| Signature type | `2` (GNOSIS_SAFE) | Reuse — verified for BTC 5m (S.1.1 Q5). |
| Auth path | OD-4 (Phase 1A): standard CLOB API, no relayer, Signer pays own MATIC | Reuse. Decision #17 (gasless relayer) does NOT apply to MMB maker orders (no MEV surface — explained in S.1.1 Q5). |
| Credential derivation | `scripts/derive_creds.py` | Reuse — produces L2 `apiKey/secret/passphrase`. |
| USDC.e allowance | NOT YET SET on Signer | **GAP** — see §2. One-time on-chain tx before S.6 live. |
| MATIC for gas | Funder must seed Signer with small MATIC for the one allowance tx | **GAP** — operator action. |

### 1.3 Dependencies (already pinned in `pyproject.toml`)

| Package | Version pin | MMB use |
|---|---|---|
| `py-clob-client` | `>=0.34.6` | L1/L2 auth, order place + cancel, heartbeat, orderbook reads. |
| `eth-account` | `>=0.13.7` | EIP-712 signing for L1 + onchain allowance tx. |
| `httpx` | `>=0.28.1` | Gamma + Data API calls (py-clob-client uses this under the hood). |
| `websockets` | `>=16.0` | CLOB market + user channel subscriptions (Session 3+). |
| `pydantic` | `>=2.13.3` | dataclass alternatives if we need stricter validation on order payloads. |
| `ta` | `>=0.11.0` | MMD (market-mode detector) — already in use; MMB likely doesn't need it but available. |
| `redis` | `>=5.0.0` | Alerter queue (Phase 5.5); reuse for MMB alerts. |
| `fastapi` + `uvicorn` | pinned | Dashboard server (Session 4 surface). |

### 1.4 Polymarket reference (already cloned)

| Component | Path | MMB use |
|---|---|---|
| Polymarket agent-skills | `~/.claude/skills/agent-skills/` | Loaded this session for S.1.1. Files: `authentication.md`, `order-patterns.md`, `market-data.md`, `websocket.md`, `ctf-operations.md`, `bridge.md`, `gasless.md`. |
| Contract addresses | in skill `SKILL.md` | CTF Exchange = `0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E` (the exchange MMB routes to per S.1.1 Q5). USDC.e = `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`. |

### 1.5 Halt + Telegram alerter (Phase 5.5)

| Component | Path | MMB use |
|---|---|---|
| Halt sentinel writer | `src/polymarket_bot/_live/alerter/halt.py` | Reuse — MMB writes via same `write_halt_sentinel()` interface. |
| Halt sentinel reader | `scripts/run_paper.py` reads `state/halt.sentinel` | Adapt pattern for `scripts/run_mm_paper.py` + `scripts/run_mm_live.py`. |
| Telegram drain + `/halt` poller | `src/polymarket_bot/_live/alerter/service.py` | Reuse as-is. Currently DISABLED. Re-enable as `tg-alerter.service` Session 4. |
| Redis queue protocol | `src/polymarket_bot/_live/alerter/redis_queue.py` + `protocols.py` | Reuse — MMB pushes alerts to same queue. |
| Telegram formatting | `src/polymarket_bot/_live/alerter/formatter.py` | Adapt: add MMB-specific alert types (ladder placed, max-loss tripped, heartbeat-miss). |

### 1.6 Decision-log pattern (Phase 11.A.X.B — inode-stability defense)

| Component | Path | MMB use |
|---|---|---|
| Append-only JSONL | `state/decisions/<UTC>.jsonl` | Adapt: MMB writes to `state/mm-decisions/<UTC>.jsonl` (separate namespace). |
| FD inode stability | `_paper/decision_log.py` | Reuse pattern. Prevents the 8.5h orphan-FD incident from re-occurring. |
| `resolve_decisions.py` | `scripts/resolve_decisions.py` | Adapt: MMB needs `scripts/resolve_mm_windows.py` (window-end payout resolver) — or extend the existing script to honor MMB record shape. |

### 1.7 BankrollTracker pattern (Phase J.1 / 11.A — replay)

| Component | Path | MMB use |
|---|---|---|
| Bankroll dashboard | `src/polymarket_bot/dashboard/bankroll.py` | Read-only viewer — adapt to read MMB's separate bankroll envelope. |
| Replay-on-startup pattern | embedded in v2.1 strategy via `BANKROLL_REPLAY_ENABLED` env | Adapt: MMB needs its own MM_BANKROLL_REPLAY logic reading `state/mm-decisions/*.jsonl`. |
| `PMB_STARTING_BANKROLL` env | honored by dashboard (`9516f39` fix) | New env: `MM_STARTING_BANKROLL=1000` (decision #10 baseline). |

### 1.8 Test + verify harness (Phase 0+, ongoing)

| Component | Path | Status |
|---|---|---|
| `make verify` | runs `lint` (ruff) + `type` (mypy --strict) + `test` (pytest) | Reuse. Baseline 728 tests passing after Session 2 (partial). |
| `mypy --strict` | configured in `pyproject.toml` | Required for all new MMB modules. |
| `ruff check` | configured in `pyproject.toml` | Required. |
| `import-linter` | configured | Enforces `_paper` ↔ `_live` separation. MMB strategy stays under `strategies/`. |
| `pre-commit` | configured | Reuse. |
| pytest fixtures pattern | `tests/strategies/test_kelly_config.py` etc. | Followed for MMB tests (this session). |

### 1.9 Backtest harness (Phase 3.1.5 → 16.B)

| Component | Path | MMB use |
|---|---|---|
| Backtest types | `src/polymarket_bot/backtest/types.py` | Reuse `Decision`, `MarketEvent`, `WindowBoundary` shapes if compatible; otherwise MMB ships its own action types (already shipped in `market_maker.py`). |
| Replay engine | `src/polymarket_bot/backtest/replay.py` | Reuse for orderbook reconstruction from subgraph data. |
| Fills simulator | `src/polymarket_bot/backtest/fills.py` | Adapt: existing fill semantics are taker-side; MMB needs a maker-side fill model that respects the simulator floor + depth guard at commits `46b3ce6` / `10e08e8` / `f8da51f`. |
| Walk-forward | `src/polymarket_bot/backtest/walk_forward.py` | Reuse if Session 2 backtest does walk-forward; probably not needed for plumbing-only sanity check. |
| `scripts/run_backtest.py` | entrypoint | Reuse pattern; MMB has `scripts/research/mmb_backtest.py` as a new script. |

### 1.10 Strategy module conventions (Phase G → P, refined)

| Component | Path | MMB compliance |
|---|---|---|
| Protocol | `src/polymarket_bot/strategies/protocol.py` | MMB does NOT implement — needs multi-order interface (documented in `market_maker.py` header). |
| Kelly config | `src/polymarket_bot/strategies/kelly_config.py` | MMB's Kelly logic is inline in `j7_priors.bet_size()` — separate from v2.1's KellyConfig because of cross-side sizing semantics. |
| Sizing | `src/polymarket_bot/strategies/sizing.py` | Not used by MMB. |
| Conventions | docstring header ≥80 chars (rule #5), type hints (#6), no TODOs (#8), stochastic-injection (#10) | All followed in this session's MMB code. |

### 1.11 Bonereaper data corpus (Phase A + this session)

| Component | Path | MMB use |
|---|---|---|
| 30d audit (n=306,997) | `runbooks/research/bonereaper-{spot-vs-book,microstructure}-30d-2026-05-08.md` | Aligned-WR + per-tier + time-bucket priors. |
| 30d raw fills | `state/research/bonereaper/{subgraph_fills_{maker,taker},spot-vs-book-joined,weekly_*_2026-05-06}.json` | Inputs to backtest cross-validation (Session 2). |
| 7d fresh refresh | `state/research/bonereaper/weekly_*_2026-05-19.json` | Confirms direct WR 50.93% on n=21,630; stable. |
| J.7 priors digital | `design/j7_priors.{json,md}` | Loaded at runtime by `J7Priors` class. |
| Refresh script | `scripts/research/weekly_audit.py`, `bonereaper_spot_vs_book.py`, `bonereaper_microstructure.py` | Reuse; cron / systemd timer wiring is a §2 gap. |

### 1.12 Phase S artifacts already shipped (this conversation)

| Component | Path | Status |
|---|---|---|
| Design lock | `design/S.1-market-maker-bot.md` | LOCKED (272 lines, updated 2026-05-20 for $1k pivot). |
| Priors data | `design/j7_priors.{json,md}` | LOCKED. |
| S.1.1 research | `runbooks/S-mmb-research-2026-05-20.md` | CLOSED. |
| J7Priors loader | `src/polymarket_bot/strategies/j7_priors.py` | 189 LOC, 18 tests green. |
| MarketMakerStrategy + helpers | `src/polymarket_bot/strategies/market_maker.py` | 689 LOC, 36 tests green. |
| Phase ledger | `state/phases/phase-S-market-maker.md` | ongoing. |
| Decisions #22 + #23 | `memory/project_decisions.md` | LOCKED. |
| Session 2 prompt | `phase-prompts/phase-S-session-2-core.md` | staged. |

---

## 2. Gap analysis

What MMB needs that doesn't yet exist. Each row names a file path it would land at + the prior gaps it depends on.

| # | Gap | Path | Depends on |
|---|---|---|---|
| G1 | **Backtest harness** | `scripts/research/mmb_backtest.py` + output `runbooks/research/mmb-backtest-2026-05-XX.md` | §1.9 backtest module + §1.11 bonereaper corpus + Session 2 modules (shipped). |
| G2 | **CLOB order client wrapper** | `src/polymarket_bot/_live/clob_orders.py` | py-clob-client (§1.3); Polymarket skill (§1.4). Implements: `place_maker_limit(level, post_only=True, neg_risk=False)`, `cancel(order_id)`, `cancel_all()`, `get_orderbook(token_id)`, `heartbeat()`. |
| G3 | **Heartbeat task** | inside G2's module or new `src/polymarket_bot/_live/mm_heartbeat.py` | G2. 5s asyncio cadence; 2-miss → write halt sentinel + push Telegram alert. |
| G4 | **Paper-mode MMB runner** | `src/polymarket_bot/_paper/mm_runner.py` + `scripts/run_mm_paper.py` | Session 2 modules (shipped); G2 (mocked CLOB for paper); §1.5 halt reader; §1.6 decision log; §1.7 bankroll replay. Paper shakedown only — validates plumbing, NOT edge. |
| G5 | **Live-mode MMB runner** | `src/polymarket_bot/_live/mm_runner.py` + `scripts/run_mm_live.py` | G2 (real CLOB), G3 (heartbeat), G4 (shared logic factored out), §1.5 halt mechanism. |
| G6 | **USDC.e allowance one-time tx** | `scripts/mm_set_allowance.py` (new) | §1.2 wallet, Signer with MATIC. One-shot script the operator runs before S.6 live. Approves CTF Exchange (§1.4) for MAX_UINT256 USDC.e. |
| G7 | **MMB systemd unit** | `runbooks/systemd/bot-mm.service` | §1.1 template; G4/G5 entrypoints. Separate from `bot.service` + `bot-staging.service` so the two strategy classes never share process state. |
| G8 | **Dashboard panel** | `src/polymarket_bot/dashboard_server/mm_panel.py` + React side | §1.7 dashboard pattern; G4/G5 state files. Surface: per-window inventory, active orders, hourly PnL, top markets, kill-switch button. |
| G9 | **Prometheus metrics** | inline in G4/G5 — export via grafana-agent (§1.1) | §1.1 grafana-agent. Counters: orders_placed, orders_filled, orders_cancelled, heartbeat_missed, halt_triggered. |
| G10 | **Daily priors refresh** | `scripts/research/refresh_bonereaper_30d.py` + systemd timer | §1.11 audit scripts. Produces `state/research/bonereaper/aligned_priors_30d.json` daily 04:00 UTC; runtime J7Priors loader prefers this over the bootstrap. |
| G11 | **Empirical S.1.1 probes** | `runbooks/S-mmb-{fee,cancel-latency,rate-limit}-empirical-2026-05-XX.md` | G2 (real CLOB calls). Three deferred probes from S.1.1: realized maker fee, cancel latency p50/p95/p99, rate-limit ceiling. Run during S.4 against a low-volume market with $5 test orders. |
| G12 | **MMB-specific bankroll envelope** | `state/mm-bankroll/<UTC>.jsonl` + getter in G4/G5 | §1.7 BankrollTracker pattern + `MM_STARTING_BANKROLL=1000` env. Separate file namespace so the bankroll number doesn't conflate with the (now archived) directional bot's history. |

---

## 3. Phased plan (S.2 → S.6)

### S.2 — Backtest harness (close out Session 2)

| Field | Content |
|---|---|
| Scope | Build `scripts/research/mmb_backtest.py`; close out Session 2 acceptance gates. |
| Inputs | Session 2 modules (shipped); §1.9 backtest module; §1.11 bonereaper raw fills + subgraph data. |
| Deliverables | (a) `scripts/research/mmb_backtest.py` reconstructs per-second orderbook snapshots + simulates `MarketMakerStrategy` ladder placement + fills + payouts; (b) `runbooks/research/mmb-backtest-2026-05-XX.md` with per-day per-tier breakdown + cross-validation against bonereaper actuals on same windows; (c) `memory/checkpoint_phase_S_session_2.md` + MEMORY.md update; (d) `phase-prompts/phase-S-session-3-orders.md`. |
| Gate command | `uv run python scripts/research/mmb_backtest.py --lookback-days 7 && uv run pytest -q` |
| Pass criteria | Harness runs to completion; per-window $/window non-catastrophic on ≥5/7 days; cross-val within ±50% of bonereaper actuals (loosened gate per 2026-05-20 paper-is-fake pivot); 728+ pytest tests still green. |
| Calendar | 1–2 days. |
| Risks | (a) Subgraph orderbook reconstruction may be sparse or wrong-exchange-rooted (Phase A had this — fallback to per-market replay if needed); (b) cross-validation may fail by >10× — STOP and investigate simulator, don't tune strategy. |

### S.3 — Order management + paper runner (CLOB plumbing)

| Field | Content |
|---|---|
| Scope | Build G2 (CLOB client wrapper) + G3 (heartbeat) + G4 (paper runner). Run empirical S.1.1 probes (G11). |
| Inputs | Session 2 modules + S.2 backtest validated. |
| Deliverables | (a) `src/polymarket_bot/_live/clob_orders.py` — py-clob-client wrapper with `place_maker_limit`, `cancel`, `cancel_all`, `get_orderbook`, `heartbeat` (post-only + neg_risk=False bound by interface); (b) heartbeat asyncio task — 5s cadence, 2-miss → halt-sentinel + Telegram alert; (c) `src/polymarket_bot/_paper/mm_runner.py` + `scripts/run_mm_paper.py` — paper shakedown driving `MarketMakerStrategy` against a MOCKED CLOB to validate plumbing only; (d) ≥20 new tests for G2/G3/G4; (e) empirical probes for maker fee + cancel latency + rate limits → 3 short runbook addenda. |
| Gate command | `uv run python scripts/run_mm_paper.py --duration-min 60 && uv run pytest -q && uv run mypy --strict src/polymarket_bot/_live/clob_orders.py src/polymarket_bot/_paper/mm_runner.py` |
| Pass criteria | 60-min paper run with mocked CLOB completes cleanly; no orphaned orders in mock state; heartbeat task missed = 0; 3 probes write data to runbook addenda; tests green. |
| Calendar | 3–5 days (most complex session — networking + asyncio + the heartbeat correctness). |
| Risks | (a) py-clob-client may behave differently from skill docs on edge cases (e.g., heartbeat ID rotation) — buffer for empirical adjustments; (b) cancel latency may be > 100ms p95 — would force ladder repost rate to drop; (c) the 3 deferred S.1.1 probes may surface a non-zero maker fee that breaks Kelly sizing math — recalibrate before S.5. |

### S.4 — Dashboard + safety circuits + Telegram

| Field | Content |
|---|---|
| Scope | Build G7 (systemd unit), G8 (dashboard panel), G9 (Prometheus metrics). Re-enable `tg-alerter.service` and add MMB alert types. |
| Inputs | S.3 paper runner working. |
| Deliverables | (a) `runbooks/systemd/bot-mm.service` — systemd unit pointing at `scripts/run_mm_paper.py` initially (live entrypoint added in S.5); (b) MMB dashboard panel in `src/polymarket_bot/dashboard_server/` — per-window inventory + active orders + hourly PnL + top markets; (c) Prometheus counters wired via grafana-agent; (d) tg-alerter re-enabled with MMB alert formatter additions (`ladder_placed`, `daily_loss_tripped`, `heartbeat_missed`, `halt_engaged`); (e) test the kill switch: `MM_KILL_SWITCH=true` env flip → drain in <30s + Telegram ping; (f) intentional heartbeat-miss test → confirm server auto-cancel + sentinel write. |
| Gate command | `systemctl restart bot-mm.service && systemctl is-active bot-mm.service && systemctl is-active tg-alerter.service` then `MM_KILL_SWITCH=true systemctl restart bot-mm.service` then poll for drained state. |
| Pass criteria | Dashboard renders MMB state in browser preview; kill switch drains within 30s; intentional heartbeat-miss triggers sentinel + Telegram within 15s; daily-loss circuit-breaker test (force `today_realized_pnl = -$60`) writes sentinel. |
| Calendar | 2–3 days. |
| Risks | (a) Re-enabling tg-alerter loops in old halt sentinel as a "still halted" notification — handle gracefully (alerter knows current sentinel state); (b) dashboard rebuild may surface stale state from the directional bot's old data — namespace MMB state to its own panel. |

### S.5 — Live-micro deploy + 7-day soak (replaces "shadow")

| Field | Content |
|---|---|
| Scope | First real money. $1k bankroll. Live-micro caps: $5/level, $50 max gross per window, $50/day loss cap. Real orders, real queue position. |
| Inputs | S.3 + S.4 green; G6 USDC.e allowance set; Signer funded; halt sentinel removed. |
| Deliverables | (a) `src/polymarket_bot/_live/mm_runner.py` + `scripts/run_mm_live.py` — same lifecycle as paper runner but talks to real CLOB; (b) `bot-mm.service` re-pointed at the live entrypoint; (c) 7-day soak with operator daily checks; (d) Day-7 audit: `runbooks/research/mmb-live-micro-day7-2026-05-XX.md` — total realized PnL, per-tier per-day breakdown, fill-rate, cancel-rate, queue-position estimates, comparison to backtest projections. |
| Gate command | `systemctl is-active bot-mm.service` daily + operator manual review via dashboard. Day-7: realized PnL on the soak. |
| Pass criteria (S.5 → S.6 promotion) | **Day-7 realized PnL > +$0** (i.e., net positive on the soak); **no incidents** (no halt-sentinel trips, no heartbeat misses beyond noise, no orphan orders surviving > 1 minute). If Day-7 is breakeven or marginally negative: extend soak 7 days. If Day-7 is < -$50 (a full daily-loss cap): STOP, do not advance, write postmortem. |
| Calendar | 1 day deploy + 7 days soak. |
| Risks | (a) Edge non-transferability — bonereaper's edge may be queue-position-driven and our $5 levels get back-of-queue; this is the question S.5 *answers*, so an honest negative result here means MMB is structurally non-viable at $1k and we stop. (b) py-clob-client throttling — if rate limits bite, ladder cadence drops. (c) Operator vigilance — first real money; daily checks should not lapse. |

### S.6 — Scale-up to full $1k bankroll caps + 5-day soak

| Field | Content |
|---|---|
| Scope | Raise caps to scale-up column (MAX_INV $50, MAX_GROSS $100, MAX_DAILY_LOSS $100, MAX_BET $25). Same $1k bankroll; just higher per-window exposure. |
| Inputs | S.5 passed — Day-7 PnL net positive. |
| Deliverables | (a) `RiskCaps` overrides via env: `MM_RISK_CAPS=scale_up`; (b) `bot-mm.service` restart with new caps; (c) 5-day soak; (d) Day-5 audit — same shape as S.5 Day-7 but with higher-exposure caps. |
| Gate command | Same as S.5; PnL gate at Day-5. |
| Pass criteria (Phase S CLOSED) | Day-5 PnL > +$0; per-window order placement rate stable within ±15% of S.5 baseline. |
| Calendar | 5 days. |
| Risks | (a) Variance scales linearly with exposure — Day-5 noise could mask edge; budget for an extension if needed. (b) If S.6 PnL is worse than S.5 (higher exposure → lower PnL), the edge is order-sized-bounded and we stop at S.5 caps permanently. |

---

## 4. Critical-path diagram

```
        +---------------------+
        |  Session 1 CLOSED   |  design + priors + research + decisions  (2026-05-19/20)
        +----------+----------+
                   |
                   v
        +---------------------+
        |  Session 2 partial  |  modules + tests   (2026-05-20)   ← currently here
        +----------+----------+
                   |
                   v
        +---------------------+
        | S.2 close: backtest |  1–2 days   ← next session
        +----------+----------+
                   |
                   v
        +---------------------+
        | S.3 orders + paper  |  3–5 days   ← most complex
        +----------+----------+
                   |   ┌── (parallelizable if 2nd dev exists; solo = serial)
                   v   v
        +---------------------+
        | S.4 dashboard +     |  2–3 days
        |     safety + tg     |
        +----------+----------+
                   |
                   v
        +---------------------+
        | G6: USDC allowance  |  ~1 hour operator tx + a few mins for confirmation
        +----------+----------+
                   |
                   v
        +---------------------+
        | S.5 LIVE-MICRO      |  1 day deploy + 7 days soak
        +----------+----------+
                   |
                   v
        +---------------------+
        | S.6 scale-up        |  5 days soak
        +---------------------+
                   |
                   v
        +---------------------+
        | PHASE S CLOSED      |  total to first live money: ~10–14 days
        +---------------------+  total to Phase S close: ~22–28 days
```

**Critical path (longest chain) = S.2 → S.3 → S.4 → G6 → S.5 → S.6 = serial.**

| Time-to milestone | Calendar |
|---|---|
| Time-to-first-live-order (S.5 deploy day) | **10–14 days from this plan's sign-off** (assumes daily focus; longer if intermittent). |
| Time-to-Phase-S-closed (S.6 Day-5 audit passes) | **22–28 days from sign-off.** |

Nothing in this critical path can be reasonably parallelized solo. S.4 has minor parallelization potential with S.3 if the dashboard work happens on a separate task, but the same operator can only context-switch so much without quality loss.

---

## 5. Open questions — RESOLVED 2026-05-20

### Q1. HW wallet wiring schedule (decision #12) — DEFERRED
**Resolution:** Option (c) — defer until bankroll bump past $2k is explicitly approved (operator instruction: "do what is recommended" + $1k bankroll is below the #12 trigger). HW wallet wiring is NOT a prerequisite for S.5 or S.6. If MMB succeeds and a future bankroll-bump session pushes past $2k, that session ships HW wallet wiring as its own hard prerequisite (own decision logged at that time).

### Q2. Dashboard re-enable timing — S.4
**Resolution:** Option (a) — re-enable `dashboard-server.service` as part of S.4 (operator instruction: "do what is recommended"). Needed for live-micro visibility during S.5 + S.6 daily checks. Re-enabling early in S.4 (alongside Telegram alerter re-enable) gives time to verify the dashboard surfaces MMB state correctly before any real money flows.

### Q3. Signer wallet reuse vs split — REUSE
**Resolution:** Option (a) — reuse existing Signer `0x8d97...2B4A` (operator explicit: "reuse since we never used it on real trades"). The Signer derived in Phase 1A has only signed paper/test orders to date; reuse incurs zero key-gen overhead and avoids the friction of funding a new wallet. If future bankroll-isolation across strategy classes becomes important, a fresh Signer can be generated at that time without losing MMB history.

### Q4. PHASE_S_PLAN.pdf rendering — SKIP
**Resolution:** Option (c) — skip the PDF (operator instruction: "up to you"; markdown is the source of truth). This planning markdown + the design doc + the J.7 priors files + S.1.1 runbook are the durable record. PDF can be rendered as a closeout artifact at Phase S close IF the operator wants a packaged review document at that time.

### Implications for the phased plan

- **S.4 scope expands slightly** to include re-enabling `dashboard-server.service` + verifying MMB panel renders MMB state (G8) before S.5.
- **S.4 scope shrinks slightly** — no HW wallet wiring this phase; calendar estimate 2–3 days stands.
- **S.6 scope** stays at "scale-up caps with $1k bankroll." No bankroll bump in scope. If S.6 closes green and operator wants to bump past $2k, a new phase (Phase T?) opens with HW wallet wiring + bankroll-bump as its scope.
- **G6 (USDC.e allowance)** remains a one-time operator tx using the existing Signer — no key-gen step before it.

---

## 6. References

- [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md) — locked design
- [design/j7_priors.json](../design/j7_priors.json) + [design/j7_priors.md](../design/j7_priors.md) — priors data + companion
- [runbooks/S-mmb-research-2026-05-20.md](S-mmb-research-2026-05-20.md) — S.1.1 closure
- [state/phases/phase-S-market-maker.md](../state/phases/phase-S-market-maker.md) — phase ledger
- [state/sessions/2026-05-19-phase-S-kickoff.md](../state/sessions/2026-05-19-phase-S-kickoff.md) — Session 1 note
- [state/sessions/2026-05-20-phase-S-session-2-partial.md](../state/sessions/2026-05-20-phase-S-session-2-partial.md) — Session 2 partial note
- [memory/project_decisions.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md) — decisions #22 + #23
- [memory/checkpoint_phase_S_session_1.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_1.md) — Session 1 checkpoint
- [phase-prompts/phase-S-session-2-core.md](../phase-prompts/phase-S-session-2-core.md) — Session 2 prompt
- `~/.claude/skills/agent-skills/` — Polymarket official skill
