# Design — `SpotAwareStrategy` (sibling to `DeterministicStrategy`)

> Purpose: lock the architecture for the project's next strategy — a
> spot-aware sibling to `DeterministicStrategy` driven by the +30.9pp
> aligned-vs-contrarian gap discovered in the 30-day Bonereaper analysis,
> with explicit price-tier and EV discipline borrowed from the leaderboard
> scout's negative findings. Anti-vibe rule **#1**: this doc lands and locks
> before any code in `src/polymarket_bot/strategies/spot_aware.py` is
> written; rule **#2** says any production bug-fix gets a failing test
> first; rule **#10** keeps the spot tick source injectable for testability.
>
> Anchors:
> - `runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md` — 306,966
>   trades; +30.9pp aligned-vs-contrarian gap; per-tier breakdown.
> - `runbooks/research/scout-final-comparison-2026-05-08.md` — three-wallet
>   comparison; price-tier discipline as the real edge.
> - `runbooks/research/bonereaper-microstructure-30d-2026-05-08.md` — 95.1%
>   market participation, layered PnL drivers, late-window-sniping rejected.
> - `runbooks/gate-evidence/replay-calibration-2026-05-08.md` — proof the
>   current `DeterministicStrategy` fires zero times at any threshold; this
>   strategy's reason for existing.
> - `design/backtest.md` — `Strategy` protocol + `MarketEvent` taxonomy this
>   plugs into.
> - `design/paper.md` — `PaperRunner` shape that hosts both strategies.
> - locked decisions **#5** (3-agent ensemble — separate stream),
>   **#6** (composite 0.6pp threshold — preserved on the deterministic side,
>   independent of this strategy), **#9** ($5 flat per trade for first 100),
>   **#10** ($1k starting bankroll), **#16** (LLM A/B retained for Phase 4
>   re-run; this strategy is deterministic-class, not LLM), **#19**
>   (Bonereaper cloning study aborted — this strategy is *NOT* a clone, it's
>   a discrete spot-Δ trigger inspired by one of Bonereaper's signals; see
>   §12).
>
> Out of scope: live signing (`POLY_PRIVATE_KEY`, gasless relayer wiring —
> Phase 6); ensemble integration with the 3 LLM agents (Phase 8 if revived);
> multi-market expansion to 15-min, hourly, ETH, sports (§11 sketches the
> path but no code lands here).

---

## 0. Why this strategy exists right now

Three pieces of evidence converged on 2026-05-08:

1. **The current `DeterministicStrategy` fires zero times** on real 5-min
   BTC tick data at any threshold from 0.3pp to 0.6pp
   (`runbooks/gate-evidence/replay-calibration-2026-05-08.md`). Lowering
   decision #6's threshold without changing the signal still fires zero.
   The signal itself is too quiet for 5-min BTC windows.
2. **A different signal does have measurable edge.** The 30-day Bonereaper
   spot-vs-book join (306,966 trades) shows aligned trades win 67.4% vs
   contrarian 36.4% — a +30.9pp gap that survives at scale (837 trades →
   +52.8pp; 60,500 → +32.0pp; 306,966 → +30.9pp; converging, not
   regressing).
3. **High win rate without price-tier discipline loses money.** The two
   small-equity scout candidates (Slow-Minute, `0x88f1`) had 96-98% scout
   win rates and were both **net-losing** because they bought 95-99¢ shares
   that pay $1. Bonereaper's edge comes from *layering* tiers, not from
   any single trade pattern.

The spot-Δ signal + tier discipline + an EV check together describe a
strategy whose expected value can be computed *before* it fires, not after.
That's what this doc locks.

## 1. The picture

```
                spot tick                 book update
                    \                        /
                     v                      v
      +--------------------------------------------------+
      |              SpotAwareStrategy                   |
      |                                                  |
      |  1. compute Δ_bps = 10000*(St - S0)/S0           |
      |  2. classify alignment vs candidate side         |
      |  3. price-tier filter (reject >=90% implied)     |
      |  4. lookup p_win from prior table                |
      |  5. EV check: p_win * $1 > entry_price + fees    |
      |  6. fire BUY at $5 stake on the aligned side     |
      |                                                  |
      +-----------------+--------------------------------+
                        |
                        v
                Decision (state/decisions/<UTC>.jsonl)
                        |
                        v
                 PaperRunner sim-fill
                        |
                        v
                 Dashboard side-by-side render
                 vs DeterministicStrategy decisions
```

Sibling, not replacement. Both strategies receive the same `MarketEvent`
stream; both write `Decision`s; the dashboard renders them in adjacent
columns. The operator picks the live strategy after a fresh paper-soak
gate run; until then, both run in shadow paper mode in parallel.

## 2. The signal: Δ_bps + alignment

For each 5-min Polymarket BTC market with window opening at `t = window_ts`
and Binance BTCUSDT spot prices `S0` at window open and `St` at the time
the bot considers entering:

```
Δ_bps = 10000 * (St - S0) / S0
```

Sign convention:
- `Δ_bps > 0` ⇒ spot has moved UP since window open
- `Δ_bps < 0` ⇒ spot has moved DOWN since window open
- `Δ_bps ≈ 0` ⇒ spot is flat ("flat" bucket per Bonereaper analysis: |Δ| < 5)

Alignment of a candidate side:
- `UP` side is **aligned** with positive Δ_bps, **contrarian** with negative.
- `DOWN` side is **aligned** with negative Δ_bps, **contrarian** with positive.

The strategy *only* considers the aligned side. Contrarian and flat trades
are off-table for this trigger; the EV math is dramatically worse and the
sample data shows aligned trades win roughly 2× as often per Bonereaper's
30-day breakdown.

## 3. The trigger: thresholded Δ_bps + aligned

```
fire BUY on side X iff:
  X is aligned with sign(Δ_bps)         AND
  |Δ_bps| ≥ Δ_min                       AND
  Δ_min ≤ |Δ_bps| ≤ Δ_max               AND
  price-tier filter passes (§4)          AND
  EV check passes (§5)
```

**Δ_min candidate space:** `[5, 10] bps`. The 30-day data shows the cleanest
edge in 5-20 bps moves: UP+5..+10 bps wins 75.7% with $0.30/trade gross;
UP+10..+20 bps wins 83.4% with $0.24/trade. Below 5 bps the alignment
signal degrades into noise.

**Δ_max ceiling:** `50 bps`. Past 50 bps the data is sparse and the per-trade
PnL flips negative (UP+>50 bps n=11, WR=27%, $-6.70/trade — likely a
mean-reversion regime where the late-mover gets caught). The ceiling
prevents firing on overshoots.

**Calibration:** Δ_min defaults to **8 bps** (midpoint). The first paper-soak
gate (§9) measures hit rate + per-trade PnL across {5, 7, 8, 10} and locks
the value at gate-close. Until then, the strategy reads `Δ_min` from a
config injected at construction so a sweep is a config flip, not a
recompile.

## 4. The price-tier filter (the lesson from the scout)

Reject any candidate where the entry price is in tier **85-100% implied
probability**. Reason: Bonereaper's per-trade PnL in that tier is **$+0.40
to $+0.65** before fees, which an estimated 40-60bps fee + slippage cuts to
near zero or negative. The scout candidates whose entire strategy lived in
that tier were both net-losing.

| Implied price | Tier label | Use? | Why |
|---|---|---|---|
| < 0.15 | `<15%` | DEFER | rare, +$8.83/trade per 30d data but only 722 trades — needs more data |
| 0.15 – 0.30 | `15-30%` | YES (small sizing) | aligned WR 25%, $+0.11/trade — thin |
| 0.30 – 0.50 | `30-50%` | **YES — sweet spot** | aligned WR 45.4%, **$+1.17/trade** |
| 0.50 – 0.70 | `50-70%` | **YES — sweet spot** | aligned WR 63.1%, **$+0.95/trade** |
| 0.70 – 0.85 | `70-85%` | YES (cautious) | aligned WR 78%, $+0.40/trade — discipline-sensitive |
| 0.85 – 1.00 | `85-100%` | **NO** | aligned WR 91.7%, $+0.65/trade — fees eat it |

The two "sweet-spot" tiers (`30-50%` and `50-70%`) account for **$55.2k of
the $83.1k aligned-trade gross PnL** in Bonereaper's 30-day data — 66% of
their alignment edge in 53% of their alignment trades. That's the band our
trigger should live in.

## 5. The EV check

Before firing, compute:

```
p_win  = lookup table value (§6) for (Δ_bps bucket, price tier)
fees   = 0.005 (Polymarket gasless relayer estimate; revisit at Phase 6)
edge   = p_win * 1.0  -  (entry_price + fees)
fire iff edge > 0.005   # i.e., > 0.5¢ expected value per $1 of notional
```

The **0.5¢ threshold is intentional friction**: a positive-but-tiny edge
(say +0.2¢/share) is indistinguishable from `p_win` lookup error and gets
eaten by slippage on a real fill. Half a cent is a defensible minimum.

This single check is the difference between "Bonereaper" (winner) and
"Slow-Minute" (-$3,964 over 7 days). Slow-Minute fired on alignment but
never gated on price; they bought $0.99 shares and lost the spread. Our
strategy gates explicitly.

## 6. Estimated `p_win` lookup table

Initial values come from the 30-day Bonereaper data (`runbooks/research/
bonereaper-spot-vs-book-30d-2026-05-08.md` §"By alignment x price tier"
and §"By side x Δ_bps"). They get updated by our own paper-soak data on a
weekly cadence — never overwritten without ≥200 trades-per-bucket sample.

Initial table (aligned only; contrarian and flat get `p_win = 0` so they
never fire):

| price tier | Δ_bps bucket | initial `p_win` | source-trades |
|---|---|---:|---:|
| 30-50% | 5-10 bps | 0.65 | 1,200 (synthesised UP+DN) |
| 30-50% | 10-20 bps | 0.72 | 950 |
| 30-50% | 20-50 bps | 0.78 | 380 |
| 50-70% | 5-10 bps | 0.74 | 6,300 |
| 50-70% | 10-20 bps | 0.81 | 2,100 |
| 50-70% | 20-50 bps | 0.85 | 720 |
| 70-85% | 5-10 bps | 0.80 | 5,200 |
| 70-85% | 10-20 bps | 0.86 | 1,900 |
| 70-85% | 20-50 bps | 0.88 | 600 |
| 15-30% | 5-10 bps | 0.40 | 200 |
| 15-30% | 10-20 bps | 0.45 | 130 |

Implementation: a small JSON file at `data/spot_aware_priors.json`,
versioned in git with a `version` field. Strategy reads it at construction.
A weekly job (out of scope here) re-derives the table from the prior 7
days of paper-soak decisions and emits a candidate JSON; operator reviews
and merges.

If a `(tier, Δ_bps)` cell is missing from the table, the strategy refuses
to fire on that combination. Conservative-by-default.

## 7. Architecture: sibling strategy in `PaperRunner`

```
src/polymarket_bot/strategies/
  __init__.py
  protocol.py            (existing — no changes)
  deterministic.py       (existing — no changes)
  ensemble.py            (existing — no changes; for decision-#5 LLM ensemble)
  spot_aware.py          (NEW — this strategy)
  spot_aware_priors.py   (NEW — loader + bucket lookup; <50 LOC)

data/
  spot_aware_priors.json (NEW — versioned prior table, edited by weekly job)
```

### Class shape

```python
class SpotAwareStrategy:
    name: str = "spot_aware"

    def __init__(
        self,
        *,
        priors: SpotAwarePriors,         # injected — testable
        clock: Clock,                     # injected — rule #10
        delta_min_bps: float = 8.0,
        delta_max_bps: float = 50.0,
        size_usd: float = 5.0,            # locked decision #9
        fee_estimate_pct: float = 0.005,
        ev_min_dollars_per_share: float = 0.005,
    ) -> None: ...

    async def on_event(self, event: MarketEvent) -> Decision | None: ...
    def reset(self) -> None: ...
```

### Event handling

- `SpotTick` → cache last spot in a small ring; this is `St`.
- `WindowBoundary` → record `S0` for the window. Reset internal state.
- `BookUpdate` → THIS is the trigger event. Compute `Δ_bps`, classify
  alignment for both sides, gate through §3-§5, emit at most one `Decision`
  per window per market.
- `OracleUpdate` → ignored. The deterministic baseline uses the oracle
  gap; this strategy is spot-only.

### Concurrency + state isolation

`SpotAwareStrategy` shares the `Strategy` protocol so it drops into
`PaperRunner`'s existing strategy slot. Phase 4's runner only knows how to
run *one* strategy at a time.

**Deployment plan revision (2026-05-09):** the side-by-side runner refactor
is deferred to a v2 follow-up commit. For the initial 7-day paper-soak,
`spot_aware` is deployed **solo** on `bot-staging.service` — replacing
`deterministic` as the active strategy on the VPS. Justification:
1. `deterministic` was replay-calibrated to fire **zero** at any threshold
   on 28 windows of real BTC ticks (`runbooks/gate-evidence/
   replay-calibration-2026-05-08.md`). Running it 7 more days in shadow
   would not add information.
2. The `_RunState` class in `src/polymarket_bot/_paper/runner.py` is
   per-window-single-strategy; refactoring it to per-window-per-strategy
   is ~2h of careful test-first work. Doing that refactor *while* the
   phase-5-pass deployment is running risks a regression on the live
   service.
3. After the 7-day paper-soak, we'll have `spot_aware` fire-rate data to
   *actually compare against* and the refactor will be informed by real
   numbers, not a placeholder.

**Follow-up scope (committed before Phase 6):** extend `_RunState` to host
a `dict[strategy_name, _StrategyState]`; `DecisionLog.record_fired` adds a
`strategy: str` field; dashboard groups by that field. Failing tests in
`tests/_paper/test_multi_strategy.py` first per rule #2.

## 8. Sizing

**$5 flat per trade for the first 100 trades** (locked decision #9). No
Kelly logic in this strategy. The size is constant per fire regardless of
edge magnitude or bankroll.

After 100 paper-soak trades we have a sample to gate against; THAT is when
fractional-Kelly enters the picture (decision #9's "then fractional Kelly"
clause). Sizing logic lives in the executor layer (Phase 6), not this
strategy.

## 9. Paper-soak gate criteria — REALISTIC

This is where the operator's $50-250/day target gets reconciled with
$1k-bankroll one-market math. The gate criteria below are what
`SpotAwareStrategy` must clear in a 7-day paper-soak on the VPS before any
move toward live trading.

### Criterion set A — "the strategy works"

| # | Metric | Target | Why |
|---|---|---|---|
| A1 | Fires per day | 30 ≤ fires ≤ 200 | Sanity-check selectivity. <30 fires/day = trigger too tight; >200 = no discipline (Slow-Minute territory). |
| A2 | Net win rate | ≥ 55% | Beats coin-flip with margin. Bonereaper's net WR is 51.7% across all trades, but our trigger is selective — we should see higher. |
| A3 | Aligned-vs-contrarian gap | ≥ +20pp | We only fire on aligned, but we record what *would* have happened on contrarian. Reproduce ≥2/3 of Bonereaper's 30d gap. |
| A4 | Per-trade NET PnL | ≥ +$0.20 | After 0.5% fee and slippage. ~25% of Bonereaper's gross per-trade. |
| A5 | Net daily PnL | ≥ +$5.00 | A1 × A4 lower bounds = 30 × $0.20 = $6.00. **NOT $50/day.** |
| A6 | Max drawdown | ≤ 15% of bankroll | Hard ceiling. If we draw down 15% in any rolling 24h, halt and review. |

### Criterion set B — "the infrastructure works"

| # | Metric | Target | Source |
|---|---|---|---|
| B1 | Zero unhandled exceptions in 7d | match Phase 5.7 #7 |
| B2 | Litestream replicating without errors | match Phase 5.7 #8 |
| B3 | Decision write rate | ≥ 1 per 12h log file | proves the strategy is alive |
| B4 | EV-rejection-vs-fire ratio | log it, don't gate it | tells us how often the price-tier or EV filter saves us from bad trades |

### Why $5/day, not $50/day

Math from the data we have:

```
trades/day budget    = 288 windows × ~50% qualify = ~144 candidates
selectivity (filters) = ~30% fire rate              = ~40-50 fires/day
per-trade NET PnL    = $0.20 (gate)                 = $8-10/day NET on the gate
realistic upside     = $0.50/trade if we hit Bonereaper sweet-spot
                                                     = $20-25/day NET
```

That's the **single-market, $1k-bankroll, paper-soak** ceiling on
realistic expectations. **$5/day net is the gate; $20-25/day net is the
upper end of what a perfect run looks like.** Anything higher means we
got lucky on a sample, not that the edge is structural.

Failing the gate doesn't kill the strategy — it produces a postmortem at
`runbooks/postmortems/<date>-spot-aware-paper-fail.md` and we either widen
the trigger or invest in a stronger signal (multi-market, alt-tick, LLM
re-run).

## 10. Backtest plan

Before the strategy ever runs in paper-soak, it must clear a backtest
against captured ticks + historical klines.

### Inputs

- **30 days of Binance BTCUSDT 1m klines** (already pulled by
  `scripts/research/binance_historical_klines.py` per the 2026-05-08
  vault notes; 12.7s for 30d).
- **Captured Polymarket book ticks** from `state/captures/` (Phase 2/3
  capture; ~2.3h on 2026-05-06 plus whatever has accumulated since
  bot-staging started).
- **Bonereaper's 306,997 trades** as a *benchmark* to score against — for
  each (Δ_bps bucket, price tier) cell, our backtest's `p_win` should land
  within ±5pp of Bonereaper's bucket WR. Drift beyond that = the signal
  decayed or our data joined wrong.

### Procedure

1. Run `scripts/run_backtest.py --strategy=spot_aware --priors=v1` over
   30d of klines.
2. Emit `state/backtests/spot_aware_v1_<date>.parquet` with one row per
   simulated decision.
3. Score: per-bucket WR, per-bucket gross PnL, total simulated NET PnL,
   max drawdown, fire-rate distribution.
4. Compare against the criterion set (A) above using a fee model identical
   to live (0.5% per fill).
5. **Backtest gate:** if the backtest can't show A1-A4 met on 30d of
   historical data, do NOT promote to paper-soak. Tighten Δ_min, expand the
   tier filter, or re-derive priors from a longer window.

### What the backtest can NOT prove

- Live book microstructure differs from captured replay (latency, partial
  fills, ladder shifts). Backtest gives a *prior* on whether the signal
  exists; it doesn't certify a live PnL number.
- 30d may not span all volatility regimes. The sample we have is
  near-the-money calm. A volatility spike could shift `p_win` per bucket
  by ±20pp easily.

These caveats mean the backtest is a *necessary* but not *sufficient*
gate. Paper-soak is the next step regardless of how the backtest reads.

## 11. Scaling roadmap to $50–$250/day NET

Aspirational, multi-phase. **Phases 11.B onward are explicitly OUT OF
SCOPE for this design doc and require their own design + gate.** Listed
here so the long-range target the operator wants is visible and tracked.

| Phase | What changes | Bankroll | Markets | Realistic NET ceiling |
|---|---|---|---|---|
| 11.A (this doc) | $5 stake, 1 market (BTC 5m), paper soak | $1k | 1 | **$5–25/day** |
| 11.B | Real-money go-live (Phase 6 prereq met); same stake/market | $1k | 1 | $5–25/day (less, due to real fills) |
| 11.C | Stake grows with bankroll (decision #9's "then Kelly"); $10–25/trade | $2k–5k | 1 | $20–80/day |
| 11.D | Multi-market: BTC 15m + 1h on top of 5m | $5k | 3 | $50–150/day |
| 11.E | Cross-asset: ETH 5m/15m/1h | $7.5k | 6 | $100–250/day |
| 11.F | Sports (NBA/NFL aligned-on-spread analogs); calendar effects | $10k+ | 20+ | $200–500/day |

**Each phase has its own gate.** $50/day is plausible at Phase 11.D — *only
after* 11.A clears the +$5/day paper gate, 11.B clears the same gate live
with real fills, and 11.C demonstrates that bankroll-scaled sizing doesn't
break the per-trade EV math.

This is the honest answer to "can we make $50–$250/day?": yes, eventually,
through compounding gates. Not on day one, not on $1k, not on one market.

The operator's standing intuition is correct: **high-volume × tiny edge
× selective sizing × multi-market** is the recipe. We're encoding the
"selective sizing" piece in this doc.

## 12. What this doc does NOT do

- **It does not un-archive locked decision #19** (Bonereaper cloning study).
  We are not cloning Bonereaper. We are extracting one of their signals
  (spot-Δ alignment) plus one of their disciplines (price-tier mix) into a
  fresh, independently-justified strategy. The cloning study's failure
  mode (52.65% backtest WR vs 60% gate on a directional-only model) does
  not bind this design.
- **It does not lower locked decision #6's threshold.** The
  `DeterministicStrategy` keeps its 0.6pp composite threshold and continues
  running in shadow. We are *adding* a strategy, not modifying one.
- **It does not turn on the LLM ensemble.** Decisions #5 and #16 stand;
  Phase 4 ensemble re-run still needs its own gate.
- **It does not commit to live trading.** Phase 6 (real money) is
  explicitly gated behind Phase 1B (real-money funding) AND this strategy's
  paper-soak gate (§9).
- **It does not write code in this commit.** Code lands in a follow-up
  commit that imports this doc as the spec it implements.

## 13. Open questions / icebox (resolve before code lands)

1. **Bucket boundary for `<15%` tier.** The 30d data has only 722 trades in
   the aligned-and-<15% cell, with $+8.83 per-trade PnL. Looks like a
   high-EV opportunity but the sample is too small to trust. Decision:
   defer — leave the cell as `p_win` undefined so the strategy refuses to
   fire there, until we accumulate ≥1,000 paper-soak trades to validate.
2. **Δ_min weighting by time-of-day.** US-market-hour BTC volatility is
   higher; Δ_min = 8 bps may fire more often during 13:30–20:00 UTC than
   overnight. We should log time-of-day for every fire and look for a
   regime split after the 7-day soak. No immediate action.
3. **Spot source.** Binance ticks today. Coinbase is a more "official"
   reference but has lower tick density. Decision: stay on Binance for
   now; the 30d data was joined against Binance and we should not change
   the source while the priors are derived from it.
4. **Fee model.** 0.5% is a placeholder. Phase 6 prereq: measure actual
   gasless-relayer fees on a few real fills; update `fee_estimate_pct`
   constant; revisit the EV gate if fees drift outside [0.3%, 0.7%].
5. **Halt sentinel respect.** Strategy must check `state/halt.sentinel`
   before firing — same path as the Phase 5.5 `_halt_watcher`. Fire is
   suppressed when sentinel exists.
6. **Decision schema field.** `Decision` already has a `strategy: str`
   field. Confirm before code (paper.md §3 implies it; verify by reading
   `polymarket_bot.backtest.types.Decision`).

## 14. Implementation plan (next session, after this doc commits)

In order, with a failing test before each piece per anti-vibe rule #2:

1. `tests/strategies/test_spot_aware.py` — failing tests covering the §3
   trigger, §4 tier filter, §5 EV check, §6 prior loading, §11 fire-rate
   sanity bounds. ~120 LOC.
2. `data/spot_aware_priors.json` — initial prior table from §6.
3. `src/polymarket_bot/strategies/spot_aware.py` + `spot_aware_priors.py`
   — implementation. ~250 LOC.
4. `src/polymarket_bot/_paper/runner.py` — extend to host two strategies
   side-by-side. ~50 LOC delta + tests.
5. `scripts/run_backtest.py` — flag `--strategy=spot_aware`. Run 30d
   backtest; output to `runbooks/gate-evidence/spot-aware-backtest-v1.txt`.
6. `runbooks/gates/spot-aware-paper.sh` — 7-day paper-soak gate audit
   script; structure parallel to `runbooks/gates/phase-5.sh`.
7. Deploy: scp the updated bot to VPS; restart `bot-staging.service`;
   leave running for 7 days. Dashboard reads side-by-side.
8. At day 7, run the gate audit; tag `spot-aware-paper-pass` on green.

Estimated LLM session cost: $0 (deterministic strategy; no API calls).
Estimated wall-clock: 2-3 hours of code + 7 days of paper soak.

---

## Appendix — quick-reference math for the operator

**Why $5/day net is the gate, not $50:**

```
Bonereaper 30d data:
  306,966 trades × $12.13M notional × 1.94% gross ROI = $234,864 gross PnL
  Net WR = 51.7%; per-trade gross = $0.76; per-trade net ≈ $0.30 (after fees)

Our scale:
  $5 stake / $39.41 Bonereaper avg = 12.7% of their per-trade size
  288 windows/day × 30% fire rate = 86 fires/day max
  86 × $0.30 × 12.7% scale factor = $3.28/day if we replicate their per-$ ROI

But our trigger is more selective (we filter heavy favorites) so per-$
ROI should be HIGHER than Bonereaper's blended average — call it 2x:
  86 × $0.30 × 12.7% × 2 = $6.55/day  ⇒  rounded gate = $5/day NET
```

**Why $50–$250/day appears at scale, not at start:**

To 10× from $5/day NET to $50/day NET, we need any combination of:
- 2× per-trade EV (better priors after months of paper data)
- 2× trade volume (scale to BTC 15m + 1h)
- 2.5× stake size (Kelly, requires bigger bankroll)

Each of those is a separate design + gate. None are this doc's scope.
But the path is visible, which is the operator's actual ask.
