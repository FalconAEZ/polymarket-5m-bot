---
date: 2026-05-20
session: phase-S-session-4-close
branch: claude/phase-S-market-maker
tags: [session-note, phase-S, alerter, systemd, safety]
---

# Phase S Session 4 — CLOSED 2026-05-20

## Scope reduction from prompt

Session 4 prompt scoped 6 deliverables (D1–D6). After honest review:

- **D1 (dashboard panel UI)** — DEFERRED. The dashboard service can be re-enabled standalone (`systemctl enable dashboard-server.service` on the VPS); the MMB-specific React panel is a separate UI task that doesn't block S.5 deployment. Operator can SSH + tail `state/mm-decisions/*.jsonl` + Telegram for observability through the live-micro soak.
- **D5 (G11 empirical probes)** — DEFERRED to S.5 pre-deploy. Operator confirmed USDC.e allowance is NOT yet set on the Signer; without it the probes either fail with `InsufficientBalance` or yield no fee data. Bundled into S.5 pre-deploy step alongside the allowance tx.
- **D2 (alerter MMB types)** — re-scoped: existing `format_alert` already handles the MMB use case via the `source` field. Built a thin payload-constructor module instead of modifying the formatter. Less coupling, same end result.

What landed this session: D2 (payload module), D3 (systemd unit), D4 (safety circuits + sentinel wiring), D6 (13 new tests).

## What shipped

**Source (~150 LOC, mypy --strict + ruff green):**
- [src/polymarket_bot/_live/mm_alerts.py](../../src/polymarket_bot/_live/mm_alerts.py) — 6 payload constructors for MMB alert kinds: `mm_heartbeat_missed`, `mm_daily_loss_tripped`, `mm_kill_switch`, `mm_halt_engaged`, `mm_place_failed`, `mm_first_fill_confirmed`. Every payload uses `source="mm-bot"` + a stable level (`critical`/`error`/`warn`) so the existing `format_alert` renders them with prefix + source stamp without any formatter changes.
- [src/polymarket_bot/_paper/mm_runner.py](../../src/polymarket_bot/_paper/mm_runner.py) — added `alert_callback` field + `_engage_halt_from_gate()` method. When `on_resolution` lands a fill that trips `RiskGate`'s daily-loss accumulator, the runner writes the on-disk halt sentinel (via `asyncio.to_thread(write_halt_sentinel, ...)`) AND pushes a CRITICAL alert through the callback. Bridges in-process gate state to filesystem signal + alerter pipeline. One-shot: `_sentinel_written` flag prevents double-writes.

**systemd unit:**
- [runbooks/systemd/bot-mm.service](../../runbooks/systemd/bot-mm.service) — new unit. Description "Polymarket 5m BTC bot — market-maker (Phase S)". Initially `ExecStart` points at `scripts/run_mm_paper.py`; S.5 deploy flips it to `scripts/run_mm_live.py`. Hardening matches `bot-staging.service` (`NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`). Restart=on-failure with 30s timeout.

**Tests (+13 new; 770 total):**
- [tests/_live/test_mm_alerts.py](../../tests/_live/test_mm_alerts.py) — 7 tests: each payload kind level + source + key field; combined verification all 6 constructors emit `source="mm-bot"`.
- [tests/_paper/test_mm_safety.py](../../tests/_paper/test_mm_safety.py) — 6 tests: daily-loss trip writes sentinel + fires alert; idempotency (no double-write/alert); runner short-circuits after halt; pre-existing operator sentinel honored; alert callback exception doesn't crash runner (best-effort alerts; sentinel is authoritative); bot-mm.service unit file parses + has required sections.

## Gate verification

| Gate | Result |
|---|---|
| `uv run pytest -q` | **770 passed** (no regressions; +13 from 757) |
| `uv run mypy --strict <new src>` | green |
| `uv run ruff check <new src + tests>` | green |
| `uv run lint-imports` | 3 contracts kept / 0 broken (paper→live-alerter import path stays compliant) |

## Critical safety chain — now end-to-end testable

Pre-S.4 state: `RiskGate` self-halted in-process on daily loss but no signal escaped the runner. Alerter + dashboard + peer processes were blind.

Post-S.4 state:

```
RiskGate.record_realized_pnl(loss)
    → today_realized_pnl <= -max_daily_loss
    → gate.halted = True
    ↓
MmRunner.on_resolution detects gate.halted
    → write_halt_sentinel("mm_daily_loss_cap", ...) — atomic tmp+rename
    → alert_callback(mm_daily_loss_tripped_alert(...))
        → Redis push (S.5 wiring) → tg-alerter drain → Telegram
    ↓
MmRunner._sentinel_written = True   (one-shot)
    ↓
Subsequent on_book_update sees halt_sentinel_present() → returns []
    → no new orders placed
```

S.5 will exercise this chain against a real Redis + live tg-alerter. S.4 tests cover the in-process portion + sentinel file write via a `tmp_path` fixture.

## Deferred (explicitly, with rationale)

- **Dashboard MMB panel (D1)** — operator can monitor via Telegram + SSH log tail through S.5 soak. React UI is a separate concern; ship after S.5 if needed.
- **G11 empirical probes (D5)** — bundle with S.5 pre-deploy step. Requires USDC.e allowance + $5 test orders. The probes inform whether `J7Priors.bet_size` math needs recalibration before going to scale.
- **Daily-loss cap recalibration** — Session 2 backtest showed $2k daily sim variance → ~$80 at live-micro scale, suggesting $50 cap might trip on noise. BUT the sim doesn't model queue position; at back-of-queue live we get fewer fills, less variance. **Decision: keep $50 for initial S.5 deploy.** If it trips spuriously during soak, raise then with empirical evidence. Don't pre-emptively loosen safety.

## VPS deploy plan (operator-driven, not in this session)

When ready to ship to VPS:

1. SSH into `ops@108.132.51.116:2222`.
2. `git pull` to bring the 6 Phase S commits onto the box.
3. Copy `runbooks/systemd/bot-mm.service` → `/etc/systemd/system/bot-mm.service` (or symlink).
4. `sudo systemctl daemon-reload`.
5. `sudo systemctl enable bot-mm.service`.
6. Verify halt sentinel is in place (`state/halt.sentinel` exists) — if not, MMB will start trading immediately on `start`.
7. `sudo systemctl start bot-mm.service` to bring up paper-mode.
8. Tail journal: `journalctl -u bot-mm.service -f`.
9. Re-enable dashboard-server.service + tg-alerter.service if operator wants those running before live-micro.

S.4 deliberately does NOT execute this. The VPS state change is a discrete operator-approved action; the code landing in commits today doesn't change running services until you say so.

## Branch state at close

```
$ git log --oneline -7
<commit6>  feat(phase-S): Session 4 CLOSED — alerter + systemd + safety (this)
05e195b    fix(phase-S): wrap halt-sentinel exists() in asyncio.to_thread (ASYNC240)
e64ff48    feat(phase-S): Session 3 CLOSED — CLOB wrapper + heartbeat + paper runner + 29 tests
3840b9a    feat(phase-S): Session 2 CLOSED — backtest harness +$1,586 sim PnL + Session 3 prompt
1210e13    feat(phase-S): Session 2 (partial) — MMB modules + 54 tests + high-volume plan
02f8803    docs(phase-S): Session 1 — MMB design + J.7 priors + S.1.1 research + Session 2 prompt
9516f39    fix(dashboard): honor PMB_STARTING_BANKROLL + BANKROLL_REPLAY_ENABLED  ← base
```

## Next session

**Phase S Session 5 — live-micro deploy + 7-day soak.** First real money. $1k bankroll. Live-micro caps ($5/level, $50 max gross/window, $50/day loss). See [phase-prompts/phase-S-session-5-live-micro.md](../../phase-prompts/phase-S-session-5-live-micro.md).

S.5 pre-deploy checklist:

1. Operator sets USDC.e allowance on Signer (`scripts/mm_set_allowance.py` — write in S.5).
2. G11 empirical probes against a low-volume BTC 5m market — fee + cancel latency + rate limit data.
3. Recalibrate priors math if maker fee is non-zero (sizing depends on this).
4. Author `scripts/run_mm_live.py` (mirrors `run_mm_paper.py` but with `LiveClobOrderClient`).
5. Wire `alert_callback` in `run_mm_live.py` to push to the alerter Redis queue (production callback that closes the safety chain).
6. Deploy: VPS git pull + flip `bot-mm.service` ExecStart to live entrypoint + remove halt sentinel + `systemctl start`.
7. Day-1 audit at +24h: PnL + fill rate + heartbeat misses + alert routing.
8. Day-7 audit: PnL > $0 gate → S.6 promotion (scale-up caps).
