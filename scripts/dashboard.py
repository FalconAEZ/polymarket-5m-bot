"""Single-page Streamlit dashboard — operations observability.

Run with: `uv run streamlit run scripts/dashboard.py`. Binds to
127.0.0.1:8501 per .streamlit/config.toml. Reads state/decisions/*.jsonl
+ state/feeds_health.json + paper.log + capture.log. Auto-refreshes
every N seconds (sidebar control).

Two layouts:
  - PMB_DASH_V2=0 (default): v1 layout per design/dashboard.md §4.3
  - PMB_DASH_V2=1: v2 Bloomberg-terminal layout per design/dashboard-v2.md §5

Both share state loaders + theme tokens; v2 adds the hero pixel-display
PnL, live tape, pipeline strip, orderbook panels, and provider RTT.
"""

from __future__ import annotations

import html
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from streamlit_autorefresh import st_autorefresh  # noqa: E402

from polymarket_bot.dashboard.agents_loader import load_transcript  # noqa: E402
from polymarket_bot.dashboard.bankroll import load_bankroll  # noqa: E402
from polymarket_bot.dashboard.components import (  # noqa: E402
    bankroll_chip,
    cycle_meta_chip,
    live_pnl_panel,
    live_tape,
    market_tabs,
    orderbook_from_ctf,
    pipeline_stages_from_state,
    pipeline_strip,
    provider_rtt_panel,
    tape_events_from_decisions,
    tradingview_chart,
    wallet_panel,
)
from polymarket_bot.dashboard.loaders import (  # noqa: E402
    DecisionRow,
    HealthSnapshot,
    ProcessStatus,
    aggregate_pnl,
    fire_rate_per_hour,
    latest_active_mode,
    load_decisions,
    load_feeds_health,
    load_process_status,
    per_tier_stats,
    tail_log,
)
from polymarket_bot.dashboard.pipeline_latency import derive_pipeline_latencies  # noqa: E402
from polymarket_bot.dashboard.polymarket_orderbook import fetch_ctf_orderbook  # noqa: E402
from polymarket_bot.dashboard.profit_pace import profit_pace_per_hour  # noqa: E402
from polymarket_bot.dashboard.rtt_loader import load_provider_rtt  # noqa: E402
from polymarket_bot.dashboard.streaks import compute_streak  # noqa: E402
from polymarket_bot.dashboard.theme import (  # noqa: E402
    badge,
    incident_banner,
    inject,
    kpi_card,
)


def _resolve_default_state_dir() -> Path:
    env = os.environ.get("PMB_DASH_STATE_DIR")
    if env:
        return Path(env)
    demo = ROOT / "state-demo"
    if (demo / "feeds_health.json").exists():
        return demo
    return ROOT / "state"


DEFAULT_STATE_DIR = _resolve_default_state_dir()
DASH_V2 = os.environ.get("PMB_DASH_V2", "0") == "1"
PAPER_LOG = "paper.log"
CAPTURE_LOG = "capture.log"
DECISIONS_SUBDIR = "decisions"
PHASE_3_AB_PATH = ROOT / "runbooks" / "gate-evidence" / "phase-3.3-llm-ab.txt"
PHASE_3_VERDICT_PATH = ROOT / "runbooks" / "decisions" / "llm-ab-result.md"
SYNC_SCRIPT = ROOT / "runbooks" / "scripts" / "sync_staging.sh"
SYNC_MIN_INTERVAL_S = 30.0


# ============================================================================
# Shared formatting helpers (used by both v1 and v2)
# ============================================================================


def _fmt_currency(value: float | None, *, decimals: int = 2) -> str:
    if value is None:
        return "—"
    sign = "+" if value > 0 else ("-" if value < 0 else " ")
    return f"{sign}${abs(value):,.{decimals}f}"


def _fmt_pct(value: float | None, *, decimals: int = 1) -> str:
    if value is None:
        return "—"
    return f"{value * 100:.{decimals}f}%"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def _humanize_age(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s ago"
    if seconds < 3600:
        return f"{int(seconds / 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds / 3600)}h ago"
    return f"{int(seconds / 86400)}d ago"


def _process_uptime(p: ProcessStatus) -> str:
    if not p.alive or p.create_time_utc is None:
        return "—"
    seconds = (datetime.now(tz=UTC) - p.create_time_utc).total_seconds()
    return _humanize_age(seconds)


def _level_class(line: str) -> str:
    if "Traceback" in line or " ERROR " in line or " ERROR:" in line:
        return "pmb-log__line--err"
    if " WARNING " in line or " WARN " in line:
        return "pmb-log__line--warn"
    return "pmb-log__line--info"


def _last_decision_label(rows: list[DecisionRow]) -> str:
    if not rows:
        return "—"
    most_recent = max(rows, key=lambda r: r.decision_dt_utc)
    age_s = (datetime.now(tz=UTC) - most_recent.decision_dt_utc).total_seconds()
    return _humanize_age(age_s)


def _detect_incidents(
    capture: ProcessStatus,
    paper: ProcessStatus,
    snap: HealthSnapshot | None,
    paper_log_path: Path,
) -> list[str]:
    issues: list[str] = []
    if paper.pid is not None and not paper.alive:
        issues.append(f"paper process dead (pid {paper.pid})")
    elif paper.pid is None:
        issues.append("paper process not running")
    if capture.pid is not None and not capture.alive:
        issues.append(f"capture process dead (pid {capture.pid})")
    if snap is None:
        issues.append("feeds_health.json missing")
    else:
        for f in snap.feeds:
            if not f.healthy:
                issues.append(f"{f.name} feed unhealthy")
        age_s = (datetime.now(tz=UTC) - snap.snapshot_mtime_utc).total_seconds()
        if age_s > 300:
            issues.append(f"feeds_health snapshot stale ({_humanize_age(age_s)})")
    recent = tail_log(paper_log_path, n_lines=200)
    if any("Traceback" in line for line in recent):
        issues.append("traceback in paper.log (last 200 lines)")
    return issues


_MODE_BADGE = {
    "aggressive": ("AGGRESSIVE MODE", "bad"),
    "spot_aware": ("SPOT_AWARE", "good"),
    "deterministic": ("DETERMINISTIC", "warn"),
}


def _maybe_auto_sync(state_dir: Path) -> float | None:
    sentinel = state_dir / "feeds_health.json"
    if not sentinel.exists():
        return None
    return (
        datetime.now(tz=UTC) - datetime.fromtimestamp(sentinel.stat().st_mtime, tz=UTC)
    ).total_seconds()


def _run_sync(state_dir: Path) -> bool:
    if not SYNC_SCRIPT.exists():
        return False
    sentinel = state_dir / "feeds_health.json"
    if sentinel.exists():
        age = (
            datetime.now(tz=UTC) - datetime.fromtimestamp(sentinel.stat().st_mtime, tz=UTC)
        ).total_seconds()
        if age < SYNC_MIN_INTERVAL_S:
            return False
    if sentinel.exists():
        try:
            sentinel.touch()
        except OSError:
            pass
    try:
        import subprocess

        subprocess.Popen(  # noqa: S603
            ["/bin/bash", str(SYNC_SCRIPT)],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except Exception:
        return False


def _log_age_label(mtime: float | None) -> str:
    if mtime is None:
        return "missing"
    age_s = (datetime.now(tz=UTC) - datetime.fromtimestamp(mtime, tz=UTC)).total_seconds()
    return _humanize_age(age_s)


# ============================================================================
# v1 panels (unchanged from prior implementation)
# ============================================================================


def _render_header_v1(
    refreshed_at: datetime,
    since_filter: str | None,
    *,
    rows: list[DecisionRow],
    last_sync_age_s: float | None,
) -> None:
    sub_parts = [f"refreshed {refreshed_at.strftime('%H:%M:%S')} UTC"]
    if since_filter:
        sub_parts.append(f"since {since_filter}")
    if last_sync_age_s is not None:
        sub_parts.append(f"vps sync: {_humanize_age(last_sync_age_s)}")
    else:
        sub_parts.append("vps sync: never")
    sub = " · ".join(sub_parts)

    mode = latest_active_mode(rows)
    if mode in _MODE_BADGE:
        label, tone = _MODE_BADGE[mode]
    elif mode is not None:
        label, tone = (mode.upper(), "warn")
    else:
        label, tone = ("WAITING", "warn")
    mode_badge = badge(label, tone=tone)

    sub_text = "Phase 11.A · spot_aware paper-soak"
    if mode == "aggressive":
        sub_text = "Phase 11.A.2 · aggressive_mode test (48h gate)"

    st.html(
        '<div class="pmb-header">'
        '<div class="pmb-header__left">'
        '<span class="pmb-live-dot" title="live"></span>'
        '<h1 class="pmb-header__title">Polymarket 5m BTC · Operations</h1>'
        f"{mode_badge}"
        f'<span class="pmb-header__sub">{html.escape(sub_text)}</span>'
        "</div>"
        f'<div class="pmb-header__sub">{html.escape(sub)}</div>'
        "</div>"
    )


def _render_kpi_row_v1(rows: list[DecisionRow], paper: ProcessStatus) -> None:
    agg = aggregate_pnl(rows)
    pnl = agg["total_pnl_usd"]
    win_rate = agg["win_rate"]
    n_settled = agg["n_settled"]
    n_won = agg["n_won"]
    n_fired = agg["n_fired"]
    avg_pnl = agg["avg_pnl_per_filled"]

    if isinstance(pnl, float) and pnl > 0:
        pnl_tone, pnl_glyph = "good", "▲"
    elif isinstance(pnl, float) and pnl < 0:
        pnl_tone, pnl_glyph = "bad", "▼"
    else:
        pnl_tone, pnl_glyph = "neutral", None

    if isinstance(win_rate, float):
        wr_tone = "good" if win_rate >= 0.55 else ("bad" if win_rate < 0.45 else "warn")
    else:
        wr_tone = "neutral"

    uptime_tone = "good" if paper.alive else "bad"
    uptime_value = _process_uptime(paper) if paper.alive else "OFFLINE"

    last_dec = _last_decision_label(rows)
    last_dec_tone = "neutral" if rows else "warn"
    rate_per_hour, fires_24h = fire_rate_per_hour(rows, lookback_hours=24.0)
    rate_label = f"{rate_per_hour:.1f}/hr"
    rate_subtitle = f"{fires_24h} in 24h · {int(rate_per_hour * 24)}/d projected"
    if rate_per_hour == 0:
        rate_tone: str = "warn"
    elif rate_per_hour > 14.5:
        rate_tone = "bad"
    else:
        rate_tone = "good"

    pnl_card = kpi_card(
        label="Cumulative PnL",
        value=_fmt_currency(pnl) if isinstance(pnl, float) else "—",
        subtitle=(
            f"avg {_fmt_currency(avg_pnl, decimals=3)} / trade"
            if isinstance(avg_pnl, float)
            else None
        ),
        tone=pnl_tone,
        glyph=pnl_glyph,
    )
    win_card = kpi_card(
        label="Win Rate",
        value=_fmt_pct(win_rate) if isinstance(win_rate, float) else "—",
        subtitle=(
            f"{n_won}/{n_settled} settled"
            if isinstance(n_won, int) and isinstance(n_settled, int)
            else None
        ),
        tone=wr_tone,
    )
    decisions_card = kpi_card(
        label="Decisions Fired",
        value=_fmt_int(n_fired) if isinstance(n_fired, int) else "—",
        subtitle=f"{agg['n_filled']} filled" if isinstance(agg["n_filled"], int) else None,
        tone="neutral",
    )
    rate_card = kpi_card(
        label="Fire Rate",
        value=rate_label,
        subtitle=rate_subtitle,
        tone=rate_tone,
    )
    last_card = kpi_card(
        label="Last Decision",
        value=last_dec,
        subtitle=(
            "no fires yet — bot is waiting for signal" if not rows else f"{n_fired} fired total"
        ),
        tone=last_dec_tone,
    )
    uptime_card = kpi_card(
        label="Paper Uptime",
        value=uptime_value,
        subtitle=f"PID {paper.pid}" if paper.pid is not None else "no PID file",
        tone=uptime_tone,
    )

    main_kpi_col, side_kpi_col, log_kpi_col = st.columns([0.55, 0.25, 0.20], gap="small")
    with main_kpi_col:
        a, b, c, d = st.columns(4, gap="small")
        with a:
            st.html(pnl_card)
        with b:
            st.html(win_card)
        with c:
            st.html(decisions_card)
        with d:
            st.html(rate_card)
    with side_kpi_col:
        st.html(last_card)
    with log_kpi_col:
        st.html(uptime_card)


def _section_header(title: str, badge_html: str = "") -> None:
    st.html(
        f'<div class="pmb-section"><div class="pmb-card__title">{title}{badge_html}</div></div>'
    )


def _render_pnl_chart_v1(rows: list[DecisionRow]) -> None:
    settled = [r for r in rows if r.pnl_usd is not None]
    _section_header("📈 Cumulative PnL")
    if not settled:
        st.html(
            '<div class="pmb-empty">'
            "No settled decisions yet. Settled records appear after the 5-min "
            "window closes and oracle resolution lands."
            "</div>"
        )
        return

    df = pd.DataFrame(
        {
            "decision_dt_utc": [r.decision_dt_utc for r in settled],
            "pnl_usd": [r.pnl_usd or 0.0 for r in settled],
            "side": [r.side for r in settled],
        }
    ).sort_values("decision_dt_utc")
    df["cumulative_pnl"] = df["pnl_usd"].cumsum()

    base = alt.Chart(df).encode(
        x=alt.X(
            "decision_dt_utc:T",
            title=None,
            axis=alt.Axis(
                format="%b %d %H:%M",
                labelColor="#9c8d6b",
                titleColor="#9c8d6b",
                grid=False,
                domain=False,
                tickColor="#2a261c",
                labelFontSize=10,
                labelFontWeight=500,
                labelPadding=6,
                tickCount=6,
            ),
        ),
        y=alt.Y(
            "cumulative_pnl:Q",
            title=None,
            axis=alt.Axis(
                labelColor="#9c8d6b",
                grid=True,
                gridColor="#2a261c",
                gridOpacity=0.5,
                domain=False,
                ticks=False,
                labelFontSize=10,
                labelPadding=6,
                format="$,.2f",
            ),
        ),
    )
    area = base.mark_area(
        line={"color": "#8aff7a", "strokeWidth": 2, "strokeJoin": "round", "strokeCap": "round"},
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color="rgba(138, 255, 122, 0.42)", offset=0),
                alt.GradientStop(color="rgba(138, 255, 122, 0.02)", offset=1),
            ],
            x1=1,
            x2=1,
            y1=1,
            y2=0,
        ),
        interpolate="monotone",
        clip=True,
    ).encode(
        tooltip=[
            alt.Tooltip("decision_dt_utc:T", title="When", format="%Y-%m-%d %H:%M:%S UTC"),
            alt.Tooltip("side:N", title="Side"),
            alt.Tooltip("pnl_usd:Q", title="Trade PnL", format="+$.4f"),
            alt.Tooltip("cumulative_pnl:Q", title="Cumulative", format="+$.4f"),
        ],
    )
    zero_rule = (
        alt.Chart(pd.DataFrame({"y": [0.0]}))
        .mark_rule(color="#3d3725", strokeWidth=1, strokeDash=[3, 3])
        .encode(y="y:Q")
    )
    chart = (
        (zero_rule + area)
        .properties(
            height=280,
            background="transparent",
            padding={"top": 6, "right": 8, "bottom": 4, "left": 4},
        )
        .configure_view(strokeWidth=0)
        .configure_axisX(grid=False)
    )
    st.altair_chart(chart, width="stretch")


def _render_processes_inline(capture: ProcessStatus, paper: ProcessStatus) -> None:
    rows_html: list[str] = []
    for p in (capture, paper):
        if p.alive:
            tone, label = "good", "ALIVE"
        elif p.pid is not None:
            tone, label = "bad", "DEAD"
        else:
            tone, label = "muted", "ABSENT"
        pid_str = f"pid {p.pid}" if p.pid is not None else "no pid file"
        uptime = _process_uptime(p)
        rows_html.append(
            f'<div class="pmb-proc-row">'
            f'<div><div class="pmb-proc-row__name">{html.escape(p.name)}</div>'
            f'<div class="pmb-proc-row__sub">{html.escape(pid_str)} · uptime {html.escape(uptime)}</div>'
            f"</div>{badge(label, tone=tone)}</div>"
        )
    st.html('<div class="pmb-card__title">⚙️ Processes</div>' f'{"".join(rows_html)}')


def _render_feeds_inline(snap: HealthSnapshot | None) -> None:
    if snap is None:
        st.html(
            '<div class="pmb-card__title" style="margin-top: 14px;">📡 Feeds Health</div>'
            '<div class="pmb-empty">No feeds_health.json found.</div>'
        )
        return
    age_s = (datetime.now(tz=UTC) - snap.snapshot_mtime_utc).total_seconds()
    age_tone = "good" if age_s < 60 else ("warn" if age_s < 300 else "bad")
    age_badge = badge(_humanize_age(age_s), tone=age_tone)
    feed_cards: list[str] = []
    for f in snap.feeds:
        tone = "good" if f.healthy else "bad"
        last_err = f.last_error[:80] if f.last_error else "no errors"
        feed_cards.append(
            f'<div class="pmb-feed">'
            f'<div class="pmb-feed__name">{html.escape(f.name)}'
            f'{badge("OK" if f.healthy else "BAD", tone=tone)}</div>'
            f'<div class="pmb-feed__stat"><strong>{f.msgs_seen:,}</strong> msgs</div>'
            f'<div class="pmb-feed__stat"><strong>{f.reconnects}</strong> reconnects</div>'
            f'<div class="pmb-feed__err">{html.escape(last_err)}</div>'
            f"</div>"
        )
    st.html(
        f'<div class="pmb-card__title" style="margin-top: 14px;">📡 Feeds Health{age_badge}</div>'
        f'<div class="pmb-feed-row">{"".join(feed_cards)}</div>'
    )


def _render_decisions_table_v1(rows: list[DecisionRow]) -> None:
    _section_header("📋 Decisions")
    if not rows:
        st.html(
            '<div class="pmb-empty">'
            "No decisions logged yet. Files at <code>state/decisions/&lt;UTC-date&gt;.jsonl</code> populate "
            "as the active strategy fires."
            "</div>"
        )
        return
    df = pd.DataFrame(
        [
            {
                "When (UTC)": r.decision_dt_utc.strftime("%H:%M:%S · %b %d"),
                "Market": r.window_ts,
                "Strategy": (r.strategy or "—"),
                "Side": ("🟢 UP" if r.side == "UP" else "🔴 DOWN"),
                "Asset": r.asset_id[:10] + "…" if len(r.asset_id) > 10 else r.asset_id,
                "Limit": r.price_limit,
                "Fill": r.fill_price if r.fill_price is not None else None,
                "Resolution": (
                    "✓ won"
                    if r.resolution is not None and r.resolution == r.side
                    else "✗ lost"
                    if r.resolution is not None
                    else "— pending"
                ),
                "PnL": r.pnl_usd if r.pnl_usd is not None else None,
                "Δ_bps": r.delta_bps,
                "p_win": r.p_win,
                "EV($)": r.ev_dollars,
                "Composite": r.composite_pct,
                "TTL": f"{r.ttl_s}s",
            }
            for r in reversed(rows)
        ]
    )
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "When (UTC)": st.column_config.TextColumn("When", width="small"),
            "Market": st.column_config.NumberColumn(
                "Market",
                help="5-min market window_ts (Unix seconds).",
                format="%d",
                width="small",
            ),
            "Side": st.column_config.TextColumn("Side", width="small"),
            "Asset": st.column_config.TextColumn("Asset", width="small"),
            "Limit": st.column_config.NumberColumn("Limit", format="$%.4f"),
            "Fill": st.column_config.NumberColumn("Fill", format="$%.4f"),
            "Resolution": st.column_config.TextColumn("Outcome", width="small"),
            "PnL": st.column_config.NumberColumn("PnL", format="$%+.4f"),
            "Composite": st.column_config.NumberColumn("Comp", format="%+.3f"),
            "TTL": st.column_config.TextColumn("TTL", width="small"),
        },
        height=min(220, 40 + len(rows) * 30),
    )


def _render_log_panel(state_dir: Path) -> None:
    paper_lines = tail_log(state_dir / PAPER_LOG, n_lines=60)
    capture_lines = tail_log(state_dir / CAPTURE_LOG, n_lines=60)
    paper_mtime = (
        (state_dir / PAPER_LOG).stat().st_mtime if (state_dir / PAPER_LOG).exists() else None
    )
    capture_mtime = (
        (state_dir / CAPTURE_LOG).stat().st_mtime if (state_dir / CAPTURE_LOG).exists() else None
    )

    _section_header("📜 Live Logs")
    selected = st.segmented_control(
        "log",
        options=["paper.log", "capture.log"],
        default="paper.log",
        label_visibility="collapsed",
        key="pmb_log_select",
    )
    if selected == "capture.log":
        lines, mtime = capture_lines, capture_mtime
    else:
        lines, mtime = paper_lines, paper_mtime
    age_label = _log_age_label(mtime)
    if not lines:
        st.html(f'<div class="pmb-empty">log file not found · {age_label}</div>')
        return
    html_lines = "".join(
        f'<div class="pmb-log__line {_level_class(line)}">{html.escape(line)}</div>'
        for line in lines
    )
    st.html(
        f'<div style="font-size: 10px; color: var(--text-muted); margin-bottom: 6px; '
        f'text-transform: lowercase; letter-spacing: 0.04em;">last update {age_label}</div>'
        f'<div class="pmb-log">{html_lines}</div>'
    )


def _render_aggressive_trip_wires(rows: list[DecisionRow]) -> None:
    mode = latest_active_mode(rows)
    if mode != "aggressive":
        return

    aggressive_rows = [r for r in rows if r.mode == "aggressive"]
    if not aggressive_rows:
        return

    cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
    rows_24h = [r for r in aggressive_rows if r.decision_dt_utc >= cutoff]
    pnl_24h = sum((r.pnl_usd or 0.0) for r in rows_24h)

    rate_24h, fires_24h = fire_rate_per_hour(aggressive_rows, lookback_hours=24.0)
    fires_per_day = rate_24h * 24

    settled = [r for r in aggressive_rows if r.resolution is not None and r.fill_price is not None]
    won = [r for r in settled if r.resolution == r.side]
    wr = (len(won) / len(settled)) if settled else None

    earliest = min(r.decision_dt_utc for r in aggressive_rows)
    elapsed_h = (datetime.now(tz=UTC) - earliest).total_seconds() / 3600
    review_due = elapsed_h >= 48

    rows_html = []

    def _row(label: str, current: str, threshold: str, breach: bool) -> str:
        cls = "bad" if breach else "good"
        glyph = "🛑" if breach else "✓"
        return (
            f'<tr><td>{glyph} {html.escape(label)}</td>'
            f'<td><b>{html.escape(current)}</b></td>'
            f'<td style="color: var(--text-muted);">{html.escape(threshold)}</td>'
            f'<td><span class="pmb-pill pmb-pill--{cls}">'
            f'{"BREACH" if breach else "OK"}</span></td></tr>'
        )

    rows_html.append(_row("PnL (24h)", f"${pnl_24h:+.2f}", "≥ -$50.00", pnl_24h < -50.0))
    rows_html.append(
        _row(
            "Fire rate (24h)",
            f"{fires_24h} fires · {fires_per_day:.0f}/d",
            "≤ 350/d",
            fires_per_day > 350,
        )
    )
    rows_html.append(
        _row(
            "Net win-rate",
            f"{(wr * 100):.1f}%" if wr is not None else "—",
            "≥ 47% (after 100 settled)",
            wr is not None and len(settled) >= 100 and wr < 0.47,
        )
    )
    rows_html.append(
        _row(
            "Elapsed since 1st aggressive fire",
            f"{elapsed_h:.1f}h",
            "review at 48h",
            review_due,
        )
    )

    table = (
        '<table class="pmb-trip-table" style="width:100%; font-size: 11px;">'
        '<thead><tr>'
        '<th style="text-align: left; color: var(--text-muted);">Trip wire</th>'
        '<th style="text-align: left; color: var(--text-muted);">Current</th>'
        '<th style="text-align: left; color: var(--text-muted);">Threshold</th>'
        '<th style="text-align: left; color: var(--text-muted);">Status</th>'
        '</tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody>'
        '</table>'
    )
    st.html(
        '<div class="pmb-section"><div class="pmb-card__title">'
        "🛑 Aggressive-mode exit criteria</div></div>" + table
    )


def _render_tier_panel(rows: list[DecisionRow]) -> None:
    stats = per_tier_stats(rows)
    st.html(
        '<div class="pmb-section"><div class="pmb-card__title">'
        "🎯 Per-tier discipline check</div></div>"
    )
    if not stats:
        st.html('<div class="pmb-empty">No fires yet to break down by tier.</div>')
        return
    df = pd.DataFrame(
        [
            {
                "Tier": s.tier,
                "Fires": s.n_fired,
                "Filled": s.n_filled,
                "Settled": s.n_settled,
                "Won": s.n_won,
                "WR": (s.win_rate * 100 if s.win_rate is not None else None),
                "PnL": s.pnl_usd,
            }
            for s in stats
        ]
    )
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Tier": st.column_config.TextColumn("Tier", width="small"),
            "WR": st.column_config.NumberColumn("WR", format="%.1f%%", width="small"),
            "PnL": st.column_config.NumberColumn("PnL", format="$%+.2f", width="small"),
        },
    )


def _render_agent_panel() -> None:
    transcript = load_transcript(PHASE_3_AB_PATH, verdict_path=PHASE_3_VERDICT_PATH)
    title = (
        '<div class="pmb-card__title pmb-card__title--muted">🤖 Agent Activity'
        f"{badge('HISTORICAL · Phase 3 A/B', tone='warn')}</div>"
    )

    if transcript is None:
        st.html(
            f'<div class="pmb-card pmb-card--dim">{title}'
            '<div class="pmb-empty">No Phase 3 evidence found.</div></div>'
        )
        return

    det = transcript.deterministic
    ens = transcript.ensemble
    pieces: list[str] = [
        '<div class="pmb-feed-row pmb-feed-row--4col">',
        '<div class="pmb-feed">'
        '<div class="pmb-feed__name">deterministic</div>'
        f'<div class="pmb-feed__stat"><strong>{det.n_fired if det else "—"}</strong> fired</div>'
        f'<div class="pmb-feed__stat"><strong>{det.n_filled if det else "—"}</strong> filled · '
        f"<strong>{det.n_won if det else '—'}</strong> won</div>"
        f'<div class="pmb-feed__stat"><strong>{_fmt_pct(det.win_rate) if det else "—"}</strong> win-rate</div>'
        f'<div class="pmb-feed__stat"><strong>{_fmt_currency(det.total_pnl_usd) if det else "—"}</strong> pnl</div>'
        "</div>",
        '<div class="pmb-feed">'
        '<div class="pmb-feed__name">ensemble</div>'
        f'<div class="pmb-feed__stat"><strong>{ens.n_fired if ens else "—"}</strong> fired</div>'
        f'<div class="pmb-feed__stat"><strong>{ens.n_filled if ens else "—"}</strong> filled · '
        f"<strong>{ens.n_won if ens else '—'}</strong> won</div>"
        f'<div class="pmb-feed__stat"><strong>{_fmt_pct(ens.win_rate) if ens else "—"}</strong> win-rate</div>'
        f'<div class="pmb-feed__stat"><strong>{_fmt_currency(ens.total_pnl_usd) if ens else "—"}</strong> pnl</div>'
        "</div>",
        '<div class="pmb-feed">'
        '<div class="pmb-feed__name">api activity</div>'
        f'<div class="pmb-feed__stat"><strong>{transcript.n_anthropic_calls:,}</strong> /v1/messages calls</div>'
        f'<div class="pmb-feed__stat"><strong>{ens.elapsed_s:.1f}s</strong> elapsed</div>'
        '<div class="pmb-feed__stat">3 specialists x Sonnet meta · decision #5</div>'
        "</div>",
        '<div class="pmb-feed">'
        '<div class="pmb-feed__name">verdict</div>'
        f'<div class="pmb-feed__stat" style="margin-top: 6px;">'
        f"{badge(transcript.verdict or 'PENDING', tone='bad' if transcript.verdict == 'CUT' else 'good')}"
        "</div>"
        '<div class="pmb-feed__err">decision #16: kept iff uplift≥3pp, p99≤4s, $/dec≤$0.01.</div>'
        "</div>",
        "</div>",
    ]
    body = "".join(pieces)
    st.html(f'<div class="pmb-card pmb-card--dim">{title}{body}</div>')


# ============================================================================
# v2 panels
# ============================================================================


def _render_topstrip_v2(
    rows: list[DecisionRow], paper: ProcessStatus, *, last_sync_age_s: float | None
) -> None:
    bankroll = load_bankroll(rows)
    bankroll_html = bankroll_chip(bankroll.starting_usd, bankroll.current_usd)
    tabs_html = market_tabs(active="BTC")

    mode = latest_active_mode(rows)
    if mode in _MODE_BADGE:
        label, tone = _MODE_BADGE[mode]
    elif mode is not None:
        label, tone = (mode.upper(), "warn")
    else:
        label, tone = ("WAITING", "warn")
    mode_badge = badge(label, tone=tone)

    sub_text = "Phase 11.A · spot_aware paper-soak"
    if mode == "aggressive":
        sub_text = "Phase 11.A.2 · aggressive_mode · 48h gate at 2026-05-10 22:26 UTC"

    sync_text = (
        f"vps sync {_humanize_age(last_sync_age_s)}"
        if last_sync_age_s is not None
        else "vps sync: never"
    )
    clock = datetime.now(tz=UTC).strftime("%H:%M:%S UTC")
    paper_status = "ALIVE" if paper.alive else "OFFLINE"
    paper_tone = "good" if paper.alive else "bad"

    st.html(
        '<div class="pmb-topstrip">'
        '<div class="pmb-topstrip__left">'
        '<span class="pmb-live-dot" title="live"></span>'
        '<span class="pmb-topstrip__brand">POLYMARKET 5M</span>'
        f"{tabs_html}"
        f"{mode_badge}"
        f'<span class="pmb-topstrip__sub">{html.escape(sub_text)}</span>'
        "</div>"
        '<div class="pmb-topstrip__right">'
        f"{bankroll_html}"
        f"{badge(paper_status, tone=paper_tone)}"
        f'<span class="pmb-topstrip__sub">{html.escape(sync_text)}</span>'
        f'<span class="pmb-clock">{html.escape(clock)}</span>'
        "</div>"
        "</div>"
    )


def _render_live_tape_v2(rows: list[DecisionRow]) -> None:
    events = tape_events_from_decisions(rows, n=12)
    st.html(live_tape(events))


def _render_pnl_chart_plotly(rows: list[DecisionRow]) -> None:
    settled = [r for r in rows if r.pnl_usd is not None]
    _section_header("📈 Cumulative PnL")
    if not settled:
        st.html(
            '<div class="pmb-empty">'
            "No settled decisions yet. Settled records appear after the 5-min "
            "window closes and oracle resolution lands."
            "</div>"
        )
        return
    import plotly.graph_objects as go  # local import; plotly is heavy

    df = pd.DataFrame(
        {
            "decision_dt_utc": [r.decision_dt_utc for r in settled],
            "pnl_usd": [r.pnl_usd or 0.0 for r in settled],
        }
    ).sort_values("decision_dt_utc")
    df["cumulative_pnl"] = df["pnl_usd"].cumsum()

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["decision_dt_utc"],
            y=df["cumulative_pnl"],
            mode="lines",
            line={"color": "#8aff7a", "width": 2, "shape": "spline", "smoothing": 0.8},
            fill="tozeroy",
            fillcolor="rgba(138, 255, 122, 0.18)",
            hovertemplate="%{x|%Y-%m-%d %H:%M:%S}<br>Cumulative: $%{y:.4f}<extra></extra>",
            name="Cumulative PnL",
        )
    )
    fig.update_layout(
        height=240,
        margin={"t": 10, "b": 30, "l": 50, "r": 10},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "JetBrains Mono", "size": 10, "color": "#9c8d6b"},
        xaxis={
            "showgrid": False,
            "tickformat": "%b %d %H:%M",
            "tickfont": {"size": 9, "color": "#9c8d6b"},
        },
        yaxis={
            "gridcolor": "rgba(42, 38, 28, 0.5)",
            "tickformat": "$,.2f",
            "tickfont": {"size": 9, "color": "#9c8d6b"},
            "zerolinecolor": "#3d3725",
            "zerolinewidth": 1,
        },
        hoverlabel={
            "bgcolor": "#11100c",
            "bordercolor": "#3d3725",
            "font": {"family": "JetBrains Mono", "size": 11, "color": "#f5edd6"},
        },
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def _render_decisions_aggrid(rows: list[DecisionRow]) -> None:
    _section_header("📋 Decisions Tape")
    if not rows:
        st.html(
            '<div class="pmb-empty">No decisions logged yet. '
            "Files at <code>state/decisions/&lt;UTC-date&gt;.jsonl</code> populate "
            "as the active strategy fires.</div>"
        )
        return
    from st_aggrid import AgGrid, GridOptionsBuilder
    from st_aggrid.shared import GridUpdateMode

    df = pd.DataFrame(
        [
            {
                "When": r.decision_dt_utc.strftime("%H:%M:%S · %b %d"),
                "Side": "▲ UP" if r.side == "UP" else "▼ DOWN",
                "Tier": _tier_for_price(r.price_limit),
                "Limit": round(r.price_limit, 4),
                "Fill": round(r.fill_price, 4) if r.fill_price is not None else None,
                "Outcome": (
                    "WON"
                    if r.resolution is not None and r.resolution == r.side
                    else "LOST"
                    if r.resolution is not None
                    else "PENDING"
                ),
                "PnL": round(r.pnl_usd, 4) if r.pnl_usd is not None else None,
                "Δ_bps": r.delta_bps,
                "p_win": r.p_win,
                "EV": r.ev_dollars,
                "TTL": r.ttl_s,
            }
            for r in reversed(rows)
        ]
    )
    gb = GridOptionsBuilder.from_dataframe(df)
    gb.configure_default_column(
        sortable=True,
        filterable=False,
        resizable=True,
        suppressMenu=True,
    )
    gb.configure_grid_options(
        rowHeight=26,
        headerHeight=28,
        suppressCellSelection=True,
        suppressMovableColumns=True,
    )
    grid_opts = gb.build()
    AgGrid(
        df,
        gridOptions=grid_opts,
        theme="alpine-dark",
        height=320,
        update_mode=GridUpdateMode.NO_UPDATE,
        allow_unsafe_jscode=False,
        fit_columns_on_grid_load=True,
        key="pmb_decisions_grid",
    )


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


# ============================================================================
# main entrypoints
# ============================================================================


def _render_main_v1(
    capture: ProcessStatus,
    paper: ProcessStatus,
    snap: HealthSnapshot | None,
    rows: list[DecisionRow],
    issues: list[str],
    state_dir: Path,
    last_sync_age_s: float | None,
    since: str,
) -> None:
    _render_header_v1(
        refreshed_at=datetime.now(tz=UTC),
        since_filter=since,
        rows=rows,
        last_sync_age_s=last_sync_age_s,
    )
    if issues:
        st.html(incident_banner(issues))
    _render_kpi_row_v1(rows, paper)

    main_col, side_col, log_col = st.columns([0.55, 0.25, 0.20], gap="small")
    with main_col, st.container(border=True, key="pmb-main-panel"):
        _render_pnl_chart_v1(rows)
        _render_decisions_table_v1(rows)
    with side_col, st.container(border=True, key="pmb-side-panel"):
        _render_processes_inline(capture, paper)
        _render_feeds_inline(snap)
    with log_col, st.container(border=True, key="pmb-log-panel"):
        _render_log_panel(state_dir)

    _render_aggressive_trip_wires(rows)
    _render_tier_panel(rows)

    with st.expander("🤖  Historical agent activity  ·  Phase 3 A/B (CUT)", expanded=False):
        _render_agent_panel()


def _today_pnl(rows: list[DecisionRow]) -> tuple[float | None, int]:
    """Sum of pnl_usd for settled rows whose decision_dt_utc is today (UTC)."""
    today = datetime.now(tz=UTC).date()
    settled_today = [
        r
        for r in rows
        if r.resolution is not None and r.pnl_usd is not None and r.decision_dt_utc.date() == today
    ]
    if not settled_today:
        return (0.0, 0) if rows else (None, 0)
    return (sum(r.pnl_usd or 0.0 for r in settled_today), len(settled_today))


def _best_tier_pnl(rows: list[DecisionRow]) -> tuple[str | None, float | None]:
    """Return (label, pnl_usd) of the tier with the highest cumulative PnL."""
    stats = per_tier_stats(rows)
    if not stats:
        return (None, None)
    best = max(stats, key=lambda s: s.pnl_usd)
    return (best.tier, best.pnl_usd)


def _elapsed_label(rows: list[DecisionRow]) -> str:
    if not rows:
        return "—"
    first = min(rows, key=lambda r: r.decision_dt_utc).decision_dt_utc
    elapsed_s = (datetime.now(tz=UTC) - first).total_seconds()
    return _humanize_age(elapsed_s).replace(" ago", "")


def _render_row1_panels(rows: list[DecisionRow], paper: ProcessStatus) -> None:
    """Row 1 — wallet | TradingView | Polymarket CTF book | Live PnL pace.

    Single horizontal strip; everything visible without scrolling.
    """
    bankroll = load_bankroll(rows)
    agg = aggregate_pnl(rows)
    streak = compute_streak(rows)
    pace_per_hour, pace_n = profit_pace_per_hour(rows, window_s=3600.0)
    today_pnl_val, today_n = _today_pnl(rows)
    best_tier_label, best_tier_pnl = _best_tier_pnl(rows)

    mode = latest_active_mode(rows)
    if mode in _MODE_BADGE:
        mode_label, mode_tone = _MODE_BADGE[mode]
    else:
        mode_label, mode_tone = ("OFFLINE" if not paper.alive else "WAITING", "warn")

    win_rate_val = agg["win_rate"] if isinstance(agg["win_rate"], float) else None
    avg_pnl_val = (
        agg["avg_pnl_per_filled"] if isinstance(agg["avg_pnl_per_filled"], float) else None
    )
    n_fired_val = int(agg["n_fired"]) if isinstance(agg["n_fired"], int) else 0
    n_filled_val = int(agg["n_filled"]) if isinstance(agg["n_filled"], int) else 0
    n_settled_val = int(agg["n_settled"]) if isinstance(agg["n_settled"], int) else 0
    n_won_val = int(agg["n_won"]) if isinstance(agg["n_won"], int) else 0

    wallet_html = wallet_panel(
        starting_usd=bankroll.starting_usd,
        current_usd=bankroll.current_usd,
        n_fired=n_fired_val,
        n_filled=n_filled_val,
        n_settled=n_settled_val,
        n_won=n_won_val,
        win_rate=win_rate_val,
        avg_pnl_per_filled=avg_pnl_val,
        elapsed_label=_elapsed_label(rows),
        mode_label=mode_label,
        mode_tone=mode_tone,  # type: ignore[arg-type]
    )
    live_html = live_pnl_panel(
        pace_per_hour=pace_per_hour,
        pace_n=pace_n,
        streak_glyph=streak.current_glyph,
        streak_n=streak.current_n,
        best_win_streak=streak.best_win_streak,
        worst_loss_streak=streak.worst_loss_streak,
        today_pnl=today_pnl_val,
        today_n=today_n,
        best_tier_label=best_tier_label,
        best_tier_pnl=best_tier_pnl,
    )

    ctf_snap = None
    if rows:
        most_recent = max(rows, key=lambda r: r.decision_dt_utc)
        try:
            ctf_snap = fetch_ctf_orderbook(most_recent.window_ts, side=most_recent.side)
        except Exception:
            ctf_snap = None
    ctf_html = orderbook_from_ctf(ctf_snap)

    wallet_col, chart_col, book_col, live_col = st.columns([0.22, 0.30, 0.22, 0.26], gap="small")
    with wallet_col:
        st.html(wallet_html)
    with chart_col, st.container(border=True, key="pmb-row1-chart"):
        st.html(
            '<div class="pmb-panel__hdr" style="margin-bottom: 4px;">'
            '<span class="pmb-panel__title">BTC · 5M · BINANCE</span>'
            '<span class="pmb-panel__sub" style="margin:0">SPOT REFERENCE</span>'
            "</div>"
        )
        components.html(tradingview_chart(), height=220, scrolling=False)
    with book_col:
        st.html(ctf_html)
    with live_col:
        st.html(live_html)


def _render_pipeline_row_v2(
    rows: list[DecisionRow],
    feeds: list | None,
    capture: ProcessStatus,
    paper: ProcessStatus,
    snap: HealthSnapshot | None,
) -> None:
    """Row 2 — pipeline strip + cycle meta chip on the right."""
    latencies = derive_pipeline_latencies(rows, snap)
    stages = pipeline_stages_from_state(
        rows, snap.feeds if snap else None, capture, paper, latencies
    )
    n_fired_val = len(rows)
    elapsed_label = "—"
    if rows:
        most_recent = max(rows, key=lambda r: r.decision_dt_utc)
        if most_recent.resolution is None:
            elapsed_s = (datetime.now(tz=UTC) - most_recent.decision_dt_utc).total_seconds()
            elapsed_label = _humanize_age(elapsed_s).replace(" ago", "")
        else:
            elapsed_label = "settled"
    pipeline_html = pipeline_strip(stages)
    meta_html = cycle_meta_chip(
        cycle_n=n_fired_val,
        budget_label="5m",
        elapsed_label=elapsed_label,
    )
    st.html(
        '<div class="pmb-cycle-row">'
        f'<div class="pmb-cycle-row__pipeline">{pipeline_html}</div>'
        f'<div class="pmb-cycle-row__meta">{meta_html}</div>'
        "</div>"
    )


def _render_row3_main(rows: list[DecisionRow]) -> None:
    """Row 3 — PnL curve (60%) + decisions tape (40%)."""
    chart_col, table_col = st.columns([0.60, 0.40], gap="small")
    with chart_col, st.container(border=True, key="pmb-main-panel"):
        _render_pnl_chart_plotly(rows)
    with table_col, st.container(border=True, key="pmb-side-panel"):
        _render_decisions_aggrid(rows)


def _render_row4_bottom(
    rows: list[DecisionRow],
    capture: ProcessStatus,
    paper: ProcessStatus,
    snap: HealthSnapshot | None,
    state_dir: Path,
) -> None:
    """Row 4 — provider RTT | trip-wires (compact) | per-tier (compact)."""
    samples_by_provider = load_provider_rtt(state_dir)
    last_age_s: float | None = None
    if samples_by_provider:
        most_recent = max(
            (s.ts_utc for samples in samples_by_provider.values() for s in samples),
            default=None,
        )
        if most_recent is not None:
            last_age_s = (datetime.now(tz=UTC) - most_recent).total_seconds()

    rtt_col, trip_col, tier_col = st.columns([0.30, 0.30, 0.40], gap="small")
    with rtt_col, st.container(border=True, key="pmb-rtt-panel"):
        st.html('<div class="pmb-card__title">📡 PROVIDER RTT · VPS</div>')
        st.html(provider_rtt_panel(samples_by_provider, last_collected_age_s=last_age_s))
    with trip_col, st.container(border=True, key="pmb-trip-panel"):
        _render_aggressive_trip_wires(rows)
        if not rows or latest_active_mode(rows) != "aggressive":
            _render_processes_inline(capture, paper)
            _render_feeds_inline(snap)
    with tier_col, st.container(border=True, key="pmb-tier-panel"):
        _render_tier_panel(rows)


def _render_main_v2(
    capture: ProcessStatus,
    paper: ProcessStatus,
    snap: HealthSnapshot | None,
    rows: list[DecisionRow],
    issues: list[str],
    state_dir: Path,
    last_sync_age_s: float | None,
) -> None:
    _render_topstrip_v2(rows, paper, last_sync_age_s=last_sync_age_s)
    _render_live_tape_v2(rows)
    if issues:
        st.html(incident_banner(issues))

    _render_row1_panels(rows, paper)
    _render_pipeline_row_v2(rows, snap.feeds if snap else None, capture, paper, snap)
    _render_row3_main(rows)
    _render_row4_bottom(rows, capture, paper, snap, state_dir)

    # Below-the-fold: deemphasized inspect tools (logs, agents) — collapsed.
    with st.expander("📜 Live logs (paper.log + capture.log)", expanded=False):
        _render_log_panel(state_dir)
    with st.expander("🤖 Historical agent activity · Phase 3 A/B (CUT)", expanded=False):
        _render_agent_panel()


def main() -> None:
    page_title = "Polymarket Bot — Operations" + (" · v2" if DASH_V2 else "")
    st.set_page_config(
        page_title=page_title,
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(inject(), unsafe_allow_html=True)

    st.sidebar.title("Dashboard")
    if DASH_V2:
        st.sidebar.markdown("**Layout:** v2 (Bloomberg terminal)")
    else:
        st.sidebar.markdown("**Layout:** v1")
    refresh_s = st.sidebar.slider("Auto-refresh (sec)", 2, 30, 4, step=1)
    refresh_paused = st.sidebar.toggle("⏸ Pause refresh", value=False)
    auto_sync = st.sidebar.toggle(
        "🔁 Auto-sync from VPS",
        value=True,
        help="Run runbooks/scripts/sync_staging.sh before each refresh",
    )
    state_dir = Path(st.sidebar.text_input("state/ dir", value=str(DEFAULT_STATE_DIR)))
    default_since = (datetime.now(tz=UTC) - timedelta(days=14)).strftime("%Y-%m-%d")
    since = st.sidebar.text_input("Decisions since (YYYY-MM-DD)", value=default_since)
    st.sidebar.caption(f"Reading {state_dir}/")

    if not refresh_paused:
        st_autorefresh(interval=refresh_s * 1000, key="pmb_autorefresh")

    if auto_sync and "staging" in str(state_dir):
        _run_sync(state_dir)

    last_sync_age_s = _maybe_auto_sync(state_dir)
    capture, paper = load_process_status(state_dir)
    snap = load_feeds_health(state_dir)
    rows = load_decisions(state_dir / DECISIONS_SUBDIR, since_utc_date=since or None)
    issues = _detect_incidents(capture, paper, snap, state_dir / PAPER_LOG)

    if DASH_V2:
        _render_main_v2(capture, paper, snap, rows, issues, state_dir, last_sync_age_s)
    else:
        _render_main_v1(capture, paper, snap, rows, issues, state_dir, last_sync_age_s, since)


if __name__ == "__main__":
    main()
