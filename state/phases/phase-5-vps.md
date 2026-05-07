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

## What's next (post-5.5 GREEN)

1. **Wait for the 24h staging clock.** bot-staging started 2026-05-07 19:32:54 UTC; gate-eligible 2026-05-08 19:32:54 UTC. The bot is on its own — no code work between now and then.
2. **At ~24h elapsed:** run `bash runbooks/gates/phase-5.sh` from the VPS. Gate criteria #1, #2, #3, #4, #5, #6 already pass; #7 (24h zero exceptions) and #8 (litestream) are the remaining checks. Litestream binary is installed but not yet configured — that's a small task to wire before tagging.
3. **Tag `phase-5-pass`** on green by hand at the commit that captures the gate evidence.
4. **Then 5.6 (Signer key)** — age-encrypt the Signer EOA, scp to VPS, decrypt into `.envrc` as `POLY_PRIVATE_KEY`. Locked decision #11 still in force (Funder NEVER leaves laptop). Doesn't unblock anything unless going to Phase 6.
5. **Then Phase 1B funding decision** — only if the operator looks at 7-14 days of paper-soak data and decides to flip live. Per anti-vibe rules, this gets its own gate, its own decision doc, its own incident-response plan. **Do not skip the soak.**

Honest reminder: the decision to go live is a separate gate from "infrastructure works." 5.5 GREEN means the kill-switch and observability work, not that the strategy makes money. The deterministic baseline at threshold 0.6 may go many windows without firing — that's not a bug, that's the strategy. Look at `state/staging/decisions/*.jsonl` over multiple days to see if any decisions actually fire AND settle in your favor before raising stakes.
