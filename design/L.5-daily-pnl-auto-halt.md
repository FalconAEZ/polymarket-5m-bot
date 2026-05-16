# Design — L.5 Daily PnL Auto-Halt (Phase M Session 2)

> Purpose: retrofit the bot to auto-halt itself when a UTC day closes with
> realised PnL below a configured floor. Today's 2026-05-16 trip of the
> manual −$30 gate (PnL −$520) showed the gate is operator-driven only; if
> the operator is asleep or away the bleed continues. L.5 closes that loop
> via the existing `state/halt.sentinel` infrastructure + Telegram CRITICAL
> alert.
>
> **Anti-vibe rule #1**: this doc lands and locks before any code in
> `src/polymarket_bot/_live/auto_halt.py`.
>
> **Anchors**:
> - `design/alerter.md` §4.3 (halt-sentinel infrastructure)
> - `phase-prompts/phase-M-pre-live-edge-stacking-2026-05-16.txt` Part C §L.5
> - `state/phases/phase-M-pre-live-edge-stacking.md` (operator-locked Kelly 0.15× + replay → drawdown defense is L.5's job)
> - `memory/project_phase_j16_kelly_variance_realized.md`
> - Locked decisions: #7 Telegram via BotFather, #15 UTC everywhere
>
> **Out of scope**:
> - Multi-threshold ladder (M.6 hard triggers cover WR/DD/bankroll separately; this is daily-PnL only)
> - Auto-resume (operator clears `state/halt.sentinel` manually after review)
> - Per-tier or per-regime PnL gates (Phase M.4 adaptive WR territory)
> - Replacement of the existing operator `/halt` Telegram command (orthogonal — both paths write the same sentinel)

---

## 1. The picture

```
                ┌────────────────────────────────────────┐
                │  bot main loop                         │
                │  every minute:                          │
                │    if (utc_h, utc_m) == (23, 50)       │
                │      and not halted_today:             │
                │        check_daily_pnl_gate(...)       │
                └──────────────┬─────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────┐
        │  auto_halt.check_daily_pnl_gate              │
        │  1. read state/decisions-resolved/YYYY-MM-DD │
        │     .jsonl                                   │
        │  2. sum pnl_usd (apply settled_correction)   │
        │  3. if total < DAILY_PNL_GATE_USD:           │
        │        write halt.sentinel(by="auto-halt")   │
        │        publish CRITICAL alert                │
        │        return True (halted)                  │
        │     else:                                    │
        │        return False                          │
        └──────────────────────────────────────────────┘
```

## 2. Public surface

One module: `src/polymarket_bot/_live/auto_halt.py`.

```python
def check_daily_pnl_gate(
    *,
    now_ns: int,                           # injected clock
    today_utc: date,                       # the UTC day being closed
    pnl_reader: DailyPnlReader,            # injected
    halt_writer: HaltWriter,               # injected (wraps halt.py)
    alerts: AlertSink,                     # injected (alerts.protocols)
    threshold_usd: float,                  # DAILY_PNL_GATE_USD
) -> AutoHaltResult: ...
```

`AutoHaltResult` is a frozen dataclass with `(halted: bool, pnl_usd: float, reason: str)`.

The function MUST NOT raise — it absorbs reader/sentinel/alert errors and returns `halted=False` on any internal failure (per `AlertSink` contract: best-effort, must not block hot path). Internal failures are themselves logged + published as `Level.ERROR` alerts.

## 3. Protocols (anti-vibe rule #10: stochastic + I/O behind interfaces)

```python
class DailyPnlReader(Protocol):
    def read(self, day_utc: date) -> float: ...
    # Returns the sum of corrected_pnl_usd (preferring settled_correction
    # records over settled records, keyed by decision_id).
    # Reads from state/decisions-resolved/YYYY-MM-DD.jsonl.
    # Returns 0.0 if file is absent or empty.

class HaltWriter(Protocol):
    def write(self, *, reason: str, ts_ns: int, by: str) -> None: ...
    # Wraps the existing halt.py write_halt_sentinel + adds the `by` field
    # so the existing operator-/halt code path stays unchanged.
```

The production `JsonlDailyPnlReader` lives in the same module. The production `SentinelHaltWriter` wraps the existing `halt.py:write_halt_sentinel` — see §6 for the small extension needed there.

## 4. Wiring (bot main loop)

The bot's main loop runs a minute-resolution scheduler today (existing). L.5 adds one hook:

```python
# scripts/run_paper.py (or _live runner) main loop, once per minute
if config.daily_pnl_auto_halt_enabled:
    now = clock.utc_now()
    if now.hour == config.daily_pnl_check_hour and now.minute == config.daily_pnl_check_minute:
        if not halt_sentinel_present():           # idempotent: skip if already halted
            check_daily_pnl_gate(
                now_ns=clock.time_ns(),
                today_utc=now.date(),
                pnl_reader=jsonl_reader,
                halt_writer=sentinel_writer,
                alerts=redis_alert_sink,
                threshold_usd=config.daily_pnl_gate_usd,
            )
```

The check is idempotent on `halt_sentinel_present()` so multiple invocations on the same UTC day with the same trip outcome are a no-op (the halt is absorbing — bot won't fire again until operator clears the sentinel).

## 5. Env-vars (DARK ship default; new `.envrc` entries on VPS)

| name | default | role |
|---|---|---|
| `DAILY_PNL_AUTO_HALT_ENABLED` | `false` | DARK ship switch — must be flipped to `true` after smoke test |
| `DAILY_PNL_GATE_USD` | `-30.0` | Threshold; PnL ≤ this fires halt |
| `DAILY_PNL_CHECK_HOUR_UTC` | `23` | Check fires at this UTC hour |
| `DAILY_PNL_CHECK_MINUTE_UTC` | `50` | Check fires at this minute (so day closes at UTC 24:00 ~10 minutes after) |

The hour/minute envs default to 23:50 per Phase L L.5 prompt; operator can shift to e.g. 23:55 if they want a tighter window.

## 6. Small extension to `halt.py`

Existing `write_halt_sentinel(reason, ts_ns)` hard-codes `"halted_by": "telegram-/halt"`. Extend to:

```python
def write_halt_sentinel(reason: str, ts_ns: int, *, by: str = "telegram-/halt", path: Path = DEFAULT_SENTINEL_PATH) -> None:
    ...
    payload = {"halted_at_ns": ts_ns, "halted_by": by, "reason": reason}
    ...
```

The default preserves the existing alerter call site (which now becomes `write_halt_sentinel(reason, ts_ns)` — unchanged behaviour). L.5 calls `write_halt_sentinel(reason, ts_ns, by="auto-halt-daily-pnl")`.

## 7. Telegram alert (Level.CRITICAL)

`AlertSink.publish` with:

```python
Alert(
    level=Level.CRITICAL,
    message=(
        f"DAILY PNL GATE TRIPPED — day {day_utc} closed at PnL ${pnl:+,.2f}, "
        f"threshold ${threshold:+,.2f}. Bot halted via state/halt.sentinel. "
        "Operator: review decisions-resolved + clear sentinel to resume."
    ),
    ts_ns=now_ns,
    source="auto_halt.daily_pnl_gate",
    fields={"pnl_usd": pnl, "threshold_usd": threshold, "day_utc": str(day_utc)},
)
```

The existing alerter service formats `Level.CRITICAL` with a 🚨 prefix (per `formatter.py`).

## 8. Tests (target ≥7 in `tests/_live/test_auto_halt.py`)

Anti-vibe rule #10: deterministic clock + injected readers/writers/sinks.

| # | test | scenario |
|---|---|---|
| 1 | `test_halt_fires_when_pnl_below_threshold` | reader returns −50 vs threshold −30 → halted=True, sentinel written, CRITICAL published |
| 2 | `test_halt_does_not_fire_when_pnl_above_threshold` | reader returns −20 vs threshold −30 → halted=False, no sentinel, no alert |
| 3 | `test_halt_fires_at_exact_threshold` | reader returns exactly −30 → halted=True (≤ semantics) |
| 4 | `test_idempotent_when_sentinel_already_present` | sentinel exists → no-op (caller's responsibility, but check_daily_pnl_gate must not double-publish if called twice) |
| 5 | `test_reader_error_returns_halted_false_and_publishes_error` | reader raises → halted=False, ERROR alert published, no sentinel |
| 6 | `test_halt_writer_error_publishes_error_alert` | halt_writer raises → halted=False (no false-positive halt), ERROR alert |
| 7 | `test_sentinel_written_with_by_field` | post-trip, sentinel JSON contains `"halted_by": "auto-halt-daily-pnl"` |
| 8 | `test_alert_publish_uses_critical_level` | level=Level.CRITICAL on the published Alert |
| 9 | `test_alert_publish_failure_does_not_block_halt` | alerts.publish raises → halted=True still (halt is the primary action, alert is best-effort) |

Plus one integration test against the existing `halt.py` extension:

| # | test | scenario |
|---|---|---|
| H1 | `test_halt_py_by_param_defaults_to_telegram` | `write_halt_sentinel(...)` without `by=` → sentinel payload `"halted_by": "telegram-/halt"` (backward compat) |
| H2 | `test_halt_py_by_param_override` | `write_halt_sentinel(..., by="auto-halt-daily-pnl")` → payload reflects new value |

## 9. Promote gate

This is a DARK ship — env-default OFF. Promotion criteria:

1. `make verify` green (ruff + mypy --strict + pytest, all 9 + 2 new tests passing)
2. Smoke test on VPS staging: temporarily set `DAILY_PNL_GATE_USD=+1e6` (always-trip) + `DAILY_PNL_AUTO_HALT_ENABLED=true` → observe Telegram alert + sentinel written within 60s of the scheduled hour:minute
3. Operator clears smoke-test sentinel and resets threshold to `-30.0`
4. Operator flips `DAILY_PNL_AUTO_HALT_ENABLED=true` on VPS staging
5. Watch first real check at UTC 23:50 (next UTC day after promote)

## 10. Rollback

`env-flip DAILY_PNL_AUTO_HALT_ENABLED=true → false` + restart bot. Reversible in 30 seconds.

## 11. Honest pushback

- **P1** — A daily check fires once per UTC day; if the bot bleeds catastrophically between UTC 00:00 and 23:50, the gate won't trip until day-close. M.6 supplies a faster trigger (drawdown >35%) for that scenario; L.5 is the day-close floor, not intra-day protection.
- **P2** — Threshold `−$30` is the Phase K spec value. With Kelly 0.15× + replay producing per-trade variance of ~$5-7, a single losing afternoon can easily hit −$30 even on a winning day. Operator may want to raise threshold to `−$75` (matching M.6 hard trigger) to reduce false trips. Default stays `−$30` for spec compatibility; env var lets operator tune.
- **P3** — `decisions-resolved/<date>.jsonl` is written by the resolver loop; if the resolver is behind (which has happened mid-session per Phase 11.A history), the reader may see partial PnL. Mitigation: the check runs at 23:50, the resolver is usually within 5min of real-time, so the worst case is a 10-minute lag at UTC day close.
- **P4** — Today (2026-05-16) the gate would have tripped at ~UTC 01:00 (when day's PnL crossed −$30). Auto-halt at 23:50 would have stopped firing 22h later than ideal. Operator should consider whether L.5 should also support an intraday check (every hour?) but that's out-of-scope for the first ship — get the day-close path live first, then iterate.
