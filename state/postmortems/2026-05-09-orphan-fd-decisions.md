---
date: 2026-05-09
type: silent-data-loss
phase: 11.A.X.B
severity: warn
tags: [postmortem, dashboard, decision-log, atomic-rename]
---

# 2026-05-09 — orphan-FD on bot decisions JSONL — 8.5h dashboard blindness

> Operator-side mirror of `runbooks/incidents/2026-05-09-orphan-fd-decisions.md`. The runbook is canonical; this is the vault-resident summary with backlinks for graph view.

## What happened (timeline)

- **04:14 UTC** — atomic-rename writer (most likely [[../../scripts/resolve_decisions.py|resolve_decisions.py]] in legacy single-arg in-place mode, run during the prior dashboard-v3 deploy session) replaces `state/decisions/{2026-05-08,2026-05-09}.jsonl` at the same paths. Bot's open append FDs are now orphaned (unlinked but referenced).
- **04:14 → 12:48 UTC** — bot keeps firing every 5 min into the orphan inodes. Visible files frozen at 60068 bytes (May-9) / 40609 bytes (May-8). Dashboard reports `n_fired = 89, today.pnl_usd = +$83`. Real bot state: 154+ fired in May-9 alone with net-negative PnL in the silent hours, hidden from view.
- **12:40 UTC** — pre-flight diagnosis for the dashboard polish session. `lsof -p <bot-pid> | grep state/decisions` shows both FDs marked `(deleted)`. `cat /proc/<bot-pid>/fd/12 | wc -l` returns 308 vs visible 100.
- **12:48 UTC** — `cat /proc/<bot-pid>/fd/{11,12} > state/decisions-recovered/*.recovered` (no bot impact; just reads the orphan). Verified shared-prefix length matches visible file (100 lines clean prefix, no divergence).
- **13:09 UTC** — `systemctl stop bot-staging.service` (clean shutdown, `dropped_records=0`). Visible files replaced with recovered content. `systemctl start bot-staging.service`. New FDs not marked `(deleted)`. Dashboard now sees 197 fired / 184 settled.
- **13:21 UTC** — second restart to pick up the new self-healing DecisionLog code.

## Root cause

`scripts/resolve_decisions.py` had a legacy single-argument in-place mode that did `tmp.write_text(...) → tmp.rename(target)`. That atomic-rename pattern replaces the inode at the destination path while any concurrent appender's FD continues to point at the now-unlinked source inode.

The bot's [[../../src/polymarket_bot/_paper/decision_log.py|DecisionLog]] held the FD across the rename and kept writing. Linux holds unlinked inodes alive while any FD references them — appends succeed at the kernel level, just into a file the directory no longer points at.

## Blast radius

- **USD lost / at risk:** $0. Bot's strategy and capital path were unaffected. Only the *visibility* of decisions was lost; the recovery preserved every line.
- **Time lost:** ~3 minutes of bot downtime across two restarts; 0 decisions dropped. Aggressive-mode 48h gate clock preserved.
- **Trust impact:** medium. Operator's reading of the dashboard was wrong by ~3× for 8.5h. Phantom +$82 today number led to a "where did the money go?" question once the truth landed.

## Fix

### Immediate (recovery)

Snapshot orphan FDs to disk → stop bot → replace visible files → start bot. See timeline above.

### Long-term (this session's commit `ac80f9b`)

Three concentric guardrails:

1. **DecisionLog inode-stability check.** Before each write, compare the path's `(st_dev, st_ino)` to the open FD's `os.fstat`. On mismatch: salvage orphan content via `/proc/self/fd/<n>` (Linux) to a `*.recovered` sibling, close orphan, reopen against the live path, log WARN. The bot now self-heals — worst future case bounds drift to a single decision write.
2. **`resolve_decisions.py` refuses in-place mode.** Single-arg form removed; two-arg form is the only mode; rejects `src.resolve() == dst.resolve()`. `sync_staging.sh` already used two-arg mode, no callers break.
3. **Dashboard staleness wire.** [[../../src/polymarket_bot/dashboard_server/state.py|`snapshot()`]] emits `"decisions JSONL stale: last fire <X> ago while bot alive"` when the most recent fired decision is older than `DECISIONS_STALE_THRESHOLD_S = 30 min` AND `paper.alive`. Visible to the operator on the v3 incident strip.

## Prevention

- Treat `state/decisions/` on the VPS as **bot-owned**. Never run a script that writes there with the bot live, even temporarily. The two-arg `resolve_decisions.py` writes to `state/staging/decisions/` (laptop) — never to the VPS bot's dir.
- If a future deploy needs to touch any of the bot's writeable state directories, stop the bot first. The brief soak interruption is much cheaper than 8.5 hours of dashboard blindness.
- Operator can sanity-check at any time:
  ```
  ssh ops@vps "lsof -p \$(systemctl show -p MainPID --value bot-staging.service | xargs -I{} pgrep -P {} | head -1) | grep state/decisions"
  ```
  Healthy state shows two write FDs at the day's JSONL files with **no `(deleted)` marker**.

## Connections

- Phase: [[../phases/phase-11-spot-aware|Phase 11.A.X.B]] (sub-phase covering the dashboard ship + this incident).
- Related: [[../../runbooks/incidents/2026-05-09-orphan-fd-decisions|canonical incident runbook]] (the runbook is the source of truth; this vault note exists for backlinks).
- Pattern: any append-only file plus any atomic-rename writer = potential orphan FD. Same risk applies to [[../../state/feeds_health.json|feeds_health.json]] writes, the litestream replicator, and any future state file the bot holds open across rename operations.
- Operating rule: [[../concepts/anti-vibe-rules|anti-vibe rule #2]] — bug → failing test → fix → green. Three regression tests landed alongside the fix in `tests/paper/test_decision_log.py`.
