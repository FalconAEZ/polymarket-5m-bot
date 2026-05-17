# 2026-05-18 — Phase P Session 1 — Hard revert to J.1.6 + dashboard reset + kickoff PDF

**Bot state at session start:** active on `claude/jovial-hermann-7e103f`
HEAD `98940b1` at MainPID 1002001, bankroll $3,000 (Phase O override),
5 Phase M/O features live (L.5 @ −$90 / M.1a v1 disabled / M.5 active /
M.2 v0 shadow / O.1 SURV canary). VPS UTC clock: 2026-05-17 21:28:57Z.
1 fire post-Phase-O-restart = LOSS −$163.

**Bot state at session close:** active on `claude/phase-P-hard-reset`
HEAD `53e08c9` at MainPID 1019607, bankroll $1,000 (decision #10
restored), J.1.6 baseline (Kelly 0.15× + replay=true + cap=1 + J.1.5
fold + J.1 floor + J.2 hour blocklist + H.2.12 path-A block_up).
VPS UTC clock: 2026-05-17 21:37:34Z. Zero fires post-restart.

## Operator framing

(Verbatim — operator authored prompt at `~/Desktop/phase-P-hard-reset-2026-05-18.txt`.)

> "I'm really disappointed at the results that we currently have. We're
> going to revert back to pre peak. The pre peak — the last ship was
> J.1.6, Kelly 0.15× plus replay. ... So just make a plan for that
> because we have shipped so many fucking features based on emotions
> post peak. ... The bot is in a really nice stage. It can't even make
> a single trade now. Fully revert to pre peak now. ...
> I think we're missing one thing only, and I think it's the regime
> classifier. Let's not call it regime classifier. ... find this one
> GitHub repo that when we turn on and integrate into our bot, it can
> detect when Bitcoin is going up, when Bitcoin is going down, and when
> Bitcoin is choppy or mixed. ...
> Make sure to restart the bot, turn it on with one thousand dollar
> bankroll. Make sure to reset the chart, the cumulative PnL chart,
> and make sure to reset the decision tape. Just reset the full
> dashboard. ... This is the last chance we have."

## Session 1 sequence (chronological, VPS UTC)

1. **21:28:57** — VPS health check confirms bot active on `98940b1` at $3k,
   no halt sentinel, dashboard active. Modified files on VPS:
   `apps/dashboard-v3/package-lock.json`, `state/token_side_index.json`.
2. **21:33:53** — `halt.sentinel` written with reason
   `phase-P-hard-revert | operator-revert-to-J.1.6-baseline-via-phase-P-prompt`.
   Watcher did not drain in 8s.
3. **21:34:03** — `sudo systemctl stop bot-staging.service`. Clean exit,
   `Result=success`.
4. **21:37:00** — `.envrc` backed up to `.envrc.bak.phase-P-revert-2026-05-18`
   (8,404 bytes). VPS modified files stashed
   (`phase-P-pre-revert-stash-1779053834`). `git fetch origin` + `git
   checkout claude/phase-P-hard-reset` + `git pull --ff-only`. HEAD =
   `53e08c903f4d2a3e53b8da63aed35e2184c8e236`.
5. **21:37:10** — `.envrc` rewritten (56 lines, J.1.6 baseline only).
   `chmod 0600`. Strip-list: REGIME_*, DAILY_PNL_*, SURV_*,
   ORDERBOOK_IMBALANCE_*, TIER_GATE_*, REGIME_GATE_*. Add-list:
   `PMB_STARTING_BANKROLL=1000`, `BANKROLL_REPLAY_ENABLED=true`.
6. **21:37:15** — 5-day decisions archived
   (`state/decisions/2026-05-{13..17}.jsonl` → `archived/phase-P-reset/`;
   same for `decisions-resolved/`). Fresh empty
   `state/decisions/2026-05-18.jsonl` created.
7. **21:37:18** — Dashboard systemd drop-in
   `/etc/systemd/system/dashboard-server.service.d/bankroll.conf` deleted.
   `sudo systemctl daemon-reload` + `restart dashboard-server.service`.
   Service active.
8. **21:37:22** — `state/halt.sentinel` removed. `sudo systemctl start
   bot-staging.service` → MainPID 1019607, active+running.
9. **21:37:29** — Startup log signature confirmed:
   - `active strategy: spot_aware_v2_1`
   - `spot_aware_v2_1: kelly_mult=0.15 max_bet_abs=$500 multi_fire_cap=1
     tier_relax_p_win_fallback=None tier_relax_price_floor=0.420
     block_up_in_tiers=('70-85%',) hour_blocklist_utc=(22, 23, 0)
     hour_blocklist_tiers=('70-85%',)`
   - `bankroll_getter wired (start=$1000.00, replay=True, cap=1)`
   - `bankroll replay: starting=$1000.00 current=$1000.00`
   - `orphan recovery: 0 orphans found`
   - **Absent**: L.5 / M.5 / M.1a / SURV canary / orderbook-imbalance /
     MMD lines.
10. **21:37:34** — Dashboard `/api/state` snapshot:
    - `mode.label = WAITING`
    - `bankroll.starting_usd = $1000.0`
    - `bankroll.current_usd = $1000.0`
    - `bankroll.delta_usd = $0.0`
    - `today.n_settled = 0`
    - `decisions[] = 0 entries`
    - `cumulative_pnl_series = 0 pts`
    - `scenarios[].n_settled = 0`

## Decisions made this session

1. Branch base = `83fe119` (operator-confirmed): docs-only commit
   ("phase-J design lock for J.3 + J.7"), contains all J.1.6 code, last
   before any Phase L/M code lands.
2. L.5 = STRIP (operator-confirmed plan default): clean revert; bot has
   no automated halt-on-bleed; operator halts manually if needed.
3. Operator-confirmed run cadence: end-to-end, pause only on errors.

## Files written

- `runbooks/research/phase-P-feature-inventory.md` (KEEP/DROP table for
  every feature shipped 2026-05-13 → 2026-05-17)
- `state/phases/phase-P-hard-reset.md` (phase ledger)
- `state/sessions/2026-05-18-phase-P-session-1-revert.md` (this file)
- `memory/checkpoint_phase_P.md` (NEW memory checkpoint)
- `memory/MEMORY.md` (index updated: Phase P added, Phase O marked
  SUPERSEDED)
- `memory/project_bankroll_reset_2026_05_17.md` (marked HISTORICAL)
- `pdfs/PHASE_P_KICKOFF.pdf` (12-15 pp)
- `pdfs/build_phase_p_kickoff_pdf.py` (reportlab builder)

## What did NOT happen this session (intentional)

- No code changes to `src/` (revert was the cut, not a patch).
- No M/O feature env vars added to `.envrc`.
- No MMD work (Session 2 deliverable).
- No new tests (no src/ changes).
- No PR opened on the new branch — the branch is the deliverable; PR
  to `main` will land at Phase P close (after Session 3 + re-soak).

## What's next

- **Operator review** of PHASE_P_KICKOFF.pdf + first 24-48h dashboard
  observation.
- **Session 2 (T+1-3d)** — MMD candidate research + backtest on Phase N
  n=755. Outputs: `phase-P-mmd-backtest-2026-05-XX.md`,
  `design/P.1-market-mode-detector-integration.md`,
  `PHASE_P_SESSION2_MMD_RESEARCH.pdf`. No bot changes.
- **Session 3 (T+5-7d after Session 2)** — MMD shadow-ship + 5-day
  observation window.
- **Phase Q decision (Day 5 from Session 3 ship)** — promote MMD /
  shelve / iterate; reconsider M.5 reintroduction.
