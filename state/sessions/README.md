---
title: Sessions ledger
tags: [moc, sessions]
---

# Sessions ledger

Daily session logs (anti-vibe operating rule #5: end every session with a 2-line note in `state/sessions/<utc-date>.md`).

## Logs

- [[2026-05-06]] — bootstrap finished, Phase A closed (ABORT), Phase 0 closed (GREEN), decision #20 (Phase 1 1A/1B split), vault built; Phase 1A code shipped (8 commits 80df145..eb9d4d5).
- [[2026-05-07]] — Phase 1A gate green at `1537a18`, tag `phase-1a-pass` pushed; env-req-rtf incident + postmortem; Phase 2 prompt staged at `~/Desktop/phase-2-prompt.txt`.

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
