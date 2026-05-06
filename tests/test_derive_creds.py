"""Unit tests for scripts/derive_creds.py — pure-Python paths only.

Covers `validate_signer_key`, `format_creds`, `make_client` (constructs
without raising), and `main`'s exit-code matrix for missing / malformed
env values. The Polymarket-network call inside `derive` is exercised at
runtime by the operator and surfaced via stack trace if it fails — see
design/derive_creds.md §7 for the testability rationale.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "derive_creds.py"
_SPEC = importlib.util.spec_from_file_location("derive_creds", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
derive_creds = importlib.util.module_from_spec(_SPEC)
sys.modules["derive_creds"] = derive_creds
_SPEC.loader.exec_module(derive_creds)


# A cryptographically valid throwaway secp256k1 key (well-known: 1, padded).
# Used only in test fixtures; never funded; never used outside tests.
_FIXTURE_KEY = "0x0000000000000000000000000000000000000000000000000000000000000001"


@dataclass(frozen=True)
class _StubCreds:
    """Mimics the py_clob_client ApiCreds dataclass for format_creds tests."""

    api_key: str
    api_secret: str
    api_passphrase: str


def test_validate_signer_key_strips_whitespace() -> None:
    """Trailing/leading whitespace is stripped to canonical form."""
    raw = f"  {_FIXTURE_KEY}\n  "
    assert derive_creds.validate_signer_key(raw) == _FIXTURE_KEY


def test_validate_signer_key_accepts_uppercase_hex() -> None:
    """Mixed-case hex is accepted (Ethereum is case-insensitive)."""
    upper = "0x" + ("AB" * 32)
    assert derive_creds.validate_signer_key(upper) == upper


def test_validate_signer_key_missing_aborts_with_2() -> None:
    """Missing env var aborts with exit 2."""
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.validate_signer_key(None)
    assert excinfo.value.code == 2


def test_validate_signer_key_empty_aborts_with_2() -> None:
    """Empty string is treated as missing (exit 2)."""
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.validate_signer_key("")
    assert excinfo.value.code == 2


def test_validate_signer_key_short_aborts_with_3() -> None:
    """Length < 66 aborts with exit 3."""
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.validate_signer_key("0xabcd")
    assert excinfo.value.code == 3


def test_validate_signer_key_long_aborts_with_3() -> None:
    """Length > 66 aborts with exit 3."""
    too_long = _FIXTURE_KEY + "00"
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.validate_signer_key(too_long)
    assert excinfo.value.code == 3


def test_validate_signer_key_no_prefix_aborts_with_3() -> None:
    """Missing 0x prefix aborts with exit 3."""
    no_prefix = "0" * 66  # 66 chars, no 0x
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.validate_signer_key(no_prefix)
    assert excinfo.value.code == 3


def test_validate_signer_key_non_hex_aborts_with_3() -> None:
    """Non-hex chars in the body abort with exit 3."""
    non_hex = "0x" + ("zz" * 32)
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.validate_signer_key(non_hex)
    assert excinfo.value.code == 3


def test_format_creds_emits_three_export_lines() -> None:
    """Output is exactly three export lines, newline-terminated, no comments."""
    stub = _StubCreds(
        api_key="11111111-2222-3333-4444-555555555555",
        api_secret="c2VjcmV0LWJhc2U2NA==",
        api_passphrase="passphrase-string",
    )
    out = derive_creds.format_creds(stub)
    lines = out.split("\n")
    # Three exports + trailing newline yields a trailing empty element after split.
    assert lines == [
        "export POLY_API_KEY=11111111-2222-3333-4444-555555555555",
        "export POLY_API_SECRET=c2VjcmV0LWJhc2U2NA==",
        "export POLY_API_PASSPHRASE=passphrase-string",
        "",
    ]


def test_format_creds_no_header_comment() -> None:
    """Output does not start with '#'; piping `>> .envrc` should not add cruft."""
    stub = _StubCreds(api_key="a", api_secret="b", api_passphrase="c")
    out = derive_creds.format_creds(stub)
    assert not out.startswith("#")


def test_make_client_constructs_without_network() -> None:
    """make_client returns a ClobClient pinned to chain 137; no network call yet."""
    client = derive_creds.make_client(_FIXTURE_KEY)
    # ClobClient stores chain_id on the instance; verify the constant.
    assert derive_creds.POLYGON == 137
    # Constructed object exists and has the expected host attribute.
    assert client.host == derive_creds.CLOB_HOST


def test_main_missing_env_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() exits 2 when POLY_PRIVATE_KEY is unset (no network call attempted)."""
    monkeypatch.delenv("POLY_PRIVATE_KEY", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.main([])
    assert excinfo.value.code == 2


def test_main_malformed_env_returns_3(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() exits 3 when POLY_PRIVATE_KEY is malformed (no network call attempted)."""
    monkeypatch.setenv("POLY_PRIVATE_KEY", "0xnope")
    with pytest.raises(SystemExit) as excinfo:
        derive_creds.main([])
    assert excinfo.value.code == 3


def test_derive_uses_create_or_derive_api_creds() -> None:
    """derive() forwards to client.create_or_derive_api_creds — covers the
    one-line wrapper without hitting the network."""

    class _StubClient:
        def __init__(self) -> None:
            self.calls = 0

        def create_or_derive_api_creds(self) -> _StubCreds:
            self.calls += 1
            return _StubCreds(api_key="k", api_secret="s", api_passphrase="p")

    stub = _StubClient()
    out = derive_creds.derive(stub)  # type: ignore[arg-type]
    assert stub.calls == 1
    assert out.api_key == "k"
    assert out.api_secret == "s"
    assert out.api_passphrase == "p"
