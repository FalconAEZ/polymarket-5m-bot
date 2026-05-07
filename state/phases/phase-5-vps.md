---
title: Phase 5 — VPS provisioning + 24h staging
status: in-progress (5.1/5.2/5.3/5.4 GREEN; 5.5 partial — grafana-agent live, alerter daemon = next chunk; 5.6/5.7 pending)
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
| 5.5 | Monitoring stack | ⏳ partial — design locked + grafana-agent live; alerter daemon code = next chunk | **Live now:** `runbooks/grafana-agent.yaml.template` (`fae32e5`); grafana-agent v0.44.2 pushing node-exporter metrics to `prometheus-prod-68-prod-eu-west-6.grafana.net` (3377+ samples sent, verified). **Next chunk:** `polymarket_bot.alerts` + `_live.alerter` per `design/alerter.md` (`15d8e48`); ~25 tests; `tg-alerter.service` deploy; halt-watcher in `run_paper.py`. End-to-end smoke = Telegram alert + `/halt`. |
| 5.6 | Move Signer key to VPS via `age` + SCP | ⏸ deferred (Phase 6 prereq) | Doesn't block 5.7 since paper mode doesn't sign orders. Locked decision #11: ONLY Signer goes to VPS, Funder NEVER. |
| 5.7 | 24-hour staging run | ⏸ blocked on 5.5 part 2 | Bot-staging clock IS already running (since 18:05:54 UTC) but the formal gate needs Telegram smoke + `/halt` smoke that 5.5 part 2 provides. |

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

## See also

- [[../runbooks/decision-18-revision]] — vault tracking model.
- [[../sessions/2026-05-07-vps-provisioned]] — instance provisioned (had wrong IP).
- [[../sessions/2026-05-07-phase-5.1-pass]] — 5.1 GREEN session note.
- [[../sessions/2026-05-07-phase-5.2-pass-5.3-blocked]] — 5.2 GREEN, 5.3 measured + blocked on operator A/B.
- [[../sessions/2026-05-07-phase-5.4-systemd-pass-5.5-design]] — 5.4 GREEN, 5.5 design locked.
- [[../sessions/2026-05-07-phase-5.5-chunk1-grafana-live]] — bot-staging live, grafana-agent pushing.
- `design/alerter.md` — locked architecture for Chunk 2 (next session).
- `runbooks/vps-ssh-lockdown.md`, `runbooks/systemd/README.md`, `runbooks/grafana-agent.yaml.template` — operational audit trail.
- `phase-prompts/phase-5-prompt.txt` — original engineered launch prompt (now mostly historical; this note + the latest session note + `design/alerter.md` are the live pickup spec).
