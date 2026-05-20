# Phase S — Session 4 prompt — Dashboard + safety circuits + Telegram + G11 empirical probes

**Authored:** 2026-05-20 (immediately after Session 3 close).
**Pre-conditions:** Session 3 CLOSED — `state/sessions/2026-05-20-phase-S-session-3-close.md` + `memory/checkpoint_phase_S_session_3.md`.
**Estimated duration:** 2–3 days for dashboard/alerter + ~half day for G11 probes once allowance is set.
**Branch:** `claude/phase-S-market-maker` (continue).
**VPS status:** dormant. S.4 starts re-enabling auxiliary services. Directional bot stays disabled.

---

## What you're stepping into

Sessions 1–3 shipped: design + priors + research + strategy modules (878 LOC) + backtest harness + 54 strategy tests + CLOB wrapper + heartbeat + paper runner + 29 more tests + 60s paper gate clean (757 total passing). Now S.4 makes MMB observable + safe + close the deferred empirical probes.

**Required reading:**

1. [runbooks/phase-S-high-volume-plan-2026-05-20.md](../runbooks/phase-S-high-volume-plan-2026-05-20.md) §3 S.4 + §2 G8/G9/G11.
2. [memory/checkpoint_phase_S_session_3.md](../../../.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_S_session_3.md) — what's in place + carried-forward findings.
3. [src/polymarket_bot/_live/alerter/](../src/polymarket_bot/_live/alerter/) — existing alerter shape; reuse for MMB.
4. [src/polymarket_bot/dashboard_server/](../src/polymarket_bot/dashboard_server/) — v3 FastAPI dashboard pattern.
5. [runbooks/S-mmb-research-2026-05-20.md](../runbooks/S-mmb-research-2026-05-20.md) §5 deferred items — G11 probe targets.

---

## Deliverables

### D1 — Re-enable dashboard-server.service + add MMB panel

- `src/polymarket_bot/dashboard_server/mm_panel.py` (new) reads `state/mm-decisions/<UTC>.jsonl` (the schema kinds shipped in Session 3) + the live `strategy.tracker` snapshot (via a Redis or shared-state hop).
- Surface: per-window inventory (UP / DOWN / gross), active orders count, hourly PnL chart, top markets today, kill-switch button (writes halt sentinel).
- React side: a new tab/panel in the existing v3 UI. Layout parity with the directional panel.
- `systemctl enable --now dashboard-server.service` on the VPS once panel renders cleanly.

### D2 — Re-enable tg-alerter.service + MMB alert formatting

- Extend `src/polymarket_bot/_live/alerter/formatter.py` with MMB alert types: `mm_ladder_placed`, `mm_daily_loss_tripped`, `mm_heartbeat_missed`, `mm_halt_engaged`, `mm_fill_confirmed`.
- Heartbeat task (already shipped) pushes to Redis on 2-miss → alerter drains → Telegram. End-to-end test: intentional heartbeat-miss → confirm Telegram message arrives within 15s.
- `systemctl enable --now tg-alerter.service` on the VPS.

### D3 — bot-mm.service systemd unit

- `runbooks/systemd/bot-mm.service` — template from existing `bot-staging.service` with these changes:
  - `ExecStart=...uv run python -u scripts/run_mm_paper.py` (paper mode default; flip to `run_mm_live.py` in S.5).
  - `WorkingDirectory=/home/ops/polymarket-5m-bot`.
  - Service name distinct from `bot-staging.service` so process state never crosses.
  - `Restart=on-failure` with `RestartSec=10`.
- Install + start as **paper-mode** on the VPS. Operator verifies dashboard shows MMB state ticking.

### D4 — Safety circuit verification + cap recalibration

- Per Session 2 finding "$50/day cap will trip on normal multi-loss days": revisit `RiskCaps.max_daily_loss_usd`. Reasonable revised range from sim distribution: $75–$100. Lock the chosen number in `design/S.1-market-maker-bot.md` §2.4.
- Tests:
  - Intentional heartbeat miss (kill the Redis connection or use a flaky stub) → halt sentinel written + Telegram alert routed within 15s.
  - Daily-loss trip: force `RiskGate.record_realized_pnl(-$60)` programmatically → next `can_place` returns `max_daily_loss` + halt engaged.
  - `MM_KILL_SWITCH=true` env flip → bot drains within 30s + writes sentinel with reason `operator_kill_switch`.

### D5 — G11 empirical probes (3 short runbook addenda)

These need **funded Signer + USDC.e allowance** (G6 — one-time operator on-chain tx). If allowance is not yet set, defer probes to S.5 pre-deploy.

1. **Maker fee probe** → `runbooks/S-mmb-fee-empirical-2026-05-XX.md`. Place 5 maker-limit BUYs at deep depths ($0.20 below ask) on a live BTC 5m market. Wait for fills. Compare gross PnL (size × (1 - fill_price) if win else -size × fill_price) to net USDC.e settled.
2. **Cancel latency probe** → `runbooks/S-mmb-cancel-latency-empirical-2026-05-XX.md`. Place + cancel 1000 orders sequentially. p50/p95/p99.
3. **Rate-limit probe** → `runbooks/S-mmb-rate-limit-empirical-2026-05-XX.md`. Place at increasing rates until 429. Log `X-RateLimit-*` headers.

Real money risk: tiny ($5 × 5 = $25 max for the fee probe; cancel + rate probes use $5 each but cancel before fill so net exposure ≈ 0). Acceptable.

### D6 — Tests (≥10 new)

- MMB panel reader parses all S.3 decision-log kinds correctly.
- Alerter formatter renders all 5 MMB alert types.
- bot-mm.service template validates (`systemctl cat`).
- Daily-loss cap trip → halt sentinel + Telegram (mocked alerter).
- Kill-switch env flip → drain within 30s.

---

## Acceptance gates (S.4 close)

ALL of:

1. `uv run pytest -q` → ≥767 tests pass (757 baseline + 10+ new).
2. `mypy --strict` + `ruff` on new modules → green.
3. `dashboard-server.service` running on VPS; MMB panel renders MMB state from `state/mm-decisions/`.
4. `tg-alerter.service` running on VPS; intentional heartbeat-miss reaches operator's Telegram within 15s.
5. `bot-mm.service` installed + running as paper-mode; visible in dashboard.
6. Daily-loss circuit verified (force trip → sentinel + alert).
7. Kill-switch env-var verified (force flip → drain in <30s + sentinel).
8. G11 probes shipped OR explicitly deferred to S.5 with operator approval (write the deferral into the session note).
9. Closeout: `state/sessions/2026-05-XX-phase-S-session-4-close.md` + `memory/checkpoint_phase_S_session_4.md` + MEMORY.md + `phase-prompts/phase-S-session-5-live-micro.md`.

---

## Don't-do rules

- Do NOT re-enable `bot-staging.service` (directional bot). Stays disabled.
- Do NOT skip the intentional heartbeat-miss test. The whole halt → alert chain must be proven end-to-end before any live money flows in S.5.
- Do NOT change `MarketMakerStrategy` logic. If a bug surfaces, ship failing test + design-doc note before code change.
- Do NOT submit live orders beyond the $5 G11 probes. Phase S live-money deploy is gated to S.5.
- Do NOT lower the $5 floor on probe orders. CLOB minimums + meaningful fee delta require at least $5.

---

## When you finish Session 4

1. `state/sessions/2026-05-XX-phase-S-session-4-close.md` (template: previous close notes).
2. `memory/checkpoint_phase_S_session_4.md` (template: previous checkpoints).
3. Update `MEMORY.md` — mark Session 3 superseded for live status; add Session 4 entry.
4. Update `state/phases/phase-S-market-maker.md` — mark S.4 CLOSED, S.5 next.
5. Write `phase-prompts/phase-S-session-5-live-micro.md` (S.5 = first real money: scripts/run_mm_live.py + 7-day soak gate).

---

## Reference

- Session 3 close: [state/sessions/2026-05-20-phase-S-session-3-close.md](../state/sessions/2026-05-20-phase-S-session-3-close.md)
- Phase plan: [runbooks/phase-S-high-volume-plan-2026-05-20.md](../runbooks/phase-S-high-volume-plan-2026-05-20.md)
- Polymarket skill: `~/.claude/skills/agent-skills/`
- Existing alerter: [src/polymarket_bot/_live/alerter/service.py](../src/polymarket_bot/_live/alerter/service.py)
- Existing dashboard: [src/polymarket_bot/dashboard_server/](../src/polymarket_bot/dashboard_server/)
- Daily-loss revisit context: Session 2 close note §4 + Session 2 backtest findings
- Memory: `feedback_test_under_load.md`, `feedback_vps_deploy_verify_late.md`, `feedback_pragmatic_gate_revision.md`
