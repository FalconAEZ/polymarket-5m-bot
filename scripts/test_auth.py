"""End-to-end auth smoke test against clob.polymarket.com — no funds required.

Validates the full L1 + L2 auth stack before any wallet is funded (locked
decision #13). Reads the four POLY_* env vars, constructs a ClobClient with
the trading-flavored params we will use in Phase 1B (signature_type=0,
funder=Signer.address), then runs two assertions:
  (1) local signer wiring — client.get_address() matches the address derived
      from POLY_PRIVATE_KEY directly via eth-account; pure local check.
  (2) L2 round-trip — a Level-2 authenticated REST call to /auth/api-keys
      returns a list containing POLY_API_KEY; proves L2 HMAC sign works.
Both must pass. Failure exits non-zero; do not move money to the Signer
until this exits 0. See design/test_auth.md for full design.
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
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
REQUIRED_ENV = (
    "POLY_PRIVATE_KEY",
    "POLY_API_KEY",
    "POLY_API_SECRET",
    "POLY_API_PASSPHRASE",
)


def validate_env(env: dict[str, str]) -> tuple[str, ApiCreds]:
    """Read and validate the four POLY_* env vars; return (signer_key, ApiCreds).

    Aborts with exit 2 if any var is missing, exit 3 if any is malformed.
    Validation runs BEFORE any network call so the operator sees an
    unambiguous local diagnosis on copy-paste error rather than an opaque
    Polymarket auth-fail response.
    """
    missing = [name for name in REQUIRED_ENV if not env.get(name)]
    if missing:
        print(
            "error: the following env vars are not set: "
            f"{', '.join(missing)}. Complete tasks 1.1 (genwallets) and 1.2 "
            "(derive_creds), then `direnv allow`, then re-run this.",
            file=sys.stderr,
        )
        sys.exit(2)

    signer_key = env["POLY_PRIVATE_KEY"].strip()
    if len(signer_key) != 66 or not PRIVKEY_RE.match(signer_key):
        print(
            "error: POLY_PRIVATE_KEY must be 0x + 64 hex chars. Common "
            "cause: stray whitespace or truncated paste in .envrc.",
            file=sys.stderr,
        )
        sys.exit(3)

    api_key = env["POLY_API_KEY"].strip()
    if not UUID_RE.match(api_key):
        print(
            f"error: POLY_API_KEY must be a UUID (got {len(api_key)} chars). "
            "Common cause: a multi-line paste merged two .envrc lines.",
            file=sys.stderr,
        )
        sys.exit(3)

    creds = ApiCreds(
        api_key=api_key,
        api_secret=env["POLY_API_SECRET"].strip(),
        api_passphrase=env["POLY_API_PASSPHRASE"].strip(),
    )
    return signer_key, creds


def make_client(signer_key: str, creds: ApiCreds) -> ClobClient:
    """Construct the ClobClient with the full trading-flavored params.

    `signature_type=0` (EOA) and `funder=Signer.address` per OD-4c. We use
    the same construction here as Phase 1B's test_gasless_order.py will, so
    a green 1.3 maximally de-risks 1B.
    """
    address = Account.from_key(signer_key).address
    return ClobClient(
        CLOB_HOST,
        key=signer_key,
        chain_id=POLYGON,
        creds=creds,
        signature_type=0,
        funder=address,
    )


def assert_local_signer(client: ClobClient, expected_address: str) -> None:
    """Check (1) — client.get_address() returns the expected Signer address.

    `get_address()` is local-only in py-clob-client (no network). Mismatch
    here means the ClobClient was constructed with a different key than
    `expected_address` was derived from — a wiring bug, exit code 4.
    """
    got = client.get_address()
    if got != expected_address:
        print(
            f"error: client.get_address() = {got} but expected {expected_address}. "
            "ClobClient was constructed with a different key than the env "
            "POLY_PRIVATE_KEY resolves to. This is a wiring bug.",
            file=sys.stderr,
        )
        sys.exit(4)
    print(f"  ✓ local signer address: {got}")


def assert_l2_roundtrip(client: ClobClient, expected_api_key: str) -> None:
    """Check (2) — L2-authenticated GET /auth/api-keys returns expected_api_key.

    Single signed network call. The response is the list of api_keys
    registered to this address; it must include the one we just put in
    .envrc via 1.2. If the call returns 401/403, py-clob-client raises;
    we let the stack trace propagate so the operator sees Polymarket's
    own error reason rather than a guessed paraphrase.
    """
    print(f"  · calling {CLOB_HOST}/auth/api-keys (L2-signed) ...", file=sys.stderr)
    response = client.get_api_keys()
    keys = _extract_api_keys(response)
    if expected_api_key not in keys:
        print(
            f"error: L2 round-trip succeeded but POLY_API_KEY ({expected_api_key}) "
            f"is not in the returned api-key list ({len(keys)} keys returned). "
            "Most likely cause: stale POLY_API_KEY in .envrc — re-run 1.2.",
            file=sys.stderr,
        )
        sys.exit(4)
    print("  ✓ L2 round-trip OK (api_key matches)")


def _extract_api_keys(response: object) -> list[str]:
    """Normalize get_api_keys output across the two shapes the API has used.

    Older py-clob-client versions return `{"apiKeys": [...]}`; newer return a
    bare list. We accept both so a library bump doesn't silently break the
    gate. Anything else falls through to an empty list — the assertion in
    `assert_l2_roundtrip` will fail with a clear message.
    """
    if isinstance(response, list):
        return [str(k) for k in response]
    if isinstance(response, dict) and "apiKeys" in response:
        return [str(k) for k in response["apiKeys"]]
    return []


def main(argv: list[str]) -> int:
    """Wire up the validation, client construction, and the two assertions.

    Returns 0 on success. Non-zero exits happen inside the helpers via
    sys.exit so the exit code uniquely identifies the failed step.
    """
    del argv  # this script takes no args
    signer_key, creds = validate_env(dict(os.environ))
    expected_address = Account.from_key(signer_key).address

    client = make_client(signer_key, creds)
    assert_local_signer(client, expected_address)
    assert_l2_roundtrip(client, creds.api_key)

    print(f"  Signer: {expected_address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
