---
title: Funder/Signer wallet topology
tags: [concept, wallet, security, money]
---

# Funder/Signer

> Two wallets. One holds money. The other moves money. Separation of concerns + blast-radius limit.

## The split (decision #11)

| | **Funder** | **Signer** |
|---|---|---|
| Role | working capital, long-term holder | bot operator, daily authorizer |
| Address (live) | `0x512DA3825E69A8c19d2e0D00b66dd23d3ec95d22` | `0x8d9759A73D65aD32cd858eb3AdE46ce56F5F2B4A` |
| Balance bound | up to total bankroll | ≤ 2 days of working capital |
| Key location | offline, age-encrypted at `~/secrets/polymarket-5m/funder.age`, ephemeral MetaMask import for sends | `.envrc` (gitignored, mode 0600) as `POLY_PRIVATE_KEY` on laptop; eventually on Dublin VPS; encrypted backup at `~/secrets/polymarket-5m/signer.age` |
| Touches | rare manual top-ups + nightly sweeps from Signer | every order |
| Geography | operator's laptop only | laptop now → Dublin VPS in Phase 5 |
| Generated | 2026-05-06 by `scripts/genwallets.py` (Phase 1A task 1.1) | same |

> **Key-on-disk incident:** the Signer privkey briefly landed in `env req.rtf` (mode 644) instead of `.envrc` during initial setup — see [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]]. Fixed mid-session. Generalized lesson at [[secret-hygiene]].

## Sweep policy

- **Signer balance > $50** → sweep excess back to Funder (nightly cron in Phase 6+).
- **Funder balance > $200** → sweep to cold storage (Phase 7, hardware wallet at $2k bankroll trigger per [[../decisions/README#decision-12|decision #12]]).

## Why this matters

If Signer key is compromised:
- Maximum loss = Signer's current balance (≤ 2 days of working capital, capped at ~$50–$100 in early phases).
- Funder is untouched — still has the rest of the bankroll.
- Recovery: revoke Signer's USDC allowance to Polymarket exchange (one tx from Funder), regenerate Signer wallet, derive new L2 creds, redeploy.

If Funder key is compromised:
- Maximum loss = total bankroll.
- This is why Funder lives offline and is never on the running bot machine.

## Phase ordering

- [[../phases/phase-1-wallet-auth|Phase 1A]]: generate both wallets, encrypt both backups, derive Signer L2 creds.
- [[../phases/phase-1-wallet-auth|Phase 1B]]: fund Funder ($50 USDC + $5 MATIC), sweep $20 to Signer, approve Polymarket exchange for Signer's USDC.
- Phase 5: Signer key moves to Dublin VPS (age-encrypted transfer over SSH). Funder key NEVER goes to the VPS.
- Phase 7 step 7.1 ($3k bankroll): buy Ledger Nano S/X for Funder. Cold storage.

## Operator UX (MetaMask)

The operator uses MetaMask in a dedicated browser profile. For sends:
- Import Funder + Signer one at a time as separate accounts.
- MetaMask signs in its vault — privkey never pasted into a CLI.
- After a send, optionally remove the Funder account from MetaMask (the age-encrypted backup is the source of truth).

## Recovery procedure

Documented in `runbooks/wallet-ops.md` (created in Phase 1A task 1.6):

1. **Suspect Signer leak:** `poly-clob-client.revoke_api_key()` to invalidate L2 creds; on-chain `usdc.approve(exchange, 0)` from Signer to revoke allowance; regenerate Signer; derive new creds.
2. **Suspect Funder leak:** sweep all balances out of Funder immediately to a fresh address; regenerate Funder; update sweep targets.

## See also

- [[../decisions/README#decision-11|Decision #11]] — the split locked
- [[../decisions/README#decision-12|Decision #12]] — hardware wallet trigger at $2k
- [[../decisions/README#decision-13|Decision #13]] — derive → test sign → THEN fund
- [[../decisions/README#decision-17|Decision #17]] — gasless relayer (so Signer pays minimal MATIC)
- [[../decisions/README#decision-20|Decision #20]] — Phase 1A/1B split that closed OD-4c (signature_type=0, EOA `funder` = Signer's own address)
- [[../phases/phase-1-wallet-auth]] — Phase 1A close state + addresses
- [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]] — Signer key-on-disk incident
- [[secret-hygiene]] — generalized lesson from the incident
- [[gasless-relayer]] — how Signer interacts with Polymarket without paying per-trade gas
- `runbooks/wallet-ops.md` (project root) — full ops procedures: sweep policy, four recovery scenarios, MetaMask hygiene, pre-send checklist
