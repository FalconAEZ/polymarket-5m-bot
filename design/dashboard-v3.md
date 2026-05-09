# Design — Operations Dashboard v3 (Phase 11.A.X.B)

> Locks the v3 rebuild of the operator dashboard. **v3 throws away v2.1's
> Streamlit UI** and replaces it with a custom React + FastAPI app that
> runs on the VPS, mirrored to the operator's laptop via SSH tunnel.
> v2.1 stays reachable as `/audit` for back-office decision deep-dive.
>
> Anti-vibe rule #1: this doc lands and locks before any code under
> `apps/dashboard-v3/` or `src/polymarket_bot/dashboard_server/`.
>
> **Operator critique that triggered v3** (2026-05-09):
> v2.1 reads as v1 with restructured panels — no original design voice.
> No real animation. Decisions tape is Excel. Per-tier panel is
> copy-paste. RTT panel all errs (browser CORS). TradingView feels
> foreign. The reference dashboards (MiroFish, BTC/ETH Polymarket
> Terminals) are clearly hand-coded React with WebSocket-pushed state
> and Framer Motion — Streamlit cannot match that bar.
>
> Anchors:
> - v2.1 critique that drove this rewrite (operator-tested)
> - Bot data map (deep-read 2026-05-09) — see §3
> - Reference screenshots: 3 dashboards operator shared
> - Locked decisions [#10 $1k starting, #15 UTC, #18 vault on laptop only]
> - design/dashboard-v2.md — the v2.1 design doc (kept, not deleted)

---

## 1. Why v3 — and why a full rewrite

The v2.1 layout work was **not wasted**: every Python loader under
`src/polymarket_bot/dashboard/` is correct, the Phase A critique +
Phase B tooling docs stand, and the design tokens in `theme.py` v2
inform v3's palette choices. What gets thrown out is the **rendering
layer** — the Streamlit UI, the .pmb-* CSS classes, the Python
component string-builders.

The fundamental issue: Streamlit's render model (full-script rerun on
every interaction) is hostile to:
- Smooth animations across data updates (the DOM remounts; CSS
  transitions reset)
- WebSocket-pushed real-time state (Streamlit polls)
- Custom interactive charts that maintain client-side state

The reference dashboards demonstrate what the operator wants. Those
dashboards are **single-page React apps with WebSocket-driven Zustand
stores and Framer Motion animations**. To deliver that experience,
v3 is a custom React app — no Streamlit primitives, no autorefresh,
no rerender-everything model.

**What v3 is not**: a port of v2.1's panels. We rethink each panel
from the data and the user's question, not from the previous panel.

---

## 2. Architecture overview

```
[VPS Dublin · eu-west-1]                                  [Laptop]

 ┌─ bot-staging.service ─ writes ─→ state/
 │                                       │
 │  ┌────────────────────────────────────┴────────┐
 │  │ rtt-collector.service (kept from v2)        │
 │  │   pings 5 providers every 10s               │
 │  │   appends state/provider_rtt.jsonl          │
 │  └─────────────────────────────────────────────┘
 │
 │  ┌─ NEW: dashboard-server.service (FastAPI) ──────────────────┐
 │  │  python -m polymarket_bot.dashboard_server                 │
 │  │  - subscribes to Binance/Polymarket WS upstreams           │
 │  │  - reads state/* (decisions, feeds_health, rtt jsonl)      │
 │  │  - composes a single state JSON                            │
 │  │  - serves at 127.0.0.1:8505 with two endpoints:            │
 │  │     GET  /          → static React build                   │
 │  │     GET  /api/state → snapshot JSON                        │
 │  │     WS   /api/live  → diff stream @ 1Hz                    │
 │  └────────────────────────────────────────────────────────────┘
 │
 └─ streamlit-dashboard.service ──── 127.0.0.1:8503 (kept; /audit)

                       │
                       │  SSH tunnel
                       │  -L 8505:127.0.0.1:8505
                       │  -L 8503:127.0.0.1:8503
                       ▼
                                                        ┌──────────┐
                                                        │ browser  │
                                                        │ 127.0.0.1│
                                                        │ :8505 (v3│
                                                        │ :8503 v1)│
                                                        └──────────┘
```

**Keys**:
- v3 React app + FastAPI ship as **one unit** behind one port (8505),
  served as static files by FastAPI itself
- WebSocket lives on the same origin so no CORS
- Streamlit v2.1 stays at 8503 as `/audit` — operator opens explicitly
  for deep-dive
- Both behind the same SSH tunnel script (one tunnel, two `-L` rules)

---

## 3. Real data — what the bot already writes

Every panel in v3 must trace back to a real field on disk or a real
upstream WS message. From the deep-read:

### 3.1 Fired record (`state/decisions/<UTC-date>.jsonl`)
```
kind: "fired"
decision_id: str (uuid hex)
window_ts: int (unix seconds, 5m window start)
decision_ts_ns: int (ns)
asset_id: str (78-digit ERC1155)
side: "UP" | "DOWN"
size_usd: float (5.0 in current config)
price_limit: float (0..1)
ttl_s: int (10..30)
rationale: str (parsed)
snapshot:
  spot_now: float
  window_open_spot: float
  oracle_last: float
  open_oracle: float
  best_bid: float | None
  best_ask: float
  ask_size_top: float | None
composite_pct: null   (always null — drop from UI)
fill: { ts_utc_ns, asset_id, size_filled, price_filled, fee_usd } | None
```

`rationale` parses as: `strategy=spot_aware mode=aggressive|spot_aware
delta_bps=±X.XX p_win=X.XXX ev=±X.XXXX ttl=Xs side=UP|DOWN`

### 3.2 Settled record (same JSONL, written at window close)
```
kind: "settled"
decision_id: str (matches fired)
window_ts: int
settled_ts_ns: int
open_oracle: float | None
close_oracle: float | None
resolution: "UP" | "DOWN" | None
fill_at_settle: {...} | None
pnl_usd: float
resolution_source: str    (added by resolve_decisions: "polymarket")
resolution_oracle_local: str  (the original Chainlink-side answer)
```

### 3.3 Feed health (`state/feeds_health.json`)
Aggregator updates every ~30s. Schema: `{ feeds: { binance, coinbase,
oracle, polymarket: { name, last_seen_ns, msgs_seen, reconnects,
last_error }}}`

### 3.4 Provider RTT (`state/provider_rtt.jsonl`, from v2 collector — KEPT)
Per-line: `{ provider, ts_utc, rtt_ms, status_code, ok }`.
v2's `rtt-collector.service` continues to populate this. v3 reads it
directly from FastAPI.

### 3.5 Halt sentinel (`state/halt.sentinel`)
File-presence flag. v3 surfaces "HALT REQUESTED" badge if present.

### 3.6 Live upstream WS (NEW for v3)
The dashboard server subscribes directly to:
- **Binance** `wss://stream.binance.com:9443/stream?streams=btcusdt@kline_5m/btcusdt@depth20@100ms`
  — 5m candles + depth20 for the live BTC chart and spot orderbook
- **Polymarket** `wss://ws-subscriptions-clob.polymarket.com/ws/market`
  — current window's UP/DOWN tokens for live CTF orderbook

These are **separate** subscriptions from the bot's own feeds — the
dashboard server is read-only, it never interferes with the bot's WS
connections. It also re-subscribes to fresh tokens every 5min as the
window rolls.

### 3.7 What the bot writes that v2.1 *missed*

Per Explore agent finding §F:
- **Spot drift trend over time** — `delta_bps` per decision
- **Priors miss vs hit** — implicit in p_win field; 0.54 ⇒ aggressive
  fallback, otherwise table hit
- **TTL distribution** — `ttl_s` is the actual clamped TTL
- **Feed reconnect spikes** — feeds_health.reconnects over time
- **Resolution disagreement** — `resolution` (Polymarket) vs
  `resolution_oracle_local` (Chainlink): % of decisions where these
  differ is the "oracle drift" health metric
- **Oracle gap at settlement** — `close_oracle - open_oracle` per
  window
- **Snapshot.best_ask vs price_limit** — the slippage budget

v3 surfaces these as a "Bot insights" tab below the main view.

---

## 4. Backend — `src/polymarket_bot/dashboard_server/`

### 4.1 Module layout
```
dashboard_server/
  __init__.py        — package marker
  __main__.py        — `python -m polymarket_bot.dashboard_server`
                       launches uvicorn
  app.py             — FastAPI app, routes, static-files mount
  state.py           — composes the unified state JSON (snapshot)
  diff.py            — diff two state snapshots → minimal patch
  ws_pump.py         — WS endpoint /api/live, broadcasts diffs @ 1Hz
  upstream.py        — Binance/Polymarket WS subscriptions; pushes
                       book + candle updates into state.py
  rtt_jsonl_tail.py  — tails state/provider_rtt.jsonl, integrates into
                       state.py
  decisions_watcher.py — watches state/decisions/*.jsonl + reloads on
                       file change (uses watchfiles, already in deps
                       via uvicorn[standard])
```

### 4.2 State model (`state.py`)

A single `DashboardState` TypedDict (or pydantic model) is the
ground truth that the WS pump broadcasts. Fields, with their *real*
sources:

| Field | Source |
|---|---|
| `now_utc_ns: int` | server clock, refreshed each diff |
| `mode: "AGGRESSIVE" \| "SPOT_AWARE" \| "WAITING"` | parsed from latest decision rationale |
| `bankroll: { starting, current, delta_usd, delta_pct }` | $1k + sum(pnl_usd) |
| `agg: { n_fired, n_filled, n_settled, n_won, win_rate, avg_pnl }` | aggregate over rows |
| `streak: { glyph, n, best_win, worst_loss }` | walk over settled rows |
| `pace: { usd_per_hour, n_settled_60m }` | window over rows |
| `today: { pnl_usd, n_settled }` | filter by date(today) |
| `mode_meta: { strategy, mode, delta_min_bps, delta_max_bps, ev_floor, limit_buffer }` | parsed from latest rationale + env (recommended persistent state/current_config.json for the future) |
| `decisions: list[DecisionTapeRow]` | last 100, newest first |
| `pipeline: { capture, strategy, sim_fill, settle, resolve, persist }` | derived per stage |
| `feeds: list[FeedSnapshot]` | feeds_health.json |
| `processes: { capture, paper }` | psutil.pid_exists |
| `provider_rtt: list[{ name, samples: [ms], last_ms, last_age_s }]` | rtt_loader.load_provider_rtt |
| `tier_breakdown: list[{ tier, n_fired, n_filled, n_settled, n_won, win_rate, pnl }]` | per_tier_stats |
| `trip_wires: list[{ name, current, threshold, breach }]` | aggressive-mode trip wires |
| `halt_requested: bool` | state/halt.sentinel exists |
| `chart: { candles: list[Candle], last_price: float, change_pct }` | from Binance kline WS |
| `spot_book: { asks: [{p,s}], bids: [{p,s}], mid, ts }` | from Binance depth20 WS |
| `ctf_book: { window_ts, side, asks, bids, mid, ts, slug }` | from Polymarket WS |
| `oracle: { open, close, drift_bps, gap_at_settle }` | latest settled record |
| `disagreements: { rate, n_resolved_local, n_resolved_pm, last_disagree_window_ts }` | computed: `resolution != resolution_oracle_local` |

### 4.3 Diff protocol (`diff.py`)

Compute JSON Patch (RFC 6902) between previous and current state. Send
only the patch over WS. First message after connect is a full
snapshot. JSON Patch keeps payloads tiny (a single price tick is
~80 bytes).

### 4.4 WS broadcast (`ws_pump.py`)

```python
@app.websocket("/api/live")
async def live(ws: WebSocket):
    await ws.accept()
    snap = state.snapshot()
    await ws.send_json({"type": "snapshot", "state": snap})
    last = snap
    while True:
        await asyncio.sleep(1.0)
        cur = state.snapshot()
        patch = diff.compute(last, cur)
        if patch:
            await ws.send_json({"type": "patch", "ops": patch})
        last = cur
```

1Hz heartbeat is a starting point. Chart/orderbook updates are pushed
**immediately** when upstream WS messages arrive (off-cadence) so the
chart doesn't lag — see `upstream.py`.

### 4.5 Static-files mount

```python
app.mount("/", StaticFiles(directory="apps/dashboard-v3/dist", html=True))
```

The Vite build output is served directly. No nginx needed for v3
itself; the FastAPI process handles both API and static.

### 4.6 systemd unit (`dashboard-server.service`)

Same shape as `streamlit-dashboard.service` but invokes
`python -m polymarket_bot.dashboard_server`. Bound to `127.0.0.1:8505`.

---

## 5. Frontend — `apps/dashboard-v3/`

### 5.1 Stack

| Lib | Version | Why |
|---|---|---|
| React | 19 | Latest |
| TypeScript | 6 | Strict mode |
| Vite | 8 | Build tool, instant HMR |
| Tailwind v4 | 4.x | Token-driven utility CSS, with `@theme` directive |
| Framer Motion | 12 | Declarative animations, `layout` + `AnimatePresence` |
| lightweight-charts | 5 | TradingView's free OSS — replaces the embed |
| Zustand | 5 | Global state store, plays nicely with WS push |
| TanStack Query | 5 | Initial snapshot fetch + reconnect retry |
| lucide-react | 1.x | Icons |
| react-use | 17 | `useWebSocket`, `useInterval`, `usePrevious` hooks |
| clsx + tailwind-merge | — | Class composition utility |

shadcn/ui primitives (Button, Tabs, Tooltip, Dialog) are copy-pasted
into `apps/dashboard-v3/src/ui/` rather than imported as a package
(per shadcn convention).

### 5.2 Directory layout
```
apps/dashboard-v3/
  index.html
  vite.config.ts
  tsconfig.json
  tailwind.config.ts            (theme tokens — see §7)
  src/
    main.tsx                    — React root + providers
    App.tsx                     — top-level layout + routing
    store/
      dashboardStore.ts         — Zustand store, applies WS patches
      types.ts                  — DashboardState matching backend
    api/
      ws.ts                     — WS client with reconnect + JSON Patch
      snapshot.ts               — initial fetch via TanStack Query
    panels/
      TopStrip.tsx              — brand, market tabs, mode banner, clock
      LiveTape.tsx              — scrolling event ticker
      WalletPanel.tsx           — bankroll + session PnL (digit roll)
      ChartPanel.tsx            — lightweight-charts BTC 5m
      SpotBookPanel.tsx         — Binance L2 depth (animated rows)
      CTFBookPanel.tsx          — Polymarket book (animated rows)
      LivePnlPanel.tsx          — pace, streak, today, best tier
      PipelineStrip.tsx         — 6 numbered execution-cycle stages
      DecisionsTape.tsx         — newest-first, animated row enter
      RTTPanel.tsx              — VPS-side provider RTT bars
      TripWiresPanel.tsx        — aggressive-mode trip wires
      TierBreakdownPanel.tsx    — segmented bars per tier
      InsightsPanel.tsx         — drift trend, oracle gap, disagree rate
    chart/
      lwcInit.ts                — lightweight-charts setup
      candleSubscriber.ts       — wires WS candles into chart
    book/
      AnimatedBook.tsx          — Framer Motion `layout` for both books
      DepthRow.tsx              — single book row with animated bar
    ui/                         — shadcn primitives copied here
      button.tsx, tabs.tsx, tooltip.tsx, dialog.tsx
    lib/
      cn.ts                     — clsx+tailwind-merge helper
      format.ts                 — number/time/age formatters
    motion/
      digitRoll.tsx             — animated digit-roll component
      tickerScroll.tsx          — continuous left-scroll wrapper
      pulseDot.tsx              — pulsing live dot
    styles/
      tokens.css                — design tokens + base styles
```

### 5.3 State store (`dashboardStore.ts`)

Zustand store with one slice per top-level state key. WS handler
applies JSON Patch via `fast-json-patch` (small dep, MIT). On
reconnect: refetch snapshot via TanStack Query and replace whole
state.

### 5.4 Reconnect behaviour

WS drops happen (laptop sleep, tunnel reset). Strategy:
- exponential backoff with jitter (0.5s → 30s cap)
- on reconnect: GET `/api/state` for full snapshot, replace store
- show "RECONNECTING" pill in top strip during retries

---

## 6. Layout — 12-col grid, no scroll

Target viewport: 1440-1920 wide, 900-1080 tall. Above-the-fold fits
in 1080px.

```
┌──────────────────────────────────────────────────────────────────┐
│ TOP STRIP (56px)                                                 │
│  ●LIVE  POLYMARKET 5M · v3  |  AGGRESSIVE  Phase 11.A.2 · 48H   │
│                              gate at 22:26 UTC                   │
│  BTC $77,501  →  PNL +$61.99  56 trades  WIN 57.1%   17:40 UTC  │
├──────────────────────────────────────────────────────────────────┤
│ LIVE TAPE (24px) — continuous left-scroll                        │
│ ▲WIN +$5.88 30-50% UP  ▼LOSS -$5.00 70-85% DOWN  ▲WIN +$2.94 …  │
├──────────────────────────────────────────────────────────────────┤
│ ROW A — 12 cols, ~280px tall                                     │
│ ┌── 3 cols ─┐┌── 5 cols ──────────────┐┌── 4 cols ────────────┐  │
│ │           ││                        ││                      │  │
│ │  WALLET   ││  BTC 5M CHART          ││  POLYMARKET BOOK     │  │
│ │           ││  lightweight-charts    ││  current 5m window   │  │
│ │ +$61.99   ││  green/red candles     ││  ASK red, MID, BID   │  │
│ │ digit roll││  decision-fire markers ││  rows animate        │  │
│ │ ▲ 5.97%   ││  T+5m ETA marker       ││  on price update     │  │
│ │ trades 56 ││                        ││                      │  │
│ │ win 57.1% ││                        ││  rtt: 220ms          │  │
│ │ R/R 2.41  ││                        ││                      │  │
│ │           ││                        ││                      │  │
│ └───────────┘└────────────────────────┘└──────────────────────┘  │
├──────────────────────────────────────────────────────────────────┤
│ ROW B — pipeline (6 numbered stages, full width, ~80px)          │
│ 01 Capture · 02 Strategy · 03 Sim-Fill · 04 Settle · 05 …        │
│ each stage glows on activity (Framer Motion `whileInView`)       │
├──────────────────────────────────────────────────────────────────┤
│ ROW C — 12 cols, ~280px                                          │
│ ┌── 7 cols ──────────────────┐┌── 5 cols ────────────────────┐   │
│ │                            ││                              │   │
│ │  CUMULATIVE PNL            ││  DECISIONS TAPE              │   │
│ │  lightweight-charts area   ││  custom React table          │   │
│ │  green when up, red below  ││  newest at top, slide+fade   │   │
│ │  hover scrubber w/ values  ││  in. row left-border green   │   │
│ │                            ││  for win, red for loss.      │   │
│ │                            ││  PnL cell has horizontal     │   │
│ │                            ││  bar fill behind number.     │   │
│ │                            ││  hover reveals rationale.    │   │
│ └────────────────────────────┘└──────────────────────────────┘   │
├──────────────────────────────────────────────────────────────────┤
│ ROW D — 12 cols, ~140px                                          │
│ ┌─ 4 cols ─┐┌─ 4 cols ─┐┌─ 4 cols ───────────────────────────┐   │
│ │ RTT VPS  ││ TRIP-WIRE││ TIER BREAKDOWN                     │   │
│ │ 5 bars   ││ status   ││ stacked bars (fired/filled/won)    │   │
│ │ live age ││ live     ││ animated grow on update            │   │
│ └──────────┘└──────────┘└────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘

BELOW THE FOLD (scroll):
- INSIGHTS panel: drift trend, oracle gap, disagreement rate, TTL
  distribution (drawer that slides up)
- LINK to /audit (Streamlit v2.1 — for full decision deep-dive)
```

### 6.1 Why this differs from v2.1

| v2.1 | v3 |
|---|---|
| 4-row grid with dense Row 1 (4 panels) | 4-row grid with **lighter** Row A (3 panels), data flows down from there |
| TradingView embed | lightweight-charts inside our DOM with our colors + decision markers |
| Decisions tape was AG-Grid alpine-dark | Custom React table with row-level color codes + per-cell PnL bar + hover-reveal rationale |
| Per-tier was `st.dataframe` | Stacked-bar visualization (fired / filled / settled / won segments) |
| RTT was browser-side JS | Server-side from VPS, pushed via WS |

---

## 7. Design tokens — refined dark terminal

Operator's "dark" instruction stays. Palette is more sophisticated
than v2.1 — closer to the ETH Polymarket Terminal reference (warm
amber on near-black, with cyan and magenta as live-event accents).

```css
@theme {
  /* surfaces */
  --color-bg-page:        #08070a;
  --color-bg-panel:       #0e0d09;
  --color-bg-panel-hi:    #15130c;
  --color-bg-inset:       #050405;
  --color-bg-overlay:     rgba(8, 7, 10, 0.85);

  /* borders */
  --color-border-subtle:  #221e15;
  --color-border-strong:  #36301f;
  --color-border-amber:   #6b4d18;
  --color-border-glow:    rgba(255, 184, 74, 0.30);

  /* text */
  --color-text-primary:   #f5edd6;
  --color-text-secondary: #a08f6a;
  --color-text-muted:     #5a4f3a;
  --color-text-disabled:  #2c281c;

  /* status */
  --color-good:           #6effa1;     /* slightly cooler than v2 */
  --color-good-glow:      rgba(110, 255, 161, 0.20);
  --color-bad:            #ff5c5c;
  --color-bad-glow:       rgba(255, 92, 92, 0.22);
  --color-warn:           #ffb84a;
  --color-warn-glow:      rgba(255, 184, 74, 0.22);
  --color-warn-strong:    #ff9420;

  /* accent — used SPARINGLY for live events */
  --color-accent-cyan:    #58e1ff;
  --color-accent-magenta: #ff6ec7;

  /* typography */
  --font-mono: "JetBrains Mono", "SF Mono", "Menlo", ui-monospace;
  --font-sans: "Inter Display", "Inter", system-ui;
  --font-numeric: "JetBrains Mono", monospace;  /* tabular nums for all numbers */

  /* spacing */
  --sp-1: 4px;  --sp-2: 8px;  --sp-3: 12px; --sp-4: 16px;
  --sp-5: 20px; --sp-6: 24px; --sp-7: 32px; --sp-8: 48px;

  /* radius — Bloomberg flat by default */
  --r-sm: 2px;
  --r-md: 4px;

  /* shadows */
  --shadow-panel: 0 1px 0 rgba(255,255,255,0.02) inset;
  --shadow-glow-good: 0 0 24px var(--color-good-glow);
  --shadow-glow-warn: 0 0 24px var(--color-warn-glow);
}
```

### 7.1 Typography rules
- ALL numerics: `font-feature-settings: "tnum"` (tabular nums)
- Hero PnL: **JetBrains Mono 700 weight, 64px, -0.02em letter-spacing.**
  No more pixelated fonts. The wow comes from animation (digit roll +
  glow pulse), not the typeface.
- Body: JetBrains Mono 11px (the terminal density)
- Panel titles: JetBrains Mono 10px, 700 weight, uppercase, +0.10em
  tracked
- Inter Display reserved for ONE place: the brand "POLYMARKET 5M" in
  the top strip — humanist sans for the only piece of branding.

### 7.2 Color rules
- **Green is reserved for wins** (PnL positive, decision won, feed
  alive, RTT good)
- **Red is reserved for losses** (PnL negative, decision lost, feed
  dead, breach)
- **Amber is the brand accent** (mode banner, cycle counter, "active"
  state)
- **Cyan/magenta** appear ONLY for transient live events (a fire
  pulse, a chart marker fade-in) — never as a panel color

---

## 8. Animation principles — every animation answers a question

| Animation | Question | Trigger | Duration | Easing |
|---|---|---|---|---|
| Live dot pulse | "Is the page live?" | always-on | 1.6s loop | ease-in-out |
| Digit roll on PnL | "Did PnL just change?" | bankroll/session pnl update | 600ms | ease-out |
| Row enter (decisions) | "Did anything fire?" | new decision arrives | 280ms | spring (0.65, 0, 0.30, 1) |
| Row exit (decisions) | older row falling off | scroll past viewport | 200ms | linear |
| Layout reorder (book) | "Is the market moving?" | book level shifts | 240ms | ease-out (Framer `layout`) |
| Tape ticker scroll | "What recently happened?" | continuous | 60s loop | linear |
| Pipeline stage glow | "Is the bot working right now?" | activity in stage | 1.2s | ease-out |
| Trip-wire bar fill | "How close to breach?" | data update | 500ms | ease-out |
| Page load fade-in | first paint | once on mount | 320ms | ease-out |
| Mode banner pulse (amber) | aggressive-mode is ON | always-on while active | 2.4s loop | ease-in-out |
| Decision-fire flash on chart | "We just fired" | new fired record | 600ms | ease-out |

### 8.1 Hard rules
- No animation longer than 1.2s for triggered events (only loops are
  longer)
- No animation triggers on a stable page; the operator's focus must
  not be hijacked by motion when nothing changed
- Respect `prefers-reduced-motion` — the loops stop, transitions
  shorten to 80ms

---

## 9. Routing + hosting

```
http://127.0.0.1:8505/             — v3 React app (this design)
http://127.0.0.1:8505/api/state    — current snapshot (JSON)
http://127.0.0.1:8505/api/live     — WebSocket diff stream
http://127.0.0.1:8503/             — v2.1 Streamlit (kept; deep-dive)
```

The two are **separate processes, separate ports, separate systemd
units**. Operator's primary URL is `:8505`. They click a "Deep-dive
audit" link in v3 that opens `:8503/` in a new tab when they want
v2.1. Both behind the same SSH tunnel:

```bash
ssh -p 2222 -L 8505:127.0.0.1:8505 -L 8503:127.0.0.1:8503 -N pmb-staging
```

`pmb-staging` is a `~/.ssh/config` Host alias the operator already
has (or will configure once for v3 deploy).

---

## 10. Deployment

### 10.1 New systemd unit: `runbooks/staging/dashboard-server.service`

```
[Unit]
Description=Polymarket bot v3 dashboard (FastAPI + React static)
After=network-online.target rtt-collector.service
Wants=network-online.target

[Service]
Type=simple
User=ops
Group=ops
WorkingDirectory=/home/ops/polymarket-5m-bot
Environment=PATH=/home/ops/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PMB_DASH_STATE_DIR=/home/ops/polymarket-5m-bot/state
Environment=PMB_DASHBOARD_HOST=127.0.0.1
Environment=PMB_DASHBOARD_PORT=8505

ExecStart=/home/ops/.local/bin/uv run --quiet python -m polymarket_bot.dashboard_server

Restart=on-failure
RestartSec=10s
StandardOutput=append:/home/ops/polymarket-5m-bot/state/dashboard-server.log
StandardError=inherit

MemoryMax=512M
CPUQuota=50%

NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/home/ops/polymarket-5m-bot/state
ProtectHome=read-only

[Install]
WantedBy=multi-user.target
```

### 10.2 Deploy runbook: `runbooks/staging/deploy-dashboard-v3.md`

Step-by-step:
1. SSH to VPS
2. `git pull` + `uv sync`
3. `cd apps/dashboard-v3 && npm ci && npm run build` (produces
   `apps/dashboard-v3/dist/` static files)
4. Smoke-test: `uv run python -m polymarket_bot.dashboard_server`
5. Install systemd unit + enable + start
6. Verify: `curl :8505/api/state` returns JSON
7. From laptop: `make dash-tunnel` (already supports multiple `-L`)

### 10.3 Tunnel script update

`runbooks/operations/dashboard-tunnel.sh` updated to forward both
ports. Defaults to `pmb-staging` ssh alias; falls back to
`-p 2222 ops@108.132.51.116`.

---

## 11. Tests

### 11.1 Backend (Python)
- `tests/dashboard_server/test_state.py` — snapshot composition is
  deterministic given a fixed state directory
- `tests/dashboard_server/test_diff.py` — JSON Patch round-trip
- `tests/dashboard_server/test_ws_pump.py` — WebSocket
  connect/snapshot/patch sequence using `httpx.AsyncClient`
- `tests/dashboard_server/test_upstream.py` — Binance/Polymarket WS
  message → state field updates (mocked WS)

### 11.2 Frontend (TypeScript)
- `vitest` for component logic (digit-roll, JSON Patch reducer,
  reconnect backoff)
- No browser-rendering tests in v3 ship; Playwright deferred to v3.1

### 11.3 Integration
- `make verify-v3` runs:
  1. `make verify` (Python: ruff/mypy/pytest still green)
  2. `cd apps/dashboard-v3 && npm run build` (TypeScript compile +
     Vite production build with no warnings)

---

## 12. File map

| Path | Purpose | Phase |
|---|---|---|
| `design/dashboard-v3.md` (this file) | Lock | 11.A.X.B.0 |
| `apps/dashboard-v3/` (Vite scaffold) | React frontend | 11.A.X.B.1 |
| `apps/dashboard-v3/src/panels/*.tsx` | All panels | 11.A.X.B.2 |
| `apps/dashboard-v3/src/store/*.ts` | Zustand store | 11.A.X.B.2 |
| `apps/dashboard-v3/src/api/*.ts` | WS + snapshot fetch | 11.A.X.B.2 |
| `apps/dashboard-v3/src/chart/*.ts` | lightweight-charts setup | 11.A.X.B.2 |
| `apps/dashboard-v3/src/motion/*.tsx` | Reusable animation primitives | 11.A.X.B.2 |
| `apps/dashboard-v3/src/ui/*.tsx` | shadcn primitives copied in | 11.A.X.B.1 |
| `src/polymarket_bot/dashboard_server/` | FastAPI backend | 11.A.X.B.3 |
| `runbooks/staging/dashboard-server.service` | systemd unit | 11.A.X.B.4 |
| `runbooks/staging/deploy-dashboard-v3.md` | Deploy runbook | 11.A.X.B.4 |
| `runbooks/operations/dashboard-tunnel.sh` (UPDATED) | Multi-port tunnel | 11.A.X.B.4 |
| `tests/dashboard_server/` | Python tests | 11.A.X.B.3 |
| `Makefile` (verify-v3, dash-v3) | Build/run targets | 11.A.X.B.4 |
| `pyproject.toml` (UPDATED) | + fastapi, uvicorn, aiofiles | 11.A.X.B.0 (DONE) |

### 12.1 Files NOT touched
- All loaders under `src/polymarket_bot/dashboard/` stay (the FastAPI
  backend imports them — they're the real data layer)
- All bot code (`_paper`, `_live`, `strategies`, `feeds`, `agents`,
  `backtest`) stays untouched
- `scripts/dashboard.py` (Streamlit v2.1) stays — reachable at `:8503`
- `src/polymarket_bot/dashboard/theme.py` stays (used by Streamlit
  v2.1)

---

## 13. Out of scope for v3

- Light theme (operator instruction: dark only)
- Public exposure (still tunnel-only)
- Phone access (Tailscale upgrade, separate task)
- Aggregate "all markets" view (Phase 11.D)
- Strategy switcher UI (only one strategy active)
- Order placement / bot control surface (read-only stays the rule)
- Tradingview embed (replaced by lightweight-charts)
- Multi-language i18n (English only)
- User accounts (single operator)

---

## 14. v3 success criteria

The v3 ships when:

1. `design/dashboard-v3.md` (this file) reviewed + approved by operator
2. `make verify` green (zero Python regressions)
3. `cd apps/dashboard-v3 && npm run build` green (zero TS/build
   errors)
4. `make verify-v3` green (combined gate)
5. Operator-timed audit on local v3 dev (running against
   `state/staging/`):
   - "Are we making money?" answerable in <1s ✅
   - "Is the bot firing?" answerable in <1s ✅
   - "Is anything broken?" answerable in <2s ✅
   - "Does it feel alive?" — yes (animations, WS push) ✅
6. VPS deploy via `runbooks/staging/deploy-dashboard-v3.md`
7. Operator approves the visual diff via SSH tunnel
8. Commit pushed; v2.1 stays at `:8503/`

---

## 15. Locked surface (after operator approval)

- **Wire format**: `DashboardState` shape, JSON Patch over WS @ 1Hz
  (off-cadence pushes for chart/book updates)
- **Token system** (§7) — colors, typography, spacing, radius
- **Layout grid** (§6) — 12-col, 4 rows above-fold, drawer below
- **Animation principles** (§8) — every animation answers a question
- **Routing** (§9) — v3 at `:8505`, v2.1 at `:8503`, both tunneled
- **File map** (§12) — additive only; existing files stay

Future v3.x revisions add panels / tweak animation timings without
re-locking. v4 (whenever — possibly the live-trading observability
pass when bot moves to real money) gets its own design doc.

---

## 16. What v3 deliberately does NOT include

Per anti-vibe and honest-data discipline:
- No fake agent network graph (LLM ensemble is CUT — decision #16)
- No fake L2 spot order book (use real Binance depth20 only)
- No invented "convergence %" or "confidence" numbers
- No multi-coin trader portfolio (BTC only)
- No fake "people copying" badge (nobody is copying)
- No trophy-unlock animations on wins (tonally wrong for paper-soak;
  operator might enable later for live)
- No Monte Carlo / Volume Profile / Sentiment / Inventory mini-charts
  (we don't compute them)

The visual density of v3 comes from **real** telemetry — every panel
traces back to a field on disk or an upstream WS message.
