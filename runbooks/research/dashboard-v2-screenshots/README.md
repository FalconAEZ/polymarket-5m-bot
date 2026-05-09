# Dashboard v2 — visual diff capture

> Visual diff captured 2026-05-09 in the conversation that produced this
> commit. The screenshots themselves are inline in that chat record;
> this file documents how to regenerate them and what each shows. No
> headless browser was available in the build environment to commit
> PNGs at the time of writing — adding `playwright` for that is queued
> as a follow-up.

## Regenerate the visual diff

Two parallel Streamlit instances against the live aggressive-mode soak
data:

```bash
# v1 (baseline) — port 8511
PMB_DASH_V2=0 PMB_DASH_STATE_DIR=/Users/hamad/Desktop/PolyMarket-5m/state/staging \
  uv run streamlit run scripts/dashboard.py \
  --server.headless=true --server.port=8511

# v2 (new) — port 8512
PMB_DASH_V2=1 PMB_DASH_STATE_DIR=/Users/hamad/Desktop/PolyMarket-5m/state/staging \
  uv run streamlit run scripts/dashboard.py \
  --server.headless=true --server.port=8512
```

Or via Make:

```bash
make dash-staging      # v1, default port 8503
make dash-staging-v2   # v2, default port 8503 with PMB_DASH_V2=1
```

The launch.json file at `.claude/launch.json` has the two preview-MCP
configurations under names `dashboard-v1-screenshot` and
`dashboard-v2-screenshot` — use those if iterating with the Preview
MCP.

## What v2 shows that v1 doesn't

Captured against the same data (`state/staging` mid-aggressive-mode-
soak, PnL +$61.99, 56 settled, 32 won):

| Panel | v1 | v2 |
|---|---|---|
| Cumulative PnL | 22px KPI card, one of six | **96px Pixelify Sans hero**, dominant focal point |
| Bankroll | not shown | top-strip chip: `BANKROLL $1,061.99 +6.20% started $1,000` |
| Live tape | not present | 28px scrolling tape with last 12 settled events |
| Pipeline | not visible | 6-stage strip: CAPTURE / STRATEGY / SIM-FILL / SETTLE / RESOLVE / PERSIST with per-stage latency + status |
| Streak | not present | `▲ 5 · best 5W · worst 6L` satellite |
| Profit Pace | not present | `+$32.48/hr · last 60m` satellite |
| Provider RTT | not present | 5 sparklines (Binance, Coinbase, Chainlink, PM-Gamma, PM-CLOB) measured browser-side, with the "from this laptop, not the bot's VPS" caveat |
| BTC spot orderbook | not present | live Binance L2 via WS, top 10 each side |
| BTC 5m candle chart | not present | TradingView dark-theme embed |
| Polymarket CTF orderbook | not present | live for current 5m window via py-clob-client (e.g. `OUR MARKET · DOWN · btc-updown-5m-1778276700`, MID 0.7250) |
| Decisions table | `st.dataframe` | `streamlit-aggrid` alpine-dark with sortable columns |
| PnL chart | Altair area | Plotly area (smoother live updates) |
| Market switcher | none | `BTC | + ETH SOON` placeholder for Phase 11.B |
| Theme | grayscale dark | warm Bloomberg-terminal cream-on-near-black with amber accents |
| Typography | Inter humanist | JetBrains Mono terminal |

## What v2 deliberately does NOT show

Per design/dashboard-v2.md §14 (out-of-scope):

- No fake L2 depth — only real Binance + real Polymarket CTF
- No fake agent graph — LLM ensemble was CUT (decision #16); panel stays
  as the historical Phase 3 record
- No "people copying" badge — nobody is copying
- No Monte Carlo / sentiment / inventory sub-charts — we don't compute them
- No trade-fired Lottie / trophy animations — tonally wrong for paper-soak
- No light theme — operator instruction was dark only

## Bot-side latency follow-up

The provider RTT widget measures BROWSER → provider, not BOT → provider.
The follow-up commit in this PR adds a one-line hook to each feed in
`src/polymarket_bot/feeds/*` that measures bot-side per-message RTT and
writes it into `feeds_health.json`. The v2 dashboard renders it
alongside the browser-side reading once that hook lands. Tracked in
`design/dashboard-v2.md` §10.
