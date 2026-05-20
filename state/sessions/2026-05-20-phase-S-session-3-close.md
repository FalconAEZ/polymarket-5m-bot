---
date: 2026-05-20
session: phase-S-session-3-close
branch: claude/phase-S-market-maker
tags: [session-note, phase-S, orders, paper-runner]
---

# Phase S Session 3 — CLOSED 2026-05-20

## What shipped

**Source modules (~1,000 LOC; mypy --strict + ruff green):**
- [src/polymarket_bot/_live/clob_orders.py](../../src/polymarket_bot/_live/clob_orders.py) — `ClobOrderClient` Protocol + `MockClobOrderClient` (deterministic, fully tested) + `LiveClobOrderClient` skeleton (real py-clob-client wrapper; not exercised this session). 5 exception classes for error classification per S.1.1 §Q2 (PostOnlyRejected → soft skip; OrderTickViolation / OrderSizeViolation / InsufficientBalance → raise).
- [src/polymarket_bot/_live/mm_heartbeat.py](../../src/polymarket_bot/_live/mm_heartbeat.py) — `mm_heartbeat_loop` asyncio task at 5s cadence, 2-miss threshold → halt sentinel + Telegram alert. `sleep_fn` injectable for deterministic tests.
- [src/polymarket_bot/_paper/mm_runner.py](../../src/polymarket_bot/_paper/mm_runner.py) — `MmRunner` coordinator + `MmDecisionLog` (append-only JSONL with inode-stability) + `replay_bankroll` (reconstructs current bankroll from prior days' resolve records).
- [scripts/run_mm_paper.py](../../scripts/run_mm_paper.py) — paper-mode entry script driving 3 synthetic markets with a deterministic (seed=42) random book-update stream.

**Tests (29 new; full suite 757 / +29 from 728 baseline):**
- [tests/_live/test_clob_orders.py](../../tests/_live/test_clob_orders.py) — 13 tests: place succeeds + post-only rejects on cross + tick/min-size violations + cancel + cancel_all + heartbeat rotation + injection.
- [tests/_live/test_mm_heartbeat.py](../../tests/_live/test_mm_heartbeat.py) — 5 tests: success path, 2-miss halt, intermittent recovery, alert callback, halt_writer exception handling.
- [tests/_paper/test_mm_runner.py](../../tests/_paper/test_mm_runner.py) — 11 tests: decision log r/w, bankroll replay, place ladder, post-only soft skip, halt sentinel short-circuit, drain, on_fill_confirmed, on_resolution, multi-market isolation, 1000-tick burst (queue-doesn't-overflow proxy).

## Gate verification

| Gate | Result |
|---|---|
| `uv run pytest -q` | **757 passed in ~11s** (no regressions) |
| `uv run mypy --strict <new modules>` | **green** on 4 new source files |
| `uv run ruff check ...` | **green** on src + tests |
| `uv run python scripts/run_mm_paper.py` 60s run | **clean**: 60 ticks, 14 orders placed + 14 drained, 0 post-only rejects, 0 heartbeat misses, 15 decision-log records (14 `place_succeeded` + 1 `drain`) |
| Orphan orders post-drain | 0 |
| Heartbeat task wiring | confirmed via test + paper run |

## Deferred from Session 3 (per phase plan §3 explicit allowance)

- **G11 empirical probes** (maker fee, cancel latency, rate limits) — these require LIVE CLOB calls + USDC.e allowance on the Signer. Without funded allowance we can't probe maker fees against real fills, and an unfunded probe would surface `InvalidOrderNotEnoughBalance` rather than the data we want. Moved to **S.4** alongside the dashboard + alerter re-enable work. Adds ~half a day to S.4's scope.
- **G6 USDC.e allowance one-time tx** — operator hardware action (sign + broadcast on Polygon). Sits between S.4 and S.5; not S.3 blocker.

## Findings worth carrying into S.4+

1. **Heartbeat alert routing is wired but the alerter is OFF.** When MMB heartbeat fails it pushes to the Redis alerter queue, but `tg-alerter.service` is currently disabled (per 2026-05-20 halt). S.4 re-enables it and adds MMB-specific alert formatting. Until then, heartbeat failures during paper soak will write the sentinel but won't surface as a Telegram message. Acceptable for paper.
2. **Live skeleton is intentionally untested.** `LiveClobOrderClient` matches the Mock's Protocol shape but has zero test coverage — full integration needs a funded Signer + a live BTC 5m market. S.4 ships the first live calls via the empirical probes; pyclob_client integration gets its first real exercise there.
3. **Decision-log schema is MMB-specific.** Kinds shipped: `place_attempt`, `place_succeeded`, `place_rejected`, `place_failed`, `cancel_attempt`, `cancel_result`, `fill`, `resolve`, `drain`. Distinct from the directional bot's `fired`/`settled`/`settled_correction` schema. Dashboard panel in S.4 needs an MMB-specific reader; cannot reuse the v3 dashboard's existing kind dispatch.
4. **The decision-log root defaults to `state/mm-decisions/`.** Namespaced separately from the directional bot's `state/decisions/` so the two strategy classes never conflate. Litestream config in S.4 should mirror to S3 alongside the existing `trades.db` backup (or treat the MMB JSONLs as ephemeral — operator decides).

## Verification commands (for future reference)

```bash
# Full suite (regression check)
uv run pytest -q   # 757 passed

# New modules only
uv run pytest tests/_live/ tests/_paper/test_mm_runner.py -v

# Type + lint sweep
uv run mypy --strict src/polymarket_bot/_live/clob_orders.py \
    src/polymarket_bot/_live/mm_heartbeat.py \
    src/polymarket_bot/_paper/mm_runner.py \
    scripts/run_mm_paper.py
uv run ruff check src/polymarket_bot/_live/clob_orders.py \
    src/polymarket_bot/_live/mm_heartbeat.py \
    src/polymarket_bot/_paper/mm_runner.py \
    scripts/run_mm_paper.py \
    tests/_live/ tests/_paper/

# 60s paper soak (gate)
rm -rf /tmp/mmb-gate-decisions /tmp/mmb-gate-halt.sentinel && \
  MM_DURATION_S=60 MM_TICK_INTERVAL_S=1.0 \
  MM_DECISION_LOG_ROOT=/tmp/mmb-gate-decisions \
  MM_HALT_SENTINEL_PATH=/tmp/mmb-gate-halt.sentinel \
  uv run python scripts/run_mm_paper.py
```

## Branch state at close

```
$ git log --oneline -4
<commit4> feat(phase-S): Session 3 CLOSED — CLOB wrapper + heartbeat + paper runner + 29 tests + S.4 prompt
3840b9a   feat(phase-S): Session 2 CLOSED — backtest harness +$1,586 sim PnL + Session 3 prompt
1210e13   feat(phase-S): Session 2 (partial) — MMB modules + 54 tests + high-volume plan
02f8803   docs(phase-S): Session 1 — MMB design + J.7 priors + S.1.1 research + Session 2 prompt
```

## Next session

**Phase S Session 4 — dashboard + safety circuits + Telegram + G11 empirical probes.** See [phase-prompts/phase-S-session-4-dashboard.md](../../phase-prompts/phase-S-session-4-dashboard.md). Adds the 3 deferred probes to S.4 alongside the dashboard re-enable + tg-alerter MMB formatting.
