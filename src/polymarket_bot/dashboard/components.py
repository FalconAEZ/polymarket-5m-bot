"""HTML-string components for the v2 dashboard layout.

Pure functions that take dataclasses + scalars and return well-formed
HTML fragments. The Streamlit layout in scripts/dashboard.py threads
loader output through these functions and emits the result with
st.html(). No Streamlit imports here so each component is independently
testable. Per design/dashboard-v2.md §6.

Components:
  pixel_display       — hero PnL number, 96px Pixelify Sans
  live_tape           — top-of-page scrolling event ticker
  pipeline_strip      — 6-stage execution-cycle visualization
  kpi_satellite       — small 24px-value KPI card (Fire Rate, Streak, Pace)
  bankroll_chip       — top-strip BANKROLL display
  orderbook_panel     — L2 depth (spot OR Polymarket CTF)
  tradingview_chart   — TradingView 5m candle embed iframe
  market_tabs         — top-strip BTC | ETH | ... selector
  tape_event_inline   — single event, used inside live_tape

Builder helpers:
  tape_events_from_decisions     — derives TapeEvent list from settled rows
  pipeline_stages_from_state     — derives PipelineStage list from loaders
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from polymarket_bot.dashboard.loaders import DecisionRow, FeedSnapshot, ProcessStatus
from polymarket_bot.dashboard.markets import MARKETS, MarketConfig
from polymarket_bot.dashboard.pipeline_latency import PipelineLatencies
from polymarket_bot.dashboard.polymarket_orderbook import CTFBookSnapshot, OrderbookRow
from polymarket_bot.dashboard.provider_rtt import PROVIDERS as RTT_PROVIDERS
from polymarket_bot.dashboard.rtt_loader import RttSample

Tone = Literal["good", "bad", "warn", "neutral", "muted"]
StageStatus = Literal["alive", "pending", "warn", "dead"]
HeroSize = Literal["sm", "md", "lg"]


# ============================================================================
# Hero PnL pixel display
# ============================================================================


def pixel_display(
    value: str,
    *,
    sign: str | None = None,
    glow: Tone = "good",
    size: Literal["sm", "md", "lg"] = "md",
) -> str:
    sign_html = (
        f'<span class="pmb-hero__sign" aria-hidden="true">{html.escape(sign)}</span>'
        if sign
        else ""
    )
    glow_class = f" pmb-hero--{glow}"
    size_class = f" pmb-hero--{size}"
    return (
        f'<div class="pmb-hero{glow_class}{size_class}">'
        f'{sign_html}<span class="pmb-hero__value">{html.escape(value)}</span>'
        f"</div>"
    )


# ============================================================================
# Wallet / bankroll panel — Row 1 left
# ============================================================================


def wallet_panel(
    *,
    starting_usd: float,
    current_usd: float,
    n_fired: int,
    n_filled: int,
    n_settled: int,
    n_won: int,
    win_rate: float | None,
    avg_pnl_per_filled: float | None,
    elapsed_label: str,
    mode_label: str,
    mode_tone: Tone,
) -> str:
    delta = current_usd - starting_usd
    pct = (delta / starting_usd * 100) if starting_usd > 0 else 0.0
    sign = "+" if delta >= 0 else "-"
    glow: Tone = "good" if delta > 0 else ("bad" if delta < 0 else "neutral")
    pixel = pixel_display(f"${abs(delta):,.2f}", sign=sign, glow=glow, size="sm")
    wr_str = f"{(win_rate * 100):.1f}%" if win_rate is not None else "—"
    avg_str = f"${avg_pnl_per_filled:.3f}" if avg_pnl_per_filled is not None else "—"
    return (
        '<div class="pmb-panel pmb-panel--wallet">'
        '<div class="pmb-panel__hdr">'
        '<span class="pmb-panel__title">WALLET · BANKROLL</span>'
        f'<span class="pmb-badge pmb-badge--{mode_tone}">{html.escape(mode_label)}</span>'
        '</div>'
        '<div class="pmb-panel__sub">BTC POLYMARKET · 5M UP/DOWN</div>'
        '<div class="pmb-panel__pnl-label">SESSION PNL</div>'
        f'{pixel}'
        f'<div class="pmb-panel__pnl-meta">'
        f'<span class="pmb-pill pmb-pill--{glow}">'
        f'{"▲" if delta >= 0 else "▼"} {abs(pct):.2f}%</span> '
        f'<span class="pmb-panel__time">· {html.escape(elapsed_label)} · {n_fired} TRADES</span>'
        f'</div>'
        '<div class="pmb-panel__stats">'
        f'<div class="pmb-panel__stat"><div class="pmb-panel__stat-label">TRADES</div>'
        f'<div class="pmb-panel__stat-val">{n_fired}</div></div>'
        f'<div class="pmb-panel__stat"><div class="pmb-panel__stat-label">WIN%</div>'
        f'<div class="pmb-panel__stat-val">{wr_str}</div></div>'
        f'<div class="pmb-panel__stat"><div class="pmb-panel__stat-label">AVG/TR</div>'
        f'<div class="pmb-panel__stat-val">{avg_str}</div></div>'
        '</div>'
        f'<div class="pmb-panel__foot">BANKROLL ${current_usd:,.2f} · STARTED ${starting_usd:,.0f}</div>'
        '</div>'
    )


# ============================================================================
# Live PnL pace panel — Row 1 right
# ============================================================================


def live_pnl_panel(
    *,
    pace_per_hour: float,
    pace_n: int,
    streak_glyph: str,
    streak_n: int,
    best_win_streak: int,
    worst_loss_streak: int,
    today_pnl: float | None,
    today_n: int,
    best_tier_label: str | None,
    best_tier_pnl: float | None,
) -> str:
    pace_sign = "+" if pace_per_hour >= 0 else "-"
    pace_tone: Tone = "good" if pace_per_hour > 0 else ("bad" if pace_per_hour < 0 else "muted")
    pace_pixel = pixel_display(
        f"${abs(pace_per_hour):,.2f}", sign=pace_sign, glow=pace_tone, size="md"
    )
    streak_tone: Tone = (
        "good" if streak_glyph == "▲" else ("bad" if streak_glyph == "▼" else "muted")
    )
    today_str = (
        f"{'+' if today_pnl >= 0 else '-'}${abs(today_pnl):.2f}" if today_pnl is not None else "—"
    )
    today_tone: Tone = (
        "good"
        if today_pnl is not None and today_pnl > 0
        else ("bad" if today_pnl is not None and today_pnl < 0 else "muted")
    )
    tier_html = ""
    if best_tier_label and best_tier_pnl is not None:
        tier_sign = "+" if best_tier_pnl >= 0 else "-"
        tier_html = (
            f'<div class="pmb-panel__row">'
            f'<span class="pmb-panel__row-label">BEST TIER</span>'
            f'<span class="pmb-panel__row-val">{html.escape(best_tier_label)} '
            f"{tier_sign}${abs(best_tier_pnl):.2f}</span>"
            f"</div>"
        )
    return (
        '<div class="pmb-panel pmb-panel--live">'
        '<div class="pmb-panel__hdr">'
        '<span class="pmb-panel__title">LIVE PACE · STREAK</span>'
        '<span class="pmb-badge pmb-badge--good">LIVE</span>'
        "</div>"
        '<div class="pmb-panel__pnl-label">PROFIT PACE / HR</div>'
        f"{pace_pixel}"
        f'<div class="pmb-panel__pnl-meta">'
        f"{pace_n} settled · last 60m</div>"
        '<div class="pmb-panel__rows">'
        f'<div class="pmb-panel__row">'
        f'<span class="pmb-panel__row-label">TODAY</span>'
        f'<span class="pmb-panel__row-val pmb-panel__row-val--{today_tone}">'
        f'{today_str} <span class="pmb-panel__row-sub">({today_n} settled)</span></span>'
        f"</div>"
        f'<div class="pmb-panel__row">'
        f'<span class="pmb-panel__row-label">STREAK</span>'
        f'<span class="pmb-panel__row-val pmb-panel__row-val--{streak_tone}">'
        f"{html.escape(streak_glyph)} {streak_n} "
        f'<span class="pmb-panel__row-sub">best {best_win_streak}W · worst {worst_loss_streak}L</span></span>'
        f"</div>"
        f"{tier_html}"
        "</div>"
        "</div>"
    )


# ============================================================================
# Cycle budget chip — Row 2 right of pipeline strip
# ============================================================================


def cycle_meta_chip(*, cycle_n: int, budget_label: str, elapsed_label: str) -> str:
    return (
        '<div class="pmb-cycle-meta">'
        f'<div class="pmb-cycle-meta__cycle">CYCLE #{cycle_n}</div>'
        f'<div class="pmb-cycle-meta__pair">'
        f'<span class="pmb-cycle-meta__label">BUDGET</span>'
        f'<span class="pmb-cycle-meta__val">{html.escape(budget_label)}</span>'
        f"</div>"
        f'<div class="pmb-cycle-meta__pair">'
        f'<span class="pmb-cycle-meta__label">ELAPSED</span>'
        f'<span class="pmb-cycle-meta__val pmb-cycle-meta__val--accent">{html.escape(elapsed_label)}</span>'
        f"</div>"
        "</div>"
    )


# ============================================================================
# Bankroll chip
# ============================================================================


def bankroll_chip(starting_usd: float, current_usd: float) -> str:
    delta = current_usd - starting_usd
    pct = (delta / starting_usd * 100) if starting_usd > 0 else 0.0
    sign = "+" if delta >= 0 else "-"
    tone: Tone = "good" if delta > 0 else ("bad" if delta < 0 else "muted")
    return (
        f'<span class="pmb-bankroll pmb-bankroll--{tone}">'
        f'<span class="pmb-bankroll__label">BANKROLL</span> '
        f'<span class="pmb-bankroll__value">${current_usd:,.2f}</span> '
        f'<span class="pmb-bankroll__delta">{sign}{abs(pct):.2f}%</span>'
        f'<span class="pmb-bankroll__start">started ${starting_usd:,.0f}</span>'
        f"</span>"
    )


# ============================================================================
# KPI satellite
# ============================================================================


def kpi_satellite(
    *,
    label: str,
    value: str,
    subtitle: str | None = None,
    tone: Tone = "neutral",
    glyph: str | None = None,
) -> str:
    tone_class = f" pmb-kpi--{tone}" if tone != "neutral" else ""
    sub_html = f'<div class="pmb-kpi__sub">{html.escape(subtitle)}</div>' if subtitle else ""
    glyph_html = (
        f'<span class="pmb-kpi__glyph" aria-hidden="true">{html.escape(glyph)}</span>'
        if glyph
        else ""
    )
    return (
        f'<div class="pmb-kpi{tone_class}">'
        f'<div class="pmb-kpi__label">{html.escape(label)}</div>'
        f'<div class="pmb-kpi__value">{glyph_html}{html.escape(value)}</div>'
        f"{sub_html}"
        f"</div>"
    )


# ============================================================================
# Live tape
# ============================================================================


@dataclass(frozen=True, slots=True)
class TapeEvent:
    glyph: str  # "▲" win, "▼" loss, "•" neutral / pending
    label: str  # short text — escaped before render
    tone: Tone
    age_s: float


def tape_events_from_decisions(rows: list[DecisionRow], n: int = 12) -> list[TapeEvent]:
    """Derives the latest n events from settled (or recently fired) decisions.

    Newest first in the returned list — the live_tape renderer concatenates
    the list to itself so the CSS scroll loops without seam.
    """
    settled = [r for r in rows if r.resolution is not None and r.fill_price is not None]
    settled.sort(key=lambda r: r.decision_dt_utc, reverse=True)
    now = datetime.now(tz=UTC)
    out: list[TapeEvent] = []
    for r in settled[:n]:
        won = r.resolution == r.side
        glyph = "▲" if won else "▼"
        tone: Tone = "good" if won else "bad"
        prefix = "WIN" if won else "LOSS"
        pnl = r.pnl_usd if r.pnl_usd is not None else 0.0
        sign = "+" if pnl >= 0 else "-"
        age_s = (now - r.decision_dt_utc).total_seconds()
        label = (
            f"{prefix} {sign}${abs(pnl):.2f}  ·  {r.side}  ·  win={r.p_win:.2f}"
            if r.p_win is not None
            else f"{prefix} {sign}${abs(pnl):.2f}  ·  {r.side}"
        )
        out.append(TapeEvent(glyph=glyph, label=label, tone=tone, age_s=age_s))
    return out


def tape_event_inline(ev: TapeEvent) -> str:
    return (
        f'<span class="pmb-tape__ev pmb-tape__ev--{ev.tone}">'
        f'<span class="pmb-tape__glyph">{html.escape(ev.glyph)}</span>'
        f'<span class="pmb-tape__label">{html.escape(ev.label)}</span>'
        f"</span>"
    )


def live_tape(events: list[TapeEvent]) -> str:
    if not events:
        return (
            '<div class="pmb-tape pmb-tape--empty">'
            '<div class="pmb-tape__inner">'
            '<span class="pmb-tape__ev pmb-tape__ev--muted">'
            '<span class="pmb-tape__glyph">·</span>'
            '<span class="pmb-tape__label">awaiting first settled decision</span>'
            "</span>"
            "</div></div>"
        )
    inner = "".join(tape_event_inline(e) for e in events)
    # duplicate for seamless scroll
    return '<div class="pmb-tape">' f'<div class="pmb-tape__inner">{inner}{inner}</div>' "</div>"


# ============================================================================
# Pipeline strip
# ============================================================================


@dataclass(frozen=True, slots=True)
class PipelineStage:
    name: str
    detail: str
    latency_ms: float | None
    status: StageStatus
    is_active: bool


def _fmt_latency(ms: float | None) -> str:
    if ms is None:
        return "—"
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms / 1000:.1f}s"


def _fmt_settle_wait(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds <= 0:
        return "DUE"
    mins, secs = divmod(int(seconds), 60)
    if mins > 0:
        return f"T-{mins}m{secs:02d}s"
    return f"T-{secs}s"


def pipeline_stages_from_state(
    rows: list[DecisionRow],
    feeds: list[FeedSnapshot] | None,
    capture: ProcessStatus,
    paper: ProcessStatus,
    latencies: PipelineLatencies,
) -> list[PipelineStage]:
    feeds_count = len(feeds) if feeds else 0
    feeds_healthy = sum(1 for f in feeds or [] if f.healthy)
    capture_status: StageStatus
    if not capture.alive:
        capture_status = "dead"
    elif feeds and feeds_healthy < feeds_count:
        capture_status = "warn"
    else:
        capture_status = "alive"

    strategy_name = "—"
    strategy_status: StageStatus = "pending"
    if rows:
        strategy_name = rows[-1].strategy or "spot_aware"
        strategy_status = "alive" if paper.alive else "dead"

    most_recent_unsettled = next(
        (
            r
            for r in sorted(rows, key=lambda r: r.decision_dt_utc, reverse=True)
            if r.resolution is None
        ),
        None,
    )
    sim_fill_status: StageStatus = (
        "alive" if rows and paper.alive else ("warn" if rows else "pending")
    )
    settle_status: StageStatus = "pending" if most_recent_unsettled else "alive"
    resolve_status: StageStatus = "alive" if any(r.resolution for r in rows) else "pending"
    persist_status: StageStatus = "alive" if rows else "pending"

    return [
        PipelineStage(
            name="CAPTURE",
            detail=f"{feeds_healthy}/{feeds_count} feeds" if feeds else "no feeds",
            latency_ms=latencies.capture_ms,
            status=capture_status,
            is_active=capture_status == "alive",
        ),
        PipelineStage(
            name="STRATEGY",
            detail=strategy_name,
            latency_ms=latencies.strategy_ms,
            status=strategy_status,
            is_active=False,
        ),
        PipelineStage(
            name="SIM-FILL",
            detail=f"{len([r for r in rows if r.fill_price is not None])} fills",
            latency_ms=latencies.sim_fill_ms,
            status=sim_fill_status,
            is_active=False,
        ),
        PipelineStage(
            name="SETTLE",
            detail=_fmt_settle_wait(latencies.settle_wait_s),
            latency_ms=None,
            status=settle_status,
            is_active=settle_status == "pending",
        ),
        PipelineStage(
            name="RESOLVE",
            detail="Gamma OK" if any(r.resolution for r in rows) else "—",
            latency_ms=latencies.resolve_ms,
            status=resolve_status,
            is_active=False,
        ),
        PipelineStage(
            name="PERSIST",
            detail="JSONL",
            latency_ms=latencies.persist_ms,
            status=persist_status,
            is_active=False,
        ),
    ]


def pipeline_strip(stages: list[PipelineStage]) -> str:
    cells = []
    for i, s in enumerate(stages, start=1):
        active = " pmb-stage--active" if s.is_active else ""
        latency = _fmt_latency(s.latency_ms) if s.name != "SETTLE" else s.detail
        detail = s.detail if s.name != "SETTLE" else f"{s.detail}"
        cells.append(
            f'<div class="pmb-stage pmb-stage--{s.status}{active}">'
            f'<div class="pmb-stage__num">{i:02d}</div>'
            f'<div class="pmb-stage__name">{html.escape(s.name.title())}</div>'
            f'<div class="pmb-stage__detail">{html.escape(detail)}</div>'
            f'<div class="pmb-stage__latency">{html.escape(latency)}</div>'
            f"</div>"
        )
    return f'<div class="pmb-pipeline">{"".join(cells)}</div>'


# ============================================================================
# Orderbook panel
# ============================================================================


def _format_price(p: float, *, side: Literal["spot", "ctf"]) -> str:
    if side == "spot":
        return f"${p:,.2f}"
    return f"{p:.4f}"


def _format_size(s: float, *, side: Literal["spot", "ctf"]) -> str:
    if side == "spot":
        return f"{s:.4f}"
    return f"{s:,.0f}"


def orderbook_panel(
    *,
    side: Literal["spot", "ctf"],
    rows_ask: list[OrderbookRow],
    rows_bid: list[OrderbookRow],
    mid: float | None,
    asof: datetime | None = None,
    title: str,
    subtitle: str,
    rtt_ms: float | None = None,
    offline: bool = False,
) -> str:
    if offline:
        return (
            f'<div class="pmb-book pmb-book--offline">'
            f'<div class="pmb-book__hdr">'
            f'<div class="pmb-book__title">{html.escape(title)}</div>'
            f'<div class="pmb-book__sub">{html.escape(subtitle)}</div>'
            f"</div>"
            f'<div class="pmb-book__offline">FEED OFFLINE</div>'
            f"</div>"
        )

    max_ask = max((r.size for r in rows_ask), default=1.0)
    max_bid = max((r.size for r in rows_bid), default=1.0)

    ask_rows_html = []
    # asks rendered top-to-bottom, highest first then descending toward mid
    for r in sorted(rows_ask, key=lambda x: x.price, reverse=True):
        bar_pct = (r.size / max_ask * 100) if max_ask > 0 else 0
        ask_rows_html.append(
            f'<div class="pmb-book__row pmb-book__row--ask">'
            f'<div class="pmb-book__bar pmb-book__bar--ask" style="width:{bar_pct:.0f}%"></div>'
            f'<div class="pmb-book__price">{_format_price(r.price, side=side)}</div>'
            f'<div class="pmb-book__size">{_format_size(r.size, side=side)}</div>'
            f"</div>"
        )

    mid_html = ""
    if mid is not None:
        mid_html = (
            f'<div class="pmb-book__mid">'
            f'<span class="pmb-book__mid-label">MID</span>'
            f'<span class="pmb-book__mid-value">{_format_price(mid, side=side)}</span>'
            f"</div>"
        )

    bid_rows_html = []
    # bids rendered top-to-bottom, highest first descending
    for r in sorted(rows_bid, key=lambda x: x.price, reverse=True):
        bar_pct = (r.size / max_bid * 100) if max_bid > 0 else 0
        bid_rows_html.append(
            f'<div class="pmb-book__row pmb-book__row--bid">'
            f'<div class="pmb-book__bar pmb-book__bar--bid" style="width:{bar_pct:.0f}%"></div>'
            f'<div class="pmb-book__price">{_format_price(r.price, side=side)}</div>'
            f'<div class="pmb-book__size">{_format_size(r.size, side=side)}</div>'
            f"</div>"
        )

    rtt_html = ""
    if rtt_ms is not None:
        rtt_html = f'<span class="pmb-book__rtt">{rtt_ms:.0f}ms</span>'

    return (
        f'<div class="pmb-book pmb-book--{side}">'
        f'<div class="pmb-book__hdr">'
        f'<div class="pmb-book__title">{html.escape(title)}</div>'
        f'<div class="pmb-book__sub">{html.escape(subtitle)} {rtt_html}</div>'
        f'</div>'
        f'<div class="pmb-book__asks">{"".join(ask_rows_html)}</div>'
        f"{mid_html}"
        f'<div class="pmb-book__bids">{"".join(bid_rows_html)}</div>'
        f"</div>"
    )


def orderbook_from_ctf(snap: CTFBookSnapshot | None) -> str:
    if snap is None:
        return orderbook_panel(
            side="ctf",
            rows_ask=[],
            rows_bid=[],
            mid=None,
            title="OUR MARKET",
            subtitle="Polymarket CLOB · resolving…",
            offline=True,
        )
    return orderbook_panel(
        side="ctf",
        rows_ask=list(snap.rows_ask),
        rows_bid=list(snap.rows_bid),
        mid=snap.mid,
        asof=snap.asof,
        title=f"OUR MARKET · {snap.side}",
        subtitle=f"Polymarket CLOB · {snap.market_slug}",
        rtt_ms=snap.rtt_ms,
    )


# ============================================================================
# TradingView 5m candle chart
# ============================================================================


def tradingview_chart(symbol: str = "BINANCE:BTCUSDT", interval: str = "5") -> str:
    """Returns the TradingView Advanced Chart embed snippet, dark theme.

    Embed via st.components.v1.html(tradingview_chart(), height=300). The
    operator's browser fetches the widget script directly from
    s3.tradingview.com.
    """
    safe_symbol = html.escape(symbol)
    safe_interval = html.escape(interval)
    return f"""
<div class="tradingview-widget-container" style="height:280px;width:100%">
  <div id="pmb-tv-chart" style="height:280px;width:100%"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
  <script type="text/javascript">
    new TradingView.widget({{
      "autosize": true,
      "symbol": "{safe_symbol}",
      "interval": "{safe_interval}",
      "timezone": "Etc/UTC",
      "theme": "dark",
      "style": "1",
      "locale": "en",
      "toolbar_bg": "#11100c",
      "enable_publishing": false,
      "hide_top_toolbar": true,
      "hide_legend": false,
      "save_image": false,
      "container_id": "pmb-tv-chart",
      "backgroundColor": "#08070a",
      "gridColor": "rgba(42, 38, 28, 0.5)"
    }});
  </script>
</div>
"""


# ============================================================================
# Spot orderbook panel — Binance L2 via WS, browser-side
# ============================================================================


def spot_orderbook_widget(*, container_id: str = "pmb-spot-book") -> str:
    """Returns the inline HTML+JS that streams Binance BTCUSDT L2 depth.

    Maintains a top-10-each-side snapshot from the depth20@100ms stream.
    Renders into the given container_id with the same DOM shape as
    orderbook_panel("spot") so the CSS theme applies uniformly. Embed
    via st.components.v1.html(spot_orderbook_widget(), height=420).
    """
    return f"""
<div id=\"{container_id}\" class=\"pmb-book pmb-book--spot\">
  <div class=\"pmb-book__hdr\">
    <div class=\"pmb-book__title\">BTC SPOT REFERENCE</div>
    <div class=\"pmb-book__sub\">Binance L2 · btcusdt@depth20@100ms</div>
  </div>
  <div class=\"pmb-book__asks\"></div>
  <div class=\"pmb-book__mid\">
    <span class=\"pmb-book__mid-label\">MID</span>
    <span class=\"pmb-book__mid-value\">—</span>
  </div>
  <div class=\"pmb-book__bids\"></div>
</div>
<script>
(function() {{
  const root = document.getElementById('{container_id}');
  const asksEl = root.querySelector('.pmb-book__asks');
  const bidsEl = root.querySelector('.pmb-book__bids');
  const midEl = root.querySelector('.pmb-book__mid-value');
  const fmt = (n) => '$' + Number(n).toLocaleString('en-US', {{ minimumFractionDigits: 2, maximumFractionDigits: 2 }});
  const fmtSize = (n) => Number(n).toFixed(4);
  function render(side, levels, max) {{
    const target = side === 'ask' ? asksEl : bidsEl;
    target.innerHTML = '';
    const ordered = side === 'ask'
      ? [...levels].sort((a, b) => b[0] - a[0])
      : [...levels].sort((a, b) => b[0] - a[0]);
    ordered.slice(0, 10).forEach(([price, size]) => {{
      const pct = max > 0 ? (size / max) * 100 : 0;
      const row = document.createElement('div');
      row.className = 'pmb-book__row pmb-book__row--' + side;
      row.innerHTML = '<div class=\"pmb-book__bar pmb-book__bar--' + side + '\" style=\"width:' + pct.toFixed(0) + '%\"></div>'
        + '<div class=\"pmb-book__price\">' + fmt(price) + '</div>'
        + '<div class=\"pmb-book__size\">' + fmtSize(size) + '</div>';
      target.appendChild(row);
    }});
  }}
  function connect() {{
    const ws = new WebSocket('wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms');
    ws.onmessage = (msg) => {{
      try {{
        const data = JSON.parse(msg.data);
        const bids = (data.bids || []).map(([p, s]) => [parseFloat(p), parseFloat(s)]).filter(([_, s]) => s > 0);
        const asks = (data.asks || []).map(([p, s]) => [parseFloat(p), parseFloat(s)]).filter(([_, s]) => s > 0);
        if (asks.length && bids.length) {{
          const mid = (asks[0][0] + bids[0][0]) / 2;
          midEl.textContent = fmt(mid);
        }}
        const maxAsk = asks.reduce((m, [_, s]) => Math.max(m, s), 0);
        const maxBid = bids.reduce((m, [_, s]) => Math.max(m, s), 0);
        render('ask', asks, maxAsk);
        render('bid', bids, maxBid);
      }} catch (e) {{ /* ignore parse errors */ }}
    }};
    ws.onclose = () => setTimeout(connect, 2000);
    ws.onerror = () => ws.close();
  }}
  connect();
}})();
</script>
"""


# ============================================================================
# Market tabs — top strip
# ============================================================================


def market_tabs(*, active: str = "BTC") -> str:
    pieces: list[str] = ['<div class="pmb-mtabs">']
    for m in MARKETS:
        cls = "pmb-mtabs__tab" + (" pmb-mtabs__tab--active" if m.market_id == active else "")
        pieces.append(
            f'<span class="{cls}" data-market="{html.escape(m.market_id)}">'
            f"{html.escape(m.display_name)}"
            f"</span>"
        )
    if len(MARKETS) == 1:
        pieces.append(
            '<span class="pmb-mtabs__placeholder" title="ETH coming in Phase 11.B">+ ETH soon</span>'
        )
    pieces.append("</div>")
    return "".join(pieces)


def market_for_id(market_id: str) -> MarketConfig:
    """Convenience pass-through; the dashboard imports both module-level
    helpers from one place."""
    from polymarket_bot.dashboard.markets import market_by_id

    return market_by_id(market_id)


# ============================================================================
# Provider RTT panel — server-side rendered, reads from JSONL
# ============================================================================


def _classify_rtt(ms: float | None) -> str:
    if ms is None:
        return "bad"
    if ms < 200:
        return "good"
    if ms < 600:
        return "warn"
    return "bad"


def _rtt_row_html(name: str, samples: list[RttSample], n_bars: int = 6) -> str:
    """One row: provider name on the left, 6 mini bars in the middle, last
    RTT value on the right. Bars padded with None (gray) on the left when
    history is shorter than n_bars."""
    pad: list[float | None] = [None] * max(0, n_bars - len(samples))
    rtt_values: list[float | None] = pad + [s.rtt_ms for s in samples[-n_bars:]]
    visible = [v for v in rtt_values if v is not None]
    max_ms = max(visible) if visible else 100.0
    if max_ms <= 0:
        max_ms = 100.0
    bar_html: list[str] = []
    for v in rtt_values:
        cls = _classify_rtt(v)
        height_px = 2.0 if v is None else max(2.0, min(18.0, (v / max_ms) * 18.0))
        bar_html.append(
            f'<div class="pmb-rtt__bar pmb-rtt__bar--{cls}" '
            f'style="height:{height_px:.0f}px"></div>'
        )
    last = rtt_values[-1] if rtt_values else None
    if last is None:
        last_label = "err"
        last_class = "pmb-rtt__value--err"
    else:
        last_label = f"{last:.0f}ms"
        last_class = ""
    return (
        '<div class="pmb-rtt__row">'
        f'<div class="pmb-rtt__name">{html.escape(name)}</div>'
        f'<div class="pmb-rtt__bars">{"".join(bar_html)}</div>'
        f'<div class="pmb-rtt__value {last_class}">{html.escape(last_label)}</div>'
        '</div>'
    )


def provider_rtt_panel(
    samples_by_provider: dict[str, list[RttSample]],
    *,
    last_collected_age_s: float | None = None,
) -> str:
    """Server-side rendered RTT panel. Replaces the v2.0 JS widget.

    samples_by_provider: output of load_provider_rtt(state_dir).
    last_collected_age_s: seconds since last RTT sample anywhere; renders
        in the caveat strip so operator sees collector liveness.
    """
    rows_html = [_rtt_row_html(p.name, samples_by_provider.get(p.name, [])) for p in RTT_PROVIDERS]
    if last_collected_age_s is None:
        liveness = "no collector data yet"
        live_tone = "muted"
    elif last_collected_age_s < 30:
        liveness = f"collector live · last sample {last_collected_age_s:.0f}s ago"
        live_tone = "good"
    elif last_collected_age_s < 120:
        liveness = f"collector slow · last sample {last_collected_age_s:.0f}s ago"
        live_tone = "warn"
    else:
        liveness = f"collector stale · last sample {last_collected_age_s / 60:.1f}m ago"
        live_tone = "bad"
    return (
        '<div class="pmb-rtt pmb-rtt--vps">'
        '<div class="pmb-rtt__caveat">RTT measured server-side from VPS · '
        '10s cadence</div>'
        f'<div class="pmb-rtt__liveness pmb-rtt__liveness--{live_tone}">{html.escape(liveness)}</div>'
        f'<div class="pmb-rtt__rows">{"".join(rows_html)}</div>'
        '</div>'
    )
