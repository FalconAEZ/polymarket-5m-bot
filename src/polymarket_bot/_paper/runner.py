"""PaperRunner — live-feed fan-in -> Strategy -> ShadowBook -> DecisionLog.

Phase 4 paper-trading runtime per design/paper.md §4.2. Subscribes to a
sequence of live Feed instances (production passes the four real WS feeds
from polymarket_bot._live.feeds; tests pass FakeFeed). Each Record is
decoded into MarketEvents via polymarket_bot.backtest.replay.decode_record
(reused so paper and backtest share the decoder). WindowBoundary events
are synthesised at every 300s rollover. Decisions returned by the
Strategy are queued and tried against ShadowBook on each subsequent
matching BookUpdate within decision.ttl_s. At window close, P&L is
realised against the oracle samples seen at open and close, and a
`settled` line is written to DecisionLog. One pending decision per
window — Phase 3 strategy invariant; relaxed in Phase 8 if needed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from polymarket_bot._live.alerter.halt import write_halt_sentinel
from polymarket_bot._paper.daily_loss_guard import DailyLossGuard
from polymarket_bot._paper.decision_log import DecisionLog, read_jsonl
from polymarket_bot._paper.shadow_book import ShadowBook
from polymarket_bot.alerts import Alert, AlertSink, Level, NullAlertSink
from polymarket_bot.backtest.replay import SideResolver, decode_record
from polymarket_bot.backtest.types import (
    BookUpdate,
    Decision,
    Fill,
    MarketEvent,
    OracleUpdate,
    Side,
    SpotTick,
    WindowBoundary,
)
from polymarket_bot.feeds.protocols import Feed, Record
from polymarket_bot.gamma_resolver import gamma_resolution, poll_gamma_for_resolution
from polymarket_bot.resolver import (
    WINDOW_SECONDS,
    active_window_ts,
    actual_resolution,
)
from polymarket_bot.strategies.protocol import Strategy

LOG = logging.getLogger("polymarket_bot._paper.runner")

DEFAULT_QUEUE_SIZE = 1024
# Instant-settle defaults — see design/instant_settlement.md and the
# 2026-05-10 audit (runbooks/incidents/2026-05-10-settle-resolution-bug.md).
# Live observation: with the previous 30s/1s defaults, gamma instant-settle
# succeeded 0/22 times — every settle fell through to chainlink-local, which
# disagrees with on-chain truth on ~33% of windows. Gamma typically becomes
# `closed=true` within 1-3 minutes of T+300; the new 5-minute timeout covers
# that window. With background-settle (commit 43872e9) the long poll does
# not block the main loop, so a generous timeout is now safe.
# Per-poll interval bumped 1s → 5s to reduce gamma load and sidestep the
# CDN/cache TTL hypothesis (cached "not closed yet" responses for ~1-30s).
DEFAULT_INSTANT_SETTLE_TIMEOUT_S = 300.0
DEFAULT_INSTANT_SETTLE_INTERVAL_S = 5.0

# Post-hoc gamma re-resolution defaults. After the chainlink-local fallback
# writes a `settled` record, the bot schedules a background task that waits
# briefly for gamma to catch up, then re-polls. If gamma's truth disagrees
# with the recorded chainlink resolution, a `settled_correction` record is
# appended to the same JSONL — the original `settled` is preserved so the
# audit trail is intact. Defaults: wait 5 min before first retry, poll
# every 30s for up to ~25 min total. Off-by-default flag wires through env
# `POST_HOC_GAMMA_RETRY_ENABLED` so the operator has a 30s kill-switch.
DEFAULT_POST_HOC_RETRY_INITIAL_DELAY_S = 300.0
DEFAULT_POST_HOC_RETRY_INTERVAL_S = 30.0
DEFAULT_POST_HOC_RETRY_MAX_ATTEMPTS = 50

# Periodic orphan-recovery sweep. Per audit 2026-05-10 16:18 UTC:
# window 1778428800 was permanently orphaned because the bot was
# restarted at 16:05:30 mid-settle, gamma still hadn't resolved by the
# new bot's startup at 16:05:51, orphan-recovery counted it as
# "unresolved" and never retried. With the periodic sweep, the bot
# rechecks unresolved orphans every PERIODIC_ORPHAN_RECOVERY_INTERVAL_S
# seconds — gamma typically resolves within 1-3 min so a 5-min sweep
# catches everything. Bounded by the date-window of orphan_recovery_
# lookback_days so the sweep is cheap.
DEFAULT_PERIODIC_ORPHAN_RECOVERY_INTERVAL_S = 300.0

# Post-hoc retry phantom-detection thresholds — mirror
# scripts/backfill_phantom_floor_fills.py AUTO_FILL_PRICE_MAX /
# AUTO_FILL_SIZE_MIN. When the existing fill matches the phantom pattern
# (near-floor price + large size), the post-hoc gamma retry must NOT
# recompute pnl from `size * payout - cost - fee` — that turns a
# phantom -$5 loss into a phantom +$161 win when gamma flips the side.
# Instead, write corrected_pnl_usd=0 + phantom_fill=true so the
# dashboard / rollup neutralize it.
POST_HOC_PHANTOM_PRICE_MAX = 0.05
POST_HOC_PHANTOM_SIZE_MIN = 50.0


def _fill_matches_phantom_pattern(fill: Fill | None) -> bool:
    """A fill at <= POST_HOC_PHANTOM_PRICE_MAX and >= POST_HOC_PHANTOM_SIZE_MIN
    is the simulator-bug signature: depth was unknown, size was over-filled
    at the floor. Pnl-from-fill cannot be trusted for these — the user-
    visible truth is "no realistic trade actually happened, pnl=$0".
    """
    if fill is None:
        return False
    return (
        fill.price_filled <= POST_HOC_PHANTOM_PRICE_MAX
        and fill.size_filled >= POST_HOC_PHANTOM_SIZE_MIN
    )


class PaperRunner:
    """Drive a Strategy over live feeds, simulating fills + writing decision_log."""

    def __init__(
        self,
        *,
        feeds: Sequence[Feed],
        strategy: Strategy,
        side_resolver: SideResolver,
        shadow_book: ShadowBook | None = None,
        decision_log: DecisionLog | None = None,
        clock_ns: Callable[[], int] | None = None,
        queue_size: int = DEFAULT_QUEUE_SIZE,
        alert_sink: AlertSink | None = None,
        alert_source: str = "bot-staging",
        # Instant-settle: when enabled, _settle_current_window polls
        # Polymarket Gamma for the truth resolution before falling back to
        # the local Chainlink-derived actual_resolution(). Disabled by
        # default to preserve legacy behavior; enabled in production via
        # scripts/run_paper.py reading INSTANT_SETTLE_* env vars.
        # gamma_client is injected for testability (MockTransport in tests);
        # production passes a real httpx.Client with timeouts.
        instant_settle_enabled: bool = False,
        gamma_client: httpx.Client | None = None,
        instant_settle_timeout_s: float = DEFAULT_INSTANT_SETTLE_TIMEOUT_S,
        instant_settle_interval_s: float = DEFAULT_INSTANT_SETTLE_INTERVAL_S,
        # Orphan-fire recovery — at startup, scan recent decision-log
        # files for `fired` records that have no matching `settled`
        # record (e.g., from a deploy-time restart that occurred mid-
        # window) and post-hoc resolve them via Polymarket Gamma. Off
        # by default to preserve legacy behavior; production wires the
        # ORPHAN_RECOVERY_ENABLED env var (default true) in run_paper.py.
        # Idempotent: a re-run skips already-settled decisions, so two
        # consecutive startups don't double-write.
        orphan_recovery_enabled: bool = False,
        orphan_recovery_lookback_days: int = 1,
        # Post-hoc gamma re-resolution — after a chainlink-local-fallback
        # writes a settled record, schedule a background task that polls
        # gamma a few minutes later and appends a `settled_correction`
        # record if the truths disagree. Off-by-default to preserve
        # legacy behavior; production wires POST_HOC_GAMMA_RETRY_ENABLED
        # (default true) in run_paper.py. Defaults match
        # DEFAULT_POST_HOC_RETRY_* constants. Tunable for tests.
        post_hoc_gamma_retry_enabled: bool = False,
        post_hoc_retry_initial_delay_s: float = DEFAULT_POST_HOC_RETRY_INITIAL_DELAY_S,
        post_hoc_retry_interval_s: float = DEFAULT_POST_HOC_RETRY_INTERVAL_S,
        post_hoc_retry_max_attempts: int = DEFAULT_POST_HOC_RETRY_MAX_ATTEMPTS,
        # Periodic orphan-recovery sweep — re-runs orphan_recovery on a
        # timer (default every 5 min). Catches windows that were unresolved
        # at startup-time but have since become resolvable. Audit
        # 2026-05-10 16:18 UTC: window 1778428800 was permanently
        # orphaned by a startup-only recovery; periodic catches that case.
        # Off-by-default; production wires PERIODIC_ORPHAN_RECOVERY_ENABLED
        # (default true) in run_paper.py.
        periodic_orphan_recovery_enabled: bool = False,
        periodic_orphan_recovery_interval_s: float = DEFAULT_PERIODIC_ORPHAN_RECOVERY_INTERVAL_S,
        # BankrollTracker — Kelly feedback loop for v2.1+. The tracker
        # always exists (default $1000 from locked decision #10) so any
        # strategy can read it via runner._bankroll.current. Replay-on-
        # startup walks recent state/decisions/*.jsonl files and replays
        # settled + settled_correction records into the tracker so a
        # restart doesn't reset the compound clock. Default off to
        # preserve legacy behaviour; production wires both flags via
        # PMB_STARTING_BANKROLL + BANKROLL_REPLAY_ENABLED env vars in
        # run_paper.py. Spec §5.2-5.3 / design/spot_aware_v2_1.md.
        bankroll_starting_usd: float = 1000.0,
        bankroll_replay_on_start: bool = False,
        bankroll_replay_lookback_days: int = 14,
        # H.2.3 multi-fire cap. Default 1 preserves Phase-3 single-fire-
        # per-window invariant for v1/v2/v3/wide_fire. v2.1 wires 2 from
        # the MULTI_FIRE_CAP env var via run_paper.py. Spec §6.2.
        multi_fire_cap: int = 1,
        # Phase T Session 2 P1 — runner-level daily-loss guard. Continuous
        # check after every bankroll mutation; on trip, writes the standard
        # state/halt.sentinel so the run_paper.py halt watcher exits the bot
        # gracefully. 0.0 (default) disables. Wired via DAILY_LOSS_HALT_USD
        # env var in run_paper.py. See design/phase-T-l5-runner-daily-loss-
        # guard.md.
        daily_loss_halt_usd: float = 0.0,
    ) -> None:
        if not feeds:
            raise ValueError("PaperRunner requires at least one Feed")
        self._feeds: list[Feed] = list(feeds)
        self._strategy = strategy
        self._side_resolver = side_resolver
        self._shadow = shadow_book if shadow_book is not None else ShadowBook()
        self._log = decision_log if decision_log is not None else DecisionLog()
        self._clock_ns: Callable[[], int] = clock_ns if clock_ns is not None else time.time_ns
        self._queue_size = queue_size
        self._stop = asyncio.Event()
        self._dropped = 0
        if multi_fire_cap < 1:
            raise ValueError(f"multi_fire_cap must be >= 1; got {multi_fire_cap}")
        self._state = _RunState(multi_fire_cap=multi_fire_cap)
        self._alerts: AlertSink = alert_sink if alert_sink is not None else NullAlertSink()
        self._alert_source = alert_source
        self._instant_settle_enabled = instant_settle_enabled
        self._gamma_client = gamma_client
        self._instant_settle_timeout_s = instant_settle_timeout_s
        self._instant_settle_interval_s = instant_settle_interval_s
        self._gamma_timeout_count = 0
        # Background-settle bookkeeping. Per the 2026-05-09 instant-settle
        # incident postmortem: settle is fire-and-forget, snapshot-driven, so
        # the main loop can keep pulling from the queue while gamma polls.
        # Shutdown awaits this set so settled records aren't lost on stop.
        self._pending_settles: set[asyncio.Task[None]] = set()
        self._orphan_recovery_enabled = orphan_recovery_enabled
        self._orphan_recovery_lookback_days = orphan_recovery_lookback_days
        self._post_hoc_gamma_retry_enabled = post_hoc_gamma_retry_enabled
        self._post_hoc_retry_initial_delay_s = post_hoc_retry_initial_delay_s
        self._post_hoc_retry_interval_s = post_hoc_retry_interval_s
        self._post_hoc_retry_max_attempts = post_hoc_retry_max_attempts
        # Tracks in-flight post-hoc retry tasks the same way settle does, so
        # shutdown can await them and we don't lose corrections on stop.
        self._pending_post_hoc_retries: set[asyncio.Task[None]] = set()
        self._post_hoc_corrections_total = 0
        self._periodic_orphan_recovery_enabled = periodic_orphan_recovery_enabled
        self._periodic_orphan_recovery_interval_s = max(30.0, periodic_orphan_recovery_interval_s)
        # Tracks the periodic-recovery task so shutdown can cancel + await it.
        self._periodic_orphan_task: asyncio.Task[None] | None = None
        self._bankroll = BankrollTracker(starting_usd=bankroll_starting_usd)
        self._bankroll_replay_on_start = bankroll_replay_on_start
        self._bankroll_replay_lookback_days = bankroll_replay_lookback_days
        # Phase T Session 2 P1 — construct the daily-loss guard once at
        # __init__ so the same instance threads through both bankroll
        # mutation sites (settle + post-hoc correction). Disabled state
        # is represented by guard is None — keeps the hot path branch-free
        # when the operator has the env var off.
        self._daily_loss_guard: DailyLossGuard | None = None
        if daily_loss_halt_usd > 0.0:
            self._daily_loss_guard = DailyLossGuard(
                threshold_usd=daily_loss_halt_usd,
                log_root=self._log.root,
                halt_writer=lambda reason, ts_ns: write_halt_sentinel(
                    reason,
                    ts_ns,
                    by="auto-halt-daily-loss",
                ),
            )

    def _maybe_trip_daily_loss_guard(self) -> None:
        """Phase T Session 2 P1 — call after every bankroll mutation
        (settle + post-hoc correction). On trip, the guard writes
        ``state/halt.sentinel``; this method only emits the alert/log so
        the operator sees why. The existing _halt_watcher in run_paper.py
        observes the sentinel and stops the runner gracefully."""
        if self._daily_loss_guard is None:
            return
        result = self._daily_loss_guard.evaluate(bankroll_current=self._bankroll.current())
        if result is None or not result.tripped:
            return
        LOG.critical(
            "daily-loss guard tripped: today_pnl=%.2f threshold=-%.2f day=%s",
            result.today_pnl_usd,
            result.threshold_usd,
            result.anchored_day.isoformat(),
        )
        self._alert(
            Level.CRITICAL,
            (
                f"auto-halt daily-loss: today=${result.today_pnl_usd:.2f} "
                f"<= -${result.threshold_usd:.2f}"
            ),
            today_pnl_usd=result.today_pnl_usd,
            threshold_usd=result.threshold_usd,
            anchored_day=result.anchored_day.isoformat(),
        )

    def _alert(self, level: Level, message: str, **fields: str | int | float) -> None:
        try:
            self._alerts.publish(
                Alert(
                    level=level,
                    message=message,
                    ts_ns=self._clock_ns(),
                    source=self._alert_source,
                    fields=fields,
                )
            )
        except Exception:
            # AlertSink contract says publish never raises, but defend anyway —
            # the trading hot path must not break if a sink misbehaves.
            LOG.exception("alert publish raised; suppressed")

    @property
    def dropped_records_total(self) -> int:
        return self._dropped

    @property
    def bankroll(self) -> BankrollTracker:
        """Live bankroll tracker — read via ``.current()`` for compounding strategies."""
        return self._bankroll

    def stop(self) -> None:
        self._stop.set()
        for feed in self._feeds:
            feed.stop()

    async def run(self, *, stop: asyncio.Event | None = None) -> None:
        # BankrollTracker startup replay — walks state/decisions/<UTC-date>.jsonl
        # over the lookback window and re-applies settled + settled_correction
        # records so the compound clock survives restarts. Opt-in via env;
        # default off to preserve legacy behaviour. Spec §5.3.
        if self._bankroll_replay_on_start:
            try:
                replayed = replay_bankroll_from_log(
                    log_root=self._log.root,
                    starting_usd=self._bankroll.starting_usd,
                    lookback_days=self._bankroll_replay_lookback_days,
                )
                self._bankroll = replayed
                LOG.info(
                    "bankroll replay: starting=$%.2f current=$%.2f",
                    self._bankroll.starting_usd,
                    self._bankroll.current(),
                )
            except Exception as exc:
                LOG.exception("bankroll replay raised; continuing with starting bankroll")
                self._alert(
                    Level.WARN,
                    f"bankroll replay raised: {exc}",
                )

        # Orphan-fire recovery — runs once at startup, BEFORE the main
        # event loop. Fires that lost their close-side settle (e.g.,
        # because the bot was restarted between fire and window-close)
        # are post-hoc resolved against Polymarket Gamma. A failure here
        # never blocks the runner: log + alert and proceed.
        if self._orphan_recovery_enabled:
            try:
                await self._recover_orphan_fires()
            except Exception as exc:
                LOG.exception("orphan recovery raised; continuing startup")
                self._alert(
                    Level.WARN,
                    f"orphan recovery raised: {exc}",
                )

        # Cross-restart double-fire guard — operator-observed bug
        # 2026-05-10 03:55 UTC: bot was restarted at 03:59:44 UTC, but
        # window 1778385300 (opened 03:55:00) had already been fired by
        # the OLD bot at 03:55:00 (DOWN, tier 85-100%). The NEW bot
        # started with fresh `_state` and didn't know about that fire,
        # so when wide_fire emitted a candidate at 03:59:46 the runner
        # accepted it (UP, tier 30-50%). Net: two opposing bets on the
        # same 5m market, guaranteed -$5 loss. Orphan recovery only
        # handles PAST windows; this handles the CURRENT one. Pre-
        # populates self._state with the prior fire so the existing
        # duplicate-fire guard in `_on_decision` rejects new candidates
        # in the same window. Cheap (one file read) and idempotent.
        try:
            self._prime_active_window_state()
        except Exception as exc:
            LOG.exception("active-window prime raised; continuing startup")
            self._alert(
                Level.WARN,
                f"active-window prime raised: {exc}",
            )

        external_stop = stop
        queue: asyncio.Queue[Record | None] = asyncio.Queue(self._queue_size)

        async def pump(feed: Feed) -> None:
            try:
                async for record in feed.stream():
                    if self._stop.is_set() or (
                        external_stop is not None and external_stop.is_set()
                    ):
                        break
                    try:
                        queue.put_nowait(record)
                    except asyncio.QueueFull:
                        self._dropped += 1
                        with contextlib.suppress(asyncio.QueueEmpty):
                            queue.get_nowait()
                        with contextlib.suppress(asyncio.QueueFull):
                            queue.put_nowait(record)
                        if self._dropped == 1 or self._dropped % 100 == 0:
                            self._alert(
                                Level.WARN,
                                f"paper-runner queue overflow; dropped={self._dropped}",
                                dropped_total=self._dropped,
                            )
            except asyncio.CancelledError:
                raise
            finally:
                await queue.put(None)

        tasks = [asyncio.create_task(pump(f), name=f"paper-pump-{f.name}") for f in self._feeds]
        active = len(tasks)
        # Periodic orphan-recovery sweep — runs in parallel with the main
        # consumer loop. Every interval seconds it re-scans for orphans
        # and resolves any whose gamma has caught up since startup. This
        # closes the "restart-during-settle while gamma is still pending"
        # gap (audit 2026-05-10 16:18 UTC, window 1778428800).
        if (
            self._periodic_orphan_recovery_enabled
            and self._orphan_recovery_enabled
            and self._gamma_client is not None
        ):
            self._periodic_orphan_task = asyncio.create_task(
                self._periodic_orphan_recovery_loop(), name="periodic-orphan-recovery"
            )
        try:
            while active > 0:
                if external_stop is not None and external_stop.is_set():
                    break
                if self._stop.is_set():
                    break
                record = await queue.get()
                if record is None:
                    active -= 1
                    continue
                await self._on_record(record)
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            # Cancel + await the periodic orphan-recovery task. Cancel
            # first so its own asyncio.sleep wakes up as CancelledError;
            # then gather with return_exceptions so a hung sweep can't
            # block shutdown.
            if self._periodic_orphan_task is not None:
                self._periodic_orphan_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._periodic_orphan_task
            # Wait for in-flight background settle tasks before closing the
            # log. Snapshot the set first because each task's done_callback
            # discards itself from the live set, which would mutate during
            # iteration. asyncio.gather returns_exceptions so a single bad
            # settle doesn't abort the wait.
            if self._pending_settles:
                pending = list(self._pending_settles)
                LOG.info("awaiting %d in-flight settle tasks", len(pending))
                await asyncio.gather(*pending, return_exceptions=True)
            # Also await post-hoc gamma retries so a stop-mid-retry doesn't
            # silently drop a pending correction record. Snapshot first
            # because each task's done_callback discards itself.
            if self._pending_post_hoc_retries:
                pending_retries = list(self._pending_post_hoc_retries)
                LOG.info("awaiting %d in-flight post-hoc gamma retries", len(pending_retries))
                await asyncio.gather(*pending_retries, return_exceptions=True)
            # Strategies that own background tasks (e.g., EnsembleWrapper's
            # shadow-mode LLM votes) get an aclose() callout so their
            # work finishes writing to disk before we close the decision
            # log. Optional protocol — if the strategy has no aclose,
            # skip silently.
            aclose = getattr(self._strategy, "aclose", None)
            if callable(aclose):
                try:
                    await aclose()
                except Exception:
                    LOG.exception("strategy.aclose() raised; ignoring on shutdown")
            self._log.close()

    async def _on_record(self, record: Record) -> None:
        events = decode_record(record, self._side_resolver)
        for event in events:
            await self._on_event(event)

    async def _on_event(self, event: MarketEvent) -> None:
        await self._maybe_emit_boundaries(event.ts_utc_ns)

        if isinstance(event, BookUpdate):
            self._shadow.update(event)
            self._state.observe_book(event)
            self._try_fill_pending(event.ts_utc_ns)
        elif isinstance(event, OracleUpdate):
            self._state.observe_oracle(event)
        elif isinstance(event, SpotTick):
            self._state.observe_spot(event)

        decision = await self._strategy.on_event(event)
        if decision is not None:
            self._on_decision(decision)

    async def _maybe_emit_boundaries(self, now_ts_ns: int) -> None:
        now_s = now_ts_ns // 1_000_000_000
        new_window_ts = active_window_ts(now_s)
        current = self._state.window_ts
        if current is None:
            self._state.start_window(new_window_ts)
            await self._strategy.on_event(
                WindowBoundary(
                    ts_utc_ns=new_window_ts * 1_000_000_000,
                    window_ts=new_window_ts,
                    kind="open",
                )
            )
            return
        if new_window_ts == current:
            return
        # Crossed at least one boundary. Settle the current window first
        # (close), then open the new one. If we skipped multiple windows
        # (no traffic for >5m — shouldn't happen, but guarded), only the
        # most recent close+open pair is emitted; intermediate windows
        # never had decisions to settle.
        await self._strategy.on_event(
            WindowBoundary(
                ts_utc_ns=(current + WINDOW_SECONDS) * 1_000_000_000,
                window_ts=current,
                kind="close",
            )
        )
        # H.2.3 multi-fire: snapshot each pending decision BEFORE
        # start_window clears the list, then fire-and-forget one settle
        # task per snapshot. The main loop returns to processing records
        # immediately while gamma polls each task in parallel.
        # Per runbooks/incidents/2026-05-09-instant-settle-queue-overflow.md.
        for snap in self._snapshots_for_settle():
            task = asyncio.create_task(
                self._settle_window_background(snap),
                name=f"settle-{snap.window_ts}-{snap.decision_id[:8]}",
            )
            self._pending_settles.add(task)
            task.add_done_callback(self._pending_settles.discard)
        self._state.start_window(new_window_ts)
        await self._strategy.on_event(
            WindowBoundary(
                ts_utc_ns=new_window_ts * 1_000_000_000,
                window_ts=new_window_ts,
                kind="open",
            )
        )

    def _on_decision(self, decision: Decision) -> None:
        # H.2.3 multi-fire refactor: the per-window cap is configurable.
        # For v1/v2/v3/wide_fire (cap=1) the guard preserves the Phase-3
        # invariant exactly; for v2.1 (cap=2 by default) the second fire
        # is admitted, the third dropped. Counted by list length so the
        # cap is unambiguous regardless of which decision filled when.
        if self._state.window_ts is None:
            LOG.warning("decision arrived before window boundary; dropping")
            self._alert(Level.WARN, "decision arrived before window boundary; dropped")
            return
        cap = self._state.multi_fire_cap
        if len(self._state.pending_decisions) >= cap:
            if cap == 1:
                LOG.warning(
                    "second decision in window %s; dropping",
                    self._state.window_ts,
                )
                self._alert(
                    Level.WARN,
                    f"second decision in window {self._state.window_ts}; dropped",
                    window_ts=self._state.window_ts,
                )
            else:
                LOG.info(
                    "fire %d would exceed multi_fire_cap=%d in window %s; dropping",
                    len(self._state.pending_decisions) + 1,
                    cap,
                    self._state.window_ts,
                )
            return
        side = _side_from_rationale(decision.rationale)
        if side is None:
            LOG.warning(
                "decision rationale missing side= marker; dropping (asset=%s)",
                decision.asset_id,
            )
            self._alert(
                Level.WARN,
                "decision rationale missing side= marker; dropped",
                asset_id=decision.asset_id,
            )
            return
        # Try immediate fill against the latest book in the shadow book.
        # Taker path — we're crossing the existing book at decision time.
        fill = self._shadow.attempt_fill(decision, decision.ts_utc_ns, is_taker=True)
        snapshot = self._snapshot_for_log(decision)
        composite = _composite_from_rationale(decision.rationale)
        # OSError guard: per audit 2026-05-10, an uncaught DecisionLog write
        # exception (disk full, NFS unmount, permissions) would propagate up
        # the async stack and kill the entire runner. We catch + alert + drop
        # the decision rather than crash. The bot keeps running; the operator
        # gets a CRITICAL page; the next decision retries the write.
        try:
            decision_id = self._log.record_fired(
                decision=decision,
                side=side,
                window_ts=self._state.window_ts,
                snapshot=snapshot,
                composite_pct=composite,
                fill=fill,
            )
        except OSError as exc:
            LOG.critical("decision_log.record_fired raised OSError: %s", exc)
            self._alert(
                Level.CRITICAL,
                f"decision_log.record_fired raised OSError; decision dropped: {exc}",
                asset_id=decision.asset_id,
                window_ts=self._state.window_ts,
            )
            return
        self._state.record_decision(decision, side, decision_id, fill)

    def _try_fill_pending(self, now_ts_ns: int) -> None:
        # H.2.3 multi-fire: iterate every still-unfilled pending decision
        # and try a maker fill on each. Each decision keys to its own
        # asset_id (carried on the Decision) so the shadow book picks the
        # correct side. Order is insertion order — first-fired gets first
        # crack at the new book, which mirrors single-fire semantics for
        # cap=1.
        for pd in self._state.pending_decisions:
            if pd.settled_fill is not None:
                continue
            # Maker path — our limit is resting; an incoming seller crosses the
            # spread to hit it. Fill at our limit (price-improvement to maker),
            # NOT at the new (potentially much lower) ask. See fills.py docstring
            # for the simulator-bug postmortem this guards against.
            fill = self._shadow.attempt_fill(pd.decision, now_ts_ns, is_taker=False)
            if fill is not None:
                pd.settled_fill = fill

    async def _recover_orphan_fires(self) -> None:
        # Scan today's + the previous N UTC-day decision-log files for
        # `fired` records that have no matching `settled` record. For
        # each orphan whose closing window is in the past, look up the
        # truth via Polymarket Gamma and write a synthetic settled
        # record (resolution_source="polymarket-recovery"). Idempotent
        # because already-settled fires are filtered out by decision_id.
        if self._gamma_client is None:
            LOG.info("orphan recovery skipped: no gamma_client configured")
            return

        from datetime import UTC, datetime, timedelta

        log_root = self._log.root
        now_s = self._clock_ns() // 1_000_000_000
        current_window = active_window_ts(now_s)
        today = datetime.fromtimestamp(now_s, tz=UTC).date()
        dates = [today - timedelta(days=i) for i in range(self._orphan_recovery_lookback_days + 1)]

        fired_by_id: dict[str, dict[str, Any]] = {}
        settled_ids: set[str] = set()
        for d in dates:
            path = log_root / f"{d.strftime('%Y-%m-%d')}.jsonl"
            if not path.exists():
                continue
            for rec in read_jsonl(path):
                kind = rec.get("kind")
                did = rec.get("decision_id")
                if not isinstance(did, str):
                    continue
                if kind == "fired":
                    fired_by_id[did] = rec
                elif kind == "settled":
                    settled_ids.add(did)

        orphans = [
            (did, rec)
            for did, rec in fired_by_id.items()
            if did not in settled_ids
            and isinstance(rec.get("window_ts"), int)
            and rec["window_ts"] < current_window
        ]
        if not orphans:
            LOG.info("orphan recovery: 0 orphans found")
            return

        LOG.info("orphan recovery: %d orphans to resolve", len(orphans))
        recovered = 0
        unresolved = 0
        for decision_id, fired in orphans:
            window_ts = int(fired["window_ts"])
            try:
                truth = await asyncio.to_thread(
                    gamma_resolution, window_ts, client=self._gamma_client
                )
            except Exception as exc:
                LOG.warning(
                    "orphan recovery gamma fetch raised for window %s: %s",
                    window_ts,
                    exc,
                )
                unresolved += 1
                continue
            if truth not in ("UP", "DOWN"):
                # Gamma hasn't resolved yet (or never will). Leave the
                # orphan — a later startup will retry.
                unresolved += 1
                continue
            fill = _fill_from_dict(fired.get("fill"))
            side = fired.get("side")
            if side not in ("UP", "DOWN"):
                # Defensive: a fired record without a parseable side can't
                # be settled. Skip + count as unresolved.
                unresolved += 1
                continue
            won = truth == side
            pnl = _realised_pnl(fill, won) if fill is not None else 0.0
            try:
                self._log.record_settled(
                    decision_id=decision_id,
                    window_ts=window_ts,
                    settled_ts_ns=self._clock_ns(),
                    open_oracle=None,
                    close_oracle=None,
                    resolution=truth,
                    fill_at_settle=fill,
                    pnl_usd=pnl,
                    resolution_source="polymarket-recovery",
                )
            except OSError as exc:
                LOG.critical("orphan recovery record_settled OSError: %s", exc)
                self._alert(
                    Level.CRITICAL,
                    f"orphan recovery record_settled OSError: {exc}",
                    decision_id=decision_id,
                    window_ts=window_ts,
                )
                continue
            recovered += 1
        LOG.info(
            "orphan recovery complete: recovered=%d unresolved=%d",
            recovered,
            unresolved,
        )
        if recovered > 0:
            self._alert(
                Level.INFO,
                f"orphan recovery: recovered={recovered} unresolved={unresolved}",
                recovered=recovered,
                unresolved=unresolved,
            )

    async def _periodic_orphan_recovery_loop(self) -> None:
        """Re-runs orphan recovery on a timer so windows that were
        unresolvable at startup get retried as gamma catches up.

        Audit 2026-05-10 16:18 UTC: window 1778428800 was permanently
        orphaned because the bot was restarted at 16:05:30 mid-settle.
        At the new bot's startup orphan-recovery (16:05:51) gamma
        hadn't yet resolved the window, so it was counted "unresolved"
        and never retried. With this loop, it would have been picked up
        on the next sweep ~5min later.

        Fire-and-forget exception handling: any failure in a single
        sweep is logged + alerted but never propagates to the runner.
        """
        # Initial delay so the first sweep doesn't pile on top of the
        # startup-time recovery (which just ran).
        try:
            await asyncio.sleep(self._periodic_orphan_recovery_interval_s)
            while not self._stop.is_set():
                try:
                    await self._recover_orphan_fires()
                except Exception as exc:
                    LOG.exception("periodic orphan recovery sweep raised; continuing")
                    self._alert(
                        Level.WARN,
                        f"periodic orphan recovery sweep raised: {exc}",
                    )
                await asyncio.sleep(self._periodic_orphan_recovery_interval_s)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOG.exception("periodic orphan recovery loop crashed; will not restart")

    def _prime_active_window_state(self) -> None:
        # Scan today's decision_log for fired records in the CURRENT
        # 5m window (active_window_ts(now)). If found, pre-populate
        # self._state so _on_decision's existing duplicate-fire guard
        # rejects new candidates from the strategy.
        #
        # Why this matters even though `_recover_orphan_fires` runs
        # first: orphan recovery only handles PAST windows (fires
        # whose close has already happened). A fire in the CURRENT
        # window is legitimately pending — orphan recovery skips it.
        # Without this method, a restart mid-window leaves the new
        # runner unaware of the prior fire and a second decision in
        # the same window becomes possible.
        log_root = self._log.root
        now_s = self._clock_ns() // 1_000_000_000
        current_window = active_window_ts(now_s)

        from datetime import UTC, datetime

        today = datetime.fromtimestamp(now_s, tz=UTC).date()
        path = log_root / f"{today.strftime('%Y-%m-%d')}.jsonl"
        if not path.exists():
            return

        prior_fires_in_window: list[dict[str, Any]] = []
        settled_ids: set[str] = set()
        for rec in read_jsonl(path):
            did = rec.get("decision_id")
            if not isinstance(did, str):
                continue
            kind = rec.get("kind")
            if kind == "fired" and rec.get("window_ts") == current_window:
                prior_fires_in_window.append(rec)
            elif kind == "settled":
                settled_ids.add(did)

        # Only fires WITHOUT a settled record matter — settled fires are
        # over and don't conflict with a new fire in (technically) the
        # same window. (In practice, settled-in-current-window is rare
        # but possible if instant-settle resolved early.)
        unsettled = [f for f in prior_fires_in_window if f["decision_id"] not in settled_ids]
        if not unsettled:
            return

        # Use the most-recent unsettled fire — that's the one that
        # would conflict with the next fire from the strategy.
        most_recent = unsettled[-1]
        decision_id = most_recent["decision_id"]
        side = most_recent.get("side")
        if side not in ("UP", "DOWN"):
            return  # malformed; can't trust it
        LOG.info(
            "active window %s already has unsettled fire %s (side=%s); "
            "priming _state to block double-fire",
            current_window,
            decision_id[:8],
            side,
        )
        # Build a stub Decision to set as pending so the duplicate-fire
        # guard in _on_decision (`pending_decision is not None`) trips.
        try:
            stub = Decision(
                ts_utc_ns=int(most_recent["decision_ts_ns"]),
                asset_id=str(most_recent["asset_id"]),
                side="BUY",
                size_usd=float(most_recent["size_usd"]),
                price_limit=float(most_recent["price_limit"]),
                ttl_s=int(most_recent["ttl_s"]),
                rationale=str(most_recent.get("rationale", "")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            LOG.warning("could not reconstruct pending decision for prime: %s", exc)
            return

        # H.2.3 multi-fire: prime the pending_decisions list directly.
        # For cap=1 this restores the singular-pending pre-refactor
        # state exactly; for cap>=2 it leaves room for the strategy to
        # add up to (cap-1) more decisions in the same window.
        self._state.window_ts = current_window
        fill_dict = most_recent.get("fill")
        fill = _fill_from_dict(fill_dict)
        self._state.pending_decisions.append(
            _PendingDecision(
                decision=stub,
                decision_id=decision_id,
                side=side,
                settled_fill=fill,
            )
        )

    def _snapshots_for_settle(self) -> list[_SettleSnapshot]:
        # H.2.3 multi-fire: one snapshot per pending decision. Capture
        # everything the settle path needs BEFORE start_window clears
        # the list for the next window. Snapshots are the only state
        # the fire-and-forget settle tasks read, so they're decoupled
        # from any future _RunState mutation.
        s = self._state
        if s.window_ts is None or not s.pending_decisions:
            return []
        return [
            _SettleSnapshot(
                window_ts=s.window_ts,
                decision_id=pd.decision_id,
                open_oracle=s.open_oracle,
                close_oracle=s.close_oracle,
                side=pd.side,
                settled_fill=pd.settled_fill,
            )
            for pd in s.pending_decisions
        ]

    def _snapshot_for_settle(self) -> _SettleSnapshot | None:
        """Backward-compat shim: first pending decision's snapshot or
        None. Existing v2/v3/wide_fire callers keep their semantics for
        cap=1; v2.1 invokes ``_snapshots_for_settle`` directly."""
        snaps = self._snapshots_for_settle()
        return snaps[0] if snaps else None

    async def _settle_window_background(self, snap: _SettleSnapshot) -> None:
        # Top-level guard: a settle failure (gamma raise, log raise, etc.)
        # must NEVER propagate to the main event loop. Log + alert and
        # return; the runner stays alive for the next window.
        try:
            await self._do_settle(snap)
        except Exception as exc:
            LOG.exception("settle background task failed for window %s", snap.window_ts)
            try:
                self._alert(
                    Level.CRITICAL,
                    f"settle task failed: {exc}",
                    decision_id=snap.decision_id,
                    window_ts=snap.window_ts,
                )
            except Exception:
                LOG.exception("alert publish raised inside settle exception handler")

    async def _do_settle(self, snap: _SettleSnapshot) -> None:
        resolution: Side | None = None
        resolution_source: str | None = None

        # Instant-settle path — try Polymarket Gamma first if enabled.
        # Per design/instant_settlement.md: 30x faster than the Chainlink-
        # local fallback (60s -> 1-3s typical). Falls through to Chainlink
        # if Gamma times out or instant-settle is disabled.
        #
        # poll_gamma_for_resolution is synchronous (sleep+http) so we
        # asyncio.to_thread it. Because this whole method runs as a
        # fire-and-forget background task created by _maybe_emit_boundaries,
        # the main runner loop is NOT blocked on this await — it returned
        # to queue.get() the instant the task was scheduled.
        if self._instant_settle_enabled and self._gamma_client is not None:
            truth = await asyncio.to_thread(
                poll_gamma_for_resolution,
                snap.window_ts,
                client=self._gamma_client,
                timeout_s=self._instant_settle_timeout_s,
                interval_s=self._instant_settle_interval_s,
            )
            if truth in ("UP", "DOWN"):
                resolution = truth
                resolution_source = "polymarket"
            else:
                # Gamma didn't resolve in time. Increment counter; emit a
                # WARN alert every Nth failure so the operator notices a
                # degraded state without spamming on every single timeout.
                self._gamma_timeout_count += 1
                if self._gamma_timeout_count == 1 or self._gamma_timeout_count % 10 == 0:
                    LOG.warning(
                        "instant-settle gamma timeout #%d for window %s; "
                        "falling back to chainlink-local",
                        self._gamma_timeout_count,
                        snap.window_ts,
                    )
                    self._alert(
                        Level.WARN,
                        f"instant-settle gamma timeout x{self._gamma_timeout_count}; "
                        "falling back to chainlink-local",
                        gamma_timeout_total=self._gamma_timeout_count,
                        window_ts=snap.window_ts,
                    )

        # Chainlink-local fallback — also the legacy behavior when
        # instant-settle is disabled.
        if resolution is None and snap.open_oracle is not None and snap.close_oracle is not None:
            resolution = actual_resolution(snap.window_ts, snap.open_oracle, snap.close_oracle)
            if self._instant_settle_enabled:
                resolution_source = "chainlink-local-fallback"

        fill = snap.settled_fill
        pnl = 0.0
        if fill is not None and resolution is not None and snap.side is not None:
            pnl = _realised_pnl(fill, resolution == snap.side)
        settled_ts_ns = self._clock_ns()
        try:
            self._log.record_settled(
                decision_id=snap.decision_id,
                window_ts=snap.window_ts,
                settled_ts_ns=settled_ts_ns,
                open_oracle=snap.open_oracle,
                close_oracle=snap.close_oracle,
                resolution=resolution,
                fill_at_settle=fill,
                pnl_usd=pnl,
                resolution_source=resolution_source,
            )
        except OSError as exc:
            LOG.critical("decision_log.record_settled raised OSError: %s", exc)
            self._alert(
                Level.CRITICAL,
                f"decision_log.record_settled raised OSError; settle dropped: {exc}",
                decision_id=snap.decision_id,
                window_ts=snap.window_ts,
            )
            return
        # Update the live BankrollTracker for compounding strategies (v2.1+).
        # Only counted AFTER the disk write succeeds so a write failure
        # doesn't poison the tracker. Spec §5.2 / design CH6.
        self._bankroll.apply_settle(pnl)
        # Phase T Session 2 P1 — continuous daily-loss guard. No-op when
        # DAILY_LOSS_HALT_USD=0; otherwise compares today's realised PnL
        # against the operator threshold and writes halt.sentinel on trip.
        self._maybe_trip_daily_loss_guard()
        # Phase T Improvement #2 — notify strategy of settlement so the
        # cell-flip detector can update its rolling per-cell WR. Only
        # invoked when the strategy exposes on_settle (duck-typed) so
        # legacy strategies (deterministic, spot_aware, spot_aware_v2,
        # ensemble, wide_fire) are unaffected. won = pnl > 0 (binary).
        # Asset_id comes from the original fired Decision's asset_id;
        # snap captures it via settled_fill.asset_id when a fill exists,
        # otherwise the original decision's asset_id (stored on the
        # _PendingDecision). For abstained windows there's no settle so
        # this path doesn't run. See design/phase-T-cell-flip-detector.md.
        on_settle = getattr(self._strategy, "on_settle", None)
        if callable(on_settle):
            asset_id = snap.settled_fill.asset_id if snap.settled_fill is not None else None
            if asset_id is not None:
                try:
                    on_settle(window_ts=snap.window_ts, asset_id=asset_id, won=pnl > 0.0)
                except Exception:
                    LOG.exception(
                        "strategy.on_settle raised; ignoring (detector may miss this update)"
                    )

        # Schedule a post-hoc gamma re-resolution if we fell back to
        # chainlink-local. Per audit 2026-05-10: chainlink and gamma
        # disagree on ~33% of windows. The retry waits a few minutes for
        # gamma to catch up, then appends a settled_correction if the
        # truths differ. Fire-and-forget so the settle path returns
        # immediately; shutdown awaits the task.
        if (
            self._post_hoc_gamma_retry_enabled
            and resolution_source == "chainlink-local-fallback"
            and self._gamma_client is not None
        ):
            task = asyncio.create_task(
                self._post_hoc_gamma_retry(
                    snap=snap,
                    original_resolution=resolution,
                    original_pnl_usd=pnl,
                    original_settled_ts_ns=settled_ts_ns,
                ),
                name=f"post-hoc-gamma-{snap.window_ts}",
            )
            self._pending_post_hoc_retries.add(task)
            task.add_done_callback(self._pending_post_hoc_retries.discard)

    async def _post_hoc_gamma_retry(
        self,
        *,
        snap: _SettleSnapshot,
        original_resolution: Side | None,
        original_pnl_usd: float,
        original_settled_ts_ns: int,
    ) -> None:
        # Top-level guard: a failure here must NEVER propagate. Log + alert
        # and return; the runner stays alive and the next settle's retry
        # is independent.
        try:
            await asyncio.sleep(self._post_hoc_retry_initial_delay_s)
            client = self._gamma_client
            if client is None:
                # Caller already checks this; defensive narrowing for mypy.
                return
            for _attempt in range(self._post_hoc_retry_max_attempts):
                try:
                    truth = await asyncio.to_thread(gamma_resolution, snap.window_ts, client=client)
                except Exception as exc:
                    LOG.warning(
                        "post-hoc gamma retry fetch raised for window %s: %s",
                        snap.window_ts,
                        exc,
                    )
                    truth = None
                if truth in ("UP", "DOWN"):
                    if truth == original_resolution:
                        LOG.info(
                            "post-hoc gamma retry for window %s: agrees with chainlink (%s)",
                            snap.window_ts,
                            truth,
                        )
                        return
                    # Truths disagree — write a correction.
                    fill = snap.settled_fill
                    is_phantom = _fill_matches_phantom_pattern(fill)
                    if is_phantom:
                        # The fill was over-filled at the floor (depth
                        # unknown). Recomputing pnl as size * payout - cost
                        # would produce a phantom positive — turning a
                        # phantom -$5 loss into a phantom +$161 win. Refuse:
                        # write corrected_pnl_usd=0 + phantom_fill=true so
                        # the dashboard / rollup neutralize it.
                        corrected_pnl = 0.0
                    else:
                        corrected_pnl = (
                            _realised_pnl(fill, truth == snap.side)
                            if (fill is not None and snap.side is not None)
                            else 0.0
                        )
                    try:
                        self._log.record_settled_correction(
                            decision_id=snap.decision_id,
                            window_ts=snap.window_ts,
                            original_settled_ts_ns=original_settled_ts_ns,
                            original_resolution=original_resolution,
                            original_pnl_usd=original_pnl_usd,
                            corrected_resolution=truth,
                            corrected_pnl_usd=corrected_pnl,
                            corrected_ts_ns=self._clock_ns(),
                            fill_at_settle=fill,
                            phantom_fill=is_phantom,
                            phantom_reason=(
                                "post-hoc retry detected near-floor over-fill "
                                f"(price={fill.price_filled if fill else None}, "
                                f"size={fill.size_filled if fill else None}); "
                                "neutralizing pnl"
                                if is_phantom
                                else None
                            ),
                        )
                    except OSError as exc:
                        LOG.critical("decision_log.record_settled_correction OSError: %s", exc)
                        self._alert(
                            Level.CRITICAL,
                            f"settled_correction OSError; correction dropped: {exc}",
                            decision_id=snap.decision_id,
                            window_ts=snap.window_ts,
                        )
                        return
                    self._post_hoc_corrections_total += 1
                    # Apply the bankroll overlay (Phase 15.5). The original
                    # settled record already updated the tracker; this delta
                    # net-replaces that contribution with the corrected pnl.
                    self._bankroll.apply_correction(
                        original_pnl_usd=original_pnl_usd,
                        corrected_pnl_usd=corrected_pnl,
                    )
                    # Phase T Session 2 P1 — corrections shift today's PnL too.
                    self._maybe_trip_daily_loss_guard()
                    LOG.info(
                        "post-hoc gamma correction for window %s: %s -> %s " "(pnl %.4f -> %.4f)",
                        snap.window_ts,
                        original_resolution,
                        truth,
                        original_pnl_usd,
                        corrected_pnl,
                    )
                    self._alert(
                        Level.INFO,
                        f"post-hoc correction window {snap.window_ts}: "
                        f"{original_resolution} -> {truth}",
                        decision_id=snap.decision_id,
                        window_ts=snap.window_ts,
                        delta_pnl_usd=corrected_pnl - original_pnl_usd,
                    )
                    return
                await asyncio.sleep(self._post_hoc_retry_interval_s)
            LOG.info(
                "post-hoc gamma retry for window %s gave up after %d attempts",
                snap.window_ts,
                self._post_hoc_retry_max_attempts,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.exception("post-hoc gamma retry crashed for window %s", snap.window_ts)
            try:
                self._alert(
                    Level.WARN,
                    f"post-hoc gamma retry crashed: {exc}",
                    decision_id=snap.decision_id,
                    window_ts=snap.window_ts,
                )
            except Exception:
                LOG.exception("alert publish raised inside post-hoc retry exception handler")

    def _snapshot_for_log(self, decision: Decision) -> dict[str, float | None]:
        s = self._state
        book = self._shadow.latest(decision.asset_id)
        return {
            "spot_now": s.last_spot,
            "window_open_spot": s.window_open_spot,
            "oracle_last": s.last_oracle,
            "open_oracle": s.open_oracle,
            "best_bid": book.best_bid if book is not None else None,
            "best_ask": book.best_ask if book is not None else None,
            "ask_size_top": book.ask_size_top if book is not None else None,
        }


@dataclass
class _SettleSnapshot:
    """Frozen view of the closing window's state, captured at boundary
    crossing and read by the fire-and-forget background settle task. The
    snapshot is the only state the settle path touches, so settle is
    decoupled from any future mutation of the live `_RunState`."""

    window_ts: int
    decision_id: str
    open_oracle: float | None
    close_oracle: float | None
    side: Side | None
    settled_fill: Fill | None


@dataclass(slots=True)
class BankrollTracker:
    """Tracks live bankroll for compounding-aware strategies (v2.1+).

    Starting bankroll is set at construction time (locked decision #10
    default = $1000). Realized P&L accumulates on every settled record
    via ``apply_settle`` and is overlaid by Phase 15.5
    ``settled_correction`` records via ``apply_correction``. The single
    public read is ``current()`` — the strategy's ``bankroll_getter``
    callback invokes this at every fire.

    Thread-safety note: PaperRunner runs a single asyncio event loop;
    apply_settle / apply_correction are called from awaited background
    tasks but never concurrently with the main strategy fire path (the
    settle path is awaited at shutdown, and Kelly bet sizing happens on
    the main loop). No locking required.
    """

    starting_usd: float = 1000.0
    realized_pnl_usd: float = 0.0

    def current(self) -> float:
        return self.starting_usd + self.realized_pnl_usd

    def apply_settle(self, pnl_usd: float) -> None:
        self.realized_pnl_usd += pnl_usd

    def apply_correction(self, *, original_pnl_usd: float, corrected_pnl_usd: float) -> None:
        # The original `settled` record already contributed
        # ``original_pnl_usd`` to ``realized_pnl_usd``. The correction
        # overlay replaces the per-decision pnl with ``corrected_pnl_usd``
        # so the delta we apply is the difference. Phantom-fill
        # neutralization (corrected_pnl_usd == 0.0) lands correctly:
        # the delta becomes -original_pnl_usd.
        self.realized_pnl_usd += corrected_pnl_usd - original_pnl_usd


def replay_bankroll_from_log(
    *,
    log_root: Path,
    starting_usd: float = 1000.0,
    today: date | None = None,
    lookback_days: int = 14,
) -> BankrollTracker:
    """Walk recent decision-log JSONL files; replay settled + settled_correction
    records into a fresh ``BankrollTracker``.

    Mirrors the orphan-fire-recovery pattern in PaperRunner (read
    state/decisions/<UTC-date>.jsonl, look back N days). Recovers
    cross-restart bankroll without depending on the dashboard's
    derivation. Records are walked oldest → newest so the correction
    overlay applies after its parent settled record in time order.

    ``today`` defaults to UTC today; tests pin it to a deterministic
    date. ``lookback_days`` defaults to 14 (covers a typical operator
    redeploy gap + a margin for offline soaks).
    """
    tracker = BankrollTracker(starting_usd=starting_usd)
    root = Path(log_root)
    if not root.exists():
        return tracker
    base_date = today if today is not None else datetime.now(tz=UTC).date()
    dates = [base_date - timedelta(days=i) for i in range(lookback_days + 1)]
    for d in sorted(dates):  # ascending — proper time order
        path = root / f"{d.strftime('%Y-%m-%d')}.jsonl"
        if not path.exists():
            continue
        for rec in read_jsonl(path):
            kind = rec.get("kind")
            if kind == "settled":
                pnl = rec.get("pnl_usd")
                if isinstance(pnl, int | float):
                    tracker.apply_settle(float(pnl))
            elif kind == "settled_correction":
                orig = rec.get("original_pnl_usd")
                corr = rec.get("corrected_pnl_usd")
                if isinstance(orig, int | float) and isinstance(corr, int | float):
                    tracker.apply_correction(
                        original_pnl_usd=float(orig),
                        corrected_pnl_usd=float(corr),
                    )
    return tracker


@dataclass(slots=True)
class _PendingDecision:
    """One fired decision per window; v2.1 may have up to ``multi_fire_cap``.

    Each ``_PendingDecision`` carries its own decision_id, side, and
    settled_fill — they do NOT share state. ``settled_fill is None``
    means we're still awaiting a maker fill on this decision's limit;
    once a fill arrives (taker at fire time OR maker later) ``settled_fill``
    is populated and the window-close settle path computes pnl against
    it. Multi-fire counter lives on ``_RunState``, keyed by ``window_ts``
    so per-side state pollution (see project_per_side_state_pollution_pattern)
    can't corrupt it.
    """

    decision: Decision
    decision_id: str
    side: Side
    settled_fill: Fill | None = None


@dataclass
class _RunState:
    """Per-window scratch state for the runner. Not part of the public API.

    H.2.3 multi-fire refactor: ``pending_decision`` (singular) became
    ``pending_decisions: list[_PendingDecision]`` to admit v2.1's
    multi-fire pattern (up to ``multi_fire_cap`` decisions per window).
    Backward-compat properties (``pending_decision``, ``decision_id``,
    ``side``, ``settled_fill``) preserve READ access for existing call
    sites — for cap=1 they return the first/only entry in the list.
    """

    window_ts: int | None = None
    open_oracle: float | None = None
    close_oracle: float | None = None
    last_oracle: float | None = None
    last_spot: float | None = None
    window_open_spot: float | None = None
    pending_decisions: list[_PendingDecision] = field(default_factory=list)
    multi_fire_cap: int = 1

    @property
    def pending_decision(self) -> Decision | None:
        """Backward-compat: first pending decision still awaiting maker
        fill, or None. Tests and probes that read this continue to work
        unchanged — for cap=1 (v1/v2/v3 default) the list has at most
        one entry; for cap>=2 (v2.1) the first un-filled wins."""
        for pd in self.pending_decisions:
            if pd.settled_fill is None:
                return pd.decision
        return None

    @property
    def decision_id(self) -> str | None:
        """Backward-compat: first pending decision_id (or None)."""
        return self.pending_decisions[0].decision_id if self.pending_decisions else None

    @property
    def side(self) -> Side | None:
        """Backward-compat: first pending decision's side (or None)."""
        return self.pending_decisions[0].side if self.pending_decisions else None

    @property
    def settled_fill(self) -> Fill | None:
        """Backward-compat: the first pending decision's fill (or None).

        For cap=1, equivalent to the pre-refactor singular field — the
        sole pending decision's fill, or None if not yet filled. For
        cap>=2 it returns the FIRST decision's fill specifically (not
        "any filled decision") so cap-1 callers see consistent
        semantics.
        """
        return self.pending_decisions[0].settled_fill if self.pending_decisions else None

    def start_window(self, window_ts: int) -> None:
        # Carry last_oracle / last_spot forward as the open values; clear
        # decision state.
        self.window_ts = window_ts
        self.open_oracle = self.last_oracle
        self.close_oracle = None
        self.window_open_spot = self.last_spot
        self.pending_decisions.clear()

    def observe_oracle(self, event: OracleUpdate) -> None:
        self.last_oracle = event.price
        self.close_oracle = event.price
        if self.window_ts is not None and self.open_oracle is None:
            self.open_oracle = event.price

    def observe_book(self, event: BookUpdate) -> None:
        # Books don't carry prices we use for resolution; tracked here only
        # so future logic can latch top-of-book at window-open if needed.
        return

    def observe_spot(self, event: SpotTick) -> None:
        self.last_spot = event.price
        if self.window_open_spot is None and self.window_ts is not None:
            self.window_open_spot = event.price

    def record_decision(
        self,
        decision: Decision,
        side: Side,
        decision_id: str,
        immediate_fill: Fill | None,
    ) -> None:
        # Append a new pending decision. If the taker leg filled
        # immediately, settled_fill carries that fill (the window-close
        # settle path treats it as already-filled); otherwise None means
        # we wait for a maker fill on subsequent BookUpdates within ttl.
        self.pending_decisions.append(
            _PendingDecision(
                decision=decision,
                decision_id=decision_id,
                side=side,
                settled_fill=immediate_fill,
            )
        )


def _side_from_rationale(rationale: str) -> Side | None:
    if "side=UP" in rationale:
        return "UP"
    if "side=DOWN" in rationale:
        return "DOWN"
    return None


def _composite_from_rationale(rationale: str) -> float | None:
    """Parse the leading 'composite=<float>pct' marker emitted by DeterministicStrategy."""
    marker = "composite="
    idx = rationale.find(marker)
    if idx < 0:
        return None
    tail = rationale[idx + len(marker) :]
    end = 0
    while end < len(tail) and (tail[end].isdigit() or tail[end] in "+-.eE"):
        end += 1
    if end == 0:
        return None
    try:
        return float(tail[:end])
    except ValueError:
        return None


def _fill_from_dict(d: object) -> Fill | None:
    """Reconstruct a `Fill` from a JSON-decoded fired-record `fill` dict.

    Used by orphan-fire recovery, which reads the historical fired record
    off disk; the fired schema persists fills as plain dicts via
    `_fill_to_dict`. Returns None if the dict is None or malformed (a
    malformed fill in a fired record means we can't compute pnl, so the
    recovered settle records pnl=0 with fill_at_settle=None).
    """
    if not isinstance(d, dict):
        return None
    try:
        return Fill(
            ts_utc_ns=int(d["ts_utc_ns"]),
            asset_id=str(d["asset_id"]),
            size_filled=float(d["size_filled"]),
            price_filled=float(d["price_filled"]),
            fee_usd=float(d["fee_usd"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _realised_pnl(fill: Fill, won: bool) -> float:
    """Mirrors backtest.fills.realised_pnl_usd. Inlined so paper has no
    backwards reach into backtest internals beyond decode_record + types."""
    cost = fill.size_filled * fill.price_filled
    payout = fill.size_filled if won else 0.0
    return payout - cost - fill.fee_usd
