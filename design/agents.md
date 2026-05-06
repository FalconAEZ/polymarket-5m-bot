# Design — LLM Agent Layer (Phase 3.2)

> Purpose: lock the design for the 3-agent + meta-decider ensemble that Phase 3.2
> implements per locked decisions #4, #5, #6, #14, #16. This doc precedes any
> code in `src/polymarket_bot/agents/`, `prompts/`, `runbooks/scripts/run_ab.py`,
> per anti-vibe rule #1.
>
> Anchors:
> - `RUNBOOK.md` §"Phase 3 — Backtest Harness + LLM A/B Test" (3.2-3.4)
> - `MASTERPLAN.md` §"LLM Ensemble" (line 138 onward)
> - `design/backtest.md` §3 (Strategy interface — ensemble plugs in here)
> - locked decisions [#4, #5, #6, #14, #16] in `project_decisions.md`
> - Anthropic API skill (loaded into the build session) — adaptive thinking,
>   prompt caching, structured outputs via `client.messages.parse()`
>
> Out of scope: live trading (Phase 6), kill switches (Phase 5), the
> deterministic baseline strategy (already locked in
> `src/polymarket_bot/strategies/deterministic.py`).

---

## 1. Why an ensemble at all

The deterministic baseline in `strategies/deterministic.py` is the floor:
window-delta + oracle-gap composite > threshold ⇒ fire on the matching side.
It catches the obvious lag-driven trades. The ensemble exists to catch the
non-obvious ones — orderbook microstructure that says "the book is leaning
DOWN even though spot is flat", momentum bursts that the simple composite
misses, oracle-gap analysis aware of the recently-measured 33s heartbeat
(decision #21).

Per locked decision #16, the ensemble is **kept iff backtest win-rate uplift
≥ 3pp over deterministic-only**. If LLMs lose, deterministic ships and the
ensemble sleeps until Phase 8. Either outcome is a passing Phase 3 gate.

## 2. Architecture

Three specialist agents vote in parallel; a meta-decider combines the votes
plus the deterministic composite into a final action.

```
                       ┌──────────────────┐
       MarketEvent ───▶│ orderbook agent  │──┐
                       │   Haiku 4.5      │  │ AgentVote
                       └──────────────────┘  │
                       ┌──────────────────┐  │
                  ───▶ │ oracle-gap agent │──┤
                       │   Haiku 4.5      │  │
                       └──────────────────┘  │ ─▶ ┌─────────────────┐ ─▶ MetaDecision
                       ┌──────────────────┐  │    │ meta-decider    │    (FIRE / ABSTAIN
                  ───▶ │ momentum agent   │──┘    │   Sonnet 4.6    │     side, confidence)
                       │   Haiku 4.5      │       └─────────────────┘
                       └──────────────────┘                ▲
                                                           │
                       deterministic composite ────────────┘
                       (also passed for context)
```

Per locked decision #5: **exactly 3 specialist agents + 1 meta-decider**. No
`behavioral_mimic` 4th agent (decision #19 closed that). No agent fan-out
beyond 3 — adding more increases cost without commensurate signal in the
2026-05 calibration window.

### Model choices (per RUNBOOK 3.2)

| Agent / role | Model | Why |
|---|---|---|
| orderbook | `claude-haiku-4-5` | Speed-critical (5m windows); pattern-matching task |
| oracle-gap | `claude-haiku-4-5` | Same |
| momentum | `claude-haiku-4-5` | Same |
| meta-decider | `claude-sonnet-4-6` | Synthesises 3 votes + deterministic; benefits from adaptive thinking |

Haiku 4.5 caches at 4096 tokens minimum; Sonnet 4.6 at 2048. System prompts
are sized accordingly — see §6.

## 3. Tier-3 fallback (decision #6)

Per locked decision #6, the deterministic Tier-3 path catches every LLM
failure. The ensemble's contract:

- If **≥ 2 agents return valid `AgentVote`s** → meta-decider runs, returns
  `MetaDecision` (FIRE or ABSTAIN).
- If **< 2 agents** return valid votes (refusals, schema failures, API
  errors, budget caps) → ensemble abstains; downstream strategy falls back
  to the deterministic composite. Never skip a window for an LLM problem.
- If the deterministic composite is itself below the 0.6pp threshold AND
  the ensemble fires, **the meta-decider's vote wins** — the ensemble's
  whole point is catching trades the composite missed.
- If the deterministic composite is above threshold AND the ensemble
  abstains, the deterministic side fires — the LLM doesn't get to veto a
  strong composite signal.

So the union is: fire if `(composite ≥ 0.6) OR (ensemble FIRE)`.
Side selection: ensemble's side if it fired, else composite's sign.

## 4. The `Agent` protocol

```python
# src/polymarket_bot/agents/protocol.py
from typing import Literal, Protocol
from pydantic import BaseModel, Field

Side = Literal["UP", "DOWN"]

class AgentContext(BaseModel):
    """Per-window context handed to each agent at decision time.

    All fields are derived from the typed MarketEvent stream — agents do NOT
    parse raw payloads. Phase 3.1.5 (replay) and Phase 6 (live runtime) both
    produce this same shape.
    """
    window_ts: int
    now_ts_utc_ns: int
    seconds_to_close: int

    # Spot
    spot_now: float
    spot_at_window_open: float
    spot_recent_60s: list[float]   # last ~60s of spot ticks (downsampled)

    # Oracle
    oracle_last: float
    oracle_at_window_open: float
    oracle_age_s: float            # seconds since last oracle update

    # Polymarket book
    best_bid_up: float | None
    best_ask_up: float | None
    best_bid_down: float | None
    best_ask_down: float | None
    book_imbalance: float | None   # (bid_size - ask_size) / total

    # Deterministic composite
    composite_pct: float

class AgentVote(BaseModel):
    """Each specialist's verdict. Validated by pydantic on parse."""
    side: Literal["UP", "DOWN", "ABSTAIN"] = Field(description="Direction or abstain")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=240)

class Agent(Protocol):
    name: str
    model: str
    async def vote(self, ctx: AgentContext) -> AgentVote | None: ...

class MetaDecision(BaseModel):
    action: Literal["FIRE", "ABSTAIN"]
    side: Literal["UP", "DOWN"] | None
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(max_length=400)
```

## 5. Cost discipline (decision #14)

Locked decision #14: $50 covers Phases 0-3 with cache discipline, $150
before Phase 4, $300 before Phase 6, $200/month sustained. For Phase 3
specifically:
- Max 4 backtest passes
- Hard cap: $35 per pass
- Cache hit-rate ≥ 80% required to hit budget

The implementation:

- **`agents.budget.BudgetTracker`** — counts every API call's tokens
  (input/output/cache-read/cache-create), multiplies by per-token unit
  prices, raises `BudgetExceeded` when cumulative spend ≥ hard_cap. The
  Phase 3 backtest catches `BudgetExceeded` and writes a partial-results
  evidence file rather than letting Anthropic charges run away.
- **`agents.cache.cache_blocks(...)`** — helper that returns a
  `system=[...]` list with `cache_control: {"type": "ephemeral"}` on the
  static prompt block, so the per-window dynamic block (the JSON-encoded
  `AgentContext`) sits AFTER the cache breakpoint. With prompts sized
  ≥ 4096 tokens (Haiku) and a deterministic prompt order, cache hit rate
  ≥ 95% is achievable.
- **Adaptive thinking only on the meta-decider** (Sonnet 4.6 supports it,
  Haiku 4.5 doesn't). `effort: "medium"` on the meta; specialist agents
  use no thinking mode. Per the API skill: lower effort means tighter,
  more-consolidated outputs — exactly what we want for Haiku.

### Estimated cost per backtest pass

Assumptions: 21-day walk-forward × 288 windows/day × 1 pass = 6,048
windows. Each window: 3 Haiku calls + 1 Sonnet call. Each Haiku call
~5K input cached + ~50 input dynamic + ~120 output. Sonnet meta call:
~3K cached + ~250 dynamic (3 votes + composite) + ~250 output.

| Component | Tokens | Unit price | Total |
|---|---|---|---|
| Haiku cache reads (3 × 5K × 6048) | 90.7M | $0.10 / 1M | $9.07 |
| Haiku dynamic input (3 × 50 × 6048) | 0.91M | $1.00 / 1M | $0.91 |
| Haiku output (3 × 120 × 6048) | 2.18M | $5.00 / 1M | $10.90 |
| Sonnet cache reads (3K × 6048) | 18.1M | $0.30 / 1M | $5.43 |
| Sonnet dynamic input (250 × 6048) | 1.51M | $3.00 / 1M | $4.54 |
| Sonnet output (250 × 6048) | 1.51M | $15.00 / 1M | $22.68 |
| Cache writes (one-time per session, ~$0.05) | — | — | $0.05 |
| **Total per pass** | | | **~$53.6** |

That's **over the $35 hard cap**. Two adjustments before live:
1. Reduce specialist input by half (windows of 144 instead of 288 — fire
   only every other minute, sufficient given the 33s heartbeat).
2. Or: drop to 1-2 specialists per window where deterministic is high-
   confidence (only call all 3 when composite is in the indeterminate
   band 0.3-0.6pp).

For the FIRST backtest pass we keep all 3 agents on every window to
calibrate; budget tracker will catch any runaway. Subsequent passes
narrow the call set per the calibration result.

## 6. Prompt design

### Specialist agents (Haiku 4.5)

Per the API skill, Haiku 4.5 caches at ≥ 4096 tokens. Each specialist's
system prompt:

| Section | Tokens (approx) | Cacheable? |
|---|---|---|
| Role + task framing | ~200 | ✅ |
| Polymarket BTC 5m market explanation | ~600 | ✅ |
| Heartbeat context (33s, decision #21) | ~150 | ✅ |
| Output schema description (`AgentVote`) | ~250 | ✅ |
| Few-shot examples (5-10 windows with vote) | ~3000 | ✅ |
| **Total static prompt** | **~4200** | ✅ above min |

Each specialist's prompt lives at `prompts/<agent>.md`, version-controlled,
inspectable by reviewers. Editing a prompt creates a new prompt cache key
(any byte change invalidates the prefix per the API skill).

### Meta-decider (Sonnet 4.6)

Sonnet 4.6 caches at ≥ 2048 tokens. Meta prompt:

| Section | Tokens (approx) | Cacheable? |
|---|---|---|
| Role: "weigh 3 specialist votes + deterministic" | ~150 | ✅ |
| Trade thesis context | ~400 | ✅ |
| Decision criteria (when to FIRE) | ~600 | ✅ |
| Output schema description (`MetaDecision`) | ~200 | ✅ |
| Few-shot examples (5 vote-sets with decision) | ~1200 | ✅ |
| **Total static prompt** | **~2550** | ✅ above min |

The meta-decider runs with `thinking: {"type": "adaptive"}` and
`output_config: {"effort": "medium"}`. Per the API skill, this is the
right balance for synthesising 3 votes + a composite — fast enough for
the 5m cadence, deep enough to spot when the votes disagree.

## 7. Anthropic adapter

Single source of truth for API calls. Wraps `anthropic.AsyncAnthropic`:

```python
# src/polymarket_bot/agents/anthropic_client.py
class AnthropicAdapter:
    def __init__(
        self,
        api_key: str | None = None,
        budget: BudgetTracker | None = None,
    ) -> None: ...

    async def parse(
        self,
        *,
        model: str,
        system: list[dict],   # cache_blocks(...) output
        user: str,             # JSON-encoded AgentContext
        output_format: type[BaseModel],
        thinking: dict | None = None,
        effort: str | None = None,
        max_tokens: int = 1024,
    ) -> tuple[BaseModel | None, Usage]: ...
```

Returns `(parsed_pydantic_model, usage)` on success, `(None, usage)` on
refusal / schema fail / `BudgetExceeded`. Per the API skill, uses
`client.messages.parse()` which auto-validates against the pydantic
output_format.

Tests inject a `FakeAdapter` that returns canned responses — no real API
calls in unit tests (anti-vibe rule #6).

## 8. EnsembleStrategy — bridge to BacktestRunner

`src/polymarket_bot/strategies/ensemble.py` implements the `Strategy`
protocol from `strategies/protocol.py`:

```python
class EnsembleStrategy:
    name = "ensemble"

    def __init__(
        self,
        specialists: list[Agent],
        meta: MetaAgent,
        deterministic_threshold_pct: float = 0.6,
        size_usd: float = 5.0,
    ) -> None: ...

    async def on_event(self, event: MarketEvent) -> Decision | None:
        # 1. Maintain per-window state (same as DeterministicStrategy)
        # 2. At fire-window time:
        #    a. Build AgentContext
        #    b. Fan out to 3 specialists (asyncio.gather)
        #    c. Filter to valid votes; abstain if < 2
        #    d. Call meta-decider with votes + composite
        #    e. Compute final action per §3 union rule
        # 3. Return Decision or None
```

This way the BacktestRunner from Phase 3.1.5 doesn't need to know about
LLMs at all — it just sees a Strategy.

## 9. Test discipline

Per anti-vibe rule #6, **NO real API calls in unit tests**. Plan:

- `tests/agents/test_protocol.py` — schema validation: AgentVote, MetaDecision
- `tests/agents/test_budget.py` — token counting math, BudgetExceeded raise
- `tests/agents/test_cache.py` — cache_blocks helper output shape
- `tests/agents/test_anthropic_client.py` — adapter parses mock responses,
  records usage, surfaces BudgetExceeded
- `tests/agents/test_orderbook.py` — agent calls adapter with right
  prompt + context, parses vote, falls back to None on schema fail
- (same shape for oracle_gap, momentum, meta)
- `tests/strategies/test_ensemble.py` — ensemble logic: <2 votes →
  abstain; FIRE wins over composite-below-threshold; high composite
  fires even when ensemble abstains; meta side wins if ensemble fires.

Live API tests (running real Haiku/Sonnet calls) are **manual scripts**
under `runbooks/scripts/`, NOT in CI, gated behind explicit operator
$-approval per decision #14.

## 10. Phase 3.3 A/B run (next session, deferred)

`runbooks/scripts/run_ab.py`:
- Loads same captured ticks data + same TokenSideIndex as
  `scripts/run_backtest.py`
- Runs `BacktestRunner` twice on the same date range:
  1. `DeterministicStrategy` (cost: $0)
  2. `EnsembleStrategy(specialists, meta, ...)` (cost: ≤ $35)
- Captures per-window WindowResults from each pass
- Computes paired metrics: win_rate_delta, latency_delta, cost_per_decision
- Writes `runbooks/decisions/llm-ab-result.md` with verdict per decision #16

The actual live A/B run is **next session** — this session ships the
agent layer + tests + design docs only. No live API spend in this
session beyond what cache-warming might cost in dev (target $0.50 max).

## 11. File map (what Phase 3.2 creates)

| Path | Phase | Purpose |
|---|---|---|
| `design/agents.md` (this) | 3.2 | Lock first |
| `src/polymarket_bot/agents/__init__.py` | 3.2 | Package marker |
| `src/polymarket_bot/agents/protocol.py` | 3.2 | Agent + AgentVote + MetaDecision + AgentContext |
| `src/polymarket_bot/agents/budget.py` | 3.2 | BudgetTracker |
| `src/polymarket_bot/agents/cache.py` | 3.2 | cache_blocks helper |
| `src/polymarket_bot/agents/anthropic_client.py` | 3.2 | AnthropicAdapter (Anthropic SDK wrapper) |
| `src/polymarket_bot/agents/orderbook.py` | 3.2 | Specialist 1 |
| `src/polymarket_bot/agents/oracle_gap.py` | 3.2 | Specialist 2 |
| `src/polymarket_bot/agents/momentum.py` | 3.2 | Specialist 3 |
| `src/polymarket_bot/agents/meta.py` | 3.2 | Meta-decider |
| `prompts/orderbook.md` + `oracle_gap.md` + `momentum.md` + `meta.md` | 3.2 | Versioned prompts |
| `src/polymarket_bot/strategies/ensemble.py` | 3.2 | EnsembleStrategy |
| `tests/agents/*` | 3.2 | Unit tests with mocked adapter |
| `tests/strategies/test_ensemble.py` | 3.2 | Ensemble integration tests |
| `runbooks/scripts/run_ab.py` | 3.3 (next session) | A/B harness |
| `runbooks/decisions/llm-ab-result.md` | 3.4 (next session) | OD-5 verdict |

---

**Locked.** Schema changes (AgentVote / MetaDecision / AgentContext) require
a new design-doc revision committed before code. The model choices, prompt
structure, and cost cap are tunable — only the ensemble shape (3+1) and the
Tier-3 fallback rule are locked.
