"""Unit tests for scripts/genwallets.py — pure-Python paths, no `age` subprocess.

Covers `generate_wallet`, `verify_age_armor`, `refuse_if_existing`,
`ensure_secrets_dir`, and the WalletRole dataclass. We deliberately do not
invoke the real `age` binary here — the encrypt path is exercised manually
by the operator at task-1.1 runtime against the live tty. Anti-vibe rule
#2 says bugs land as failing tests first; this file is the regression guard
for the pure-Python invariants the script depends on.
"""

from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path

import pytest

# Load scripts/genwallets.py as a module without requiring it to live under
# src/ (it is intentionally a one-shot script, not a package).
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "genwallets.py"
_SPEC = importlib.util.spec_from_file_location("genwallets", _SCRIPT_PATH)
assert _SPEC is not None
assert _SPEC.loader is not None
genwallets = importlib.util.module_from_spec(_SPEC)
sys.modules["genwallets"] = genwallets
_SPEC.loader.exec_module(genwallets)


def test_generate_wallet_returns_valid_eoa() -> None:
    """generate_wallet returns a 0x-prefixed 64-hex-char privkey + 0x-prefixed
    40-hex-char checksummed address; 100 invocations all unique."""
    seen_addrs: set[str] = set()
    seen_keys: set[bytes] = set()
    for _ in range(100):
        address, privkey = genwallets.generate_wallet()
        assert address.startswith("0x")
        assert len(address) == 42  # 0x + 40 hex
        assert privkey.startswith(b"0x")
        assert len(privkey) == 66  # 0x + 64 hex
        seen_addrs.add(address)
        seen_keys.add(bytes(privkey))
    assert len(seen_addrs) == 100, "address collision under CSPRNG — entropy broken"
    assert len(seen_keys) == 100, "privkey collision under CSPRNG — entropy broken"


def test_generate_wallet_address_matches_privkey() -> None:
    """The returned address is the eth-account-derived address of the privkey."""
    from eth_account import Account

    address, privkey_bytes = genwallets.generate_wallet()
    privkey_hex = bytes(privkey_bytes).decode("ascii")
    rederived = Account.from_key(privkey_hex).address
    assert rederived == address


def test_verify_age_armor_accepts_real_armor(tmp_path: Path) -> None:
    """A file starting with the v1 armor prefix is accepted (returns None)."""
    target = tmp_path / "fake.age"
    target.write_bytes(genwallets.AGE_HEADER_PREFIX + b"\nrest of file...")
    genwallets.verify_age_armor(target)  # should not raise / exit


def test_verify_age_armor_rejects_plaintext(tmp_path: Path) -> None:
    """A file that doesn't start with v1 armor causes SystemExit(4)."""
    target = tmp_path / "fake.age"
    target.write_bytes(b"not an age file at all")
    with pytest.raises(SystemExit) as excinfo:
        genwallets.verify_age_armor(target)
    assert excinfo.value.code == 4


def test_refuse_if_existing_aborts_without_flag(tmp_path: Path) -> None:
    """An existing target file aborts with SystemExit(5) when overwrite off."""
    target = tmp_path / "funder.age"
    target.write_bytes(b"existing content")
    with pytest.raises(SystemExit) as excinfo:
        genwallets.refuse_if_existing(genwallets.FUNDER, target, allow_overwrite=False)
    assert excinfo.value.code == 5


def test_refuse_if_existing_passes_with_flag(tmp_path: Path) -> None:
    """An existing target file is allowed through when --allow-overwrite is on."""
    target = tmp_path / "funder.age"
    target.write_bytes(b"existing content")
    # No SystemExit expected.
    genwallets.refuse_if_existing(genwallets.FUNDER, target, allow_overwrite=True)


def test_refuse_if_existing_passes_when_absent(tmp_path: Path) -> None:
    """A non-existent target is fine regardless of the flag."""
    target = tmp_path / "funder.age"
    genwallets.refuse_if_existing(genwallets.FUNDER, target, allow_overwrite=False)


def test_ensure_secrets_dir_creates_at_0700(tmp_path: Path) -> None:
    """A non-existent directory is created at mode 0700."""
    target = tmp_path / "nested" / "secrets-dir"
    genwallets.ensure_secrets_dir(target)
    assert target.is_dir()
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o700


def test_ensure_secrets_dir_accepts_existing_0700(tmp_path: Path) -> None:
    """An existing directory at mode 0700 is accepted without modification."""
    target = tmp_path / "existing"
    target.mkdir(mode=0o700)
    genwallets.ensure_secrets_dir(target)
    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o700


def test_ensure_secrets_dir_rejects_loose_perms(tmp_path: Path) -> None:
    """An existing directory with group/other bits set causes SystemExit(2)."""
    target = tmp_path / "loose"
    target.mkdir(mode=0o755)
    with pytest.raises(SystemExit) as excinfo:
        genwallets.ensure_secrets_dir(target)
    assert excinfo.value.code == 2


def test_walletrole_filename() -> None:
    """WalletRole.filename joins lowercase name with the .age suffix."""
    assert genwallets.FUNDER.filename == "funder.age"
    assert genwallets.SIGNER.filename == "signer.age"


def test_walletrole_is_frozen() -> None:
    """WalletRole is frozen — no accidental mutation of FUNDER/SIGNER constants."""
    with pytest.raises((AttributeError, Exception)):
        genwallets.FUNDER.name = "tampered"  # type: ignore[misc]
