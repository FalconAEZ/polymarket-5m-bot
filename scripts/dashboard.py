"""Single-page Streamlit dashboard — Phase 4.5 operations observability.

Run with: `uv run streamlit run scripts/dashboard.py`. Binds to 127.0.0.1:8501
per .streamlit/config.toml. Reads state/decisions/*.jsonl + state/feeds_health.json
+ paper.log + capture.log. Auto-refreshes every N seconds (sidebar control).

Layout per design/dashboard.md §4.3:
  Header strip → 5 KPI hero cards → Center hero PnL chart →
  System + Feeds rows → Agent activity panel → Decisions table →
  Live logs (paper + capture, side-by-side tabs).
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
from streamlit_autorefresh import st_autorefresh  # noqa: E402

from polymarket_bot.dashboard.agents_loader import load_transcript  # noqa: E402
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
    # If state-demo/ exists with a feeds_health.json, prefer it (demo mode).
    demo = ROOT / "state-demo"
    if (demo / "feeds_health.json").exists():
        return demo
    return ROOT / "state"


DEFAULT_STATE_DIR = _resolve_default_state_dir()
PAPER_LOG = "paper.log"
CAPTURE_LOG = "capture.log"
DECISIONS_SUBDIR = "decisions"
PHASE_3_AB_PATH = ROOT / "runbooks" / "gate-evidence" / "phase-3.3-llm-ab.txt"
PHASE_3_VERDICT_PATH = ROOT / "runbooks" / "decisions" / "llm-ab-result.md"


# ----------------------------- helpers ---------------------------------------


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
    """Aggregate red signals into a single list for the top banner.

    Per design-critique recommendation #1 — operator should not have to
    scan multiple panels during an incident. One source of truth.
    """
    issues: list[str] = []
    # Process aliveness
    if paper.pid is not None and not paper.alive:
        issues.append(f"paper process dead (pid {paper.pid})")
    elif paper.pid is None:
        issues.append("paper process not running")
    if capture.pid is not None and not capture.alive:
        issues.append(f"capture process dead (pid {capture.pid})")
    # Feed health
    if snap is None:
        issues.append("feeds_health.json missing")
    else:
        for f in snap.feeds:
            if not f.healthy:
                issues.append(f"{f.name} feed unhealthy")
        age_s = (datetime.now(tz=UTC) - snap.snapshot_mtime_utc).total_seconds()
        if age_s > 300:
            issues.append(f"feeds_health snapshot stale ({_humanize_age(age_s)})")
    # Recent paper.log tracebacks (cheap: scan last 64KB)
    recent = tail_log(paper_log_path, n_lines=200)
    if any("Traceback" in line for line in recent):
        issues.append("traceback in paper.log (last 200 lines)")
    return issues


# ----------------------------- panels ----------------------------------------


_MODE_BADGE = {
    "aggressive": ("AGGRESSIVE MODE", "bad"),
    "spot_aware": ("SPOT_AWARE", "good"),
    "deterministic": ("DETERMINISTIC", "warn"),
}


def _render_header(
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
        sub_parts.append(f"vps sync: {_humanize_age(last_sync_age_s)} ago")
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


def _render_kpi_row(rows: list[DecisionRow], paper: ProcessStatus) -> None:
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
    elif rate_per_hour > 14.5:  # >350/d → trip wire #2 in aggressive runbook
        rate_tone = "bad"
    else:
        rate_tone = "good"

    pnl_card = kpi_card(
        label="Cumulative PnL",
        value=_fmt_currency(pnl) if isinstance(pnl, float) else "—",
        subtitle=f"avg {_fmt_currency(avg_pnl, decimals=3)} / trade"
        if isinstance(avg_pnl, float)
        else None,
        tone=pnl_tone,
        glyph=pnl_glyph,
    )
    win_card = kpi_card(
        label="Win Rate",
        value=_fmt_pct(win_rate) if isinstance(win_rate, float) else "—",
        subtitle=f"{n_won}/{n_settled} settled"
        if isinstance(n_won, int) and isinstance(n_settled, int)
        else None,
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

    # KPI grid uses the SAME 55/25/20 column ratios as the panel grid
    # below so each KPI vertically aligns with its related panel.
    main_kpi_col, side_kpi_col, log_kpi_col = st.columns([0.55, 0.25, 0.20], gap="small")
    with main_kpi_col:
        # 4 sub-KPIs (PnL / Win / Decisions / Fire Rate) above the chart+table panel
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
        st.html(last_card)  # above the Processes/Feeds panel
    with log_kpi_col:
        st.html(uptime_card)  # above the Live Logs panel


def _section_header(title: str, badge_html: str = "") -> None:
    """A panel section header. Used to group widgets visually without
    trying to wrap them in HTML containers (which breaks Streamlit's block
    model). Each header is a single self-contained st.html call."""
    st.html(
        f'<div class="pmb-section"><div class="pmb-card__title">{title}{badge_html}</div></div>'
    )


def _render_pnl_chart(rows: list[DecisionRow]) -> None:
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
    df["color"] = df["cumulative_pnl"].apply(lambda v: "good" if v >= 0 else "bad")

    base = alt.Chart(df).encode(
        x=alt.X(
            "decision_dt_utc:T",
            title=None,
            axis=alt.Axis(
                format="%b %d %H:%M",
                labelColor="#9ba6b3",
                titleColor="#9ba6b3",
                grid=False,
                domain=False,
                tickColor="#1f242e",
                labelFontSize=10,
                labelFontWeight=500,
                labelPadding=6,
                tickCount=6,  # ~6 label slots — was ~14, much less clutter
            ),
        ),
        y=alt.Y(
            "cumulative_pnl:Q",
            title=None,
            axis=alt.Axis(
                labelColor="#9ba6b3",
                grid=True,
                gridColor="#171c25",
                gridOpacity=0.6,
                domain=False,
                ticks=False,
                labelFontSize=10,
                labelPadding=6,
                format="$,.2f",
            ),
        ),
    )
    area = base.mark_area(
        line={"color": "#2ee08c", "strokeWidth": 2, "strokeJoin": "round", "strokeCap": "round"},
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color="rgba(46, 224, 140, 0.42)", offset=0),
                alt.GradientStop(color="rgba(46, 224, 140, 0.02)", offset=1),
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
        .mark_rule(color="#2a3140", strokeWidth=1, strokeDash=[3, 3])
        .encode(y="y:Q")
    )
    # Pulsing dot at the latest data point — shows the "live" tip of the line.
    latest = df.iloc[-1:]
    glow = (
        alt.Chart(latest)
        .mark_point(size=380, filled=True, color="#2ee08c", opacity=0.20)
        .encode(x="decision_dt_utc:T", y="cumulative_pnl:Q")
    )
    dot = (
        alt.Chart(latest)
        .mark_point(size=120, filled=True, color="#2ee08c", stroke="#08090c", strokeWidth=2)
        .encode(x="decision_dt_utc:T", y="cumulative_pnl:Q")
    )
    chart = (
        (zero_rule + area + glow + dot)
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
    """Same content as _render_processes but no outer .pmb-card wrapper —
    used inside .st-key-pmb-side-panel which already provides the card."""
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
    """No outer card; inline variant for use inside a side-panel container."""
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


def _render_processes(capture: ProcessStatus, paper: ProcessStatus) -> None:
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
    st.html(
        f'<div class="pmb-card">'
        f'<div class="pmb-card__title">⚙️ Processes</div>'
        f"{''.join(rows_html)}"
        f"</div>"
    )


def _render_feeds(snap: HealthSnapshot | None) -> None:
    if snap is None:
        st.html(
            '<div class="pmb-card">'
            '<div class="pmb-card__title">📡 Feeds Health</div>'
            '<div class="pmb-empty">No feeds_health.json found.</div>'
            "</div>"
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
            f"{badge('OK' if f.healthy else 'BAD', tone=tone)}</div>"
            f'<div class="pmb-feed__stat"><strong>{f.msgs_seen:,}</strong> msgs</div>'
            f'<div class="pmb-feed__stat"><strong>{f.reconnects}</strong> reconnects</div>'
            f'<div class="pmb-feed__err">{html.escape(last_err)}</div>'
            f"</div>"
        )
    st.html(
        f'<div class="pmb-card">'
        f'<div class="pmb-card__title">📡 Feeds Health{age_badge}</div>'
        f'<div class="pmb-feed-row">{"".join(feed_cards)}</div>'
        f"</div>"
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
            '<div class="pmb-empty">No Phase 3 evidence found. The LLM ensemble '
            "runs only when explicitly enabled — see <code>scripts/run_ab.py "
            "--enable-ensemble</code>.</div></div>"
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
        '<div class="pmb-feed__err">decision #16: kept iff uplift≥3pp, p99≤4s, $/dec≤$0.01. Two of three failed.</div>'
        "</div>",
        "</div>",
    ]
    if transcript.sample_rationales:
        pieces.append(
            '<div class="pmb-rationale__heading">Sample agent rationales (from schema-validation logs):</div>'
        )
        for r in transcript.sample_rationales[:3]:
            pieces.append(f'<div class="pmb-rationale">{html.escape(r)}</div>')
    body = "".join(pieces)
    st.html(f'<div class="pmb-card pmb-card--dim">{title}{body}</div>')


def _render_decisions_table(rows: list[DecisionRow]) -> None:
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
            for r in reversed(rows)  # newest first
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
                help="5-min market window_ts (Unix seconds). "
                "Same identifier used in the Polymarket slug "
                "btc-updown-5m-<window_ts>.",
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


def _log_age_label(mtime: float | None) -> str:
    if mtime is None:
        return "missing"
    age_s = (datetime.now(tz=UTC) - datetime.fromtimestamp(mtime, tz=UTC)).total_seconds()
    return _humanize_age(age_s)


# ----------------------------- main ------------------------------------------


SYNC_SCRIPT = ROOT / "runbooks" / "scripts" / "sync_staging.sh"


def _maybe_auto_sync(state_dir: Path) -> float | None:
    """Run sync_staging.sh if enabled, return last-sync age in seconds."""
    sentinel = state_dir / "feeds_health.json"
    if not sentinel.exists():
        return None
    return (
        datetime.now(tz=UTC) - datetime.fromtimestamp(sentinel.stat().st_mtime, tz=UTC)
    ).total_seconds()


SYNC_MIN_INTERVAL_S = 30.0


def _run_sync(state_dir: Path) -> bool:
    """Run sync_staging.sh in the background, throttled to one per 30s.

    Streamlit autorefreshes every few seconds; sync_staging.sh takes
    ~5-15s. Without throttling, sync processes stack up faster than they
    complete and eat CPU. We use the on-disk feeds_health.json mtime as
    the "last sync time" — anything newer than 30s skips. Subprocess is
    fire-and-forget (Popen, no wait) so the Streamlit render is never
    blocked on the rsync.
    """
    if not SYNC_SCRIPT.exists():
        return False
    sentinel = state_dir / "feeds_health.json"
    if sentinel.exists():
        age = (
            datetime.now(tz=UTC) - datetime.fromtimestamp(sentinel.stat().st_mtime, tz=UTC)
        ).total_seconds()
        if age < SYNC_MIN_INTERVAL_S:
            return False
    # Race: multiple concurrent Streamlit autorefreshes can all see the
    # same stale mtime and each spawn a sync. Touch the sentinel first
    # so subsequent renders within the same throttle window see fresh
    # mtime before the rsync writes its real content.
    if sentinel.exists():
        try:
            sentinel.touch()
        except OSError:
            pass
    try:
        import subprocess

        # bash + SYNC_SCRIPT are controlled paths in this repo. Popen
        # (not run) — non-blocking; render proceeds while sync streams
        # data in the background.
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


def _render_aggressive_trip_wires(rows: list[DecisionRow]) -> None:
    """Trip-wire panel for the aggressive-mode 48h experiment.

    Shows progress against the four numerical exit criteria from
    runbooks/decisions/aggressive-mode-2026-05-09.md so the operator can
    see at a glance whether we're still safely inside the experiment.
    """
    mode = latest_active_mode(rows)
    if mode != "aggressive":
        return

    aggressive_rows = [r for r in rows if r.mode == "aggressive"]
    if not aggressive_rows:
        return

    # PnL trip wire (-$50 in any rolling 24h)
    cutoff = datetime.now(tz=UTC) - timedelta(hours=24)
    rows_24h = [r for r in aggressive_rows if r.decision_dt_utc >= cutoff]
    pnl_24h = sum((r.pnl_usd or 0.0) for r in rows_24h)

    # Fire rate trip wire (>350/d)
    rate_24h, fires_24h = fire_rate_per_hour(aggressive_rows, lookback_hours=24.0)
    fires_per_day = rate_24h * 24

    # WR trip wire (<47% on 100+ settled)
    settled = [r for r in aggressive_rows if r.resolution is not None and r.fill_price is not None]
    won = [r for r in settled if r.resolution == r.side]
    wr = (len(won) / len(settled)) if settled else None

    # 48h elapsed (from earliest aggressive decision)
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
            f"{(wr*100):.1f}%" if wr is not None else "—",
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


def main() -> None:
    st.set_page_config(
        page_title="Polymarket Bot — Operations",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(inject(), unsafe_allow_html=True)

    # Sidebar controls.
    st.sidebar.title("Dashboard")
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

    # Pull fresh VPS state if requested. Best-effort; the rest of the
    # page renders from local files regardless.
    if auto_sync and "staging" in str(state_dir):
        _run_sync(state_dir)

    # Load state.
    last_sync_age_s = _maybe_auto_sync(state_dir)
    capture, paper = load_process_status(state_dir)
    snap = load_feeds_health(state_dir)
    rows = load_decisions(state_dir / DECISIONS_SUBDIR, since_utc_date=since or None)
    issues = _detect_incidents(capture, paper, snap, state_dir / PAPER_LOG)

    # ABOVE THE FOLD — fits in a single viewport (~900px tall).
    # Header → incident banner → KPI strip → 3-column terminal grid.
    _render_header(
        refreshed_at=datetime.now(tz=UTC),
        since_filter=since,
        rows=rows,
        last_sync_age_s=last_sync_age_s,
    )
    if issues:
        st.html(incident_banner(issues))
    _render_kpi_row(rows, paper)

    main_col, side_col, log_col = st.columns([0.55, 0.25, 0.20], gap="small")
    with main_col, st.container(border=True, key="pmb-main-panel"):
        _render_pnl_chart(rows)
        _render_decisions_table(rows)
    with side_col, st.container(border=True, key="pmb-side-panel"):
        _render_processes_inline(capture, paper)
        _render_feeds_inline(snap)
    with log_col, st.container(border=True, key="pmb-log-panel"):
        _render_log_panel(state_dir)

    # Below-the-fold panels: aggressive-mode trip wires (only renders if
    # mode==aggressive) + per-tier discipline breakdown.
    _render_aggressive_trip_wires(rows)
    _render_tier_panel(rows)

    # Historical reference (Phase 3 ensemble that was CUT) — collapsed by
    # default so the live above-fold content fills the viewport. Operator
    # clicks to expand for the post-mortem.
    with st.expander("🤖  Historical agent activity  ·  Phase 3 A/B (CUT)", expanded=False):
        _render_agent_panel()


if __name__ == "__main__":
    main()
