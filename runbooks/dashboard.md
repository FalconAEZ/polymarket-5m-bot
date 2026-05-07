# Dashboard runbook — Phase 4.5

**Goal.** Operate the Streamlit operations dashboard at `localhost:8501`
to monitor the running paper-mode bot. Read-only by design — the
dashboard never sends signals, never writes JSONL, never starts/stops
processes. It's a glanceable view over `state/`.

## Prerequisites

[ ] `make verify` green (ruff + mypy + pytest).
[ ] `uv sync` has installed streamlit + psutil + pandas + altair.
[ ] On a fresh checkout, `state/decisions/*.jsonl` is populated by
    git (Phase 4.5 narrowed the .gitignore to track this subpath only).
    Other `state/` files are machine-local and recreated when the
    capture / paper runner starts on this machine.

## Launch

```bash
cd /path/to/polymarket-5m-bot
uv run streamlit run scripts/dashboard.py
# or, for headless (no browser auto-open):
uv run streamlit run scripts/dashboard.py --server.headless=true
```

Open `http://127.0.0.1:8501` in any browser. The page binds to
localhost only — no remote access; no auth.

## What you see

Top-to-bottom:

1. **Header strip** — title + last-refresh timestamp + active date filter.
2. **5 KPI hero cards** — Cumulative PnL (green/red), Win Rate, Decisions
   Fired (with filled count), Paper Uptime (red if process is dead),
   Strategy Mode (DETERMINISTIC; ensemble is currently CUT per Phase 3
   OD-5).
3. **Cumulative PnL chart** — full-width Altair area chart over decision
   timestamps. Empty state if no settled decisions yet (expected at
   threshold 0.6pp).
4. **Processes + Feeds health row** — capture/paper PID + uptime;
   per-feed (binance, coinbase, oracle, polymarket) msgs / reconnects /
   last error. Stale-snapshot badge if `state/feeds_health.json` mtime
   is > 5 min ago.
5. **Agent Activity panel** — currently HISTORICAL: parsed from the
   Phase 3 A/B evidence (`runbooks/gate-evidence/phase-3.3-llm-ab.txt`)
   to show what 26 ensemble decisions looked like. The verdict (CUT)
   is read from `runbooks/decisions/llm-ab-result.md`. When ensemble
   is enabled live in Phase 8, this panel switches to LIVE mode and
   shows per-window agent votes from the extended decision-log schema.
6. **Decisions table** — every row from `state/decisions/*.jsonl` (newest
   first), sortable, with When / Side / Asset / Limit / Fill /
   Resolution / PnL / Composite / TTL columns.
7. **Live logs** — paper.log + capture.log tabs, last 60 lines each,
   color-coded by level (errors red, warnings amber, info muted).

## Sidebar controls

- **Auto-refresh (sec)**: 5–60s slider. The page refreshes via a
  `<meta http-equiv="refresh">` tag — light, browser-native, no JS.
- **state/ dir**: override if running against a different state dir
  (e.g. a previous run's data preserved on disk).
- **Decisions since (YYYY-MM-DD)**: filter for the decisions table.
  Default is "today − 14 days".

## Daily ritual (replaces the jq script in `paper-monitor.md`)

1. Open the dashboard.
2. Glance at the KPI row: PnL, Win Rate, Paper Uptime.
3. Confirm Processes + Feeds badges are green.
4. Skim Decisions table for any anomalies (e.g. a decision with
   `Composite` near zero — possible misfire).
5. Skim Live Logs tabs for `ERROR` lines (color-coded red).
6. If anything looks off, drop into the terminal and run the diagnostic
   block from `runbooks/paper-monitor.md`.

## Cross-platform notes

- The dashboard is fully cross-platform. PID liveness uses `psutil`
  (works on macOS, Linux, Windows identically — no `kill -0` shellout).
- Log tails read with `seek` to the last 64KB; no Unix `tail` dependency.
- The dashboard runs on Windows with an identical command (`uv run
  streamlit run scripts/dashboard.py`).

## Migration: Mac → Windows

When migrating to a fresh Windows checkout:

1. Clone the repo on Windows.
2. `uv sync` — installs all deps including streamlit.
3. `state/decisions/*.jsonl` arrives via git (per the Phase 4.5
   .gitignore exception). The dashboard renders historical decisions
   immediately.
4. Other state files (parquet, feeds_health, paper.log) are absent
   until the operator launches `scripts/run_capture.py` +
   `scripts/run_paper.py` on the new machine. The dashboard handles
   this gracefully — empty Processes panel, "no feeds_health.json"
   note, etc.
5. The new run's JSONL file (e.g. `2026-05-15.jsonl`) appends to the
   git-tracked directory. Commit it after each session if you want
   the data on the next clone.

## Stop / restart

The dashboard process runs in the foreground by default. `Ctrl-C`
stops it. If launched in the background:

```bash
# find and stop
lsof -i :8501 | grep streamlit
pkill -f "streamlit run scripts/dashboard.py"
```

Restart is just re-running the launch command.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| "module not found: streamlit" | `uv sync` skipped | `uv sync` from project root |
| Page loads but says "no feeds_health.json" | capture isn't running on this machine | start capture (`runbooks/capture-launch.md`) |
| Decisions table empty after 14 days | strategy never fired (threshold 0.6pp too high for the regime) | expected; matches Phase 3 deterministic baseline |
| Browser caches old version | meta-refresh not enough | hard reload (Cmd-Shift-R / Ctrl-Shift-R) |
| Port 8501 already in use | previous Streamlit didn't shut down | `pkill -f streamlit` then relaunch |

## What this dashboard is NOT

- Not a Grafana replacement. Phase 5 brings Prometheus + Grafana Cloud
  for production VPS observability. They serve different purposes.
- Not a control panel. No buttons that start, stop, or reconfigure
  the bot. All control flow remains in `runbooks/paper-monitor.md`
  and `runbooks/capture-launch.md`.
- Not a backtest tool. To re-run a backtest with different parameters,
  use `scripts/run_backtest.py`.
