"""DashboardState composition — assembles the unified JSON snapshot.

Single source of truth read by both the /api/state (REST snapshot)
and /api/live (WS push) endpoints. Pure read over state/* + the
in-memory upstream cache; no Streamlit imports, no UI strings.
Per design/dashboard-v3.md §4.2.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from polymarket_bot.dashboard.bankroll import DEFAULT_STARTING_USD, load_bankroll
from polymarket_bot.dashboard.loaders import (
    DecisionRow,
    HealthSnapshot,
    ProcessStatus,
    aggregate_pnl,
    apply_settled_corrections,
    compute_scenarios,
    fire_rate_per_hour,
    latest_active_mode,
    load_decisions,
    load_feeds_health,
    load_process_status,
    per_tier_stats,
)
from polymarket_bot.dashboard.pipeline_latency import (
    PipelineLatencies,
    derive_pipeline_latencies,
)
from polymarket_bot.dashboard.profit_pace import profit_pace_per_hour
from polymarket_bot.dashboard.rtt_loader import load_provider_rtt
from polymarket_bot.dashboard.streaks import compute_streak

DECISIONS_SUBDIR = "decisions"
RESOLVED_DECISIONS_SUBDIR = "decisions-resolved"
WINDOW_DURATION_S: int = 300
# Surface "decisions stale" as an incident when the most recent fired
# decision is older than this AND the bot process is still alive — that
# combination is the orphan-FD-decisions failure mode (the bot is firing
# but its writes are landing on an unlinked inode while the dashboard
# reads a frozen visible file). Per runbooks/incidents/2026-05-09-
# orphan-fd-decisions.md. The threshold is generous enough that a
# legitimate quiet 15-min stretch (no fires) does NOT trip it for the
# typical aggressive-mode fire rate (~3-4/h).
# Decisions-stale wire threshold. The original 30 min was tuned for v1+
# aggressive which fired ~12/day (~2h gap baseline → 30min = 4x expected,
# legitimate "something's stuck" signal). v2 + ev_min=0.05 fires ~1/day,
# so the same 4x-expected-gap heuristic gives 96h — too lax. Compromise:
# 6h. Catches "bot stuck for half a day" without strobing the banner
# every time the bot is just being patient. Operator audit 2026-05-10:
# saw the alert fire at 1h-since-last-fire under v2-tight, which is
# entirely normal v2 behavior — not actionable.
DECISIONS_STALE_THRESHOLD_S: float = 6 * 60 * 60.0


@dataclass(slots=True)
class UpstreamCache:
    """In-memory snapshot of live upstream WS data — populated by
    upstream.py, read by snapshot()."""

    btc_candles: list[dict[str, float]] = field(default_factory=list)
    btc_last_price: float | None = None
    btc_change_pct: float | None = None
    spot_book_asks: list[tuple[float, float]] = field(default_factory=list)
    spot_book_bids: list[tuple[float, float]] = field(default_factory=list)
    spot_book_mid: float | None = None
    spot_book_ts_ns: int = 0
    ctf_window_ts: int | None = None
    ctf_side: Literal["UP", "DOWN"] | None = None
    ctf_slug: str | None = None
    ctf_asks: list[tuple[float, float]] = field(default_factory=list)
    ctf_bids: list[tuple[float, float]] = field(default_factory=list)
    ctf_mid: float | None = None
    ctf_ts_ns: int = 0


def _humanize_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds / 60)}m"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _decision_to_tape_row(r: DecisionRow) -> dict[str, Any]:
    won: bool | None
    if r.resolution is None or r.fill_price is None:
        won = None
    else:
        won = r.resolution == r.side
    return {
        "decision_id": r.decision_id,
        "window_ts": r.window_ts,
        "decision_dt_utc": r.decision_dt_utc.isoformat(),
        "side": r.side,
        "size_usd": r.size_usd,
        "price_limit": r.price_limit,
        "fill_price": r.fill_price,
        "ttl_s": r.ttl_s,
        "strategy": r.strategy,
        "mode": r.mode,
        "delta_bps": r.delta_bps,
        "p_win": r.p_win,
        "ev_dollars": r.ev_dollars,
        "resolution": r.resolution,
        "pnl_usd": r.pnl_usd,
        "won": won,
        "tier": _tier_for_price(r.price_limit),
        "fire_n": r.fire_n,
        "fire_total": r.fire_total,
    }


def _tier_for_price(p: float) -> str:
    if p < 0.15:
        return "<15%"
    if p < 0.30:
        return "15-30%"
    if p < 0.50:
        return "30-50%"
    if p < 0.70:
        return "50-70%"
    if p < 0.85:
        return "70-85%"
    return "85-100%"


def _trip_wires(rows: list[DecisionRow]) -> list[dict[str, Any]]:
    aggressive = [r for r in rows if r.mode == "aggressive"]
    if not aggressive:
        return []

    cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
    rows_24h = [r for r in aggressive if r.decision_dt_utc >= cutoff]
    pnl_24h = sum((r.pnl_usd or 0.0) for r in rows_24h)

    rate_24h, fires_24h = fire_rate_per_hour(aggressive, lookback_hours=24.0)
    fires_per_day = rate_24h * 24

    settled = [r for r in aggressive if r.resolution is not None and r.fill_price is not None]
    won = [r for r in settled if r.resolution == r.side]
    wr = (len(won) / len(settled)) if settled else None

    earliest = min(r.decision_dt_utc for r in aggressive)
    elapsed_h = (datetime.now(tz=UTC) - earliest).total_seconds() / 3600

    return [
        {
            "name": "PnL (24h)",
            "current_str": f"${pnl_24h:+.2f}",
            "current": pnl_24h,
            "threshold_str": "≥ -$50.00",
            "breach": pnl_24h < -50.0,
            "progress_pct": min(100, max(0, (pnl_24h + 100) / 1.5)),
        },
        {
            "name": "Fire rate (24h)",
            "current_str": f"{fires_24h} · {fires_per_day:.0f}/d",
            "current": fires_per_day,
            "threshold_str": "≤ 350/d",
            "breach": fires_per_day > 350,
            "progress_pct": min(100, fires_per_day / 350 * 100),
        },
        {
            "name": "Net win-rate",
            "current_str": f"{(wr * 100):.1f}%" if wr is not None else "—",
            "current": (wr * 100) if wr is not None else None,
            "threshold_str": "≥ 47% (n≥100)",
            "breach": wr is not None and len(settled) >= 100 and wr < 0.47,
            "progress_pct": (wr * 100) if wr is not None else 0,
        },
        {
            "name": "Elapsed",
            "current_str": f"{elapsed_h:.1f}h",
            "current": elapsed_h,
            "threshold_str": "review at 48h",
            "breach": elapsed_h >= 48,
            "progress_pct": min(100, elapsed_h / 48 * 100),
        },
    ]


def _cumulative_pnl_series(
    rows: list[DecisionRow], *, max_points: int = 500
) -> list[dict[str, float | int]]:
    """Build the running PnL curve plotted on the dashboard.

    One point per settled decision, sorted ascending by decision time.
    Each point carries the wall-clock UTC second at which the decision
    fired and the running sum of pnl_usd up to and including that point.
    The curve starts at the first settled decision's PnL value (NOT
    forced to zero) so the chart's vertical scale matches WalletPanel's
    cumulative number — operator can read absolute dollars off the
    y-axis without mental arithmetic.

    Capped at the most recent ``max_points`` for payload sanity. The
    bot fires ~150-300 decisions/day, so 500 points covers ~2 days at
    aggressive cadence; deeper history can be backfilled by extending
    the lookback if the operator asks.
    """
    series: list[dict[str, float | int]] = []
    running = 0.0
    for r in rows:
        if r.resolution is None or r.pnl_usd is None:
            continue
        running += r.pnl_usd
        series.append({"ts": int(r.decision_dt_utc.timestamp()), "pnl": running})
    if len(series) > max_points:
        series = series[-max_points:]
    return series


def _today_pnl(rows: list[DecisionRow]) -> tuple[float | None, int]:
    today = datetime.now(tz=UTC).date()
    settled_today = [
        r
        for r in rows
        if r.resolution is not None and r.pnl_usd is not None and r.decision_dt_utc.date() == today
    ]
    if not settled_today:
        return (None, 0)
    return (sum(r.pnl_usd or 0.0 for r in settled_today), len(settled_today))


def _pnl_by_day(rows: list[DecisionRow], *, n_days: int = 7) -> list[dict[str, Any]]:
    """Per-UTC-day PnL bucket — supports the operator-asked "yesterday vs
    today" view, which the LivePnlPanel "TODAY" deliberately doesn't show
    (resets at 00:00 UTC). Returns the most recent ``n_days`` buckets,
    newest first. Each bucket: date string ("YYYY-MM-DD"), pnl_usd,
    n_settled. Days with zero settled decisions are still included so the
    operator sees explicit zeros rather than missing rows."""
    from collections import defaultdict

    today = datetime.now(tz=UTC).date()
    buckets_pnl: dict[str, float] = defaultdict(float)
    buckets_n: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.resolution is None or r.pnl_usd is None:
            continue
        key = r.decision_dt_utc.date().isoformat()
        buckets_pnl[key] += r.pnl_usd
        buckets_n[key] += 1

    out: list[dict[str, Any]] = []
    for offset in range(n_days):
        d = today - timedelta(days=offset)
        key = d.isoformat()
        out.append(
            {
                "date": key,
                "pnl_usd": buckets_pnl.get(key, 0.0),
                "n_settled": buckets_n.get(key, 0),
            }
        )
    return out


def _best_tier_pnl(rows: list[DecisionRow]) -> tuple[str | None, float | None]:
    stats = per_tier_stats(rows)
    if not stats:
        return (None, None)
    best = max(stats, key=lambda s: s.pnl_usd)
    return (best.tier, best.pnl_usd)


def _disagreement_rate(rows: list[DecisionRow]) -> dict[str, Any]:
    """% of settled decisions where the (Polymarket-corrected) resolution
    disagrees with the original Chainlink-side resolution_oracle_local
    (loaded via the JSONL extra fields, but DecisionRow doesn't track
    them today). For now, return the count of resolutions present and a
    placeholder. v3.1 adds the field to DecisionRow."""
    settled = [r for r in rows if r.resolution is not None]
    return {
        "n_resolved": len(settled),
        "rate": None,  # filled in once DecisionRow exposes resolution_oracle_local
        "last_disagree_window_ts": None,
    }


def _humanize_mode(mode: str | None) -> tuple[str, str]:
    if mode == "aggressive":
        return ("AGGRESSIVE", "warn")
    if mode == "spot_aware":
        return ("SPOT_AWARE", "good")
    if mode == "deterministic":
        return ("DETERMINISTIC", "muted")
    return ("WAITING", "muted")


def snapshot(
    state_dir: Path | str,
    *,
    upstream: UpstreamCache | None = None,
    decisions_lookback_days: int = 14,
    n_decisions_in_tape: int = 100,
) -> dict[str, Any]:
    """Compose the unified DashboardState JSON. Pure function over
    state_dir + upstream cache; no module-level state."""
    state_dir = Path(state_dir)
    upstream = upstream or UpstreamCache()
    now = datetime.now(tz=UTC)

    capture, paper = load_process_status(state_dir)
    snap: HealthSnapshot | None = load_feeds_health(state_dir)
    since = (now - timedelta(days=decisions_lookback_days)).strftime("%Y-%m-%d")
    # Prefer the Polymarket-truth resolved dir (written by the dashboard
    # server's resolver_loop) over the bot's raw oracle-truth decisions.
    # Fallback to raw if the resolved dir is missing or empty so the
    # dashboard renders SOMETHING during the brief warm-up after restart
    # or if the resolver loop is disabled. truth_source is surfaced on
    # the snapshot so the operator-facing panel can label the PnL.
    resolved_dir = state_dir / RESOLVED_DECISIONS_SUBDIR
    rows = load_decisions(resolved_dir, since_utc_date=since)
    if rows:
        truth_source = "polymarket"
    else:
        rows = load_decisions(state_dir / DECISIONS_SUBDIR, since_utc_date=since)
        truth_source = "oracle" if rows else "unknown"

    # Phase 15.5: ALSO honor `settled_correction` records the bot writes to
    # its raw log (state/decisions/) — these neutralize phantom fills and
    # back-correct chainlink/polymarket-mismatch resolutions that
    # resolver_loop's gamma re-resolve doesn't see. Idempotent + cheap.
    rows = apply_settled_corrections(rows, state_dir / DECISIONS_SUBDIR, since_utc_date=since)

    # Phase O Session 1 (2026-05-17): honor the bot's PMB_STARTING_BANKROLL +
    # BANKROLL_REPLAY_ENABLED env vars so the dashboard hero bankroll matches
    # what the runtime Kelly sizer reads at fire time. Defaults preserve the
    # historical $1k locked-decision-#10 behavior + replay-on semantics for
    # operators who haven't set the env vars.
    starting_env = os.environ.get("PMB_STARTING_BANKROLL", "").strip()
    try:
        starting_usd = float(starting_env) if starting_env else DEFAULT_STARTING_USD
    except ValueError:
        starting_usd = DEFAULT_STARTING_USD
    replay_env = os.environ.get("BANKROLL_REPLAY_ENABLED", "").strip().lower()
    replay_enabled = replay_env not in ("0", "false", "no", "off")
    bankroll = load_bankroll(rows, starting_usd=starting_usd, replay_enabled=replay_enabled)
    # Phase 16: project realised PnL onto alternative starting bankrolls.
    # Display-only — locked decision #10 ($1k paper) is unchanged. Stake is
    # fixed (locked decision #9) so the absolute PnL is the same across all
    # scenarios, only the starting balance differs.
    scenarios = compute_scenarios(rows)
    agg = aggregate_pnl(rows)
    streak = compute_streak(rows)
    pace_per_hour, pace_n = profit_pace_per_hour(rows, window_s=3600.0)
    today_pnl_val, today_n = _today_pnl(rows)
    best_tier_label, best_tier_pnl = _best_tier_pnl(rows)
    rate_per_hour, fires_24h = fire_rate_per_hour(rows, lookback_hours=24.0)

    mode_active = latest_active_mode(rows)
    mode_label, mode_tone = _humanize_mode(mode_active)

    latencies: PipelineLatencies = derive_pipeline_latencies(rows, snap)

    tier_stats = per_tier_stats(rows)
    rtt_samples = load_provider_rtt(state_dir)
    rtt_panel = []
    last_rtt_age_s: float | None = None
    for name, samples in rtt_samples.items():
        if samples:
            last = samples[-1]
            age_s = (now - last.ts_utc).total_seconds()
            if last_rtt_age_s is None or age_s < last_rtt_age_s:
                last_rtt_age_s = age_s
            rtt_panel.append(
                {
                    "name": name,
                    "samples": [s.rtt_ms for s in samples],
                    "last_ms": last.rtt_ms,
                    "last_age_s": age_s,
                }
            )
    halt_requested = (state_dir / "halt.sentinel").exists()

    # Incident detection. Only the actual outages go in the banner —
    # if the bot is alive, missing telemetry files are surfaced by the
    # individual panels (CAPTURE 0/0 in the pipeline, "—" in the feeds
    # column) rather than as a screaming top-of-page banner. Per
    # operator critique 2026-05-09 — the v2.1 incident banner was
    # crying about feeds_health.json missing on the VPS even though
    # the bot was clearly alive; the v3 banner only fires for the
    # things that actually need operator action.
    incidents: list[str] = []
    if paper.pid is not None and not paper.alive:
        incidents.append(f"paper process dead (pid {paper.pid})")
    elif not paper.alive:
        incidents.append("paper process not running")
    if capture.pid is not None and not capture.alive:
        incidents.append(f"capture process dead (pid {capture.pid})")
    # Decisions-quiet wire. Fires only when the bot has been silent for
    # significantly longer than its expected fire cadence — at the 6h
    # threshold this could be: (a) the strategy is genuinely quiet (no
    # edge — fine for v2-tight), (b) a journal/strategy bug, OR (c) the
    # historical orphan-FD failure mode where the bot writes into an
    # unlinked inode. The message lists possibilities rather than
    # prejudging — operator audit 2026-05-10 noted the prior "check for
    # orphan FDs" message confused triage when most quiet periods are
    # just v2 being patient.
    if paper.alive and rows:
        last_fire = max(r.decision_dt_utc for r in rows)
        gap_s = (now - last_fire).total_seconds()
        if gap_s > DECISIONS_STALE_THRESHOLD_S:
            incidents.append(
                f"no fires in {_humanize_age(gap_s)} while bot alive — "
                "v2-quiet or stuck? check journal/lsof for orphan FDs"
            )
    if snap is None and paper.alive:
        # Bot is alive but no feeds_health.json — soft warning, not
        # incident-worthy. (The bot's _live.health aggregator may not
        # be running, which is a degraded but non-critical state.)
        pass
    elif snap is None:
        incidents.append("feeds_health.json missing")
    elif snap is not None:
        for f in snap.feeds:
            if not f.healthy:
                incidents.append(f"{f.name} feed unhealthy")
        age_s = (now - snap.snapshot_mtime_utc).total_seconds()
        if age_s > 300:
            incidents.append(f"feeds_health snapshot stale ({_humanize_age(age_s)})")

    return {
        "schema_version": 1,
        "now_utc_iso": now.isoformat(),
        "now_utc_ns": int(now.timestamp() * 1_000_000_000),
        "decisions_truth_source": truth_source,
        "mode": {
            "label": mode_label,
            "tone": mode_tone,
            "raw": mode_active,
        },
        "bankroll": {
            "starting_usd": bankroll.starting_usd,
            "current_usd": bankroll.current_usd,
            "delta_usd": bankroll.delta_usd,
            "delta_pct": bankroll.delta_pct,
        },
        "scenarios": [
            {
                "start_bankroll_usd": s.start_bankroll_usd,
                "end_bankroll_usd": s.end_bankroll_usd,
                "realized_pnl_usd": s.realized_pnl_usd,
                "n_settled": s.n_settled,
                "fixed_stake_usd": s.fixed_stake_usd,
                "is_bankrupt": s.is_bankrupt,
            }
            for s in scenarios
        ],
        "agg": {
            "n_fired": agg["n_fired"],
            "n_filled": agg["n_filled"],
            "n_settled": agg["n_settled"],
            "n_won": agg["n_won"],
            "win_rate": agg["win_rate"],
            "avg_pnl_per_filled": agg["avg_pnl_per_filled"],
            "total_pnl_usd": agg["total_pnl_usd"],
        },
        "streak": {
            "glyph": streak.current_glyph,
            "n": streak.current_n,
            "best_win": streak.best_win_streak,
            "worst_loss": streak.worst_loss_streak,
        },
        "pace": {
            "usd_per_hour": pace_per_hour,
            "n_settled_60m": pace_n,
        },
        "today": {
            "pnl_usd": today_pnl_val,
            "n_settled": today_n,
        },
        "pnl_by_day": _pnl_by_day(rows),
        "fire_rate": {
            "per_hour": rate_per_hour,
            "fires_24h": fires_24h,
            "projected_per_day": int(rate_per_hour * 24),
        },
        "pipeline": {
            "capture_ms": latencies.capture_ms,
            "strategy_ms": latencies.strategy_ms,
            "sim_fill_ms": latencies.sim_fill_ms,
            "settle_wait_s": latencies.settle_wait_s,
            "resolve_ms": latencies.resolve_ms,
            "persist_ms": latencies.persist_ms,
        },
        "feeds": (
            [
                {
                    "name": f.name,
                    "msgs_seen": f.msgs_seen,
                    "healthy": f.healthy,
                    "reconnects": f.reconnects,
                    "last_error": f.last_error,
                    "last_seen_ns": f.last_seen_ns,
                }
                for f in snap.feeds
            ]
            if snap is not None
            else []
        ),
        "feeds_snapshot_age_s": (
            (now - snap.snapshot_mtime_utc).total_seconds() if snap is not None else None
        ),
        "processes": {
            "capture": {
                "name": capture.name,
                "pid": capture.pid,
                "alive": capture.alive,
                "create_time_utc": (
                    capture.create_time_utc.isoformat() if capture.create_time_utc else None
                ),
            },
            "paper": {
                "name": paper.name,
                "pid": paper.pid,
                "alive": paper.alive,
                "create_time_utc": (
                    paper.create_time_utc.isoformat() if paper.create_time_utc else None
                ),
            },
        },
        "provider_rtt": {
            "providers": rtt_panel,
            "last_sample_age_s": last_rtt_age_s,
        },
        "tier_breakdown": [
            {
                "tier": s.tier,
                "n_fired": s.n_fired,
                "n_filled": s.n_filled,
                "n_settled": s.n_settled,
                "n_won": s.n_won,
                "win_rate": s.win_rate,
                "pnl_usd": s.pnl_usd,
            }
            for s in tier_stats
        ],
        "best_tier": {"label": best_tier_label, "pnl_usd": best_tier_pnl},
        "cumulative_pnl_series": _cumulative_pnl_series(rows),
        "trip_wires": _trip_wires(rows),
        "halt_requested": halt_requested,
        "incidents": incidents,
        "decisions": [_decision_to_tape_row(r) for r in reversed(rows[-n_decisions_in_tape:])],
        "n_decisions_total": len(rows),
        "chart": {
            "candles": upstream.btc_candles,
            "last_price": upstream.btc_last_price,
            "change_pct": upstream.btc_change_pct,
        },
        "spot_book": {
            "asks": [{"p": p, "s": s} for p, s in upstream.spot_book_asks],
            "bids": [{"p": p, "s": s} for p, s in upstream.spot_book_bids],
            "mid": upstream.spot_book_mid,
            "ts_ns": upstream.spot_book_ts_ns,
        },
        "ctf_book": {
            "window_ts": upstream.ctf_window_ts,
            "side": upstream.ctf_side,
            "slug": upstream.ctf_slug,
            "asks": [{"p": p, "s": s} for p, s in upstream.ctf_asks],
            "bids": [{"p": p, "s": s} for p, s in upstream.ctf_bids],
            "mid": upstream.ctf_mid,
            "ts_ns": upstream.ctf_ts_ns,
        },
        "disagreement": _disagreement_rate(rows),
    }


def _process_to_dict(p: ProcessStatus) -> dict[str, Any]:
    return {
        "name": p.name,
        "pid": p.pid,
        "alive": p.alive,
        "create_time_utc": p.create_time_utc.isoformat() if p.create_time_utc else None,
    }
