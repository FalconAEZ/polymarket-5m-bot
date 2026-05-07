---
title: Phase 1 — Wallet & Auth (1A closed, 1B deferred)
status: 1A ✅ closed (gate green); 1B deferred to head of Phase 6
tags: [phase, wallet, auth, money, closed-1a]
---

# Phase 1 — Wallet & Auth

Per [[../decisions/README#decision-20|decision #20]], Phase 1 was split into two halves. **1A is now closed; 1B is deferred to the head of Phase 6.**

## Phase 1A — no-money setup ✅ CLOSED 2026-05-06

**Outcomes:**
- ✅ Funder address: `0x512DA3825E69A8c19d2e0D00b66dd23d3ec95d22` (encrypted backup at `~/secrets/polymarket-5m/funder.age`; privkey **never** on bot host or in `.envrc`)
- ✅ Signer address: `0x8d9759A73D65aD32cd858eb3AdE46ce56F5F2B4A` (privkey in `.envrc` as `POLY_PRIVATE_KEY`, mode 0600, gitignored; encrypted backup at `~/secrets/polymarket-5m/signer.age`)
- ✅ L2 creds derived against Signer; full L1+L2 round-trip green via `scripts/test_auth.py` against live Polymarket
- ✅ All 10 gate assertions in `runbooks/gates/phase-1a.sh` exit 0; evidence at `runbooks/gate-evidence/phase-1a.txt` (ran 2026-05-06T20:17:29Z)
- ✅ Tag `phase-1a-pass` at commit `1537a18` on branch `claude/bold-galileo-2d56ca`, pushed to GitHub
- ✅ Memory checkpoint at `~/.claude/projects/.../memory/checkpoint_phase_1a.md`
- ✅ Cost: **$0** (no on-chain footprint, by decision #20)

**Tasks shipped:**
- 1.0 — `design/gasless.md` ([[../concepts/gasless-relayer|OD-4]] resolution: orders via standard CLOB API not Relayer SDK; skip Builder Program; `signature_type=0`; CLOB `funder` = Signer's own address)
- 1.1 — `scripts/genwallets.py` + 13 unit tests + `eth-account` runtime dep; both wallets generated offline, age-encrypted to `~/secrets/polymarket-5m/`
- 1.2 — `scripts/derive_creds.py` + 14 unit tests + `py-clob-client` runtime dep; L2 creds derived and appended to `.envrc`
- 1.3 — `scripts/test_auth.py` + 18 unit tests; full L1+L2 verification against `clob.polymarket.com/auth/api-keys`
- 1.6 — `runbooks/wallet-ops.md` (Funder/Signer ops + sweep policy + four recovery procedures + MetaMask hygiene + pre-send checklist + audit commands)
- 1.6.5 — `runbooks/gates/phase-1a.sh` + `make gate-1a` target

**Commits this phase (9 total since `phase-0-pass`):**
- `80df145` design/gasless.md — OD-4 closed
- `c9db20e` design/genwallets.md
- `c4de873` scripts/genwallets.py + tests + `eth-account`
- `a8411c1` design/derive_creds.md + `py-clob-client`
- `6d72554` scripts/derive_creds.py + tests
- `bfc1ad2` scripts/test_auth.py + tests
- `0631090` runbooks/wallet-ops.md
- `eb9d4d5` runbooks/gates/phase-1a.sh + Makefile target + RUNBOOK.md callout
- `1537a18` Phase 1A gate green; addresses recorded in wallet-ops.md; cleanup of pre-OD-4c `POLY_FUNDER_ADDRESS` / `POLY_SIGNATURE_TYPE` from `.envrc.example`, `RUNBOOK.md`, `scripts/bootstrap.sh`, and the REQUIREMENTS.pdf builder; gate script walks up to find `.envrc` (worktree fix)

**Two `/security-review` passes during the phase** (after 1.1 commit, after 1.2 commit) returned no HIGH/MEDIUM findings.

**One incident: [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]].** Operator pasted `genwallets.py` output into `env req.rtf` (mode 644) instead of `.envrc`. Detected mid-session via diagnostic that counts hex strings in the rtf without echoing values. Privkey moved to `.envrc` via shell-pipeline that never logged the value. Severity LOW (Phase 1A is no-money). Operator-side cleanup (`rm` the rtf) still pending. Generalized lesson at [[../concepts/secret-hygiene]].

**Why we did 1A independently of 1B:** Phase 2 (data plane), Phase 3 (backtest), and Phase 4 (paper trading) are all read-only or paper-mode. They don't need a funded wallet. So 1A's outputs (wallet addresses + working creds + signing-flow proof) sit in the project until 1B fires.

## Phase 1B — funding + first gasless test order (deferred to head of Phase 6)

**Tasks shipping in 1B:**
- 1.4 — fund the Funder, sweep dust to Signer, approve Polymarket exchange
- 1.5 — place + cancel a $5 limit via gasless relayer

**Gate:** original funded gate `runbooks/gates/phase-1.sh` exits 0; tag `phase-1-pass`. Asserts Signer USDC ≥ $20 on PolygonScan, allowance set, four order-state transitions captured (placed → OPEN → cancel-submitted → CANCELED).

**Cost:** $5 gas + $50 USDC working capital (not consumed; at risk).

**When 1B fires:** immediately before Phase 6 go-live, after Phase 4 paper testing has confirmed the strategy works with real-data simulation. Sequence: 0 → 1A → 2 → 3 → 4 → 5 → **1B → 6**.

## Locked discipline preserved

[[../decisions/README#decision-13|Decision #13]] (creds → test sign → fund order) is **not relaxed** by the split. We just pause between "test sign" (end of 1A) and "fund" (start of 1B). The order stays right.

## Wallet topology (locked)

Per [[../decisions/README#decision-11|decision #11]] and [[../concepts/funder-signer|Funder/Signer concept]]:

| Wallet | Purpose | Key location | Balance bound |
|---|---|---|---|
| **Funder** | working capital, long-term holder | `~/secrets/polymarket-5m/funder.age` (offline, age-encrypted), ephemeral MetaMask import for sends | $0 in 1A; $50 after 1B; up to $1k post-Phase-6 |
| **Signer** | bot operational, daily authorizer | `~/secrets/polymarket-5m/signer.age` + `.envrc` `POLY_PRIVATE_KEY` | $0 in 1A; ≤$50 ongoing (sweep excess to Funder nightly) |

Hardware wallet (Ledger) for the Funder triggers at $2k bankroll per [[../decisions/README#decision-12|decision #12]] — that's Phase 7 step 7.1, not now.

## OD-4 resolution (carried into 1A from Phase 0)

Per [[../decisions/README#decision-20|decision #20]] (which captured an in-flight design decision), OD-4 was resolved:

- Orders go via the **standard CLOB API**, not the Relayer SDK.
- **Skip the Builder Program** — Signer pays its own MATIC for one-time approvals (USDC `approve()` to Polymarket exchange). This is the only on-chain tx that costs gas; orders themselves go through the CLOB without on-chain footprint per fill.
- `signature_type = 0` (EOA — externally-owned account).
- CLOB `funder` parameter = Signer's own address (not a separate proxy wallet).

Implementation notes for 1A `design/gasless.md`:
- Use `py-clob-client.ClobClient(host, key=signer_pk, chain_id=137, signature_type=0, funder=signer_addr)`.
- Approval call: `client.set_api_creds(...)` for L2; for the on-chain USDC approval the Polymarket UI is the path of least resistance (see [[../concepts/gasless-relayer]]).

## MetaMask UI (operator-facing)

Operator uses MetaMask in a dedicated browser profile. In 1B task 1.4:
1. Import Funder + Signer one at a time as separate accounts.
2. Send Funder → Signer via MetaMask's normal UI (key never leaves vault).
3. Approve Polymarket exchange via polymarket.com connected with Signer.
4. Optionally remove Funder from MetaMask after — age-encrypted backup is the source of truth.

## Connections

- Phase before: [[phase-0-foundations]]
- Phase after 1A: [[phase-2-data-plane]] (read-only data plane; doesn't need funding)
- Decisions: [[../decisions/README#decision-11|#11 Funder/Signer]], [[../decisions/README#decision-13|#13 derive→sign→fund order]], [[../decisions/README#decision-17|#17 gasless relayer]], [[../decisions/README#decision-20|#20 1A/1B split]]
- Concepts: [[../concepts/funder-signer]], [[../concepts/gasless-relayer]], [[../concepts/secret-hygiene]]
- Postmortem: [[../postmortems/2026-05-07-env-req-rtf-key-on-disk]]
- Sessions: [[../sessions/2026-05-06]] (code shipped) · [[../sessions/2026-05-07]] (operator ran scripts; gate green; Phase 2 prep)
- Skills: `~/.claude/skills/agent-skills/{authentication,gasless}.md`
- Memory: `~/.claude/projects/.../memory/checkpoint_phase_1a.md`
- External prompts:
  - `~/Desktop/phase-1-prompt.txt` — the original Phase 1 prompt (covers 1A + 1B)
  - `~/Desktop/phase-2-prompt.txt` — the next-up Phase 2 dev-session prompt (written 2026-05-07)
