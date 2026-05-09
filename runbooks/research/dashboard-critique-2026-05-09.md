# Dashboard v1 critique — 2026-05-09

> Phase A of the dashboard-overhaul session. Audits the current Streamlit
> dashboard at `scripts/dashboard.py` + `src/polymarket_bot/dashboard/`
> against the eight criteria in `phase-prompts/dashboard-overhaul.txt`.
> Findings drive the v2 redesign locked in `design/dashboard-v2.md`.
>
> Anchors:
> - Current implementation: [scripts/dashboard.py](../../scripts/dashboard.py) (~975 LOC) + [src/polymarket_bot/dashboard/theme.py](../../src/polymarket_bot/dashboard/theme.py) (~680 LOC)
> - v1 design doc: [design/dashboard.md](../../design/dashboard.md)
> - Latest overhaul context: [state/sessions/2026-05-09-spot-aware-aggressive-launch.md](../../state/sessions/2026-05-09-spot-aware-aggressive-launch.md)
> - Operator references: 3 demo screenshots provided 2026-05-09 (MiroFish
>   light-cream terminal, BTC Polymarket light terminal, ETH Polymarket
>   dark amber terminal)

---

## Executive summary

The current dashboard is **functionally complete** — every piece of bot
state is rendered, the data is honest, the colour rules are consistent,
and the recent Phase 11.A.2 overhaul (MODE banner, Fire Rate KPI,
trip-wires, per-tier panel) added the right operator-critical signals.

It is **visually generic**. The structure betrays Streamlit primitives —
`st.columns`, `st.dataframe`, `st.expander` — and the resulting page
reads as "engineering tool" rather than "trader's terminal." The
operator's reference dashboards demonstrate that the same data, restyled
with stronger hierarchy and Bloomberg-terminal aesthetics, can carry far
more meaning per glance.

The eight findings below drive the v2 redesign.

---

## Finding 1 — Information hierarchy is flat

**The single most important number on the page** ("are we making
money?") is currently a 22px KPI card sitting in a row of six equal-
weight cards (Cumulative PnL, Win Rate, Decisions Fired, Fire Rate,
Last Decision, Paper Uptime).

A Bloomberg trader-facing screen reserves one large area for the P&L
hero — the operator's eye should land there before anywhere else.
Current dashboard scatters the eye across six equal targets.

**Reference parallel**: MiroFish dashboard uses a 200-pixel pixel-bitmap
display for cumulative realized PnL ($361,945) — it is the first thing
your eye finds. Our $39.51 deserves the same treatment.

**v2 fix**: pixel-display hero PnL at 96px, Pixelify Sans font, with a
small delta sparkline below. Other KPIs (Fire Rate, Win Streak, Profit
Pace) become satellite cards at standard size.

---

## Finding 2 — At-a-glance state communication: timed audit

Self-timed audit on the live dashboard (`make dash-staging` →
`http://127.0.0.1:8503/`):

| Question | Time to answer (s) | Pass? |
|---|---|---|
| Is the bot firing? | 1s — Last Decision card and Fire Rate card give it | ✅ |
| Are we making money? | 3s — eyes have to find the small Cumulative PnL card | ❌ |
| Is anything broken? | 2s — incident banner shows it but only when populated; in steady state, requires scanning Processes + Feeds + log | ⚠ |

**The "are we making money?" failure is the biggest single defect.**
Three seconds to answer the most important question on the page.

**v2 fix**: hero PnL is the first visual element after the top strip;
nothing else in the page commands attention away from it.

---

## Finding 3 — No event rhythm

The page refreshes every 4 seconds but reads as static. There is no way
to feel **what just happened**. The operator can't tell the difference
between "nothing fired in the last 4s" and "a decision fired, won, and
locked in $5 of PnL." Both look identical between refreshes.

**Reference parallel**: BTC and ETH terminals both feature a "LIVE TAPE"
strip across the top — scrolling stream of recent fills, signals, wins.
This is the heartbeat of the page.

**v2 fix**: 28px live tape immediately below the top strip, scrolling
left at a fixed cadence, fed by the last 12 events from the decision
log. Each tape entry colour-coded by win/loss.

---

## Finding 4 — Decisions table reads as a dataframe, not a product

`st.dataframe` is functional but generic. Newest-first is the right
direction (already implemented), but the table doesn't differentiate
visual weight by outcome — won/lost rows look the same; the PnL column
is just a signed number.

**Reference parallel**: BTC terminal's "RECENT TRADES" panel uses
coloured row backgrounds, larger typography for PnL, and a side glyph
for win/loss. It's the same data, rendered as a tape — much more
legible per row.

**v2 fix**: replace `st.dataframe` with `streamlit-aggrid` and custom
cell renderers. Won rows get a faint green left-border; lost rows get
faint red. PnL column shows a horizontal bar (proportional to absolute
value) with the number overlaid. Composite/Δ_bps/p_win render as
muted tabular nums to keep them readable but secondary.

---

## Finding 5 — Logs eat 20% of above-fold for debug content

The right column (~20% width) is dedicated to a log tail panel, with a
segmented control to switch between paper.log and capture.log. This is
useful **when debugging** but is not what an operator scans for "is the
bot making money?"

**v2 fix**: collapse the log panel into a single tab in the side
column. Keep its full content (we won't lose information), but reduce
its idle-state visual weight. When the incident banner fires, the log
tab auto-expands; otherwise it sits at ~80px tall and shows the latest
single line per stream.

---

## Finding 6 — The bot's actual pipeline is invisible

The bot's execution loop is real and measurable:

```
CAPTURE → STRATEGY → SIM-FILL → SETTLE → RESOLVE → PERSIST
```

Each stage has measurable latency. None of it is shown today.

**Reference parallel**: BTC terminal's "LIVE EXECUTION CYCLE" panel
shows each stage with its current ms timing and a "BUDGET 2.7S /
ELAPSED 1.50S" comparison. It is the single most "trader terminal"
element on the reference page.

**v2 fix**: render a 90px pipeline strip below the hero row. Six stage
boxes (CAPTURE, STRATEGY, SIM-FILL, SETTLE, RESOLVE, PERSIST). Each
shows current ms latency or status (e.g. SETTLE: "5m wait, T-47s").
A stage glows briefly (200ms) when activity hits it. Real data only:
no fake budgets, no invented stages.

Implementation note: the latency for STRATEGY/SIM-FILL/PERSIST can be
captured in the existing decision rationale (or extracted from JSONL
timestamps); CAPTURE latency requires bot-side instrumentation
(deferred — see notes on bot-logic boundary in design/dashboard-v2.md).
For v2 the displayed latencies are derived from JSONL deltas where
available, and shown as "—" otherwise.

---

## Finding 7 — Empty states are inconsistent

Different idioms across panels:

- PnL chart: "No settled decisions yet. Settled records appear after
  the 5-min window closes and oracle resolution lands."
- Decisions table: "No decisions logged yet. Files at
  `state/decisions/<UTC-date>.jsonl` populate as the active strategy
  fires."
- Per-tier panel: "No fires yet to break down by tier."
- Agent panel: "No Phase 3 evidence found. The LLM ensemble runs only
  when explicitly enabled — see `scripts/run_ab.py
  --enable-ensemble`."

Each is correct on its own; together they read as four different
voices.

**v2 fix**: empty-state component with a single voice — short headline,
optional helper text, monospace inline code where useful. Pass to
`design:ux-copy` skill for final wording.

---

## Finding 8 — Future scaling not anticipated

Phase 11.B-F adds ETH alongside BTC; later phases add additional
markets and additional strategies. The current header has no slot for
a market switcher; the loaders are implicitly BTC-only; the layout
assumes one strategy.

**v2 fix**: top strip carries `BTC | ETH | …` market tabs (only BTC
visible until Phase 11.B); loaders take an explicit `market_id`
parameter; layout is parameterized so adding a strategy is a config
change, not a layout rewrite.

---

## Finding 9 (bonus) — Bankroll missing from the page

Cumulative PnL is shown ($+39.51); bankroll ($1,039.51 at session end)
is **nowhere on the page**. Operator needs to do mental math to know
their actual balance.

**v2 fix**: bankroll renders adjacent to the hero PnL — same row,
secondary weight, e.g. "BANKROLL $1,039.51 · STARTED $1,000.00".

---

## Finding 10 (bonus) — Provider latency invisible

The operator runs the bot from Dublin (108.132.51.116:2222) but reads
the dashboard from a UAE laptop. The dashboard shows feeds_health
("X msgs, Y reconnects, last seen Zs ago") but never shows actual
provider response time. When a feed is slow, operator sees only "stale
mtime" — no signal of *which leg* (capture box → bot, bot → provider,
provider → upstream) is the cause.

**v2 fix**: per-provider browser-side RTT sparkline (60-second history)
for Binance, Coinbase, Chainlink, Polymarket Gamma, Polymarket CLOB.
Limitation honestly labelled: "RTT measured from this laptop, not
from the bot's VPS." Bot-side per-message RTT instrumentation is
deferred to a separate follow-up commit (touches `feeds/` — out of
scope per dashboard prompt).

---

## Summary table

| # | Finding | v2 fix | Severity |
|---|---|---|---|
| 1 | Hierarchy flat | Pixel-display hero PnL at 96px | High |
| 2 | "Making money?" takes 3s to answer | Hero PnL becomes first focal point | High |
| 3 | No event rhythm | Live tape ticker | High |
| 4 | Decisions table is generic | streamlit-aggrid + custom cell renderers | Medium |
| 5 | Logs eat 20% above-fold | Collapse to single tab | Medium |
| 6 | Pipeline invisible | 90px pipeline strip below hero | High |
| 7 | Empty states inconsistent | Single component, ux-copy skill pass | Low |
| 8 | Future scaling not anticipated | Market tabs in top strip; market_id loader param | Medium |
| 9 | Bankroll missing | Adjacent to hero PnL | Medium |
| 10 | Provider RTT invisible | Per-provider 60s sparklines | Medium |

---

## What stays from v1

- Two-stage sync pipeline (`decisions.raw/` → resolve → `decisions/`)
- Auto-sync toggle and 30s throttle
- Trip-wire panel (renders only when mode=aggressive)
- Per-tier discipline panel
- MODE banner colour rules (`AGGRESSIVE` red, `SPOT_AWARE` green,
  `DETERMINISTIC` amber, `WAITING` muted)
- Incident banner aggregation logic (`_detect_incidents`)
- Loaders public surface (`DecisionRow`, `ProcessStatus`,
  `HealthSnapshot`, `aggregate_pnl`, `fire_rate_per_hour`,
  `latest_active_mode`, `per_tier_stats`) — all stay; v2 adds new
  loaders alongside, never breaks existing.
- Historical agent panel (collapsed by default; valued for audit trail)

The v2 work is layout + theme + new components. The data interface is
locked.
