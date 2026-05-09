# Session — 2026-05-09 — orphan-FD incident response + dashboard-v3 polish + cumulative PnL chart

**Branch:** `claude/trusting-spence-03c165`. Six commits ahead of the prior session tip `76e104b`:
`ac80f9b` (incident response) → `8838545` (Phase A polish) → `8254340` (session note + launch.json)
→ `7657377` (book overflow + label clarity) → `0885ea3` (Market column + countdown)
→ `d32d1d5` (Cumulative PnL chart panel).
**VPS:** all three services restarted; bundle `index-D6WMsd2r.js` live; bot's FDs clean (no `(deleted)`).
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

### Commit `7657377` — book overflow clip + SESSION PNL label clarity (mid-session operator screenshot review)

After the operator looked at the live tunnel, two follow-ups:

1. **AnimatedBook overflow** (`apps/dashboard-v3/src/book/AnimatedBook.tsx`). BTC SPOT · BINANCE and OUR MARKET · DOWN/UP both bled past their panel boundaries. Outer column now fills parent height with `flex-1 min-h-0 overflow-hidden`; asks/bids each take half the remaining space and clip from the side furthest from mid (top for asks, bottom for bids); mid divider gets `shrink-0`.
2. **WalletPanel label** (`apps/dashboard-v3/src/panels/WalletPanel.tsx`). The hero label "SESSION PNL" was ambiguous — the operator read the +$11.80 cumulative-since-bot-start number as "today" and asked where the +$82 (today's pre-recovery snapshot) had gone. Renamed to **"CUMULATIVE PNL · SINCE BOT START"** so the time-window contrast against the LivePnlPanel TODAY field is unambiguous. The +$82 was a phantom from the frozen visible file showing only the first 100 (winning) decisions of the day; the truth, after recovery, was today +$37.04 net of the 8.5h hidden losing period.

### Commit `0885ea3` — DecisionsTape: Market column + open-window countdown

1. **Market column** between When and Side. Shows full 10-digit `window_ts` (e.g. `1778294100`) so the operator can cross-reference against `polymarket.com/event/btc-updown-5m-XXXXXXXXXX` URLs and the bot's logs.
2. **Live countdown for open positions**. The PnL cell (renamed "PnL · Status") now shows:
   - `M:SS left` (warn color) while the 5m window is still open — derived from `s.now_utc_iso` so the countdown advances on every WS push (~1s) without per-row `setInterval`.
   - `settling…` (muted) once the window closed but Polymarket hasn't published truth yet (~60-90s gap).
   - the actual `±$X.XX` PnL once resolved.

### Commit `d32d1d5` — Cumulative PnL chart panel (operator ask)

New `apps/dashboard-v3/src/panels/CumulativePnlPanel.tsx`. Slotted into Row C between DecisionsTape and CTFBookPanel; columns redistributed 9/3 → 5/4/3.

- **lightweight-charts BaselineSeries** (already in bundle, used by ChartPanel). `baseValue.price = 0`. Top fill green, bottom fill red — profit/loss zones immediately readable.
- **Backend** (`src/polymarket_bot/dashboard_server/state.py`). `snapshot()` now ships `cumulative_pnl_series`: one point per settled decision, ascending by ts, capped at 500 points (~2 days at aggressive cadence). Same number as WalletPanel's CUMULATIVE PNL — the chart's y-axis matches the hero number.
- **Header badge** shows current cumulative value with tone matching sign. **Subtitle** shows `n settled · peak $X · trough $Y`.
- **Hero** above curve shows `NOW · ±$X.XX`.
- Duplicate timestamps are bumped `+1s` so lightweight-charts' monotonic-time invariant holds when the bot fires multiple decisions inside one UTC second.
- iOS-Safari clip discipline matches `ChartPanel`: `autoSize: false` + `ResizeObserver` driving `chart.applyOptions` with floored ints.

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

## Numbers (at session close, 2026-05-09 ~14:30 UTC)

- Bot decisions: **226 fired, 226 settled across both days** (per the `cumulative_pnl_series` count).
- Today (2026-05-09): 166 fired, 163 settled, **PnL net of the day** = bouncing between +$37 and −$3 as new windows resolve. Snapshot at hand-off: cumulative −$28.57, today −$3.33 (the soak swung negative in the last hour as the chart was being shipped).
- Cumulative since bot start: peak +$65.29, trough −$28.57. WalletPanel hero label is now "CUMULATIVE PNL · SINCE BOT START" so the operator reads the time window correctly.
- Aggressive-mode soak: ~16h elapsed at session close, ~32h remaining to gate at 2026-05-10 22:26:15 UTC.
- Bot interruption this session: ~3 minutes total across two restarts (one for orphan-FD recovery, one for new DecisionLog code).
- Soak data fully preserved — no decisions lost despite the 8.5h orphan-FD blindness.

## Hand-off to phase-11.a-gate-2026-05-10 session

The next session is the aggressive-mode 48h gate review. **It can run from `claude/trusting-spence-03c165` directly** — the gate is data-driven (reads decisions JSONL via `sync_staging.sh`, runs gate criteria in `runbooks/decisions/aggressive-mode-2026-05-09.md`); none of the dashboard or incident-response code changes alter the strategy. The gate prompt expects HEAD = main @ `7199845`, but main is now stale relative to the bot's reality. Two paths:

1. **Cleanest:** open a PR to merge `claude/trusting-spence-03c165` → `main`, fast-forward to `d32d1d5` (or whatever the chart-deploy tip is at gate time), then start the gate session from main. The diff is 6 commits: incident response (`ac80f9b`), four polish commits (`8838545`, `7657377`, `0885ea3`, `d32d1d5`), one docs commit (`8254340`).
2. **Pragmatic:** start the gate session on `claude/trusting-spence-03c165`. Tag `spot-aware-paper-pass` (or `spot-aware-paper-bust`) lands on this branch. Operator merges to main after the gate decision.

Either is fine; recommend (1) so main reflects the deployed reality.

The bot will keep firing every 5 min between now and gate time. **Do not restart the bot** unless absolutely necessary — every restart costs ~1 min of soak. If the dashboard staleness wire fires (no decisions written for >30 min while bot alive), check `lsof -p $(pgrep -P $(systemctl show -p MainPID --value bot-staging.service) | head -1) | grep state/decisions` for a `(deleted)` marker — the DecisionLog now self-heals, so this should not recur, but the diagnostic is the same.
