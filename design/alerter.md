# Design — `tg-alerter` service + alert producer + `/halt` sentinel (Phase 5.5)

> Purpose: lock the architecture for the operator-facing notification + remote
> kill-switch path that fires when the staging or live bot generates an alert
> or when the operator wants to stop the bot from anywhere via Telegram.
> Anti-vibe rule #1: this doc lands and locks before any code in
> `src/polymarket_bot/alerts/`, `src/polymarket_bot/_live/alerter/`, or
> `scripts/run_alerter.py`.
>
> Anchors:
> - `RUNBOOK.md` §"PHASE 5 — VPS Provisioning" — sub-task 5.5
> - `phase-prompts/phase-5-prompt.txt` — Task 5.5 (monitoring stack + tg-alerter)
> - `design/paper.md` (Phase 4) — runner shape + signal-handling model that the supervisor loop adds onto
> - `runbooks/systemd/README.md` (Phase 5.4) — the `bot-staging.service` unit this design extends with a sibling `tg-alerter.service`
> - locked decisions [#7 Telegram via BotFather], [#11 funder/signer split], [#15 UTC everywhere], [#17 gasless relayer] in `~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/project_decisions.md`
> - Phase 0 already configured `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in operator's `.envrc`; Phase 5.2 added them as required vars in the VPS `.envrc` skeleton
>
> Out of scope for this doc: full incident-response routing (one chat for now,
> per locked decision #7); rich Markdown formatting beyond plain text + bold;
> message templating per alert kind (covered in `formatter.py` impl); Grafana
> Cloud agent config (separate runbook in `runbooks/grafana-agent.md` once
> 5.5 monitoring lands).

---

## 1. The picture

```
                     +-------------------+
                     |  bot-staging      |
                     |  (Phase 5.4)      |
                     |                   |
                     |  publish(Alert)   |
                     |        |          |
                     +--------|----------+
                              v
                +---------------------------+
                | polymarket_bot.alerts     |   <-- producer side, top-level package
                | RedisAlertSink            |       (both _live and _paper import)
                +---------------------------+
                              |
                       LPUSH polybot:alerts
                              v
                     +-------------------+
                     |  Redis            |  <-- localhost:6379, durable queue
                     |  (Phase 5.2)      |
                     +-------------------+
                              |
                       BRPOP polybot:alerts
                              v
                     +-------------------+        Telegram Bot API
                     |  tg-alerter       | <----------------------+
                     |  (Phase 5.5)      |   getUpdates long-poll |
                     |                   |                        v
                     |  - drain queue    |              +------------------+
                     |  - format text    | <----------> | Telegram         |
                     |  - sendMessage    |  sendMessage |  (operator chat) |
                     |  - watch /halt    |              |                  |
                     +-------------------+              +------------------+
                              |
                              | on /halt from chat:
                              | atomic write
                              v
                     +-------------------+
                     | state/halt.       |   <-- sentinel file (presence = halt)
                     | sentinel          |       project tree, gitignored
                     +-------------------+
                              ^
                              | os.path.exists() check
                              | every 1s in supervisor loop
                              |
                     +--------|----------+
                     |  bot-staging      |
                     |  supervisor sets  |
                     |  stop_event;      |
                     |  graceful exit    |
                     +-------------------+
```

The bot and the alerter are **two separate processes in two separate systemd units**. They communicate exclusively through Redis (alerts) and a sentinel file (halt). No direct in-process coupling — locked decision #7 says Telegram is the operator surface; the alerter is the only component that talks to Telegram.

## 2. Module layout + import boundaries

```
src/polymarket_bot/
  alerts/                                  # producer side — public API for the bot
    __init__.py                            # re-exports Alert, AlertSink, NullAlertSink, RedisAlertSink
    types.py                               # @dataclass(frozen=True) Alert; Level enum
    protocols.py                           # AlertSink, Clock protocols
    null.py                                # NullAlertSink — drops everything; default in tests + backtest
    redis_sink.py                          # RedisAlertSink — LPUSH JSON onto polybot:alerts
  _live/
    alerter/                               # consumer side — runs in its own process
      __init__.py                          # tg-alerter package
      protocols.py                         # TelegramClient, RedisQueue protocols
      formatter.py                         # Alert -> human-readable text
      telegram_client.py                   # httpx-backed Telegram Bot API client
      redis_queue.py                       # redis-py-backed BRPOP wrapper
      halt.py                              # halt sentinel writer + reader (atomic)
      service.py                           # main loop: alert drain + getUpdates
scripts/
  run_alerter.py                           # CLI entry — uv run python -u scripts/run_alerter.py
```

**Import-linter compliance:** producer at `polymarket_bot.alerts.*` is top-level, so neither the existing `_paper -> _live` contract nor the `dashboard -> _live` contract is affected. Both `_live` and `_paper` are free to import `polymarket_bot.alerts`. The alerter consumer at `_live.alerter.*` is process-local (only `scripts/run_alerter.py` imports it); nothing in `_paper` will ever pull it.

## 3. Producer side — `polymarket_bot.alerts`

### 3.1. Types

```python
class Level(StrEnum):
    INFO = "info"      # heartbeats, window-rotate confirmations
    WARN = "warn"      # transient feed errors, gamma misses
    ERROR = "error"    # unhandled exception in a feed; bot keeps running
    CRITICAL = "critical"  # bot is shutting down or refused to start
```

```python
@dataclass(frozen=True)
class Alert:
    level: Level
    message: str            # plain text, ≤ 250 chars (Telegram limits + readability)
    ts_ns: int              # UTC ns; injected via Clock protocol; never wall-clock by accident
    source: str             # "bot-staging", "tg-alerter", "phase-6-bot"
    fields: Mapping[str, str | int | float] = field(default_factory=dict)  # structured ctx
```

### 3.2. AlertSink protocol

```python
class AlertSink(Protocol):
    def publish(self, alert: Alert) -> None: ...   # MUST NOT raise; MUST be sync
    def close(self) -> None: ...
```

- **Synchronous, never raises:** alerts are best-effort. A failed publish (Redis down, network partition) is logged and dropped; the bot's primary trading path must not block on observability.
- **Two implementations land in 5.5:** `NullAlertSink` (default in tests, backtest, dashboard) and `RedisAlertSink` (used by `run_paper.py` + Phase 6 `run_live.py`).

### 3.3. Wiring into `run_paper.py`

`run_paper.py` constructs the sink at startup based on `REDIS_URL` env var:

```python
sink: AlertSink = (
    RedisAlertSink(url=os.environ["REDIS_URL"], queue_key="polybot:alerts", source="bot-staging")
    if "REDIS_URL" in os.environ
    else NullAlertSink()
)
```

`REDIS_URL=redis://127.0.0.1:6379/0` lands in the staging `.envrc` (operator action — added to the skeleton in Phase 5.2's update). Default to `Null` so backtests, tests, and the dashboard never accidentally talk to a real Redis.

The PaperRunner takes `alert_sink: AlertSink` as a constructor param; today's runner calls `decision_log.write(...)` for every decision — 5.5 also calls `alert_sink.publish(...)` for `WARN`/`ERROR`/`CRITICAL`-level events only. `INFO` heartbeats stay in the decision log, not the alert stream — Telegram is for things the operator must see, not for routine traffic.

## 4. Halt sentinel contract

### 4.1. Filename + location

`/home/ops/polymarket-5m-bot/state/halt.sentinel` (project tree, under `state/` so the systemd `ReadWritePaths` is unchanged from 5.4). Gitignored — same line as `state/decisions/`. Operator's local repo can also use this for the dashboard or for ad-hoc kill via `touch state/halt.sentinel`.

### 4.2. Schema

The file is `JSON` for forward-compat (in case Phase 6 wants to encode "halt and cancel open orders" vs "halt without canceling"):

```json
{
  "halted_at_ns": 1761234567890123456,
  "halted_by": "telegram-/halt",
  "reason": "operator request"
}
```

Phase 5.5 only writes from `tg-alerter` on `/halt` from the chat. Phase 6 may add other writers (e.g., risk-limit breach in the live bot). The bot reads this file as **opaque presence** — JSON parse failure does NOT prevent halt; the file existing is sufficient signal.

### 4.3. Writer atomic-rename

```python
def write_halt_sentinel(reason: str, ts_ns: int) -> None:
    target = Path("state/halt.sentinel")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"halted_at_ns": ts_ns, "halted_by": "telegram-/halt", "reason": reason}))
    tmp.replace(target)   # POSIX atomic on same filesystem
```

This guarantees the bot never sees a half-written file: `.replace(...)` is `rename(2)` which is atomic on the same FS.

### 4.4. Reader supervisor loop in `run_paper.py`

`run_paper.py` already has a `stop_event = asyncio.Event()` driven by `SIGTERM`/`SIGINT`. Phase 5.5 adds one more trigger: a 1-second poll loop that calls `stop_event.set()` if the sentinel exists. Implementation lives next to the existing signal handlers:

```python
async def _halt_watcher(stop_event: asyncio.Event, sleep: SleepFn) -> None:
    sentinel = Path("state/halt.sentinel")
    while not stop_event.is_set():
        if sentinel.exists():
            LOG.info("halt sentinel detected; setting stop_event")
            stop_event.set()
            return
        await sleep(1.0)
```

`stop_event.set()` triggers the existing graceful shutdown (drain queue, close files). `_halt_watcher` is one of the tasks gathered in `main()`; same lifecycle as `_warmer`.

### 4.5. Why a file and not a Redis key

- File presence survives Redis restart (Redis persistence is RDB by default, not AOF; a Redis crash + restart could drop a freshly-set kill key).
- `os.path.exists()` is ~µs and never raises in steady state. The supervisor loop is on the runner's hot path; we don't want it making a Redis round-trip every second.
- The halt mechanism must work even if Redis is the *thing that's broken*.

## 5. Consumer side — `tg-alerter` daemon

### 5.1. Two concurrent loops, one process

```python
async def main(...) -> int:
    stop = asyncio.Event()
    register_signal_handlers(stop)
    drain_task = asyncio.create_task(_drain_alert_queue(redis_q, telegram, stop))
    poll_task  = asyncio.create_task(_poll_telegram_for_halt(telegram, halt_writer, stop))
    await stop.wait()
    drain_task.cancel(); poll_task.cancel()
    await asyncio.gather(drain_task, poll_task, return_exceptions=True)
    return 0
```

- `_drain_alert_queue`: `BRPOP polybot:alerts 30` (30 s timeout) → format → `sendMessage`. On Telegram error: log + push back onto a `polybot:alerts:dlq` list (dead-letter, capped at 1000 entries — circular).
- `_poll_telegram_for_halt`: `getUpdates?offset=...&timeout=25` long-poll. On message text exactly `/halt` from `TELEGRAM_CHAT_ID`: write sentinel, reply "halt sentinel set; bot will exit on next 1s tick" to the chat.

### 5.2. Why `sendMessage` over a webhook

- Webhook needs a public TLS endpoint; we only opened SSH:2222 in 5.1. A second listener is more attack surface for a one-line feature.
- Long-poll is bounded by Telegram (25 s `timeout` parameter), idle-cheap (~zero bandwidth between polls), and trivially restartable.

### 5.3. Rate limit + de-duplication

- Telegram bot API: 30 messages/sec per bot, 1 per chat per second sustained.
- `_drain_alert_queue` enforces a sliding-window rate limiter (token bucket, 1 msg/sec to chat). Burst of alerts compresses into a single message via in-memory coalesce: if ≥ 3 alerts arrive in the bucket window, the message becomes `"3 alerts in 5s — see decision log"`.
- `INFO`-level alerts are dropped at the alerter (formatter returns `None`), not just unsent. The producer logs the publish at INFO, but the operator never sees it on Telegram.

### 5.4. Stochastic injection (anti-vibe rule #10)

The service constructor takes:
- `redis_q: RedisQueue` — the protocol that BRPOPs JSON
- `telegram: TelegramClient` — the protocol that exposes `send_message(text)` and `get_updates(offset)`
- `halt_writer: Callable[[str, int], None]` — write atomic sentinel
- `clock_ns: ClockNs` — current UTC ns

In tests, all four are fakes. In production, real impls back them. No `import redis` or `import httpx` outside the `redis_queue.py` / `telegram_client.py` modules.

## 6. Systemd: `tg-alerter.service` (sibling to `bot-staging.service`)

Lands in `runbooks/systemd/tg-alerter.service` and follows the same shape as `bot-staging.service`:

```ini
[Unit]
Description=Polymarket bot — Telegram alerter + /halt watcher (Phase 5.5)
After=network-online.target redis-server.service
Wants=network-online.target redis-server.service

[Service]
Type=simple
User=ops
Group=ops
WorkingDirectory=/home/ops/polymarket-5m-bot
ExecStart=/bin/bash -c 'source /home/ops/polymarket-5m-bot/.envrc && exec /home/ops/.local/bin/uv run python -u scripts/run_alerter.py'
Restart=on-failure
RestartSec=15
TimeoutStopSec=15
KillSignal=SIGTERM
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
```

Enable and start are independent of `bot-staging.service` — the alerter is useful even when the bot is paused (operator sees the "bot stopped" message).

## 7. Failure modes + recovery

| Mode | What happens | Recovery |
|---|---|---|
| Telegram API down | `sendMessage` 5xx → push to `polybot:alerts:dlq` (capped FIFO) | On API recovery, drain DLQ |
| Redis crash | `BRPOP` raises `ConnectionError` → reconnect with exponential backoff (max 30 s) | Once Redis is back, BRPOP resumes; published alerts during outage are lost (acceptable per rule "publish must not block trading") |
| Telegram token revoked | Repeated 401 from API → log CRITICAL (to journal, not Telegram!) and exit; systemd restarts every 15 s; operator sees the unit flapping in `journalctl -u tg-alerter` | Operator regenerates token, updates `.envrc`, restarts unit |
| `/halt` from wrong chat | `chat_id != TELEGRAM_CHAT_ID` → silently ignored. Logged at INFO. | n/a |
| Sentinel file already exists at startup | bot won't start; supervisor sets `stop_event` immediately. Operator removes file with `rm state/halt.sentinel` to allow restart. | Manual rm |
| Bot crashed without removing sentinel | Same as above | Manual rm before `systemctl start bot-staging` |

## 8. Tests (anti-vibe rule #2 + #10)

- `tests/alerts/test_redis_sink.py` — RedisAlertSink LPUSHes correct JSON; never raises on connection error (logs + drops).
- `tests/alerts/test_null_sink.py` — NullAlertSink is a no-op; passes mypy.
- `tests/_live/alerter/test_formatter.py` — Alert → text shape; INFO returns None; CRITICAL prefixes "🚨 CRITICAL"; coalesce path triggers ≥ 3.
- `tests/_live/alerter/test_drain_loop.py` — fake RedisQueue + fake TelegramClient; drains 5 alerts; on Telegram 5xx pushes to DLQ; rate-limit sleeps 1 s between bursts.
- `tests/_live/alerter/test_halt_loop.py` — fake TelegramClient yields `/halt` from correct chat → halt_writer called; from wrong chat → not called.
- `tests/_live/alerter/test_halt_sentinel.py` — atomic write + presence check; partial-write recovery (kill mid-write does not leave a corrupt file).
- `tests/_paper/test_supervisor_halt.py` — paper runner exits cleanly when sentinel appears mid-run.

Estimated +25 tests. Total post-5.5: ~300 pytest passes; mypy --strict 43+5 src files clean; lint-imports stays at 3/3 KEPT (no new contracts needed — the `_live/alerter` consumer module is process-local).

## 9. What lands in 5.5 vs deferred

**5.5 (this design's deliverables):**
- `polymarket_bot.alerts` package + 2 sinks
- `polymarket_bot._live.alerter` daemon + `scripts/run_alerter.py`
- `runbooks/systemd/tg-alerter.service` (committed + deployed)
- Halt sentinel + supervisor wiring in `run_paper.py`
- ≥ 25 new tests + design conformance under `make verify`
- Operator: signs up for Grafana Cloud free tier; pastes Prometheus remote_write URL into `.envrc` (`GRAFANA_PROM_URL`, `GRAFANA_PROM_TOKEN`); installs grafana-agent; commits its config to `runbooks/grafana-agent.yaml`. **This is the only operator-action gate in 5.5.**

**Deferred (out of scope here):**
- Bot-side Prometheus `/metrics` endpoint — Phase 5.5 sub-deliverable in its own design (`design/metrics.md`) once we know which counters/gauges/histograms matter to the dashboard.
- Per-message freshness-lag metric (driven by RUNBOOK §5.3 revision 2026-05-07) — same future design.
- Multi-chat fan-out, severity-based routing, on-call rotation — Phase 8 if ever.

## 10. Decisions locked by this doc

- **Producer/consumer split:** bot publishes via top-level `polymarket_bot.alerts`; alerter daemon at `_live/alerter`. No direct in-process coupling.
- **Redis `LIST` queue, not pub/sub:** durability across alerter restarts (BRPOP is destructive but the message wasn't lost).
- **Halt = file sentinel, not Redis:** must work when Redis is the broken thing.
- **Telegram getUpdates long-poll, not webhook:** no extra public listener.
- **`INFO` alerts stay in decision log; only `WARN+` go to Telegram.** Telegram is for "operator must see," not for ambient state.
- **Sentinel file is opaque presence:** JSON parse failure still halts. Keep it impossible to write a sentinel that the bot ignores.

Reopen these only with a written justification per CLAUDE.md "anti-vibe-coding rules — enforce without exception."
