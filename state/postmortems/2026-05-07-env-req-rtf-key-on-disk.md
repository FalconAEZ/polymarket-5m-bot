---
title: 2026-05-07 — Signer privkey landed in `env req.rtf` instead of `.envrc`
date: 2026-05-07
phase: 1A
severity: low (no money at risk yet)
status: open — operator-side cleanup pending
tags: [postmortem, secret-hygiene, phase-1a, process]
---

# Postmortem — Signer privkey on disk in `env req.rtf` (mode 644)

## TL;DR

`scripts/genwallets.py` ran successfully and printed the Signer privkey on stdout for paste into `.envrc`, per its design. The operator pasted the **entire script output** (FUNDER address, SIGNER address, encrypt-progress banner, and the SIGNER privkey line) into a TextEdit notes file at `/Users/hamad/Desktop/PolyMarket-5m/env req.rtf` — a pre-existing scratchpad — *and never updated `.envrc`'s empty `POLY_PRIVATE_KEY=` placeholder line*. The privkey then sat on disk in plaintext, mode 644 (world-readable on this Mac), unencrypted, until detected and remediated mid-session.

No money was at risk: Phase 1A is no-money by [[../decisions/README#decision-20|decision #20]]. The Signer wallet is empty; the privkey, while exposed, controls nothing yet. **But the operational lesson is real and worth pinning.**

## Timeline (UTC)

| When | What |
|---|---|
| 2026-05-06 ~19:00 | Operator ran `scripts/genwallets.py`, entered both age passphrases successfully. Both `.age` files written correctly. Two addresses + Signer privkey printed to terminal as designed. |
| ~19:01 | Operator pasted entire genwallets output into `env req.rtf`, intending it as a backup/reference. **Did not update `.envrc`**: the placeholder `export POLY_PRIVATE_KEY=` line stayed empty. |
| ~19:03 | Operator ran `derive_creds.py` — script aborted because `POLY_PRIVATE_KEY` resolved to empty. Operator did not see this failure and moved on. (Stale `POLY_API_*` lines from a prior bootstrap were already in `.envrc`, masking the issue.) |
| 2026-05-07 ~00:10 (operator local 04:10 +0400) | Operator returned to the chat, asked Claude to run steps 5-7 directly. |
| ~00:11 | Claude ran diagnostic: confirmed `POLY_PRIVATE_KEY` was empty in env. Spotted that the genwallets output was in `env req.rtf` — file existed at mode 644, 1960 bytes (way too big for just `KEY=value` pairs). |
| ~00:12 | Claude ran a second diagnostic to count 64-char hex strings in the rtf: exactly 1 (Signer privkey only — confirming the FUNDER privkey was *not* in the file, per script design where Funder privkey never hits stdout). Both 40-char addresses also extracted (PUBLIC, safe to log). |
| ~00:13 | Claude moved the privkey from `env req.rtf` → `.envrc` via shell pipeline that held the value only in a local `$KEY` shell variable, never echoed. Privkey value never entered the conversation log. |
| ~00:14 | Removed five obsolete lines from `.envrc` (stale `POLY_API_*` from a prior bootstrap, plus `POLY_FUNDER_ADDRESS` and `POLY_SIGNATURE_TYPE` from the pre-OD-4c design). `direnv allow`. |
| ~00:15 | Re-derived L2 creds against the new Signer privkey; ran `test_auth.py` — both checks green. |
| ~00:17 | Phase 1A gate ran end-to-end: 10 of 10 ✓. Tag `phase-1a-pass` at `1537a18`. |
| TBD | **Operator action still pending**: `rm "/Users/hamad/Desktop/PolyMarket-5m/env req.rtf"` (or scrub the privkey line and `chmod 0600`). |

## Root cause

Two things stacked:

1. **Script-output discoverability friction.** `genwallets.py` prints addresses on stderr and the Signer privkey on stdout. In a normal terminal both are visible at the same scroll position, which makes it easy to copy the whole blob as a single "thing" — and that's what happened. The script's design intent was that the operator copies *only* the privkey line into `.envrc` and then runs `clear` to wipe scrollback. The intent didn't survive the operator's habit of saving notes to TextEdit.

2. **Pre-existing `env req.rtf` scratchpad.** This file existed before the project started and the operator has been using it for years as a notes destination. The naming (`env req` ≈ "environment requirements") makes it sound exactly like the right place to drop env-related material. Phase 0's `gate-0.10` already gates against committing `env req.rtf` — which means we knew the file was sensitive — but didn't think about the operator using it as a *first-paste destination* for genwallets output.

## What worked

- `genwallets.py`'s design: only the **Signer** privkey appears on stdout. The Funder privkey was never printed anywhere on screen — only piped via stdin to the `age -p` subprocess for encryption. So even though the operator pasted "everything they saw" into the rtf, the FUNDER privkey was *not* in there. Verified empirically (1 hex-64 string, not 2).
- The age-encrypted `.age` backups are intact and untouched. Source of truth for both keys remains the encrypted backup pair.
- Diagnostic flow that caught it: counting hex matches and inspecting var names (not values) before any move. Privkey value never entered the conversation log.
- The recovery (move to `.envrc` via shell-variable pipeline) was reversible and clean. Phase 1A gate now green.

## What didn't work / lessons

### L1. The script's stdout banner is not load-bearing enough.

The current banner says:
> "Both wallets encrypted. Next: paste the line below into .envrc as
>    export POLY_PRIVATE_KEY=<line>
>  then `chmod 0600 .envrc`, then `clear` to wipe scrollback, then
>  `direnv allow`. The line will appear ONCE on stdout below."

It's a wall of text on stderr; the operator's eye went to the hex line on stdout, copied "the output", and didn't read the banner. **Action item:** add a strict-pause prompt — `genwallets.py` could write to a tmpfile that exists for 60s, opens an `pbcopy` pipe so the privkey is on the clipboard with a timeout, and refuses to print the privkey to stdout AT ALL (forcing it through the clipboard). That way there is nothing to paste-elsewhere.

This is a Phase 1A retrofit candidate, low priority since the encrypted backups are sound and Phase 1A is closed. Filed as icebox issue (not yet — TBD whether to file).

### L2. The `derive_creds.py` failure mode was silent enough to miss.

When `POLY_PRIVATE_KEY` was empty, the script aborts with exit 2 and a clear stderr message. But the operator's terminal had pre-existing `POLY_API_*` lines from a prior bootstrap (Phase 0 placeholders that were never blanked when the bootstrap finished). Result: the operator may have seen the abort message but assumed the API keys had been set anyway from an earlier run, and moved on without realizing the chain was broken.

**Action item (already shipped in this session):** the `1537a18` commit removed `POLY_FUNDER_ADDRESS`, `POLY_SIGNATURE_TYPE`, and stale `POLY_API_*` placeholders from `.envrc.example`, `RUNBOOK.md`, `scripts/bootstrap.sh`, and the REQUIREMENTS.pdf builder. Future bootstraps won't pre-populate stale fields.

### L3. The Phase 1A gate's `[gate-1a.4]` initially failed because of a git-worktree subtlety.

When the operator (well, Claude on the operator's behalf) ran `make gate-1a` from inside the worktree at `.claude/worktrees/bold-galileo-2d56ca`, the gate's `$ROOT/.envrc` resolved to the worktree root — where there is no `.envrc`. The actual `.envrc` lives in the main repo at `/Users/hamad/Desktop/PolyMarket-5m/.envrc`.

**Action item (shipped in `1537a18`):** gate script now walks up from `$ROOT` to find `.envrc`, mirroring direnv's hierarchical search. Worktree case handled. This was a bug in `phase-1a.sh` from its first commit (`eb9d4d5`); fixed in the gate-pass commit.

## Operator-side action items

- [ ] **`rm "/Users/hamad/Desktop/PolyMarket-5m/env req.rtf"`** — remove the file. The encrypted `signer.age` + `.envrc` are sufficient to operate; the rtf is redundant exposure.
  - If there are non-key notes in the file the operator wants to keep: open in editor, copy the non-key portions to a different file, then `rm` the rtf.
  - On the FileVault-encrypted laptop, edit-delete is acceptable; full-disk encryption is the operator's threat-model boundary.
- [ ] (Optional, future) Change MetaMask vault password if it was set during the same session as the rtf file was open. No evidence of MetaMask compromise; this is hygiene-only.
- [ ] (Optional, deferred) Consider whether to retrofit `genwallets.py` to use `pbcopy` instead of stdout for the privkey hand-off. Filed as a candidate; not blocking.

## Generalized lesson

> When a one-shot script outputs a high-value secret, **do not rely on documentation banners to direct the operator**. Either (a) refuse to put the secret in any human-readable place at all (clipboard with timeout, automatic file write), or (b) make the operator perform a single explicit action that puts the secret directly into its destination (e.g. a `--write-envrc` flag that edits `.envrc` itself).

See [[../concepts/secret-hygiene]] for the principle.

## Connections

- Phase: [[../phases/phase-1-wallet-auth]]
- Concept: [[../concepts/funder-signer]] · [[../concepts/secret-hygiene]]
- Decision: [[../decisions/README#decision-20|#20 1A/1B split]] (made the impact LOW)
- Session: [[../sessions/2026-05-07]]
- Code: `scripts/genwallets.py` (design candidate for retrofit), `runbooks/gates/phase-1a.sh` (walk-up fix shipped in `1537a18`)
