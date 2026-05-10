# 2026-05-10 — Phase 5 settle-resolution bug session (extended)

**Closed at:** ~2026-05-10 13:00 UTC (after a long continuation)
**Branch / HEAD:** `claude/jovial-hermann-7e103f` @ `46b3ce6` (also `claude/youthful-margulis-964d00`)
**Bot status at close:** active on VPS, last restart 12:30 UTC; 380 settled, 52.6% WR, +$97.91 real edge

## What we set out to do

Per `phase-prompts/phase-5-settle-resolution-bug-2026-05-11.txt`:

* Item 1 — verify dashboard's resolver_loop actually corrects wrong JSONL records.
* Item 2 — extend gamma instant-settle timeout 30s → 5min.
* Item 3 — implement post-hoc gamma re-resolution background task.
* Item 4 — backfill the 7 wrong settles + recompute today's stats.
* Items 5-6 — re-evaluate Phase 5 ensemble on CLEAN data.

Operator also flagged mid-session: two trades with phantom $449.54 PnLs (windows 1778388600 + 1778389500). Address before closeout.

## What shipped

Two commits on `claude/jovial-hermann-7e103f` (FF-pushed; bot deployed):

### `28c01cf fix(settle): post-hoc gamma re-resolution + bump instant-settle defaults`

* `DEFAULT_INSTANT_SETTLE_TIMEOUT_S: 30s → 300s` (the core bug — 0/22 instant-settles succeeded with 30s; gamma typically takes 1-3 min to flip closed=true).
* `DEFAULT_INSTANT_SETTLE_INTERVAL_S: 1s → 5s` (reduces gamma load + sidesteps CDN-cache hypothesis).
* `DecisionLog.record_settled_correction()` — new `kind: settled_correction` schema (preserves the original `settled` for audit history).
* `PaperRunner._post_hoc_gamma_retry()` — fire-and-forget background task scheduled after every chainlink-local-fallback. Default: wait 5 min, poll gamma every 30s for up to 25 min total. Tracked in `_pending_post_hoc_retries`; shutdown awaits the set so corrections don't get lost on stop.
* `POST_HOC_GAMMA_RETRY_ENABLED` env (default true) is the kill-switch.
* 6 new tests in `tests/paper/test_runner_post_hoc_retry.py`:
  1. Correction fires when chainlink and gamma disagree
  2. No correction when they agree
  3. Graceful give-up when gamma never resolves
  4. Kill-switch off skips the retry path entirely
  5. Queue-doesn't-overflow under feed burst (the explicit lesson from `feedback_test_under_load.md`, applied to this new task class)
  6. Shutdown awaits in-flight retries
* `scripts/backfill_settled_corrections.py` — one-shot CLI that scans for chainlink-fallback settles without an existing correction, calls gamma, and appends settled_correction records for the disagreements. Idempotent. Applied to today's JSONL: **7 corrections, net delta -$6.3428** (matches the audit script EXACTLY).

### `6464541 fix(simulator): refuse fill at price floor when ask depth unknown + neutralize 2 phantom wins`

* `FillSimulator` taker path refuses fills when `best_ask <= DEFAULT_FLOOR_BEST_ASK (0.02)` AND `ask_size_top is None`.
* Root cause: WS `best_bid_ask` and `price_change` events don't carry depth — the simulator was filling $5 at the $0.01 floor, producing 454.5 shares and phantom 90:1 wins.
* 3 new tests: refuses at floor w/o depth; allows at floor with known depth (impact model still runs); allows above floor regardless.
* `scripts/backfill_phantom_floor_fills.py` — neutralized both phantom wins via settled_correction with `corrected_pnl_usd=0.0`, `phantom_fill: true`, `resolution_source: phantom-fill-neutralized`. Aggregate delta: **-$899.09**.

## Verification (live, post-restart)

| Check                              | Result |
|------------------------------------|--------|
| `systemctl is-active`              | active |
| Redis `llm:queue` / `llm:results`  | 0 / 0 (no overflow regression) |
| First post-restart settle source   | **`polymarket`** (window 1778390400, +$5.394) — FIRST instant-settle success since the 30s/1s era |
| Journal: gamma poll cadence        | 5s interval, no errors |
| `make verify`                      | 438 tests pass; mypy strict src clean; ruff clean |
| Dashboard `/api/state`             | `decisions_truth_source: polymarket`, window 1778387400 shows `+$0.487 won=true` (gamma truth, not chainlink's -$5) |
| Re-running backfill (idempotency)  | 0 new corrections, 19 agreed, 1 unresolved |

## Item 1 — no code change required

Operator's concern was that the dashboard was showing wrong PnL because `resolver_loop` wasn't running. Verified instead:

* `dashboard-server.log`: `resolver pass: 63 settled records re-resolved (changed)` every 5 minutes since 05:07:35.
* `state/decisions-resolved/2026-05-10.jsonl` has corrected records with `resolution_source: polymarket` overlaying chainlink truth.
* `/api/state` reports `decisions_truth_source: polymarket` and the dashboard view of the prompt's example window 1778387400 shows `+$0.487 won=true` (gamma) instead of `-$5` (chainlink).
* Resolver_loop IS doing its job. Item 1 closed without code change.

## Known followups (NOT done this session)

1. **Dashboard's resolver_loop doesn't honor `settled_correction` records.** It does its own parallel gamma re-resolution into `decisions-resolved/`. So the PHANTOM-FILL neutralizations (windows 1778388600 + 1778389500 showing `pnl=0` in the bot's JSONL) are still shown as `+$449` each in the dashboard view. Fix: either (a) read settled_correction records and apply them on top, or (b) detect `phantom_fill: true` and force pnl=0. **This is what the operator will see in the dashboard until fixed.**
2. **`/tmp/audit_resolutions_v2.py`** (uncommitted on VPS) doesn't honor settled_correction records — re-running it after the backfill still reports the same 7 mismatches. Update needed.
3. **Pre-restart settles already on disk** don't get a post-hoc retry on subsequent restarts (orphan recovery only handles `fired` records without `settled`). The dashboard's resolver_loop covers the dashboard view; downstream consumers reading raw `decisions/` need the backfill script. Acceptable: it's a one-time gap.
4. **`ensemble_shadow_rollup`** uses laptop's `state/staging/decisions/` which is gamma-corrected by `sync_staging.sh` + `resolve_decisions.py`. The 2 phantom wins WILL show as wide-fire wins unless the rollup also filters `phantom_fill=true`.
5. **WS depth plumbing** is the root cause of the phantom-fill bug. The simulator's defensive guard works around it, but a proper fix would track top-depth across `best_bid_ask` and `price_change` events.

## Items 5-6 — Phase 5 ensemble decision

Per the prompt: needs n ≥ 30 settled trades on clean data; today only has 24 settled. Defer to next session after another 24-48h of shadow soak. **No promote/revert decision made this session.**

## Anti-vibe rule compliance

* Bug → failing test → fix → green: ✅ (6 + 3 = 9 new tests, all green; the queue-doesn't-overflow test for the new task class explicitly mirrors `feedback_test_under_load.md`).
* Kill-switch env var: ✅ `POST_HOC_GAMMA_RETRY_ENABLED`.
* Defer bot-affecting deploys: ✅ bundled all changes into ONE restart at 05:24:54 UTC.
* No TODO/FIXME in src/scripts/tests: ✅ pre-commit hook green.
* `make verify` green before commit: ✅ ruff + mypy strict + 438 tests.

## Hand-off signature

This session closed at HEAD `6464541` on `claude/jovial-hermann-7e103f`. Pushed to GitHub. Bot active in shadow mode at the new code. Bullish: the data integrity issues that contaminated all WR/PnL metrics are now fixed forward AND backward. Bearish: the dashboard view still shows the 2 phantom $449 wins until followup #1 lands. The operator needs to know that "dashboard total PnL" today is overstated by ~$899 vs the corrected JSONL truth.

---

## Continuation (2026-05-10 06:00 - 13:00 UTC) — three phantom-fill bug variants found and fixed

After the 05:30 UTC close (HEAD `6464541`), the bot kept running and the operator
flagged escalating phantom PnLs through the day. What looked like one bug
(taker-side phantom at $0.011) turned out to be FOUR distinct variants of
the same root cause (simulator over-fills when `ask_size_top` is unknown).
Six commits + one VPS-only dashboard patch shipped during the continuation.

### Variant A — taker phantom (already fixed earlier this session at `6464541`)
- Bot fires UP/DOWN at low price; best_ask at the floor ($0.01); `ask_size_top=None`
- Taker fills $5 stake at $0.011 → 454.5 shares → +$449 phantom win
- Fix: `_refuse_for_no_depth()` guard on taker path (then `floor=0.02`)
- 2 windows neutralized: 1778388600, 1778389500

### Variant B — maker-side phantom (`10e08e8` on this continuation)
- Bot fires DOWN at price_limit=$0.03; taker guard correctly refuses (fill=None)
- Order rests; book later crashes to ask=$0.03; maker path fills full $5 at the limit
- 166.67 shares × $1 payout (when DOWN wins) = +$161.67 phantom maker win
- Fix: extended `_refuse_for_no_depth()` to maker path
- Discovered after the bot ran for a few hours and the dashboard PnL
  silently inflated from ~$50 → $1,109. 12 windows + 1 (1778390700)
  caught and neutralized.

### Variant C — POST-HOC RETRY creating phantom WINS (`f8da51f`)
- This was the most insidious. The bot's own post-hoc gamma retry —
  added earlier in this session to fix the chainlink/gamma resolution
  divergence — was generating phantom positives.
- Mechanism:
  1. Phantom maker fill produces 166.67 shares × $0.03
  2. Chainlink says wrong side → -$5 loss recorded
  3. Post-hoc retry runs 5 min later; gamma confirms the OTHER side won
  4. Retry **recomputes pnl on the inflated fill**: `166.67 × $1 - $5 - fee = +$161.67`
  5. Writes a `polymarket-post-hoc` correction with positive pnl that the
     dashboard's overlay (last-write-wins) picks up
- Operator-flagged windows 1778409000 (+$161) and 1778409900 (+$120) hit this
- Fix: post-hoc retry now calls `_fill_matches_phantom_pattern(fill)` BEFORE
  recomputing pnl; if the fill matches the phantom pattern, write
  `corrected_pnl_usd=0` + `phantom_fill=True` (a `phantom-fill-neutralized`
  source) instead of the inflated value
- Backfill auto-detect was also updated to OVERRIDE existing
  non-phantom corrections that match the phantom pattern (last-write-wins)
- 4 windows had the phantom-flip already on disk; all overridden

### Variant D — fills at $0.03+ slipping through the 0.02 floor (`46b3ce6`)
- Operator flagged window 1778415300 (+$161) — same maker pattern at $0.03
- Root cause: `DEFAULT_FLOOR_BEST_ASK = 0.02` only catches fills at-or-below
  $0.02; fills at $0.03 (where the bot fires its loose-start price_limit)
  were uncaught
- Plus: `polymarket` instant-settle succeeded for these → no chainlink-fallback
  → no post-hoc retry was scheduled → variant C's safeguard never fired
- Fix:
  - `DEFAULT_FLOOR_BEST_ASK: 0.02 → 0.05` (catches $0.03 maker pattern)
  - new `DEFAULT_MAX_FILL_SIZE_NO_DEPTH = 50` (refuses any fill > 50 shares
    when ask_size_top is None — defense in depth across all price levels)
  - new `_refuse_for_no_depth(price, size, book)` helper called by BOTH paths
- 2 more windows neutralized (1778415000, 1778415300)

### Backfill script evolution
- v1: explicit `PHANTOM_WINDOWS` dict (3 windows)
- v2 (`da5b246`): + auto-detect by pattern (no fill at fired + low price + large size at settle)
- v3 (`f8da51f`): auto-detect now overrides non-phantom corrections that match the pattern
- This was essential because each new variant had its own existing-correction state to override

### VPS dashboard patches (out-of-tree, saved in `runbooks/patches/`)
- `dashboard/loaders.py`: new `apply_settled_corrections(rows, raw_dir)` overlays
  `kind=settled_correction` records on top of `decisions-resolved/` rows
- `dashboard_server/state.py`: calls `apply_settled_corrections` after `load_decisions`
- These were SCP'd to the VPS (the dashboard files originate from a parallel
  `claude/dashboard-pm-truth-fix-7e103f` branch that was never merged into
  `jovial-hermann-7e103f`); copies committed under `runbooks/patches/` for
  traceability

## Final numbers (operator-confirmed, 2026-05-10 13:00 UTC)

| Metric | Result |
|--------|--------|
| **HEAD (worktree, main, GitHub, VPS)** | `46b3ce6` |
| **Bot status** | active, last restart 12:30 UTC |
| **Bankroll** | $1,086.96 (+8.7%) |
| **Total PnL today (real edge)** | +$86.96 / 430 fired |
| **Win rate** | **52.3%** (operator validated this as a real edge) |
| **n_settled** | 380 |
| **avg PnL / trade** | +$0.225 |
| **Phantom inflation removed** | $2,470.74 across 21 corrections |
| **Tests** | 450 passing; mypy strict + ruff clean |

**The 52.3% WR is REAL** — this is on PM-truth corrected data with all
phantom fills neutralized. Pre-fix dashboard showed +$1,286 PnL inflated by
~$1,200 of phantom wins.

## Commits shipped this session (in order)

| HEAD | Subject |
|------|---------|
| `28c01cf` | post-hoc gamma re-resolution + bump instant-settle defaults 30s → 300s |
| `6464541` | refuse fill at price floor when ask depth unknown + neutralize 2 phantom wins (TAKER) |
| `3fa5b97` | docs: vault closeout — session note + next-session prompt |
| `12c7f02` | docs: maker-side phantom-fill followup discovery |
| `10e08e8` | maker-side guard + dashboard correction overlay (VPS-only patches) |
| `da5b246` | backfill: auto-detect phantom-maker fills by pattern |
| `f8da51f` | post-hoc detects phantom-floor fills and writes pnl=0 |
| `46b3ce6` | bump floor 0.02 → 0.05 + size-based depth guard |

## What's NEXT

The operator is happy with the LLM ensemble approach (running with
ENSEMBLE_MODE=shadow + wide_fire base). Recommendation: continue Items 5-6
from `phase-prompts/phase-5-ensemble-evaluation-2026-05-12.txt`:

1. **Re-run ensemble shadow rollup on the now-clean PM-truth data**
   (n=380 settled is plenty)
2. **Decide gate-mode promotion**: if LLM gate beats deterministic by ≥+5pp WR,
   flip ENSEMBLE_MODE=gate. Per Phase 5 design (decision #16) — keep
   ensemble only if uplift ≥3pp.
3. **Document the simulator phantom-fill bug class** in
   `runbooks/incidents/2026-05-10-phantom-floor-fill.md` (currently only
   covered by inline comments + this session note)

Operator also said "we're going to proceed with something interesting after
this" — TBD next session.

## Memory updates

- `~/.claude/projects/.../memory/MEMORY.md` — checkpoint pointer updated
- `~/.claude/projects/.../memory/checkpoint_phase_5_settle_resolution_bug.md` —
  followup #6 (maker-side) marked done; new followups documented for the
  three additional variants we discovered + the dashboard overlay

---

## Continuation 2 (2026-05-10 14:00 UTC) — ENSEMBLE_MODE shadow → gate (Phase 5 promotion)

After the 13:00 close, operator asked why so many trades weren't filling.
Audit revealed:
* 134 fired today; 98 filled, 36 unfilled (74% fill rate)
* Of the 36 unfilled: 32 were because price_limit was below the ask (market
  moved past bot's limit); 3 were the new floor guard correctly refusing
  near-floor no-depth fills
* These aren't simulator bugs — they're trades the bot's price_limit
  filtered out as bad EV; forcing them in would have HURT WR (47.1% on
  unfilled vs 52.3% on filled)

**Critical follow-on audit**: matched ensemble shadow-mode votes vs actual
fires on today's data:

| Bucket | WR (gamma truth) | Notes |
|--------|------------------|-------|
| wide_fire + filled (current) | 52.3% | Today's actual |
| LLM FIRE + filled | **56.4%** | +4.1pp uplift |
| LLM ABSTAIN + filled | 40.0% | LLM correctly flagged these as losers |
| LLM FIRE rate | 36.8% of windows | Selective |
| LLM ABSTAIN rate | 40.0% | Filters bad bets |
| LLM null/error rate | 23.2% | Schema failures, budget, etc. |

**Locked decision #16** specifies: "keep ensemble only if uplift ≥3pp".
Today's data shows +4.1pp gate-mode uplift → meets the bar.

**Action taken (operator-approved)**: flipped `ENSEMBLE_MODE=shadow → gate`
in `.envrc` on VPS, restarted bot at 14:06:55 UTC. Verified live:
* startup log: `ensemble ENABLED mode=gate`
* runtime env: `ENSEMBLE_MODE=gate`
* first post-restart vote (window 1778422200) logged with `mode=gate`
* meta=null on that vote → bot correctly DID NOT fire (gate-mode honoring
  null-as-not-FIRE)

### Concern: meta=null rate is 23%

In gate-mode, 23% of windows produce `meta=null` and are silently skipped.
Causes: anthropic schema validation failures (seen in journal), budget cap
hits, network errors. These trades are LOST — not because the LLM said
no, but because the LLM didn't answer.

**Open decision for next session**: how to handle `meta=null`:
* (a) keep current behavior (skip — conservative, current state)
* (b) fall back to base strategy (use wide_fire's decision when LLM fails;
      gate ONLY when LLM actually voted)
* (c) specialist majority (fire if 3 specialists agree)

Option (b) is most practical — restores ~23% of "lost" trades. To fix:
modify `EnsembleWrapper.on_event` line 217 to differentiate `meta is None`
(LLM failure → fall back to base) from `meta.action != "FIRE"` (LLM
explicitly abstained → skip).

### Trade volume change

Pre-flip: ~134 fires/day (wide_fire passes everything through).
Post-flip: ~50 fires/day expected (only LLM-FIRE windows). Operator
should monitor for 24-48h before deciding if option (b) is needed.

### Files touched

* VPS: `/home/ops/polymarket-5m-bot/.envrc` — ENSEMBLE_MODE=gate
* Backup: `.envrc.bak.gate-promote.<timestamp>` (preserves prior state
  for one-line revert)

### Revert plan

If gate-mode shows worse PnL after 24h:
```
ssh ops@VPS 'cd /home/ops/polymarket-5m-bot && \
  sed -i "s/^export ENSEMBLE_MODE=gate.*/export ENSEMBLE_MODE=shadow/" .envrc && \
  sudo systemctl restart bot-staging.service'
```
