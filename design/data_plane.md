# Design — Read-only Data Plane (Phase 2)

> Purpose: lock the architecture for the four read-only feeds (BTC spot ×2,
> Chainlink BTC/USD on Polygon, Polymarket 5m BTC up/down) and the shared
> Parquet archive that backs every Phase 3 backtest and the Phase-2-gate
> oracle-behavior verification. This doc precedes any code in
> `src/polymarket_bot/_live/feeds/`, `src/polymarket_bot/_live/storage.py`,
> `src/polymarket_bot/_live/health.py`, `src/polymarket_bot/_live/runtime.py`,
> `src/polymarket_bot/feeds/protocols.py`, `src/polymarket_bot/resolver.py`,
> or `scripts/run_capture.py`, per anti-vibe rule #1.
>
> Anchors:
> - `RUNBOOK.md` §"Phase 2 — Read-only Data Plane" (lines 719-862)
> - `MASTERPLAN.md` §"The trade thesis" (line 27 onward) and §"Architecture"
> - locked decisions [#15, #17] in
>   `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`
> - `design/gasless.md` §1 (CLOB API path is read-without-auth for market data;
>   this doc reuses that property)
> - `pdfs/BUILD_SPEC.pdf` p. 22-23 (operating discipline)
>
> Out of scope: order placement (Phase 6), strategy logic (Phase 3), kill
> switches (Phase 5), the LLM ensemble (Phase 3-4). All four feeds in this doc
> are **read-only**, no signing, no funder, no signer.

---

## 1. Why this phase exists at all

The trade thesis (`MASTERPLAN.md` line 31) hinges on a measurable property
of Chainlink BTC/USD on Polygon: **a 60s heartbeat with no deviation
threshold**. The MASTERPLAN labels that claim **PENDING ON-CHAIN
VERIFICATION**. If the heartbeat is faster, slower, or jittery, the
deterministic Tier-3 signal collapses and Phase 3 backtests would be
malpractice. So Phase 2 is two concrete deliverables:

1. A four-feed archival pipeline that captures clean, UTC-timestamped tick
   data for ≥ 7 calendar days into per-source-per-day Parquet files.
2. A statistical analysis (`scripts/analyze_oracle.py`, Phase 2.6, next
   session) over those 7 days that confirms or denies the heartbeat claim
   against four pass criteria.

This document specifies (1). (2) is a follow-up session because it depends
on data that has not yet been captured.

## 2. The four feeds and their endpoints

| Feed | Endpoint | Auth | Expected msg rate | What we keep |
|---|---|---|---|---|
| `binance` (BTC/USDT trade) | `wss://stream.binance.com:9443/ws/btcusdt@trade` | None | ~5 msg/s | Every trade |
| `coinbase` (BTC-USD matches) | `wss://ws-feed.exchange.coinbase.com` + subscribe | None | ~2-10 msg/s | Every match |
| `oracle` (Chainlink BTC/USD `AnswerUpdated`) | `POLYGON_RPC_URL` (already `wss://` in `.envrc` per pre-flight) → contract `0xc907E116054Ad103354f2D350FD2514433D57F6f` | None for `eth_subscribe logs` | ~1 msg / 60s | Every `AnswerUpdated` event |
| `polymarket` (5m BTC up/down book + trades) | `wss://ws-subscriptions-clob.polymarket.com/ws/market` (book/trade channels for the active token_id) | None for read-only market channel (per `design/gasless.md` §1) | ~bursty around price moves | Every book snapshot/update + trade |

Two upstreams for spot is **deliberate**: spot redundancy decouples
exchange-specific glitches (a Binance maintenance window, a Coinbase
freeze) from our resolution-time price view. They are independent — the
aggregator must keep running if either dies.

The **Polymarket Gamma API** at `https://gamma-api.polymarket.com/events?slug=<slug>`
is a sidecar HTTP call (not a feed) used by the polymarket WS feed to
resolve the active 5m window's slug → token_id at every window rotation.
Cached one window ahead.

## 3. Async architecture

Single asyncio event loop. No threads. Six long-running tasks share a
single `asyncio.Queue` and a graceful-shutdown event:

```
                 ┌─ binance_feed.stream() ──┐
                 │                          │
                 ├─ coinbase_feed.stream() ─┤
                 │                          │   queue (bounded, 10k)
runtime.main() ──┼─ oracle_feed.stream() ───┼──────────────► storage.writer
                 │                          │                   │
                 ├─ polymarket_feed.stream()┤                   ▼
                 │                          │              ticks/<utc-date>/<source>.parquet
                 └─ health.aggregator() ────┘
```

- Each feed is a separate `asyncio.Task` running `feed.stream()` which
  produces `Record`s via an internal channel (the feed pushes to the shared
  queue itself; `stream()` is the canonical iteration interface for tests).
- The writer is a single task draining the queue; it owns one open
  `pyarrow`-backed Parquet writer per `(utc_date, source)` pair. Per-source
  per-day files are append-only via batched Arrow writes; the writer
  flushes on either of: (a) batch size ≥ 200 records, (b) 5s elapsed since
  last flush. This trades a small recovery loss (≤ 5s of data on hard
  crash) for throughput.
- The health aggregator wakes every 30s, reads each feed's `_health` dict,
  serialises a snapshot to `state/feeds_health.json` atomically (write to
  temp + rename), and fires a Telegram alert if any feed's
  `last_seen_ns < now_ns - 5*60*10⁹`.
- `runtime.main()` registers SIGTERM and SIGINT handlers that set the
  shutdown event. On set: feeds stop reading from their WS connections,
  push a final `None` sentinel to the queue, the writer drains the queue,
  flushes all open Parquet writers, and the runtime returns.

## 4. Storage schema (PINNED — must not drift after the first commit)

Per-source Parquet files. Schema:

| Field | Arrow type | Description |
|---|---|---|
| `ts_utc_ns` | `int64` | Event time, nanoseconds since UNIX epoch UTC. Sourced from upstream where the upstream provides one (Binance `E`, Coinbase `time`, Chainlink `updatedAt`, Polymarket `timestamp`). Falls back to `received_at_ns` if upstream is silent. |
| `received_at_ns` | `int64` | Local clock at the moment our process saw the message. From `time.time_ns()` immediately after the WS `recv()` returns. |
| `source` | `string` | One of `"binance"`, `"coinbase"`, `"oracle"`, `"polymarket"`. Hard-coded per feed; no free-form values. |
| `kind` | `string` | Per-source event kind. Values: `binance` → `"trade"`. `coinbase` → `"match"`. `oracle` → `"AnswerUpdated"`. `polymarket` → `"book"` \| `"book_top"` \| `"trade"` \| `"price_change"`. |
| `payload_json` | `string` | The raw upstream payload, JSON-serialised, with **no transformation** beyond `json.dumps(msg, separators=(",", ":"))`. We deliberately archive the raw shape so Phase 3 can mine fields the original feed code did not parse. |

Two timestamps deliberately. `ts_utc_ns` is what the upstream said.
`received_at_ns` is our own clock. The skew between them is itself a
metric Phase 3 will mine (network lag distribution, oracle-block-time vs
spot-trade-time alignment).

**Why JSON not a richer schema.** We are still in a learning phase; the
strategy will mine fields we do not yet know to parse. Storing the raw
payload as a string costs ~20-40% disk (Parquet's dictionary encoding +
zstd compresses repeated JSON keys hard) in exchange for keeping every
upstream field available without a re-capture. That trade is correct here.

**No schema migration mechanism in Phase 2.** If we discover a column we
need, we re-derive it from `payload_json` in Phase 3 rather than rewriting
historical Parquets.

## 5. Storage layout

```
ticks/
├── 2026-05-08/
│   ├── binance.parquet
│   ├── coinbase.parquet
│   ├── oracle.parquet
│   └── polymarket.parquet
├── 2026-05-09/
│   └── ...
└── ...
```

- Path: `ticks/<UTC-YYYY-MM-DD>/<source>.parquet`.
- Rotation: at UTC midnight the writer closes the current day's writers
  and opens new ones for the new date. Implementation: a small
  `_current_date` field on the writer; comparing it against
  `datetime.now(UTC).date()` on each batch flush.
- `ticks/` is gitignored (already in `.gitignore` line 22).
- One file per source per day means: the Phase 2 gate's `ls ticks/` count
  ≥ 7 dated directories check is unambiguous, and Phase 3 backtest replays
  can stream a single day without scanning the rest of the archive.

## 6. Reconnect policy

Each feed's WS-loop wraps the connection in a try/except + while-True with
exponential backoff:

```
attempt:    1    2    3    4    5     6    7+
sleep (s):  1    2    4    8    16    32   60
```

After attempt 7 the sleep is clamped at 60s and stays there. Reconnect
attempts continue indefinitely; a flapping feed is still better than a
dead one during the 7-day capture.

Each `_health` dict tracks `reconnects` (a monotonic counter incremented
per failed attempt) and `last_seen_ns` (updated on every successful
`recv()`). The health aggregator (see §3) fires a single Telegram alert
the first time `last_seen_ns < now - 5min`; subsequent triggers within
the same outage are suppressed for 5 minutes to avoid alert spam, then
re-alerted at 5-minute intervals until recovery.

## 7. Backpressure

The shared queue is bounded at 10,000 records. Policy when full:

- Writer is responsible for draining at all times.
- If a feed's `queue.put_nowait()` raises `asyncio.QueueFull`, the feed
  drops the **oldest** record by calling `queue.get_nowait()` once and
  then retrying `put_nowait()`. The dropped record is counted in a
  process-wide `dropped_records` counter that the health aggregator
  reports.
- Recent ticks matter more than complete history for our use case
  (5-minute trading windows + 60s oracle heartbeat + Phase 3 walk-forward
  is OK with the occasional dropout). Disk I/O latency, not capture, is
  what we are protecting against.

In practice the queue should rarely exceed a few hundred items. If
`dropped_records` ever crosses 1,000 in a session that's a real
problem and the operator's daily check should catch it.

## 8. The `Feed` protocol and `Record` dataclass

Both live in `src/polymarket_bot/feeds/protocols.py` (NOT under `_live/`)
so paper-mode code in Phase 4 can import the protocol without dragging in
real WS clients. `import-linter` enforces this boundary. Sketch:

```python
# src/polymarket_bot/feeds/protocols.py
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

@dataclass(frozen=True, slots=True)
class Record:
    ts_utc_ns: int
    received_at_ns: int
    source: str       # "binance" | "coinbase" | "oracle" | "polymarket"
    kind: str
    payload_json: str

class Feed(Protocol):
    name: str  # one of the four source values

    async def stream(self) -> AsyncIterator[Record]:
        """Yield records until the underlying connection is shut down."""
        ...
```

Each concrete feed (Binance, Coinbase, Oracle, Polymarket) implements
`Feed`. Tests inject a `FakeWSClient` (defined in `tests/feeds/conftest.py`)
that yields recorded payloads at recorded timing. **No real network in
unit tests** — `pytest tests/ -q` runs cleanly with networking disabled
(rule #6 of the operating discipline).

## 9. Layer boundary

```
src/polymarket_bot/
├── feeds/
│   └── protocols.py          # Feed protocol, Record dataclass — paper + live both import this
├── _live/
│   ├── feeds/
│   │   ├── spot_binance.py
│   │   ├── spot_coinbase.py
│   │   ├── spot_aggregator.py
│   │   ├── oracle.py
│   │   └── polymarket.py
│   ├── storage.py
│   ├── health.py
│   └── runtime.py
└── resolver.py               # pure helpers, no I/O — paper + live both import this
```

`import-linter` rule "production never imports paper" already in
`.importlinter` (line 6-8) catches the inverse mistake. Phase 2 adds no
new linter contracts; the existing two are sufficient because:

- `feeds/protocols.py` is **outside** both `_live` and `_paper`, so both
  layers can import it without violating either contract.
- `resolver.py` is similarly outside both layers — pure functions, no I/O.
- All real-network code lives under `_live/feeds/` and is therefore
  caught by the existing forbidden-import contracts.

## 10. Failure surface — `_health` and `state/feeds_health.json`

Each feed maintains a private `_health: dict[str, int | float | str]`
updated on every message:

```python
self._health = {
    "name": "binance",
    "last_seen_ns": 0,        # int — time.time_ns() at last successful recv
    "msgs_seen": 0,           # int — monotonic counter
    "reconnects": 0,          # int — monotonic counter
    "last_error": "",         # str — empty string when healthy
}
```

`state/feeds_health.json` is rewritten every 30s by the health
aggregator. Atomic write: write to `state/feeds_health.json.tmp` then
`os.replace()` to the final name. Schema:

```json
{
  "snapshot_ts_utc_ns": 1715116800000000000,
  "snapshot_ts_utc": "2026-05-08T00:00:00Z",
  "queue_depth": 47,
  "dropped_records_total": 0,
  "feeds": {
    "binance":    {"last_seen_ns": ..., "lag_ms": 234,    "msgs_seen": 18234, "reconnects": 0, "healthy": true},
    "coinbase":   {"last_seen_ns": ..., "lag_ms": 1102,   "msgs_seen": 5421,  "reconnects": 1, "healthy": true},
    "oracle":     {"last_seen_ns": ..., "lag_ms": 41203,  "msgs_seen": 12,    "reconnects": 0, "healthy": true},
    "polymarket": {"last_seen_ns": ..., "lag_ms": 891,    "msgs_seen": 4231,  "reconnects": 0, "healthy": true}
  }
}
```

`lag_ms = (snapshot_ts_utc_ns - last_seen_ns) / 1_000_000`.

`healthy = lag_ms < threshold_ms` where:

| Feed | Healthy lag threshold |
|---|---|
| `binance` | 10s (5 msg/s expected) |
| `coinbase` | 30s (more bursty) |
| `oracle` | 180s (60s heartbeat + 2× margin; alerts trigger at 5min) |
| `polymarket` | 60s (book updates can be sparse on a slow window; conservative) |

Telegram alert fires when *any* feed has `lag_ms > 5*60_000` (5 minutes),
once per outage with 5-minute re-alerts.

Operator's monitoring command (documented in `runbooks/capture-launch.md`
in task 2.5):

```bash
cat state/feeds_health.json | jq
```

## 11. Polymarket window resolution (used by the polymarket feed)

The active 5m BTC up/down market is fully determined by clock arithmetic
from `MASTERPLAN.md` line 27:

```python
def active_window_ts(now_utc_s: int) -> int:
    return now_utc_s - (now_utc_s % 300)

def active_slug(window_ts: int) -> str:
    return f"btc-updown-5m-{window_ts}"
```

The polymarket feed runs an inner loop that:

1. At startup and at every 300-second boundary, computes
   `active_window_ts(time.time())` and the slug.
2. Issues `GET https://gamma-api.polymarket.com/events?slug=<slug>` to
   resolve the slug → token_id (or token_ids — there are two outcomes,
   UP and DOWN; we subscribe to both).
3. Caches the next window's resolution one window ahead so the rotation
   has zero gap.
4. On the WS connection, sends a `subscribe` message for the relevant
   `assets_ids` (the Polymarket WS payload shape — exact field name
   verified against the live endpoint or `agent-skills/websocket.md`
   when implementing).

**Edge case.** If the Gamma API does not yet have an event for the
current window (rare gap when Polymarket's market-creator script is late
spawning the window), the feed logs a structured "gamma-miss" line,
sleeps until the next 300-second boundary, and retries. It does NOT
crash; it does NOT poll Gamma in a tight loop. Test coverage for this
case is mandatory in `tests/feeds/test_polymarket.py`.

## 12. The resolver helper (Task 2.4)

`src/polymarket_bot/resolver.py` is two pure functions plus the two
window-arithmetic helpers above (which the polymarket feed and the
resolver share — both go in this file):

```python
from typing import Literal

def hypothetical_now(window_open_oracle: float, current_oracle: float) -> Literal["UP", "DOWN"]:
    """What does this market resolve as if it ended *right now*?

    Polymarket convention: ties resolve UP. We follow that — verified
    against an actual historical resolution if a fixture is available
    in references/Polymarket-BTC-15-Minute-Trading-Bot/.
    """
    return "UP" if current_oracle >= window_open_oracle else "DOWN"

def actual_resolution(window_ts: int, oracle_at_window_open: float, oracle_at_window_close: float) -> Literal["UP", "DOWN"]:
    """The real resolver. Uses oracle as of T+300, not now."""
    return "UP" if oracle_at_window_close >= oracle_at_window_open else "DOWN"
```

Both must be in code, named distinctly. Tests cover the boundary case
(`current_oracle == window_open_oracle` → `"UP"`) and a known historical
window from references if we find one.

## 13. New runtime dependencies

| Package | Why | Mode | Notes |
|---|---|---|---|
| `web3` | `eth_subscribe('logs')` for the Chainlink contract | runtime | Added via `uv add web3` in Task 2.2 |
| `websockets` | Raw WS client for Binance, Coinbase, Polymarket | runtime | Added via `uv add websockets` in Task 2.1 |
| `polars` | Parquet writer | runtime — promoted from dev | `uv add polars` in Task 2.4b |
| `pyarrow` | Underlying Arrow tables for Parquet | runtime — pulled in by polars | Same `uv add` |
| `httpx` | Polymarket Gamma API GET requests | runtime — promoted from dev | `uv add httpx` in Task 2.3 |

No env-var changes. `.envrc` is read-only per the prompt; we use defaults
for `BINANCE_WS_URL`, `COINBASE_WS_URL`, `POLYMARKET_WS_URL`,
`GAMMA_API_BASE`, `CHAINLINK_BTC_USD_AGGREGATOR` and an optional env-var
override pattern in code (`os.environ.get(KEY, DEFAULT)`).

## 14. Test discipline

Per anti-vibe rule #6 and the prompt's Task 2.x verification sections:

- Every concrete feed has a unit-test module under `tests/feeds/` that
  exercises the protocol against `FakeWSClient` — no real network.
- `tests/feeds/conftest.py` provides the `FakeWSClient` fixture and a
  small library of recorded payloads (one Binance trade, one Coinbase
  match, one synthetic Chainlink `AnswerUpdated` log, a Polymarket book
  snapshot + trade pair).
- Smoke tests against the real network are written as **manual scripts**
  that the developer runs from a fresh shell (60s for spot, 5min for
  oracle, 6min for polymarket). They are NOT in `tests/` and are NOT in
  CI. They produce evidence captured into `runbooks/gate-evidence/`.
- `pytest tests/ -q` must run with networking disabled (no implicit
  internet dep).

## 15. Header docstrings (rule #4 reminder)

Every new file under `src/`, `tests/`, `scripts/` ships with a
≥80-character one-paragraph header docstring. Files this phase creates:

- `src/polymarket_bot/feeds/__init__.py`
- `src/polymarket_bot/feeds/protocols.py`
- `src/polymarket_bot/_live/feeds/__init__.py`
- `src/polymarket_bot/_live/feeds/spot_binance.py`
- `src/polymarket_bot/_live/feeds/spot_coinbase.py`
- `src/polymarket_bot/_live/feeds/spot_aggregator.py`
- `src/polymarket_bot/_live/feeds/oracle.py`
- `src/polymarket_bot/_live/feeds/polymarket.py`
- `src/polymarket_bot/_live/storage.py`
- `src/polymarket_bot/_live/health.py`
- `src/polymarket_bot/_live/runtime.py`
- `src/polymarket_bot/resolver.py`
- `scripts/run_capture.py`
- `tests/feeds/__init__.py`
- `tests/feeds/conftest.py`
- `tests/feeds/test_spot_binance.py`
- `tests/feeds/test_spot_coinbase.py`
- `tests/feeds/test_spot_aggregator.py`
- `tests/feeds/test_oracle.py`
- `tests/feeds/test_polymarket.py`
- `tests/test_resolver.py`

## 16. Pre-flight evidence (gathered before this doc landed)

- `phase-1a-pass` tag exists at commit `1537a18` on branch
  `claude/bold-galileo-2d56ca`.
- `make verify` green at HEAD on the same branch (ruff ✅, mypy --strict
  ✅, 45 pytest pass ✅).
- `.envrc` contains all four `POLY_*` variables and the four Phase-0
  variables (`ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`,
  `POLYGON_RPC_URL`).
- `POLYGON_RPC_URL` already begins with `wss://` — the
  prompt's predicted swap from `https://` to `wss://` was pre-resolved
  by the operator. No `.envrc` edits required in this session.
- Chainlink BTC/USD aggregator on Polygon =
  `0xc907E116054Ad103354f2D350FD2514433D57F6f`. Operator verified via the
  prompt; final visual confirmation at
  https://data.chain.link/feeds/polygon/mainnet/btc-usd recommended
  before Task 2.2 commits oracle code.

## 17. Out of scope for this design doc

- The seven-day capture (Task 2.5 — operator-side launch).
- The oracle-behavior analysis script (Task 2.6 — next session).
- Phase 3 backtest replay over the captured Parquets.
- Any signing, funding, order placement, or signer-private-key path.
- Strategy logic, LLM agents, kill switches.

## 18. What success looks like at end-of-Phase-2-dev

When this design has been implemented through Task 2.4b and the runtime
has been launched in tmux for 90 seconds (Task 2.5):

```
$ cat state/feeds_health.json | jq '.feeds | to_entries | map({(.key): {msgs_seen: .value.msgs_seen, healthy: .value.healthy}}) | add'
{
  "binance":    {"msgs_seen": 450,  "healthy": true},
  "coinbase":   {"msgs_seen": 120,  "healthy": true},
  "oracle":     {"msgs_seen": 1,    "healthy": true},
  "polymarket": {"msgs_seen": 8,    "healthy": true}
}

$ ls -lh ticks/$(date -u +%F)/
binance.parquet     ~30 KB
coinbase.parquet    ~10 KB
oracle.parquet      ~1 KB
polymarket.parquet  ~5 KB
```

If those numbers are within an order of magnitude of the above and all
four `healthy` values are `true`, Task 2.5 commits the launch runbook,
writes `~/Desktop/phase-2-analysis-prompt.txt`, and the dev session ends.
The 7-day capture wall-clock then starts. The Phase 2 gate
(`runbooks/gates/phase-2.sh`) runs in the *next* session, against ≥ 7
dated directories, and decides whether the thesis survives.

---

**Locked.** Any change to schema (§4), layout (§5), reconnect policy (§6),
backpressure rule (§7), or `Feed` protocol shape (§8) requires a new
design-doc revision committed before the code change, per anti-vibe
rule #1.
