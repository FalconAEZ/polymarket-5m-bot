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
