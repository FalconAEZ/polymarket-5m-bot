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
    load_decisions,
    load_feeds_health,
    load_process_status,
    tail_log,
)
from polymarket_bot.dashboard.theme import (  # noqa: E402
    badge,
    incident_banner,
    inject,
    kpi_card,
)

DEFAULT_STATE_DIR = ROOT / "state"
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


def _render_header(refreshed_at: datetime, since_filter: str | None) -> None:
    sub_parts = [f"refreshed {refreshed_at.strftime('%H:%M:%S')} UTC"]
    if since_filter:
        sub_parts.append(f"since {since_filter}")
    sub = " · ".join(sub_parts)
    mode_badge = badge("DETERMINISTIC", tone="warn")
    st.markdown(
        f"""
        <div class="pmb-header">
          <div>
            <h1 class="pmb-header__title">Polymarket 5m BTC Bot — Operations</h1>
            <div class="pmb-header__sub" style="margin-top: 4px;">
              {mode_badge}
              <span style="margin-left: 8px;">ensemble CUT per Phase 3 OD-5</span>
            </div>
          </div>
          <div class="pmb-header__sub">{html.escape(sub)}</div>
        </div>
        """,
        unsafe_allow_html=True,
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

    cols = st.columns(5, gap="small")
    cards = [
        kpi_card(
            label="Cumulative PnL",
            value=_fmt_currency(pnl) if isinstance(pnl, float) else "—",
            subtitle=f"avg {_fmt_currency(avg_pnl, decimals=3)} / trade"
            if isinstance(avg_pnl, float)
            else None,
            tone=pnl_tone,
            glyph=pnl_glyph,
        ),
        kpi_card(
            label="Win Rate",
            value=_fmt_pct(win_rate) if isinstance(win_rate, float) else "—",
            subtitle=f"{n_won}/{n_settled} settled"
            if isinstance(n_won, int) and isinstance(n_settled, int)
            else None,
            tone=wr_tone,
        ),
        kpi_card(
            label="Decisions Fired",
            value=_fmt_int(n_fired) if isinstance(n_fired, int) else "—",
            subtitle=f"{agg['n_filled']} filled" if isinstance(agg["n_filled"], int) else None,
            tone="neutral",
        ),
        kpi_card(
            label="Last Decision",
            value=last_dec,
            subtitle="silence is normal at threshold 0.6pp" if not rows else None,
            tone=last_dec_tone,
        ),
        kpi_card(
            label="Paper Uptime",
            value=uptime_value,
            subtitle=f"PID {paper.pid}" if paper.pid is not None else "no PID file",
            tone=uptime_tone,
        ),
    ]
    for col, card in zip(cols, cards, strict=True):
        with col:
            st.markdown(card, unsafe_allow_html=True)


def _render_pnl_chart(rows: list[DecisionRow]) -> None:
    settled = [r for r in rows if r.pnl_usd is not None]
    st.markdown(
        '<div class="pmb-card"><div class="pmb-card__title">📈 Cumulative PnL</div>',
        unsafe_allow_html=True,
    )
    if not settled:
        st.markdown(
            '<div style="color: var(--text-muted); padding: 40px 0; text-align: center;">'
            "No settled decisions yet. The deterministic strategy at 0.6pp threshold "
            "may go many windows without firing — that matches the Phase 3 baseline."
            "</div></div>",
            unsafe_allow_html=True,
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

    chart = (
        alt.Chart(df)
        .mark_area(
            line={"color": "#1ed760", "strokeWidth": 2},
            color=alt.Gradient(
                gradient="linear",
                stops=[
                    alt.GradientStop(color="rgba(30, 215, 96, 0.45)", offset=0),
                    alt.GradientStop(color="rgba(30, 215, 96, 0.0)", offset=1),
                ],
                x1=1,
                x2=1,
                y1=1,
                y2=0,
            ),
        )
        .encode(
            x=alt.X(
                "decision_dt_utc:T",
                title="UTC",
                axis=alt.Axis(
                    format="%b %d %H:%M", labelColor="#8b949e", titleColor="#8b949e", grid=False
                ),
            ),
            y=alt.Y(
                "cumulative_pnl:Q",
                title="Cumulative PnL ($)",
                axis=alt.Axis(
                    labelColor="#8b949e", titleColor="#8b949e", grid=True, gridColor="#21262d"
                ),
            ),
            tooltip=[
                alt.Tooltip("decision_dt_utc:T", title="When", format="%Y-%m-%d %H:%M:%S UTC"),
                alt.Tooltip("side:N", title="Side"),
                alt.Tooltip("pnl_usd:Q", title="Trade PnL", format="+$.4f"),
                alt.Tooltip("cumulative_pnl:Q", title="Cumulative", format="+$.4f"),
            ],
        )
        .properties(height=360, background="transparent")
        .configure_view(strokeWidth=0)
    )
    st.altair_chart(chart, use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_system_row(
    capture: ProcessStatus, paper: ProcessStatus, snap: HealthSnapshot | None
) -> None:
    col1, col2 = st.columns([1, 2], gap="small")
    with col1:
        _render_processes(capture, paper)
    with col2:
        _render_feeds(snap)


def _render_processes(capture: ProcessStatus, paper: ProcessStatus) -> None:
    rows: list[str] = []
    for p in (capture, paper):
        if p.alive:
            tone = "good"
            label = "ALIVE"
        elif p.pid is not None:
            tone = "bad"
            label = "DEAD"
        else:
            tone = "muted"
            label = "ABSENT"
        pid_str = f"pid {p.pid}" if p.pid is not None else "no pid file"
        uptime = _process_uptime(p)
        rows.append(
            f"""
            <div style="display: flex; justify-content: space-between; align-items: center;
                        padding: 8px 0; border-bottom: 1px solid var(--border-subtle);">
              <div>
                <div style="font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; font-size: 12px;">{p.name}</div>
                <div style="color: var(--text-muted); font-size: 11px;">{pid_str} · uptime {uptime}</div>
              </div>
              {badge(label, tone=tone)}
            </div>
            """
        )
    body = "".join(rows)
    st.markdown(
        f"""<div class="pmb-card"><div class="pmb-card__title">⚙️ Processes</div>{body}</div>""",
        unsafe_allow_html=True,
    )


def _render_feeds(snap: HealthSnapshot | None) -> None:
    title_html = '<div class="pmb-card__title">📡 Feeds Health'
    if snap is None:
        st.markdown(
            f"""<div class="pmb-card">{title_html}</div>
            <div style="color: var(--text-muted); padding: 12px 0;">No feeds_health.json found.</div></div>""",
            unsafe_allow_html=True,
        )
        return
    age_s = (datetime.now(tz=UTC) - snap.snapshot_mtime_utc).total_seconds()
    age_tone = "good" if age_s < 60 else ("warn" if age_s < 300 else "bad")
    title_html += f" {badge(_humanize_age(age_s), tone=age_tone)}</div>"
    feed_cards = []
    for f in snap.feeds:
        tone = "good" if f.healthy else "bad"
        last_err = f.last_error[:80] if f.last_error else "no errors"
        feed_cards.append(
            f"""
            <div class="pmb-feed">
              <div class="pmb-feed__name">
                {html.escape(f.name)}
                {badge("OK" if f.healthy else "BAD", tone=tone)}
              </div>
              <div class="pmb-feed__stat"><strong>{f.msgs_seen:,}</strong> msgs</div>
              <div class="pmb-feed__stat"><strong>{f.reconnects}</strong> reconnects</div>
              <div class="pmb-feed__stat" style="color: var(--text-muted); font-size: 10px; margin-top: 4px;">{html.escape(last_err)}</div>
            </div>
            """
        )
    feeds_html = '<div class="pmb-feed-row">' + "".join(feed_cards) + "</div>"
    st.markdown(
        f"""<div class="pmb-card">{title_html}{feeds_html}</div>""",
        unsafe_allow_html=True,
    )


def _render_agent_panel() -> None:
    transcript = load_transcript(PHASE_3_AB_PATH, verdict_path=PHASE_3_VERDICT_PATH)
    title_html = (
        '<div class="pmb-card__title pmb-card__title--muted">🤖 Agent Activity '
        + badge("HISTORICAL · Phase 3 A/B", tone="warn")
        + "</div>"
    )

    if transcript is None:
        st.markdown(
            f"""<div class="pmb-card pmb-card--dim">{title_html}
            <div style="color: var(--text-secondary); padding: 12px 0;">
              No Phase 3 evidence found. The LLM ensemble runs only when explicitly
              enabled — see <code>scripts/run_ab.py --enable-ensemble</code>.
            </div></div>""",
            unsafe_allow_html=True,
        )
        return

    # Top: A/B summary as a 4-column grid.
    det = transcript.deterministic
    ens = transcript.ensemble
    summary = f"""
    <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px;">
      <div class="pmb-feed">
        <div class="pmb-feed__name">deterministic</div>
        <div class="pmb-feed__stat"><strong>{det.n_fired if det else "—"}</strong> fired</div>
        <div class="pmb-feed__stat"><strong>{det.n_filled if det else "—"}</strong> filled · <strong>{det.n_won if det else "—"}</strong> won</div>
        <div class="pmb-feed__stat" style="margin-top: 4px;"><strong>{_fmt_pct(det.win_rate) if det else "—"}</strong> win-rate</div>
        <div class="pmb-feed__stat"><strong>{_fmt_currency(det.total_pnl_usd) if det else "—"}</strong> pnl</div>
      </div>
      <div class="pmb-feed">
        <div class="pmb-feed__name">ensemble</div>
        <div class="pmb-feed__stat"><strong>{ens.n_fired if ens else "—"}</strong> fired</div>
        <div class="pmb-feed__stat"><strong>{ens.n_filled if ens else "—"}</strong> filled · <strong>{ens.n_won if ens else "—"}</strong> won</div>
        <div class="pmb-feed__stat" style="margin-top: 4px;"><strong>{_fmt_pct(ens.win_rate) if ens else "—"}</strong> win-rate</div>
        <div class="pmb-feed__stat"><strong>{_fmt_currency(ens.total_pnl_usd) if ens else "—"}</strong> pnl</div>
      </div>
      <div class="pmb-feed">
        <div class="pmb-feed__name">api activity</div>
        <div class="pmb-feed__stat"><strong>{transcript.n_anthropic_calls:,}</strong> /v1/messages calls</div>
        <div class="pmb-feed__stat"><strong>{ens.elapsed_s:.1f}s</strong> elapsed</div>
        <div class="pmb-feed__stat" style="margin-top: 4px;">3 specialists x Sonnet meta · locked decision #5</div>
      </div>
      <div class="pmb-feed">
        <div class="pmb-feed__name">verdict</div>
        <div class="pmb-feed__stat" style="margin-top: 6px;">
          {badge(transcript.verdict or "PENDING", tone="bad" if transcript.verdict == "CUT" else "good")}
        </div>
        <div class="pmb-feed__stat" style="margin-top: 8px; color: var(--text-muted);">
          locked decision #16: kept iff uplift≥3pp, p99≤4s, $/dec≤$0.01.
          Two of three failed.
        </div>
      </div>
    </div>
    """

    # Bottom: sample rationales (the actual model outputs that hit pydantic validation).
    rationales_html = ""
    if transcript.sample_rationales:
        rationales_html += (
            '<div style="font-size: 12px; color: var(--text-secondary); margin-bottom: 6px;">'
            "Sample agent rationales (from schema-validation logs):</div>"
        )
        for r in transcript.sample_rationales[:3]:
            rationales_html += (
                f'<div style="font-family: ui-monospace, monospace; font-size: 11.5px; color: var(--text-primary); '
                f"background: var(--bg-tertiary); border: 1px solid var(--border-subtle); border-radius: 6px; "
                f'padding: 8px 10px; margin-bottom: 6px; white-space: pre-wrap;">'
                f"{html.escape(r)}"
                f"</div>"
            )

    st.markdown(
        f"""<div class="pmb-card pmb-card--dim">{title_html}{summary}{rationales_html}</div>""",
        unsafe_allow_html=True,
    )


def _render_decisions_table(rows: list[DecisionRow]) -> None:
    st.markdown(
        '<div class="pmb-card"><div class="pmb-card__title">📋 Decisions</div>',
        unsafe_allow_html=True,
    )
    if not rows:
        st.markdown(
            '<div style="color: var(--text-muted); padding: 24px 0; text-align: center;">'
            "No decisions logged yet. Files at <code>state/decisions/&lt;UTC-date&gt;.jsonl</code> populate "
            "as the deterministic strategy fires."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return
    df = pd.DataFrame(
        [
            {
                "When (UTC)": r.decision_dt_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "Side": r.side,
                "Asset": r.asset_id[:14] + "…" if len(r.asset_id) > 14 else r.asset_id,
                "Limit": r.price_limit,
                "Fill": r.fill_price if r.fill_price is not None else None,
                "Resolution": r.resolution or "—",
                "PnL": r.pnl_usd if r.pnl_usd is not None else None,
                "Composite": r.composite_pct,
                "TTL": r.ttl_s,
            }
            for r in reversed(rows)  # newest first
        ]
    )
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Limit": st.column_config.NumberColumn("Limit", format="%.4f"),
            "Fill": st.column_config.NumberColumn("Fill", format="%.4f"),
            "PnL": st.column_config.NumberColumn("PnL", format="%+.4f"),
            "Composite": st.column_config.NumberColumn("Composite (pp)", format="%+.4f"),
        },
        height=min(400, 50 + len(rows) * 36),
    )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_log_panel(state_dir: Path) -> None:
    paper_lines = tail_log(state_dir / PAPER_LOG, n_lines=60)
    capture_lines = tail_log(state_dir / CAPTURE_LOG, n_lines=60)
    paper_mtime = (
        (state_dir / PAPER_LOG).stat().st_mtime if (state_dir / PAPER_LOG).exists() else None
    )
    capture_mtime = (
        (state_dir / CAPTURE_LOG).stat().st_mtime if (state_dir / CAPTURE_LOG).exists() else None
    )

    st.markdown(
        '<div class="pmb-card"><div class="pmb-card__title">📜 Live Logs</div>',
        unsafe_allow_html=True,
    )
    tabs = st.tabs(
        [
            f"paper.log ({_log_age_label(paper_mtime)})",
            f"capture.log ({_log_age_label(capture_mtime)})",
        ]
    )
    for tab, lines in zip(tabs, (paper_lines, capture_lines), strict=True):
        with tab:
            if not lines:
                st.markdown(
                    '<div style="color: var(--text-muted); padding: 16px 0;">log file not found</div>',
                    unsafe_allow_html=True,
                )
                continue
            html_lines = "".join(
                f'<div class="pmb-log__line {_level_class(line)}">{html.escape(line)}</div>'
                for line in lines
            )
            st.markdown(f'<div class="pmb-log">{html_lines}</div>', unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _log_age_label(mtime: float | None) -> str:
    if mtime is None:
        return "missing"
    age_s = (datetime.now(tz=UTC) - datetime.fromtimestamp(mtime, tz=UTC)).total_seconds()
    return _humanize_age(age_s)


# ----------------------------- main ------------------------------------------


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
    refresh_s = st.sidebar.slider("Auto-refresh (sec)", 5, 60, 15, step=5)
    refresh_paused = st.sidebar.toggle("⏸ Pause refresh", value=False)
    state_dir = Path(st.sidebar.text_input("state/ dir", value=str(DEFAULT_STATE_DIR)))
    default_since = (datetime.now(tz=UTC) - timedelta(days=14)).strftime("%Y-%m-%d")
    since = st.sidebar.text_input("Decisions since (YYYY-MM-DD)", value=default_since)
    st.sidebar.caption(f"Reading {state_dir}/")

    # Auto-refresh via streamlit-autorefresh — preserves widget state
    # (sort order, open tab, scroll position) across reruns. Per
    # design-critique recommendation #4.
    if not refresh_paused:
        st_autorefresh(interval=refresh_s * 1000, key="pmb_autorefresh")

    # Load state.
    capture, paper = load_process_status(state_dir)
    snap = load_feeds_health(state_dir)
    rows = load_decisions(state_dir / DECISIONS_SUBDIR, since_utc_date=since or None)
    issues = _detect_incidents(capture, paper, snap, state_dir / PAPER_LOG)

    # Render in order: header → incident banner (if any) → KPIs → hero
    # PnL → system rows → decisions table → live logs → agent panel.
    # Agent panel is intentionally last because it's HISTORICAL reference,
    # not live signal (per design-critique recommendation #3).
    _render_header(refreshed_at=datetime.now(tz=UTC), since_filter=since)
    if issues:
        st.markdown(incident_banner(issues), unsafe_allow_html=True)
    _render_kpi_row(rows, paper)
    _render_pnl_chart(rows)
    _render_system_row(capture, paper, snap)
    _render_decisions_table(rows)
    _render_log_panel(state_dir)
    _render_agent_panel()


if __name__ == "__main__":
    main()
