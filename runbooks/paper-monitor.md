# Paper-mode monitor runbook — Phase 4 task 4.4

**Goal.** Run `scripts/run_paper.py` for **14 calendar days** in the
background on the operator's laptop, alongside the existing capture
process (PID was 23820 at Phase 3 close — do NOT kill it). Each day
the operator inspects the decision log + health snapshot; the Phase 4
gate fires at the end of the 14 days, evaluating decision-level
accuracy, fill divergence, and net P&L.

This runbook is the operator's daily checklist + pre-flight + stop
procedure. The runtime itself is in `scripts/run_paper.py` and
`src/polymarket_bot/_paper/`. The Phase 4 gate that consumes this
data lives at `runbooks/gates/phase-4.sh` (do not run it before the
14-day window completes).

## Pre-flight

[ ] `cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca`
[ ] `git rev-parse HEAD` is at or after `phase-3-pass`.
[ ] `make verify` green (ruff + mypy + 246 pytest pass).
[ ] `uv run lint-imports` → 2 contracts kept.
[ ] Capture process still alive:
    ```bash
    cat state/capture.pid && kill -0 $(cat state/capture.pid) && echo OK
    cat state/feeds_health.json | jq '.feeds | to_entries | map({(.key): .value.healthy}) | add'
    ```
    All four feeds healthy. If the capture is dead → re-launch via
    `runbooks/capture-launch.md` Option A *before* starting paper mode.
[ ] No prior paper run is running:
    ```bash
    cat state/paper.pid 2>/dev/null && kill -0 $(cat state/paper.pid) 2>/dev/null && echo "ALIVE — stop it first"
    ```
    If alive, stop cleanly (see "Stop the run" below) before re-launching.
[ ] `.envrc` populated with `POLYGON_RPC_URL` (oracle feed) and any
    optional `TELEGRAM_*` variables. `POLY_*` keys are unused here.
[ ] **Window selection.** The 14-day window must include at least:
    - 1 CPI / FOMC release day (high vol)
    - 1 weekend (low vol)
    - 1 BTC daily move > 2% (regime stress)
    Per RUNBOOK §4 pre-flight. If today's date doesn't make this
    possible inside 14 days, surface to the operator before launching.

## Launch

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca
mkdir -p state state/decisions

set -a; source /Users/hamad/Desktop/PolyMarket-5m/.envrc; set +a
PATH="$HOME/.local/bin:$PATH" \
  nohup uv run python -u scripts/run_paper.py \
  >> state/paper.log 2>&1 &
echo $! > state/paper.pid
disown
echo "launched: paper-pid=$(cat state/paper.pid) log=state/paper.log"
```

`-u` forces unbuffered stdout. `nohup` + `disown` survives shell exit.
Mirrors `runbooks/capture-launch.md` Option A.

## Verify (90 seconds after launch)

```bash
sleep 90
tail -40 state/paper.log
ls -la state/decisions/
```

Pass criteria:
- `state/paper.log` contains "paper-mode runtime up; waiting for SIGTERM/SIGINT".
- "initial warm: <N> new windows; <M> tokens mapped overall" — M ≥ 2.
- The `polymarket_bot._paper.runner` logger should NOT show repeated
  errors (the Strategy might not have fired yet — that's normal at
  this scale; the deterministic baseline at threshold 0.6pp may go
  many windows without firing).
- `state/decisions/` exists. May be empty until the first decision
  fires (could be hours).

## Daily ritual

Run once a day for 14 days:

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca

# 1. Paper process alive
kill -0 $(cat state/paper.pid) && echo paper-alive
# 2. Capture process alive
kill -0 $(cat state/capture.pid) && echo capture-alive
# 3. Feeds healthy
cat state/feeds_health.json | jq '.snapshot_ts_utc, .feeds | to_entries | map({(.key): {msgs: .value.msgs_seen, healthy: .value.healthy}}) | add'
# 4. Most-recent decisions
ls -la state/decisions/
tail -1 state/decisions/$(date -u +%F).jsonl 2>/dev/null | jq

# 5. Today's tally
python3 - <<'PY'
import json
from pathlib import Path
import datetime
date = datetime.datetime.utcnow().strftime("%Y-%m-%d")
path = Path(f"state/decisions/{date}.jsonl")
if not path.exists():
    print(f"no decisions yet for {date}")
else:
    fired = settled = 0
    pnl = 0.0
    won = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec["kind"] == "fired":
            fired += 1
        elif rec["kind"] == "settled":
            settled += 1
            pnl += rec.get("pnl_usd", 0.0)
            if rec.get("pnl_usd", 0.0) > 0:
                won += 1
    print(f"date={date}  fired={fired}  settled={settled}  won={won}  pnl=${pnl:+.2f}")
PY

# 6. Tail of paper log for any errors
tail -20 state/paper.log
```

What to investigate:
- **Paper or capture dead.** Re-launch (see "Recovery" below) and write
  an incident note in `runbooks/incidents/<date>-<slug>.md`.
- **Feeds unhealthy.** Same as `capture-launch.md` Troubleshooting —
  the live feeds are shared between capture and paper.
- **`fired` lines without matching `settled` lines past T+5min.** Means
  the runner crashed mid-window or a window-boundary event was missed.
  Confirm with `tail -100 state/paper.log` and incident if needed.
- **Per-decision `delta_cents` (eyeballed in the snapshot vs. fill
  block) staying > 5¢ over the day.** Simulator divergence — reproduces
  the Phase 4.3 gap. Note in the daily checkpoint; do NOT change the
  simulator parameters mid-run (would invalidate the data).
- **Negative cumulative P&L compounding.** Expected at small samples
  given Phase 3 backtest's −$6.16 baseline. Real trend visible only
  after ≥ 7 days. Don't pre-empt the gate.

## Recovery

### Paper process died

```bash
cat state/paper.pid && kill -0 $(cat state/paper.pid) 2>&1 || echo dead
tail -80 state/paper.log
# fix root cause (env, dep, network), then:
rm -f state/paper.pid
# re-run "Launch" section
```

The capture process is independent; do NOT kill capture to recover paper.

### Laptop sleep risk

Same as `capture-launch.md`:
- Plug into power for the full 14 days.
- `caffeinate -i &` in a separate shell, or System Settings → Lock Screen.
- If laptop sleeps, both processes stop. Bytes already written stay; the
  14-day window must be extended by the gap (or the run restarted).

## Stop the run cleanly

```bash
cd /Users/hamad/Desktop/PolyMarket-5m/.claude/worktrees/bold-galileo-2d56ca
kill -INT $(cat state/paper.pid)   # SIGINT → graceful drain + flush
sleep 5
kill -0 $(cat state/paper.pid) 2>/dev/null || echo "process exited cleanly"
rm -f state/paper.pid
```

The graceful path:
1. Runner sees stop_event → cancels feed pumps + warmer.
2. PaperRunner drains the in-flight queue.
3. DecisionLog flushes + closes per-date JSONL handles.
4. Exits with `dropped_records=N` line in `state/paper.log`.

Hard kill (only if graceful fails): `kill -9 $(cat state/paper.pid)`.
Loses ≤ 1 in-flight line per open JSONL handle (DecisionLog flushes on
every write; only a partial trailing line is at risk). The capture's
Parquet archive is unaffected — separate process.

## After 14 days

1. Stop the run cleanly (above).
2. Open `runbooks/gates/phase-4.sh` (do not modify; just review the
   assertions it checks).
3. Run the gate: `bash runbooks/gates/phase-4.sh` — output goes to
   `runbooks/gate-evidence/phase-4.txt`.
4. If green: tag `phase-4-pass`, write `checkpoint_phase_4.md` memory,
   advance to Phase 5 (VPS provisioning).
5. If red: write `runbooks/incidents/phase-4-<date>.md` with the failed
   gate criterion + diagnostics, escalate. Do not advance to Phase 5
   with a failing paper-trade verification.
