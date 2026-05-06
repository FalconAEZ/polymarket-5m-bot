"""Offline generator for the Polymarket bot's Funder + Signer EOA wallet pair.

Generates two independent secp256k1 keys via secrets.token_bytes(32), derives
their Ethereum addresses with eth_account, and pipes each plaintext private
key directly into a child `age -p` subprocess that writes the age-encrypted
output to ~/secrets/polymarket-5m/{funder,signer}.age. The plaintext key never
touches the filesystem — not in /tmp, not in shell history, not in scrollback
shadow files. The Funder private key never appears on stdout; the Signer
private key is printed exactly once on stdout (with a clear banner) so the
operator can paste it into .envrc as POLY_PRIVATE_KEY=. See
design/genwallets.md for full rationale, anti-leak checklist, and CLI spec.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount

AGE_HEADER_PREFIX = b"age-encryption.org/v1"
DEFAULT_SECRETS_DIR = Path.home() / "secrets" / "polymarket-5m"


@dataclass(frozen=True)
class WalletRole:
    """One of the two wallet roles the script generates.

    `name` is the lowercase role identifier used in filenames; `display` is
    the uppercase label shown to the operator on stderr.
    """

    name: str
    display: str

    @property
    def filename(self) -> str:
        return f"{self.name}.age"


FUNDER = WalletRole(name="funder", display="FUNDER")
SIGNER = WalletRole(name="signer", display="SIGNER")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments. Returns an argparse Namespace with `secrets_dir`
    (Path) and `allow_overwrite` (bool); see design/genwallets.md §4."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate Funder + Signer EOA wallets, age-encrypt them to "
            "~/secrets/polymarket-5m/, and print the Signer privkey once."
        ),
    )
    parser.add_argument(
        "--secrets-dir",
        type=Path,
        default=DEFAULT_SECRETS_DIR,
        help="Directory for {funder,signer}.age (default: ~/secrets/polymarket-5m).",
    )
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="Permit overwriting existing .age files. Default refuses (destructive).",
    )
    return parser.parse_args(argv)


def ensure_age_available() -> str:
    """Resolve the `age` binary on PATH and return its absolute path.

    Aborts with exit 2 if `age` is not installed. We pin the resolved path
    so subprocess invocations don't rely on PATH at exec time (S607-clean).
    """
    resolved = shutil.which("age")
    if resolved is None:
        print(
            "error: `age` not found on PATH. Install with `brew install age` and rerun.",
            file=sys.stderr,
        )
        sys.exit(2)
    return resolved


def ensure_secrets_dir(path: Path) -> None:
    """Create the secrets directory at mode 0700 if it does not exist;
    abort with exit 2 if it exists with broader permissions."""
    if path.exists():
        if not path.is_dir():
            print(f"error: {path} exists and is not a directory.", file=sys.stderr)
            sys.exit(2)
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            print(
                f"error: {path} mode is {oct(mode)}; expected 0700 "
                f"(group/other bits set). Run `chmod 0700 {path}` and rerun.",
                file=sys.stderr,
            )
            sys.exit(2)
        return
    path.mkdir(parents=True, mode=0o700, exist_ok=False)


def generate_wallet() -> tuple[str, bytearray]:
    """Generate a fresh EOA wallet from 32 bytes of CSPRNG entropy.

    Returns (address, privkey_hex_bytes). The privkey is returned as a mutable
    bytearray so the caller can `bytearray.__setitem__` zero-wipe it after
    piping to age. `secrets.token_bytes` wraps `os.urandom`; on macOS that
    routes through `getentropy(3)` → kernel CSPRNG.
    """
    entropy = secrets.token_bytes(32)
    account: LocalAccount = Account.from_key(entropy)
    privkey_hex = account.key.hex()
    if not privkey_hex.startswith("0x"):
        privkey_hex = "0x" + privkey_hex
    return account.address, bytearray(privkey_hex.encode("ascii"))


def encrypt_to_age(age_bin: str, plaintext: bytearray, output_path: Path) -> None:
    """Pipe plaintext into `age -p -o output_path` via stdin.

    `age -p` reads the passphrase from /dev/tty, so the stdin pipe carries
    plaintext only — no filesystem exposure. Plaintext is wiped in-place
    after the subprocess returns successfully. Aborts the script with exit
    code 3 if age returns non-zero. `age_bin` is the absolute path resolved
    by `ensure_age_available`; we pass it explicitly to avoid relying on
    PATH at exec time. The S603 noqa is correct here — the subprocess
    input is the locally-generated CSPRNG private key, not user input.
    """
    proc = subprocess.run(  # noqa: S603
        [age_bin, "-p", "-o", str(output_path)],
        input=bytes(plaintext),
        check=False,
        timeout=180,
    )
    # Wipe the bytearray contents regardless of outcome.
    for i in range(len(plaintext)):
        plaintext[i] = 0
    if proc.returncode != 0:
        print(
            f"error: age exited {proc.returncode} writing {output_path}. "
            "If you aborted, no .age file was written for this role.",
            file=sys.stderr,
        )
        sys.exit(3)


def verify_age_armor(path: Path) -> None:
    """Sanity-check the encrypted output starts with the age v1 armor prefix.

    This is a low-cost catch for situations where age silently wrote a
    zero-byte or otherwise malformed file.
    """
    with path.open("rb") as fh:
        head = fh.read(len(AGE_HEADER_PREFIX))
    if head != AGE_HEADER_PREFIX:
        print(
            f"error: {path} does not start with age v1 armor; encryption may have failed silently.",
            file=sys.stderr,
        )
        sys.exit(4)


def refuse_if_existing(role: WalletRole, target: Path, allow_overwrite: bool) -> None:
    """Refuse to overwrite an existing .age file unless --allow-overwrite was passed.

    Overwrite is destructive when the wallet has already been funded — the
    plaintext key is gone and on-chain funds are lost. The script defaults
    to refusal so accidental re-runs are a no-op rather than a key burn.
    """
    if target.exists() and not allow_overwrite:
        print(
            f"error: {target} already exists. Refusing to overwrite. "
            f"If you really want to regenerate the {role.display} wallet, "
            "rerun with --allow-overwrite (and update runbooks/wallet-ops.md).",
            file=sys.stderr,
        )
        sys.exit(5)


def main(argv: list[str]) -> int:
    """Top-level entry point. Side effects: writes two .age files and prints
    the Signer privkey to stdout once. Returns 0 on success, non-zero on any
    failure path with a printed message on stderr."""
    args = parse_args(argv)
    age_bin = ensure_age_available()
    ensure_secrets_dir(args.secrets_dir)

    funder_path = args.secrets_dir / FUNDER.filename
    signer_path = args.secrets_dir / SIGNER.filename
    refuse_if_existing(FUNDER, funder_path, args.allow_overwrite)
    refuse_if_existing(SIGNER, signer_path, args.allow_overwrite)

    funder_addr, funder_pk = generate_wallet()
    signer_addr, signer_pk = generate_wallet()

    # Snapshot the Signer privkey for the final stdout print before wipe.
    # We deliberately keep this in process memory only; it is never
    # written to a file by this script.
    signer_pk_for_paste = bytes(signer_pk)

    print(f"\n  FUNDER address: {funder_addr}", file=sys.stderr)
    print(f"  SIGNER address: {signer_addr}", file=sys.stderr)
    print("", file=sys.stderr)
    print(f"  encrypting → {funder_path}", file=sys.stderr)
    encrypt_to_age(age_bin, funder_pk, funder_path)
    verify_age_armor(funder_path)
    os.chmod(funder_path, 0o600)

    print(f"  encrypting → {signer_path}", file=sys.stderr)
    encrypt_to_age(age_bin, signer_pk, signer_path)
    verify_age_armor(signer_path)
    os.chmod(signer_path, 0o600)

    print(
        "\n  Both wallets encrypted. Next: paste the line below into .envrc as\n"
        "    export POLY_PRIVATE_KEY=<line>\n"
        "  then `chmod 0600 .envrc`, then `clear` to wipe scrollback, then\n"
        "  `direnv allow`. The line will appear ONCE on stdout below.\n",
        file=sys.stderr,
    )
    sys.stdout.buffer.write(signer_pk_for_paste + b"\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
