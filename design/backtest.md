# Design — Backtest Harness + Strategy Interface (Phase 3)

> Purpose: lock the architecture for the replay engine, strategy interface,
> fill simulator, walk-forward harness, and cost tracker that Phase 3.1-3.3
> implement on top. This doc precedes any code in
> `src/polymarket_bot/backtest/`, `src/polymarket_bot/strategies/`,
> `src/polymarket_bot/agents/`, or `runbooks/gates/phase-3.sh`, per
> anti-vibe rule #1.
>
> Anchors:
> - `RUNBOOK.md` §"Phase 3 — Backtest Harness + LLM A/B Test" (lines 866-979)
> - `MASTERPLAN.md` §"The trade thesis" (line 27 onward), §"Architecture"
> - locked decisions [#5, #6, #14, #16] in
>   `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`
> - **decision #21** (locked 2026-05-07): Phase 2 gate relaxed; thesis
>   re-baselined to ~33s Chainlink heartbeat (median 33.0s, σ < 5s
>   across 36 events spanning 19 minutes). The strategy unchanged in
>   shape; the lag window is roughly half the masterplan's assumption.
> - `design/data_plane.md` §4 — Record schema (load-bearing for replay)
>
> Out of scope for this doc: the actual win-rate-≥-53% number (that's
> a Phase 3.1 backtest result, not an architectural choice); LLM agent
> prompts (`design/agents.md` precedes Phase 3.2); paper-trading on
> live venues (Phase 4); kill switches (Phase 5).

---

## 1. The two questions Phase 3 answers

1. **Does the deterministic baseline have alpha?** Win-rate ≥ 53% after
   fees on ≥ 2,500 trades over a walk-forward 21-day window. If no, we
   don't introduce LLMs to paper over a weak baseline.
2. **Does the LLM ensemble add ≥ 3pp uplift over the baseline?** Same
   simulator, same fees, same 21-day window. If yes, ensemble is
   kept; if no, deterministic-only and ensemble revisited in Phase 8.

This doc lays the rails for both answers.

## 2. The core abstraction — MarketEvent

The replay engine emits `MarketEvent`s in event-time order. Strategies
consume these via `on_event`. Live mode in Phase 6 produces the same
type from real WS streams — same strategy code, two backends.

```python
# src/polymarket_bot/backtest/types.py
@dataclass(frozen=True, slots=True)
class SpotTick:
    ts_utc_ns: int
    source: Literal["binance", "coinbase"]
    price: float

@dataclass(frozen=True, slots=True)
class OracleUpdate:
    ts_utc_ns: int
    price: float           # int256 'current' decoded to float (8-decimal Chainlink scaling)
    round_id: int
    updated_at_s: int      # unix seconds from the event's updatedAt field

@dataclass(frozen=True, slots=True)
class BookUpdate:
    ts_utc_ns: int
    asset_id: str
    side: Literal["UP", "DOWN"]
    best_bid: float | None
    best_ask: float | None
    bid_size_top: float | None
    ask_size_top: float | None
    raw: dict[str, object]   # full Polymarket payload for top-5 + further depth

@dataclass(frozen=True, slots=True)
class WindowBoundary:
    """Synthesised by the replay engine at every 300s mark to mark
    open/close. NOT a real upstream event — purely a strategy convenience.
    """
    ts_utc_ns: int
    window_ts: int
    kind: Literal["open", "close"]

MarketEvent = SpotTick | OracleUpdate | BookUpdate | WindowBoundary
```

**Why a sum type rather than a single Record-passing interface.** The
strategy logic should not parse JSON. The replay engine (and the live
bridge in Phase 6) takes care of decoding raw payloads into the typed
events above. Tests inject `MarketEvent`s directly.

## 3. Strategy interface

```python
# src/polymarket_bot/strategies/protocol.py
@dataclass(frozen=True, slots=True)
class Decision:
    """A decision to place an order. Consumed by the fill simulator."""
    ts_utc_ns: int
    asset_id: str          # which Polymarket CTF token (UP or DOWN side)
    side: Literal["BUY"]   # we always buy outcome shares (never sell short)
    size_usd: float        # $5 flat per locked decision #9, 1% Kelly later
    price_limit: float     # cents, in [0.01, 0.99]
    ttl_s: int             # seconds the order is good-for, in [10, 30]
    rationale: str         # short string; for diagnostics, non-load-bearing

class Strategy(Protocol):
    name: str
    async def on_event(self, event: MarketEvent) -> Decision | None: ...
    def reset(self) -> None: ...   # clear state at start of each test fold
```

**Why async.** The interface needs to support LLM strategies in 3.2
without changing the protocol. Deterministic strategies just `return`
without `await`.

**Why one Decision at a time.** Per-window, we either fire or don't.
Multi-leg orders are out of scope (see RUNBOOK Phase 3 — bot is binary
single-leg by design).

## 4. Replay engine

```python
# src/polymarket_bot/backtest/replay.py
class ReplayEngine:
    """Reads ticks/<date>/*.parquet and emits MarketEvents in ts_utc_ns order."""

    def __init__(self, ticks_root: str, dates: list[str]) -> None: ...

    async def stream(self) -> AsyncIterator[MarketEvent]: ...
```

Implementation rules:

- Reads all `<source>_*.parquet` files for each requested date (the
  multi-launch suffix from Decision-21 / the storage fix means a day
  may have several files per source). Concat by source, sort by
  `ts_utc_ns`, dedupe on (`source`, `ts_utc_ns`, `payload_json`) so a
  re-launch overlap doesn't double-count.
- Decodes payloads into typed events:
  - binance trade → `SpotTick(source="binance", price=float(p["p"]))`
  - coinbase match → `SpotTick(source="coinbase", price=float(p["price"]))`
  - oracle AnswerUpdated → `OracleUpdate(price=int(topics[1])/1e8, round_id=int(topics[2]), updated_at_s=int(data[:64]))`
  - polymarket book/price_change/last_trade_price → `BookUpdate(...)` (top-of-book extracted; raw kept for depth/imbalance metrics in 3.2)
- Synthesises `WindowBoundary` events at every 300s boundary inside the
  date range. Open at window_ts; close at window_ts + 300. The replay
  engine emits these BEFORE / AFTER the natural events that share their
  timestamp so strategies see boundaries cleanly.
- Streaming, not loading the entire archive into memory. polars
  `scan_parquet` for laziness; pull row groups as needed. Memory cap
  ~512 MB even for full 30-day windows.

## 5. Fill simulator

```python
# src/polymarket_bot/backtest/fills.py
@dataclass(frozen=True, slots=True)
class Fill:
    ts_utc_ns: int
    asset_id: str
    size_filled: float       # in shares (USDC notional / fill_price)
    price_filled: float      # average per share
    fee_usd: float           # see locked decision #9

class FillSimulator:
    """Match an order against the captured orderbook + self-impact model."""

    def __init__(
        self,
        *,
        fee_bps: float = 2.0,           # placeholder; calibrated from Phase 1B fills
        impact_per_5usd_per_5kbid: float = 0.001,   # $5 trade vs $5K depth → 0.1¢
    ) -> None: ...

    def attempt_fill(
        self, decision: Decision, book_at_decision_time: BookUpdate
    ) -> Fill | None: ...
```

**Self-impact model (deliberately simple for Phase 3).**
- We size trades at $5 per locked decision #9 — small relative to typical
  Polymarket book depth ($1K-$10K at the top tick).
- A $5 buy against a $5K top of book moves the next-tick price by ~0.1¢
  in our captured-book frame. Linear scaling for first iteration.
- If the limit price is below the best_ask + impact, the order does not
  fill.
- The order's TTL is honoured: if the book moves favourably within ttl_s
  the order fills at the limit; otherwise it expires and `attempt_fill`
  returns None for that window.

This is a paper estimate. Phase 1B (post-Phase-4) gives us empirical
fee/impact numbers; the simulator parameters are then re-calibrated and
Phase 3 backtest re-run as a sanity check.

## 6. Walk-forward harness

```python
# src/polymarket_bot/backtest/walk_forward.py
@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    train_start: str  # YYYY-MM-DD (UTC)
    train_end: str
    test_start: str
    test_end: str

def windows(all_dates: list[str], *, train_days: int = 7, test_days: int = 1) -> list[WalkForwardWindow]: ...

class WalkForwardRunner:
    """Slides a (train, test) window forward by 1 day at a time."""

    async def run(
        self, strategy: Strategy, all_dates: list[str]
    ) -> list[WindowResult]: ...
```

For Phase 3, the deterministic strategy has no parameters to fit, so the
"train" window is just a warm-up period (state filling). LLM strategies
in 3.2 use the train window for prompt-cache warming + few-shot calibration.

A 30-day archive yields 23 walk-forward folds (30 - 7 train). With the
33s heartbeat: each test day has 86,400 / 33 ≈ 2,618 oracle events,
288 5m windows, and Phase 3.1's 53%-win-rate target requires ≥ 2,500
trades over the 23 folds total (i.e. ~109 trades/day, well below the
fire-rate ceiling of 288 / day).

## 7. Cost tracker (LLM passes only)

```python
# src/polymarket_bot/backtest/cost.py
class CostTracker:
    """Counts Anthropic API calls; multiplies by per-token unit prices."""

    def __init__(self, *, hard_limit_usd: float = 35.0, alarm_at_usd: float = 30.0) -> None: ...

    def record(
        self,
        model: Literal["claude-haiku-4-5", "claude-sonnet-4-6"],
        input_tokens: int, output_tokens: int, cache_read_tokens: int,
    ) -> None: ...

    def total(self) -> float: ...
    def assert_within_limit(self) -> None: ...
```

Hard-limit of $35 per pass is RUNBOOK 3.0's spec. With four passes
budgeted at $50 total per locked decision #14, this leaves $15 of
headroom across the four passes for re-runs.

The cost tracker raises `BudgetExceeded` mid-pass if the limit hits;
the harness catches and writes a partial-result evidence file rather
than letting Anthropic charges run away.

## 8. P&L + metrics

```python
@dataclass(frozen=True, slots=True)
class WindowResult:
    window_ts: int
    fired: bool
    side: Literal["UP", "DOWN", None]
    fill: Fill | None
    resolution: Literal["UP", "DOWN", None]
    pnl_usd: float           # net of fees
    composite_signal: float  # for diagnostics

class Metrics:
    @staticmethod
    def aggregate(results: list[WindowResult]) -> dict[str, float]: ...
```

`aggregate` returns: total P&L, win-rate-after-fees, n_trades, avg-fill-time,
avg-rationale-length (LLM-only), p50/p99 decision latency.

## 9. Test discipline

Per anti-vibe rule #6:

- **Replay engine**: synthesise small Parquet fixtures (10 events
  per source per file) under `tests/backtest/fixtures/`. Round-trip
  Records → Parquet → ReplayEngine → MarketEvent and verify shape +
  ordering.
- **Strategy**: tests construct `MarketEvent` sequences directly,
  assert on `on_event`'s output. No file I/O.
- **Fill simulator**: deterministic fixtures: book + decision pairs,
  assert fills/no-fills.
- **Walk-forward**: assert window boundaries given a fake date list.

`pytest tests/ -q` runs without networking, without API keys, in
under 5 seconds.

## 10. Phase 3.1 deterministic strategy — formula and threshold rationale

```python
def _composite_pct(window_delta_frac: float, oracle_gap_frac: float, w_wd: float, w_og: float) -> float:
    """Returns a percentage-point composite signal. Positive ⇒ UP.

    The masterplan's threshold of 0.6 is in *percentage points*, not in
    fractional units; the formula in MASTERPLAN line 146 and RUNBOOK
    3.1 is fractional which is the source of confusion. We multiply by
    100 here so the threshold reads as a normal percentage.
    """
    return (w_wd * window_delta_frac + w_og * oracle_gap_frac) * 100.0
```

| Parameter | Default (Phase 3.1) | Rationale |
|---|---|---|
| `w_wd` (window-delta weight) | `0.5` | Equal split with oracle-gap; tuned in Phase 3.3 |
| `w_og` (oracle-gap weight) | `0.5` | Equal split |
| `threshold_pct` | `0.6` | Locked decision #6 wording, interpreted as percentage points |
| `ttl_low_s` | `10` | Locked decision #6 |
| `ttl_high_s` | `30` | Locked decision #6 |
| `size_usd` | `5.0` | Locked decision #9 |
| `price_limit` | per-call: best_ask | passive limit at top-of-book |

The `threshold_pct = 0.6` is **the calibration knob**. In Phase 3.1's
first backtest pass it's set per the masterplan; in Phase 3.3 we sweep
it across [0.3, 1.0] in the cost-bounded optimisation step before the
LLM A/B fires.

**Heartbeat-aware adjustment.** Decision-21 re-baselined the heartbeat
to ~33s. The lag window the strategy exploits is half the masterplan's
assumption. Two deterministic-strategy implications:

1. The `oracle_gap_frac` term sees fresher oracle prices — gap magnitudes
   are smaller on average. Threshold may need to drop (sweep covers this).
2. The `ttl_high_s = 30` clamp is now larger than the heartbeat. If we
   fire at T+30 of a window with a fresh oracle update at T+30 + ε, the
   decision goes stale fast. May tighten to `ttl_high_s ∈ [10, 20]` once
   the 3.3 sweep speaks.

Neither is locked here. Phase 3.3 selects the values empirically.

## 11. File map (what Phase 3.1-3.3 creates)

| Path | Phase | Purpose |
|---|---|---|
| `design/backtest.md` (this file) | 3.0 | Architecture, locked first |
| `src/polymarket_bot/backtest/types.py` | 3.1 | MarketEvent + Decision + Fill |
| `src/polymarket_bot/strategies/__init__.py` | 3.1 | Package marker |
| `src/polymarket_bot/strategies/protocol.py` | 3.1 | Strategy Protocol |
| `src/polymarket_bot/strategies/deterministic.py` | 3.1 | Baseline strategy |
| `src/polymarket_bot/backtest/replay.py` | 3.1.5 | ReplayEngine |
| `src/polymarket_bot/backtest/fills.py` | 3.1.5 | FillSimulator |
| `src/polymarket_bot/backtest/walk_forward.py` | 3.1.5 | WalkForwardRunner |
| `src/polymarket_bot/backtest/cost.py` | 3.2 | CostTracker (LLM only) |
| `design/agents.md` | 3.2 | Per-agent prompts + cache strategy |
| `src/polymarket_bot/agents/{orderbook,oracle_gap,momentum,meta,protocol,budget,cache}.py` | 3.2 | LLM ensemble |
| `prompts/*.md` | 3.2 | Versioned prompts |
| `tests/strategies/test_deterministic.py` | 3.1 | Unit tests for the baseline |
| `tests/backtest/test_*.py` | 3.1.5 | Replay/fills/walk-forward tests |
| `tests/agents/test_*.py` | 3.2 | Schema + adversarial tests |
| `runbooks/decisions/llm-ab-result.md` | 3.4 | OD-5 verdict |
| `runbooks/gate-evidence/phase-3.txt` | 3.4 | Gate proof |

This session ships Phase 3.0 (this doc) + Phase 3.1 (the deterministic
baseline + its tests). Phase 3.1.5 (replay/fills/walk-forward) and
Phase 3.2-3.4 follow in subsequent sessions.

## 12. What success looks like at end-of-Phase-3

```
$ make gate-3
=== Phase 3 gate ===
1. make verify         OK
2. backtest 21-day:    deterministic 53.8% wr, 2,712 trades  ← passes 53% target
3. A/B verdict:        kept   (uplift +4.1pp; latency p99 3.2s; $/decision $0.0084)
4. cost cap:           $48.20 cumulative across 4 passes (limit $50)
5. evidence:           runbooks/gate-evidence/phase-3.txt written
=== Phase 3 gate green ===
```

If `kept`: ensemble carries forward into Phase 4 paper. If `cut`:
deterministic-only into Phase 4; ensemble rework deferred to Phase 8.

---

**Locked.** Any change to MarketEvent / Decision / Fill schemas after
the first commit requires a new design-doc revision (anti-vibe rule #1).
The threshold and weights ARE not locked — they're calibrated by
Phase 3.3.
