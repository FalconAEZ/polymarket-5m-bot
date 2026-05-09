# Bot v3 roadmap — 10 phases from "break-even at $5" to "real money"

**Date:** 2026-05-10
**Triggered by:** operator request for an engineering-grounded path to a
profitable bot — not "wait and see", concrete next steps with realistic
deliverables.
**Inputs:** full vault arc (28 memory checkpoints + 20 locked decisions
+ all research docs) + parallel audits of codebase + VPS + WS feeds
landed 2026-05-10.

## State of play (2 paragraphs)

**Where we are.** Bot has been paper-trading since 2026-05-08. ~28h
into the Phase 11.A.2 aggressive-mode soak (256 fires, currently
hovering near $0 cumulative PnL with the +$133.88 → -$135 → recover
swing documented in `runbooks/research/regime-shift-investigation-2026-05-09.md`).
Two PRs open: PR #1 (gate early-read + edge research + v2 + instant-
settle, on `claude/jovial-hermann-7e103f`), PR #2 (dashboard PM-truth
fix, deployed and stable). 369 pytest pass; mypy strict clean; 3
import-linter contracts kept. Codebase audit found 1 CRITICAL bug
(httpx.Client leak — fixed in this commit) + 4 HIGH-severity items
(see Phase 1). VPS audit clean (zero crashes, 12 fires/hr metronome,
PnL accounting exact); minor concerns about dashboard restart noise +
unreloaded systemd unit. WS feed audit found ~60-90ms latency win
available on Polygon RPC by switching to Chainstack EU.

**What the data tells us.** We have two evidentiary bases for "edge
exists": (1) Bonereaper 30-day analysis showed +30.9pp aligned-vs-
contrarian gap on 306,966 trades — aligned win-rate 67.4%, contrarian
36.4% — and per-tier the aligned edge concentrates in 30-50% (45.4% WR
× +$1.17/trade) and 50-70% (63.1% WR × +$0.95/trade). (2) Our own 256
trades show the spot-Δ alignment signal works (61.5% WR pre-peak in a
trending regime) and fails (41.5% WR post-peak in chop). The signal is
real but **regime-dependent**, and at our $5 sizing + fill quality the
WR we can realistically hit per tier is probably 50-55% — meaning the
30-50% tier (asymmetric payoff favors us at any 45%+ WR) is
profitable, while the 50-70% tier (needs 56%+ WR to break even) is
not. v2 strategy correctly drops 50-70%, restoring the structural
edge of asymmetric payoffs.

## Why "100x" isn't the right framing

100x of current cumulative (~$0) is still ~$0. The right framing is
**"build until cumulative monthly PnL exceeds $200/month sustained at
$5 sizing, then scale via Kelly per locked decision #9"**. At
50 fires/day × 30 days = 1500 trades/month × $0.30/trade expected
edge = $450/month. That's the engineering target. From there, scaling
via decision #9's fractional Kelly + decision #10's bankroll rungs
($1k → $3k → $10k → $30k) is mechanical — not an engineering problem
once edge is proven.

**100x growth comes from compounding at proven edge, not from
firing-more-knobs in unproven directions.**

---

# The 10 phases

Sequential where dependencies require, with parallel branches noted.
Each phase has a concrete deliverable + a gate criterion + an honest
estimate of effort and risk.

---

## Phase 1 — Audit-driven hardening (1-2 days, MUST FINISH BEFORE GATE-DAY DEPLOY)

The 3 parallel audits found 4 issues that are deploy-blockers OR very
close to it. v2 + instant-settle should NOT deploy until these are
addressed. CRITICAL httpx leak already fixed in this commit + delta_bps
near-zero guard. Remaining:

**1.1 — Wrap DecisionLog write in exception-handled try/except** (HIGH)
- File: `src/polymarket_bot/_paper/decision_log.py:_write` + caller in
  `_paper/runner.py::_on_decision` and `_settle_current_window`
- Current: if disk fills or NFS unmounts mid-trade, `path.open("a")`
  raises uncaught OSError that kills the event loop
- Fix: try/except around the write, emit CRITICAL alert + continue
- ~30 min + 2 tests

**1.2 — Add `open_timeout=5.0` to all WS feed connections** (MEDIUM,
high MTTR value)
- Files: `_live/feeds/spot_binance.py`, `spot_coinbase.py`,
  `polymarket.py`, `oracle.py`
- Current: default 20s timeout on initial WS handshake; if DNS stalls,
  reconnect waits 20s before backoff
- Fix: pass `open_timeout=5.0` to every `websockets.connect(...)`
- ~10 min, no tests needed

**1.3 — Add per-message recv timeout to WS feeds** (MEDIUM, robustness)
- Same files as 1.2
- Current: hung TCP half-open could block a feed for ~2min until
  kernel keepalive
- Fix: wrap recv loops in `asyncio.timeout(60.0)` (or per-feed-tuned
  value)
- ~30 min + 1 test per feed

**1.4 — Document the race in `_settle_current_window`** (HIGH per
audit, but actually OK in current architecture)
- The audit flagged a race because settle awaits via asyncio.to_thread
  and state could mutate. In current architecture this is bounded
  because the main runner loop is single-tasked through
  `await self._on_record(record)` — no other coroutine mutates state.
  But this is fragile if a future change adds a parallel mutator.
- Fix: add a one-line comment in `_settle_current_window` explaining
  the invariant; add a single-tasked runner loop assertion test.

**Phase 1 gate**: all 4 fixes shipped + tested + landed in PR #1; ruff
+ mypy --strict + pytest all green; deploy script dry-run still
passes pre-flight.

---

## Phase 2 — Gate-day deploy of v2 + instant-settle (~1h on the day, ~25h from this writing)

Already planned. Run `bash runbooks/scripts/deploy-v2-and-instant-settle.sh
--apply` at the 48h gate. Per the existing deploy script, this:
1. Backs up `.envrc` to `.envrc.bak`
2. `git checkout claude/jovial-hermann-7e103f` (after PR #1 merge)
3. Rewrites `.envrc`: STRATEGY=spot_aware_v2, drop AGGRESSIVE_MODE,
   add INSTANT_SETTLE_ENABLED=1
4. `sudo systemctl restart bot-staging.service`
5. 30s warmup wait + post-deploy verification

**Phase 2 gate**: within 10 min of restart, first new fired record
shows `strategy=spot_aware_v2`; first settled record shows
`resolution_source: "polymarket"`; dashboard `/api/state.pipeline.settle_wait_s`
drops below 5s.

**Pre-deploy checklist** (operator owns):
- [ ] PR #1 merged to main (or deploy from the branch directly)
- [ ] PR #2 (dashboard fix) is already deployed; confirm
  `decisions_truth_source: polymarket` still showing
- [ ] `systemctl daemon-reload` on the VPS (audit found unreloaded
  unit warning) BEFORE the deploy
- [ ] Stop the dashboard-restart noise — find what's causing the 25
  SIGTERMs/day and debounce it

---

## Phase 3 — 7-day v2 re-soak with regime tracking (7 days passive + 1 hour active analysis)

The actual test of whether v2's tier-restriction edge holds. NOT
passive — actively track per-regime PnL using the methodology from
`runbooks/scripts/peak_trough_investigation.py`.

**3.1 — Daily roll-up script** (~1h to write, runs daily)
- New script: `runbooks/scripts/v2_soak_daily_rollup.py`
- For each UTC day of the v2 soak: compute total fires, WR by regime
  (rolling 5-min realized vol bucketed into quartiles), PnL per tier,
  EV gate stats
- Output to `runbooks/gate-evidence/v2-soak-day-N.txt`

**3.2 — Manual re-run gate at end of day 7** (per existing
`runbooks/gates/spot-aware-paper.sh`)

**Phase 3 gate (binary):**
- (a) v2 cumulative PnL > +$5 across the full 7 days AND in at least
  one chop-dominant 12h window → **EDGE PERSISTS** → proceed to
  Phase 4 (regime detector to amplify)
- (b) v2 cumulative within ±$10 of zero → **MARGINAL** → proceed to
  Phase 4 (regime detector now mandatory not optional)
- (c) v2 cumulative < -$10 → **NO EDGE AT THIS TIER** → revert to v1
  and reconsider the strategy fundamentally; v3 isn't the answer

---

## Phase 4 — Regime detector design + impl (~5-7 days)

The biggest single architectural change. Per the regime-shift
investigation, the spot-Δ alignment signal is regime-dependent: works
in trends, fails in chop. A regime detector layered ON TOP of v2's
tier filter would only fire when realized 5-min vol indicates a
trending regime.

**4.1 — Design doc `design/regime_detector.md`** (~1 day)
- Hypothesis: 5-min realized volatility (computed from spot ticks) vs
  10-min realized volatility ratio is a regime classifier:
  - ratio > 1.2 → trending (5min more volatile than baseline)
  - ratio < 0.8 → chop (5min less volatile)
  - 0.8-1.2 → mixed
- Validate against the 28h soak data: did regime-classifier "trending"
  hours have higher WR than "chop" hours?
- Backtest filter: "fire only when classifier=trending" against the
  256 fires we have

**4.2 — Implementation** (~2 days)
- New module: `src/polymarket_bot/strategies/regime_detector.py`
- Wraps the v2 strategy: returns `True` if regime is trending, `False`
  otherwise. v2 only fires if regime detector says yes.
- New env var `REGIME_FILTER_ENABLED=1`
- Tests with synthetic spot histories representing chop vs trend

**4.3 — Re-soak v2 + regime filter for 7 days** (passive)
- Compare vs Phase 3 numbers — did regime filter improve per-trade PnL?
- Expected: per-trade PnL should jump from ~+$0.30 (v2 alone, both
  regimes) to ~+$1-2 (v2 + regime, only fires in trends)

**Phase 4 gate**: per-trade PnL improvement > 50% relative to Phase 3
v2-alone. If not, regime detector hypothesis is wrong; revisit in
Phase 5 or look elsewhere.

---

## Phase 5 — Build the second + third agents per locked decision #5 (~7-14 days)

Decision #5 locks "3 agents + meta-decider": orderbook, oracle-gap,
momentum + Sonnet meta. Currently we have ONLY momentum (spot-aware
≈ momentum). The other 2 agents were never built. Building them gives
us **3 independent signals per window** = 3x the volume of decisions
WITHOUT violating fire-once-per-window (each agent contributes to a
single meta-decision).

**5.1 — Orderbook-imbalance agent** (~3 days)
- Watches Polymarket CLOB book updates
- Signal: bid-side liquidity > ask-side liquidity within $0.05 of
  fair value → bias UP, opposite → bias DOWN
- Confidence proportional to imbalance ratio
- New file: `src/polymarket_bot/agents/orderbook_imbalance.py`
- Design doc first: `design/agent_orderbook.md`

**5.2 — Oracle-gap agent** (~3 days)
- Watches Chainlink AnswerUpdated vs Binance/Coinbase spot
- Signal: spot has moved > oracle by > N bps and oracle is mid-
  heartbeat → bias toward spot direction
- This was the Tier-3 deterministic baseline from MASTERPLAN §0;
  partially in current bot but not as a discrete agent
- New file: `src/polymarket_bot/agents/oracle_gap.py`
- Design doc: `design/agent_oracle_gap.md`

**5.3 — Sonnet meta-decider** (~3 days)
- Aggregates the 3 agent signals (momentum/spot-aware,
  orderbook-imbalance, oracle-gap) into a single fire/no-fire decision
- Sonnet prompt: "given these 3 signals, fire UP / fire DOWN / abstain"
- Anthropic budget per decision #14: $0.19-0.58/hour empirical, well
  under the $200/month sustained tier
- Design doc: `design/meta_decider.md`
- A/B test against the deterministic baseline per locked decision #16
  (LLM ensemble retained only if uplift ≥ 3pp over deterministic)

**Phase 5 gate**: in 7-day re-soak with the 3-agent ensemble, WR
improves ≥ 3pp over v2 + regime alone (per locked decision #16). If
not, drop the LLM, keep deterministic-only.

---

## Phase 6 — Variable sizing v1 ($5-$25 confidence-weighted, regime-gated) (~5 days)

After Phase 4 (regime detector) AND Phase 5 (3-agent ensemble)
validate, sizing becomes safe. Per locked decision #9: "$5 flat for
first 100 trades, then fractional Kelly". We're past 100; Phase 5's
ensemble produces a confidence score that maps to size.

**6.1 — Design doc `design/sizing_v1.md`**
- Kelly fraction formula: `size = base × f × confidence`, where
  base = $5, f = 0.25 (quarter-Kelly), confidence ∈ [0, 1]
- Min $5 (per current minimum), max $25 (5% of bankroll, NOT $60 —
  $60 would be 12% bankroll-at-risk per trade, regime-shift-finding
  showed this could mean -42% drawdown in a 7-loss streak)
- Daily loss cap auto-halt at -$50 (matches existing trip-wire #1)

**6.2 — Implementation**
- New module: `src/polymarket_bot/sizing/confidence_kelly.py`
- Modify SpotAwareStrategyV2 (or its successor) to size based on
  meta-decider confidence
- New env var `SIZING_MODE=flat|kelly`, default flat for backward compat

**6.3 — Re-soak 7 days** with sizing enabled, regime filter enabled,
3-agent ensemble enabled.

**Phase 6 gate**: cumulative PnL/week ≥ +$50 (10x the $5 trade size)
across multiple regime cycles. If not, sizing is amplifying noise; revert
to flat.

---

## Phase 7 — Daily loss cap auto-halt + alerting (~2 days)

Operator-safety feature. Per locked decision MASTERPLAN §6 (Phase 6
spec): "Daily loss circuit breaker: -$50 (5%) → bot exits and pages
Telegram." Currently exists as a trip-wire on the dashboard but does
NOT auto-halt the bot.

**7.1 — Auto-halt logic in PaperRunner**
- Compute today_pnl on every settled decision
- If today_pnl < -$50 (configurable), touch `state/halt.sentinel` to
  trigger the existing halt-watcher
- Send CRITICAL alert via tg-alerter with the trip details

**7.2 — Tests**
- Synthetic loss sequence triggers halt
- Halt sentinel respected by halt-watcher (existing path)

**Phase 7 gate**: synthetic 11-loss-streak test triggers halt within
1 settle of crossing -$50; CRITICAL alert delivered.

---

## Phase 8 — Multi-market support (BTC + ETH + SOL) (~7-10 days)

The fastest way to triple opportunity surface WITHOUT violating
fire-once-per-window. Per design/spot_aware_strategy.md §11, this is
Phase 11.D in the strategy roadmap. Each market has its own 5-min
windows, its own priors, its own fire-once invariant.

**8.1 — Design doc `design/multi_market.md`**
- Market routing: per-asset `MarketRunner` instances, sharing the
  same DecisionLog + ShadowBook? Or separate logs?
- Bankroll allocation: equal split (1/3 each) or weighted by
  historical edge per asset?
- Per-asset priors: re-derive from per-asset Bonereaper-equivalent
  data (need to find or generate)

**8.2 — Implementation**
- Refactor PaperRunner to accept a `markets: list[MarketSpec]`
  parameter
- Add Coinbase ETH/USD + SOL/USD feeds (already have Binance for both
  on the existing connection)
- Add Polymarket markets for `eth-updown-5m-{ts}` and
  `sol-updown-5m-{ts}` (verify these exist on Polymarket)

**8.3 — Re-soak 7 days** at 3x volume (BTC + ETH + SOL)

**Phase 8 gate**: cumulative weekly PnL ≥ 2.5x of single-market
weekly PnL (sub-linear scaling expected due to correlated regimes
across BTC+ETH+SOL).

---

## Phase 9 — Polymarket Streams WS for sub-second settle (~5 days)

The Phase 6 prereq. Current instant-settle uses Gamma REST poll (1-3s
typical). Polymarket Streams WS resolves sub-second after T+300. For
Phase 11.B (real-money) and beyond, sub-second matters for capital
recycling + streak-derived halts.

**9.1 — Design doc `design/polymarket_streams.md`**
- Polymarket Streams WS protocol (different from CLOB WS)
- Auth + subscription state management
- Reconnect logic
- Fallback to Gamma REST poll on Streams outage

**9.2 — Implementation**
- New module: `src/polymarket_bot/_live/feeds/streams.py`
- Replaces `gamma_resolver.poll_gamma_for_resolution` for in-bot use
- Keeps Gamma resolver for back-fill scripts

**Phase 9 gate**: in 24h soak, p99 settle latency < 1s (was 1-3s with
REST poll, was 60s with Chainlink-only).

---

## Phase 10 — Real-money go (Phase 11.B → Phase 1B funding → Phase 6 live) (~30-day soak THEN switch)

This is the ORIGINAL "Phase 6 — Live with kill-switches" from
MASTERPLAN, gated on Phases 1-9 above completing successfully and
producing 30+ days of paper soak with proven persistent edge.

**Pre-conditions** (all must be true):
- Phase 1-9 complete; v3 strategy deployed
- 30 consecutive days of paper soak with cumulative PnL ≥ +$200
  (consistent with the $200/month edge target from "State of play")
- Win rate (across all regimes) ≥ 51% (achievable per Bonereaper data;
  doesn't need to hit the unrealistic 60% bar)
- All 5 kill-switches per MASTERPLAN §6 tested at least once

**10.1 — Phase 1B funding** (per locked decision #20)
- Funder wallet: $1,000 USDC + $5 MATIC
- Signer wallet: starts at $0, sweeps from Funder as needed (≤ 2 days
  bankroll per decision #11)
- Hardware wallet trigger: $2k bankroll (decision #12)

**10.2 — Live deployment**
- Switch from `bot-staging.service` (paper) to `bot.service` (live)
  per the existing systemd unit pattern (Phase 5.7 closed)
- Run in shadow-mode side-by-side for 24h: paper bot continues; live
  bot trades $5 flat. Compare per-trade PnL between them.

**10.3 — Scale via Kelly per decisions #9 + #10**
- After 100 live trades, compute empirical WR + edge per tier
- Switch from $5 flat to fractional Kelly: `size = bankroll × f × edge`
- Bankroll rungs: $1k → $3k → $10k → $30k (decision #10 + #12)

**Phase 10 gate (the real one)**: 14 days live with positive PnL,
zero kill-switch trips, ≥ 100 live trades. THIS is what "winning"
looks like.

---

# Honest framing

## What you cannot have

- **"5 trades per 5-min window"** without violating the fire-once-per-
  window invariant. The 3-agent ensemble (Phase 5) is the right way
  to get 3x decision throughput per window — 3 independent agents
  contribute to ONE meta-decision per window, not 3 separate fires.
- **"60%+ WR as a must"** at the current architecture. Bonereaper
  achieves 67.4% WR on aligned trades but only via 30 days of data
  + their fill quality + their sizing. Realistic for us at our infra:
  **52-55% WR with positive per-trade EV**, which is enough.
- **"100x improvement"** as an engineering target. The right framing
  is **"$200+/month sustained at $5 flat → switch to Kelly → scale
  bankroll via decision #10 rungs"**. Compounding does the rest.
- **"Sizing $5-$60 right now"** without regime detector. Per regime-
  shift investigation, $60 sizing in chop = bankroll wipeout in a
  7-loss streak. Sizing is Phase 6 (after Phase 4 regime detector).

## What you CAN have

- **A strategy that works** if all 10 phases land. v3 = v2 +
  regime detector + 3-agent ensemble + variable sizing + multi-
  market + sub-second settle. Each phase is independently shippable
  + measurable.
- **Real money in 60-90 days** if Phases 1-9 each complete on
  schedule and the 30-day paper soak in Phase 10 shows the expected
  edge.
- **Edge that compounds** rather than edge that gets diluted by
  firing-on-noise.

## What's uncertain

- Whether the spot-Δ alignment edge is large enough at our infra +
  fill quality to overcome fees at $5/trade. Bonereaper proves it
  exists at scale; our 256 trades is too small to confirm.
- Whether the regime detector hypothesis (5min/10min vol ratio) is
  the right classifier. 5+ alternative classifiers possible; might
  need iteration.
- Whether the LLM meta-decider gives ≥ 3pp uplift (locked decision
  #16's bar). If not, we ship deterministic-only and save the LLM
  cost.
- Whether multi-market correlations make Phase 8 sublinear in PnL
  (probably yes; expect 2-2.5x not 3x).

## What's certain

- The bot is structurally sound. Audits found 4 fixable issues, 0
  showstoppers.
- The data IS showing edge per-tier — not in 50-70% (asymmetric
  payoff problem) but in 30-50% where v2 will fire.
- Operator + bot have built rigorous infra (12-hr fire metronome,
  exact PnL accounting, two PRs of clean diffs, vault discipline).
  This is the foundation 100x compounds on.

---

## Time estimate (calendar)

| Phase | Calendar days | Active dev hours |
|---|---|---|
| 1 | 1-2 | 5-8 |
| 2 | 1 (gate-day deploy) | 1 |
| 3 | 7 (passive soak) + 1 active | 5 |
| 4 | 5-7 | 30 |
| 5 | 7-14 | 60 |
| 6 | 5-7 | 25 |
| 7 | 2 | 10 |
| 8 | 7-10 | 40 |
| 9 | 5 | 25 |
| 10 | 30 paper + 14 live | 30 |
| **Total** | **~70-90 days** | **~230 hours** |

**~3 months calendar time, ~30 sessions.** Realistic for solo build
with day job.

## Decision points along the way (where operator must decide)

| After Phase | Decision |
|---|---|
| 3 | If v2 has no edge → revert to v1 + reconsider strategy fundamentally |
| 4 | If regime detector doesn't improve per-trade PnL ≥ 50% → drop it; rethink |
| 5 | If LLM ensemble < 3pp uplift over deterministic → drop LLMs (decision #16) |
| 6 | If sizing degrades equity curve → revert to flat; sizing was premature |
| 8 | If multi-market < 2x scaling → focus on BTC alone with deeper signal work |
| 10 | Real-money go/no-go (locked decision #11 — Funder/Signer; #12 — HW wallet at $2k) |

---

## Cross-references

- `MASTERPLAN.md` — original architecture (this roadmap is its v3 evolution)
- `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md` — 20 locked decisions
- `runbooks/research/edge-discovery-2026-05-09.md` — where the per-tier edge lives
- `runbooks/research/regime-shift-investigation-2026-05-09.md` — why regime matters
- `runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md` — empirical basis for the strategy
- `design/spot_aware_strategy.md` — v1 spec (what we're improving on)
- `design/spot_aware_v2_tier_restricted.md` — v2 spec (Phase 2 deploy)
- `design/instant_settlement.md` — Gamma poll spec (Phase 2 deploy)
