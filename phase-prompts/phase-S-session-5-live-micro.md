# Phase S — Session 5 prompt — Live-micro deploy + 7-day soak

**Authored:** 2026-05-20 (immediately after Session 4 close).
**Pre-conditions:** Session 4 CLOSED — `state/sessions/2026-05-20-phase-S-session-4-close.md` + `memory/checkpoint_phase_S_session_4.md` written.
**Risk class:** **FIRST REAL MONEY on MMB.** Live orders against the Polymarket CLOB at $1k bankroll. Live-micro caps: $5/level, $50 max gross/window, $50/day loss cap, MAX_BET=$10.
**Estimated duration:** ~1 day pre-deploy + 7-day soak (with daily operator check-ins).
**Branch:** `claude/phase-S-market-maker` (continue).

---

## What you're stepping into

Sessions 1-4 shipped: design + priors + research + strategy modules (878 LOC) + backtest harness + CLOB wrapper (Mock fully tested, Live skeleton untested) + heartbeat + paper runner (60s gate clean) + alerter MMB types + sentinel-on-gate-halt safety wiring + `bot-mm.service` systemd unit. 770 tests passing. 6 commits ahead of `9516f39`.

S.5 turns the key. Real money flows. The "is bonereaper's edge transferable to our scale" question gets answered by the 7-day soak, not by any backtest.

**Required reading:**

1. [memory/checkpoint_phase_S_session_4.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_4.md) — what's in place.
2. [design/S.1-market-maker-bot.md](../design/S.1-market-maker-bot.md) §2.4 + §4 risks (R1 edge non-transferability, R2 cross-side exposure).
3. [runbooks/research/mmb-backtest-2026-05-20.md](../runbooks/research/mmb-backtest-2026-05-20.md) Findings — especially the `<15%` tier loss + the queue-position caveat.
4. [memory/project_decisions.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md) #10 + #11 + #12 (bankroll, Funder/Signer split, HW wallet trigger at $2k — NOT crossed at $1k).
5. [~/.claude/skills/agent-skills/](file:///Users/hamad/.claude/skills/agent-skills/) — Polymarket reference.
6. State of VPS: dormant, all services disabled, `state/halt.sentinel` in place from 2026-05-20 operator halt.

---

## Pre-deploy steps (THE BAR for going live)

### P1 — USDC.e allowance on Signer

Operator hardware action. Signer `0x8d97...2B4A` must `USDC.approve(CTFExchange, MAX_UINT256)` once.

Write `scripts/mm_set_allowance.py`:
- Reads Signer PK from env (`PK_SIGNER`)
- Reads Funder MATIC balance — Signer must have ≥ ~$5 in MATIC for gas
- Calls `USDC.approve(0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E, MAX_UINT256)`
- Prints tx hash; waits for confirmation
- Saves tx hash + block number to `state/mm-allowance.json` for audit

Operator runs this once. Verify via Polygonscan.

### P2 — G11 empirical probes (deferred from S.3 + S.4)

Now that allowance is set, exercise `LiveClobOrderClient` against a low-volume BTC 5m market with $5 test orders.

1. **Maker fee** → `runbooks/S-mmb-fee-empirical-2026-05-XX.md`. Place 5 maker-limit BUYs at -$0.20 depths. Compare gross PnL vs net USDC.e settled. Delta = realized fee.
2. **Cancel latency** → `runbooks/S-mmb-cancel-latency-empirical-2026-05-XX.md`. Place + cancel 1000 orders sequentially. p50/p95/p99.
3. **Rate-limit** → `runbooks/S-mmb-rate-limit-empirical-2026-05-XX.md`. Increase rate until 429. Log headers.

If maker fee is non-zero (operator-empirical contradicts S.1.1 assumed-zero), recalibrate `J7Priors.bet_size` math:
- Effective EV per trade = `(p_win - fill_price - fee_rate)` not `(p_win - fill_price)`
- Tier-by-tier sensitivity check: which tiers stay +EV at the empirical fee?
- Update `design/S.1-market-maker-bot.md` §2.3 + push a doc-revision commit BEFORE live entrypoint.

### P3 — Author `scripts/run_mm_live.py`

Mirror `scripts/run_mm_paper.py` structure but:
- `client = LiveClobOrderClient(inner=...)` instead of `MockClobOrderClient()`
- `inner` constructed from py-clob-client with L2 creds (Phase 1A `scripts/derive_creds.py` produces them)
- Real heartbeat task — same `mm_heartbeat_loop` but pointed at the live client
- Real alert callback — pushes to Redis at `polybot:alerts` (the existing alerter queue). Format:
  ```python
  async def _push_alert(payload: dict) -> None:
      import json
      from redis.asyncio import Redis
      r = Redis.from_url(os.environ["REDIS_URL"])
      await r.lpush("polybot:alerts", json.dumps(payload))
  ```
- Read live orderbook from the CLOB at a configured cadence (start at 1s; tighten later if needed)
- Subscribe to user-channel WebSocket for fill notifications (or poll `/trades` at 5s cadence as a v1 simplification)

### P4 — Pre-deploy gate run

Before flipping ExecStart:

- `uv run pytest -q` → ≥770 passing
- `uv run mypy --strict scripts/run_mm_live.py src/polymarket_bot/_live/clob_orders.py` → green
- `uv run ruff check ...` → green
- Dry-run paper mode one more time (`scripts/run_mm_paper.py --duration-s 60`) → clean

### P5 — Re-enable auxiliary services on VPS

- `systemctl enable --now dashboard-server.service` (lets operator monitor)
- `systemctl enable --now tg-alerter.service` (Telegram alerts route)
- Verify the operator's Telegram receives an `info` test message (use a one-shot test push to `polybot:alerts`)

### P6 — Install bot-mm.service unit

- SSH to VPS, `git pull` to bring the 6+ Phase S commits.
- `sudo cp runbooks/systemd/bot-mm.service /etc/systemd/system/`
- Edit the ExecStart to point at `scripts/run_mm_live.py` (NOT run_mm_paper.py).
- `sudo systemctl daemon-reload && sudo systemctl enable bot-mm.service`
- DO NOT start yet — sentinel still in place.

### P7 — Remove halt sentinel + start

- `rm /home/ops/polymarket-5m-bot/state/halt.sentinel`
- `sudo systemctl start bot-mm.service`
- Tail journal + dashboard for the first 5 minutes; expect ladder placements visible in `state/mm-decisions/<UTC>.jsonl`

---

## Soak phase (7 days)

### Daily check-ins (operator)

Every 12-24h:
- Dashboard PnL panel: net realized today + cumulative
- `journalctl -u bot-mm.service --since "24h ago" | grep ERROR` — should be empty
- Telegram channel: any alerts? Heartbeat misses count?
- `tail -50 state/mm-decisions/$(date -u +%F).jsonl` — orders placing + draining cleanly?

### Day-1 audit at T+24h

`runbooks/research/mmb-day1-2026-05-XX.md`:
- Total realized PnL
- Fill rate (orders_placed_count / orders_filled_count)
- Per-tier fill distribution
- Heartbeat miss count
- Alert count + types
- Hours of "halt sentinel present" (should be 0)

If Day-1 PnL is < -$50: full circuit-breaker trip → halt + investigate. Do not let it ride.

### Day-7 audit (S.5 → S.6 promotion gate)

`runbooks/research/mmb-day7-2026-05-XX.md`:

| Gate | Pass condition |
|---|---|
| Day-7 cumulative PnL | > $0 (net positive over 7 days) |
| No incidents | 0 halt-sentinel trips, 0 unrecovered heartbeat misses, 0 orphaned orders > 1 min |
| Fill-rate | Within 25% of S.5 Day-1 baseline (no degradation) |
| `<15%` tier behavior | Confirm or refute Session 2 sim finding — does this tier lose money live? |
| Maker fee impact | Confirm or recalibrate (P2 empirical vs S.5 realized) |

**Pass → S.6 (scale-up caps).**
**Marginal/breakeven → extend soak 7 more days at live-micro.**
**Fail (< -$50 cumulative) → STOP. Postmortem at `runbooks/postmortems/2026-05-XX-mmb-s5-failure.md`. MMB strategy class possibly not viable at $1k.**

---

## Don't-do rules (operator-stated + locked)

- Do NOT re-enable `bot-staging.service` (directional bot). Stays disabled.
- Do NOT bypass P1-P7 ordering. Allowance must be set before any live order; probes must precede live deploy; tests must pass; auxiliary services must be up; sentinel must be in place until manual removal.
- Do NOT touch caps mid-soak. If $50/day trips spuriously, log it + raise in postmortem; don't loosen safety while live.
- Do NOT scale up bankroll past $2k without HW wallet wiring (decision #12).
- Do NOT mass-cancel orders manually unless via the kill-switch path. The bot owns its own cancel discipline.
- Do NOT change strategy logic (`market_maker.py` / `j7_priors.py`) during soak. Issues surface in the Day-7 audit; redesign happens between soaks.

---

## When you finish Session 5 (Day-7 audit passes)

1. `state/sessions/2026-05-XX-phase-S-session-5-close.md` — Day-7 audit numbers + soak narrative.
2. `memory/checkpoint_phase_S_session_5.md` — checkpoint for next session.
3. Update `MEMORY.md`.
4. Update `state/phases/phase-S-market-maker.md` — mark S.5 CLOSED, S.6 next.
5. Write `phase-prompts/phase-S-session-6-scaleup.md` (scale-up caps + 5-day soak).

---

## Reference

- Session 4 close: [state/sessions/2026-05-20-phase-S-session-4-close.md](../state/sessions/2026-05-20-phase-S-session-4-close.md)
- Phase plan: [runbooks/phase-S-high-volume-plan-2026-05-20.md](../runbooks/phase-S-high-volume-plan-2026-05-20.md)
- Polymarket skill: `~/.claude/skills/agent-skills/`
- Phase 1A wallet checkpoint: `memory/checkpoint_phase_1a.md`
- VPS access: `memory/reference_vps_ssh.md`
- Test-under-load: `memory/feedback_test_under_load.md`
- VPS deploy verification discipline: `memory/feedback_vps_deploy_verify_late.md`
- Pragmatic gate revision: `memory/feedback_pragmatic_gate_revision.md`
