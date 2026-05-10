# Phase 13 — fill-rate audit + tractable price-limit lift

**Session start:** 2026-05-10 (UTC) at HEAD `c66fc07`
**Branch:** `claude/hopeful-mcnulty-b81585` (worktree of `claude/jovial-hermann-7e103f`)
**Bot state at start:** active on bot-staging, ENSEMBLE_MODE=gate since 2026-05-10 16:31:15 UTC, 5 defense layers live.

---

## Item 1 — Fill-rate audit (no-code phase)

### Method

`scripts/audit_unfilled_v2.py` joins `kind=fired` and `kind=settled` records by `decision_id` and classifies each fired record as:

- `filled_at_fire`   — taker fill at fire-time (`fired.fill` non-null)
- `filled_at_settle` — maker fill at settle (`settled.fill_at_settle` non-null)
- `never_filled`    — neither
- `no_settle`       — fired but no settled record (pending/lost)

For each `never_filled` record we compute `gap = best_ask - price_limit` (in dollars) and bucket it:

- `0-1c` (0 < gap ≤ $0.01) — tractable if counterfactual W ≥ 50%
- `1-2c` ($0.01 < gap ≤ $0.02) — tractable if counterfactual W ≥ 50%
- `2-5c` ($0.02 < gap ≤ $0.05) — marginal; lift only with explicit operator approval
- `>5c`  (gap > $0.05) — saturated market; do not chase
- `floor_guard` — `price_limit ≥ best_ask` with `best_ask ≤ $0.05` and `ask_size_top=null` (correct refusal class — phantom-fill defense)
- `OTHER` — `price_limit ≥ best_ask` but didn't fill for other reasons (mostly depth-guard refusals)
- `missing_book` — snapshot lacked `best_ask` (shouldn't happen post Phase-5)

Counterfactual W = `(resolution == fired.side) | resolution known` — i.e. "would we have won if we'd filled at best_ask?" Resolution sourced from the settled record (Chainlink wrong-resolution corrections already merged via `settled_correction`). 95% Wilson CI reported.

### Data inventory

The VPS has 3 daily JSONLs (prompt asked for 5; only 3 exist):

| date | n_fired | filled_at_fire | filled_at_settle | never_filled | no_settle | fill rate |
|------|---------|----------------|------------------|--------------|-----------|-----------|
| 2026-05-08 | 39  | 59.0% | 15.4% | 17.9% | 7.7% | **74.4%** |
| 2026-05-09 | 262 | 100.0% | 0.0% | 0.0% | 0.0% | **100.0%** |
| 2026-05-10 | 166 | 56.0% | 13.3% | 30.7% | 0.0% | **69.3%** |
| **AGGREGATE** | **467** | 80.9% | 6.0% | 12.4% | 0.6% | **86.9%** |

**The three days are NOT homogeneous:**

- 2026-05-08 ran `strategy=spot_aware mode=aggressive` (different price-limit logic — `price_limit == best_ask` ties → simulator depth-guard refusal).
- 2026-05-09 ran `wide_fire` shadow-mode → 100% taker fills (the spot-derived price already lifted ~2¢ above ask, taker-crosses on every fire). No unfills to bucket.
- 2026-05-10 ran `wide_fire` (mixed pre/post gate-flip at 16:31 UTC). Of 166 fires: 159 pre-gate (89 filled = 56.0%), 7 post-gate (4 filled = 57%).

Because 2026-05-09 has zero never-filled and 2026-05-08 is a different strategy class, **the only legitimate dataset for a Phase-13 lift decision is 2026-05-10 (n=51 never-filled records, all under `wide_fire`)**.

### never_filled bucket table — 2026-05-10 (load-bearing)

| bucket       |  n | n_resolved | counterfactual_W | 95% CI (Wilson) | gate-decision |
|--------------|---:|-----------:|-----------------:|:---------------:|:--------------|
| **0-1c**     |  0 |          0 |           **n/a** | n/a            | **bucket is EMPTY — no lift target** |
| **1-2c**     | 39 |         39 |        **46.2%** | [31.6, 61.4]   | **FAILS ≥50% gate; CI straddles 50%** |
| 2-5c         |  0 |          0 |             n/a  | n/a            | bucket empty |
| >5c          |  0 |          0 |             n/a  | n/a            | bucket empty |
| **floor_guard** | 12 |       12 |        **66.7%** | [39.1, 86.2]   | **leave alone — correct refusal class (phantom-fill defense)** |
| OTHER        |  0 |          0 |             n/a  | n/a            | bucket empty |
| missing_book |  0 |          0 |             n/a  | n/a            | bucket empty |

(2026-05-08's 7 OTHER records bucket separately — `strategy=spot_aware`, irrelevant to current wide_fire decision.)

### Why 0-1c is empty

Spot-derived `price_limit` under `wide_fire` lands at one of two states relative to the book:

1. `price_limit > best_ask` by ~2¢ (most common — fires fill at taker price)
2. `price_limit < best_ask` by ~1-2¢ (the 1-2c bucket — fires don't taker-cross; rest as maker; sometimes fill at settle, sometimes never)

The 0-1c bucket is empty because the price-limit formula doesn't produce gaps in that range — it rounds to whole-cent ticks aligned with the book grid. A `LIFT_BPS=100` would jump these unfilled fires from the 1-2c bucket past best_ask (taker-cross), not into the 0-1c bucket.

### Verdict per master plan §4 deploy criteria

The prompt's lift policy:

> - Ship lift only if the 0-1c bucket counterfactual W ≥ 50%.
> - Ship lift to 2c only if 1-2c bucket counterfactual W ≥ 50%.
> - Do NOT lift past 2c without explicit operator approval.

**Both gates FAIL on 2026-05-10 data:**

- 0-1c bucket is empty (no point estimate to gate on).
- 1-2c bucket counterfactual W = 46.2% < 50% (CI [31.6, 61.4] — point fails, CI straddles).
- floor_guard is the correct-refusal class — lifting these = re-enabling the phantom-fill class from the 2026-05-09 incident.

**Honest pushback:** the unfilled-in-1-2c subset is *negatively selected* — these are windows where the market correctly priced our side worse than even (46.2% vs the bot's 52.0% overall WR). Forcing them in via `SPOT_AWARE_LIMIT_LIFT_BPS=100` would not raise fill quality; it would drag WR ~6pp toward 46% on the marginal trades and net-negative the PnL.

### Recommendation

**DO NOT ship the lift env right now.** The current `wide_fire` price-limit logic is already aggressive: it lifts ~2¢ above the spot-derived price for most fires (driving 56-100% taker-fill rates), and where it doesn't, the unfill is information — the market is pricing our side as a loser. Lifting these in burns money.

Three forward paths, in order of preference:

1. **Defer Phase 13 — advance to Phase 14 (per-tier WR codification).**
   Per the prompt's session boundary (c): "Audit shows no tractable subset → write null result, defer Phase 13, advance to Phase 14. 🛑 (this is success, not failure — honest pushback in action)." Phase 14 has a clearer payoff (the per-tier breakdown shows real WR divergence on the dashboard).

2. **Re-audit after 7+ days of pure gate-mode data** (currently we only have ~7 post-gate fires on 2026-05-10). If post-gate behavior diverges from pre-gate, the picture may change. Cheapest option: wait until 2026-05-17 and re-run the audit.

3. **Ship the env scaffolding with default=0 ONLY** (so we have the kill-switch ready). This is a "design-doc-but-no-behavior" change. The 36-page master plan §4 already prescribes the implementation. But this trades a few hours of code+tests for zero observed payoff — anti-vibe rule says don't build for hypothetical future requirements.

---

## OPERATOR SIGN-OFF — option (1) chosen

Operator confirmed 2026-05-10: **defer Phase 13, advance to Phase 14 in same session.**

Rationale captured for the record:
- 1-2¢ unfilled subset is *negatively selected* (46.2% WR vs bot's 52.0%); lifting these in dilutes WR.
- 0-1¢ bucket is empty (price grid doesn't produce gaps in that range).
- Scaffolding-with-default=0 is dead code until a future audit reverses; re-audit is <30 min if behavior shifts.
- Phase 14 per-tier WR codification has clearer payoff per master plan §6.

**Deliverables committed for Phase 13:**
- `scripts/audit_unfilled_v2.py` — re-runnable audit tool (ruff + mypy --strict green)
- this session note documenting the null result

Phase 13 is **complete as a null-result deferral** per the prompt's session boundary (c). Phase 13 prompt at `phase-prompts/phase-13-fill-rate-lift-2026-05-11.txt` is now archived intent — no code shipped, no env added. Advancing to Phase 14.
