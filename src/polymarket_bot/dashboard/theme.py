"""Custom CSS injected into the Streamlit page — Phase 4.5 dashboard.

Per design/dashboard.md §4.3. Defines the design tokens (colors, spacing,
typography) and the .card / .kpi / .badge primitives used by every panel.
Everything here is rendered via st.markdown(unsafe_allow_html=True) at
the top of the script — Streamlit's own widgets continue to work with
their default styling, but the panel containers acquire a consistent
financial-tooling look (dense cards, subtle borders, tabular numbers).
"""

from __future__ import annotations

CSS = """
<style>
    /* Design tokens — colors */
    :root {
        --bg-primary: #0d1117;
        --bg-secondary: #161b22;
        --bg-tertiary: #1c2128;
        --bg-quaternary: #11151b;   /* dimmer than tertiary, for de-emphasized cards */
        --border-subtle: #30363d;
        --text-primary: #e6edf3;
        --text-secondary: #8b949e;
        --text-muted: #6e7681;
        --good: #1ed760;
        --warn: #f0b400;
        --bad: #ff5572;
        --accent: #58a6ff;
        /* Spacing scale — 4px baseline */
        --sp-1: 4px;
        --sp-2: 8px;
        --sp-3: 12px;
        --sp-4: 16px;
        --sp-5: 20px;
        --sp-6: 24px;
        /* Radius scale */
        --r-sm: 6px;
        --r-md: 8px;
        --r-lg: 10px;
    }

    /* Tighten Streamlit's default spacing */
    .block-container {
        padding-top: 1.6rem;
        padding-bottom: 2rem;
        max-width: 1400px;
    }

    /* Tabular numbers in metrics + dataframes — finance-grade alignment */
    [data-testid="stMetricValue"],
    .stDataFrame, .stTable, .pmb-num, .pmb-mono {
        font-variant-numeric: tabular-nums;
        font-feature-settings: "tnum";
    }

    /* KPI hero card */
    .pmb-kpi {
        background: var(--bg-secondary);
        border: 1px solid var(--border-subtle);
        border-radius: 10px;
        padding: 14px 16px;
        height: 100%;
    }
    .pmb-kpi__label {
        color: var(--text-secondary);
        font-size: 11px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .pmb-kpi__value {
        font-size: 28px;
        font-weight: 700;
        line-height: 1.2;
        letter-spacing: -0.02em;
        font-variant-numeric: tabular-nums;
    }
    .pmb-kpi__sub {
        color: var(--text-secondary);  /* WCAG-AA contrast bumped from --text-muted */
        font-size: 11px;
        margin-top: 4px;
    }
    .pmb-kpi__glyph {
        font-size: 18px;
        font-weight: 700;
        margin-right: 2px;
        line-height: 1;
        vertical-align: 1px;
    }
    .pmb-kpi--good .pmb-kpi__value { color: var(--good); }
    .pmb-kpi--bad .pmb-kpi__value { color: var(--bad); }
    .pmb-kpi--warn .pmb-kpi__value { color: var(--warn); }

    /* Section card wrapper */
    .pmb-card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-lg);
        padding: var(--sp-4);
        margin-bottom: var(--sp-3);
    }
    .pmb-card--dim {
        /* Used for reference data the operator should clearly see is
           historical, not live — e.g. Phase 3 ensemble agent activity. */
        background: var(--bg-quaternary);
        opacity: 0.92;
    }
    .pmb-card__title {
        font-size: 14px;
        font-weight: 700;
        color: var(--text-primary);
        letter-spacing: 0;
        text-transform: none;
        margin-bottom: var(--sp-3);
        display: flex;
        align-items: center;
        gap: var(--sp-2);
    }
    .pmb-card__title--muted {
        font-size: 12px;
        font-weight: 600;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }

    /* Incident banner — sticky top alert when something is wrong */
    .pmb-incident {
        background: rgba(255, 85, 114, 0.10);
        border: 1px solid rgba(255, 85, 114, 0.45);
        border-left: 3px solid var(--bad);
        border-radius: var(--r-md);
        padding: var(--sp-3) var(--sp-4);
        margin-bottom: var(--sp-4);
        display: flex;
        align-items: center;
        gap: var(--sp-3);
        font-size: 13px;
        color: var(--text-primary);
    }
    .pmb-incident__count {
        font-weight: 700;
        color: var(--bad);
        font-size: 16px;
        font-variant-numeric: tabular-nums;
    }
    .pmb-incident__list {
        color: var(--text-secondary);
        font-size: 12px;
    }

    /* Status badge */
    .pmb-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        line-height: 1.5;
    }
    .pmb-badge--good { background: rgba(30, 215, 96, 0.15); color: var(--good); border: 1px solid rgba(30, 215, 96, 0.4); }
    .pmb-badge--warn { background: rgba(240, 180, 0, 0.15); color: var(--warn); border: 1px solid rgba(240, 180, 0, 0.4); }
    .pmb-badge--bad  { background: rgba(255, 85, 114, 0.15); color: var(--bad);  border: 1px solid rgba(255, 85, 114, 0.4); }
    .pmb-badge--muted{ background: rgba(139, 148, 158, 0.10); color: var(--text-secondary); border: 1px solid rgba(139, 148, 158, 0.30); }

    /* Process / feed status row */
    .pmb-status-row {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 10px;
    }
    .pmb-feed-row {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
    }
    .pmb-feed {
        background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle);
        border-radius: 8px;
        padding: 12px 14px;
    }
    .pmb-feed__name {
        font-size: 12px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: var(--text-primary);
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .pmb-feed__stat {
        color: var(--text-secondary);
        font-size: 12px;
        font-variant-numeric: tabular-nums;
    }
    .pmb-feed__stat strong {
        color: var(--text-primary);
        font-weight: 600;
    }

    /* Log lines — color by level */
    .pmb-log {
        background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle);
        border-radius: 8px;
        padding: 10px 12px;
        max-height: 320px;
        overflow-y: auto;
        font-family: "SF Mono", "Menlo", ui-monospace, monospace;
        font-size: 11.5px;
        line-height: 1.5;
        white-space: pre-wrap;
        word-break: break-word;
    }
    .pmb-log__line { color: var(--text-secondary); }
    .pmb-log__line--info { color: var(--text-secondary); }
    .pmb-log__line--warn { color: var(--warn); }
    .pmb-log__line--err  { color: var(--bad); font-weight: 500; }

    /* Header strip */
    .pmb-header {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        margin-bottom: 18px;
    }
    .pmb-header__title {
        font-size: 22px;
        font-weight: 700;
        letter-spacing: -0.01em;
        color: var(--text-primary);
        margin: 0;
    }
    .pmb-header__sub {
        color: var(--text-muted);
        font-size: 12px;
    }

    /* Hide Streamlit chrome that doesn't fit the financial-tool aesthetic */
    [data-testid="stToolbar"] { visibility: hidden; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
</style>
"""


def inject() -> str:
    """Returns the CSS block to be passed to st.markdown(..., unsafe_allow_html=True)."""
    return CSS


def kpi_card(
    *,
    label: str,
    value: str,
    subtitle: str | None = None,
    tone: str = "neutral",
    glyph: str | None = None,
) -> str:
    """Render a single KPI hero card. tone in {neutral, good, bad, warn}.

    glyph is an optional small character prepended to the value (e.g. ▲/▼
    for non-color-only signal on PnL). Per design-critique recommendation
    #5 (color-blind accessibility).
    """
    tone_class = "" if tone == "neutral" else f" pmb-kpi--{tone}"
    sub = f'<div class="pmb-kpi__sub">{subtitle}</div>' if subtitle else ""
    glyph_html = f'<span class="pmb-kpi__glyph" aria-hidden="true">{glyph}</span> ' if glyph else ""
    return (
        f'<div class="pmb-kpi{tone_class}">'
        f'<div class="pmb-kpi__label">{label}</div>'
        f'<div class="pmb-kpi__value">{glyph_html}{value}</div>'
        f"{sub}"
        f"</div>"
    )


def badge(text: str, tone: str = "muted") -> str:
    """Render a small uppercase badge. tone in {good, warn, bad, muted}."""
    return f'<span class="pmb-badge pmb-badge--{tone}">{text}</span>'


def incident_banner(issues: list[str]) -> str:
    """Render the sticky top alert strip when one+ system signals are red.

    issues is a list of short human-readable strings like "paper process dead"
    or "binance feed unhealthy". When empty, returns "" so the caller can
    cheaply omit the banner.
    """
    if not issues:
        return ""
    n = len(issues)
    items = " · ".join(issues[:5])
    suffix = f" (+{n - 5} more)" if n > 5 else ""
    return (
        f'<div class="pmb-incident">'
        f'<span class="pmb-incident__count">⚠ {n}</span>'
        f"<span><strong>Issues detected.</strong> "
        f'<span class="pmb-incident__list">{items}{suffix}</span></span>'
        f"</div>"
    )
