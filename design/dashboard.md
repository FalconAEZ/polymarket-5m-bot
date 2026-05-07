# Design — Operations Dashboard (Phase 4.5)

> Purpose: lock the architecture for a single-page Streamlit dashboard
> the operator runs locally to monitor the paper-mode runtime. Reads
> only — never writes back into the runtime, never imports anything
> that mutates state. Anti-vibe rule #1: this doc lands and locks
> before any code under `src/polymarket_bot/dashboard/` or
> `scripts/dashboard.py`.
>
> Anchors:
> - `design/paper.md` (Phase 4) — DecisionLog JSONL schema this dashboard reads
> - `design/data_plane.md` — `state/feeds_health.json` schema
> - locked decisions [#15 UTC everywhere, #18 Obsidian on laptop only]
> - operator-context: laptop ↔ Windows-PC migration; dashboard must be
>   cross-platform (`os.kill(pid, 0)` doesn't work on Windows; use psutil).
>
> Out of scope for this doc: real-time WS push (Streamlit's auto-refresh
> is enough for a 5m-window bot), authentication (it binds to localhost
> only), production observability on the VPS (Phase 5 brings Prometheus +
> Grafana Cloud — this dashboard is laptop-only operator monitoring).

---

## 1. Why a dashboard exists at this phase

The Phase 4 paper run produces:

  - JSONL decisions at `state/decisions/<UTC-date>.jsonl`
  - feed health snapshot at `state/feeds_health.json` (every 30s)
  - logs at `state/paper.log`, `state/capture.log`
  - PIDs at `state/paper.pid`, `state/capture.pid`

The 14-day daily ritual in `runbooks/paper-monitor.md` is a series of
`jq` + `tail` + a Python tally script. It works, but:

  1. **Operator's laptop sleeps.** A 14-day uninterrupted clock on a
     MacBook Pro that travels is unrealistic. The dashboard makes
     **interruptions visible** so the operator can reason about
     coverage gaps rather than silently believing the wall-clock.
  2. **Migration to a Windows PC is planned.** A web dashboard at
     `localhost:8501` works the same on macOS and Windows; the bash
     ritual depends on `jq` + zsh. Cross-platform UI removes one
     environment-bug surface.
  3. **The decision log is dense.** A table of `(window_ts, side,
     fill, resolution, pnl)` is much more useful as a sortable
     panel than as 60-character JSONL lines.

Phase 5 brings Prometheus + Grafana on the VPS. That stack serves
production observability (metrics, alerting, on-call); this dashboard
serves laptop operator review. Both can coexist; neither replaces the
other.

## 2. Architecture — read-only consumer of `state/`

```
       ┌──────────────────────────────────────────────────────┐
       │           Streamlit single-page app                  │
       │           scripts/dashboard.py                       │
       │                                                      │
       │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
       │   │  System     │  │  Feeds      │  │  Process    │  │
       │   │  health     │  │  health     │  │  uptime     │  │
       │   └─────────────┘  └─────────────┘  └─────────────┘  │
       │                                                      │
       │   ┌─────────────────────────────────────────────────┐│
       │   │   Decisions table (sortable, date-filtered)     ││
       │   └─────────────────────────────────────────────────┘│
       │                                                      │
       │   ┌─────────────────────┐  ┌─────────────────────┐   │
       │   │   PnL chart         │  │  Win-rate trend     │   │
       │   └─────────────────────┘  └─────────────────────┘   │
       │                                                      │
       │   ┌─────────────────────────────────────────────────┐│
       │   │   Recent log tails (paper.log + capture.log)    ││
       │   └─────────────────────────────────────────────────┘│
       └────────────────────┬─────────────────────────────────┘
                            │ reads (no writes)
            ┌───────────────┼─────────────────────┐
            ▼               ▼                     ▼
       state/decisions/  state/feeds_health.json  state/{paper,capture}.pid
       *.jsonl           state/paper.log          os/psutil for "is alive?"
                         state/capture.log
```

**Why Streamlit.** Single-file app, no JS toolchain, professional default
look, auto-refresh built-in via `st.experimental_rerun` + a refresh
timer, cross-platform via `pip install streamlit`. Trade-off: slightly
heavyweight (~50 MB of deps). Acceptable since this is operator-side
tooling, not bot runtime.

**Why no auth.** Streamlit binds to `127.0.0.1:8501` by default; the
operator runs it on the same machine as the bot. No remote access; no
auth needed. If Phase 5 ever wants remote dashboards, that's the point
the Grafana stack takes over.

**Why no real-time push.** Decisions fire at most once per 5m window.
Auto-refresh every 10-30 seconds catches every state change with
acceptable latency. Streamlit's `st.autorefresh()` covers this.

## 3. Import boundaries (anti-vibe rule #7)

A new top-level package `polymarket_bot.dashboard`. Its imports:

  - `polymarket_bot._paper.decision_log` — uses `read_jsonl` and
    `join_fired_settled` (pure read-helpers, already public).
  - `polymarket_bot.feeds.protocols` — for the `Health` TypedDict shape.

It does NOT import:
  - `polymarket_bot._live.*` — dashboard reads `state/feeds_health.json`
    directly as JSON; never instantiates a Feed.
  - `polymarket_bot._paper.runner` / `polymarket_bot._paper.shadow_book`
    — dashboard does not run the strategy; it just reads its output.
  - Anything from `polymarket_bot.backtest` or `polymarket_bot.strategies`
    — the dashboard is observability, not backtest replay.

We add a third import-linter contract:

```ini
[importlinter:contract:layered3]
name = dashboard never imports live, paper-runtime, backtest, or strategies
type = forbidden
source_modules = polymarket_bot.dashboard
forbidden_modules =
    polymarket_bot._live
    polymarket_bot._paper.runner
    polymarket_bot._paper.shadow_book
    polymarket_bot.backtest
    polymarket_bot.strategies
    polymarket_bot.agents
```

This locks the "dashboard is observability only" rule. The two existing
contracts stay unchanged.

## 4. Component contracts

### 4.1 Loaders (`src/polymarket_bot/dashboard/loaders.py`)

Pure functions; no Streamlit imports. Tests under `tests/dashboard/`
cover each. No async — Streamlit's runtime is sync.

```python
@dataclass(frozen=True, slots=True)
class ProcessStatus:
    name: str           # "capture" | "paper"
    pid: int | None     # None if pid file absent
    alive: bool         # False if pid file present but process gone
    pid_file: Path

@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    name: str
    msgs_seen: int
    healthy: bool
    reconnects: int
    last_error: str
    last_seen_ns: int   # for "X seconds ago" rendering

@dataclass(frozen=True, slots=True)
class DecisionRow:
    """Joined fired+settled record. Settled fields are None until window closes."""
    decision_id: str
    window_ts: int                # 5m window start (UTC seconds)
    decision_dt_utc: datetime
    asset_id: str
    side: Side                    # "UP" | "DOWN"
    size_usd: float
    price_limit: float
    ttl_s: int
    composite_pct: float | None
    fill_price: float | None
    fee_usd: float | None
    resolution: Side | None
    pnl_usd: float | None         # 0.0 if no fill; None if not yet settled

def load_process_status(state_dir: Path) -> tuple[ProcessStatus, ProcessStatus]:
    """Read state/capture.pid and state/paper.pid; check process aliveness."""

def load_feeds_health(state_dir: Path) -> list[FeedSnapshot] | None:
    """Read state/feeds_health.json. None if missing or malformed."""

def load_decisions(decisions_dir: Path, *, since_utc_date: str | None = None) -> list[DecisionRow]:
    """Walk state/decisions/*.jsonl and join fired+settled by decision_id.

    Sorted ascending by decision_dt_utc. since_utc_date filter (YYYY-MM-DD)
    drops everything older.
    """

def tail_log(path: Path, *, n_lines: int = 40) -> list[str]:
    """Last N lines of a log file. Empty list if missing."""
```

**Why dataclasses, not raw dicts.** Streamlit's `st.dataframe` accepts
either, but the loaders are unit-testable with structured types. The
dashboard module converts to pandas DataFrames at the rendering layer.

**Cross-platform process check.** `psutil.pid_exists(pid)` works on
macOS, Linux, and Windows identically. `os.kill(pid, 0)` on Windows
behaves differently (no SIGNAL 0 concept) — psutil normalizes this.

### 4.2 App (`scripts/dashboard.py`)

Streamlit script — single file, ~250 lines. Structure:

```python
def main() -> None:
    st.set_page_config(page_title="Polymarket Bot — Operations", layout="wide")
    st.title("Polymarket 5m BTC Bot — Operations")

    # Sidebar: refresh interval + state-dir override + date filter
    refresh_s = st.sidebar.slider("Auto-refresh (seconds)", 5, 60, 15)
    state_dir = Path(st.sidebar.text_input("state/ dir", value="state"))
    date_filter = st.sidebar.date_input("Decisions since", value=...)

    st_autorefresh(interval=refresh_s * 1000, key="refresh")

    _render_system_health(state_dir)
    _render_feeds_health(state_dir)
    _render_decisions_table(state_dir, date_filter)
    _render_pnl_charts(state_dir, date_filter)
    _render_log_tails(state_dir)
```

Each `_render_*` panel is a thin wrapper over the loaders + Streamlit
widgets. Streamlit auto-reruns the whole script on refresh; loaders are
fast enough (file I/O, no DB) that no caching is required for v1.

### 4.3 What goes in each panel

**Visual design system.** Custom CSS injected via `st.markdown` to
override Streamlit defaults toward a deliberate, dense-but-clean
financial-tooling aesthetic:

  - Dark theme via `.streamlit/config.toml` (base = "dark", primaryColor
    = `#1ed760`, backgroundColor = `#0d1117`, secondary = `#161b22`)
  - Typography: Inter / SF Pro stack; tabular-nums for all numbers;
    larger weights for KPI hero values, regular weight for labels
  - Status colors: `--good = #1ed760` (green), `--warn = #f0b400`
    (amber), `--bad = #ff5572` (red), `--muted = #8b949e` (gray)
  - Card pattern: every panel inside a `<div class="card">` with
    1px border, 12px radius, 16px padding — consistent visual rhythm

**Layout (top to bottom):**

```
┌─────────────────────────────────────────────────────────────────┐
│  HEADER: title + last-refresh + "since: <date>" + refresh button│
├─────────────────────────────────────────────────────────────────┤
│  KPI ROW (st.columns([1,1,1,1,1])) — five hero cards            │
│  Cumulative PnL │ Win-rate │ Decisions │ Avg PnL/trade │ Uptime │
├─────────────────────────────────────────────────────────────────┤
│  CENTER HERO: live PnL chart (full-width, ~360px tall)          │
│   - Cumulative PnL line over decision_dt_utc                    │
│   - Color: green when positive, red when negative               │
│   - Zero baseline + per-day vertical separators                 │
├─────────────────────────────────────────────────────────────────┤
│  SYSTEM ROW (2 cols)                                            │
│  ┌──────────────┐   ┌──────────────────────────────────────┐    │
│  │ Process card │   │ Feeds health card (4 mini-stats)     │    │
│  │ capture +    │   │ binance / coinbase / oracle /        │    │
│  │ paper status │   │ polymarket — msgs, healthy, reconns  │    │
│  └──────────────┘   └──────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────────────┤
│  AGENT ACTIVITY PANEL (full-width)                              │
│  - "LIVE" badge if ensemble enabled, "HISTORICAL" badge if not  │
│  - When live: most recent ensemble votes from JSONL             │
│  - When historical: parsed transcript from                      │
│    runbooks/gate-evidence/phase-3.3-llm-ab.txt                  │
│  - Each entry: window_ts, three specialist votes (orderbook /   │
│    oracle-gap / momentum), Sonnet meta verdict, latency, cost   │
├─────────────────────────────────────────────────────────────────┤
│  DECISIONS TABLE (full-width, st.dataframe with filters)        │
│  - sortable, 50-row paginated                                   │
│  - columns: dt, side, asset (truncated), limit, fill, resolved, │
│    pnl, composite_pct                                           │
├─────────────────────────────────────────────────────────────────┤
│  LIVE LOGS (2-col tabs)                                         │
│  ┌──────────────────────┐   ┌──────────────────────────────┐    │
│  │  paper.log (last 60) │   │  capture.log (last 60)       │    │
│  │  color-coded INFO/   │   │  color-coded by level        │    │
│  │  WARN/ERROR          │   │                              │    │
│  └──────────────────────┘   └──────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

**KPI hero cards:**
  - Cumulative PnL: $X.XX (green/red), with delta vs yesterday
  - Win rate: 60.0% (small "n=15" subscript)
  - Decisions: total fired / total settled
  - Avg PnL/trade: ${X.XX}
  - Uptime: paper-process uptime hours; ⚠ if < 24h

**Live PnL center hero (`st.altair_chart`, 360px height):**
  - X axis: decision_dt_utc, full date range
  - Y axis: cumulative pnl_usd
  - Line color encoded by sign (green above zero, red below)
  - Zero baseline (gray dashed)
  - Tooltip on hover shows window_ts + that decision's pnl + cumulative
  - Per-day vertical rule (thin gray) to separate sessions

**Agent activity panel:**
  - Header: "LIVE" badge (green) when paper-mode ensemble is enabled,
    else "HISTORICAL · Phase 3 A/B evidence" badge (amber)
  - Body when live: per-decision row showing the three specialist
    votes + Sonnet verdict + latency + cost. Reads from extended
    DecisionLog schema (Phase 8 work; not part of v1 dashboard build —
    panel scaffolding present, populates when ensemble flag enabled)
  - Body when historical: parsed transcript from
    `runbooks/gate-evidence/phase-3.3-llm-ab.txt`. One row per
    window decision; columns: window_ts, agent_orderbook,
    agent_oracle_gap, agent_momentum, meta_verdict, latency_s,
    cost_usd
  - Why have it at all when ensemble is CUT: gives the operator a
    visceral sense of what the ensemble used to look like and primes
    the panel for Phase 8 re-enable. Per locked decision #16 the
    ensemble code is retained.

**Live logs:**
  - 2 tabs side-by-side
  - 60 most recent lines each
  - Color rule: lines containing " ERROR " or "Traceback" → red;
    " WARN " → amber; everything else → muted gray
  - Stale badge if file mtime > 5 min ago
  - Auto-scrolls to bottom on refresh

## 5. State files committed to git

`state/` is gitignored today. To support the Mac→Windows migration
(operator pulls fresh on Windows; runs without re-capturing the macOS
data), we make ONE narrow exception:

```gitignore
# Phase 4.5: keep decision-log JSONL in git so the dashboard
# has data the moment the repo is cloned on a new machine.
# Everything else under state/ stays excluded — parquet is too big,
# logs are too noisy, pid files are obviously machine-local.
state/
!state/decisions/
!state/decisions/*.jsonl
```

Sizes: each fired+settled pair is ~700 bytes JSON. 14 days * 288
windows/day * fire-rate = at most a few thousand lines per day. Total
< 10 MB across the run. Manageable as text-in-git.

NOT committed:
  - `state/*.parquet`, `state/feeds_health.json` (recoverable on the
    next capture run; the dashboard handles their absence gracefully)
  - `state/paper.log`, `state/capture.log` (machine-local; would leak
    machine-specific paths and host names)
  - `state/*.pid` (obviously machine-local)
  - `state/sessions/`, `state/postmortems/` (Obsidian-style notes;
    locked decision #18 keeps these laptop-only)

## 6. Cross-platform notes

- `psutil.pid_exists()` handles macOS/Linux/Windows uniformly.
- All paths are `pathlib.Path`; no shell-outs to `tail`/`cat`/`jq`.
- `os.path.getmtime(path)` for stale-file detection works everywhere.
- No `os.kill(pid, signal.SIGTERM)` from the dashboard — it's read-only.
  Stop/start happens via the existing runbook commands.
- Log tails read with `seek` to last ~64KB then split by newline. Avoids
  `tail` shellout; works on Windows where Unix `tail` may be absent.

## 7. Test discipline (anti-vibe rule #6)

- `tests/dashboard/test_loaders.py`:
  - `load_process_status` with synthetic pid files (alive PID = own
    process; dead PID = a high-numbered random PID; missing PID file)
  - `load_feeds_health` with synthetic JSON; missing file; malformed
    JSON; partial schema
  - `load_decisions` with synthetic JSONL fixtures: fired-only, fired
    + settled, settled-only (orphan), date filter, multiple files
  - `tail_log` with synthetic file: shorter than n_lines; longer; empty;
    missing; binary-noise lines; UTF-8
- No tests on Streamlit UI code itself (the framework's job).
- 246 + ~20 dashboard tests = ~266 total target.

## 8. Dependencies

Added to `pyproject.toml`:
  - `streamlit>=1.51.0` — single-page UI
  - `psutil>=7.2.0` — cross-platform PID checks
  - `pandas>=2.3.4` — Streamlit's preferred dataframe; charts use it
  - `altair>=5.5.0` — Streamlit's default charting (already a transitive)

Install size impact: ~80MB. All laptop-side; no impact on bot runtime.

## 9. File map

| Path | Phase | Purpose |
|---|---|---|
| `design/dashboard.md` (this file) | 4.5.0 | Architecture, locked first |
| `src/polymarket_bot/dashboard/__init__.py` | 4.5.1 | Package marker |
| `src/polymarket_bot/dashboard/loaders.py` | 4.5.1 | Pure-function loaders |
| `src/polymarket_bot/dashboard/agents_loader.py` | 4.5.1 | Phase 3 A/B transcript parser |
| `src/polymarket_bot/dashboard/theme.py` | 4.5.2 | Custom CSS injection |
| `scripts/dashboard.py` | 4.5.2 | Streamlit single-page app |
| `.streamlit/config.toml` | 4.5.2 | Dark theme config |
| `tests/dashboard/__init__.py` | 4.5.1 | Package marker |
| `tests/dashboard/test_loaders.py` | 4.5.1 | Loader tests |
| `tests/dashboard/test_agents_loader.py` | 4.5.1 | Transcript parser tests |
| `runbooks/dashboard.md` | 4.5.3 | Operator runbook (launch, daily use) |
| `runbooks/gates/phase-4.5.sh` | 4.5.3 | Gate script |
| `RUNBOOK.md` | 4.5.4 | Add Phase 4.5 entry between Phase 4 and Phase 5 |
| `.gitignore` | 4.5.0 | Un-ignore `state/decisions/*.jsonl` |
| `.importlinter` | 4.5.0 | Add contract 3 |
| `pyproject.toml` | 4.5.0 | Add streamlit + psutil + pandas |

## 10. Phase 4.5 success looks like

```
$ make gate-4.5
=== Phase 4.5 gate ===
1. make verify         OK   (266 tests pass)
2. lint-imports        OK   (3 contracts kept)
3. dashboard import    OK   (scripts/dashboard.py imports without errors)
4. headless smoke      OK   (streamlit hello rendered with synthetic state/)
=== Phase 4.5 gate green ===
```

Tag `phase-4.5-pass` by hand on green. Phase 4.5 is purely additive
observability — passing it does not unblock Phase 5; Phase 5 still
gates on the Phase 4 14-day evidence.

## 11. Locked

`DecisionRow` shape + `loaders.py` public surface are locked. Streamlit
panels can be reorganized without breaking the contract; the loader
output is the durable interface. Adding new panels in v2 (e.g. a
sim-validation histogram, a regime-coverage tracker) is allowed without
a design-doc revision provided they only consume existing loader
outputs.

The "JSONL committed to git" exception is locked at exactly
`state/decisions/*.jsonl`. Anything else under `state/` (logs, parquet,
pid, sessions, postmortems) stays gitignored.
