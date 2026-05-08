---
title: Phase 5 — VPS provisioning + 24h staging
status: in-progress (5.1/5.2/5.3/5.4/5.5 GREEN; 5.6 deferred to Phase 6 prep; 5.7 24h soak ticking, gate-eligible 2026-05-08 19:32:54 UTC)
tags: [phase, vps, ops, lockdown, staging]
---

# Phase 5 — VPS provisioning + 24h staging

> Move the bot from the operator's laptop (where Phase 4 paper-mode died on laptop sleep) to a dedicated AWS Lightsail VPS in Dublin (eu-west-1) — sub-5ms to Polymarket CLOB, 24/7 uptime, real systemd, real monitoring, real staging environment. **Last gate before real money** (Phase 6).

Phase 5 sits between paper trading (Phase 4 ✅ closed) and real-money go-live (Phase 6 ⏸ parked behind Phase 1B). Closes when 5.7's 24-hour staging run is clean.

## Why this phase exists

Phase 4's 14-day paper run on the Mac died because the laptop slept. That single-machine failure mode is unacceptable for Phase 6 real-money trading. Plus Phase 6 needs:
- **Sub-5ms** path to CLOB (locked decision #2 — Dublin).
- **Stable static IP** for Telegram webhooks + Grafana scrape + dashboard sync.
- **24/7 process supervisor** (systemd, not nohup).
- **Out-of-band kill switch** (`/halt` Telegram command).
- **Time sync** for windowed trading logic (chrony, locked decision #15).
- **Replicated state** (litestream → Backblaze B2 for trades.db; resolves OD-2).
- **Single-purpose host** that the operator's laptop slips/sleeps/screenshots can't disturb.

## Provisioning facts

Confirmed at the start of session 2026-05-07-phase-5.1-pass (corrected from the prior session's hand-off):

| | |
|---|---|
| Provider | AWS Lightsail |
| Region / AZ | `eu-west-1` / `eu-west-1a` (Ireland / Dublin) — IMDSv2 verified |
| Instance | `5m-Polymarket-bot` (Ubuntu 24.04.4 LTS, x86_64) |
| Plan | $24/mo · 2 vCPU · 4 GB RAM · 80 GB SSD · 4 TB transfer · IPv4+IPv6 |
| Public IPv4 | `108.132.51.116` (static `StaticIp-1`) |
| SSH | port 2222, key-only, `ops` user, no root, no password |
| Snapshots | disabled (~$4/mo extra; revisit after 5.7 closes) |

Cost reality check: the original RUNBOOK §"PHASE 5" said "$5/mo" — that was wrong. The $5 plan is 2vCPU/512MB which would bottleneck on RAM (paper + dashboard + prometheus). $24/mo plan is right; locked decision #14's $200/mo sustained-OPEX budget covers Phase 5+6 comfortably.

## Tasks

| # | Task | Status | Evidence |
|---|---|---|---|
| 5.1 | SSH lockdown (port 2222, key-only, no root, UFW) | ✅ GREEN @ `13cb807` | `runbooks/vps-ssh-lockdown.md`. Path B (Any-IPv4 + layered auth). Ubuntu 24.04 socket-activation gotcha documented. |
| 5.2 | Install runtime (Python 3.11.15, uv 0.11.11, redis, chrony 0.0038ms offset, litestream 0.5.11) | ✅ GREEN @ `8ff5920` | 274 pytest in 6.76 s on VPS (5× faster than Mac); mypy --strict 43 files clean; lint-imports 3/3 KEPT. **NB: phase-5 prompt's litestream URL was wrong** (404 — naming changed in v0.5.x). |
| 5.3 | CLOB latency check | ✅ measured + gate revised (Option B) @ `15d8e48` | `runbooks/gate-evidence/phase-5.3-latency.txt`, `runbooks/incidents/2026-05-07-clob-latency-gate-analysis.md`. Network-layer 1–2 ms verified; app-layer 13–17 ms structural Cloudflare→origin proxy hop (region-independent). RUNBOOK §5.3 + decision #2 updated to reflect achievable thresholds (`subscribe→first-msg p50<20ms p99<30ms`). |
| 5.4 | Two systemd units | ✅ GREEN @ `15d8e48` | `runbooks/systemd/{bot-staging,bot}.service` + README. `bot-staging` enabled+running since 18:05:54 UTC; `bot.service` disabled (`ConditionPathExists` guards Phase 6). Smoke-test 8 s active → graceful SIGTERM stop. **First-attempt hardening** `ProtectHome=read-only` blocked uv cache writes; relaxed to `ProtectSystem=full`. |
| 5.5 | Monitoring stack | ✅ GREEN @ `90608cb` (chunks 1+2) | **Chunk 1** (`fae32e5`): grafana-agent v0.44.2 pushing node-exporter to `prometheus-prod-68-prod-eu-west-6.grafana.net`. **Chunk 2** (`6713b97`): `polymarket_bot.alerts` producer + `_live.alerter` consumer + `tg-alerter.service` + halt-watcher in `run_paper.py`. **30 new tests** (304 → 307 after the regression fix). **2 bugs caught + fixed during smoke:** `b932361` BRPOP `socket_timeout` < BRPOP server timeout caused noisy reconnects (regression test added); `6713b97` httpx INFO logged Telegram bot token URL to journal. **Operator-confirmed e2e smoke:** Telegram CRITICAL delivered → operator typed `/halt` → bot exited within ~1s with alerter ack message; sentinel removed + bot restarted clean at 19:32:54 UTC. |
| 5.5+ | Staging-mode dashboard | ✅ shipped @ `dda29dd` | `make sync-staging` rsyncs VPS state into `state/staging/`; `make dash-staging` opens existing Phase 4.5 dashboard pointed at the mirror (port 8503). Zero changes to `scripts/dashboard.py` — pure glue. Caveats documented in `runbooks/staging-dashboard.md` (PROCESSES panel reads local PIDs, FEEDS msgs_seen always 0; both fixed when Prometheus metrics land). |
| 5.6 | Move Signer key to VPS via `age` + SCP | ⏸ deferred (Phase 6 prereq) | Doesn't block 5.7 since paper mode doesn't sign orders. Locked decision #11: ONLY Signer goes to VPS, Funder NEVER. |
| 5.7 | 24-hour staging run | ⏳ ticking; gate-eligible 2026-05-08 19:32:54 UTC | bot-staging.service active since 2026-05-07 19:32:54 UTC. Telegram smoke + `/halt` smoke already passed (criteria #5+#6 from gate). Remaining: 24h clean uptime (#7) + litestream (#8). At 24h, run gate audit script + tag `phase-5-pass`. |

## Phase 5 gate (`runbooks/gates/phase-5.sh` — written alongside 5.5 part 2)

Eight assertions (criterion #3 revised 2026-05-07 per Option B / `runbooks/incidents/2026-05-07-clob-latency-gate-analysis.md`):
1. `systemctl is-active bot-staging` == active
2. `systemctl is-enabled bot.service` == disabled
3. WS `subscribe → first-message` p50 < 20ms AND p99 < 30ms (was `p99 < 15ms`; revised — see incident analysis). Bot also exports per-message freshness-lag (server timestamp → local recv) as Prometheus metric for ongoing operational SLO.
4. `chronyc tracking` offset < 10ms (currently 0.0038 ms, ~2600× under)
5. Telegram smoke alert received
6. `/halt` smoke works
7. 24h staging logs: 0 unhandled exceptions
8. litestream replicating `trades.db` to chosen S3-compatible target (resolves OD-2; default Backblaze B2)

Tag `phase-5-pass` by hand on green. Phase 6 (real money) gates next, blocked behind Phase 1B (real-money funding).

## Hard limits

- Cumulative Anthropic spend so far: **$0.405** (Phase 3 only). Phase 5 adds **$0** in API.
- AWS recurring: $24/mo Lightsail. AWS Billing → Budgets alarm at $30/mo (set this if not already done).
- **Phase 1B (real money) STILL parked.** The Signer key transferred in 5.6 is for Phase 6 staging readiness; `bot.service` stays DISABLED until Phase 6 gate.
- **Funder key NEVER goes to the VPS.** Only Signer (locked decision #11). Funder lives on the laptop's encrypted keychain until $2k bankroll triggers hardware wallet (locked decision #12).

## Locked decisions in play this phase

- **#2 (Dublin VPS, sub-5ms to CLOB)** — REVISED 2026-05-07 with measured numbers: network-layer (ICMP/TCP to Cloudflare edge) IS sub-5 ms verified; app-layer (real Polymarket protocol RTT) is 13–17 ms structural floor, region-independent. Acceptable for 5-min bar strategy. The original "5 ms" was an ICMP-to-edge read misinterpreted as app RTT.
- **#11 (Funder/Signer split)** — affects 5.6.
- **#14 (Budget tiers)** — $200/mo sustained; $24/mo Lightsail + Grafana Cloud free tier well under.
- **#15 (UTC everywhere)** — chrony offset 0.0038 ms; far inside the <10 ms gate.
- **#17 (Polymarket gasless relayer)** — affects 5.5 alerter (alerts on relayer errors).
- **#18 revised (vault → git for markdown)** — this note + session notes are vault content tracked in git.

## Postmortems / learnings

- *2026-05-07 phase 5.1 session* — wrong public IP in prior hand-off note (`108.130.237.88` vs actual `108.132.51.116`) cost ~30 min of debugging. Lesson: first-contact verification round (IMDSv2 `meta-data/`) before trusting hand-off facts.
- *2026-05-07 phase 5.3 session* — gate criterion was based on a flawed measurement (ICMP-to-edge → "5 ms to CLOB"); real app-layer RTT is structurally 13–17 ms. Lesson: **measure what the bot actually does**, not a proxy. Revised gate uses `subscribe → first-message` (real protocol exchange) instead of WS handshake or PING/PONG. New feedback memory: `feedback_pragmatic_gate_revision.md` — when a locked gate is structurally unmeetable due to flawed original measurement, prefer documented revision + advance over rigid retry.
- *2026-05-07 phase 5.4 session* — `ProtectHome=read-only` in initial systemd unit blocked uv's cache writes at `~/.cache/uv`. Lesson: ops-user isolation is the security boundary on a single-tenant VPS; in-home write isolation creates more friction than it prevents.
- *2026-05-07 phase 5.5 chunk 1 session* — operator screenshotted `.envrc` mid-edit, exposing live Alchemy + Telegram tokens to chat. Neither key controls funds; rotate after Phase 5 closes. Lesson: when guiding `nano` editing in chat, request structure-only verification (`grep -c`, `bash -n`) rather than file dumps.
- *2026-05-07 phase 5.5 chunk 2 session — `redis-py` socket_timeout footgun.* Setting `socket_timeout=5.0` on the BRPOP client makes the socket-read deadline fire BEFORE BRPOP's server-side `timeout=30` returns, raising `redis.exceptions.TimeoutError` and ratcheting the reconnect backoff. The generic `RedisError` branch caught it and emitted a noisy WARN every cycle. Fix: drop `socket_timeout`, add `health_check_interval=30`, catch `RedisTimeoutError` → return `None`. Regression test added. Lesson: when a library has TWO timeout layers (transport vs protocol), the transport one MUST be larger than the protocol one or you convert "queue empty" into "connection error".
- *2026-05-07 phase 5.5 chunk 2 session — `httpx` INFO logs leaked Telegram bot token to journal.* httpx logs every HTTP request URL at INFO. The Telegram Bot API embeds the token in the path, so each `getUpdates` long-poll wrote the bare token to `journalctl -u tg-alerter`. Fix: `logging.getLogger("httpx").setLevel(WARNING)` in `run_alerter._configure_logging`. Past journal lines cannot be redacted; pre-existing token-rotation reminder still applies. Lesson: always set httpx (and any HTTP-client) logger to WARNING in production daemons that hit token-bearing URLs.
- *2026-05-07 phase 5.5 chunk 2 session — pre-commit ruff (v0.8.0) ≠ local ruff (0.15+).* Local ruff has `ASYNC240` (no `pathlib.Path` in async); pre-commit ruff doesn't, so a `# noqa: ASYNC240` parses as `RUF100 unused noqa` in pre-commit. Worked around by lifting the `os.path.exists` call into a sync `_sentinel_present` helper outside the async function — clean for both versions, no `# noqa` needed. Long-term: bump pre-commit ruff or pin local to match. Filed as icebox follow-up.
- *2026-05-08 framing pushback — operator excitement vs scope reality.* After 5.5 closed, operator asked "did we just build a high-volume Bonereaper-clone using the Claude API?" — answer was **no**: locked decision #19 archived Bonereaper after the 52.65% backtest; `bot-staging` runs `DeterministicStrategy` only (one $5 bet per 5-min window, threshold ≥0.6 composite); Phase 3 LLM A/B verdict was CUT (decision #16); no Anthropic spend in chunks 1+2. The 3-agent + Sonnet-meta ensemble is **designed** (decision #5), not coded. Lesson: when a stakeholder asks an enthusiastic-but-wrong question, mark them. Distinguishing "shipped infra + baseline" from "shipped Bonereaper-clone" matters when friends and family are watching.
- *2026-05-08 Bonereaper investigation chain — three hypothesis turns.* Operator's "they enter every window for high win rate" prompted three sequential investigations: (1) MARKET MAKING hypothesis, killed by predicts.guru `BUY/SELL RATIO 5000/0` (they never close early); (2) LATE-WINDOW SNIPING hypothesis, killed by microstructure data showing only 15.4% of >=70¢ entries land in the final 60s (replicated at 7d=60,500 trades and 30d=306,997 trades — same answer); (3) SPOT-AWARE SIDE SELECTION hypothesis, **CONFIRMED** at 30d/306,966 trades with a +30.9pp aligned-vs-contrarian win-rate gap. Lessons: (a) sample-size variance is huge — initial 837-trade sample showed +52.8pp gap that shrank to +30.9pp at scale; trust the bigger sample. (b) "Win rate" framing was misleading — net 51.7% is barely coin-flip; money comes from layered PnL drivers (heavy-favorite concentration, low-price mean-reversion, flat-condition fair-price bets) NOT from the clean directional cells where the book mostly catches up. (c) Operator's "every window" instinct was right on COVERAGE (Bonereaper hits 95.1% of 8,637 markets in 30d) but wrong on the implied "high accuracy." High-volume CAN work, but only with a real per-trade signal — which Δ_bps from window-open looks like.
- *2026-05-08 replay calibration — signal-too-quiet, not threshold-too-tight.* Operator pushed for "every window" trading driven by frustration that bot-staging fires nothing. Replay sweep at thresholds {0.3, 0.4, 0.5, 0.6} on 28 windows of captured BTC ticks → ZERO fires at every threshold. The deterministic composite signal itself doesn't cross 0.3pp on real 5-min BTC data; lowering the threshold doesn't add signal. Implication: decisions #16 (LLM A/B cut "didn't beat baseline by 3pp") and #19 (Bonereaper cloning aborted) BOTH rest on a baseline that fires zero times — those decisions need fresh written justification before any reversal. Lesson: when the dashboard looks empty, the diagnostic question is "what is the signal actually outputting?" — not "should we lower the threshold?".
- *2026-05-08 leaderboard scout — high win rate is a TRAP without price-tier discipline.* Built `scripts/research/leaderboard_scout.py` to find small-equity wallets crushing BTC 5m. Top two scout survivors (Slow-Minute $4.5k equity, 97.8% scout WR; `0x88f1` $1.1k equity, 98.4% scout WR) both LOOKED like the dream template. Deep 7-day microstructure showed BOTH are NET-LOSING (Slow-Minute -$3,964; 0x88f1 -$186). They win 95%+ of trades but bleed money because they only buy heavy favorites at 95-99¢ implied prob — at those prices, 96.6% accuracy doesn't clear the cost basis (need ≥97.6% just to break even before fees). However, **spot-Δ alignment pattern reproduces across all 3 wallets** (Slow-Minute aligned 98.6%, 0x88f1 92.9%, Bonereaper 91.7% on their respective 85-100% tiers) — robust signal. **The discipline gap separating Bonereaper (winner) from Slow-Minute (bleeder) is price-tier mix, not signal awareness.** Lessons: (a) "win rate" is a misleading single-number summary on binary markets at high implied probability; rank by per-$ PnL. (b) The scout works as a filter but per-$ PnL column needs a full per-wallet verification pass to be trustworthy at small sample sizes. (c) For our future strategy, encode an explicit EV check: refuse trades where `(entry_price + fees) > (estimated_win_prob × $1)`. See `runbooks/research/scout-final-comparison-2026-05-08.md`.

## See also

- [[../runbooks/decision-18-revision]] — vault tracking model.
- [[../sessions/2026-05-07-vps-provisioned]] — instance provisioned (had wrong IP).
- [[../sessions/2026-05-07-phase-5.1-pass]] — 5.1 GREEN session note.
- [[../sessions/2026-05-07-phase-5.2-pass-5.3-blocked]] — 5.2 GREEN, 5.3 measured + blocked on operator A/B.
- [[../sessions/2026-05-07-phase-5.4-systemd-pass-5.5-design]] — 5.4 GREEN, 5.5 design locked.
- [[../sessions/2026-05-07-phase-5.5-chunk1-grafana-live]] — bot-staging live, grafana-agent pushing.
- [[../sessions/2026-05-07-phase-5.5-chunk2-pass]] — alerter daemon shipped; e2e Telegram + `/halt` smoke confirmed by operator; 5.5 GREEN.
- `design/alerter.md` — locked architecture for Chunk 2 (now implemented).
- `runbooks/vps-ssh-lockdown.md`, `runbooks/systemd/README.md`, `runbooks/grafana-agent.yaml.template`, `runbooks/staging-dashboard.md` — operational audit trail.
- `phase-prompts/phase-5-prompt.txt` — original engineered launch prompt (now mostly historical; this note + the latest session note are the live pickup spec).

## What's next (post-5.5 GREEN, updated 2026-05-08 after Bonereaper investigation)

### Tomorrow's 24h gate (~2026-05-08 19:32:54 UTC) — realistic expectations

| # | Criterion | Expected status |
|---|---|---|
| 1 | bot-staging active | ✅ pass |
| 2 | bot.service disabled | ✅ pass |
| 3 | WS subscribe→first-msg latency | ✅ pass (measured in 5.3) |
| 4 | chrony offset <10ms | ✅ pass |
| 5 | Telegram smoke | ✅ pass (operator-confirmed) |
| 6 | /halt smoke | ✅ pass (operator-confirmed) |
| 7 | 24h logs zero unhandled exceptions | ✅ probable pass (clean so far) |
| 8 | litestream replicating trades.db | ❌ NOT WIRED — only blocker |

**Decisions fired during 24h soak: expected ZERO.** The replay calibration showed the deterministic composite never crosses 0.3pp on real 5-min BTC tick data. Live behaviour will reproduce that. The dashboard will read "CUMULATIVE PNL —, silence is normal at 0.6pp threshold." That's NOT a gate failure (#7 is about exception-free uptime, not profitable trades) but it IS the strategy-design problem we now have evidence to solve.

### Path to phase-5-pass tag

1. Wire litestream → Backblaze B2 bucket (or equivalent S3-compatible) + systemd timer + restore-test. Gate criterion #8 satisfied. ~1h work.
2. At 24h elapsed, run `bash runbooks/gates/phase-5.sh` to capture evidence; confirm criteria #7 and #8 land.
3. Tag `phase-5-pass` by hand on green.

### Strategy track (parallel to gate work; NOT a Phase 5 deliverable)

Driven by the 2026-05-08 Bonereaper investigation chain. Both findings tracked under `runbooks/research/`:

- `runbooks/gate-evidence/replay-calibration-2026-05-08.md` — deterministic composite fires zero times at any threshold on real ticks. Signal-too-quiet, not threshold-too-tight.
- `runbooks/research/bonereaper-microstructure-2026-05-07.md` (7d, 60,500 trades) and `bonereaper-microstructure-30d-2026-05-08.md` (30d, 306,997 trades) — late-window-sniping rejected; 95.1% market participation; layered PnL drivers.
- `runbooks/research/bonereaper-spot-vs-book-2026-05-07.md` (7d, 837 trades, +52.8pp gap) and `bonereaper-spot-vs-book-30d-2026-05-08.md` (30d, 306,966 trades, **+30.9pp gap**) — spot-aware side selection signal CONFIRMED at scale.

What this enables when ready:

1. **`design/spot_aware_strategy.md`** — locked design for a sibling strategy to `DeterministicStrategy`. Trigger: |Δ_bps| ≥ X with side-aligned sign. Evaluation: same buckets the bonereaper analysis used. Anti-vibe rule #1: doc + gate before any code.
2. **Backtest gate** — replay over captured + historical kline data, score per-bucket against the bonereaper benchmark (1.94% gross ROI / 51.7% win rate / +30.9pp aligned-vs-contrarian gap).
3. **Phase 8 ensemble re-audit** — decisions #16 (LLM A/B cut) and #19 (Bonereaper aborted as directional) BOTH rest on "the deterministic baseline" being well-defined. The baseline fires zero times. Both decisions deserve fresh written justification before any change to the locked store.
4. **Eventual paper integration** — sibling strategy fed the same events as `DeterministicStrategy`; both write to `state/decisions/`; dashboard renders side-by-side. Operator picks the live strategy after a fresh paper soak.

### Operational housekeeping (not blocking)

- 5.6 (Signer key) — operator deferred until ready to flip live. No urgency.
- Phase 1B funding — only after a strategy that fires AND passes a fresh gate.
- Token rotations (Telegram + Alchemy) — operator deferred until Phase 5 closes.

### Honest reminders (carry forward)

- 5.5 GREEN means the kill-switch and observability work, not that the strategy makes money.
- The current deterministic baseline at threshold 0.6 fires zero times in real data. Lowering the threshold without changing the signal still fires zero times.
- Bonereaper's 30-day numbers prove **high volume × tiny edge × selective sizing CAN work** — but their net win rate is 51.7%, not "high." Don't confuse "trade every window" with "trade every window with no edge."
- Each addition (spot-aware strategy, Claude ensemble, ensemble revisit) gates separately. Anti-vibe rule #1 still in force.
