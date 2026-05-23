# Phase T — L.5 runner-level daily-loss guard

**Status:** design lock 2026-05-23. Phase T Session 2 P1 (per phase-prompts/phase-T-session-2-mmd-gate-soak-2026-05-23.md §3).
**Owner:** Hamad (operator) / Claude (implementer).
**Branch:** `claude/phase-T-directional-revival`.

## 1. Motivation

Session 1's 57.5h live soak (`pdfs/PHASE_T_LIVE_SOAK_AUDIT.pdf`) found the bot drawing down past −$1k on multiple UTC days with no automated halt. The original L.5 (commit `3277225`, Phase M Session 2) was a once-per-day end-of-UTC-day check wired only when `STRATEGY=ensemble`, and was reverted on the Phase P branch cut. The current live strategy `spot_aware_v2_1` has **no daily-loss protection at all**.

This design re-introduces L.5 as a **runner-level, strategy-agnostic, continuous** guard. Continuous (post-settle) is required because the original 23:50 UTC end-of-day check would have left the Session-1 mid-day −$2.6k bleed running for hours before tripping.

## 2. Scope (P1 only)

- One halt knob: `DAILY_LOSS_HALT_USD` (positive magnitude, USD; 0 disables).
- Trips when realised today PnL ≤ −threshold.
- Writes the existing `state/halt.sentinel`; the existing `_halt_watcher` in `scripts/run_paper.py` handles graceful stop.
- Lives in `_paper/runner.py` → protects any strategy the runner drives.
- Truth-corrected: anchors day-start by subtracting today's realised PnL (settled + settled_correction) from current bankroll, so a mid-day restart does NOT reset the day's loss-budget.

Out of scope (do not ship in P1): auto-resume, daily-WR gate, per-tier gates, scaling-by-bankroll, Slack/Telegram alerts beyond the existing alerter pipeline.

## 3. Architecture

```
                +-------------------------------------+
 settled  --->  | PaperRunner._do_settle               |
 / correction   |   bankroll.apply_settle / correction |
                |   daily_loss_guard.evaluate(...)     |
                +-----------------+-------------------+
                                  |
                                  v   (only on trip)
                +-------------------------------------+
                | DailyLossGuard.evaluate              |
                |  - anchors day-start on first call   |
                |    (truth-corrected from log)        |
                |  - delta = bankroll - day_start      |
                |  - if delta <= -threshold: trip      |
                |  - tripped_today => idempotent       |
                +-----------------+-------------------+
                                  |
                                  v
                +-------------------------------------+
                | write_halt_sentinel(by=…, reason=…) |
                +-----------------+-------------------+
                                  |
                                  v
                +-------------------------------------+
                | run_paper.py _halt_watcher          |
                |   sees sentinel -> sets stop_event  |
                +-------------------------------------+
```

## 4. Public surface

New module: `src/polymarket_bot/_paper/daily_loss_guard.py`.

```python
@dataclass(slots=True, frozen=True)
class DailyLossGuardResult:
    tripped: bool
    today_pnl_usd: float
    threshold_usd: float
    reason: str
    anchored_day: date


class DailyLossGuard:
    def __init__(
        self,
        *,
        threshold_usd: float,                       # magnitude; 0 disables
        log_root: Path,                              # state/decisions
        halt_writer: Callable[[str, int], None],    # write_halt_sentinel
        clock_utc: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None: ...

    def evaluate(self, *, bankroll_current: float) -> DailyLossGuardResult | None:
        """Called after every bankroll change. Returns the result iff
        this call tripped (so caller can alert / log). Returns None on
        no-op (under threshold, disabled, or already tripped)."""
```

Helper (module-private):
```python
def _today_realised_pnl(log_root: Path, today: date) -> float:
    """Sum of `settled.pnl_usd` + (`settled_correction.corrected_pnl_usd`
    − `settled_correction.original_pnl_usd`) for `today`'s decisions
    log. Mirrors `replay_bankroll_from_log` semantics scoped to one
    date. Returns 0.0 if file missing or empty."""
```

## 5. Day-start anchor — restart-safe

On the first `evaluate()` call within a UTC day (or on UTC rollover):

```
today_pnl_so_far = _today_realised_pnl(log_root, today)
bankroll_at_day_start = bankroll_current - today_pnl_so_far
```

**Why this is correct under restart:** `bankroll_current` is already truth-corrected (`replay_bankroll_from_log` walks today's log on startup when `BANKROLL_REPLAY_ENABLED=true`, which Phase T uses). `today_pnl_so_far` independently sums today's settled + settled_correction records. Subtraction gives the day-start bankroll that existed at 00:00:00 UTC. Continuous evaluation thereafter compares against that fixed anchor.

**Edge cases:**
- Bot starts before today's log file exists → `_today_realised_pnl` returns 0.0 → anchor = bankroll_current (correct: nothing has been realised yet today).
- Bot starts mid-day after a clean wipe (Session 2 case: $3k reset) → today's log is the post-reset log; bankroll replay reads only post-reset records; both stay consistent.
- UTC rollover during a long-running process → next `evaluate()` re-anchors using the (now empty) new-day log → fresh budget.

## 6. Wiring in PaperRunner

`PaperRunner.__init__` gains:
```python
daily_loss_halt_usd: float = 0.0,   # 0 = disabled
```

`PaperRunner.run()` constructs the guard once, only if `daily_loss_halt_usd > 0`, before the main loop:
```python
self._daily_loss_guard: DailyLossGuard | None = None
if daily_loss_halt_usd > 0:
    self._daily_loss_guard = DailyLossGuard(
        threshold_usd=daily_loss_halt_usd,
        log_root=self._log.root,
        halt_writer=lambda reason, ts_ns: write_halt_sentinel(
            reason, ts_ns, by="auto-halt-daily-loss",
        ),
    )
```

Two call sites — both immediately after a bankroll mutation:

1. `_do_settle()`, after `self._bankroll.apply_settle(pnl)` (line ≈944):
   ```python
   self._maybe_trip_daily_loss_guard()
   ```

2. `_post_hoc_gamma_retry()`, after `self._bankroll.apply_correction(...)` (line ≈1075):
   ```python
   self._maybe_trip_daily_loss_guard()
   ```

`_maybe_trip_daily_loss_guard()` is a small synchronous helper on PaperRunner:
```python
def _maybe_trip_daily_loss_guard(self) -> None:
    if self._daily_loss_guard is None:
        return
    result = self._daily_loss_guard.evaluate(
        bankroll_current=self._bankroll.current(),
    )
    if result is None or not result.tripped:
        return
    LOG.critical(
        "daily-loss guard tripped: today_pnl=%.2f threshold=-%.2f",
        result.today_pnl_usd, result.threshold_usd,
    )
    self._alert(
        Level.CRITICAL,
        f"auto-halt daily-loss: today=${result.today_pnl_usd:.2f} <= -${result.threshold_usd:.2f}",
        today_pnl_usd=result.today_pnl_usd,
        threshold_usd=result.threshold_usd,
    )
```

The runner's stop is **not** called directly. The sentinel + existing `_halt_watcher` handles a graceful exit. This preserves the existing halt path's invariants (drain in-flight tasks, flush logs) verbatim.

## 7. Sentinel writer extension

The existing `write_halt_sentinel` hardcodes `halted_by="telegram-/halt"`. Extend with an optional keyword:

```python
def write_halt_sentinel(
    reason: str,
    ts_ns: int,
    *,
    path: Path = DEFAULT_SENTINEL_PATH,
    by: str = "telegram-/halt",    # backward-compatible default
) -> None:
```

`halted_by` field in the JSON payload uses `by`. Existing call site (`alerter/service.py:176` context) is unaffected. New L.5 call site passes `by="auto-halt-daily-loss"`. This mirrors the original L.5 commit `3277225`'s halt.py extension exactly.

## 8. Env-var wiring (`scripts/run_paper.py`)

```python
daily_loss_halt_usd = _env_float("DAILY_LOSS_HALT_USD", 0.0) or 0.0
```

Pass to `PaperRunner(..., daily_loss_halt_usd=daily_loss_halt_usd)`.

`0.0` is the default — guard disabled — so this change is dark for any deploy that doesn't set the env var. Phase T Session 2's `.envrc` will set `DAILY_LOSS_HALT_USD=300` (10% of $3k) at the next natural restart per `feedback_defer_deploys_to_natural_restart`.

## 9. Tests

Target: 6+ tests (5 minimum per session prompt §3). All in `tests/test_daily_loss_guard.py`.

| # | Test | Verifies |
|---|---|---|
| 1 | `test_trip_when_threshold_crossed` | One synthetic settle that pushes today PnL ≤ −threshold → halt sentinel written exactly once |
| 2 | `test_no_trip_when_above_threshold` | Multiple settles staying above −threshold → sentinel NEVER written |
| 3 | `test_threshold_zero_is_disabled` | `threshold_usd=0.0` → any loss magnitude does not trip |
| 4 | `test_truth_corrected_anchor_restart_mid_day` | Pre-populate today's log with −$200 of settles → on first evaluate, anchor = bankroll + 200 → small additional loss does not trip if total still above threshold |
| 5 | `test_utc_rollover_resets_anchor` | Trip on day N; advance clock to day N+1; small loss day N+1 does NOT trip; new day's anchor is fresh |
| 6 | `test_idempotent_after_trip` | After tripping, further evaluate() calls return None and do NOT re-write sentinel |
| 7 | `test_correction_overlay_can_trigger_trip` | A `settled_correction` that net-erases a prior win pushes today PnL across threshold |

Test pattern: inject a fake `halt_writer` that records calls into a list. Inject a fake `clock_utc` for deterministic dates. Write fake JSONL records under a `tmp_path / "state/decisions"` tree for the log-derived anchor tests.

No integration test against PaperRunner in P1 — unit tests + the existing PaperRunner test surface (which exercises the bankroll path) cover the wiring contract. A smoke run on the VPS at the next natural restart confirms the end-to-end.

## 10. Acceptance gates

- `ruff check .` clean
- `mypy --strict src/polymarket_bot/_paper/daily_loss_guard.py src/polymarket_bot/_paper/runner.py` clean
- `pytest tests/test_daily_loss_guard.py -v` — all new tests green
- `pytest` — full suite green (no regressions in 694 existing tests)

## 11. Do-not-do (per session prompt §5 + project policy)

- Do NOT deploy this change mid-soak. P1 ships code + tests + push to origin only. The operator decides when to flip `DAILY_LOSS_HALT_USD` in `.envrc` and restart `bot-staging.service`.
- Do NOT bundle with cell-flip enable or hour-blocklist (P3 / P4 — session prompt §5).
- Do NOT alter the existing halt-sentinel JSON schema beyond the `halted_by` field re-use.
- Do NOT add auto-resume — operator-only.

## 12. Open question parked for after P1

- Should the threshold be percent-of-day-start instead of absolute USD? Easier to reason about across bankroll-reset boundaries. For P1, absolute USD matches operator's prompt verbatim (`DAILY_LOSS_HALT_USD=300`). Convert to pct after first trip in production if it bites.
