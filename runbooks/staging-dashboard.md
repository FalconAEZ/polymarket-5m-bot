# Staging dashboard — viewing VPS bot-staging on your laptop

Phase 5.5+ workflow. The dashboard from Phase 4.5 (`scripts/dashboard.py`) was originally designed for laptop paper-trading; it reads `state/decisions/*.jsonl` + `state/feeds_health.json` + `state/{paper,capture}.log`. With the bot now running on the VPS, those files live at `/home/ops/polymarket-5m-bot/state/` — not on the laptop.

The minimal solution: rsync the VPS state into a `state/staging/` mirror locally, then point the existing dashboard at it via `PMB_DASH_STATE_DIR`. No dashboard code changes.

## One-shot view

```bash
make dash-staging   # rsyncs from VPS, then opens the dashboard pointed at the mirror
```

Or split it:

```bash
make sync-staging                                                # pull VPS state
PMB_DASH_STATE_DIR=state/staging uv run streamlit run scripts/dashboard.py
```

## What `make sync-staging` does

[runbooks/scripts/sync_staging.sh](scripts/sync_staging.sh):
1. `rsync -az --delete` of `/home/ops/polymarket-5m-bot/state/decisions/` → `state/staging/decisions/`.
2. `rsync` of the token-side index for completeness.
3. `journalctl -u bot-staging.service --since "24 hours ago"` → `state/staging/paper.log`.
4. `journalctl -u tg-alerter.service --since "24 hours ago"` → `state/staging/capture.log` (the dashboard's "capture" tab is repurposed for the alerter).
5. `runbooks/scripts/synthesize_feeds_health.py` produces a best-effort `state/staging/feeds_health.json` from the unit's `is-active` state + journal grep.
6. Prints a one-shot live status block (uptime, queue depth, DLQ depth, decision count, sentinel state) pulled fresh over SSH.

`state/staging/` is git-ignored (it's a mirror, not source-of-truth).

## Known caveats

- **PROCESSES panel says "OFFLINE / no PID file"** even when `bot-staging.service` is healthy. The dashboard uses `psutil` to verify a *local* PID — it has no way to check a remote process. Source of truth in this mode is the **LIVE LOGS** panel (real journal lines) and the terminal output of `make sync-staging`. Will be fixed properly when the bot exposes Prometheus metrics (per design/alerter.md §9).
- **Feeds panel `msgs_seen` always shows 0**. The bot doesn't write a `feeds_health.json` (Phase 4.5 capture script did, but capture isn't running on the VPS). The synthesizer can only confirm "feeds running" or "not", not message counts. Ditto: real fix when Prometheus metrics land.
- **Data is a snapshot**, not live-streamed. Re-run `make sync-staging` to refresh; the dashboard's auto-refresh just re-reads the local mirror.

## Required env / paths

The sync script defaults to:
- key:  `~/Downloads/LightsailDefaultKey-eu-west-1.pem` (override with `LIGHTSAIL_KEY`)
- host: `ops@108.132.51.116`                            (override with `VPS_HOST`)
- port: `2222`                                          (override with `VPS_PORT`)
