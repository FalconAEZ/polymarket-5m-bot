"""Derive Polymarket L2 API credentials from the Signer private key in env.

Reads POLY_PRIVATE_KEY from the environment, validates its shape locally
(prefix, length, hex), constructs a py-clob-client ClobClient pinned to
chain_id=137, and calls create_or_derive_api_creds() — a single L1 EIP-712
signature against ClobAuthDomain that needs no on-chain funds. Emits three
shell `export` lines on stdout (directly appendable to .envrc via `>>`)
and the Signer address on stderr for visual confirmation. The private key
is never echoed back. See design/derive_creds.md for full design and
failure-mode table.
"""

from __future__ import annotations

import os
import re
import sys

from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON

CLOB_HOST = "https://clob.polymarket.com"
PRIVKEY_RE = re.compile(r"^0x[0-9a-fA-F]{64}$")


def validate_signer_key(raw: str | None) -> str:
    """Validate POLY_PRIVATE_KEY shape and return a stripped, canonical 0x-hex string.

    Exits the process with a specific code on failure so the operator gets an
    unambiguous diagnosis without ever seeing the (possibly garbled) value
    echoed back. We catch the three highest-frequency copy-paste defects:
    missing env var, wrong length, non-hex characters.
    """
    if raw is None or raw == "":
        print(
            "error: POLY_PRIVATE_KEY not set in env. Run task 1.1 "
            "(scripts/genwallets.py) first, paste the Signer privkey into "
            ".envrc, then `direnv allow`, then re-run this.",
            file=sys.stderr,
        )
        sys.exit(2)
    candidate = raw.strip()
    if len(candidate) != 66:
        print(
            f"error: POLY_PRIVATE_KEY must be 0x + 64 hex chars (got "
            f"length {len(candidate)}). Common cause: trailing newline, "
            "missing 0x prefix, or truncated paste.",
            file=sys.stderr,
        )
        sys.exit(3)
    if not PRIVKEY_RE.match(candidate):
        print(
            "error: POLY_PRIVATE_KEY contains non-hex characters or is " "missing the 0x prefix.",
            file=sys.stderr,
        )
        sys.exit(3)
    return candidate


def format_creds(creds: ApiCreds) -> str:
    """Format an ApiCreds triple as three shell `export KEY=value` lines.

    Output is intentionally bare — no header comments, no trailing blank
    line — so `>> .envrc` appends only the three lines that need to live
    in the file. Returns the multi-line string with a trailing newline so
    each export occupies its own line in `.envrc`.
    """
    return (
        f"export POLY_API_KEY={creds.api_key}\n"
        f"export POLY_API_SECRET={creds.api_secret}\n"
        f"export POLY_API_PASSPHRASE={creds.api_passphrase}\n"
    )


def derive(client: ClobClient) -> ApiCreds:
    """Thin wrapper around ClobClient.create_or_derive_api_creds.

    The single L1 EIP-712 sign + handshake step. Isolated as its own
    function so tests can pass a stub client (returning a fixture ApiCreds)
    without monkeypatching the network library. See design/derive_creds.md
    §7 for the testability rationale.
    """
    return client.create_or_derive_api_creds()


def make_client(signer_key: str) -> ClobClient:
    """Construct the ClobClient for L1 cred derivation only.

    No signature_type and no funder — those are required for trading
    signatures in Phase 1B (orders, cancels), not for the EIP-712 sign
    against ClobAuthDomain that backs create_or_derive_api_creds. Keeping
    them out of this construction makes the script's intent crisp: derive
    only, never trade.
    """
    return ClobClient(CLOB_HOST, key=signer_key, chain_id=POLYGON)


def main(argv: list[str]) -> int:
    """Top-level entry. Reads env, validates the key, calls Polymarket,
    emits export lines on stdout. Exit codes per design/derive_creds.md §3."""
    del argv  # this script takes no args; kept for symmetric main signature
    signer_key = validate_signer_key(os.environ.get("POLY_PRIVATE_KEY"))
    address = Account.from_key(signer_key).address
    print(f"  Signer address: {address}", file=sys.stderr)
    print(f"  deriving L2 creds at {CLOB_HOST} ...", file=sys.stderr)

    client = make_client(signer_key)
    creds = derive(client)

    print(
        "  done. Append the lines below to .envrc, then `direnv allow`.\n",
        file=sys.stderr,
    )
    sys.stdout.write(format_creds(creds))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
