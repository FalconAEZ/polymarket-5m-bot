# Session — VPS provisioned + repo finalized for migration (2026-05-07 late)

## What shipped this session

**Two big workstreams closed:**

### 1. GitHub repo finalized for cross-machine work
- **`main` branch fast-forwarded** from `phase-0-pass` (56a44ca) → latest (~b4d8890). Was 33 commits behind; default branch on GitHub now reflects everything. Fresh `git clone` lands on the latest.
- **Full Obsidian vault committed** to git. Previously the bot's runtime `state/` was tracked as a target, but the user's actual vault content (50 files: concepts, postmortems, phases, research, sessions, runbooks, README, Untitled.canvas, bonereaper-postmortem.md, token_side_index.json) lived in the **main repo's** `state/` and was untracked because of a bug in the previous gitignore rule (`state/` excluded the directory entirely; per git docs `!state/sessions/` cannot un-include from an excluded parent). Rewrote `.gitignore` to exclude only specific machine-local patterns (`*.log`, `*.pid`, `feeds_health.json`, `.obsidian/`, `state-demo/`, `.DS_Store`) and let everything else track. Commit `566f490`. Total +70MB; biggest file is `state/research/bonereaper/weekly_trades_2026-05-06.json` at 42MB. Acceptable for git; flagged as git-lfs candidate if repo size becomes an issue.
- **Locked decision #18 revised**: vault markdown (sessions/postmortems/runbooks) → git; runtime ephemeral state stays gitignored. Audit trail at `state/runbooks/decision-18-revision.md`. `memory/project_decisions.md` updated.
- **`phase-prompts/` folder committed** (commit `b4d8890`) — 6 engineered session-launch prompts the operator wrote for each phase, with a README indexing what each was for and which commit/tag it produced.
- **`RESUME-WINDOWS.md`** at repo root — the cross-machine pickup prompt, polished version of the earlier `~/Desktop/.txt`.
- **`runbooks/obsidian-setup.md`** — install Obsidian on Windows + open the vault + recommended settings.
- **`runbooks/windows-pc-setup.md`** — irreducible "human only" Windows manual setup steps (Git, Python 3.11, uv, .envrc, Obsidian, optional VS Code).

### 2. Phase 5 started — VPS provisioned in Dublin

**Decisions confirmed at provisioning:**
- AWS Lightsail · region **eu-west-1 (Ireland)** — locked decision #2
- Availability Zone: **eu-west-1a**
- Plan: **$24/mo · 2 vCPU · 4 GB RAM · 80 GB SSD · 4 TB transfer · Dual-stack (IPv4 + IPv6)**
- Blueprint: **Ubuntu 24.04 LTS** (initially the operator selected OpenClaw — caught + corrected before launch)
- Instance name: **Ubuntu-1**
- SSH key: **Default Lightsail SSH key** (not yet downloaded; will be needed for non-browser SSH)
- Automatic snapshots: **disabled** for now (~$4/mo extra; not critical for Phase 5)
- Launch script: **none** — anti-vibe rule, set up via SSH so steps land in a runbook

**Runtime state at session close:**
- Public IPv4: **108.130.237.88**
- Static IP attached: **`StaticIp-1`** (free as long as it stays attached)
- Browser SSH terminal: **opened, operator confirmed connectivity**
- No latency test run yet — that's the next session

**Cost reality check:**
- RUNBOOK §"PHASE 5" "$5/mo" line was wrong — the spec we actually need (2vCPU/4GB/80GB) is the $24/mo plan. The $5 plan is 2vCPU/512MB which would bottleneck on RAM under paper + dashboard + prometheus. Going with $24/mo.
- This puts Phase 5 + Phase 6 in the locked decision #14 sustained-OPEX range ($200/mo budget).

## What's running now

- **AWS Lightsail Ubuntu-1** in eu-west-1 — public IP 108.130.237.88, static `StaticIp-1`. SSH terminal open in the operator's browser.
- **Mac processes** (capture pid 23820, paper pid 30325) — likely dead now since laptop has been used for screenshots and likely slept. Phase 4 14-day clock effectively dead. Will restart on the VPS as part of Phase 5.7 staging.

## Next session — Phase 5.1 → 5.7

Start a new Claude Code session and paste `phase-prompts/phase-5-prompt.txt` (created this session). The operator runs commands on the VPS and pastes output; Claude drafts the next commands.

The single most important number in the next session is the **Polymarket CLOB ping** from the Dublin VPS:
```
ping -c 20 ws-subscriptions-clob.polymarket.com
```
Need average < 15ms (locked decision #2 promised sub-5ms). If Dublin doesn't deliver, Phase 5 reopens region selection.

## Spend

$0 Anthropic this session (deterministic-only since OD-5 CUT). Phase 5 doesn't add API cost; the VPS adds ~$24/mo recurring AWS cost.

## Tags applied

None this session. Phase 5 closes when 5.7 (24h staging clean) passes; tag `phase-5-pass` then.

## Where to resume

`phase-prompts/phase-5-prompt.txt` (added this session). Anchored docs same as always: CLAUDE.md, RUNBOOK.md §"PHASE 5", memory MEMORY.md.
