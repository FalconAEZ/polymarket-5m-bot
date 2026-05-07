# Design — Paper-mode Runtime + Sim Validation + Decision Log (Phase 4)

> Purpose: lock the architecture for the paper-trading runtime that
> consumes the same live feeds the production bot will use in Phase 6,
> drives the deterministic Strategy from Phase 3 against them, simulates
> fills via the same FillSimulator the backtest uses, and writes every
> decision + settlement to a JSONL log for postmortems and Phase 8
> ensemble re-runs. Anti-vibe rule #1: this doc lands and locks before
> any code in `src/polymarket_bot/_paper/` (beyond the existing stub
> `__init__.py`) or `scripts/validate_paper_sim.py`.
>
> Anchors:
> - `RUNBOOK.md` §"PHASE 4 — Paper Trading on Live Venue" (sub-tasks 4.1, 4.3, 4.4, 4.5)
> - `MASTERPLAN.md` §"Phase 4 — paper trading"
> - `design/backtest.md` (Phase 3) — the Strategy / Decision / Fill protocol shapes that this runner consumes
> - locked decisions [#9 sizing, #11 wallet split, #16 LLM verdict, #17 gasless relayer] in `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`
> - `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_3.md` — Phase 3 outcome (LLM A/B CUT; deterministic-only into Phase 4); diagnostic that the backtest produced -$6.16 P&L on 60% win-rate / 15 fills, surfacing fee+spread question
>
> Out of scope for this doc: the 14-day paper run itself (wall-clock,
> not a single-session deliverable); regime-coverage analysis; daily P&L
> ritual ergonomics. Those are future-session work that fires when the
> Phase 4 gate is ready to evaluate evidence.

---

## 1. Why paper mode exists

Phase 3 closed with a backtest that fired on real captured data:
**60% win-rate over 15 fills but −$6.16 net P&L**. There are three
non-exclusive explanations and the backtest cannot tell them apart:

  (a) the FillSimulator is too optimistic — it fills decisions that the
      live CLOB would never match, biasing the win-rate up while the
      slippage/fee math remains correct;
  (b) the fee/impact model in `polymarket_bot.backtest.fills` is wrong —
      Polymarket's actual fee structure on the gasless relayer (locked
      decision #17) differs from the 2 bps + linear-impact assumption
      `design/backtest.md` §5 baked in;
  (c) the strategy is genuinely unprofitable at $5 flat sizing
      (locked decision #9) — the edge is real but smaller than the
      round-trip cost.

Paper mode answers (a) directly: by running the same Strategy against
the **live orderbook seen at decision time** (not the next book like
the backtest's queued-fill model), and recording both the simulated
fill and the actual top-of-book at the timestamp the live order would
have hit the matching engine, we measure how close the simulator gets
to ground truth. The Phase 4 gate thresholds (RUNBOOK §4.3) require
≥ 90% of simulated fills within 1¢ of the actual top-of-book.

Paper mode does NOT answer (b) or (c) on its own. (b) gets answered in
Phase 1B when real fills generate ground-truth fee/impact numbers; (c)
gets answered by the 14-day P&L itself. But (a) is a prerequisite —
without simulator validation, Phase 1B and Phase 6 cannot proceed.

## 2. Architecture — one process, three layers

```
                          ┌────────────────────────────────────┐
                          │   _live.feeds (4 WS feeds)         │
                          │     binance / coinbase /           │
                          │     oracle / polymarket            │
                          └────────────────┬───────────────────┘
                                           │ Records (ts_utc_ns,
                                           │  source, kind,
                                           │  payload_json)
                                           ▼
              ┌────────────────────────────────────────────────┐
              │   _paper.runner.PaperRunner                    │
              │     1. fans-in feeds (drop-oldest backpressure)│
              │     2. decodes Record → MarketEvent[s]         │
              │        via replay.decode_record (reused)       │
              │     3. synthesises WindowBoundary at 300s marks│
              │     4. observes oracle samples for resolution  │
              │     5. updates ShadowBook on each BookUpdate   │
              │     6. drives Strategy.on_event → Decision     │
              │     7. queues Decision; ShadowBook attempts    │
              │        fill on each subsequent matching book   │
              │        until ttl_s elapses                     │
              │     8. settles at window close → P&L           │
              │     9. writes decision_log lines               │
              └─────────┬─────────────┬──────────────┬─────────┘
                        ▼             ▼              ▼
                 ShadowBook       Strategy      DecisionLog
              (per-asset latest  (Phase 3      (JSONL append-only,
               BookUpdate +       protocol;     state/decisions/
               FillSimulator)     deterministic <UTC-date>.jsonl)
                                  this phase)
```

**Why one process, not two.** The capture is already running (PID 23820
at the start of Phase 4). PaperRunner subscribes to the same upstream
WS endpoints **as a separate process** with its own feed instances — it
does NOT share a queue with the capture writer. Two consequences:

  - Doubled outbound WS load on Polymarket / Binance / Coinbase /
    Alchemy. Each is well within published per-IP rate limits at the
    observed message rates (Polymarket ~14M msgs / 5 days ≈ 32 msg/s
    average; Polymarket's published WS limits are far above this).
  - PaperRunner crash does not affect capture, and vice-versa.

If WS load becomes a problem, a future refactor can have PaperRunner
tail the capture's Parquet files instead. That refactor is out of scope
here.

## 3. Import boundaries (anti-vibe rule #7)

The existing `.importlinter` has two contracts:

  1. `production never imports paper`: `_live` ⊄ `_paper`. KEPT.
  2. `paper never imports live infra`: `_paper` ⊄ `_live`. **CHANGED**.

The second contract is too strict for Phase 4. Paper mode needs to
subscribe to the same WS feeds the production runtime uses; rewriting
`BinanceTradeFeed`, `CoinbaseMatchFeed`, `OracleFeed`, `PolymarketFeed`
under `_paper.feeds` would be 100% duplication of code Phase 6 will
also need. The Phase 4 prompt narrows the rule:

  > `_paper` may import `_live.feeds.*` (read-only) but never
  > `_live.execution.*` (the order-placement / signing path that does
  > not exist yet but will land in Phase 6).

We change the contract from `forbidden source=_paper modules=_live` to
the narrower `forbidden source=_paper modules=_live.runtime,
_live.health, _live.storage` (everything in `_live` except `_live.feeds`).
Adding new modules under `_live` (e.g. a future `_live.execution`)
inherits the ban — the contract is by-allowlist of what `_paper` may
touch under `_live.*`, not by-denylist of new packages.

The Phase-6 production runtime continues to never import `_paper` —
that contract is unchanged.

## 4. Component contracts

### 4.1 ShadowBook (`src/polymarket_bot/_paper/shadow_book.py`)

```python
class ShadowBook:
    """In-memory snapshot of the most recent BookUpdate per asset_id.

    update(book) keeps the latest BookUpdate per asset_id (UP and DOWN
    are distinct asset_ids on Polymarket). attempt_fill(decision, now_ns)
    delegates to FillSimulator after enforcing the TTL gate so the same
    cost model runs in both backtest and paper.
    """

    def __init__(self, simulator: FillSimulator | None = None) -> None: ...
    def update(self, book: BookUpdate) -> None: ...
    def latest(self, asset_id: str) -> BookUpdate | None: ...
    def attempt_fill(self, decision: Decision, now_ts_ns: int) -> Fill | None: ...
```

**TTL semantics.** A Decision is valid for `decision.ts_utc_ns +
decision.ttl_s * 1e9` nanoseconds. After that, `attempt_fill` returns
None even if the book matches and the limit is satisfied. This mirrors
the backtest's TTL gate (`backtest/runner.py:_try_fill`) so the cost
model is identical between the two harnesses.

**Why no per-side index.** Polymarket's two outcome tokens (UP and
DOWN) have distinct `asset_id`s. A Decision targets exactly one
asset_id; ShadowBook only needs to look up the book for that asset_id.
The side field on BookUpdate is consumed by the Strategy, not by
ShadowBook.

### 4.2 PaperRunner (`src/polymarket_bot/_paper/runner.py`)

```python
class PaperRunner:
    """Drives the live feed fan-in through a Strategy + ShadowBook + DecisionLog."""

    def __init__(
        self,
        *,
        feeds: Sequence[Feed],
        strategy: Strategy,
        side_resolver: SideResolver,
        shadow_book: ShadowBook | None = None,
        decision_log: DecisionLog | None = None,
        clock_ns: Callable[[], int] | None = None,
    ) -> None: ...

    async def run(self, *, stop: asyncio.Event | None = None) -> None: ...
    def stop(self) -> None: ...
```

Run-loop steps per record (drop-oldest queue, default 1024):

  1. Decode `Record` → `list[MarketEvent]` via the public
     `polymarket_bot.backtest.replay.decode_record` helper (added in
     Phase 4 as a thin wrapper around the existing `_decode_row` so
     paper/backtest share the decoder).
  2. For each event:
     - emit a synthetic `WindowBoundary(kind="open")` if the event's
       `active_window_ts(...)` differs from the runner's tracked
       `window_ts` (and a `WindowBoundary(kind="close")` for the
       previous window first).
     - feed the event to `strategy.on_event(event)`.
     - if `BookUpdate`: `shadow_book.update(book)`; then re-attempt any
       pending `Decision` whose `asset_id == book.asset_id`.
     - if `OracleUpdate`: latch as last-seen oracle; on first oracle
       inside a new window, latch as `open_oracle_for(window_ts)`.
     - if Strategy returned a Decision: try immediate fill; if fill,
       write `decision_log.record_fired(..., fill=...)` and clear the
       pending slot; if no fill, queue as pending (one slot per window;
       see §5).
  3. On a `WindowBoundary(kind="close")` (synthetic, fired when the
     incoming event crosses the next 300s boundary): settle. Compute
     resolution from `actual_resolution(window_ts, open_oracle,
     close_oracle)`. If a fill landed inside the window, compute P&L
     via `realised_pnl_usd`. Write `decision_log.record_settled(...)`.

**Stop semantics.** `stop()` sets an internal stop event. The async
`run()` loop notices on the next iteration and proceeds to graceful
shutdown: stops each child feed (via `Feed.stop()`), drains the
in-flight queue, calls `decision_log.close()`. Final settlement of an
in-progress window happens iff its close boundary has already been
crossed. Otherwise the in-progress window is dropped — it will reappear
in the next launch's data.

**Backpressure.** If the strategy or fill loop falls behind the feed
fan-in, the per-runner queue drops oldest records (mirrors capture
runtime in `_live.runtime.feed_runner`). Drops are counted in a
process-local `DropCounter` and surfaced via the runner's health
snapshot — operator monitoring catches drops before they distort
sim-validation results.

### 4.3 DecisionLog (`src/polymarket_bot/_paper/decision_log.py`)

Append-only JSONL writer. Path `state/decisions/<UTC-date>.jsonl` where
the date is the UTC date of the **decision** (a settlement line for a
decision made just before midnight stays in the same file as the
fired-line — same window_ts, same asset_id, easier to grep).

Two record kinds, distinguished by `kind`:

```jsonc
// On Decision fire (whether or not a fill happens immediately):
{
  "kind": "fired",
  "decision_id": "<uuid4>",
  "window_ts": 1762540500,            // 5m window start (UTC seconds)
  "decision_ts_ns": 1762540512345678901,
  "asset_id": "0x...",
  "side": "UP" | "DOWN",              // resolved from rationale at log time
  "size_usd": 5.0,
  "price_limit": 0.51,
  "ttl_s": 18,
  "rationale": "composite=+0.612pct (|.|>=0.60) ttl=18s side=UP",
  "snapshot": {
    "spot_now": 67432.10,
    "window_open_spot": 67402.55,
    "oracle_last": 67410.00,
    "open_oracle": 67400.00,
    "best_bid": 0.495,
    "best_ask": 0.505,
    "ask_size_top": 12345.6
  },
  "composite_pct": 0.612,
  "fill": {                            // null if no fill at fire time
    "ts_utc_ns": 1762540512345678901,
    "price_filled": 0.505,
    "size_filled": 9.901,
    "fee_usd": 0.001
  } | null
}

// On window close (every fired decision gets exactly one settled line):
{
  "kind": "settled",
  "decision_id": "<same uuid as fired line>",
  "window_ts": 1762540500,
  "settled_ts_ns": 1762540800123456789,
  "open_oracle": 67400.00,
  "close_oracle": 67450.00,
  "resolution": "UP" | "DOWN" | null,    // null if oracle samples missing
  "fill_at_settle": {                    // copied from latest fill if any
    "price_filled": 0.505,
    "size_filled": 9.901,
    "fee_usd": 0.001
  } | null,
  "pnl_usd": 4.396                       // 0.0 if no fill; net of fees
}
```

**Why JSONL not Parquet.** Decisions are low-volume (≤ 288/day at the
deterministic firing ceiling). JSONL is grep-friendly and round-trips
through the standard library. Phase 8 ensemble re-runs read JSONL, not
Parquet, so the on-disk schema can drift between the runtime and the
re-run code without breaking pyarrow's stricter type-system.

**Why uuid4 not a deterministic id.** Two fired lines for the same
window can happen in principle (the strategy re-fires after a TTL
expiry — guarded against by Phase 3 today, but the schema doesn't
encode that invariant). `decision_id` is the join key between fired
and settled lines.

**Round-trip test.** Write 3 synthetic fired + 3 settled lines, read
the file back, assert all 6 lines parse and reconstruct as the same
dataclasses. Asserts on file path, schema version, append-only behaviour.

## 5. State machine — one decision per window

The Phase 3 deterministic strategy fires at most once per 5m window
(`_fired_for_window` flag in `strategies/deterministic.py`). PaperRunner
trusts this invariant: at most one Decision is pending at any time.

Lifecycle:

  - `pending_decision = None` at window open.
  - First Decision returned by Strategy → `pending_decision = decision`.
  - On each subsequent BookUpdate matching `decision.asset_id`,
    `shadow_book.attempt_fill(decision, now_ns)` is called.
  - On first successful fill: write `fill` line in decision_log,
    `pending_decision = None`. (Even though Strategy won't re-fire
    for this window, we clear so that a logic bug elsewhere produces
    a clean drop, not a double-fill.)
  - On TTL expiry without fill: `pending_decision = None`. The fired
    line is already in the log with `fill=null`.
  - On window-close boundary: write `settled` line with whatever
    fill exists (or null) and the realised P&L.

LLM strategies in Phase 8 may want to fire multiple decisions per
window (e.g. a "small initial + scale-in" pattern). When that lands,
the pending-slot becomes a list and ShadowBook tracks per-decision
TTLs. The Phase 4 design assumes one-per-window because the Phase 3
strategy enforces it.

## 6. Sim validation methodology — task 4.3

`scripts/validate_paper_sim.py` answers one question per decision:
**how close was the simulated fill price to the actual top-of-book at
the moment the order would have hit the matching engine?**

Methodology:

  1. **Source of decisions.** Run the existing `BacktestRunner` over
     captured 2026-05-06 + 2026-05-07 data with the deterministic
     strategy at threshold 0.6pp. This produces a list of
     `WindowResult` records, each with the underlying Decision (if
     `fired=True`) and the simulated Fill (if `fill is not None`).
     We sample N decisions (N=100 if available; fewer if fewer fired)
     across the captured time range.
  2. **Counterfactual fill timestamp.** Each Decision has
     `decision.ts_utc_ns`. The live order would have hit the matching
     engine at `decision.ts_utc_ns + latency_budget_ns`. We use a
     conservative latency budget of **150ms** (matches the gasless
     relayer's typical p99 confirm-time per Polymarket docs).
  3. **Look up actual top-of-book.** For each Decision, find the
     `BookUpdate` event for `decision.asset_id` whose `ts_utc_ns` is
     the smallest value `≥ decision.ts_utc_ns + 150_000_000`. That's
     "the book the order would have hit". If no such book exists
     within the window's end (T + 300s), the decision is excluded
     from the validation set with reason `no_book_after_decision`.
  4. **Compute delta in cents.** `delta_cents = abs(simulated_fill_price
     − actual_best_ask) * 100`. Buy orders fill against `best_ask`, so
     that's the comparison anchor.
  5. **Aggregate report.** count, mean, median, p95, max delta in
     cents; pass-rate = fraction with `delta_cents ≤ 1.0`. Target:
     **≥ 90% pass-rate** per RUNBOOK §4.3.

Output:
  - Stdout: human-readable summary block.
  - File: `runbooks/gate-evidence/phase-4.3-sim-validation.txt` with
    the same content + a per-decision CSV-shaped block (one row per
    sampled decision: window_ts, decision_ts_ns, asset_id, side,
    sim_price, actual_best_ask, delta_cents).

If the pass-rate is < 90% on the hours-of-data sample available now,
the script does NOT fail the gate (the gate fires after the 14-day
run, not in this session). It writes the gap to the report and the
14-day run becomes the real validation.

## 7. What is OUT of scope this session

Phase 4 *dev* lands in this session. Phase 4 *gate* fires in a future
session, after the 14-day paper run completes. Out of scope here:

  - The 14-day paper run itself (wall-clock, kicked off at end of
    this session via `runbooks/paper-monitor.md`).
  - The Phase 4 gate script (`runbooks/gates/phase-4.sh`) is written
    in this session as a mechanical scaffolding, but NOT run — it
    will fail today because no 14-day evidence exists.
  - Daily P&L ritual ergonomics (the runbook covers what to inspect;
    operator iteration on it is post-launch).
  - Regime-coverage analysis: the run window must include ≥ 1
    CPI/FOMC release, ≥ 1 weekend low-vol period, ≥ 1 BTC daily move
    > 2%. Selection of the run window is in `runbooks/paper-monitor.md`
    pre-flight; not enforced by the gate script.
  - LLM ensemble re-run: per `checkpoint_phase_3.md`, the ensemble
    code is retained; Phase 8 revisits it after Haiku caching is
    fixed. Out of scope for Phase 4.
  - VPS provisioning: Phase 5. PaperRunner runs on the laptop for the
    Phase 4 paper window.

## 8. File map

| Path | Purpose |
|---|---|
| `design/paper.md` (this file) | Architecture, locked first |
| `src/polymarket_bot/_paper/__init__.py` | Already exists; updated docstring |
| `src/polymarket_bot/_paper/shadow_book.py` | ShadowBook + tests |
| `src/polymarket_bot/_paper/runner.py` | PaperRunner + tests |
| `src/polymarket_bot/_paper/decision_log.py` | JSONL writer + reader + tests |
| `src/polymarket_bot/backtest/replay.py` | Add public `decode_record(record, side_resolver)` |
| `tests/paper/__init__.py` | Package marker |
| `tests/paper/test_shadow_book.py` | Unit tests |
| `tests/paper/test_runner.py` | Synthetic feed + assert on log shape |
| `tests/paper/test_decision_log.py` | Round-trip tests |
| `.importlinter` | Replace contract 2 with the narrower allowlist |
| `scripts/validate_paper_sim.py` | Phase 4.3 validation harness |
| `scripts/run_paper.py` | CLI entry point — wires real feeds + DeterministicStrategy + JSONL log |
| `runbooks/paper-monitor.md` | Daily ritual + pre-flight + stop procedure |
| `runbooks/gates/phase-4.sh` | Future gate (not run this session) |
| `runbooks/gate-evidence/phase-4.3-sim-validation.txt` | Sim-validation report |

## 9. Test discipline (anti-vibe rule #6)

- **ShadowBook**: synthetic BookUpdate / Decision fixtures. Cover:
  asset_id mismatch returns None; latest beats earlier; TTL gate
  rejects late attempts; FillSimulator delegation matches backtest's
  exact math on identical inputs.
- **PaperRunner**: a `FakeFeed` that yields a fixed Record sequence
  (one of each kind: spot, oracle, polymarket book, then a 300s
  rollover) drives a fake Strategy (returns one Decision) into
  PaperRunner. Assertions: decision_log captured both a `fired` and
  a `settled` line; fill semantics match the synthetic book. No real
  network, no real WS.
- **DecisionLog**: write-then-read 3 fired + 3 settled lines; assert
  schema and ordering; assert appending to existing file appends, not
  truncates.
- All tests live under `tests/paper/`. `pytest -q` stays under 5s on
  the laptop.

## 10. Locked

Anything that breaks `MarketEvent`, `Decision`, `Fill`, or
`SideResolver` shapes outside of a new design-doc revision is
prohibited. Strategy contract is unchanged from Phase 3. ShadowBook
public surface is locked at `update / latest / attempt_fill`.
PaperRunner public surface is locked at `__init__ / run / stop`.
DecisionLog public surface is locked at `__init__ / record_fired /
record_settled / close`.

The 90%-within-1¢ threshold for sim validation is a target, not a
gate-failure trigger in this session — the 14-day run produces the
real evidence.
