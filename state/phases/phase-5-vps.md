---
title: Phase 5 — VPS provisioning + 24h staging
status: in-progress (5.1 GREEN, 5.2-5.7 pending)
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

| # | Task | Status | Notes |
|---|---|---|---|
| 5.1 | SSH lockdown (port 2222, key-only, no root, UFW) | ✅ GREEN | Audit trail: [[../../runbooks/vps-ssh-lockdown|runbooks/vps-ssh-lockdown.md]]. Path B chosen (Any-IPv4 + layered auth). Ubuntu 24.04 socket-activation gotcha documented. |
| 5.2 | Install runtime (Python 3.11, uv, redis, chrony, litestream, build-essential) | ⏳ next | Runs `uv sync`; smoke must show 274 pytest pass on VPS. |
| 5.3 | **CLOB latency check (THE gate test for decision #2)** | ⏳ pending | Quick ICMP from VPS already shows avg 1.145ms / max 1.283ms / 0% loss to `ws-subscriptions-clob.polymarket.com` (Cloudflare-fronted). Formal Python WS handshake p99 < 15ms test in 5.3. |
| 5.4 | Two systemd units — `bot-staging.service` enabled, `bot.service` DISABLED until Phase 6 | ⏳ pending | Files committed to `runbooks/systemd/` for reproducibility. |
| 5.5 | Monitoring stack — node_exporter, Grafana Cloud, **`tg-alerter` Python service**, `/halt` inbound Telegram command | ⏳ pending | `tg-alerter` is new code → `design/alerter.md` first per anti-vibe rule #1. Bot ↔ alerter via Redis (rule #7 — decoupled). |
| 5.6 | Move Signer key to VPS via `age` + SCP | ⏳ pending | Locked decision #11: ONLY Signer goes to VPS, Funder NEVER. Encrypted transit; plaintext never leaves the laptop's encrypted keychain or the VPS's mode-0600 `.envrc`. |
| 5.7 | 24-hour staging run | ⏳ pending | 0 unhandled exceptions, 4 feeds healthy, `dropped_records_total == 0`, ≥1 Telegram smoke alert, `/halt` smoke works. |

## Phase 5 gate (`runbooks/gates/phase-5.sh` — to be written in 5.4)

Eight assertions:
1. `systemctl is-active bot-staging` == active
2. `systemctl is-enabled bot.service` == disabled
3. WS p99 latency last hour < 15ms (computed from metrics dump)
4. `chronyc tracking` offset < 10ms
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

- **#2 (Dublin VPS, sub-5ms to CLOB)** — VALIDATED so far. Quick ICMP shows 1.145ms; formal 5.3 gate next session.
- **#11 (Funder/Signer split)** — affects 5.6.
- **#14 (Budget tiers)** — $200/mo sustained, $24/mo Lightsail well under.
- **#15 (UTC everywhere)** — chrony in 5.2; offset < 10ms is part of phase-5 gate.
- **#17 (Polymarket gasless relayer)** — affects 5.5 monitoring (alerts on relayer errors).
- **#18 revised (vault → git for markdown)** — this note + the session note are vault content tracked in git.

## Postmortems / learnings

- *2026-05-07 phase 5.1 session* — wrong public IP in prior hand-off note (`108.130.237.88` vs actual `108.132.51.116`) cost ~30 min of debugging. Lesson: first-contact verification round (IMDSv2 `meta-data/`) before trusting hand-off facts.

## See also

- [[../runbooks/decision-18-revision]] — vault tracking model.
- [[../sessions/2026-05-07-vps-provisioned]] — instance provisioned (had wrong IP).
- [[../sessions/2026-05-07-phase-5.1-pass]] — 5.1 GREEN session note.
- `runbooks/vps-ssh-lockdown.md` — operational audit trail.
- `phase-prompts/phase-5-prompt.txt` — the engineered launch prompt for next-session pickup at 5.2.
