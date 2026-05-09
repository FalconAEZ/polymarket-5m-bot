# Incident — orphan FD on bot decisions JSONL

- **Detected:** 2026-05-09 ~12:40 UTC during dashboard-v3 polish session.
- **Started:** 2026-05-09 04:14 UTC (last visible decision write 04:05:00.763 UTC).
- **Duration of dashboard blindness:** ~8.5 hours.
- **Bot impact:** none — the bot kept firing decisions normally throughout. Every write succeeded at the FD layer; only readers (dashboard, sync, operator) saw stale data.
- **Data loss:** zero. All 208 "missing" decisions were recovered from `/proc/<bot-pid>/fd/12` and merged back into `state/decisions/2026-05-09.jsonl` before the bot was restarted.

## Symptoms

- Dashboard top-strip showed `n_fired = 89` and `today.pnl_usd = +$83`. Real values from the running bot were `n_fired = 154+` and a PnL ~$59 lower (the missing 8.5 hours had a net negative slope).
- The visible JSONL files in `state/decisions/` had `mtime = 2026-05-09 04:14` and were stuck at 100/74 lines respectively.
- `bot-staging.service` reported `active (running)`. `journalctl` showed only the warmer fetching new windows every 5 minutes — no `fired` log lines, no exceptions, no errors.
- `lsof -p <bot-pid>` revealed both `state/decisions/2026-05-08.jsonl (deleted)` and `state/decisions/2026-05-09.jsonl (deleted)` — the bot's append FDs pointed at orphan inodes.

## Root cause

Some atomic-rename writer replaced the visible JSONL files at the same path while the bot held open append FDs. Because the bot had `O_APPEND` open against the *original* inodes, the kernel kept those inodes alive (orphan / unlinked but referenced); subsequent writes from the bot landed in the orphans. The new visible inodes were a frozen snapshot — readable but never extended.

Most likely culprit: `scripts/resolve_decisions.py state/decisions/` (the legacy single-arg in-place mode). That mode does `tmp.write_text(...) → tmp.rename(target)`, exactly the atomic-rename pattern that orphans concurrent append FDs. The single-arg mode existed for the laptop-side `state/staging/decisions/` flow, but if invoked against the live VPS `state/decisions/` (e.g. by a session running it manually), it produces this exact failure mode.

Other candidates that were ruled out:
- `git pull` / `git checkout` — `state/decisions/*.jsonl` is not git-tracked (only `README.md` is). Git ops do not touch untracked files.
- `sync_staging.sh` — VPS → laptop only. Does not push back.
- The bot's own `DecisionLog` — opens with `"a"` and never renames. Verified by reading `_paper/decision_log.py` history.

The deploy reflog shows `git reset` + `git checkout claude/trusting-spence-03c165` at 04:05:02 (≤ 2s after the bot's last visible decision), then two `git pull`s at 04:08:14 and 04:29:53. The atomic-rename happened in the gap. A 1-second SSH session at 04:13:41 from the operator's IP fits a one-shot remote command (`ssh ops@host '<single command>'`).

## Why nobody noticed for 8.5 hours

- The bot's systemd unit was `active`. Process liveness was a green light.
- The dashboard had no wire that compared "most recent decision row timestamp" to wall-clock + bot liveness. A frozen visible file under a live bot is exactly the failure mode that needed surfacing.
- Telegram alerter had no equivalent staleness probe.
- Aggressive-mode soak metrics (24h PnL, fire-rate trip-wires) were computed from the visible file, so they too looked plausible — slightly negative PnL but well within thresholds.

## Recovery (executed in this session)

1. `cat /proc/<bot-pid>/fd/{11,12}` → snapshot the orphan content into `state/decisions-recovered/*.recovered`. Verified shared-prefix length matched the visible file's line count exactly (no divergence).
2. `systemctl stop bot-staging.service` (clean shutdown — `dropped_records=0`).
3. Replaced `state/decisions/{2026-05-08,2026-05-09}.jsonl` with the recovered content via `cp` + `mv`.
4. `systemctl start bot-staging.service` — bot opens fresh FDs against the now-up-to-date visible files.
5. Verified `lsof` no longer shows `(deleted)` on either FD; verified the dashboard now reports the real `n_fired`/`n_settled`/`bankroll` numbers.

The aggressive-mode 48h soak was *interrupted* by ~2 minutes (the stop+start). All decision data from the soak is preserved.

## Defense in depth (this session's commit)

Three concentric guardrails so this can never repeat silently:

1. **`DecisionLog` inode-stability check** (`src/polymarket_bot/_paper/decision_log.py`).
   - Before each write, compare the path's `(st_dev, st_ino)` to the open FD's `os.fstat`.
   - On mismatch: best-effort salvage the orphan content to `<path>.<utc-ts>.recovered` via `/proc/self/fd/<n>` (Linux), close the orphan FD, reopen against the live path. Logs a WARN.
   - This makes the bot self-healing — the worst future case bounds drift to a single decision.
   - Tests: `tests/paper/test_decision_log.py` — `test_reopens_when_path_inode_replaced_atomically`, `test_inode_unchanged_path_does_not_reopen`, `test_reopens_when_path_unlinked`.

2. **`scripts/resolve_decisions.py` refuses in-place mode** (`scripts/resolve_decisions.py`).
   - The legacy single-arg form (`uv run python scripts/resolve_decisions.py state/decisions/`) is removed.
   - Two-arg form is the only mode; explicitly rejects `src.resolve() == dst.resolve()`.
   - `sync_staging.sh` already uses two-arg mode, so no callers break.

3. **Dashboard staleness incident wire** (`src/polymarket_bot/dashboard_server/state.py`).
   - `snapshot()` now emits an incident `"decisions JSONL stale: last fire <X> ago while bot alive (check for orphan FDs)"` whenever the most recent fired decision is older than `DECISIONS_STALE_THRESHOLD_S = 30 min` AND the paper process is alive.
   - Visible to the operator on the v3 incident strip — same banner the dashboard uses for "paper process dead".

## Forward asks

- Treat `state/decisions/` on the VPS as **bot-owned**. Never run a script that writes there with the bot live, even temporarily. The two-arg `resolve_decisions.py` writes to `state/staging/decisions/` (laptop) — never to the VPS bot's dir.
- If a future deploy needs to touch any of the bot's writeable state directories, stop the bot first (`systemctl stop bot-staging.service`), make the change, restart. The brief soak interruption is much cheaper than 8.5 hours of dashboard blindness.
- Operator can sanity-check at any time with `ssh ops@vps "lsof -p \$(systemctl show -p MainPID --value bot-staging.service | xargs -I{} pgrep -P {} | head -1) | grep state/decisions"`. A clean state shows two FDs pointing at the day's JSONL files with **no `(deleted)` marker**.
