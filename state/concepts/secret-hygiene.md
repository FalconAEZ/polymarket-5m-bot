---
title: Secret hygiene — handing off high-value secrets to the operator
tags: [concept, security, process, anti-vibe]
---

# Secret hygiene

> When a one-shot script outputs a high-value secret (private key, API token), the way the operator captures it determines whether the secret stays contained. Documentation banners are not load-bearing enough.

## The principle

A secret must move from "produced" to "destination" with **zero intermediate stops**. Every place the secret transits — a terminal scrollback, a clipboard with a long timeout, a notes file, a chat window, a screenshot — is a place it can leak.

In Phase 1A's `scripts/genwallets.py`, the design intent was:
1. Generate Funder + Signer keys.
2. Pipe Funder privkey directly to `age -p` subprocess via stdin (encrypted; never on disk plaintext, never on stdout).
3. Print Signer privkey to stdout **once**, with a banner saying "paste into `.envrc` and run `clear`".

Step 3 has a hidden assumption: the operator reads the banner and acts on it before doing anything else. That assumption broke during Phase 1A — see [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]].

## Risk surface (in increasing order of badness)

| Sink | Lifetime | Permission | Mitigation |
|---|---|---|---|
| Process memory (one shell invocation) | seconds | RAM-only | acceptable; secrets land here briefly by design |
| Direct pipe to encryptor | microseconds | none | best |
| `.envrc` (gitignored, 0600) | months | owner-only | acceptable destination by project policy |
| age-encrypted `.age` file | indefinite | encrypted | best long-term |
| Clipboard | until next paste / clear | varies by OS | acceptable IF cleared promptly |
| Terminal scrollback (no `clear`) | until terminal closes | owner-only | bad; window can be hours |
| Plaintext notes file | until file deleted | varies (may be 644) | **bad** |
| Screenshot / photo | indefinite | varies | **very bad** |
| Chat / Slack / email | indefinite, often replicated | adversary-readable | **catastrophic** |
| Git commit (even gitignored-once) | forever (history) | public | **catastrophic** |

## Design rules for one-shot secret-output scripts

1. **If the secret has an obvious destination, write it there directly.** A `--write-envrc` flag that edits `.envrc` is safer than printing to stdout and asking the operator to paste.
2. **If you must print, print to stdout (not stderr) and only the secret value (no banner, no other content on the same line).** Then the operator's only safe action is `>>` redirection or piping into another tool.
3. **Force a single short-lived hand-off mechanism.** `pbcopy` + 60-second clipboard expiry is one option; named-pipe handoff is another.
4. **Never print the secret AND adjacent metadata (addresses, banners) on the same screen.** A copy-paste of "the output" should never include the secret if the operator is following normal copy habits.
5. **Make the silent-failure path obvious.** If a downstream script needs the secret and it's missing, the script should abort with an unambiguous message that does not get drowned by terminal noise. (Phase 1A's `derive_creds.py` does this correctly with exit codes 2/3 and stderr messages.)

## Anti-pattern catalog (seen in this project)

- **Banner-as-instruction.** "The line below is your privkey, paste it into .envrc and run `clear`." The operator's eye finds the hex string and skips the banner. (Phase 1A `genwallets.py`.)
- **Pre-existing notes file with "env" in the name.** `env req.rtf` had been a scratchpad for env-related notes for years. When the operator saw "env" in the prompt and "env" in their notes file name, they routed the output there. (Pinned in [[../postmortems/2026-05-07-env-req-rtf-key-on-disk|the postmortem]].)
- **Stale placeholders that mask failure.** Phase 0 left `POLY_API_*` placeholder lines in `.envrc` from a bootstrap. When `derive_creds.py` failed silently, the placeholders made it look like things worked. (Fixed in commit `1537a18`: stale lines removed from `.envrc.example`, `RUNBOOK.md`, `scripts/bootstrap.sh`, and the REQUIREMENTS.pdf builder.)

## When the rule kicks in

- Phase 1A: Funder + Signer privkeys (covered, but with the rtf-leak lesson).
- Phase 1B: USDC approve transaction signing — done via MetaMask UI; key never leaves vault. Lower risk by design.
- Phase 5: Signer key transfer from laptop to Dublin VPS — `age` over SSH, both endpoints owner-only.
- Phase 6: live trading — Signer key in VPS `.envrc` mode 0600 only.
- Phase 7: Funder key migration to Ledger hardware wallet — never appears in plaintext after migration.

Each of these handoffs should re-derive the design rules above. Don't assume the previous phase's solution scales.

## Connections

- Postmortem: [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]]
- Concept: [[funder-signer]]
- Decision: [[../decisions/README#decision-13|#13 derive→sign→fund order]]
- Anti-vibe: [[anti-vibe-rules]] (this concept is a corollary of "design doc before code")
- Code: `scripts/genwallets.py`, `scripts/derive_creds.py`, `scripts/test_auth.py`
