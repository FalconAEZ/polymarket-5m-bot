# Session — 2026-05-09 — orphan-FD incident response + dashboard-v3 polish

**Branch:** `claude/trusting-spence-03c165` (commits `ac80f9b`, `8838545` ahead of `76e104b`).
**VPS:** all three services restarted; both deploys verified live; bot has clean FDs.
**Soak status:** aggressive-mode 48h gate at 2026-05-10 22:26:15 UTC remains valid; ~3 minutes of bot downtime across two restarts; 0 decisions lost.

## What happened

The session was supposed to be Phase 11.A.X.B dashboard-v3 polish (5 visual bugs from operator screenshots). Pre-flight diagnosis revealed the actual numbers in the dashboard were wrong by ~3×, and the bot's open append FDs on `state/decisions/{2026-05-08,2026-05-09}.jsonl` were marked `(deleted)` in `lsof`. Real bot was firing fine; visible files were frozen at 04:14 UTC with 100/74 lines while the orphan inodes had 308/74. Dashboard was reading from the dead snapshot.

Root cause traced (postmortem: `runbooks/incidents/2026-05-09-orphan-fd-decisions.md`):

- `git reflog` showed `git reset` + `git checkout` at 04:05:02 UTC on the live VPS bot's working tree, plus two `git pull`s. JSONL files are gitignored so git itself didn't rewrite them.
- A 1-second SSH session at 04:13:41 from the operator's IP fits a one-shot remote command. Most likely culprit: `scripts/resolve_decisions.py state/decisions/` (legacy single-arg in-place mode) — its `tmp.write_text + tmp.rename(target)` pattern atomically replaces the inode at the same path, orphaning any concurrent append FD.
- The bot's `_paper.decision_log.DecisionLog` had no inode-stability check, so it kept writing into the unlinked inode for 8.5 hours.
- Dashboard had no staleness wire that compared "most recent decision row timestamp" to wall-clock + bot liveness, so the operator-visible signal was that everything was fine.

## What landed

### Commit `ac80f9b` — incident response

1. **`DecisionLog` self-healing** (`src/polymarket_bot/_paper/decision_log.py`). Before each write, compares path's `(st_dev, st_ino)` to the open FD's `os.fstat`. On mismatch: salvages orphan content via `/proc/self/fd/<n>` (Linux) to a `*.recovered` sibling, closes orphan, reopens against the live path, logs WARN. 3 new regression tests cover atomic-rename replacement, no-false-trip, unlink-recovery.
2. **`resolve_decisions.py` refuses in-place mode** (`scripts/resolve_decisions.py`). Legacy single-arg form removed. Two-arg form is the only mode; rejects `src.resolve() == dst.resolve()`. `sync_staging.sh` already used two-arg mode, no callers break.
3. **Dashboard staleness incident wire** (`src/polymarket_bot/dashboard_server/state.py`). `snapshot()` emits `"decisions JSONL stale: last fire <X> ago while bot alive"` whenever the most recent fired decision is older than `DECISIONS_STALE_THRESHOLD_S = 30 min` AND the paper process is alive — the orphan-FD signature.
4. Postmortem at `runbooks/incidents/2026-05-09-orphan-fd-decisions.md`.

### Commit `8838545` — Phase A polish

| # | Bug | Fix |
| --- | --- | --- |
| A.1 | Wallet panel % wrong | Already fixed in `e44dde8`; this session's `git pull` deployed it. |
| A.2 | iOS Safari chart bleed | `ChartPanel.tsx`: `autoSize:false` + `ResizeObserver` driving `chart.applyOptions({ width, height })` with floored ints. |
| A.3 | Decisions tape spillover on Safari | `DecisionsTape.tsx`: `flex-1 min-h-0` on scroll container. `App.tsx`: `min-h-0` on every Row A/C/D grid cell. |
| A.4 | RTT thresholds too aggressive + Chainlink 403s | `RTTPanel.tsx`: thresholds 200/600 → 300/800ms. `provider_rtt.py`: Chainlink URL `eth.llamarpc.com` → `cloudflare-eth.com` (responds 200 to GET). |
| A.5 | Pipeline 0/0 FEEDS | **Deferred** — needs operator decision per the prompt itself (option a: VPS-side feeds_health writer service vs option b: wire `_live.health.HealthAggregator` into `run_paper.py`). The 3.C staleness wire covers the worst failure mode either option targets. |

### Recovery actions executed

- Snapshot of orphan FDs landed at `state/decisions-recovered/*.recovered` on VPS.
- `state/decisions/{2026-05-08,2026-05-09}.jsonl` replaced with the recovered 74-line + 308-line content.
- `bot-staging.service` stopped (clean shutdown, `dropped_records=0`), restarted; new FDs not marked `(deleted)`.
- `dashboard-server.service` + `rtt-collector.service` restarted to load the new code.

## Verification

- `make verify` (lint + mypy + paper tests): ✅ green for the changed code. `tests/dashboard/test_rtt_loader.py::test_basic_round_trip` fails — pre-existing flake from a hardcoded `NOW` timestamp drifting out of `lookback_s`; spawned as a separate task, not coupled to this work.
- `npm run build`: ✅ green, bundle deployed to VPS at 13:24 UTC.
- VPS post-deploy: `systemctl is-active` for all three services; `/api/state` returns 197+ fired / 184+ settled, today PnL ~$24, `incidents: []`; `lsof | grep state/decisions` shows live FDs without `(deleted)`; rtt_collector samples for Chainlink now `status_code: 301, ok: true` (was 403).
- iOS Safari fixes (A.2, A.3) are deployed but **need operator's iPad to confirm visually** — Chromium can't reproduce the original bugs.

## Asks for the next session

- **Phase 5.A.5** — pick (a) feeds_health writer service or (b) wire HealthAggregator into run_paper.py, then implement.
- **iOS Safari visual confirmation** — operator opens the dashboard on iPad, screenshots row A (chart) and row C (decisions tape) to confirm the bleed/spillover are fixed.
- **Pre-existing flake** — fix `tests/dashboard/test_rtt_loader.py` (spawned as a separate task in this session).
- **Forward discipline** — never run any script that writes to `state/decisions/` on the VPS while the bot is live; always use `state/staging/` on the laptop. The DecisionLog self-heals now, but defense in depth is cheaper than incidents.

## Numbers

- Bot decisions today (real, post-recovery): 202 fired, 189 settled, today PnL ~$19.48 at session close.
- Aggressive-mode soak: ~14h 43min elapsed at session close, 33h 17min remaining to gate at 2026-05-10 22:26:15 UTC.
- This session's bot interruption: ~3 minutes total across two restarts (one for orphan-FD recovery, one for new DecisionLog code). Soak data fully preserved.
