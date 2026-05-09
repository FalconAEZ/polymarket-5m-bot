# Design — Operations Dashboard v2 (Phase 11.A.X)

> Locks the v2 redesign of the Streamlit operations dashboard. Read-only
> consumer of `state/` (no writes, no bot-logic touch). Bloomberg-terminal
> aesthetic, dark-only, with pixel-display hero PnL, live tape ticker,
> real execution-pipeline visualization, and dual orderbook panels (Binance
> spot + Polymarket CTF). Anti-vibe rule #1: this doc lands and locks
> before any code under `src/polymarket_bot/dashboard/` or
> `scripts/dashboard.py` changes for v2.
>
> Anchors:
> - v1 design: [design/dashboard.md](dashboard.md) — locked loader interface stays unchanged
> - v1 critique: [runbooks/research/dashboard-critique-2026-05-09.md](../runbooks/research/dashboard-critique-2026-05-09.md)
> - Tooling picks: [runbooks/research/dashboard-tooling-options-2026-05-09.md](../runbooks/research/dashboard-tooling-options-2026-05-09.md)
> - Operator references: 3 demo screenshots provided 2026-05-09 (MiroFish
>   Mispricing Scanner; BTC Polymarket Terminal; ETH Polymarket Terminal)
> - Active phase: [state/phases/phase-11-spot-aware.md](../state/phases/phase-11-spot-aware.md)
> - Locked decisions [#15 UTC everywhere, #16 ensemble cut but retained
>   as historical, #18 Obsidian on laptop only]

---

## 1. Why v2

The v1 dashboard (`design/dashboard.md`, shipped Phase 4.5, overhauled
2026-05-09 for aggressive-mode) is functionally complete but visually
generic. The 10 findings in `dashboard-critique-2026-05-09.md` collapse
to three operational problems:

1. **Hierarchy inversion** — the page's most important number ("are we
   making money?") is a 22px KPI card among six equal-weight cards.
   Operator audit: 3 seconds to answer "are we making money?" at
   a glance. Should be <1s.
2. **No event rhythm** — the page refreshes every 4s but reads as
   static. Operator can't feel what just happened.
3. **Bot pipeline invisible** — we have a real 6-stage execution
   loop (CAPTURE → STRATEGY → SIM-FILL → SETTLE → RESOLVE → PERSIST)
   with measurable per-stage latency. None of it is rendered today.

Plus two scaling pressures:

4. Phase 11.B-F introduces ETH alongside BTC; the current header has
   no slot for a market switcher.
5. Phase 11.A.2 aggressive-mode experiment (running through 2026-05-10
   22:26 UTC) demands trip-wire-grade visibility into both bot-side
   bot health and provider-side reachability.

v2 addresses all five. v2 does **not** replace v1 — it ships behind a
feature flag (`PMB_DASH_V2=1`) so the operator can toggle while the
aggressive-mode experiment is in flight.

---

## 2. What stays from v1 (locked)

The loader interface in `src/polymarket_bot/dashboard/loaders.py` is
the durable contract between dashboard and runtime. v2 adds new loaders
alongside; it never breaks the existing surface.

**Locked, unchanged**:
- `DecisionRow`, `ProcessStatus`, `HealthSnapshot`, `FeedSnapshot`
- `load_process_status`, `load_feeds_health`, `load_decisions`,
  `tail_log`
- `aggregate_pnl`, `fire_rate_per_hour`, `latest_active_mode`,
  `per_tier_stats`
- Trip-wire panel logic (`_render_aggressive_trip_wires`)
- Per-tier panel logic (`_render_tier_panel`)
- Two-stage sync mechanism (`runbooks/scripts/sync_staging.sh`)
- Auto-sync 30s throttle + sentinel-touch race fix
- Incident detection (`_detect_incidents`)
- MODE banner colour rules (`_MODE_BADGE`)
- Historical agent panel (collapsed by default)

**Migrated** (renamed but functionally same):
- `theme.py` v1 CSS replaced wholesale; `kpi_card`/`badge`/
  `incident_banner` exports retained as compatibility shims for
  the aggressive-mode trip-wire panel which keeps using them
  through v2

**Removed in v2** (hidden when `PMB_DASH_V2=1`):
- v1 layout in `scripts/dashboard.py` (kept reachable via
  `PMB_DASH_V2=0` for rollback)

---

## 3. Information hierarchy

The page answers questions in this priority order. Each answer is
visually placed so eye reaches it in the listed time budget.

| # | Question | Time budget | Where on page |
|---|---|---|---|
| 1 | Are we making money? | <1s | Hero PnL pixel display, 96px |
| 2 | Is the bot firing? | <2s | Live tape (top) + Fire Rate satellite KPI |
| 3 | Is anything broken? | <2s | Incident banner (when present); pipeline strip stage colour |
| 4 | What just happened? | <2s | Live tape, scrolling left |
| 5 | Where is the bot in its execution cycle? | <3s | Pipeline strip (90px) below hero |
| 6 | What's the current spot price? | <3s | Spot orderbook panel + 5m candle chart |
| 7 | What does our market look like? | <3s | Polymarket CTF orderbook panel |
| 8 | Are providers responsive? | <3s | Per-provider RTT sparklines in health column |
| 9 | What did each tier do? | drill-down | Per-tier panel below the fold |
| 10 | Show me the raw decisions | drill-down | Decisions tape in main column; full table below the fold |

---

## 4. Design tokens — Dark Terminal (v2 only theme)

Light theme is **out of scope** for v2 per operator instruction.

### Colour palette

```
/* Page surfaces */
--bg-page:       #08070a;   /* warm-tinted near-black, matches ETH ref */
--bg-panel:      #11100c;   /* one step lighter, panel surface */
--bg-panel-hi:   #1a1812;   /* hover / active panel */
--bg-inset:      #0c0b08;   /* inset wells (orderbook depth, log scroll) */

/* Borders */
--border-subtle: #2a261c;   /* default panel border */
--border-strong: #3d3725;   /* hover / focus border */
--border-amber:  #6b4d18;   /* dotted/dashed accent border (warning panels) */

/* Text */
--text-primary: #f5edd6;    /* warm cream — primary text */
--text-secondary: #9c8d6b;  /* warm tan — secondary */
--text-muted: #5a4f3a;      /* dim — captions */

/* Status — terminal palette */
--good: #8aff7a;            /* terminal green (wins, alive, healthy) */
--good-glow: rgba(138, 255, 122, 0.18);
--bad: #ff5c5c;             /* alarm red (losses, dead, breach) */
--bad-glow: rgba(255, 92, 92, 0.20);
--warn: #ffb84a;            /* amber (warnings, mode=aggressive) */
--warn-glow: rgba(255, 184, 74, 0.20);

/* Accent — used sparingly for the "live" elements */
--accent-cyan: #6effff;     /* live dot, "in flight" markers */
--accent-magenta: #ff6ec7;  /* pipeline glow on activity (rare) */
```

### Typography

```
/* Display — hero PnL only */
font-family: "Pixelify Sans", "VT323", monospace;
font-size: 96px;
font-weight: 600;
letter-spacing: 0.02em;
font-feature-settings: "tnum", "ss01";

/* Body — every other text element */
font-family: "JetBrains Mono", "SF Mono", "Menlo", ui-monospace, monospace;
font-size: 11px;
line-height: 1.5;
font-variant-numeric: tabular-nums;

/* Headings (panel titles, section headers) */
font-family: "JetBrains Mono", monospace;
font-size: 10px;
text-transform: uppercase;
letter-spacing: 0.10em;
font-weight: 600;
color: var(--text-secondary);

/* KPI satellite values */
font-family: "JetBrains Mono", monospace;
font-size: 24px;
font-weight: 600;
font-variant-numeric: tabular-nums;
letter-spacing: -0.01em;
```

Google Fonts loaded: `Pixelify+Sans:wght@400;500;600;700`,
`JetBrains+Mono:wght@400;500;600`. Inter is dropped (no humanist sans
in the v2 aesthetic).

### Spacing scale

4px baseline:
```
--sp-1: 4px   --sp-2: 8px    --sp-3: 12px   --sp-4: 16px
--sp-5: 20px  --sp-6: 24px   --sp-7: 32px   --sp-8: 48px
```

### Radius scale

Bloomberg terminals are **flat** — radius is reserved for soft UI
elements, not panels:
```
--r-none: 0px      /* panels, orderbook rows */
--r-sm:   3px      /* badges, small buttons */
--r-md:   6px      /* inputs, dropdowns */
```

### Borders

```
--border-default: 1px solid var(--border-subtle);
--border-dashed:  1px dashed var(--border-amber);    /* warning panels */
--border-dotted:  1px dotted var(--border-amber);    /* hero PnL frame */
```

### Animation

```
/* live dot — already in v1, kept */
@keyframes pmb-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%      { opacity: 0.55; transform: scale(1.4); }
}

/* row enter — new decisions, tape entries */
@keyframes pmb-fade-in {
  from { opacity: 0; transform: translateY(-4px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* digit roll — hero PnL on update (CSS @property) */
@property --pmb-pnl {
  syntax: "<integer>";
  inherits: false;
  initial-value: 0;
}
.pmb-hero-pnl { transition: --pmb-pnl 800ms ease-out; }

/* tape ticker scroll */
@keyframes pmb-tape-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }   /* tape content duplicated */
}
.pmb-tape__inner {
  animation: pmb-tape-scroll 60s linear infinite;
}
.pmb-tape:hover .pmb-tape__inner {
  animation-play-state: paused;
}

/* pipeline stage glow on activity */
@keyframes pmb-stage-glow {
  0%   { box-shadow: 0 0 0 0 var(--good-glow); }
  50%  { box-shadow: 0 0 12px 2px var(--good-glow); }
  100% { box-shadow: 0 0 0 0 transparent; }
}
.pmb-stage--active { animation: pmb-stage-glow 1.2s ease-out; }

/* trip-wire bar fill */
.pmb-trip-bar {
  transition: width 600ms ease-out, background-color 200ms ease;
}
```

---

## 5. Layout grid

### Above-the-fold (~900px tall, fits 1920×1080 with browser chrome)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TOP STRIP (60px)                                                         │
│  ●LIVE  POLYMARKET 5M · [BTC ⌃ ETH ⌃ ...]    BANKROLL $1,039.51         │
│  MODE: AGGRESSIVE  ·  Phase 11.A.2 · 48h gate at 22:26 UTC · sync 7s ago│
├──────────────────────────────────────────────────────────────────────────┤
│ LIVE TAPE (28px) — scrolls left, 60s loop, pauses on hover               │
│ ▲WIN +$5.88 30-50% UP · FILL 12s · ▼LOSS -$1.16 50-70% DOWN · STREAK 3 ▶│
├──────────────────────────────────────────────────────────────────────────┤
│ INCIDENT BANNER (only when present, ~38px)                               │
│ ⚠ 2  Issues detected. paper process not running · feeds_health stale     │
├──────────────────────────────────────────────────────────────────────────┤
│ HERO ROW (180px)                                                         │
│ ┌────────────────────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────┐ │
│ │ CUMULATIVE PnL             │ │ FIRE RATE  │ │ STREAK   │ │ PROFIT/HR│ │
│ │                            │ │            │ │          │ │          │ │
│ │   +$ 39.51                 │ │  14.2/hr   │ │  ▲ 3     │ │ +$10.12  │ │
│ │   ▔▔▔▔▔▔▔ pixel display    │ │  ████░░░   │ │  best 7  │ │ last 60m │ │
│ │   bankroll +3.95% · last hr│ │  341/d proj│ │ 47.9% WR │ │  on $1k  │ │
│ │   +$5.88 (1 fill)          │ │  ≤350 trip │ │ on n=48  │ │  basis   │ │
│ └────────────────────────────┘ └────────────┘ └──────────┘ └──────────┘ │
├──────────────────────────────────────────────────────────────────────────┤
│ PIPELINE STRIP (90px)                                                    │
│ ┌─────────┬─────────┬─────────┬─────────┬─────────┬─────────┐           │
│ │ CAPTURE │STRATEGY │SIM-FILL │ SETTLE  │ RESOLVE │ PERSIST │           │
│ │ 4 feeds │spot_aw  │ 96% fill│T-47s    │ Gamma OK│ JSONL   │           │
│ │ 118ms   │  41ms   │   12ms  │5m wait  │  220ms  │  3ms    │           │
│ │  ALIVE  │  ALIVE  │  ALIVE  │ PENDING │  ALIVE  │  ALIVE  │           │
│ └─────────┴─────────┴─────────┴─────────┴─────────┴─────────┘           │
├──────────────────────────────────────────────────────────────────────────┤
│ MAIN GRID — 12-col (60% / 25% / 15%)                                    │
│ ┌─────────────────────────────────────┐ ┌──────────────┐ ┌────────────┐ │
│ │ CUMULATIVE PnL CHART (180px)        │ │ HEALTH       │ │ LIVE LOG   │ │
│ │ live area chart, plotly             │ │ Processes    │ │ paper.log  │ │
│ ├─────────────────────────────────────┤ │ Feeds        │ │ │ capture  │ │
│ │ DECISIONS TAPE (320px)              │ │ ────────     │ │            │ │
│ │ aggrid, newest first, win/loss bars │ │ Trip-wires   │ │ tail 60    │ │
│ │ cols: time · side · tier · PnL bar  │ │ (when agg.)  │ │            │ │
│ │       · ttl · resolution · Δbps     │ │ ────────     │ │ ERR rows   │ │
│ │                                     │ │ RTT spark    │ │ red bg     │ │
│ │                                     │ │  Binance ▁▂▁▃│ │            │ │
│ │                                     │ │  Coinbase ▂▁ │ │            │ │
│ │                                     │ │  Chainlink ▁ │ │            │ │
│ │                                     │ │  PM-Gamma ▁▁ │ │            │ │
│ │                                     │ │  PM-CLOB ▁▁  │ │            │ │
│ └─────────────────────────────────────┘ └──────────────┘ └────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

### Below-the-fold

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ORDERBOOK ROW — dual orderbook + 5m candle chart                         │
│ ┌────────────────────────────┐ ┌─────────────────┐ ┌──────────────────┐ │
│ │ BTC SPOT REFERENCE         │ │ BTC 5M CANDLES  │ │ OUR MARKET       │ │
│ │ Binance L2 · 100ms         │ │ TradingView     │ │ Polymarket CLOB  │ │
│ │                            │ │ embed, dark     │ │ BTC ↑/↓ 5M       │ │
│ │ ASK 77502.34   95          │ │                 │ │                  │ │
│ │ ASK 77502.32  462          │ │ 280px tall      │ │ ASK 0.572   1200 │ │
│ │ ASK 77502.31  354  ────────│ │                 │ │ ASK 0.570    800 │ │
│ │ MID 77502.17               │ │                 │ │ MID 0.564        │ │
│ │ BID 77502.16  173 ─────    │ │                 │ │ BID 0.562    600 │ │
│ │ BID 77502.13  751          │ │                 │ │ BID 0.558    400 │ │
│ │ depth bars left/right side │ │                 │ │                  │ │
│ └────────────────────────────┘ └─────────────────┘ └──────────────────┘ │
├──────────────────────────────────────────────────────────────────────────┤
│ AGGRESSIVE-MODE TRIP-WIRES (only renders when mode=aggressive)           │
│ unchanged from v1                                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ PER-TIER DISCIPLINE TABLE                                                │
│ unchanged from v1                                                        │
├──────────────────────────────────────────────────────────────────────────┤
│ HISTORICAL AGENT PANEL (collapsed by default)                            │
│ unchanged from v1                                                        │
└──────────────────────────────────────────────────────────────────────────┘
```

### Streamlit column ratios

```python
st.columns([0.60, 0.25, 0.15], gap="small")    # main grid
st.columns([0.40, 0.30, 0.30], gap="small")    # orderbook row (spot / chart / CTF)
st.columns([0.30, 0.18, 0.18, 0.18, 0.16])     # hero row (PnL hero / 3 satellite KPIs / spacer)
```

---

## 6. Component contracts

All new components live in
`src/polymarket_bot/dashboard/components.py` (NEW). Each is a pure
function that returns an HTML string. Streamlit calls them via
`st.html(...)`. None of them touch `st.session_state` directly.

### 6.1 `pixel_display(value: str, *, sign: str | None, glow: str = "good") -> str`

The hero PnL display. Renders the value in Pixelify Sans 96px with an
optional `+`/`-` prefix and a tone class for colour.

```python
pixel_display(value="$39.51", sign="+", glow="good")
# → 96px Pixelify Sans, terminal green, +$39.51
```

### 6.2 `live_tape(events: list[TapeEvent]) -> str`

Renders the scrolling tape. Events doubled (concatenated to itself) so
the CSS keyframe scroll loops seamlessly.

```python
@dataclass(frozen=True, slots=True)
class TapeEvent:
    glyph: str          # "▲" / "▼" / "•"
    label: str          # "WIN +$5.88 30-50% UP"
    tone: str           # "good" / "bad" / "muted"
    age_s: float        # used for sort + decay
```

Builder helper: `tape_events_from_decisions(rows: list[DecisionRow], n: int = 12) -> list[TapeEvent]` — pure function, takes the latest `n` settled+filled decisions and turns each into a TapeEvent.

### 6.3 `pipeline_strip(stages: list[PipelineStage]) -> str`

The 6-stage execution-cycle visualization. Each stage:

```python
@dataclass(frozen=True, slots=True)
class PipelineStage:
    name: str           # "CAPTURE"
    detail: str         # "4 feeds"
    latency_ms: float | None    # None → render "—"
    status: Literal["alive", "pending", "warn", "dead"]
    is_active: bool     # True → adds .pmb-stage--active glow class
```

Builder: `pipeline_stages_from_state(rows, snap, capture, paper, latencies) -> list[PipelineStage]` — derives each stage's status/latency from the existing v1 loaders + a new `latencies` dict (see §7.4).

### 6.4 `kpi_satellite(label: str, value: str, *, subtitle: str | None, tone: str) -> str`

Standard 24px-value KPI card for the 3 satellites (Fire Rate, Win
Streak, Profit Pace). Same as v1's `kpi_card` but smaller and without
the hero variant — the hero is a separate dedicated component now.

### 6.5 `bankroll_chip(starting_usd: float, current_usd: float) -> str`

Renders "BANKROLL $1,039.51 · +3.95% · started $1,000.00" as a small
inline chip in the top strip. Tone follows sign of (current - starting).

### 6.6 `provider_rtt_sparkline(name: str, samples_ms: list[float], current_ms: float | None) -> str`

Wraps a Plotly figure in an HTML container with the provider name,
current RTT, and a 60s history sparkline. 5 of these stack vertically
in the health column.

### 6.7 `orderbook_panel(side: Literal["spot", "ctf"], rows: list[OrderbookRow], mid: float | None, asof: datetime | None) -> str`

Renders an L2 orderbook. Top-N ask rows (descending price), mid divider,
top-N bid rows. Each row: price (right-aligned), size (right-aligned),
horizontal depth bar (proportional to row size / max size on that side).

```python
@dataclass(frozen=True, slots=True)
class OrderbookRow:
    price: float
    size: float
    cumulative_size: float
```

For `side="spot"`, panel header reads "BTC SPOT REFERENCE · Binance · 100ms".
For `side="ctf"`, panel header reads "OUR MARKET · BTC ↑/↓ 5M · Polymarket CLOB · NNNs".

### 6.8 `tradingview_chart(symbol: str = "BINANCE:BTCUSDT", interval: str = "5") -> str`

Returns an `<iframe>` snippet for the TradingView free embed, dark
theme, no toolbar. Render via `st.components.v1.html(..., height=280)`.

### 6.9 `tape_event_inline(ev: TapeEvent) -> str`

Single tape event in inline form. Used inside `live_tape` and
optionally in the incident banner.

---

## 7. New loaders

### 7.1 `bankroll.py` — derived ledger

```python
@dataclass(frozen=True, slots=True)
class Bankroll:
    starting_usd: float          # locked decision #10 → $1,000
    current_usd: float           # starting + sum(pnl_usd)
    delta_usd: float
    delta_pct: float

def load_bankroll(rows: list[DecisionRow], starting_usd: float = 1000.0) -> Bankroll: ...
```

Pure function over existing `DecisionRow` data. Uses locked-decision
default of $1,000.

### 7.2 `streaks.py` — win/loss streak

```python
@dataclass(frozen=True, slots=True)
class StreakInfo:
    current_glyph: str          # "▲" if winning, "▼" if losing, "·" if none
    current_n: int              # length of current streak
    best_win_streak: int
    worst_loss_streak: int

def compute_streak(rows: list[DecisionRow]) -> StreakInfo: ...
```

Walks settled rows in chronological order; tracks current and best.

### 7.3 `profit_pace.py` — $/hour over rolling 60m

```python
def profit_pace_per_hour(rows: list[DecisionRow], window_s: float = 3600) -> tuple[float, int]:
    """Returns (usd_per_hour, n_settled_in_window)."""
```

### 7.4 `pipeline_latency.py` — derive per-stage latency

```python
@dataclass(frozen=True, slots=True)
class PipelineLatencies:
    capture_ms: float | None    # snapshot age of feeds_health (proxy)
    strategy_ms: float | None   # parsed from rationale "decision_latency_ms=X"
    sim_fill_ms: float | None   # parsed from fill rationale or settlement
    settle_wait_s: float | None # 5min - (now - window_ts), if positive
    resolve_ms: float | None    # parsed from settled rationale
    persist_ms: float | None    # always small; constant 3 if file present

def derive_pipeline_latencies(rows, snap, settled_log_path) -> PipelineLatencies: ...
```

Where data is unavailable, the field is `None` and the pipeline
strip renders "—".

### 7.5 `polymarket_orderbook.py` — CTF orderbook fetcher

```python
@dataclass(frozen=True, slots=True)
class CTFBookSnapshot:
    market_slug: str
    up_token_id: str
    down_token_id: str
    side: Literal["UP", "DOWN"]
    rows_ask: list[OrderbookRow]
    rows_bid: list[OrderbookRow]
    mid: float | None
    asof: datetime
    rtt_ms: float

def fetch_ctf_orderbook(window_ts: int, side: Literal["UP", "DOWN"] = "UP", *, throttle_s: float = 2.0) -> CTFBookSnapshot | None: ...
```

Polls `py-clob-client.get_order_book(token_id)` for the current 5m
window. Throttle: caches the last snapshot for `throttle_s` seconds.
Token-ID resolution uses Gamma `get_market(slug=f"btc-updown-5m-{window_ts}")`.

### 7.6 `provider_rtt.py` — browser-side RTT (rendered via JS)

This loader is **JS-only** — Python loader returns the configuration
the JS uses (URL list, sample count, refresh cadence). The actual RTT
measurement happens in the operator's browser:

```python
PROVIDERS = (
    ("Binance",   "https://api.binance.com/api/v3/time"),
    ("Coinbase",  "https://api.exchange.coinbase.com/time"),
    ("Chainlink", _chainlink_rpc_url()),
    ("PM-Gamma",  "https://gamma-api.polymarket.com/markets?limit=1"),
    ("PM-CLOB",   "https://clob.polymarket.com/time"),
)

def provider_rtt_config() -> list[ProviderConfig]: ...
```

JS lives in a single inline `<script>` block injected via
`st.components.v1.html(...)`. Persists samples in `localStorage` so a
page refresh doesn't lose the 60s history.

---

## 8. Feature flag

v2 is gated by env var `PMB_DASH_V2`. Read at startup:

```python
DASH_V2 = os.environ.get("PMB_DASH_V2", "0") == "1"
```

Behaviour:
- `PMB_DASH_V2=0` (default): existing v1 layout renders unchanged
- `PMB_DASH_V2=1`: v2 layout renders

Toggle mechanism: `make dash-staging` (default) → v1; `make dash-staging-v2` → v2 (new Make target sets `PMB_DASH_V2=1`).

Rationale: aggressive-mode soak is in flight (gate at 2026-05-10
22:26 UTC). v2 must not disrupt the operator's continuous visibility.
Default-off lets operator A/B compare and adopt v2 when ready.

After v2 is approved + adopted (post 48h gate, target ~2026-05-11),
a follow-up commit removes the v1 path and `PMB_DASH_V2` flag.

---

## 9. Multi-market expansion plan

Phase 11.B-F adds ETH and other markets. v2 anticipates this without
requiring a layout rewrite:

### Loader parameterization
All new loaders take an optional `market_id: str = "BTC"` parameter.
Existing v1 loaders are kept unchanged (BTC implicit). When ETH lands,
the new loaders fan out per-market; v1 loaders get one-line market
filters added.

### Top-strip market tabs
The `BTC | ETH | ...` tab control in the top strip uses
`streamlit-shadcn-ui ui.tabs` with the active tab stored in
`st.session_state["market_id"]`. Default: BTC. Tab list derived from a
`MARKETS` constant in `dashboard/markets.py` (NEW, ships with BTC only
in v2; ETH added in Phase 11.B as a one-line append).

### Aggregate view (Phase 11.D)
URL param `?view=all` activates an aggregate layout that sums hero PnL,
fire rate, etc. across all markets. Out of scope for the v2 ship.
Designed-in: the loader function signatures support `market_id="ALL"`
which returns aggregated data; the layout-switching logic lives in
`scripts/dashboard.py:main()` reading the URL param.

### Strategy switcher (when n_strategies > 1)
Currently `spot_aware` is the only active strategy. When a second
arrives (`spot_aware_v2`, etc.), a second tab control appears below
the market tabs. v2 designs the slot but doesn't render anything until
`len({r.strategy for r in rows}) > 1`.

---

## 10. VPS-side architecture (revised 2026-05-09)

> The original v2 design had the dashboard running laptop-side with
> browser-JS RTT measurement. Operator critique 2026-05-09: the bot
> is on the VPS, the dashboard should be too, RTT should be measured
> from where the bot actually is. This section captures the revised
> architecture; everything else in this doc still stands.

### Where things run

```
[VPS Dublin · eu-west-1]                                [Laptop]
 ├─ bot-staging.service       ┐
 ├─ grafana-agent.service      │ shared state/
 ├─ litestream.service         │  (bot writes,
 ├─ rtt-collector.service      │   dashboard reads)
 └─ streamlit-dashboard.service┘ ── 127.0.0.1:8503

              │                                          ┌──────────┐
              │  SSH tunnel  ────────────────────────────│ browser  │
              │  -L 8503:127.0.0.1:8503                  │ at       │
              │                                          │ 127.0.0.1│
              │                                          │   :8503  │
                                                         └──────────┘
```

The dashboard binds to `127.0.0.1:8503` only — never the public
interface. Operator opens an SSH tunnel from their laptop and browses
`http://127.0.0.1:8503/` locally.

### Provider RTT — measured server-side from the VPS

`src/polymarket_bot/dashboard/rtt_collector.py` runs as its own systemd
unit (`runbooks/staging/rtt-collector.service`). Async pings every 10s
to the 5 providers; appends one JSONL line per provider per tick to
`state/provider_rtt.jsonl`. Failures recorded with `ok=false` rather
than dropping the line.

`src/polymarket_bot/dashboard/rtt_loader.py` reads the JSONL tail
(bounded I/O — 256KB max). Returns up to 6 most-recent samples per
provider. The dashboard's RTT panel renders server-side via
`components.provider_rtt_panel(samples_by_provider)` — no JavaScript
in the operator's browser, no laptop-side measurement.

**Why a separate service** (not a sidecar in the dashboard process):

- RTT history accumulates continuously — even when dashboard restarts
  (CSS tweaks, deploys, sleeping operator), the JSONL keeps growing
- Decoupled: dashboard CSS bug can't take RTT collection down with it
- Future Telegram alert ("PM-CLOB RTT >1s for 2min") reads the same
  JSONL with no dashboard touch
- Operator already manages 5 systemd units; +1 is negligible

### What the dashboard process does NOT do anymore

- **No laptop-side state rsync.** When the dashboard runs on the VPS,
  the bot's state IS the local state. `PMB_DASH_STATE_DIR` points at
  `/home/ops/polymarket-5m-bot/state`. The two-stage decisions.raw/ →
  resolve → decisions/ pipeline still runs (it lives in the bot, not
  the dashboard) — no rsync hop.
- **No browser-side JS provider pinger.** `provider_rtt.rtt_widget_html()`
  stays in the codebase as a reference implementation but is not
  called by `scripts/dashboard.py` v2 layout.
- **No `PMB_DASH_STATE_DIR=state/staging` convention.** The `staging`
  subdir was the laptop's rsync mirror. On the VPS, drop the suffix —
  state lives at `state/`.

### Laptop access — SSH tunnel (default)

`runbooks/operations/dashboard-tunnel.sh` (also `make dash-tunnel`):

```bash
ssh -p 2222 -L 8503:127.0.0.1:8503 -N \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    ops@108.132.51.116
```

Run from laptop, browse `http://127.0.0.1:8503/`. Quit with Ctrl-C.

**Why SSH tunnel** (vs Tailscale / Cloudflare / nginx-public):

- Operator already has SSH access (port 2222, `ops` user, key auth)
- Zero new tooling to install
- Most private — no public exposure of PnL/bankroll
- Easy upgrade path to Tailscale when phone access is wanted (5-min
  install on both ends; same `127.0.0.1:8503` URL pattern)

### Bot-side per-message RTT (not in this PR)

The `rtt-collector.service` measures the *bot's* RTT to providers via
HTTP REST endpoints. It does **not** measure the per-WS-message
latency the bot sees while running its actual feeds. That requires a
one-line hook in each feed's WS message handler — touches
`src/polymarket_bot/_live/feeds/*` and so is out of scope for this
dashboard work. Queued as a separate follow-up commit in the same PR
with its own design note in `design/feeds-latency-instrument.md`. The
v2 dashboard will render bot-side per-message RTT alongside the
collector's REST RTT once that hook lands.

### Files added for the VPS architecture

| Path | Purpose |
|---|---|
| `src/polymarket_bot/dashboard/rtt_collector.py` | Async RTT pinger; runs as its own systemd unit |
| `src/polymarket_bot/dashboard/rtt_loader.py` | Reader for `state/provider_rtt.jsonl` |
| `src/polymarket_bot/dashboard/components.py` (`provider_rtt_panel`) | Server-side rendered RTT UI replacing the JS widget |
| `runbooks/staging/streamlit-dashboard.service` | systemd unit for the dashboard |
| `runbooks/staging/rtt-collector.service` | systemd unit for the RTT pinger |
| `runbooks/operations/dashboard-tunnel.sh` | SSH tunnel wrapper for laptop access |
| `runbooks/staging/deploy-dashboard.md` | Operator's 5-minute VPS deploy runbook |
| `Makefile` (`dash-tunnel` target) | `make dash-tunnel` invokes the script |

---

## 11. Animation principles

Animation in v2 is functional, not decorative. Each animation answers
a question.

| Animation | Question it answers | Duration | Easing |
|---|---|---|---|
| Live dot pulse | Is the page live? | 1.6s loop | ease-in-out |
| New decision row fade-in | Did anything just happen? | 240ms | ease-out |
| Hero PnL digit roll | Did PnL change? | 800ms | ease-out |
| Tape ticker scroll | What recently happened? | 60s loop | linear |
| Pipeline stage glow | Is the bot working right now? | 1.2s | ease-out |
| Trip-wire bar fill | How close are we to a breach? | 600ms | ease-out |
| Sparkline updates | Is provider RTT changing? | continuous | (Plotly default) |

No animation longer than 1.2s except the tape (which is a continuous
loop, not a triggered event). No animation triggers on a stable
page — the operator's focus must not be hijacked by useless motion.

---

## 12. Test discipline

`tests/dashboard/` covers the new pure-function loaders. UI rendering
is not tested (Streamlit's job). Targets:

- `tests/dashboard/test_bankroll.py` — `load_bankroll` over fixture
  rows; sums match; delta_pct computed correctly; empty rows → just
  starting capital
- `tests/dashboard/test_streaks.py` — `compute_streak`: empty,
  all-wins, all-losses, mixed, current vs best
- `tests/dashboard/test_profit_pace.py` — windowed sum; empty window
  returns (0.0, 0)
- `tests/dashboard/test_pipeline_latency.py` — derives latencies from
  fixture rows + fixture feeds_health snapshots; missing data → None
- `tests/dashboard/test_components.py` — string-output components
  return well-formed HTML (smoke test, not visual)
- `tests/dashboard/test_provider_rtt_config.py` — config returns the
  expected provider list

Existing tests stay green. `make verify` must pass.

---

## 13. File map

| Path | Phase | Purpose |
|---|---|---|
| `design/dashboard-v2.md` (this file) | 11.A.X.0 | Design lock |
| `runbooks/research/dashboard-critique-2026-05-09.md` | 11.A.X.0 | Phase A |
| `runbooks/research/dashboard-tooling-options-2026-05-09.md` | 11.A.X.0 | Phase B |
| `src/polymarket_bot/dashboard/components.py` | 11.A.X.1 | NEW — all v2 components |
| `src/polymarket_bot/dashboard/bankroll.py` | 11.A.X.1 | NEW |
| `src/polymarket_bot/dashboard/streaks.py` | 11.A.X.1 | NEW |
| `src/polymarket_bot/dashboard/profit_pace.py` | 11.A.X.1 | NEW |
| `src/polymarket_bot/dashboard/pipeline_latency.py` | 11.A.X.1 | NEW |
| `src/polymarket_bot/dashboard/polymarket_orderbook.py` | 11.A.X.1 | NEW |
| `src/polymarket_bot/dashboard/provider_rtt.py` | 11.A.X.1 | NEW |
| `src/polymarket_bot/dashboard/markets.py` | 11.A.X.1 | NEW — multi-market constants |
| `src/polymarket_bot/dashboard/theme.py` | 11.A.X.2 | Major rewrite — v2 tokens |
| `scripts/dashboard.py` | 11.A.X.2 | Layout rewrite (gated by PMB_DASH_V2) |
| `tests/dashboard/test_bankroll.py` | 11.A.X.1 | NEW |
| `tests/dashboard/test_streaks.py` | 11.A.X.1 | NEW |
| `tests/dashboard/test_profit_pace.py` | 11.A.X.1 | NEW |
| `tests/dashboard/test_pipeline_latency.py` | 11.A.X.1 | NEW |
| `tests/dashboard/test_components.py` | 11.A.X.1 | NEW |
| `tests/dashboard/test_provider_rtt_config.py` | 11.A.X.1 | NEW |
| `runbooks/research/dashboard-v2-screenshots/` | 11.A.X.3 | NEW — before/after PNGs |
| `Makefile` | 11.A.X.2 | Add `dash-staging-v2` target |
| `pyproject.toml` | 11.A.X.0 | Add streamlit-shadcn-ui, streamlit-aggrid, plotly (DONE) |

---

## 14. Out of scope for v2

- **Bot-side per-message RTT instrumentation.** Lives in
  `feeds/`; ships as a separate commit in the same PR with its own
  design note `design/feeds-latency-instrument.md`.
- **Light theme.** Operator instruction: dark only.
- **Aggregate "all markets" view.** Designed-for, not built. Phase 11.D.
- **Strategy switcher UI.** Only one strategy active; ship the slot,
  don't render until `n_strategies > 1`.
- **Trade-fired Lottie animations.** Tonally wrong for a paper-soak.
- **WebSocket-pushed Streamlit updates.** Streamlit's autorefresh model
  is sufficient at 4s; pushing updates would require streamlit-elements
  (rejected) or a custom React component (out of scope).
- **Removing the v1 layout.** v2 ships behind feature flag; v1 stays
  reachable via `PMB_DASH_V2=0` until operator confirms v2 adoption
  post 48h gate.
- **Order placement / bot control surface.** Dashboard remains
  read-only per locked decision (v1 design §2).

---

## 15. v2 success criteria

The v2 ships when:

1. `design/dashboard-v2.md` (this file) reviewed + approved by operator
2. `make verify` green (zero test regressions; new tests added)
3. `lint-imports` green (3 contracts unchanged)
4. `make dash-staging-v2` renders without errors against live staging
   data (the in-flight aggressive-mode soak data)
5. Operator-timed audit on `dash-staging-v2`:
   - "Are we making money?" answerable in <1s ✅
   - "Is the bot firing?" answerable in <2s ✅
   - "Is anything broken?" answerable in <2s ✅
6. Before/after screenshots committed to
   `runbooks/research/dashboard-v2-screenshots/`
7. Operator-approved visual diff on the screenshots
8. Commit pushed to `main` with a CHANGELOG-style commit message

The PR will contain (in this order):
- Commit 1: dashboard v2 (this design + components + tests + screenshots)
- Commit 2: bot-side latency hook (separate design + 4 feed updates + 1 test)

---

## 16. Locked surface

Once approved, the following are **locked** for v2:

- Design tokens (colours, typography, spacing, radius)
- Component public signatures in `components.py`
- New loader public signatures (sections 7.1-7.6)
- Layout grid column ratios
- Feature flag mechanism (`PMB_DASH_V2`)
- File map (sections 13)

Future v2.x revisions (e.g., adding a new orderbook level, tweaking
animation timing) don't require a design-doc revision so long as they
preserve the locked surface.

v3 (whenever — possibly Phase 11.D's aggregate view, or Phase 12's
live-trading observability needs) gets its own design doc.
