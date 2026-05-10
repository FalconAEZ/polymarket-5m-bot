"""v2 dark-terminal CSS for the Streamlit operations dashboard.

Defines the design tokens (colours, typography, spacing, animation
keyframes) and the .pmb-* primitives consumed by both v1 and v2 layouts.
Bloomberg-terminal aesthetic — warm near-black surfaces, cream text,
amber/green/red status palette, JetBrains Mono body, Pixelify Sans for
the v2 hero PnL display only. Per design/dashboard-v2.md §4.

Compatibility shims (kpi_card, badge, incident_banner) preserve the v1
public surface so scripts/dashboard.py can keep its trip-wire panel and
incident banner code unchanged across the feature-flag transition.
"""

from __future__ import annotations

CSS = """
<style>
    @import url("https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Pixelify+Sans:wght@400;500;600;700&display=swap");

    /* ===== Design tokens — Dark Terminal ============================= */
    :root {
        --bg-page:       #08070a;
        --bg-panel:      #11100c;
        --bg-panel-hi:   #1a1812;
        --bg-inset:      #0c0b08;

        --border-subtle: #2a261c;
        --border-strong: #3d3725;
        --border-amber:  #6b4d18;

        --text-primary:   #f5edd6;
        --text-secondary: #9c8d6b;
        --text-muted:     #5a4f3a;

        --good: #8aff7a;
        --good-glow: rgba(138, 255, 122, 0.18);
        --bad:  #ff5c5c;
        --bad-glow: rgba(255, 92, 92, 0.20);
        --warn: #ffb84a;
        --warn-glow: rgba(255, 184, 74, 0.20);
        --accent-cyan:    #6effff;
        --accent-magenta: #ff6ec7;

        --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
        --sp-5: 20px; --sp-6: 24px; --sp-7: 32px; --sp-8: 48px;

        --r-none: 0px;
        --r-sm:   3px;
        --r-md:   6px;
    }

    html, body, [class*="css"], .stApp, .main {
        font-family: "JetBrains Mono", "SF Mono", "Menlo", ui-monospace, monospace !important;
        font-feature-settings: "tnum";
        -webkit-font-smoothing: antialiased;
    }
    .stApp {
        background:
            radial-gradient(1200px 600px at 10% -10%, rgba(255, 184, 74, 0.04), transparent 60%),
            radial-gradient(900px 500px at 110% 0%, rgba(138, 255, 122, 0.03), transparent 55%),
            var(--bg-page) !important;
    }

    .block-container {
        padding-top: 0.6rem;
        padding-bottom: 1.0rem;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
        max-width: 100% !important;
    }
    [data-testid="stHorizontalBlock"] { gap: 10px !important; }
    [data-testid="stVerticalBlock"]   { gap: 6px !important; }

    /* ===== Animations =============================================== */
    @keyframes pmb-pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50%      { opacity: 0.55; transform: scale(1.4); }
    }
    @keyframes pmb-fade-in {
        from { opacity: 0; transform: translateY(-4px); }
        to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes pmb-tape-scroll {
        from { transform: translateX(0); }
        to   { transform: translateX(-50%); }
    }
    @keyframes pmb-stage-glow {
        0%   { box-shadow: 0 0 0 0 var(--good-glow); }
        50%  { box-shadow: 0 0 12px 2px var(--good-glow); }
        100% { box-shadow: 0 0 0 0 transparent; }
    }
    @keyframes pmb-hero-shimmer {
        0%   { background-position: 0% 50%; }
        100% { background-position: 200% 50%; }
    }

    .pmb-live-dot {
        display: inline-block;
        width: 8px; height: 8px;
        border-radius: 50%;
        background: var(--good);
        margin-right: 8px;
        animation: pmb-pulse 1.6s ease-in-out infinite;
        box-shadow: 0 0 8px rgba(138, 255, 122, 0.6);
        vertical-align: middle;
    }

    /* ===== Top strip ================================================ */
    .pmb-topstrip {
        display: flex;
        align-items: center;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 8px 24px;
        padding: 8px 0 10px 0;
        margin-bottom: 8px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .pmb-topstrip__left,
    .pmb-topstrip__right {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 6px 14px;
    }
    .pmb-topstrip__brand {
        font-size: 13px;
        font-weight: 700;
        letter-spacing: 0.04em;
        color: var(--text-primary);
        text-transform: uppercase;
    }
    .pmb-topstrip__sub {
        color: var(--text-muted);
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        font-variant-numeric: tabular-nums;
    }
    .pmb-clock {
        font-size: 12px;
        color: var(--text-secondary);
        font-variant-numeric: tabular-nums;
        letter-spacing: 0.05em;
    }

    /* ===== Bankroll chip ============================================ */
    .pmb-bankroll {
        display: inline-flex;
        align-items: baseline;
        gap: 8px;
        padding: 4px 10px;
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        background: var(--bg-panel);
        font-size: 11px;
    }
    .pmb-bankroll__label {
        color: var(--text-muted);
        font-size: 9px;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        font-weight: 600;
    }
    .pmb-bankroll__value {
        color: var(--text-primary);
        font-weight: 600;
        font-variant-numeric: tabular-nums;
    }
    .pmb-bankroll__delta { font-weight: 600; font-variant-numeric: tabular-nums; }
    .pmb-bankroll__start {
        color: var(--text-muted);
        font-size: 9px;
        margin-left: 4px;
    }
    .pmb-bankroll--good .pmb-bankroll__delta { color: var(--good); }
    .pmb-bankroll--bad  .pmb-bankroll__delta { color: var(--bad); }
    .pmb-bankroll--muted .pmb-bankroll__delta { color: var(--text-secondary); }

    /* ===== Market tabs ============================================= */
    .pmb-mtabs {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 2px;
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
    }
    .pmb-mtabs__tab {
        padding: 4px 12px;
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-secondary);
        cursor: default;
        border-radius: var(--r-sm);
    }
    .pmb-mtabs__tab--active {
        background: var(--bg-panel-hi);
        color: var(--warn);
        box-shadow: 0 0 0 1px var(--border-amber) inset;
    }
    .pmb-mtabs__placeholder {
        padding: 4px 10px;
        font-size: 10px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        font-style: italic;
    }

    /* ===== Live tape ================================================ */
    .pmb-tape {
        height: 28px;
        overflow: hidden;
        border-top: 1px solid var(--border-subtle);
        border-bottom: 1px solid var(--border-subtle);
        background: var(--bg-inset);
        margin-bottom: 8px;
        position: relative;
    }
    .pmb-tape__inner {
        display: flex;
        align-items: center;
        gap: 32px;
        white-space: nowrap;
        animation: pmb-tape-scroll 60s linear infinite;
        height: 100%;
        padding-left: 16px;
        width: max-content;
    }
    .pmb-tape:hover .pmb-tape__inner { animation-play-state: paused; }
    .pmb-tape__ev {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        font-size: 11px;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
    }
    .pmb-tape__ev--good { color: var(--good); }
    .pmb-tape__ev--bad  { color: var(--bad); }
    .pmb-tape__ev--warn { color: var(--warn); }
    .pmb-tape__ev--muted { color: var(--text-muted); }
    .pmb-tape__glyph {
        display: inline-block;
        width: 12px;
        text-align: center;
    }
    .pmb-tape--empty .pmb-tape__inner {
        animation: none;
        padding-left: 24px;
    }

    /* ===== Hero PnL — pixel display, three sizes ================== */
    .pmb-hero {
        display: flex;
        align-items: baseline;
        gap: 4px;
        font-family: "Pixelify Sans", "JetBrains Mono", monospace;
        font-weight: 600;
        line-height: 1;
        letter-spacing: 0.02em;
        font-variant-numeric: tabular-nums;
    }
    /* small — for inset panel use (wallet/live) */
    .pmb-hero--sm { font-size: 38px; padding: 4px 0 2px; }
    .pmb-hero--sm .pmb-hero__sign { font-size: 22px; opacity: 0.85; margin-right: 2px; }
    /* medium — secondary heroes (live PnL pace) */
    .pmb-hero--md { font-size: 52px; padding: 4px 0; }
    .pmb-hero--md .pmb-hero__sign { font-size: 30px; opacity: 0.85; margin-right: 3px; }
    /* large — reserved (currently unused; was the v2.0 96px hero) */
    .pmb-hero--lg { font-size: 84px; padding: 8px 0; }
    .pmb-hero--lg .pmb-hero__sign { font-size: 48px; opacity: 0.85; margin-right: 4px; }
    .pmb-hero__value { display: inline-block; }
    .pmb-hero--good { color: var(--good); text-shadow: 0 0 18px rgba(138, 255, 122, 0.20); }
    .pmb-hero--bad  { color: var(--bad);  text-shadow: 0 0 18px rgba(255, 92, 92, 0.22); }
    .pmb-hero--warn { color: var(--warn); text-shadow: 0 0 18px rgba(255, 184, 74, 0.22); }
    .pmb-hero--neutral, .pmb-hero--muted { color: var(--text-primary); }

    /* ===== Wallet / Live panels ================================== */
    .pmb-panel {
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 10px 12px;
        height: 100%;
        display: flex;
        flex-direction: column;
        gap: 4px;
    }
    .pmb-panel__hdr {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 2px;
    }
    .pmb-panel__title {
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.10em;
        text-transform: uppercase;
        color: var(--text-secondary);
    }
    .pmb-panel__sub {
        font-size: 9px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 4px;
    }
    .pmb-panel__pnl-label {
        font-size: 9px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.10em;
        margin-top: 4px;
    }
    .pmb-panel__pnl-meta {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 10px;
        color: var(--text-muted);
        margin-bottom: 6px;
    }
    .pmb-panel__time {
        color: var(--text-muted);
        font-size: 10px;
        letter-spacing: 0.04em;
    }
    .pmb-panel__stats {
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        gap: 6px;
        margin-top: auto;
        padding-top: 8px;
        border-top: 1px solid var(--border-subtle);
    }
    .pmb-panel__stat-label {
        font-size: 8.5px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-weight: 600;
    }
    .pmb-panel__stat-val {
        font-size: 14px;
        font-weight: 600;
        color: var(--text-primary);
        font-variant-numeric: tabular-nums;
    }
    .pmb-panel__foot {
        font-size: 9px;
        color: var(--text-muted);
        margin-top: 4px;
        font-variant-numeric: tabular-nums;
    }
    .pmb-panel__rows {
        display: flex;
        flex-direction: column;
        gap: 4px;
        margin-top: auto;
        padding-top: 6px;
        border-top: 1px solid var(--border-subtle);
    }
    .pmb-panel__row {
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        padding: 2px 0;
    }
    .pmb-panel__row-label {
        font-size: 9px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-weight: 600;
        flex-shrink: 0;
    }
    .pmb-panel__row-val {
        font-size: 12px;
        color: var(--text-primary);
        font-variant-numeric: tabular-nums;
        text-align: right;
    }
    .pmb-panel__row-val--good { color: var(--good); }
    .pmb-panel__row-val--bad  { color: var(--bad); }
    .pmb-panel__row-val--warn { color: var(--warn); }
    .pmb-panel__row-val--muted { color: var(--text-muted); }
    .pmb-panel__row-sub {
        color: var(--text-muted);
        font-size: 9.5px;
        margin-left: 4px;
    }
    .pmb-panel--wallet { /* default surface */ }
    .pmb-panel--live   { /* default surface */ }

    /* ===== Cycle meta chip (BUDGET / ELAPSED) ===================== */
    .pmb-cycle-meta {
        display: flex;
        align-items: center;
        gap: 16px;
        padding: 6px 12px;
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        font-variant-numeric: tabular-nums;
    }
    .pmb-cycle-meta__cycle {
        font-size: 10px;
        font-weight: 700;
        color: var(--warn);
        background: rgba(255, 184, 74, 0.08);
        padding: 3px 8px;
        border-radius: var(--r-sm);
        letter-spacing: 0.10em;
    }
    .pmb-cycle-meta__pair {
        display: flex;
        flex-direction: column;
    }
    .pmb-cycle-meta__label {
        font-size: 8px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-weight: 600;
    }
    .pmb-cycle-meta__val {
        font-size: 13px;
        font-weight: 600;
        color: var(--text-primary);
    }
    .pmb-cycle-meta__val--accent { color: var(--warn); }

    /* ===== Cycle row wrapper ===================================== */
    .pmb-cycle-row {
        display: flex;
        align-items: stretch;
        gap: 8px;
        margin: 6px 0;
    }
    .pmb-cycle-row__pipeline { flex: 1; }
    .pmb-cycle-row__meta { flex-shrink: 0; }

    /* ===== KPI satellites =========================================== */
    .pmb-kpi {
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 10px 12px;
        height: 100%;
        min-height: 90px;
        animation: pmb-fade-in 240ms ease-out;
    }
    .pmb-kpi__label {
        color: var(--text-muted);
        font-size: 9px;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-weight: 600;
        margin-bottom: 2px;
    }
    .pmb-kpi__value {
        font-size: 24px;
        font-weight: 600;
        line-height: 1.1;
        color: var(--text-primary);
        font-variant-numeric: tabular-nums;
        letter-spacing: -0.01em;
        display: flex;
        align-items: baseline;
        gap: 4px;
    }
    .pmb-kpi__sub {
        color: var(--text-secondary);
        font-size: 10px;
        margin-top: 4px;
        font-variant-numeric: tabular-nums;
    }
    .pmb-kpi__glyph { font-size: 14px; opacity: 0.95; }
    .pmb-kpi--good { border-color: rgba(138, 255, 122, 0.32); }
    .pmb-kpi--good .pmb-kpi__value { color: var(--good); }
    .pmb-kpi--bad  { border-color: rgba(255, 92, 92, 0.32); }
    .pmb-kpi--bad .pmb-kpi__value { color: var(--bad); }
    .pmb-kpi--warn { border-color: rgba(255, 184, 74, 0.32); }
    .pmb-kpi--warn .pmb-kpi__value { color: var(--warn); }
    .pmb-kpi--muted .pmb-kpi__value { color: var(--text-secondary); }

    /* ===== Pipeline strip — numbered Bloomberg-style ============== */
    .pmb-pipeline {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 6px;
        flex: 1;
    }
    .pmb-stage {
        display: grid;
        grid-template-columns: auto 1fr;
        grid-template-rows: auto auto auto;
        column-gap: 8px;
        row-gap: 2px;
        padding: 8px 10px;
        position: relative;
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        transition: background 200ms ease;
    }
    .pmb-stage__num {
        grid-row: 1 / 4;
        grid-column: 1;
        font-family: "JetBrains Mono", monospace;
        font-size: 22px;
        font-weight: 700;
        line-height: 1;
        color: var(--text-muted);
        align-self: start;
        padding-top: 2px;
        font-variant-numeric: tabular-nums;
    }
    .pmb-stage__name {
        grid-row: 1;
        grid-column: 2;
        font-size: 10.5px;
        font-weight: 700;
        letter-spacing: 0.06em;
        color: var(--text-primary);
        text-transform: uppercase;
    }
    .pmb-stage__detail {
        grid-row: 2;
        grid-column: 2;
        font-size: 9.5px;
        color: var(--text-muted);
        font-variant-numeric: tabular-nums;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }
    .pmb-stage__latency {
        grid-row: 3;
        grid-column: 1 / 3;
        font-size: 16px;
        font-weight: 600;
        line-height: 1.1;
        color: var(--text-primary);
        font-variant-numeric: tabular-nums;
        margin-top: 2px;
    }
    .pmb-stage--alive .pmb-stage__num { color: var(--good); }
    .pmb-stage--alive { border-color: rgba(138, 255, 122, 0.30); }
    .pmb-stage--pending .pmb-stage__num { color: var(--warn); }
    .pmb-stage--pending {
        border-color: rgba(255, 184, 74, 0.40);
        background:
            linear-gradient(180deg, rgba(255, 184, 74, 0.06), transparent 60%),
            var(--bg-panel);
    }
    .pmb-stage--pending .pmb-stage__latency { color: var(--warn); }
    .pmb-stage--warn .pmb-stage__num { color: var(--warn); }
    .pmb-stage--warn { border-color: rgba(255, 184, 74, 0.30); }
    .pmb-stage--dead .pmb-stage__num { color: var(--bad); }
    .pmb-stage--dead { border-color: rgba(255, 92, 92, 0.30); }
    .pmb-stage--active { animation: pmb-stage-glow 1.2s ease-out; }

    /* ===== Orderbook panel ========================================== */
    .pmb-book {
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 10px 12px;
        font-variant-numeric: tabular-nums;
        font-size: 11px;
    }
    .pmb-book__hdr { margin-bottom: 8px; }
    .pmb-book__title {
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--text-primary);
    }
    .pmb-book__sub {
        font-size: 9px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-top: 2px;
    }
    .pmb-book__rtt {
        background: var(--bg-inset);
        padding: 1px 6px;
        border-radius: var(--r-sm);
        margin-left: 8px;
        color: var(--text-secondary);
    }
    .pmb-book__row {
        position: relative;
        display: grid;
        grid-template-columns: 1fr auto;
        gap: 8px;
        padding: 2px 4px;
        font-size: 10.5px;
    }
    .pmb-book__bar {
        position: absolute;
        top: 0; bottom: 0;
        height: 100%;
        opacity: 0.18;
        z-index: 0;
        border-radius: 2px;
    }
    .pmb-book__bar--ask { left: 0; background: var(--bad); }
    .pmb-book__bar--bid { left: 0; background: var(--good); }
    .pmb-book__price {
        position: relative;
        z-index: 1;
        color: var(--text-primary);
    }
    .pmb-book__row--ask .pmb-book__price { color: var(--bad); }
    .pmb-book__row--bid .pmb-book__price { color: var(--good); }
    .pmb-book__size {
        position: relative;
        z-index: 1;
        color: var(--text-secondary);
        text-align: right;
    }
    .pmb-book__mid {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        padding: 6px 4px;
        margin: 4px 0;
        border-top: 1px dashed var(--border-strong);
        border-bottom: 1px dashed var(--border-strong);
    }
    .pmb-book__mid-label {
        font-size: 9px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.10em;
        font-weight: 700;
    }
    .pmb-book__mid-value {
        font-size: 14px;
        font-weight: 600;
        color: var(--text-primary);
        font-variant-numeric: tabular-nums;
    }
    .pmb-book__offline {
        text-align: center;
        padding: 32px 0;
        color: var(--bad);
        font-size: 11px;
        letter-spacing: 0.10em;
        font-weight: 700;
    }

    /* ===== RTT health column ======================================== */
    .pmb-rtt {
        font-family: "JetBrains Mono", ui-monospace, monospace;
    }
    .pmb-rtt--vps .pmb-rtt__caveat::before {
        content: "▣ ";
        color: var(--good);
    }
    .pmb-rtt__caveat {
        font-size: 9px;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 2px;
    }
    .pmb-rtt__liveness {
        font-size: 9px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 6px;
        font-variant-numeric: tabular-nums;
    }
    .pmb-rtt__liveness--good { color: var(--good); }
    .pmb-rtt__liveness--warn { color: var(--warn); }
    .pmb-rtt__liveness--bad  { color: var(--bad); }
    .pmb-rtt__liveness--muted{ color: var(--text-muted); }
    .pmb-rtt__rows { display: flex; flex-direction: column; }
    .pmb-rtt__row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 4px 0;
        border-bottom: 1px solid var(--border-subtle);
    }
    .pmb-rtt__row:last-child { border-bottom: none; }
    .pmb-rtt__name {
        font-size: 10px;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        min-width: 64px;
        font-weight: 600;
    }
    .pmb-rtt__bars {
        display: flex;
        align-items: flex-end;
        gap: 1px;
        height: 18px;
        flex: 1;
        margin: 0 8px;
    }
    .pmb-rtt__bar {
        flex: 1;
        background: var(--border-subtle);
        border-radius: 1px;
        min-height: 2px;
        transition: height 200ms ease, background 200ms ease;
    }
    .pmb-rtt__bar--good { background: var(--good); }
    .pmb-rtt__bar--warn { background: var(--warn); }
    .pmb-rtt__bar--bad  { background: var(--bad); }
    .pmb-rtt__value {
        font-size: 11px;
        font-variant-numeric: tabular-nums;
        min-width: 56px;
        text-align: right;
        color: var(--text-primary);
        font-weight: 600;
    }
    .pmb-rtt__value--err { color: var(--bad); }

    /* ===== Section / panel helpers ================================== */
    .pmb-card {
        background: var(--bg-panel);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 10px 12px;
        margin-bottom: 6px;
    }
    .pmb-card--dim {
        background: var(--bg-inset);
        border-color: rgba(42, 38, 28, 0.5);
        opacity: 0.94;
    }
    .pmb-card__title {
        font-size: 10px;
        font-weight: 700;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.10em;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 6px;
    }
    .pmb-card__title--muted {
        font-size: 9.5px;
        color: var(--text-muted);
    }
    .pmb-section {
        margin: 6px 0;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .pmb-section .pmb-card__title { margin-bottom: 0; }

    /* ===== Incident banner ========================================= */
    .pmb-incident {
        background:
            linear-gradient(180deg, rgba(255, 92, 92, 0.10), transparent 80%),
            var(--bg-panel);
        border: 1px solid rgba(255, 92, 92, 0.40);
        border-left: 3px solid var(--bad);
        border-radius: var(--r-sm);
        padding: 10px 14px;
        margin-bottom: 8px;
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 12px;
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
        font-size: 11px;
    }

    /* ===== Badges ================================================== */
    .pmb-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: var(--r-sm);
        font-size: 9.5px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        line-height: 1.5;
    }
    .pmb-badge--good { background: rgba(138, 255, 122, 0.10); color: var(--good); border: 1px solid rgba(138, 255, 122, 0.30); }
    .pmb-badge--warn { background: rgba(255, 184, 74, 0.10); color: var(--warn); border: 1px solid rgba(255, 184, 74, 0.30); }
    .pmb-badge--bad  { background: rgba(255, 92, 92, 0.10);  color: var(--bad);  border: 1px solid rgba(255, 92, 92, 0.30); }
    .pmb-badge--muted{ background: rgba(155, 141, 107, 0.06); color: var(--text-secondary); border: 1px solid rgba(155, 141, 107, 0.22); }

    /* ===== Empty states + processes/feeds + log + dataframe (carry over) ===== */
    .pmb-empty {
        color: var(--text-secondary);
        padding: 16px 0;
        text-align: center;
        font-size: 12px;
        line-height: 1.7;
    }
    .pmb-empty code {
        background: var(--bg-inset);
        padding: 1px 6px;
        border-radius: var(--r-sm);
        font-size: 11px;
        color: var(--text-primary);
    }
    .pmb-feed-row {
        display: grid;
        grid-template-columns: 1fr;
        gap: 6px;
    }
    .pmb-feed-row--4col { grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .pmb-feed {
        background: var(--bg-inset);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 8px 10px;
    }
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
        font-size: 10.5px;
        font-variant-numeric: tabular-nums;
        line-height: 1.5;
    }
    .pmb-feed__stat strong {
        color: var(--text-primary);
        font-weight: 600;
    }
    .pmb-feed__err {
        color: var(--text-muted);
        font-size: 9.5px;
        margin-top: 2px;
    }
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

    /* Logs */
    .pmb-log {
        background: var(--bg-inset);
        border: 1px solid var(--border-subtle);
        border-radius: var(--r-sm);
        padding: 8px 10px;
        max-height: 300px;
        overflow-y: auto;
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 10px;
        line-height: 1.55;
        white-space: pre-wrap;
        word-break: break-word;
    }
    .pmb-log__line { padding: 1px 4px; border-radius: 2px; }
    .pmb-log__line--info { color: var(--text-secondary); }
    .pmb-log__line--warn { color: var(--warn); background: rgba(255, 184, 74, 0.06); }
    .pmb-log__line--err  { color: var(--bad); background: rgba(255, 92, 92, 0.08); font-weight: 500; }
    .pmb-log::-webkit-scrollbar { width: 6px; }
    .pmb-log::-webkit-scrollbar-track { background: var(--bg-inset); }
    .pmb-log::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: var(--r-sm); }

    /* Trip-wire pill (carries over from v1) */
    .pmb-pill {
        display: inline-block;
        padding: 1px 6px;
        font-size: 9.5px;
        font-weight: 700;
        border-radius: var(--r-sm);
        text-transform: uppercase;
        letter-spacing: 0.06em;
    }
    .pmb-pill--good { background: rgba(138, 255, 122, 0.10); color: var(--good); }
    .pmb-pill--bad  { background: rgba(255, 92, 92, 0.14); color: var(--bad); }
    .pmb-pill--warn { background: rgba(255, 184, 74, 0.10); color: var(--warn); }

    /* ===== Streamlit widget polish ================================== */
    [data-testid="stSidebar"] {
        background: var(--bg-panel);
        border-right: 1px solid var(--border-subtle);
    }
    [data-testid="stSidebar"] h1 {
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.10em;
        color: var(--text-secondary);
        font-weight: 600;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .stTabs [data-baseweb="tab"] {
        background: transparent !important;
        color: var(--text-secondary) !important;
        font-size: 11px !important;
        font-weight: 500 !important;
        padding: 6px 12px !important;
        border-bottom: 2px solid transparent !important;
    }
    .stTabs [aria-selected="true"] {
        color: var(--warn) !important;
        border-bottom-color: var(--warn) !important;
    }
    .stSlider [data-baseweb="slider"] { accent-color: var(--warn); }
    .stDataFrame, [data-testid="stDataFrame"] {
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--r-sm) !important;
        overflow: hidden;
        background: var(--bg-inset) !important;
    }
    [data-testid="stDataFrame"] [role="cell"],
    [data-testid="stDataFrame"] [role="columnheader"] {
        font-variant-numeric: tabular-nums !important;
        font-family: "JetBrains Mono", monospace !important;
    }
    [data-testid="stDataFrame"] [role="columnheader"] {
        font-size: 9.5px !important;
        text-transform: uppercase !important;
        letter-spacing: 0.06em !important;
        color: var(--text-muted) !important;
        font-weight: 700 !important;
    }
    [data-testid="stDataFrame"] [role="row"]:hover [role="cell"] {
        background: var(--bg-panel-hi) !important;
    }

    .st-key-pmb-main-panel,
    .st-key-pmb-side-panel,
    .st-key-pmb-log-panel,
    .st-key-pmb-row1-chart,
    .st-key-pmb-rtt-panel,
    .st-key-pmb-trip-panel,
    .st-key-pmb-tier-panel {
        background: var(--bg-panel) !important;
        border: 1px solid var(--border-subtle) !important;
        border-radius: var(--r-sm) !important;
        padding: 10px 12px !important;
        height: 100% !important;
        display: flex !important;
        flex-direction: column !important;
    }
    .st-key-pmb-main-panel > [data-testid="stVerticalBlock"],
    .st-key-pmb-side-panel > [data-testid="stVerticalBlock"],
    .st-key-pmb-log-panel > [data-testid="stVerticalBlock"],
    .st-key-pmb-row1-chart > [data-testid="stVerticalBlock"],
    .st-key-pmb-rtt-panel > [data-testid="stVerticalBlock"],
    .st-key-pmb-trip-panel > [data-testid="stVerticalBlock"],
    .st-key-pmb-tier-panel > [data-testid="stVerticalBlock"] {
        flex: 1 1 auto;
    }
    [data-testid="stToolbar"] { visibility: hidden; }
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    [data-testid="stDecoration"] { display: none; }

    /* ===== Trip-wire table (carry from v1) ========================== */
    .pmb-trip-table {
        font-family: "JetBrains Mono", monospace;
        border-collapse: collapse;
    }
    .pmb-trip-table th, .pmb-trip-table td {
        padding: 6px 8px;
        border-bottom: 1px solid var(--border-subtle);
    }
    .pmb-trip-table tr:last-child td { border-bottom: none; }
</style>
"""


def inject() -> str:
    """Returns the CSS block to be passed to st.markdown(..., unsafe_allow_html=True)."""
    return CSS


# ============================================================================
# Compatibility shims for v1 — kpi_card / badge / incident_banner remain
# in the public surface so scripts/dashboard.py's trip-wire and incident
# code keeps working while v1 layout is reachable via PMB_DASH_V2=0.
# ============================================================================


def kpi_card(
    *,
    label: str,
    value: str,
    subtitle: str | None = None,
    tone: str = "neutral",
    glyph: str | None = None,
    hero: bool = False,
) -> str:
    """v1 KPI card — renders into the v2 .pmb-kpi class."""
    tone_class = "" if tone == "neutral" else f" pmb-kpi--{tone}"
    sub = f'<div class="pmb-kpi__sub">{subtitle}</div>' if subtitle else ""
    glyph_html = f'<span class="pmb-kpi__glyph">{glyph}</span>' if glyph else ""
    return (
        f'<div class="pmb-kpi{tone_class}">'
        f'<div class="pmb-kpi__label">{label}</div>'
        f'<div class="pmb-kpi__value">{glyph_html}<span>{value}</span></div>'
        f"{sub}"
        f"</div>"
    )


def badge(text: str, tone: str = "muted") -> str:
    return f'<span class="pmb-badge pmb-badge--{tone}">{text}</span>'


def incident_banner(issues: list[str]) -> str:
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
