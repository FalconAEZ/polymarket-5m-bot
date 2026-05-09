# Dashboard v2 tooling options — 2026-05-09

> Phase B of the dashboard-overhaul session. Concrete picks for the
> skills, MCPs, and GitHub repos used during the v2 redesign work.
>
> Companion to `dashboard-critique-2026-05-09.md` (Phase A) and
> `design/dashboard-v2.md` (the lock that drives implementation).

---

## Skills to invoke during the v2 workflow

All listed skills are in the standard `design:*` skill pack and
require no setup. Invoke with `Skill / <name>` from the worktree.

| Skill | When to invoke | Concrete v2 use |
|---|---|---|
| `design:design-critique` | After v2 mockup screenshots exist; before commit | Run blind on before/after PNGs to surface hierarchy / spacing / contrast issues I missed |
| `design:design-system` | While drafting `theme.py` v2 | Audit colour and spacing tokens for naming consistency; current `theme.py` has 4 bg- variables and no documented baseline — collapse to a 3-tier scale |
| `design:ux-copy` | After Finding 7 fix | Single voice for empty states (chart, table, agents, per-tier); MODE banner subtitle; segmented-control labels |
| `design:accessibility-review` | After theme tokens locked | Verify WCAG AA contrast on the dark Bloomberg palette (esp. amber-on-black for the warning state) and minimum touch targets on the segmented control |
| `design:design-handoff` | Before implementation | Translate the locked `design/dashboard-v2.md` into a token-by-token spec sheet so the implementation step has zero ambiguity |

Workflow order: `design-system` (audit current) → write `dashboard-v2.md` →
`design-handoff` (spec sheet) → implement → `design-critique` + `accessibility-review` (review) → `ux-copy` (final pass on empty-state copy) → commit.

---

## MCPs (already wired)

### Claude in Chrome
- **Status**: configured for this project
- **v2 use**:
  - drive `http://127.0.0.1:8503/` after each implementation slice
  - capture before/after annotated screenshots for the commit (saved to `runbooks/research/dashboard-v2-screenshots/`)
  - iterate CSS in DevTools live before locking it into `theme.py`
- **Caveat**: requires the dashboard to be running locally. Start with `make dash-staging` if not already up.

### Claude Preview MCP
- **Status**: configured
- **v2 use**: faster inner-loop iteration than Chrome — `preview_screenshot` after each `theme.py` edit, no browser tab required
- **Caveat**: separate process from `make dash-staging`; uses its own preview port

---

## Repositories — installed and use cases

All three primary deps installed via `uv add` in the worktree
(2026-05-09); pyproject.toml updated, uv.lock regenerated. Final
inclusion gated on operator approval of `design/dashboard-v2.md`.

### streamlit-shadcn-ui (v0.1.19)
- **License**: MIT
- **What it does**: shadcn-style React components (cards, badges,
  tabs, buttons, alerts) wrapped as Streamlit components
- **v2 use**:
  - `ui.badges` for the MODE banner (replaces our hand-rolled
    `pmb-badge` HTML — same look, more consistent)
  - `ui.tabs` for the BTC | ETH market switcher in the top strip
  - `ui.alert` for the incident banner (replaces `pmb-incident`)
  - **NOT** for the hero PnL — pixel-display rendering needs raw
    HTML for font-feature control
- **Cost**: each component is a separate iframe (~50ms render each);
  acceptable for the 4-5 we use. Don't go iframe-crazy.
- **Install**: `uv add streamlit-shadcn-ui` (done)

### streamlit-aggrid (v1.2.1.post2)
- **License**: MIT (AG-Grid Community Edition)
- **What it does**: AG-Grid bindings — sortable, virtualized,
  themeable, custom-cell-renderable data grid
- **v2 use**:
  - replaces `st.dataframe` in the decisions tape
  - cell renderers: PnL bar (proportional horizontal bar with
    overlaid number), win/lost glyph column, side colour-coded
- **Cost**: ~2MB JS bundle, iframe-rendered. Worth it for the
  decisions table specifically; avoid for tables that don't need
  custom rendering.
- **Install**: `uv add streamlit-aggrid` (done)

### plotly (v6.7.0)
- **License**: MIT
- **What it does**: charting with built-in transition animations
- **v2 use**:
  - replaces Altair PnL chart — smoother live updates (transition
    on data refresh), native crosshair, dark-theme native
  - per-provider 60s RTT sparklines (5 mini-charts in the health
    column)
- **Cost**: ~50MB install footprint. Already partially in our stack
  via Streamlit transitives, so net add is small.
- **Install**: `uv add plotly` (done)

### streamlit-extras (v1.5.0) — transitive bonus
- **License**: Apache-2.0
- **What it does**: catch-all utility components (colored_header,
  metric_cards, mention, etc.)
- **v2 use**: opportunistic — `metric_cards` may be useful for the
  satellite KPIs (Fire Rate, Win Streak, Profit Pace) if shadcn
  doesn't fit
- **Cost**: zero (came in as transitive)
- **Install**: already installed

---

## Repositories — evaluated and rejected

### streamlit-elements
- **What it does**: runs MUI/Nivo charts inside a single persistent
  React tree
- **Why rejected**: heavyweight (~5MB JS), and the persistent-state
  benefit is cancelled by Streamlit's full-script rerender model.
  shadcn-ui + aggrid + plotly cover the same ground at half the cost.
- **Reconsider if**: we hit Streamlit re-render flicker that we
  can't fix with the existing toolkit.

### streamlit-lottie
- **What it does**: Lottie JSON animations
- **Why rejected**: only place we'd use it (trade-fired pulse, mode-
  switch transition) is doable in pure CSS at lower cost. Lottie
  would add a 200KB+ bundle for animations the user wouldn't
  visually distinguish from a CSS keyframe.
- **Reconsider if**: we want explicit win/loss "trophy unlock"
  animations later (currently rejected as tonally wrong for a
  paper-soak observability tool).

### vizro (McKinsey)
- **What it does**: declarative dashboard builder layered on Plotly
- **Why rejected**: too opinionated; locks layout into vizro's
  configuration model. We have specific Bloomberg-terminal layout
  intent that doesn't match vizro's defaults.
- **Use as**: reference only — their gallery is worth a 5-minute
  scan for layout pattern ideas before we commit.

---

## Live external feeds for v2 (not pip-installable, browser-side only)

### Binance WS — BTC L2 spot orderbook
- **Endpoint**: `wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms`
- **Latency**: 100ms updates, lowest publicly available
- **Render**: top 10 bid + top 10 ask depth bars, with last-trade
  price overlay
- **Honest label**: "BTC SPOT REFERENCE · Binance"
- **Failure mode**: WS reconnect loop (handled in JS); panel goes
  amber on >10s without messages

### TradingView 5m candle widget
- **Endpoint**: standard TradingView free embed (BTCUSDT, 5m
  interval, dark theme)
- **Latency**: ~2-3s candle latency (good enough)
- **Render**: 280px tall, no toolbar, no symbol search — just the
  candles and volume
- **Honest label**: same as above, paired with the L2 depth panel

### Polymarket CLOB — current 5m market orderbook
- **Endpoint**: `py-clob-client.get_order_book(token_id)`, polled
  every 2s
- **Latency**: ~1-2s (REST polling)
- **Render**: 8 levels each side, with last-trade overlay
- **Honest label**: "OUR MARKET · BTC ↑/↓ 5M · Polymarket CLOB"
- **Caveat**: this requires resolving the current 5m window's UP
  and DOWN token IDs — derivable from the current window_ts +
  the slug pattern `btc-updown-5m-<window_ts>`. Loader handles
  the lookup; renders "—" gracefully when the window hasn't
  opened yet.

### Browser-side RTT to 5 providers
- **Method**: `fetch()` to a low-cost endpoint per provider, time
  the round-trip:
  - Binance: `https://api.binance.com/api/v3/time`
  - Coinbase: `https://api.exchange.coinbase.com/time`
  - Chainlink: configured RPC `eth_blockNumber`
  - Polymarket Gamma: `https://gamma-api.polymarket.com/markets?limit=1`
  - Polymarket CLOB: `https://clob.polymarket.com/time`
- **Cadence**: every 10s; keeps a 60s sliding window per provider
- **Render**: 60px sparkline per provider in the health column,
  with current ms value overlaid
- **Honest label** (small, prominent): "RTT measured from this
  laptop, not from the bot's VPS." This is critical — operator
  must not confuse browser RTT with bot RTT.

---

## Bot-side latency hook — separate follow-up commit

Per the dashboard prompt, this session **does not touch bot logic**.
True per-message bot-to-provider RTT requires a one-line hook in each
feed's WS message handler:

```python
# In each feeds/<provider>.py message handler:
self.health.last_rtt_ms = (time.monotonic_ns() - msg.send_ts_ns) / 1e6
```

That hook lands as a **separate commit in the same PR** as the
dashboard v2 work. Each commit is operator-approved separately. The
follow-up commit:

1. Adds `last_rtt_ms` field to feeds_health.json schema
2. Adds the one-line hook to each of the 4 feeds
3. Adds 1 test verifying the hook populates correctly
4. Updates the dashboard v2 to render bot-side RTT *alongside*
   browser RTT (so operator sees both)

Estimated effort: ~30 minutes. Lands as commit 2 of the PR.

---

## Decision matrix

| Component | Library | Reason |
|---|---|---|
| Hero PnL pixel display | raw HTML + CSS + Pixelify Sans (Google Fonts) | Need precise font-feature control |
| MODE banner | streamlit-shadcn-ui `ui.badges` | Drop-in upgrade |
| Market tabs (BTC \| ETH \| ...) | streamlit-shadcn-ui `ui.tabs` | Native segmented look |
| Live tape ticker | raw HTML + CSS keyframe animation | Continuous scroll; no library does this well |
| Pipeline strip | raw HTML + CSS | 6 boxes, simple flex layout |
| Hero PnL chart | plotly | Built-in transitions |
| Decisions tape | streamlit-aggrid | Custom cell renderers |
| Per-provider RTT sparklines | plotly | 5 small charts; same lib as main chart |
| Spot orderbook depth | raw HTML + JS via `st.components.v1.html` | Direct WS to Binance |
| 5m candle chart | TradingView free embed via `st.components.v1.html` | Standard widget |
| Polymarket CTF orderbook | raw HTML + py-clob-client polled | REST-only |
| Trip-wire panel | unchanged from v1 (well-designed already) | No reason to rewrite |
| Per-tier panel | unchanged from v1 | Same |
| Live logs | unchanged from v1 | Already collapsed to one tab in v2 layout |
| Auto-sync mechanism | unchanged from v1 | Two-stage pipeline works |

---

## Risks

1. **iframe overhead** — shadcn-ui + aggrid + plotly + 2 raw HTML
   widgets = 6+ iframes per page. Each costs ~30-80ms of render
   time and a separate JS context. Page may feel slower on first
   load. Mitigation: lazy-render below-the-fold panels, measure
   first-paint after implementation.

2. **External-feed dependency** — TradingView embed and Binance WS
   add new external dependencies. If either is down, the page
   degrades. Mitigation: render placeholder ("BTC SPOT — feed
   offline") on JS error, and make sure the bot-side data panels
   keep working when the orderbook panels fail.

3. **Polymarket CTF orderbook polling cost** — 2s polling × 5
   active dashboards × hours = many API calls. Mitigation: dashboard
   throttles itself; if multiple operators view simultaneously, only
   one polls (sentinel file mechanism similar to sync_staging.sh).

4. **AG-Grid dark theme** — the community AG-Grid theme is light by
   default; we use `ag-theme-alpine-dark`. Verify cell padding and
   font-size match our 11px JetBrains Mono baseline.

5. **Pixelify Sans Google Fonts dependency** — page already loads
   Google Fonts (Inter, JetBrains Mono); Pixelify Sans is one more
   font request. Negligible perf impact, fits the existing pattern.

---

## Final go list

```
INSTALL (done):
  uv add streamlit-shadcn-ui   # ui components
  uv add streamlit-aggrid      # decisions tape
  uv add plotly                # charts + sparklines
  # streamlit-extras pulled in as transitive

INVOKE (during v2 work, in this order):
  Skill / design:design-system          # audit theme.py tokens
  Skill / design:design-handoff         # spec sheet from dashboard-v2.md
  Skill / design:design-critique        # blind review on screenshots
  Skill / design:accessibility-review   # WCAG AA pass
  Skill / design:ux-copy                # empty-state wording

DO NOT INSTALL:
  streamlit-elements   # too heavy
  streamlit-lottie     # CSS achieves the same
  vizro                # too opinionated
```
