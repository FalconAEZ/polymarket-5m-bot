---
date: 2026-05-12
phase: Phase 16.B.5 soak (continuation) + wide_fire phantom-zone v2 fix + Phase 19 design + architecture-audit prep
status: 16.B.5 SHIPPED + LIVE on `7a5b19e`; wide_fire fix v2 DEPLOYED; Phase 19 design LOCKED awaiting sign-off; architecture-audit prompt drafted
tags: [session, phase-16b, phase-19, wide-fire, phantom-fill, vps-deploy, design-doc, architecture-audit, multi-deploy-session]
---

# 2026-05-12 — Phase 16.B.5 soak + wide_fire phantom-zone v2 + Phase 19 design + architecture-audit prep

## Headline

**Long operational session — three deploys, one design doc, one backfill, three architecture observations.** Started at the +5min check for yesterday's `2eb54fd` wrapper-wire deploy; ran the soak through ~17h; pivoted twice on a phantom-fill diagnosis; closed with Phase 19 design lock and an operator-requested architecture-audit prompt for the final stage of the bot.

## Commits today (3 functional + 1 design) — branch `claude/jovial-hermann-7e103f`

| Commit | Phase | Summary | VPS deployed |
|---|---|---|---|
| `c32f1e5` | vault | Phase 16.B.4 close-out: session note + phase ledger + memory checkpoint refresh + new memory `project_phantom_defense_equals_fill_rate_problem.md` | yes (incidental, with 3875d3c) |
| `3875d3c` | wide_fire v1 | Phantom-zone abstain when `ask_size_top is None AND ask <= $0.05` — strategy-layer mirror of `FillSimulator._refuse_for_no_depth`. 3 new tests. | yes via `c32f1e5` bundle 11:16:58 UTC |
| `7a5b19e` | wide_fire v2 | Per-asset_id `_book_by_token` replacing per-side `_ask_size_for_side` cache. Audit found v1 fix was bypassed by warmer's forward-window BookUpdates polluting the per-side state. 2 new tests. | yes 11:31:51 UTC |
| `(NEXT)` | Phase 19 design | `design/phase-19-llm-async-precompute.md` — LOCKED spec for the async LLM pre-compute architecture. Awaiting operator sign-off. | n/a (design only) |

## VPS state at session close

- bot-staging.service active since 2026-05-12 11:31:51 UTC, MainPID 570290, NRestarts=0
- HEAD on VPS: `7a5b19e` (current code) → will advance to next commit on next pull
- Strategy: `ensemble + ENSEMBLE_MODE=gate + ENSEMBLE_BASE_STRATEGY=wide_fire` UNCHANGED
- Env flags: `EVERY_WINDOW_SHADOW=true`, `EVERY_WINDOW_MODE=false`; TIER_GATE + REGIME_GATE both dark
- Anthropic budget: ~$2-3/day spend, well under $10/day cap
- Disk 7%, FD count low, memory ~130MB — all healthy

## Deploy chain — three restarts this session

| Time | Event | HEAD | MainPID | Note |
|---|---|---|---|---|
| 2026-05-11 17:56:22 UTC | Initial wrapper-wire deploy | `2eb54fd` | 550616 | Default-off router (yesterday's session) |
| 2026-05-11 18:02:05 UTC | `EVERY_WINDOW_SHADOW=true` flip | `2eb54fd` | 550836 | Shadow soak begins |
| 2026-05-12 11:16:58 UTC | wide_fire phantom-zone v1 deploy | `c32f1e5` | 567005 | per-side fix |
| 2026-05-12 11:31:51 UTC | wide_fire phantom-zone v2 deploy | `7a5b19e` | 570290 | per-asset_id fix |

## The phantom-zone bug saga (this session's deepest dive)

Operator flagged "trade 1778551200 PnL +120 — phantom?" Forensic:

- **Fired record**: side=UP, size=$5, price_limit=$0.04, ask_size_top=null. **Initial taker fill: null** — Phase 11.A defense (`_refuse_for_no_depth`) correctly refused at fire time.
- **+5.3s later**: a BookUpdate arrived with ask_size_top populated → `_try_fill_pending` ran the maker path → `_refuse_for_no_depth` did NOT re-trigger (because the LATER book has depth populated, even though the fill is still in the phantom zone) → 125 shares at $0.04 → UP won → **$119.999 phantom PnL**.

Two phases of fix:

### Phase 1 (`3875d3c`, per-side, BUGGY)
Mirror the simulator's threshold at the strategy layer:
```python
ask_size = self._ask_size_for_side.get(side)
if ask_size is None and ask <= DEFAULT_FLOOR_BEST_ASK:
    return None
```
Deployed at 11:16:58 UTC. **Post-deploy verification showed a phantom-zone fire still emitted** on window 1778583000 (post-deploy timestamp, sub-deploy era). Diagnostic:

The warmer pre-resolves ~12 forward windows' tokens. Every window has its own UP/DOWN token pair, but ALL UP-side BookUpdates share `event.side="UP"`. Last-write-wins per-side cache meant a future-window UP-token's depth-only BookUpdate (`best_ask=None, ask_size_top=50`) overwrote `_ask_size_for_side["UP"]` to 50 even though the strategy's chosen asset_id (the current window's UP token) actually had ask_size=None. Fix bypassed.

### Phase 2 (`7a5b19e`, per-asset_id, CORRECT)
Replace `_best_ask_for_side` + `_ask_size_for_side` with `_book_by_token: dict[asset_id, ...]`. Mirrors the runner's `_shadow.latest(asset_id)` lookup model. `best_ask` is sticky (depth-only updates don't clobber); `ask_size_top` is always written. Fire-time lookup uses the chosen asset_id, isolating from per-side pollution.

Reproduction test: `test_wide_fire_isolates_phantom_check_per_asset_id`. Verified RED on `c32f1e5`, GREEN on `7a5b19e`. 537 pytest passes.

**Residual / known limitation**: `_token_for_side` is still per-side. In extreme ordering the strategy could fire for a future-window's token. The new per-asset_id book lookup makes this MOSTLY harmless (chosen token either has no best_ask → no fire, or has its own depth → not a phantom). A proper window-scoped token tracker is a follow-up.

## Phantom-fill backfill applied to live data

Ran `scripts/backfill_phantom_floor_fills.py` against 2026-05-11.jsonl + 2026-05-12.jsonl:

| Window | Day | Fill | Naive PnL | Corrected | Net |
|---|---|---|---|---|---|
| 1778480100 | 2026-05-11 | $0.03 / 166.7 shares | -$5.00 (full stake lost) | $0.00 | +$5.00 |
| 1778487900 | 2026-05-11 | $0.03 / 166.7 shares | -$5.00 | $0.00 | +$5.00 |
| 1778551200 | 2026-05-12 | $0.04 / 125.0 shares | **+$119.999** | $0.00 | **-$120.00** |

Net dashboard delta: **-$110**.

**Dashboard bankroll: $1,120.62 → $1,010.62 (delta +$10.62)** — the truth-corrected operating PnL for the soak window.

Importantly: the **"+$77 overnight" celebration from earlier in the session was the phantom artifact, not real PnL**. Honest correction surfaced to operator.

## Phase 19 design locked

`design/phase-19-llm-async-precompute.md` — 14 sections covering:

- Goal: move 12s LLM inline await off runner hot path → background pre-compute + O(1) cache lookup at fire-time
- Targets: 8.8% gate-timeout → ≤0.5%; 22.1% meta=None → -8.8pp; 0 queue-overflow incidents
- 3 env knobs (kill-switched, default OFF): `LLM_PRECOMPUTE_ENABLED` / `_OFFSET_S` / `_MAX_AGE_S`
- 7-test plan including bulwark (default-OFF = byte-identical output) + under-load (third application of `feedback_test_under_load`)
- Cost delta: +$0.22/day (~5%) under the $10/day cap
- Soak gate criteria for PROMOTE/ROLLBACK

Operator chose to NOT implement in this session — deferred to next session per session-length discipline + 16.B.5 soak still mid-run.

## Self-correction: timestamp-arithmetic error

Mid-session I mis-derived `DEPLOY_NS = 1778578311_000_000_000` for 11:31:51 UTC when the correct value was `1778585511_000_000_000` (off by 7200s = 2h). Mis-classified pre-deploy fires as post-deploy and incorrectly reported "fix still failing." Caught when post-deploy fire count = 0 didn't match observed "post-deploy phantom" pattern. Re-classified with corrected DEPLOY_NS → no actual post-deploy phantom-zone fires. Apologized to operator.

Lesson durably saved (could become a memory): for VPS deploy timestamp math, ALWAYS get the Unix epoch from `python3 -c "import time; print(int(time.time()))"` on the VPS at deploy time, not from arithmetic on `systemctl show` output.

## Operator's architectural concern (the prompt for next session)

Operator surfaced at session close:

> "we have actually over complicated the bot's current architecture - like look at the data and pnl of the 9th of may! it's stunning in just a bunch of hours! if we can revert back to that state and fixing the downfall it had that would be amazing! ... we are currently having really bad results, really high llm delay and delay overal!"

The **"+May 9 was stunning" instinct needs honest pushback**: per Phase 15.5 truth pass (`memory/checkpoint_phase_15.5_pnl_truth_bundle.md`), the May 8-9 era's headline numbers were largely phantom-fill inflated. Naive sum +$2,556 corrected to ~+$75 truth — the same simulator bug that produced today's +$120 phantom. The operator is reaching for a number that wasn't real.

That said, the operator is correct that:
1. Architecture has grown: spot_aware → spot_aware_v2 → spot_aware_v3 → wide_fire base + ensemble wrapper + tier gate + regime gate + every-window router (shadow)
2. LLM latency is genuinely a problem (12s gate timeout, 8.8% timeout rate, 22.1% meta=None — Phase 19's target)
3. Fill rate hovers ~50% of fires; WR-on-filled is ~50% baseline

The next-session prompt (drafted separately) is the **architecture-audit + final-stage roadmap** — pruning the experiments, locking what works, sequencing toward Phase 6 live deployment.

## What did NOT happen this session

- No deploy of the phantom-fill backfill changes (backfill writes correction records to decision-log; dashboard reads them automatically; no bot restart needed)
- No Phase 16.B.6 soak gate (24h shadow soak still mid-run)
- No Phase 19 implementation (design only; operator deferred)
- No revert / rollback (all forward motion)

## Pinned next-session focus

1. **Architecture-audit prompt** (drafted this session) — operator-requested final-stage plan
2. **Phase 16.B.5 24h soak gate** (~6h until close at 2026-05-12 ~18:02 UTC)
3. **`scripts/audit_router_shadow.py`** writing (Item 2g of original 16.B prompt)
4. **Phase 19 implementation** (if sign-off lands)

## Related

- [[2026-05-11-phase-16b-4-and-phantom-zone-fix]] — prior session note (yesterday's start)
- [[../phases/phase-16b-every-window-mode]] — phase ledger
- [[../phases/phase-19-llm-async-precompute|Phase 19 design doc]] (NEW, awaiting sign-off)
- [[../decisions/README]]
- `~/.claude/projects/.../memory/checkpoint_phase_16b_router.md`
- `~/.claude/projects/.../memory/project_phantom_defense_equals_fill_rate_problem.md`

## Tags

`#phase-16b` `#phase-19` `#wide-fire` `#phantom-fill` `#vps-deploy` `#design-doc` `#architecture-audit` `#multi-deploy-session` `#truth-pass`
