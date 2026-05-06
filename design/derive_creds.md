# Design — `scripts/derive_creds.py` (Phase 1A · task 1.2)

> Purpose: derive Polymarket L2 API credentials (`POLY_API_KEY`,
> `POLY_API_SECRET`, `POLY_API_PASSPHRASE`) from the Signer private key already
> in `.envrc` (`POLY_PRIVATE_KEY`). The derivation is a single L1 EIP-712
> signature over Polymarket's `ClobAuthDomain` — no on-chain transaction, no
> wallet balance required. Output format is shell-`export`-line directly
> appendable to `.envrc`.
>
> Anchors: [`agent-skills/authentication.md`](../../.claude/skills/agent-skills/authentication.md)
> §"Create / Derive Credentials"; [`design/gasless.md`](gasless.md) §4
> (`signature_type=0`, EOA `funder` = Signer address); locked decisions
> [#13 derive → sign → fund], [#20 Phase 1A scope]; [RUNBOOK §1.2](../RUNBOOK.md).

---

## 1. What L2 derivation actually is

L1 = wallet ownership proof via EIP-712 signature over `ClobAuthDomain`. Anyone
with the Signer privkey can sign. L2 = HMAC-SHA256 over a per-request payload,
keyed by `(api_key, api_secret, api_passphrase)`.

`create_or_derive_api_creds()` does the L1 sig and calls
`POST /auth/api-key` (creates if first time) or `GET /auth/derive-api-key`
(returns the existing triple) on `clob.polymarket.com`. Either way the response
is the same three-string `ApiCreds(api_key, api_secret, api_passphrase)`.

**Crucially: this is idempotent.** Re-running the script returns the same
triple — the script can be re-run safely, but the operator must avoid
appending the same `export` lines twice into `.envrc`.

## 2. CLI

```bash
uv run python scripts/derive_creds.py
```

No flags. The script reads `POLY_PRIVATE_KEY` from the environment (set by
`direnv allow` after task 1.1 wrote it into `.envrc`). It does not read
`.envrc` directly.

## 3. Pre-flight validation (before any network call)

The most common Phase 1.2 failure mode is a copy-paste error in `.envrc` —
trailing whitespace, missing `0x`, or a truncated key. We catch all three
locally before hitting Polymarket so the diagnosis is unambiguous:

| Check | Failure exit | Message |
|---|---|---|
| `POLY_PRIVATE_KEY` is set in env | 2 | "POLY_PRIVATE_KEY not set. Run task 1.1 (scripts/genwallets.py) first, paste the Signer privkey into .envrc, then `direnv allow`, then re-run this." |
| Key strips to 66 chars (`0x` + 64 hex) | 3 | "POLY_PRIVATE_KEY must be 0x + 64 hex chars (got N). Common cause: trailing newline or truncated paste." |
| Key matches `^0x[0-9a-fA-F]{64}$` | 3 | "POLY_PRIVATE_KEY contains non-hex characters." |

The script does **not** check that the key is on the secp256k1 curve (any
32-byte string maps to a valid private key with cryptographically negligible
exception probability — `secrets.token_bytes(32)` is statistically guaranteed
in-curve). If this rare case ever fires, py-clob-client's L1 sign will raise
and the operator sees a stack trace; they can rerun task 1.1.

## 4. Network call

```python
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

client = ClobClient("https://clob.polymarket.com", key=signer_pk, chain_id=POLYGON)
creds = client.create_or_derive_api_creds()
```

Note we deliberately do **not** pass `signature_type` or `funder` to the
constructor for this single use of the client. Those parameters are required
for *trading*-flavored signed calls (orders, cancels, position queries). The
L1 EIP-712 sign for cred derivation only needs the key. Constructing without
them keeps the script's intent crisp: "derive only, do not trade."

`POLYGON = 137` is the chain ID Polymarket uses; we import the constant from
the library for explicitness.

## 5. Output streams

| Stream | Content |
|---|---|
| `stdout` | Three lines, `export KEY=value\n` each — directly appendable to `.envrc` via `>>`. No banner, no comments, no trailing blank line. |
| `stderr` | One-line confirmation: the Signer address (re-derived from the privkey for visibility). Used only as feedback, not parsed. |
| `.envrc` | **Not touched by the script.** Operator appends manually: `... >> .envrc`. |

Why no comments on stdout: piping `>> .envrc` adds whatever comes through
verbatim. Header lines (`# derived 2026-05-06`) would also append, growing
`.envrc` cruft on every re-run. Banner content goes to stderr where it doesn't
pollute the file.

## 6. Operator runbook

```bash
# precondition: task 1.1 done; POLY_PRIVATE_KEY in .envrc; `direnv allow` ran.

# (optional) verify the env var is set without echoing the key:
test -n "$POLY_PRIVATE_KEY" && echo "ok: POLY_PRIVATE_KEY is set"

# derive and append:
uv run python scripts/derive_creds.py >> .envrc
chmod 0600 .envrc                   # ensure perms (idempotent)
direnv allow                         # picks up the three new exports
test -n "$POLY_API_KEY"             # expect: prints nothing, exits 0
```

If the operator has previously run the script and is re-running for any reason,
they should first remove the old `POLY_API_KEY` / `POLY_API_SECRET` /
`POLY_API_PASSPHRASE` lines from `.envrc` to avoid duplicates. The derived
values themselves will be identical (deterministic from the Signer key).

## 7. Testability strategy

The actual `client.create_or_derive_api_creds()` call hits the Polymarket
server. We do not mock Polymarket's HTTP responses — that's brittle and
high-noise per anti-vibe rule #10's "Stochastic inputs injected, not imported"
intent. Instead the script is structured so the only network-touching unit is
a thin wrapper:

```python
def derive(client: ClobClient) -> ApiCreds:
    return client.create_or_derive_api_creds()
```

Tests cover the pure-Python pieces:
- `validate_signer_key` (whitespace, prefix, hex, length)
- `format_creds` (export-line shape)
- `main` exit codes for missing / malformed key (env injection via monkeypatch)
- `derive` itself is exercised once by the operator at runtime; failure is
  surfaced as a stack trace.

## 8. Failure modes & responses

| Symptom | Cause | Action |
|---|---|---|
| `POLY_PRIVATE_KEY not set` | task 1.1 not run, or `direnv allow` not run | Run task 1.1; `direnv allow`; rerun |
| Key length wrong / non-hex | Copy-paste error in `.envrc` | Open `.envrc`, fix; `direnv allow`; rerun |
| 401/403 from Polymarket | EIP-712 sig rejected (very unlikely with a correctly-derived key) | Verify the key derives the expected address (`uv run python -c "from eth_account import Account; print(Account.from_key('$POLY_PRIVATE_KEY').address)"`); compare to stderr line; rerun |
| Network error | Polymarket down, DNS, or VPN issue | Retry; check `https://clob.polymarket.com/` returns 200 in browser |

## 9. Anti-leak

- `POLY_PRIVATE_KEY` is never echoed by the script (only the derived
  *address* is sent to stderr).
- The three derived secrets *are* on stdout — that's intentional, the operator
  pipes them into `.envrc`. They are not high-value-secrets in the same sense
  as the privkey: an attacker with `POLY_API_*` can place CLOB orders signed
  as the Signer (still bad), but cannot move funds on-chain (the privkey
  alone enables that). Even so, the operator should not paste them into
  shell scrollback or non-`.envrc` destinations.
- `.envrc` perms checked separately at the gate (mode 0600).

## 10. What this design explicitly does *not* do

- Does not accept the privkey on stdin or as an arg. Env-var only — to keep
  the surface small and avoid creating yet another key-passing path.
- Does not write to `.envrc`. Append is the operator's hand step (consistent
  with task 1.1).
- Does not call any non-Polymarket endpoint. Single `https://clob.polymarket.com`
  call.
- Does not store / cache the derived creds locally. They live in `.envrc`
  only.
- Does not pass `signature_type` or `funder` — see §4.
