"""Custom CSS injected into the Streamlit page — Phase 4.5 dashboard.

Per design/dashboard.md §4.3. Defines design tokens (colors, spacing,
typography) and the .pmb-* primitives used by every panel. Rendered via
st.html() at the top of the script so Streamlit's markdown processor
doesn't escape the layout. The financial-tooling aesthetic targets the
look-and-feel of Linear / Stripe Dashboard / TradingView's dark theme:
dense, calm, numbers-forward, no chrome.
"""

from __future__ import annotations

CSS = """
<style>
    @import url("https://rsms.me/inter/inter.css");
    @import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap");

    /* Design tokens — colors */
    :root {
        --bg-primary: #08090c;
        --bg-secondary: #11141a;
        --bg-tertiary: #161a22;
        --bg-quaternary: #0d1015;     /* dimmer than tertiary, for de-emphasized cards */
        --bg-hover: #1c2230;
        --border-subtle: #1f242e;
        --border-strong: #2a3140;
        --text-primary: #e6edf3;
        --text-secondary: #9ba6b3;
        --text-muted: #6b7480;
        --good: #2ee08c;
        --good-glow: rgba(46, 224, 140, 0.18);
        --warn: #ffb454;
        --warn-glow: rgba(255, 180, 84, 0.18);
        --bad: #ff6f86;
        --bad-glow: rgba(255, 111, 134, 0.18);
        --accent: #6ea8ff;
        /* Spacing scale — 4px baseline */
        --sp-1: 4px;
        --sp-2: 8px;
        --sp-3: 12px;
        --sp-4: 16px;
        --sp-5: 20px;
        --sp-6: 24px;
        --sp-7: 32px;
        /* Radius scale */
        --r-sm: 6px;
        --r-md: 10px;
        --r-lg: 14px;
        --r-xl: 18px;
        /* Shadows */
        --shadow-card: 0 1px 0 rgba(255, 255, 255, 0.02) inset, 0 12px 24px -16px rgba(0, 0, 0, 0.35);
        --shadow-card-strong: 0 1px 0 rgba(255, 255, 255, 0.03) inset, 0 24px 48px -24px rgba(0, 0, 0, 0.5);
    }

    /* Global typography + page background */
    html, body, [class*="css"], .stApp, .main {
        font-family: "Inter var", "Inter", -apple-system, BlinkMacSystemFont,
                     "Segoe UI", Helvetica, Arial, sans-serif !important;
        font-feature-settings: "ss01", "cv11";  /* Inter stylistic alts */
    }
    .stApp {
        background:
            radial-gradient(1200px 600px at 10% -10%, rgba(46, 224, 140, 0.06), transparent 60%),
            radial-gradient(900px 500px at 110% 0%, rgba(110, 168, 255, 0.05), transparent 55%),
            var(--bg-primary) !important;
    }

    /* Tighten Streamlit's default block container — terminal density */
    .block-container {
        padding-top: 0.8rem;
        padding-bottom: 1.2rem;
        padding-left: 1.5rem;
        padding-right: 1.5rem;
        max-width: 100% !important;
    }
    /* Streamlit column gap tighter */
    [data-testid="stHorizontalBlock"] {
        gap: 12px !important;
    }
    [data-testid="stVerticalBlock"] {
        gap: 8px !important;
    }

    /* Live pulse keyframe */
    @keyframes pmb-pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50%      { opacity: 0.55; transform: scale(1.4); }
    }
    @keyframes pmb-fade-in {
        from { opacity: 0; transform: translateY(2px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    .pmb-live-dot {
        display: inline-block;
        width: 7px; height: 7px;
        border-radius: 50%;
        background: var(--good);
        margin-right: 6px;
        animation: pmb-pulse 1.6s ease-in-out infinite;
        box-shadow: 0 0 8px rgba(46, 224, 140, 0.6);
        vertical-align: middle;
    }
    .pmb-card, .pmb-kpi, .pmb-feed {
        animation: pmb-fade-in 240ms ease-out;
    }

    /* Tabular numbers in metrics + dataframes — finance-grade alignment */
    [data-testid="stMetricValue"],
    .stDataFrame, .stTable, .pmb-num, .pmb-mono,
    .pmb-kpi__value, .pmb-feed__stat, .pmb-feed {
        font-variant-numeric: tabular-nums;
        font-feature-settings: "tnum";
    }

    /* ================== KPI HERO CARDS (compact terminal) ================== */
    .pmb-kpi {
        position: relative;
        background:
            linear-gradient(180deg, rgba(255, 255, 255, 0.025), transparent 40%),
            var(--bg-secondary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-md);
        padding: 10px 14px;
        height: 100%;
        box-shadow: var(--shadow-card);
        transition: border-color 160ms ease, transform 160ms ease, background 200ms ease;
    }
    .pmb-kpi:hover {
        border-color: var(--border-strong);
    }
    .pmb-kpi__label {
        color: var(--text-secondary);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .pmb-kpi__value {
        font-size: 22px;
        font-weight: 600;
        line-height: 1.1;
        letter-spacing: -0.02em;
        color: var(--text-primary);
        display: flex;
        align-items: baseline;
        gap: 6px;
        transition: color 200ms ease;
    }
    .pmb-kpi__sub {
        color: var(--text-secondary);
        font-size: 10.5px;
        margin-top: 4px;
        font-weight: 500;
    }
    .pmb-kpi__glyph {
        font-size: 14px;
        line-height: 1;
        margin-right: 0;
        opacity: 0.95;
    }
    .pmb-kpi--good {
        background:
            linear-gradient(180deg, var(--good-glow), transparent 60%),
            var(--bg-secondary);
    }
    .pmb-kpi--good .pmb-kpi__value { color: var(--good); }
    .pmb-kpi--bad {
        background:
            linear-gradient(180deg, var(--bad-glow), transparent 60%),
            var(--bg-secondary);
    }
    .pmb-kpi--bad .pmb-kpi__value { color: var(--bad); }
    .pmb-kpi--warn {
        background:
            linear-gradient(180deg, var(--warn-glow), transparent 60%),
            var(--bg-secondary);
    }
    .pmb-kpi--warn .pmb-kpi__value { color: var(--warn); }

    /* ================== SECTION CARDS (compact) ================== */
    .pmb-card {
        background: var(--bg-secondary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-md);
        padding: 12px 14px;
        margin-bottom: 8px;
        box-shadow: var(--shadow-card);
    }
    .pmb-card--dim {
        background: var(--bg-quaternary);
        border-color: rgba(31, 36, 46, 0.5);
        opacity: 0.96;
    }
    .pmb-card__title {
        font-size: 11px;
        font-weight: 700;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .pmb-card__title--muted {
        font-size: 10.5px;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }

    /* Section header (used outside .pmb-card for widget panels) */
    .pmb-section {
        margin: 8px 0 6px 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .pmb-section .pmb-card__title {
        margin-bottom: 0;
    }

    /* ================== INCIDENT BANNER ================== */
    .pmb-incident {
        background:
            linear-gradient(180deg, rgba(255, 111, 134, 0.10), transparent 80%),
            var(--bg-secondary);
        border: 1px solid rgba(255, 111, 134, 0.40);
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

    /* ================== BADGES & PILLS ================== */
    .pmb-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 999px;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        line-height: 1.5;
    }
    .pmb-badge--good { background: rgba(46, 224, 140, 0.12); color: var(--good); border: 1px solid rgba(46, 224, 140, 0.35); }
    .pmb-badge--warn { background: rgba(255, 180, 84, 0.12); color: var(--warn); border: 1px solid rgba(255, 180, 84, 0.35); }
    .pmb-badge--bad  { background: rgba(255, 111, 134, 0.12); color: var(--bad);  border: 1px solid rgba(255, 111, 134, 0.35); }
    .pmb-badge--muted{ background: rgba(155, 166, 179, 0.08); color: var(--text-secondary); border: 1px solid rgba(155, 166, 179, 0.25); }

    /* ================== HEADER (compact terminal bar) ================== */
    .pmb-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 0 10px 0;
        margin-bottom: 10px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .pmb-header__left {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .pmb-header__title {
        font-size: 15px;
        font-weight: 600;
        letter-spacing: -0.005em;
        color: var(--text-primary);
        margin: 0;
        line-height: 1.2;
    }
    .pmb-header__sub {
        color: var(--text-muted);
        font-size: 11px;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
    }

    /* ================== PROCESS / FEED ROWS (compact stack) ================== */
    .pmb-feed-row {
        display: grid;
        grid-template-columns: 1fr;
        gap: 6px;
    }
    .pmb-feed-row--4col {
        grid-template-columns: repeat(4, 1fr);
        gap: 8px;
        margin-bottom: 8px;
    }
    .pmb-feed {
        background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 8px 10px;
        transition: border-color 120ms ease;
    }
    .pmb-feed:hover { border-color: var(--border-strong); }
    .pmb-feed__name {
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        color: var(--text-primary);
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .pmb-feed__stat {
        color: var(--text-secondary);
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        line-height: 1.5;
    }
    .pmb-feed__stat strong {
        color: var(--text-primary);
        font-weight: 600;
    }
    .pmb-feed__err {
        color: var(--text-muted);
        font-size: 10px;
        margin-top: 2px;
        font-variant-numeric: tabular-nums;
    }

    /* Process row */
    .pmb-proc-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 6px 0;
        border-bottom: 1px solid var(--border-subtle);
    }
    .pmb-proc-row:last-child { border-bottom: none; padding-bottom: 0; }
    .pmb-proc-row:first-child { padding-top: 0; }
    .pmb-proc-row__name {
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-size: 11px;
        color: var(--text-primary);
    }
    .pmb-proc-row__sub {
        color: var(--text-secondary);
        font-size: 10px;
        margin-top: 2px;
        font-variant-numeric: tabular-nums;
    }

    /* ================== EMPTY STATES ================== */
    .pmb-empty {
        color: var(--text-secondary);
        padding: var(--sp-6) 0;
        text-align: center;
        font-size: 12.5px;
        line-height: 1.7;
    }
    .pmb-empty code {
        background: var(--bg-tertiary);
        padding: 1px 6px;
        border-radius: 4px;
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 11px;
        color: var(--text-primary);
    }

    /* ================== LIVE LOG (terminal-tight) ================== */
    .pmb-log {
        background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 8px 10px;
        max-height: 540px;
        overflow-y: auto;
        font-family: "JetBrains Mono", "SF Mono", "Menlo", ui-monospace, monospace;
        font-size: 10.5px;
        line-height: 1.55;
        white-space: pre-wrap;
        word-break: break-word;
    }
    .pmb-log__line { color: var(--text-secondary); padding: 1px 4px; border-radius: 3px; }
    .pmb-log__line--info { color: var(--text-secondary); }
    .pmb-log__line--warn { color: var(--warn); background: rgba(255, 180, 84, 0.06); }
    .pmb-log__line--err  { color: var(--bad); background: rgba(255, 111, 134, 0.08); font-weight: 500; }
    /* Scrollbar styling */
    .pmb-log::-webkit-scrollbar { width: 8px; }
    .pmb-log::-webkit-scrollbar-track { background: var(--bg-tertiary); }
    .pmb-log::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 4px; }

    /* ================== RATIONALE ================== */
    .pmb-rationale__heading {
        font-size: 11.5px;
        color: var(--text-secondary);
        margin: var(--sp-3) 0 var(--sp-2) 0;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-weight: 600;
    }
    .pmb-rationale {
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 11.5px;
        color: var(--text-primary);
        background: var(--bg-tertiary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: var(--sp-3) var(--sp-3);
        margin-bottom: var(--sp-2);
        white-space: pre-wrap;
        line-height: 1.6;
    }

    /* ================== STREAMLIT WIDGET POLISH ================== */
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: var(--bg-secondary);
        border-right: 1px solid var(--border-subtle);
    }
    [data-testid="stSidebar"] h1 {
        font-size: 14px;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        color: var(--text-secondary);
        font-weight: 600;
    }
    /* Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: var(--text-secondary) !important;
        font-size: 12px !important;
        font-weight: 500 !important;
        padding: 8px 14px !important;
        border-radius: 0 !important;
        border-bottom: 2px solid transparent !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--text-primary) !important;
        border-bottom-color: var(--good) !important;
    }
    /* Slider primaryColor accent */
    .stSlider [data-baseweb="slider"] {
        accent-color: var(--good);
    }
    /* Dataframe — refined borders */
    .stDataFrame, [data-testid="stDataFrame"] {
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--r-md) !important;
        overflow: hidden;
    }

    /* Native st.container(border=True, key=...) — match pmb-card aesthetic */
    .st-key-pmb-main-panel,
    .st-key-pmb-log-panel {
        background: var(--bg-secondary) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--r-md) !important;
        box-shadow: var(--shadow-card);
        padding: 12px 14px !important;
    }
    .st-key-pmb-main-panel .pmb-section:first-child,
    .st-key-pmb-log-panel .pmb-section:first-child {
        margin-top: 0;
    }
    /* Hide Streamlit chrome that doesn't fit the financial-tool aesthetic */
    [data-testid="stToolbar"] { visibility: hidden; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    [data-testid="stDecoration"] { display: none; }
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
    glyph_html = f'<span class="pmb-kpi__glyph" aria-hidden="true">{glyph}</span>' if glyph else ""
    return (
        f'<div class="pmb-kpi{tone_class}">'
        f'<div class="pmb-kpi__label">{label}</div>'
        f'<div class="pmb-kpi__value">{glyph_html}<span>{value}</span></div>'
        f"{sub}"
        f"</div>"
    )


def badge(text: str, tone: str = "muted") -> str:
    """Render a small uppercase badge. tone in {good, warn, bad, muted}."""
    return f'<span class="pmb-badge pmb-badge--{tone}">{text}</span>'


def incident_banner(issues: list[str]) -> str:
    """Render the sticky top alert strip when one+ system signals are red."""
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
