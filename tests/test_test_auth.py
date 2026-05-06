"""Unit tests for scripts/test_auth.py — pure-Python paths only.

Covers env-var validation matrix, _extract_api_keys normalization,
assert_local_signer wiring check, assert_l2_roundtrip success/failure,
and make_client construction. The Polymarket round-trip itself is
exercised at runtime by the operator (anti-vibe rule #2 doesn't say
unit-test the network; it says inject the network behind an interface,
which is what the stub-client pattern below does).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "test_auth.py"
_SPEC = importlib.util.spec_from_file_location("ta_module", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
ta_module = importlib.util.module_from_spec(_SPEC)
sys.modules["ta_module"] = ta_module
_SPEC.loader.exec_module(ta_module)


# Throwaway secp256k1 key (well-known: 1, padded). Not funded; tests only.
_FIXTURE_KEY = "0x0000000000000000000000000000000000000000000000000000000000000001"
_FIXTURE_ADDR = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"  # canonical for the above
_FIXTURE_API_KEY = "11111111-2222-3333-4444-555555555555"
_FIXTURE_ENV = {
    "POLY_PRIVATE_KEY": _FIXTURE_KEY,
    "POLY_API_KEY": _FIXTURE_API_KEY,
    "POLY_API_SECRET": "c2VjcmV0LWJhc2U2NA==",
    "POLY_API_PASSPHRASE": "passphrase-string",
}


@dataclass
class _StubClient:
    """Mimics ClobClient's get_address + get_api_keys for assertion tests."""

    address: str
    api_keys_response: object

    def get_address(self) -> str:
        return self.address

    def get_api_keys(self) -> object:
        return self.api_keys_response


def test_validate_env_happy_path() -> None:
    """All four env vars set → returns (signer_key, ApiCreds)."""
    signer_key, creds = ta_module.validate_env(dict(_FIXTURE_ENV))
    assert signer_key == _FIXTURE_KEY
    assert creds.api_key == _FIXTURE_API_KEY


def test_validate_env_strips_whitespace() -> None:
    """Trailing whitespace on POLY_PRIVATE_KEY is stripped."""
    env = dict(_FIXTURE_ENV)
    env["POLY_PRIVATE_KEY"] = f"  {_FIXTURE_KEY}\n"
    signer_key, _ = ta_module.validate_env(env)
    assert signer_key == _FIXTURE_KEY


@pytest.mark.parametrize("missing", ta_module.REQUIRED_ENV)
def test_validate_env_missing_var_aborts_with_2(missing: str) -> None:
    """Removing any required env var aborts with exit 2."""
    env = dict(_FIXTURE_ENV)
    del env[missing]
    with pytest.raises(SystemExit) as excinfo:
        ta_module.validate_env(env)
    assert excinfo.value.code == 2


def test_validate_env_malformed_privkey_aborts_with_3() -> None:
    """Malformed privkey aborts with exit 3 (not 2 — env is set, just bad)."""
    env = dict(_FIXTURE_ENV)
    env["POLY_PRIVATE_KEY"] = "0xnope"
    with pytest.raises(SystemExit) as excinfo:
        ta_module.validate_env(env)
    assert excinfo.value.code == 3


def test_validate_env_malformed_api_key_aborts_with_3() -> None:
    """Non-UUID POLY_API_KEY aborts with exit 3."""
    env = dict(_FIXTURE_ENV)
    env["POLY_API_KEY"] = "not-a-uuid"
    with pytest.raises(SystemExit) as excinfo:
        ta_module.validate_env(env)
    assert excinfo.value.code == 3


def test_extract_api_keys_handles_list_shape() -> None:
    """Bare-list response shape is accepted."""
    keys = ta_module._extract_api_keys(["a", "b", "c"])
    assert keys == ["a", "b", "c"]


def test_extract_api_keys_handles_dict_shape() -> None:
    """`{"apiKeys": [...]}` response shape is accepted."""
    keys = ta_module._extract_api_keys({"apiKeys": ["x", "y"]})
    assert keys == ["x", "y"]


def test_extract_api_keys_returns_empty_for_unknown_shape() -> None:
    """Unknown shapes degrade to empty list (assertion will then fail loudly)."""
    keys = ta_module._extract_api_keys({"unexpected": "shape"})
    assert keys == []


def test_assert_local_signer_passes_on_match(capsys: pytest.CaptureFixture[str]) -> None:
    """Matching addresses prints the OK line and returns None."""
    stub = _StubClient(address=_FIXTURE_ADDR, api_keys_response=[])
    ta_module.assert_local_signer(stub, _FIXTURE_ADDR)  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert "✓ local signer address" in captured.out
    assert _FIXTURE_ADDR in captured.out


def test_assert_local_signer_fails_on_mismatch() -> None:
    """Mismatch aborts with exit 4."""
    stub = _StubClient(address="0xWrong", api_keys_response=[])
    with pytest.raises(SystemExit) as excinfo:
        ta_module.assert_local_signer(stub, _FIXTURE_ADDR)  # type: ignore[arg-type]
    assert excinfo.value.code == 4


def test_assert_l2_roundtrip_passes_when_key_present(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Expected api_key in returned list → OK line printed, exit 0 path."""
    stub = _StubClient(
        address=_FIXTURE_ADDR,
        api_keys_response=[_FIXTURE_API_KEY, "other-key"],
    )
    ta_module.assert_l2_roundtrip(stub, _FIXTURE_API_KEY)  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert "L2 round-trip OK" in captured.out


def test_assert_l2_roundtrip_fails_when_key_missing() -> None:
    """Expected api_key NOT in returned list → exit 4."""
    stub = _StubClient(
        address=_FIXTURE_ADDR,
        api_keys_response=["different-key"],
    )
    with pytest.raises(SystemExit) as excinfo:
        ta_module.assert_l2_roundtrip(stub, _FIXTURE_API_KEY)  # type: ignore[arg-type]
    assert excinfo.value.code == 4


def test_assert_l2_roundtrip_handles_dict_response(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Older response shape (dict with apiKeys) works through the normalizer."""
    stub = _StubClient(
        address=_FIXTURE_ADDR,
        api_keys_response={"apiKeys": [_FIXTURE_API_KEY]},
    )
    ta_module.assert_l2_roundtrip(stub, _FIXTURE_API_KEY)  # type: ignore[arg-type]
    captured = capsys.readouterr()
    assert "L2 round-trip OK" in captured.out


def test_make_client_returns_clobclient_with_signer_funder() -> None:
    """make_client returns a ClobClient whose funder = Signer's address."""
    creds = ta_module.ApiCreds(
        api_key=_FIXTURE_API_KEY,
        api_secret="c2VjcmV0LWJhc2U2NA==",
        api_passphrase="passphrase-string",
    )
    client = ta_module.make_client(_FIXTURE_KEY, creds)
    assert client.host == ta_module.CLOB_HOST
    # py-clob-client stores the funder as `self.funder_address` or similar;
    # the canonical way to verify is via the local get_address.
    assert client.get_address() == _FIXTURE_ADDR


def test_main_missing_env_returns_2(monkeypatch: pytest.MonkeyPatch) -> None:
    """main() exits 2 when any required var is unset; no network call."""
    for name in ta_module.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as excinfo:
        ta_module.main([])
    assert excinfo.value.code == 2
