---
title: Sessions ledger
tags: [moc, sessions]
---

# Sessions ledger

Daily session logs (anti-vibe operating rule #5: end every session with a 2-line note in `state/sessions/<utc-date>.md`).

## Logs

- [[2026-05-06]] — bootstrap finished, Phase A closed (ABORT), Phase 0 closed (GREEN), decision #20 (Phase 1 1A/1B split), vault built; Phase 1A code shipped (8 commits 80df145..eb9d4d5).
- [[2026-05-07]] — Phase 1A gate green at `1537a18`, tag `phase-1a-pass` pushed; env-req-rtf incident + postmortem; Phase 2 prompt staged at `~/Desktop/phase-2-prompt.txt`.
- [[2026-05-07-evening]] — Phase 2 dev tasks 2.0-2.5 closed; capture launched on Mac (33s heartbeat measured, decision #21 added).
- [[2026-05-07-vps-provisioned]] — Phase 5 started: AWS Lightsail Ubuntu 24.04 in Dublin provisioned; vault → git (decision #18 revised); RESUME-WINDOWS.md + obsidian-setup runbooks. **Note: hand-off recorded wrong public IP and instance name; corrected 2026-05-07-phase-5.1-pass.**
- [[2026-05-07-phase-5.1-pass]] — Phase 5 Task 5.1 (SSH lockdown) GREEN: port 2222 only, key-only, no root, no password, UFW + Lightsail console firewall. Path B chosen (Any-IPv4 + layered auth, due to NordVPN rotating egress). Ubuntu 24.04 socket-activation gotcha documented. Partial-Phase-5 checkpoint; 5.2-5.7 next session.
- [[2026-05-07-phase-5.2-pass-5.3-blocked]] — runtime install GREEN; latency measured.
- [[2026-05-07-phase-5.4-systemd-pass-5.5-design]] — systemd units GREEN; design/alerter.md locked for 5.5.
- [[2026-05-07-phase-5.5-chunk1-grafana-live]] — bot-staging LIVE on 4 feeds; grafana-agent pushing to Grafana Cloud.
- [[2026-05-07-phase-5.5-chunk2-pass]] — operator-confirmed e2e Telegram + /halt smoke; Phase 5.7 14-day clock starts.
- [[2026-05-08-phase-5-pass]] — Phase 5 GREEN; tag `phase-5-pass` at `e43b77c`; litestream → AWS S3 eu-west-1; restore drill md5-identical.
- [[2026-05-09-spot-aware-aggressive-launch]] — Phase 11.A.2 launch: SpotAwareStrategy in aggressive mode shipped to bot-staging at `fc11ad9`; soak clock starts 22:26:15 UTC; gate at 2026-05-10 22:26:15 UTC. Five bugs caught + fixed mid-session (Chainlink/Polymarket resolution mismatch, FillSimulator phantom $449 trade, dashboard sync flicker, dashboard CPU saturation, limit-at-ask non-fill).
- [[2026-05-09-orphan-fd-incident-and-dashboard-polish]] — Dashboard-v3 polish session pivoted into incident response. Bot's append FDs on `state/decisions/*.jsonl` orphaned for 8.5h (04:14 → 12:48 UTC) by an atomic-rename writer; dashboard reported wrong numbers (~3× off). Recovered all 308+ decisions via `/proc/<pid>/fd/`; bot resumed cleanly. Defenses: DecisionLog inode-stability check + salvage, `resolve_decisions.py` refuses in-place mode, dashboard staleness incident wire. Plus polish: chart bleed, decisions tape spillover, RTT thresholds, Chainlink endpoint, AnimatedBook overflow, Market column + countdown in tape, **CumulativePnlPanel** new chart between DecisionsTape + CTFBook. Six commits `ac80f9b → d32d1d5` on `claude/trusting-spence-03c165`. Postmortem: [[../postmortems/2026-05-09-orphan-fd-decisions]].

## Format

Each daily file is one markdown note with frontmatter:

```yaml
---
date: YYYY-MM-DD
phase: <current phase>
status: <closed-N | in-progress | blocked>
tags: [session, ...]
---

# YYYY-MM-DD — <one-line headline>

## What shipped today
- ...

## What's next
- ...

## Anti-vibe rule notes
- ...
```

Sessions accumulate. Don't delete past entries — they're the trail of how the project actually evolved (vs how the plan said it would).

## See also

- [[../phases/README|Phase ledger]] — what got done at the macro level
- [[../postmortems/README|Postmortems]] — incident write-ups (different from sessions)
- [[../runbooks/README|Operational runbooks]] — daily operational procedures
