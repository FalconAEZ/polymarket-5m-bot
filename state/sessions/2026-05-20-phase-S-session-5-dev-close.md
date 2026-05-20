---
date: 2026-05-20
session: phase-S-session-5-dev-close
branch: claude/phase-S-market-maker
tags: [session-note, phase-S, live-prep, dev-portion]
---

# Phase S Session 5 (dev portion) — CLOSED 2026-05-20

## What this is

S.5 splits into two halves:
- **Dev portion (this session):** write the live entrypoint + allowance verifier + Redis push helper + tests. All locally verifiable; ships in commit form for operator review.
- **Pre-deploy + live deploy + soak (operator-driven, NOT this session):** USDC.e allowance tx, G11 empirical probes, VPS deploy, start, 7-day soak audit.

Session 5 is not formally closed until the soak audit passes. This note documents what's ready.

## What shipped

**Source (~150 LOC new, mypy --strict + ruff green):**
- [src/polymarket_bot/_live/mm_alerts.py](../../src/polymarket_bot/_live/mm_alerts.py) — added `push_to_redis_alerter()` async helper. Best-effort: any Redis failure (import / connection / serialization) is logged + swallowed. The on-disk halt sentinel remains the authoritative safety signal; alerting is observability sugar.

**Scripts (~440 LOC, mypy --strict + ruff green):**
- [scripts/mm_set_allowance.py](../../scripts/mm_set_allowance.py) — verifier + optional applier. Default behavior reads current USDC.e balance + allowance via `py-clob-client.get_balance_allowance` and reports. With `--apply`, prompts operator for confirmation (literal "YES I CONFIRM" string) then calls `update_balance_allowance` to broadcast the approve tx. Writes `state/mm-allowance.json` audit after every run.
- [scripts/run_mm_live.py](../../scripts/run_mm_live.py) — live entrypoint. Refuses to start unless:
  1. `MM_LIVE_CONFIRM=yes` env
  2. Halt sentinel ABSENT
  3. `state/mm-allowance.json` present + recent (< 24h) + reports ≥ $100 allowance
  4. CLOB L2 creds + wallet env vars present
  Discovers up to 3 active BTC 5m markets via Gamma API (capped to bound exposure). Spawns one book-poll task per (market, token, side) at 1s cadence + a heartbeat task at 5s cadence. Drains all open orders on window close OR sentinel detection.

**Tests (+15 new; 785 total):**
- [tests/_live/test_mm_alerts_redis.py](../../tests/_live/test_mm_alerts_redis.py) — 3 tests covering Redis push happy path + import-error swallow + connection-error swallow.
- [tests/test_mm_live_preflight.py](../../tests/test_mm_live_preflight.py) — 12 tests covering each preflight gate individually + the aggregate `_preflight()` function across all failure modes.

## Gate verification

| Gate | Result |
|---|---|
| `uv run pytest -q` | **785 passed** (+15 from 770; no regressions) |
| `mypy --strict` on all new files | green |
| `ruff check` on all new files | green |
| `lint-imports` | 3 contracts kept / 0 broken |
| Sentinel-on-gate-halt safety chain | unchanged from S.4; tested via `tests/_paper/test_mm_safety.py` |

## What this script will NOT do (and why that's correct)

`scripts/run_mm_live.py` refuses to start in many ways and that's by design. The pre-flight gates are intentionally redundant:

1. `MM_LIVE_CONFIRM=yes` — operator must explicitly opt in via env. Default behavior is "don't trade real money."
2. Halt sentinel must be absent. Operator deliberately removes it after verifying allowance + caps + last paper soak.
3. Allowance audit must be recent (< 24h). If the audit is older, operator runs `mm_set_allowance.py` again to refresh. Prevents stale "yes it was set last week" from leaking into the start path.
4. L2 creds + wallet env must all be set. Missing any one → refuse.

Any one of these failing logs the specific reason + exits with code 2. systemd's `Restart=on-failure` will keep trying every 30s, but the bot won't trade until operator fixes the gap. This is the right asymmetry: starting trading wrongly is much worse than not trading.

## What's UNTESTED (carried into operator-supervised soak)

1. **LiveClobOrderClient against real CLOB.** Mock client is fully tested; live client's actual HTTP/WS behavior is not exercised. First fire will be the first real exercise.
2. **Polymarket maker fee.** S.1.1 §Q1 deferred this to empirical probe. Until G11 probes run against a live market, `J7Priors.bet_size` math assumes zero fee. If empirical shows > 0, sizing needs recalibration before scaling past S.5.
3. **Cancel latency under real load.** Heuristic from decision #2 evidence: 20–50ms expected; not measured directly for cancel-endpoint.
4. **Rate-limit ceiling.** No documented per-second order-place rate. Watch for 429 + `X-RateLimit-*` headers during first day of soak.
5. **Real Telegram alert routing.** S.4 wired the `alert_callback` slot; `push_to_redis_alerter` pushes to Redis; tg-alerter consumes. End-to-end live test requires re-enabling `tg-alerter.service` on the VPS (currently disabled).
6. **Multi-market concurrent state under volatile book moves.** The 1000-tick burst test confirmed the runner doesn't choke on rapid sync calls, but real markets surprise. Watch the soak.

## Pre-deploy checklist (operator-driven; NOT this session)

In order:

1. ☐ Set `PK_SIGNER` + `POLY_FUNDER` + L2 creds in VPS `.envrc`.
2. ☐ Set `MM_LIVE_CONFIRM=yes` in VPS `.envrc`.
3. ☐ SSH to VPS; `git pull` to bring the 8+ Phase S commits.
4. ☐ Run `uv run python scripts/mm_set_allowance.py` to verify current allowance state.
5. ☐ If insufficient: either `--apply` from the script, or use Polymarket UI's "Enable Trading", or `cast send` per the script's docstring.
6. ☐ Verify state/mm-allowance.json shows sufficient allowance.
7. ☐ Run G11 empirical probes (write `runbooks/S-mmb-{fee,cancel-latency,rate-limit}-empirical-2026-05-XX.md`).
8. ☐ If maker fee non-zero, recalibrate `J7Priors` math + push design-doc revision commit BEFORE next step.
9. ☐ Re-enable `tg-alerter.service` (`sudo systemctl enable --now tg-alerter.service`). Send a test alert; verify Telegram receives it.
10. ☐ Re-enable `dashboard-server.service` if monitoring via dashboard.
11. ☐ Copy `runbooks/systemd/bot-mm.service` to `/etc/systemd/system/`; `sudo systemctl daemon-reload`; `sudo systemctl enable bot-mm.service`.
12. ☐ Edit ExecStart in the system unit to point at `scripts/run_mm_live.py` (NOT run_mm_paper.py).
13. ☐ Remove `state/halt.sentinel`.
14. ☐ `sudo systemctl start bot-mm.service`. Tail journal: `journalctl -u bot-mm.service -f`.
15. ☐ Verify within 5 minutes: first ladder placement visible in `state/mm-decisions/<UTC>.jsonl`. First fill (whenever it lands) triggers a Telegram alert.

## Branch state at close

```
$ git log --oneline -8
<commit-next>  feat(phase-S): Session 5 dev — live entrypoint + allowance verifier + Redis push + 15 tests
e9aeae7       docs(phase-S): mark S.4 CLOSED in phase ledger
f2cddcd       feat(phase-S): Session 4 CLOSED — alerter + systemd + safety chain + 13 tests
05e195b       fix(phase-S): wrap halt-sentinel exists() in asyncio.to_thread (ASYNC240)
e64ff48       feat(phase-S): Session 3 CLOSED — CLOB wrapper + heartbeat + paper runner + 29 tests
3840b9a       feat(phase-S): Session 2 CLOSED — backtest harness +$1,586 sim PnL + Session 3 prompt
1210e13       feat(phase-S): Session 2 (partial) — MMB modules + 54 tests + high-volume plan
02f8803       docs(phase-S): Session 1 — MMB design + J.7 priors + S.1.1 research + Session 2 prompt
9516f39       fix(dashboard): honor PMB_STARTING_BANKROLL + BANKROLL_REPLAY_ENABLED  ← base
```

## Next move

Hand-off to operator. Phase S Session 5 final close happens after the 7-day soak passes its Day-7 audit gate (Day-7 PnL > $0 + no incidents). That triggers:
- `state/sessions/2026-05-XX-phase-S-session-5-close.md` — final close with Day-7 numbers.
- `memory/checkpoint_phase_S_session_5.md` — final checkpoint.
- `phase-prompts/phase-S-session-6-scaleup.md` — S.6 scale-up prompt.

If the soak fails (PnL < $0 by Day-7, or incidents), the close note becomes a postmortem at `runbooks/postmortems/2026-05-XX-mmb-s5-failure.md` and Phase S possibly halts at "MMB strategy class not viable at $1k" per the design risk section R1.
