# Design — `scripts/test_auth.py` (Phase 1A · task 1.3)

> Purpose: prove the full L1 + L2 auth stack works end-to-end against
> `clob.polymarket.com` BEFORE any wallet is funded. Locked decision #13:
> "Phase 1 order: derive creds → test sign → fund." This script is the
> middle step. If it does not exit 0, **do not move money** to the Signer.
>
> Anchors: [`design/gasless.md`](gasless.md) §4 (`signature_type=0`, EOA
> `funder` = Signer address); [`agent-skills/authentication.md`](../../.claude/skills/agent-skills/authentication.md);
> locked decisions [#13, #20]; [RUNBOOK §1.3](../RUNBOOK.md).

---

## 1. What "auth works" means in two layers

L1 = wallet ownership: an EIP-712 signature against `ClobAuthDomain` proves
control of the Signer key. Used by `derive_creds.py` (1.2) to mint the L2
triple. **Already proven** by 1.2 succeeding.

L2 = authenticated request: an HMAC-SHA256 signature over each REST call,
keyed by `(api_key, api_secret, api_passphrase)`. Used for every
`/v1/trade/*` endpoint in Phase 1B. **Not yet proven.**

This script proves L2 by making one signed read-only call and asserting the
response is consistent with the Signer.

## 2. Two assertions, both must pass

| # | Check | What it proves | How |
|---|---|---|---|
| 1 | **Local signer wiring.** `client.get_address()` matches `Account.from_key(POLY_PRIVATE_KEY).address`. | The ClobClient was constructed with a privkey that resolves to the address we expect. Cheap, no network. | Pure-Python comparison. |
| 2 | **L2 round-trip.** `client.get_api_keys()` (Level-2 authenticated REST) returns a list that contains `POLY_API_KEY`. | The full L2 HMAC sign + validate against Polymarket's auth service works. | Single signed HTTPS call. |

Both must pass. (1) without (2) means we have local-only wiring but L2 is
broken (most often: copy-paste error in `POLY_API_*` lines). (2) without (1)
is impossible by construction (the call uses the local key).

## 3. ClobClient construction

We construct with the **full** trading-flavored params — `signature_type=0`
and `funder=Signer.address` — even though `get_api_keys()` only needs L2 auth
(not order-flavored signatures). Reasons:

1. **Phase 1B parity.** Phase 1B's `test_gasless_order.py` will use the same
   construction. If we tested L2 here with a stripped-down client that
   happens to work but Phase 1B's full client doesn't, we'd discover that
   problem too late (after we've funded).
2. **Single source of truth.** A `make_client()` factory in this script
   becomes the canonical client builder; `test_gasless_order.py` will reuse
   the same code path in 1B.

The construction looks like:

```python
client = ClobClient(
    "https://clob.polymarket.com",
    key=signer_key,
    chain_id=137,
    creds=ApiCreds(api_key=..., api_secret=..., api_passphrase=...),
    signature_type=0,
    funder=Account.from_key(signer_key).address,
)
```

## 4. Pre-flight env validation

Four env vars are required: `POLY_PRIVATE_KEY`, `POLY_API_KEY`,
`POLY_API_SECRET`, `POLY_API_PASSPHRASE`. Validate each is set before touching
the network:

| Failure | Exit | Message |
|---|---|---|
| Any env var missing | 2 | "POLY_*: which one is missing; complete tasks 1.1 (genwallets) and 1.2 (derive_creds) first." |
| `POLY_PRIVATE_KEY` malformed | 3 | (same regex check as 1.2) |
| `POLY_API_KEY` not a UUID | 3 | "POLY_API_KEY must be a UUID; common cause: copy-paste of multi-line creds." |

The L2 secret format isn't strictly UUID; we only enforce structural sanity
on `POLY_API_KEY` since that's the most common copy-paste failure.

## 5. Output streams

| Stream | Content |
|---|---|
| `stdout` | Two confirmation lines, one per assertion. Final line: the Signer address (so a human reading the output can copy/verify it against `wallet-ops.md`). |
| `stderr` | One-line banner per network call. |
| Exit code | 0 = both checks pass. 2/3/4 = specific failure. |

The script is the gate's authority on auth health, so its stdout is captured
into `runbooks/gate-evidence/phase-1a.txt` by the gate script.

## 6. Operator runbook

```bash
# precondition: tasks 1.1 + 1.2 done; .envrc has all four POLY_* lines.

uv run python scripts/test_auth.py
# expected stdout (in order):
#     ✓ local signer address: 0x...
#     ✓ L2 round-trip OK (api_key matches)
#     Signer: 0x...
# exit code: 0
```

If the call exits non-zero, **do not proceed to task 1.4 (Phase 1B funding)**.
Diagnostics by exit code:

| Exit | Meaning | Fix |
|---|---|---|
| 0 | Both checks passed | Proceed to 1.6 / gate |
| 2 | Env var missing | Re-run 1.1 / 1.2; `direnv allow` |
| 3 | Env var malformed | Re-paste from 1.2 output; check for stray whitespace; `direnv allow` |
| 4 | L2 round-trip succeeded but `api_key` not in returned list | Most likely: `.envrc` has stale creds from an earlier run. Re-run 1.2. |
| Stack trace from `py-clob-client` | Polymarket returned non-2xx (auth fail) | Compare derived address to expected; check `clob.polymarket.com` is up |

## 7. Testability

Same pattern as 1.2: a `make_client()` factory + a `verify(client, address)`
function so unit tests can pass a stub client and exercise the assertion
logic without hitting the network. The Polymarket call itself is exercised
by the operator at runtime; that's the whole point of 1.3.

## 8. What this design explicitly does *not* do

- Does not place, modify, or cancel any order.
- Does not query market or position state.
- Does not write to `.envrc` or any other file. Read-only.
- Does not test signature_type=1 or signature_type=2 paths — we are EOA-only
  per OD-4c.
- Does not require any USDC, MATIC, or token allowance — by design (locked
  decision #13).
