# Design — `scripts/genwallets.py` (Phase 1A · task 1.1)

> Purpose: generate **Funder** and **Signer** EOA wallets offline, age-encrypt
> them to `~/secrets/polymarket-5m/`, and surface the Signer private key once
> for paste into `.envrc`. **No plaintext private key ever touches disk** —
> not in `/tmp`, not in scrollback shadow files, not in shell history.
>
> Anchors: locked decisions [#11 Funder/Signer separation], [#13 derive →
> sign → fund]; [`design/gasless.md`](gasless.md) §4 (`signature_type=0`
> ⇒ Signer EOA is its own CLOB `funder`); [RUNBOOK §1.1](../RUNBOOK.md).

---

## 1. Why two wallets

Locked decision #11. Funder is the long-term capital pool; Signer is the daily
operator. Compromise of Signer caps loss at ≤ 2 days of bankroll. Polymarket
itself never sees the Funder address — Funder is a personal cold wallet that
sweeps capital to Signer in chunks. See `design/gasless.md` §4 for why the
CLOB-API `funder` parameter is **not** this Funder wallet.

## 2. Why `eth-account` + `secrets.token_bytes(32)`

| Component | Choice | Rejected alternatives |
|---|---|---|
| Entropy source | `secrets.token_bytes(32)` — wraps `os.urandom`, which on macOS calls `getentropy(3)` (kernel CSPRNG seeded from hardware) | `random.randbytes`, mnemonic generation, BIP-39 seed phrases — all weaker or add complexity we don't need for two one-shot wallets |
| Key → address | `eth_account.Account.from_key(bytes32)` | Hand-rolled secp256k1 + keccak — needless reimplementation; eth-account is MIT, audited, and a transitive dep of py-clob-client anyway |
| Network | None — script makes zero outbound calls | Online vanity-key generators, hosted KDFs — leak the key |

`eth-account ≥ 0.13` is added as a runtime dep via `uv add eth-account`. Pinned
in `pyproject.toml`, locked in `uv.lock`.

## 3. Improvement vs. RUNBOOK §1.1

The RUNBOOK example pipes both wallets through `/tmp/wallets.txt` then `shred`s
it. That has a small but real plaintext-on-disk window. We tighten this:

- **Single invocation.** One run generates both wallets and encrypts both.
- **Subprocess to `age`.** Plaintext is piped to `age -p` via `stdin`; `age`
  reads the passphrase from `/dev/tty`, so the pipe carries plaintext that
  never lands on the filesystem.
- **No `/tmp` file ever.** No `shred` step needed.
- **Signer privkey shown once on stdout** with a clear banner. Operator copies
  to `.envrc`, then runs `clear` (or closes the tab) to remove from scrollback.

## 4. CLI

```bash
uv run python scripts/genwallets.py
```

No flags in the default path. Two optional flags exist for safety:

| Flag | Default | Effect |
|---|---|---|
| `--secrets-dir PATH` | `~/secrets/polymarket-5m` | Where the two `.age` files land |
| `--allow-overwrite` | off | If a target file exists, the script aborts unless this flag is passed |

The default refusal-on-overwrite is intentional: the script is one-shot and
overwriting a key file is destructive (loses funds if the address has been
funded already). Operator must explicitly opt in to overwrite.

## 5. Output streams

| Stream | Content |
|---|---|
| `stdout` | Single line: the **Signer** private key in `0x...` hex, followed by `\n`. This is captured by the operator's eye and pasted into `.envrc`. |
| `stderr` | Banner with both wallet addresses, the two output paths, and a `WARNING: clear scrollback` note. Visible during the age passphrase prompts. |
| Files | `~/secrets/polymarket-5m/funder.age`, `~/secrets/polymarket-5m/signer.age` (mode 0600 by `age` default; directory mode 0700) |
| `.envrc` | **Not touched by the script.** Operator pastes manually. The script never reads or writes `.envrc`. |

The Funder privkey is **never** written to stdout. It is only ever in process
memory and on the encrypted-output pipe to `age`.

## 6. Process flow

```
                ┌────────────────────────────────────────────┐
                │ 1. validate `age` on PATH                  │
                │ 2. mkdir -p ~/secrets/polymarket-5m mode 0700│
                │ 3. for each (Funder, Signer):              │
                │    a. secrets.token_bytes(32)              │
                │    b. Account.from_key() → (addr, hex)     │
                │    c. spawn `age -p -o <path>`             │
                │       │                                    │
                │       │ stdin ← privkey hex bytes          │
                │       │ tty   ↔ operator passphrase (2x)   │
                │       │                                    │
                │       └── age writes encrypted file        │
                │    d. wipe `bytearray` of plaintext        │
                │ 4. print Funder addr + Signer addr (stderr)│
                │ 5. print Signer privkey (stdout, once)     │
                │ 6. exit 0                                  │
                └────────────────────────────────────────────┘
```

Errors abort the run and exit non-zero **before** printing the Signer privkey
on stdout, so a half-encrypted state never coexists with a paste-ready privkey.

## 7. Failure modes & responses

| Symptom | Cause | Action |
|---|---|---|
| `age: command not found` | `age` not installed | `brew install age`; rerun |
| `~/secrets/polymarket-5m/funder.age already exists` | Previous run left a file | If keys are still good, abort and skip 1.1. If genuinely starting over (e.g. test run), pass `--allow-overwrite` *and* update the wallet-ops doc to reflect the new addresses. |
| `age` exits non-zero (e.g. operator hits Ctrl-C at the passphrase prompt) | Operator aborted | Script exits non-zero. The first wallet's file may exist; the second is missing. Re-run with `--allow-overwrite` to redo the pair from scratch. |
| Operator loses Signer privkey from terminal before pasting to `.envrc` | Scrollback cleared too eagerly | Decrypt `signer.age` with `age -d` and paste. The `.age` file is the recovery anchor. |

## 8. Operator runbook (the exact sequence)

```bash
# Pre-req: brew install age   ;   uv add eth-account
mkdir -p ~/secrets/polymarket-5m
chmod 0700 ~/secrets/polymarket-5m

uv run python scripts/genwallets.py
# → operator enters Funder passphrase (2x for confirmation)
# → operator enters Signer passphrase (2x for confirmation)
# stderr shows:
#     FUNDER address: 0x...
#     SIGNER address: 0x...
#     wrote: ~/secrets/polymarket-5m/funder.age
#     wrote: ~/secrets/polymarket-5m/signer.age
#     >> next: paste the line below into .envrc as POLY_PRIVATE_KEY=...
# stdout shows:
#     0x<signer-privkey-hex>

# Operator manually:
#   1. copy the stdout line
#   2. open .envrc in editor; append:  export POLY_PRIVATE_KEY=0x<...>
#   3. chmod 0600 .envrc
#   4. clear   (wipe scrollback)
#   5. direnv allow
```

**Verification (no funding required):**

```bash
test -f ~/secrets/polymarket-5m/funder.age
test -f ~/secrets/polymarket-5m/signer.age
head -c 21 ~/secrets/polymarket-5m/funder.age   # expect "age-encryption.org/v1"
head -c 21 ~/secrets/polymarket-5m/signer.age   # expect "age-encryption.org/v1"
test ! -f /tmp/wallets.txt                       # the old runbook path; should not exist
echo $POLY_PRIVATE_KEY | head -c 4               # expect "0x"; never echo the full key
```

## 9. Anti-leak checklist (enforced at the gate)

- [ ] `~/secrets/polymarket-5m/funder.age` exists.
- [ ] `~/secrets/polymarket-5m/signer.age` exists.
- [ ] First 21 bytes of each match `age-encryption.org/v1` (verifies armor).
- [ ] `grep -rE "^POLY_FUNDER" .envrc` returns nothing.
- [ ] `grep -rE "POLY_FUNDER_PRIVATE_KEY|POLY_FUNDER_ADDRESS" .` returns nothing.
- [ ] `.envrc` mode is `0600`.
- [ ] `~/secrets/polymarket-5m` mode is `0700`.

These become the assertions in `runbooks/gates/phase-1a.sh` (task 1.6 / gate).

## 10. What this design explicitly does *not* do

- Does not deploy a Safe or Proxy wallet. We're EOA-only (`signature_type=0`).
- Does not call any RPC, Polymarket API, or external network resource.
- Does not write to `.envrc`. That's the operator's hand step (rule: keep the
  paste explicit so it's never silently re-done).
- Does not generate mnemonics or BIP-39 phrases. Single 32-byte secret per
  wallet, eth_account-derived. Recovery = the `.age` file + the passphrase.
- Does not back up to cloud, network, or paper. Operator is responsible for
  out-of-band backup of the `.age` files (e.g. encrypted USB stick) before
  any Phase 1B funding step.
