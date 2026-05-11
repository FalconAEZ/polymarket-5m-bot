---
title: Phase 16.B research study — every-window mode with signal-driven routing
date: 2026-05-11
status: research-only (no code shipped)
tags: [research, strategy, phase-16b, every-window, signal-routing, decision-6-revisit]
authors: [claude+operator]
---

# Phase 16.B — every-window mode with signal-driven routing

> **Operator thesis (2026-05-11):** _"We already have so many gates and filters and ways to know if a trade will win or lose. Let's fire on every 5-min window, and use those gates/filters as **best-side / right-tier / right-size pickers** instead of FIRE-or-ABSTAIN binary gates. Make a fully research study within our Obsidian memory on how to tackle this properly to have max edge and WR."_

This study is the **research** half of Phase 16.B. The companion **plan** lives at `phase-prompts/phase-16b-every-window-mode-2026-05-11.txt` and the locked **design doc** will be written at `design/phase-16b-every-window-mode.md` before any code lands (anti-vibe rule #1).

No code is shipped from this document. The bot stays on its current strategy. Operator must sign off the plan before implementation begins.

---

## §0. What this study replaces / what it does NOT replace

| What it replaces | What it leaves alone |
|---|---|
| The composite-≥0.6 threshold as a FIRE/ABSTAIN gate (locked decision #6) | The `wide_fire` base candidate generation (still computes a side) |
| The wide-fire abstain logic (no edge → skip) | LLM ensemble call structure (3 specialists + meta) |
| The "$5 every fire OR no fire" model — adds size-shaping | The fixed $5/trade upper bound (decision #9 stays — sizing only shapes DOWN from $5, never up) |
| Trust in the LLM gate's binary ABSTAIN/FIRE | Trust in the LLM's vote as a **confidence weight** |
| | All 5 kill-switches, all defense layers (instant-settle, orphan-recovery, etc.) |
| | Locked decision #10 ($1k paper bankroll) |
| | Bot.service disabled, only bot-staging.service in scope |

**The two locked-decision revisits operator authorized:**
- **#6** (composite ≥0.6 threshold) — explicit, this session, "lets do this Lever γ"
- **#9** ($5 flat for first 100 trades) — **partially**. Size shaping DOWN from $5 ($1-5 range) is in scope so we can fire small on low-conviction windows. Going ABOVE $5 (e.g. Kelly) is Phase 17/18 territory and stays gated.

---

## §1. The current architecture (what we have now)

The strategy chain at fire time:

```
SpotTick / OracleUpdate / BookUpdate → EnsembleWrapper.on_event(...)
    │
    ▼
[1] Base strategy: wide_fire.maybe_fire(...)
    ├─ Computes composite = (delta_bps direction + magnitude)
    ├─ If |composite| < threshold OR TTL outside [10,30]s → returns None (ABSTAIN)
    └─ Otherwise returns Decision(side=sign(composite), size=$5, price_limit=...)
    │
    ▼
[2] Tier blocklist (Phase 14, dark)
    ├─ if tier(price_limit) in TIER_GATE_BLOCKLIST → emit "tier_abstained" + return None
    └─ Default: pass-through
    │
    ▼
[3] Regime gate (Phase 15, dark)
    ├─ if RegimeDetector.classify() in REGIME_GATE_ABSTAIN_REGIMES → emit "regime_abstained" + return None
    └─ Default: pass-through
    │
    ▼
[4] LLM ensemble (gate mode)
    ├─ Specialists: orderbook + oracle_gap + momentum (parallel Haiku)
    ├─ Meta: Sonnet synthesizes 3 votes + composite
    ├─ Returns MetaDecision(action=FIRE/ABSTAIN, side, confidence, rationale)
    ├─ If meta=ABSTAIN → return None (no fire)
    ├─ If meta=FIRE but meta.side != base.side → return None (disagreement = abstain)
    ├─ If meta=None (timeout/error/budget) → fall through to base (Phase 18B telemetry)
    └─ Otherwise return base Decision
    │
    ▼
[5] PaperRunner / ShadowBook
    ├─ Place post-only maker at price_limit
    ├─ TTL = 30s; if not filled by TTL, expires
    └─ At window close, settle via Gamma → write settled / settled_correction
```

**The bot fires on ~72% of windows (508/708 over 59h).** 28% are ABSTAINED by one of 5 gates. The single most-skipped gate is `wide_fire` itself (composite-magnitude too small).

## §2. The signal inventory — what we know predicts outcomes

Synthesized from the codebase-audit subagent + 7 audit/research docs in `runbooks/research/` + 4 phase checkpoints. Every signal scored by **predictive evidence** (validation data, not theory).

### §2.1 Signals with PROVEN predictive power

| Signal | Predictive power (validation) | Source | Used today |
|---|---|---|---|
| **`|delta_bps|`** | 0-1bps→50.2% WR; 1-2bps→48.7%; 2-5bps→55.0%; 5-10bps→**78.9%**. PnL per trade: −$0.09 / +$0.14 / +$0.63 / **+$1.67**. (n=513 today) | This study §3 + Phase 11.A.2 edge-discovery | Binary gate at threshold (≥0.6 composite); no shaped use of magnitude |
| **Regime (trending vs chop)** | Phase 15 audit n=477: trending WR 70.59% +$1.75/trade vs chop 47.40% −$0.22/trade. **+23.19pp delta.** Phase 13 revisit (n=39 unfilled): trending 60% W, mixed 57% W, chop 42% W. | `runbooks/gate-evidence/regime-classifier-validation.txt` + `state/sessions/2026-05-12-phase-13-revisit.md` | Binary gate (Phase 15, dark by default) |
| **Tier (price band)** | Tier 30-50% +$0.79/trade. Tier 50-70% −$0.42/trade despite 60% of volume. Tier 15-30% +$15/trade (n=8). | `runbooks/research/edge-discovery-2026-05-09.md` + Phase 14 audit | Binary blocklist (Phase 14, dark by default) |
| **Side (UP/DOWN)** | Today's 513-fire snapshot: **UP 53.3% / +$0.49 per trade vs DOWN 48.8% / −$0.43 per trade.** $237 PnL swing depending on side. May be sample asymmetry. | This study §3 | Implicit — derived from `sign(composite)`, no override |
| **Pre-gate vs post-gate (mode)** | Phase 13 revisit (n=477): pre-gate fill 86%+, post-gate fill 40-67%. LLM gate-mode 12s blocking allows ask-walks → drops fills. | `state/sessions/2026-05-12-phase-13-revisit.md` | Implicit — gate mode is current default |

### §2.2 Signals we compute but underuse (input features for a router)

| Signal | What's known | Why underused today |
|---|---|---|
| **`p_win`** (priors table) | Bonereaper 30-day prior; tier × Δ_bps lookup. Used in v2 EV gate. | v2 was reverted to wide_fire base; priors lookup dropped |
| **`ev_dollars` = (p_win − price − fee) × size** | v2 fired only if ev ≥ $0.005; rejected losers (62% WR on EV [0.02,0.05) but −$60). | Same — wide_fire ignores EV, fires on composite only |
| **`book_imbalance`** | (bid − ask) / (bid + ask). Specialist agent uses for vote. Cron ABSTAIN if `|imbalance| < 0.1`. | Continuous strength signal collapsed to a 0.1 threshold |
| **`ask_size_top` / `bid_size_top`** | Top-of-book depth per side. Used in floor-guard phantom-fill defense; not in fire decision. | Defensive only; not a positive signal |
| **`oracle_age_s`** | Time since last Chainlink update. 0-33s typical; >999 means stale. Oracle-gap specialist uses for confidence. | Implicit — used inside agent, not as standalone gate |
| **`spot_recent_60s` trajectory** | Last ~12 ticks of spot. Momentum specialist uses for acceleration sign. Deterministic baseline has no accel term. | Locked inside agent's brain |
| **LLM specialist confidences** | Each of orderbook/oracle_gap/momentum returns `confidence ∈ [0,1]`. | Aggregated by meta; not surfaced as a continuous router input |
| **LLM meta confidence** | Sonnet returns confidence on each call (Phase 18B telemetry now logs it). | Discarded after fire/abstain dispatch |
| **`meta_outcome`** (Phase 18B, NEW) | Per-fire tag: ok / api_error / refusal / no_text / validation_failed / invariant_violated / timeout / no_meta_call. | Just landed; not yet driving any decision |

### §2.3 Signals that COULD be added (not in scope today, but Phase 16.B should architect for them)

- **5m / 10m / 30m realized volatility** — input to regime classifier already; could be a continuous router input
- **Time-of-day** (UTC hour bucket) — `runbooks/research/edge-discovery` shows wide hour-of-day PnL variance
- **Recent-5-trade rolling WR** — drift detector for kill-switch + size-shaper
- **Spot-vs-VWAP-of-window** — alternative momentum signal; not in current code

---

## §3. The data — what the bot actually does

### §3.1 Window participation (3-day soak)

- **708 possible 5-min windows** over 59 hours
- **508 had ≥1 fire** = 71.8% participation
- ~200 missed windows (28%). Distribution of WHY (audit pending — needs a `scripts/audit_window_skip.py` to slice):
  - `wide_fire` abstain (|composite| < threshold): **majority** — the bot has no opinion
  - LLM meta=ABSTAIN: some
  - LLM gate-mode timeout: small (8.8% of votes per Phase 18B audit)
  - Cold-start (no spot/oracle context): rare after Phase 11.A spot-fallback fix
  - Bot was down: 30min (the Phase 15.5 SIGKILL+restart window)

### §3.2 Per-tier outcomes (515 fires)

| Tier | Fired | Filled | Fill% | WR | PnL | $/trade |
|---|---:|---:|---:|---:|---:|---:|
| **<15%** | 58 | 26 | **44.8%** | 55.2% | −$25 | −$0.43 |
| **15-30%** | 8 | 8 | 100% | **75%** | **+$122** | **+$15.20** |
| **30-50%** | 79 | 77 | 97.5% | 48.1% | +$64 | +$0.81 |
| **50-70%** | 305 | 298 | 97.7% | 50.5% | **−$93** | −$0.31 |
| **70-85%** | 19 | 18 | 94.7% | 68.4% | −$8 | −$0.44 |
| **85-100%** | 44 | 2 | **4.5%** | 47.7% | +$1 | +$0.02 |

**Takeaways:**
- The fill problem is at BOTH tier extremes (`<15%` and `85-100%`), not just one side.
- The 50-70% tier dominates volume (60%) and is the biggest PnL leak.
- 15-30% is a unicorn — tiny sample but real edge ($15/trade, 75% WR).
- `<15%` and `30-50%` show structurally different PnL despite similar WR — payoff asymmetry matters more than WR.

### §3.3 Per-`|delta_bps|` bucket (filled+settled subset, n=513)

| `|delta_bps|` | n | filled | WR | PnL | $/trade |
|---|---:|---:|---:|---:|---:|
| 0-1bps | 315 | 270 | 50.2% | −$27 | **−$0.09** |
| 1-2bps | 119 | 94 | 48.7% | +$17 | +$0.14 |
| 2-5bps | 60 | 48 | 55.0% | +$38 | +$0.63 |
| **5-10bps** | 19 | 17 | **78.9%** | +$32 | **+$1.67** |

**Takeaways:**
- The "easy money" sits at `|delta_bps| ≥ 5bps`. WR jumps from 55% to 79%.
- The biggest bucket (0-1bps, 62% of fires) is essentially break-even noise.
- This SHOULD drive size shaping: small bets on 0-2bps, full $5 at 2-5bps, $5+ at 5-10bps (if #9 allowed).

### §3.4 Per-side bias (today's snapshot)

| Side | n | WR | PnL | $/trade |
|---|---:|---:|---:|---:|
| UP | 304 | 53.3% | +$148 | +$0.49 |
| DOWN | 209 | 48.8% | −$89 | −$0.43 |

**Takeaway:** $237 PnL swing depending on side. Either BTC trended up during the soak window (sample asymmetry) OR there's a structural advantage to UP fires (asymmetric slippage / oracle bias / token liquidity profile differing UP vs DOWN). Need ≥7 more days to know.

### §3.5 Regime-conditional WR (Phase 15 audit)

| Regime | n_settled | WR | PnL | $/trade |
|---|---:|---:|---:|---:|
| **Trending** | 27 | **70.59%** | +$329 | **+$12.20** |
| Mixed | 136 | 50.7% | +$450 | +$3.31 |
| **Chop** | 249 | **51.4%** | +$1,725 | +$6.93 |

**Takeaway:** chop has *near-coinflip WR* but is the bot's PnL workhorse (60% of volume, +$1.7k of +$2.5k). The Phase 15.5 audit found that +$2.5k was mostly phantom-fill-corrected to +$75. **Re-running Phase 15's audit on corrected data is a P0 dependency** before Phase 16.B can stratify by regime correctly. Adding it to the audit slate.

### §3.6 The 2026-05-09 regime-shift case study

`runbooks/research/regime-shift-investigation-2026-05-09.md` — perhaps the most important prior research for Phase 16.B:

> Pre-peak (trending, 7.5h): 96 settled / 61.5% WR / +$133 / +$1.40 per trade
> Post-peak (chop, 12h): 147 settled / **41.5% WR** / **−$134** / **−$0.92** per trade
> **WR dropped 20pp on the same trades, same tier mix, same Δ buckets.** The signal itself stopped working in chop.

This is the smoking-gun evidence that **regime is the master switch**. Every-window mode must condition on regime to avoid amplifying the chop loss.

---

## §4. The proposed router architecture

The thesis: **transform the 5 binary gates into a continuous decision function** `(window_context) → (side, size_usd, ttl_s, fill_style, price_limit_offset)`. Every window emits SOMETHING.

### §4.1 Decision pipeline

```
SpotTick / OracleUpdate / BookUpdate
    │
    ▼
[A] Compute features (no gates):
    ├─ composite_pct, delta_bps, oracle_gap, ev_dollars (deterministic)
    ├─ regime ∈ {trending, mixed, chop, unknown}
    ├─ tier ∈ {<15%, 15-30%, ..., 85-100%}
    ├─ book_imbalance, ask_size_top, oracle_age_s
    └─ Optional: LLM specialist votes + confidences + meta_outcome
    │
    ▼
[B] Router decision (lookup table + deterministic functions):
    ├─ side       = pick_side(composite_pct, llm_meta_side)
    ├─ tier_route = tier_routing[tier] → (skip | maker | taker_fallback | reject_dangerous)
    ├─ size_usd   = size_for(regime, |delta_bps|, tier, ev_dollars, llm_confidence)
    ├─ ttl_s      = ttl_for(regime, tier, time_to_close_s)
    ├─ price_limit_offset = offset_for(tier, regime, book_imbalance)
    └─ veto_reasons = [...]  # only for SAFETY (phantom-fill defense, ev catastrophic)
    │
    ▼
[C] Veto check (RARE — only catastrophic):
    ├─ ev_dollars < $-0.50: skip this window (rare guard against −$5 expected loss)
    ├─ price <= $0.05 AND ask_size_top is None: skip (phantom-fill defense, preserve from Phase 11.A)
    ├─ oracle_age_s > 999 AND regime == chop: skip (no signal, bad regime)
    └─ All others: FIRE
    │
    ▼
[D] Place order:
    ├─ Maker-first if tier_route == "maker"
    ├─ Maker-with-taker-fallback-at-TTL/2 if tier_route == "taker_fallback"
    ├─ Pure taker (cross spread immediately) if tier ∈ extremes AND regime == trending
    └─ price_limit = base ± offset
```

### §4.2 The `tier_routing` table (first-cut, calibrated from §3.2)

| Tier | Route | Why |
|---|---|---|
| <15% | **taker_fallback** | 44.8% fill today, +55% WR when filled. Taker at TTL/2 catches the maker-fail case. |
| 15-30% | maker (current) | 100% fill, 75% WR, $15/trade. Don't touch what works. |
| 30-50% | maker (current) | 97.5% fill, 48% WR, +$0.81/trade. Payoff asymmetry covers sub-50 WR. |
| 50-70% | **size_down** | The $93 leak. Halve stake ($2.50). Halt later if rolling WR drops further. |
| 70-85% | maker (current) | 94.7% fill, 68% WR. Small sample. |
| 85-100% | **taker_fallback** | 4.5% fill today — most cataclysmic. Taker at TTL/2 brings fill rate up. |

### §4.3 The `size_for` function (first-cut)

```python
BASE = 5.0  # locked decision #9 — never go ABOVE
def size_for(regime, abs_delta_bps, tier, ev_dollars, llm_confidence):
    size = BASE
    # Regime down-shapes
    if regime == "chop":
        size *= 0.5
    elif regime == "unknown":
        size *= 0.7
    # Magnitude shape
    if abs_delta_bps < 1.0:
        size *= 0.4         # mostly coinflip — explore-only $2
    elif abs_delta_bps < 2.0:
        size *= 0.7         # small edge — $3.50
    # tier shape
    if tier == "50-70%":
        size *= 0.5         # known PnL leak — half size
    # llm confidence shape (only if available)
    if llm_confidence is not None:
        size *= max(0.4, min(1.0, llm_confidence))
    # ev safety
    if ev_dollars is not None and ev_dollars < 0:
        size *= 0.4         # explore-only on negative EV
    return max(1.0, round(size, 2))  # never below $1
```

This gives a size range of **$1 to $5**. The $5 cap honors decision #9 — we only ever shape DOWN. Phase 17 will introduce upward shaping (Kelly etc.).

### §4.4 The `pick_side` function

```python
def pick_side(composite_pct, llm_meta_side, regime, delta_bps):
    # Default: deterministic
    base_side = "UP" if composite_pct >= 0 else "DOWN"
    if llm_meta_side is None:
        return base_side
    # Agree: trust both
    if llm_meta_side == base_side:
        return base_side
    # Disagree:
    #   In trending regime, LLM is the smart-money override
    #   In chop, deterministic wins (LLM has no signal in chop either)
    #   At |delta_bps| < 1, take LLM's side (deterministic is noise)
    if regime == "trending":
        return llm_meta_side
    if abs(delta_bps) < 1.0:
        return llm_meta_side
    return base_side
```

### §4.5 The `ttl_for` function

```python
def ttl_for(regime, tier, time_to_close_s):
    # Default 30s; extend in chop (fills are slower); shrink in trending (urgency)
    base_ttl = 30
    if regime == "chop":
        base_ttl = 90      # let maker sit on book longer
    elif regime == "trending":
        base_ttl = 20      # urgency — cross sooner if needed
    if tier in ("<15%", "85-100%"):
        base_ttl = max(base_ttl, 90)   # always let extreme-tier maker work longer
    return min(base_ttl, max(10, time_to_close_s - 5))
```

### §4.6 What gets "vetoed" rather than "abstained"

The router fires on **every window**, but with three safety vetoes:

1. **Phantom-fill defense:** preserves Phase 11.A — if `price ≤ $0.05` AND `ask_size_top is None`, don't trade (this saved us from $2.5k in fake PnL).
2. **Catastrophic-EV:** if `ev_dollars ≤ −$0.50` (i.e., expected loss ≥ 10% of $5 stake), don't trade.
3. **Cold-start:** if `spot_now` or `window_open_spot` is None, fall through to base wide_fire behavior (which already handles this).

Everything else is a **fire** with some size + side + style.

---

## §5. Counterfactual — what does the new strategy DO with the existing 513-fire dataset?

This study cannot run a real backtest (no historical tick-by-tick replay infrastructure for this), but we can compute the **router's intended action** on each existing fire and compare to actual outcomes. That's not a forward-test, but it surfaces whether the router would have OBVIOUSLY worsened any single bucket.

### §5.1 Synthetic re-routing of the 513 historical fires

(Audit script `scripts/audit_router_counterfactual.py` is a Day-0 deliverable. The numbers below are projections from §3 data, not measured.)

| Cohort | Today | Expected router behavior | Expected delta |
|---|---|---|---|
| 0-1bps `|Δ|` (315 fires) | $5 fires, 50% WR, −$27 | Size halved to $2, same WR | **−$13 (less loss)** |
| 5-10bps `|Δ|` (19 fires) | $5 fires, 79% WR, +$32 | Same size, same WR | **+$0** |
| <15% tier (58 fires) | 32 unfilled, +0 PnL from those | Taker fallback fills most | **+$10-30 (best case)** |
| 85-100% tier (44 fires) | 42 unfilled, +$0.74 net | Taker fallback fills most | **+$10-30 (best case)** |
| 50-70% tier (305 fires) | $5 fires, 50.5% WR, −$93 | Size halved to $2.50 | **+$46 (half loss)** |
| Chop regime (249 settled) | Mix, +$1725 (pre-correction) | Size halved | **−$60 PnL, +0 WR** |

**Net counterfactual PnL ≈ −$13 + 0 + $10-30 + $10-30 − $60 − ... = roughly flat-to-positive on the existing fires** AND **adds 200 NEW fires from the previously-abstained windows.**

The 200 new fires' expected behavior:
- Most live in 0-1bps `|Δ|` (the abstain bucket) → at small size ($2), 50% WR, ~0 PnL
- Some live in chop regime → at half size, 47-51% WR, slight loss
- A few are 1-2bps where wide_fire was conservative → fire $3.50, ~50% WR
- **Expected from 200 fires: −$10 to +$20 over the cohort**

**Net expected delta: +$10 to +$50 over the same window, with 700-row data instead of 500-row data.**

Important caveat: this is signal-conditional. If the chop:trending ratio swings adverse, we lose. The kill-switch design must include a rolling WR floor.

### §5.2 What this counterfactual does NOT prove

- That the router IMPROVES strategy. Could be break-even / mildly net-loss.
- That the new 200 fires are profitable individually.
- That fills will actually behave as projected (taker fallback may slip more).
- That the LLM's confidence-as-weight produces good size choices.

These are why **Phase 16.B ships dark with a 7-day soak gate**, identical pattern to Phases 14 + 15.

---

## §6. Risk analysis

### §6.1 Strategy-level risks

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| Router loses money vs current strategy | Medium (40%) | Medium ($50-100 net PnL loss over a week) | 7-day dark soak; kill-switch on rolling-100-trade WR drift; per-bucket PnL audit at +24h, +48h, +7d |
| Taker fallback eats spread > expected gain | Medium (30%) | Low ($10-30 over experiment window) | Cap taker offset at 2¢; default OFF for first 24h of soak |
| Size-down in 50-70% misses winners | Low (20%) | Low ($20 over experiment window) | Audit shows that tier loses on average — downside is asymmetric |
| LLM `meta.confidence` is mis-calibrated as a size weight | Medium (40%) | Medium ($30-60 leak) | Floor at 0.4, cap at 1.0; A/B with LLM-weight enabled/disabled |
| Regime classifier flips at the wrong moment | Low (10%) | High ($100+) | Already-validated regime detector (Phase 15); 5m + 10m volatility windows give some smoothing |
| Increased order placement load → infra fault | Low (5%) | Medium (1-2 hour soft outage) | Existing instant-settle defense; orphan-recovery already running |

### §6.2 Locked-decision risks

| Decision | Risk of revisit | Mitigation |
|---|---|---|
| #6 (composite ≥0.6 threshold) | Operator-explicit override authorized this session | Document the revisit; new kill-switch `EVERY_WINDOW_MODE` defaults OFF for ANYONE who pulls the branch |
| #9 ($5 flat) | Partial revisit — DOWN-shaping only | Cap at $5 (never above); soft floor at $1; Phase 17 lands upward Kelly |
| #10 ($1k paper bankroll) | Untouched | Phase 16.B is paper-only, $1k bankroll unchanged |
| #5 (3 specialists + meta) | Untouched | Same ensemble structure; just consumes confidence differently |

### §6.3 Operational risks

- **Anthropic budget:** every-window mode fires LLM on every window (vs ~72% today) → ~40% more LLM calls. Current spend ~$1-3/day; expected ~$1.40-4.20/day. Hard cap $10/day — within budget.
- **Dashboard observability:** the v3 dashboard's `meta_outcome` panel needs to surface route+veto stats too. Out of scope for Phase 16.B core; Phase 22 will land it.
- **Test surface:** EVERY routing function needs unit tests + the counterfactual replay test must run as a regression.

---

## §7. The plan — phases of phase 16.B

Subdivided so each piece passes its own anti-vibe gate.

### Phase 16.B.1 — Counterfactual audit script (no code in src/; 1h)

Build `scripts/audit_router_counterfactual.py` that re-routes the existing 513 fires through the proposed router and reports per-cohort delta vs actual. Operator reviews before Phase 16.B.2.

### Phase 16.B.2 — Design doc lock (anti-vibe #1; ~30min)

`design/phase-16b-every-window-mode.md` — locks the router architecture, env vars, kill-switch behavior, test plan. Operator signs off.

### Phase 16.B.3 — Router primitives in src/ (~3h)

```
src/polymarket_bot/strategies/every_window/
    router.py              # pick_side, size_for, ttl_for, tier_routing, vetoes
    types.py               # RouterContext dataclass + RouterDecision
    config.py              # tunable thresholds (env-driven)
```

Plus tests under `tests/strategies/test_every_window_router.py`:
- per-tier routing decisions (parametric)
- size-shaping monotonicity (more signal → larger size; cap at $5; floor at $1)
- veto preservation (phantom-fill, catastrophic-EV, cold-start)
- 100-eval performance benchmark < 500ms (queue-overflow guard)

**Pure-function additions. No call sites change. Zero behavior risk.**

### Phase 16.B.4 — Wire into EnsembleWrapper as a strategy variant (~2h)

New `STRATEGY=every_window` env path in `scripts/run_paper.py`. When set, the wrapper consults the router AFTER specialists+meta vote (which still run as inputs) and emits a Decision per window — never abstains.

`EVERY_WINDOW_MODE` env (bool, default false):
- `false`: ZERO BEHAVIOR CHANGE. All current gates intact.
- `true`: router takes over; the 5 gates become input signals.

Plus:
- `EVERY_WINDOW_TAKER_FALLBACK_TIERS=<15%,85-100%` — CSV of tier labels that get taker fallback at TTL/2.
- `EVERY_WINDOW_SIZE_FLOOR_USD=1.0` — bottom of size shaping.
- `EVERY_WINDOW_SIZE_DOWNSHAPE_TIERS=50-70%` — CSV of tiers that get half-size.

Tests: 7 new in `test_ensemble_wrapper.py` — every-window-mode-emits-on-every-tick + size-shape-passes-through + LLM-confidence-feeds-router + dark-mode-still-respects-old-gates + kill-switch-flips-cleanly.

### Phase 16.B.5 — Dark deploy + 24h shadow + audit (~30min ops, then 24h wait)

Ship dark to VPS, env unset. After 24h of bot soak in **shadow mode** (router decision LOGGED but base strategy still fires), audit the divergence between router-would-fire vs current-fires. If divergence looks sane → flip env to gate mode (router DRIVES) for the next 24h. If router goes catastrophic → flip back to false instantly.

### Phase 16.B.6 — 7-day soak gate (the real test)

Same pattern as Phase 23 in master plan. Compare:
- PnL/trade (router vs control day, day-by-day)
- WR (rolling 100-trade)
- Per-tier behavior changes
- Per-regime behavior changes

**Promote criteria:** WR ≥ baseline +1pp AND PnL/trade ≥ baseline +20% AND no day-low below −$30. Otherwise rollback.

---

## §8. Open questions for operator (before Phase 16.B.2 design lock)

1. **Size shaping — is $1-$5 down-shaping acceptable in scope, or do you want strictly $5 flat?** I recommend yes-to-$1-floor because it's the lever that turns the "fire on bad windows" risk into a "fire small and observe" experiment.
2. **Taker fallback on `<15%` and `85-100%` — is paying 1-2¢ slippage worth fill rate boost?** I recommend yes, gated by env.
3. **Should the router use `meta.confidence` as a size scaler from day 1, or as observation-only first?** I recommend observation-only for 24h, then flip on.
4. **Is the chop-regime SIZE-HALVING aggressive enough, or do you want chop-skipping** (closer to Lever β from earlier plan)? I recommend halving for soak; can skip later.
5. **What's the kill-switch trigger threshold?** I recommend: rolling-100-trade WR < 45% OR daily PnL < −$30 triggers `EVERY_WINDOW_MODE=false` automatically.

---

## §9. What gets WRITTEN INTO the locked decisions list (after operator sign-off)

If Phase 16.B promotes through its 7-day gate, the following changes to `~/.claude/projects/.../memory/project_decisions.md`:

```
| 6 (REVISED 2026-05-11) | Composite threshold lifted from hard ≥0.6 FIRE gate
   to: composite_sign provides BASE_SIDE; magnitude shapes SIZE not FIRE/ABSTAIN.
   Router fires on every window with size ∈ [$1, $5]. |
| 9 (PARTIAL REVISIT) | $5 flat for first 100 trades softened to "up to $5,
   never above"; downward-shaping ($1-5 range) authorized for low-conviction
   windows. Phase 17 enables true Kelly upward sizing later. |
```

These revisits require the 7-day gate + operator explicit confirmation in writing.

---

## §10. Pointers / cross-references

- **Codebase signal inventory** — `state/research/phase-16b-every-window-study.md` §2 (this doc, expanded above)
- **Phase 14 audit (tier WR)** — `runbooks/research/edge-discovery-2026-05-09.md`
- **Phase 15 audit (regime WR)** — `runbooks/gate-evidence/regime-classifier-validation.txt`, `state/sessions/2026-05-12-phase-15-regime-gate.md`
- **2026-05-09 regime-shift case** — `runbooks/research/regime-shift-investigation-2026-05-09.md`
- **Phase 13 NULL + revisit** — `state/sessions/2026-05-12-phase-13-revisit.md`
- **Phase 11.A.2 v2 edge-discovery** — `runbooks/research/edge-discovery-2026-05-09.md`
- **Master plan §4 (phases 17-25)** — `pdfs/PHASE_12_MASTER_PLAN.pdf`
- **Strategy intent (locked)** — `~/.claude/projects/.../memory/project_strategy_intent.md`
- **Locked decisions (locked)** — `~/.claude/projects/.../memory/project_decisions.md` (#6 + #9 are the revisits in scope)
- **Anti-vibe rules** — `state/concepts/anti-vibe-rules.md`
- **Kill-switches concept** — `state/concepts/kill-switches.md`

---

## §11. TL;DR for the operator

> The bot has 8 strong signals (regime, tier, `|delta_bps|`, side, p_win, EV, book_imbalance, LLM confidence). Today the strategy uses them as **abstain gates** and skips 28% of windows. Operator-thesis: turn the same signals into a **router** that emits a (side, size, ttl, fill_style) decision for every window. The data already shows enough signal-conditional behavior (regime 23pp WR delta, tier 60% volume / negative PnL leak, side 9pp WR delta) that this is plausible.
>
> Phase 16.B ships this in 6 substeps: counterfactual audit → design lock → router primitives → wire into wrapper as opt-in env → 24h shadow audit → 7-day gate. Decision #6 is explicitly revisited; decision #9 is partially relaxed (downward-shaping only); decision #10 untouched. Kill-switch automatic. Estimated total work: 8-10 engineering hours, then 7-day soak.
>
> Net expected delta from the existing data: **+$10 to +$50 over a 3-day window** (combination of new fires + size-shaping reducing bad-bucket bleed). 7-day soak gate enforces promotion or rollback.
>
> Operator: sign §8 questions and I draft the design doc next.
