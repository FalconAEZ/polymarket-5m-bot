# Wallet operations runbook

> Source of truth for how the **Funder** and **Signer** wallets are managed
> across this project's lifetime. Read this once when wallets are generated
> (task 1.1) and again before any sweep, recovery, or hardware-wallet
> migration. See [`design/gasless.md`](../design/gasless.md) §4 for the
> Polymarket-side wiring (`signature_type=0`, EOA funder = Signer address)
> and locked decisions [#11, #12, #13, #20] for the policy this doc encodes.

---

## 1. Wallet identity card

Fill in addresses immediately after task 1.1 completes. **Both addresses are
public information and safe to commit.** The private keys are NOT recorded
here under any circumstance.

| Role | Address | Encrypted backup | Privkey lives in |
|---|---|---|---|
| **Funder** | `0x512DA3825E69A8c19d2e0D00b66dd23d3ec95d22` | `~/secrets/polymarket-5m/funder.age` | offline `.age` only — **never** on the bot host, **never** in `.envrc` |
| **Signer** | `0x8d9759A73D65aD32cd858eb3AdE46ce56F5F2B4A` | `~/secrets/polymarket-5m/signer.age` | `.envrc` as `POLY_PRIVATE_KEY` (mode 0600) **and** the offline `.age` |

Generated `2026-05-06` (UTC) by `scripts/genwallets.py`. Both addresses are
public and safe to commit; the keys are protected by `age -p` passphrase
encryption (and, in the Signer's case, `.envrc` mode 0600 + gitignored).

## 2. Hard rules — never violate

1. **Funder privkey never lands on the bot host.** Phase 5 promotes the
   Signer key to a Lightsail VPS; the Funder key stays on the operator's
   laptop, encrypted, period. If a sweep needs the Funder key, the operator
   imports it into MetaMask on the laptop, signs, then removes it again.
2. **Signer never holds more than 2 days' bankroll.** At $1k bankroll +
   $5 flat sizing that's ~$50 ceiling. Anything above triggers the sweep
   in §4.
3. **Plaintext keys never leave the encrypted backup or `.envrc`.** No
   pasting into chat windows, no committing to git, no cloud backup of
   plaintext, no screenshot, no printout. `.envrc` is gitignored and mode
   0600.
4. **Funder is never the CLOB `funder` parameter.** Per OD-4c, the
   ClobClient is constructed with `funder=Signer.address`. The runbook-level
   "Funder" wallet is a personal capital-segregation construct; Polymarket
   never sees it. Confusing the two will silently lose funds.
5. **No reuse of these wallets.** Both addresses are created exclusively
   for this project and will never receive or send unrelated funds.

## 3. Phase-by-phase wallet exposure

| Phase | Funder activity | Signer activity |
|---|---|---|
| 1A (now) | Address generated; key encrypted offline; **never funded** in 1A | Address generated; key in `.envrc`; **never funded** in 1A |
| 1B (pre-live) | Funded with $50 USDC + $3 MATIC from CEX; sweeps $20 USDC + 0.5 MATIC to Signer | Receives sweep; one-time USDC.e approvals to the three exchange contracts; one $5 test order placed + cancelled |
| 2 (data plane) | Untouched | Untouched (still $20 USDC + ~0.5 MATIC from 1B) |
| 3 (backtest) | Untouched | Untouched |
| 4 (paper) | Untouched | Untouched (paper sim only) |
| 5 (VPS) | Stays on laptop | `POLY_PRIVATE_KEY` is migrated to the Lightsail `.envrc` (mode 0600). See `runbooks/vps-key-handoff.md` (Phase 5 task) |
| 6 (live) | Receives sweeps from Signer when Signer > $50; topped up from CEX as needed | Trades; max balance ~$50 |
| 7 (hardware wallet) | Funder key migrated to Ledger when bankroll ≥ $2k | Stays as-is |

## 4. Sweep policy

Two thresholds, both denominated in USDC.e on the Signer:

| Trigger | Direction | Amount | Frequency |
|---|---|---|---|
| Signer balance > $50 | Signer → Funder | Excess above $30 (i.e. sweep down to $30 working balance) | Manual; check daily during live trading |
| Funder balance > $200 | Funder → cold storage | Excess above $100 | Manual; Phase 7 task once hardware wallet is in place |

Both sweeps go through MetaMask's normal UI on the operator's laptop:
1. Import the relevant key (Signer or Funder) into the dedicated browser
   profile if not already there.
2. MetaMask `Send` → enter destination address → confirm gas → sign.
3. Wait for confirmation on PolygonScan.
4. **Optionally remove the just-used account from MetaMask** (account
   menu → ⋮ → Remove account). The encrypted `.age` file remains the
   source of truth. Re-importing later is two clicks.

MetaMask itself handles MATIC for gas; ensure the source wallet has at
least 0.05 MATIC headroom before initiating any send.

## 5. Recovery procedures

### 5a. Signer key compromised or suspected leaked

Acceptable losses: up to ~$50 (whatever Signer holds). Funder is independent
and unaffected.

1. **Immediately**: from the operator's laptop, MetaMask-connect the
   Signer account at `polymarket.com` and revoke the USDC.e allowance to
   each of the three exchange contracts (CTF Exchange, Neg-Risk CTF
   Exchange, Neg-Risk Adapter). This makes the leaked key useless on the
   CLOB.
2. Sweep any remaining balance on the Signer to the Funder (or directly to
   a cold address) via MetaMask, while you still control the key.
3. Run `scripts/genwallets.py --allow-overwrite` to regenerate **only the
   Signer** (operator manually skips the Funder prompt or accepts that
   Funder gets re-encrypted to the same key — the address won't change if
   the operator passes a fresh-write only for `signer.age`; current
   script writes both, so prefer to regenerate both rather than
   half-regenerate).
4. Replace `POLY_PRIVATE_KEY` in `.envrc` with the new Signer privkey.
5. Re-run `scripts/derive_creds.py` and replace the three `POLY_API_*`
   lines.
6. Re-run `scripts/test_auth.py` — must exit 0.
7. Update §1 (this doc) with the new Signer address; commit; tag the
   commit `signer-rotated-<utc-date>`.
8. Write a postmortem at `runbooks/postmortems/signer-leak-<utc-date>.md`
   covering: how it leaked, what was lost, what changed.

### 5b. Funder key compromised or suspected leaked

Acceptable losses: full Funder balance (could be up to $200 between
sweeps).

1. **Immediately**: from the operator's laptop, MetaMask-connect the
   Funder account and sweep the entire balance to a fresh wallet (a
   throwaway address you generate on the spot via MetaMask "Create new
   account" works for transit).
2. Generate a new Funder via `scripts/genwallets.py --allow-overwrite`.
   Update §1 with the new Funder address.
3. Move the transit-wallet balance to the new Funder.
4. Future top-ups from CEX go to the new Funder address.
5. Postmortem at `runbooks/postmortems/funder-leak-<utc-date>.md`.

The Signer is untouched: a Funder leak does not invalidate the Signer's
keys, allowances, or `.envrc`.

### 5c. `.envrc` lost or corrupted

1. Decrypt `~/secrets/polymarket-5m/signer.age` with the passphrase:
   `age -d -o /tmp/signer.txt ~/secrets/polymarket-5m/signer.age`
2. Read the privkey, paste into a fresh `.envrc`:
   `export POLY_PRIVATE_KEY=0x...`
3. `chmod 0600 .envrc`; `shred -u /tmp/signer.txt`.
4. `direnv allow`.
5. Re-run `scripts/derive_creds.py` to regenerate the L2 creds (these are
   deterministic from the privkey; same triple comes back).
6. Append the export lines to `.envrc`; `direnv allow`; run
   `scripts/test_auth.py` to confirm green.

### 5d. Encrypted backup file lost

If only one of the two `.age` files is lost but the other is intact, and
the corresponding privkey is still in `.envrc` (Signer case): re-encrypt
from `.envrc` via:

```bash
echo -n "$POLY_PRIVATE_KEY" | age -p -o ~/secrets/polymarket-5m/signer.age
```

If both `.age` files are lost AND `.envrc` is also lost: the keys are
unrecoverable. Treat as "Signer + Funder both compromised" and follow 5a +
5b. Bankroll loss is bounded by whatever was on-chain at the time.

## 6. MetaMask hygiene

| Setting | Value |
|---|---|
| Browser | Brave or Chrome |
| Profile | dedicated profile for this project (no personal browsing) |
| Vault password | unique to this profile; not reused; entered manually each session |
| Networks | Polygon mainnet only (no testnets, no L1) |
| Imported accounts | Funder + Signer when sweeping; remove between sessions if the operator prefers |
| Auto-lock | aggressive (5 min) |
| Phishing protection | enabled |
| Hardware wallet | not required at $1k; Ledger added at $2k bankroll trigger (locked decision #12) |

When importing an account by private key, MetaMask reads the key into its
encrypted vault and shows the address. The plaintext key never leaves the
vault on the operator's machine.

## 7. Pre-flight before any fund movement

Before initiating any send (Funder→Signer, Signer→Funder, or
Funder→cold), the operator runs through this list:

- [ ] Browser profile is the dedicated MetaMask profile (not personal).
- [ ] Network is Polygon mainnet (chain ID 137).
- [ ] Source account in MetaMask matches the expected Funder/Signer
      address from §1.
- [ ] Destination address verified character-by-character (no clipboard
      malware swap).
- [ ] Gas estimate ≤ $0.10; if higher, abort and check Polygon mempool.
- [ ] Amount sanity-check: send ≤ $50 in any single transaction during
      Phase 1B; ≤ $500 once at Phase 6 scale.

After the send: confirm on PolygonScan, then update `runbooks/sweeps.md`
(append-only log) with the tx hash, source, destination, amount, and date.

## 8. Audit / verification commands (no funds required)

```bash
# Both .age files exist and are valid
test -f ~/secrets/polymarket-5m/funder.age
test -f ~/secrets/polymarket-5m/signer.age
head -c 21 ~/secrets/polymarket-5m/funder.age   # expect: age-encryption.org/v1
head -c 21 ~/secrets/polymarket-5m/signer.age   # expect: age-encryption.org/v1

# Signer privkey in .envrc derives to the Signer address recorded in §1
uv run python -c "
import os
from eth_account import Account
print(Account.from_key(os.environ['POLY_PRIVATE_KEY']).address)
"
# expect: matches §1 Signer address exactly

# Funder privkey is NOT in .envrc
grep -E '^POLY_FUNDER' .envrc          # expect: no matches
grep -rE 'POLY_FUNDER_PRIVATE_KEY|POLY_FUNDER_ADDRESS' .   # expect: no matches

# .envrc and secrets dir are tight
stat -f '%Lp %N' .envrc                # expect: 600
stat -f '%Lp %N' ~/secrets/polymarket-5m   # expect: 700
```

These are the assertions in `runbooks/gates/phase-1a.sh` (task 1A gate).

## 9. Open questions / TBD

- **VPS handoff (Phase 5):** how the Signer key transitions from laptop
  `.envrc` to the Lightsail `/etc/.../envrc`. Will be designed in
  `runbooks/vps-key-handoff.md` at Phase 5 time, not now.
- **Hardware wallet purchase (Phase 7):** Ledger Nano S Plus or X; chosen
  at the $2k bankroll trigger (locked decision #12).
- **Cold-storage destination:** TBD at Phase 7. Could be a second hardware
  wallet, a paper backup, or a multisig. Decision deferred until we have
  $200+ to actually move there.
