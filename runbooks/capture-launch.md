# Capture launch runbook — Phase 2 Task 2.5

**Goal.** Run the four-feed capture (`scripts/run_capture.py`) for 7
calendar days uninterrupted in a `tmux` session on the operator's laptop.
The captured data feeds the Phase 2.6 oracle-behavior gate next session.

## Prerequisites

- `bold-galileo-2d56ca` worktree clean and at `phase-2-tasks-2.0-2.4b-complete`
  (or later) with `make verify` green.
- `.envrc` at `/Users/hamad/Desktop/PolyMarket-5m/.envrc` populated with the
  4 Phase-0 vars (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHAT_ID`, `POLYGON_RPC_URL` as `wss://...`) and the 4 Phase-1A
  vars (`POLY_PRIVATE_KEY`, `POLY_API_KEY`, `POLY_API_SECRET`,
  `POLY_API_PASSPHRASE`). The capture only reads `POLYGON_RPC_URL` and the
  optional `TELEGRAM_*` for outage alerts; the `POLY_*` vars are unused
  by Phase 2 but live in the same file.
- A long-lived process manager. Three options, in order of preference:
  1. **tmux** (preferred — supports re-attach for live debugging). Not
     installed on this laptop at Phase 2 launch time. Install later via
     `brew install tmux` if/when Homebrew is set up.
  2. **screen** (system-installed at `/usr/bin/screen`, version 4.00.03
     from 2006 — old but works).
  3. **nohup + PID file** (the path used at Phase 2 launch since 1 and 2
     were not available). Process survives shell exit; cannot re-attach
     interactively but is monitored entirely through `state/capture.log`
     and `state/feeds_health.json`, so re-attach is not load-bearing.
- No prior capture is running. Check: `cat state/capture.pid 2>/dev/null`
  and verify the PID is dead with `kill -0 <pid>`. If alive and stale,
  `kill <pid>` it and remove the PID file.
- Capture-target paths are clean: `rm -rf ticks/ state/` from the worktree
  root if a previous capture left partial data you want to discard.
  (Both are gitignored.)

## Launch

From the bold-galileo worktree root:

### Option A — nohup (used at Phase 2 launch; works without extra deps)

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca
mkdir -p state ticks

set -a; source /Users/hamad/Desktop/PolyMarket-5m/.envrc; set +a
PATH="$HOME/.local/bin:$PATH" \
  nohup uv run python -u scripts/run_capture.py \
  >> state/capture.log 2>&1 &
echo $! > state/capture.pid
disown
echo "launched: pid=$(cat state/capture.pid)  log=state/capture.log"
```

`-u` on python forces unbuffered stdout so the log file flushes in real
time. `nohup` + `disown` detaches the process from the shell so it
survives shell exit.

### Option B — tmux (if installed)

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca
tmux new-session -d -s pmbot-capture \
  "set -a && source /Users/hamad/Desktop/PolyMarket-5m/.envrc && set +a && \
   PATH=\"\$HOME/.local/bin:\$PATH\" \
   uv run python -u scripts/run_capture.py 2>&1 | tee -a state/capture.log"
```

Re-attach with `tmux attach -t pmbot-capture`; detach with `Ctrl-b d`.

### Option C — screen (system-installed but ancient)

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca
/usr/bin/screen -dmS pmbot-capture bash -c \
  'set -a && source /Users/hamad/Desktop/PolyMarket-5m/.envrc && set +a && \
   PATH="$HOME/.local/bin:$PATH" \
   uv run python -u scripts/run_capture.py 2>&1 | tee -a state/capture.log'
```

Re-attach with `/usr/bin/screen -r pmbot-capture`; detach with `Ctrl-a d`.

## Verify (90 seconds after launch)

```bash
sleep 90
cat state/feeds_health.json | jq
```

Pass criteria:
- All four feeds present: `binance`, `coinbase`, `oracle`, `polymarket`.
- All four `msgs_seen > 0`. (Oracle only fires on a Chainlink heartbeat —
  ~33s observed, ~60s claimed — so 90s is just enough to see at least one;
  if msgs_seen == 0 and `lag_ms` is small, give it another 30 seconds.)
- All four `last_seen_ns` within 30s of "now".
- `dropped_records_total == 0`.
- `reconnects` for each feed should be 0 (or low — a transient WS hiccup
  is OK; > 5 reconnects in the first 90s is a red flag).

## Daily checks (during the 7-day capture window)

Run these once a day; the operator picks any time:

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca

# 1. Health snapshot age (should be < 1 minute since the last 30s tick)
ls -la state/feeds_health.json
cat state/feeds_health.json | jq '.snapshot_ts_utc, .feeds | to_entries | map({(.key): {msgs_seen: .value.msgs_seen, healthy: .value.healthy, reconnects: .value.reconnects}}) | add'

# 2. Yesterday's parquet files non-zero and growing relative to the day before
ls -lh ticks/$(date -u -v-1d +%F)/   # day before yesterday for comparison
ls -lh ticks/$(date -u +%F)/          # today

# 3. tmux session still alive
tmux ls | grep pmbot-capture

# 4. Tail of the capture log for any recent errors
tail -40 state/capture.log
```

If any check fails, see "Troubleshooting" below.

## Troubleshooting

### Capture process died

`kill -0 $(cat state/capture.pid)` returns non-zero (or the PID file is
gone). Reasons:
- Laptop slept (the most common cause).
- Process crashed (read `state/capture.log`).
- OOM kill (read `dmesg` or Console.app).

**Recovery.** Re-launch as above. The captured data so far stays on disk;
the next cycle's parquet files append to the same `ticks/<date>/` directory
(pyarrow's ParquetWriter creates a new file per (date, source) pair on
each launch, so the new launch's records land in distinct files alongside
the old).

### Some feed shows `healthy: false`

Look at `last_error` for that feed:

| Pattern | Likely cause | Action |
|---|---|---|
| `ConnectionResetError`, `TimeoutError` | Transient WS hiccup | None — feed reconnects with exp backoff |
| `gamma-miss: slug=...` | Polymarket window not yet on Gamma | None — feed retries at next 300s boundary |
| `gamma-err: HTTPError ...` | Gamma API blip | None — feed retries on next window rotation |
| `RuntimeError: eth_subscribe error` | Alchemy blocked the subscription | Check Alchemy app's quota / WS plan |
| Persistent (> 5min) for any feed | Feed dead | Re-attach tmux, read log, restart if needed |

Re-attach: `tmux attach -t pmbot-capture`. Detach without killing:
`Ctrl-b d`.

### `dropped_records_total > 0`

The 10k queue filled. This means the Parquet writer fell behind the feeds.
Almost never happens at our message rates — if it does, capture the value
and tell the operator. **Do not** raise the queue cap reactively; the
drop-oldest policy is the design choice.

### Laptop sleep risk

`tmux` survives terminal exit but **not** sleep. If the laptop sleeps:
- The tmux session disappears.
- The capture stops.
- Bytes already on disk stay; future bytes don't arrive.

Recommended:
- Plug the laptop into power for the full 7 days.
- `caffeinate -i &` in a separate shell to prevent idle sleep
  (Activity Monitor or System Settings: Lock Screen also work).
- Or run the capture on the Dublin VPS — when that's available (see
  RUNBOOK.md Phase 5).

The Phase 2 gate's "≥ 7 dated directories" check tolerates short gaps
(see `runbooks/gates/phase-2.sh` once written), but the cross-feed sanity
check (any randomly chosen 5-min window must have all four feeds
covered) is much stricter and penalizes any gap.

## Stop the capture cleanly

### nohup launch (Option A)

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca
kill -INT $(cat state/capture.pid)   # SIGINT → graceful drain + flush
sleep 5
# verify exit
kill -0 $(cat state/capture.pid) 2>/dev/null || echo "process exited cleanly"
rm -f state/capture.pid
```

### tmux launch (Option B)

```bash
tmux send-keys -t pmbot-capture C-c   # SIGINT → graceful drain + flush
sleep 5
tmux kill-session -t pmbot-capture
```

The graceful path:
1. Runtime sees stop_event → cancels feed tasks.
2. Pushes None sentinel to the queue → writer drains and flushes.
3. Closes Parquet writers → final row groups committed.
4. Exits with a `records_written=N dropped=M` line in `state/capture.log`.

Hard kill (only if graceful fails):

```bash
kill -9 $(cat state/capture.pid)
# OR: tmux kill-session -t pmbot-capture
```

This loses ≤ 5s of unflushed records (the writer's flush cadence). The
parquet files already on disk stay intact — pyarrow `ParquetWriter`
flushes a file footer on each `write_table` call.

## After 7 days of capture

Start a new Claude Code session and use
`~/Desktop/phase-2-analysis-prompt.txt` to run task 2.6 + the formal
gate:

```bash
make gate-2   # invokes runbooks/gates/phase-2.sh
```

If the gate is green: tag `phase-2-pass`, write the checkpoint memory,
and Phase 3 is unblocked.

If the gate is red: open `runbooks/incidents/oracle-behavior-N.md` and
escalate. Do not advance to Phase 3 with a failing oracle-behavior
verification — that is the entire reason this phase exists.
