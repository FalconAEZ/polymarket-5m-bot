---
date: 2026-05-11
phase: Phase 16.B.4 + 16.B.5 (router wire + dark deploy + shadow soak) + wide_fire phantom-zone fix
status: 16.B.4 SHIPPED + DEPLOYED, 16.B.5 SHADOW underway, 16.B.6 deferred next session; wide_fire phantom-zone fix SHIPPED (not deployed — defer)
tags: [session, phase-16b, every-window, router, vps-deploy, shadow-soak, wide-fire, phantom-fill, decision-9-revisit]
---

# 2026-05-11 — Phase 16.B.4 wrapper wire + VPS dark deploy + shadow soak + wide_fire phantom-zone fix

## Headline

**Two commits shipped, one deployed.** Phase 16.B.4 wrapper wire (`2eb54fd`) deployed to VPS bot-staging at 17:56:22 UTC; `EVERY_WINDOW_SHADOW=true` flipped at 18:02:05 UTC; 24h shadow soak underway. **Separately**: operator flagged "many unfilled trades" → fill-rate audit found 100% of today's 35 unfilled fires were phantom-fill defended by `FillSimulator._refuse_for_no_depth` (Phase 11.A defense). **The router's `taker_fallback` design solves the wrong problem here** — phantom defense triggers on the depth signal, not price-cross. Right fix is upstream at the strategy layer: abstain in `wide_fire` when `ask_size_top is None AND best_ask <= $0.05`. Shipped at `3875d3c`, NOT deployed (defer per `feedback_defer_deploys_to_natural_restart`).

## What shipped today (2 commits on `claude/jovial-hermann-7e103f`)

| Commit | Phase | Summary | Deployed? |
|---|---|---|---|
| `2eb54fd` | **16.B.4** | EVERY_WINDOW_MODE wired in EnsembleWrapper + every_window/runner.py + 7 new tests (bulwark MODE=off no-change is mandatory) + scripts/run_paper.py env wiring (17 `EVERY_WINDOW_*` vars). 4 gates green at 532 passes. | ✅ 17:56:22 UTC (MainPID 550616 then 550836 after SHADOW flip) |
| `3875d3c` | sidebar (wide_fire) | Phantom-zone abstain: `if ask_size_top is None AND ask <= DEFAULT_FLOOR_BEST_ASK ($0.05): return None`. Mirrors `FillSimulator._refuse_for_no_depth` Phase 11.A defense. 3 new tests. 4 gates green at 535 passes. | ❌ deferred; picks up at next natural restart |

## VPS deploy chain (Item 2 of the phase prompt)

```
17:56:22 UTC  bot-staging restarted on 2eb54fd (defaults; SHADOW unset = no behavior change)
18:00     UTC  +5min verify: active, NRestarts=0, decisions still flowing at $5 wide_fire
18:02:05 UTC  appended `export EVERY_WINDOW_SHADOW=true` to .envrc; bot restarted (MainPID 550836)
18:02:06 UTC  startup log: "WARNING: EVERY_WINDOW_MODE=False SHADOW=True — router=WIRED log_root=state/router"
18:02+        first router_shadow records flowing to state/router/2026-05-11.jsonl
```

Per `feedback_vps_deploy_verify_late`: +5min check passed in-session; **+30min and +24h checks are operator-owned**.

## The fill-rate audit pivot (the most useful finding of the session)

Operator flagged "many unfilled trades" mid-session. Diagnostic on today's decision log (n=70 fires):

```
Fires           : 70
Filled (>$0)    : 36  (51.4%)
Unfilled (=$0)  : 34
Settled wins    : 19   = 50.0% WR on filled trades (matches baseline)
Settled zero-PnL: 33   (≈ the unfilled fires)
```

WR on _filled_ trades is 50.0% — exactly the historical baseline. The 26.8% "WR" the operator saw on the dashboard counted unfilled-at-$0 as losses.

**Failure-mode classification of the 35 unfilled:**

| Failure mode | Count |
|---|---|
| NO best_ask in snapshot (no book data) | 0 |
| best_ask present, NO depth (`ask_size_top=None`) | **35** (33 in `<15%`, 2 in `85-100%`) |
| best_ask present, depth present (genuine maker miss) | **0** |

**100% of unfilled fires were caught by `FillSimulator._refuse_for_no_depth` — the Phase 11.A phantom-fill defense ($1700 incident remediation).** The bot was firing at lottery-ticket prices ($0.001-$0.03) on books with no depth signal. Phantom defense correctly prevented simulated wins that wouldn't have reproduced live.

This **changes the prescription for `<15%` tier in Phase 16.B**: the router's `taker_fallback` design (§3.8) assumes maker orders rest on a book with depth and get walked through by price. That's NOT today's failure mode. Building runner-side `taker_fallback` wouldn't help — phantom defense triggers on the depth signal, not the price-cross. The right fix is **upstream at the strategy** (don't fire when the simulator would refuse).

## wide_fire depth-skip fix (`3875d3c`)

One condition added to `WideFireStrategy._maybe_fire`:

```python
# Phantom-fill defense alignment (audit 2026-05-11)
ask_size = self._ask_size_for_side.get(side)
if ask_size is None and ask <= DEFAULT_FLOOR_BEST_ASK:
    return None
```

Mirrors `FillSimulator._refuse_for_no_depth` threshold (DEFAULT_FLOOR_BEST_ASK = $0.05). Three new tests in `test_wide_fire.py`:

- `test_wide_fire_abstains_on_phantom_floor_without_depth` (the bug)
- `test_wide_fire_fires_on_phantom_floor_when_depth_known` (depth backs a low fire)
- `test_wide_fire_fires_above_floor_without_depth` (defense zone is price-bounded, not depth-bounded)

**PnL impact today: $0.** Those 35 fires would have settled at $0 anyway. The win is operational hygiene: ~50% fewer fired records, ~$0.005 Anthropic savings per skipped window, cleaner audit numbers, less noise in shadow soak data.

## Locked-decision impacts

| Decision | Status | Notes |
|---|---|---|
| #6 (composite ≥0.6 gate) | REVISED **on PROMOTE** (not today) | router uses magnitude as confidence input |
| #9 ($5 flat → fractional Kelly) | REVISED **on PROMOTE** (not today) | router supports $5–$30 hybrid-Kelly |
| #10 ($1k paper bankroll) | UNTOUCHED | |
| #5 (3 specialists + meta) | UNTOUCHED | |
| Phase 17 + 18 | SUBSUMED | sizing.py + size_for shipped under 16.B.3 |

`memory/project_decisions.md` updates land on Phase 16.B.6 PROMOTE — NOT today.

## Bot state at session end

- bot-staging.service active since 2026-05-11 18:02:05 UTC, MainPID 550836, NRestarts=0
- HEAD on VPS: `2eb54fd` (the wrapper wire — `3875d3c` wide_fire fix is committed + pushed but NOT pulled to VPS)
- Strategy: `ensemble + ENSEMBLE_MODE=gate + ENSEMBLE_BASE_STRATEGY=wide_fire`. UNCHANGED.
- `EVERY_WINDOW_MODE=false` (default), `EVERY_WINDOW_SHADOW=true` (the audit mode)
- TIER_GATE + REGIME_GATE both dark
- Cumulative PnL: +$44.50 (gained ~$5 since start of session despite chop)
- Today: 70 fires / 36 filled (51.4%) / 19W-19L on filled / +$44 cumulative
- 18 router_shadow records in `state/router/2026-05-11.jsonl` over the first 1h25m

## What's NOT deployed (queued for next natural restart)

- `3875d3c` wide_fire phantom-zone abstain — committed + pushed; next `git pull` + service restart picks it up. NOT urgent — PnL impact today = $0.

## Sub-phase status (Phase 16.B umbrella)

| Sub-phase | State | Commit |
|---|---|---|
| 16.B.0 — Research + signal inventory | ✅ done | `e1b9a6b` |
| 16.B.1 — Counterfactual audit | ✅ done | `a36e241` |
| 16.B.2 — Design doc locked | ✅ done | `707786c` |
| 16.B.3 — Router primitives + 49 tests | ✅ done | `707786c` |
| **16.B.4 — Wrapper wire (env-gated)** | ✅ **done + deployed** | `2eb54fd` |
| **16.B.5 — Dark deploy + 24h shadow** | ⏳ **underway** (since 18:02:05 UTC) | — |
| 16.B.6 — 7-day soak gate → PROMOTE / ROLLBACK | ⏳ pending | next-next session |

## Next session

Owed work:

1. **Phase 16.B Item 3** — `scripts/audit_router_soak_gate.py` + runtime kill-switches in `_paper/runner.py` + 3 new tests (NO DEPLOY) — per phase-prompts/phase-16b-4-wrapper-wire-2026-05-12.txt §Item 3.
2. **`scripts/audit_router_shadow.py`** — Item 2 step g; runs at +24h (~2026-05-12 18:02 UTC) to compare router-would-fire vs actual-fired per cohort.
3. **Deploy `3875d3c` wide_fire fix** — bundled with whatever restart Item 3 or the audit script trigger.
4. **24h shadow audit interpretation** — note the audit script will already see fewer `<15%` phantom-defended fires after `3875d3c` deploys; expected because those abstentions ARE the desired behavior.

## Related

- [[../runbooks/README|Runbooks]]
- [[../phases/phase-16b-every-window-mode|Phase 16.B ledger]]
- [[../decisions/README|Decisions index]]
- [[2026-05-11-phase-16b|Prior session — Phase 16.B research → design → router primitives]]
- [[2026-05-11-phase-13-fill-rate-lift|Phase 13 NULL — earlier fill-rate audit]]

## Tags

`#phase-16b` `#every-window` `#router` `#vps-deploy` `#shadow-soak` `#phantom-fill` `#wide-fire` `#fill-rate-audit`
