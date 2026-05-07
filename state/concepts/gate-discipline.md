---
title: Gate discipline
tags: [concept, discipline, phases]
---

# Gate discipline

> No phase advances until the gate command exits 0 in the operator's terminal. Tags are how future sessions find the most recent green gate.

## The pattern

Every phase has:
1. A **gate script** at `runbooks/gates/phase-N.sh` (or `study-X.sh` for research streams).
2. A set of explicit checks the script runs (lint, type, test, presence of artifacts, live API smoke tests, etc.).
3. The script **exits 0** if all checks pass; non-zero otherwise.
4. The output is **tee'd to `runbooks/gate-evidence/phase-N.txt`** when run.
5. On green: the operator commits the evidence, tags `phase-N-pass`, pushes both, and writes a memory checkpoint.

## Why this works

- **The check is mechanical.** No judgment call about "is this good enough." Either the script exits 0 or it doesn't.
- **The evidence is reproducible.** Anyone (operator, future Claude session, auditor) can re-run the gate script and see the same checks.
- **The tag is immovable.** Once you `git tag phase-N-pass` and push, that point in history is the rollback target if drift later surfaces.
- **The ratchet is explicit.** Phase N+1 starts ONLY after Phase N is tagged. No skipping.

## What this prevents

- **Vibe advancement.** "It feels like Phase 0 is done, let me start Phase 1" — no. Run the gate. If it fails, you didn't actually finish Phase 0.
- **Silent gate softening** ([[anti-vibe-rules|operating rule #21]]). Once a gate criterion is in the script, it's hard to remove without leaving a trail.
- **Half-finished phases.** A green gate is a strong signal that *all* the moving parts of that phase are working together — not just the parts you remembered to verify.

## What this requires

- The gate script must be **honest**. If the criterion in the spec says "Telegram smoke message arrives on phone," the script must actually send a message and verify the API response. (Phase 0's `[gate-0.7]` does this — see `runbooks/gates/phase-0.sh`.)
- The gate script must be **non-destructive on success**. Re-running it shouldn't break anything that's already working. (Phase 0's gate runs `make verify` and a Telegram smoke message — both safe to re-run.)
- The gate script must be **fail-loud**. Any check that fails must produce a clear error message; don't swallow exceptions.

## Real applicability

Phase 0 had 10 explicit gate checks. All ran. All passed on the first attempt because the bootstrap had already done most of the underlying work. The gate is now in `runbooks/gate-evidence/phase-0.txt`, tagged `phase-0-pass` at commit `3195d2c`.

Study Phase A's gate ran twice — once with the 3-hour result (failed at 60% threshold), once with the 7-day result (failed at 60% threshold). The second run *confirmed* the first; the gate threshold did not move. Tagged `study-A-final` at `dbc33a4`.

## What's next

When [[../phases/phase-1-wallet-auth|Phase 1A]] starts, the operator (or Claude session) will:
1. Write `runbooks/gates/phase-1a.sh` with explicit assertions (wallets generated, age-encrypted backups present, derived L2 creds work via signed read-only call, no Funder key in repo).
2. Run it.
3. Capture evidence.
4. Tag `phase-1a-pass` only on green.

## See also

- [[anti-vibe-rules]] — gate discipline is rule #4 + operating rules #11-13
- [[3-fix-rule]] — the per-bug analog
- [[../phases/README|Phase ledger]] — where gates land
- `runbooks/gates/` — actual scripts
- `runbooks/gate-evidence/` — captured outputs
