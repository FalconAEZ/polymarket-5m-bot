"""mm_set_allowance.py — verify (and optionally set) USDC.e allowance on the Signer.

Phase S Session 5 pre-deploy step. Before MMB can place its first live
order on the CTF Exchange, the Signer wallet's USDC.e allowance must
cover the per-window gross exposure. This script reports current
allowance + optionally invokes py-clob-client's `update_balance_allowance`
to set it.

DEFAULT BEHAVIOR — verify only (no on-chain tx):
  $ uv run python scripts/mm_set_allowance.py

OPT-IN — apply approve via py-clob-client (requires interactive confirm):
  $ uv run python scripts/mm_set_allowance.py --apply

Either way, the script writes `state/mm-allowance.json` with the post-
verification snapshot for audit. The bot's startup check refuses to
trade if this file is absent or reports insufficient allowance.

Operator alternatives if you don't want the script to broadcast:
  - Polymarket.com UI: "Settings -> Enable Trading" performs the same
    approve via their flow.
  - Foundry/cast: `cast send 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
    "approve(address,uint256)"
    0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
    115792089237316195423570985008687907853269984665640564039457584007913129639935
    --private-key $PK_SIGNER --rpc-url $POLYGON_RPC`

After ANY of the three paths above, re-run this script (no `--apply`)
to verify the allowance landed.

Contract addresses (verified via agent-skills 2026-05-20):
  USDC.e        : 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
  CTF Exchange  : 0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

LOG = logging.getLogger("polymarket_bot.scripts.mm_set_allowance")

AUDIT_PATH = PROJECT_ROOT / "state" / "mm-allowance.json"
# Recommended minimum allowance: well above one day of MMB live-micro
# trading at $1k bankroll with worst-case daily turnover. $10k allowance
# covers ~200 days of $50/day worst-case turnover; effectively
# practical-unlimited at our scale without granting MAX_UINT256.
DEFAULT_MIN_ALLOWANCE_USD = 10_000.0


def _build_client_l2() -> Any:
    """Construct an L2-authenticated ClobClient. Requires env:
    PK_SIGNER         — Signer private key (hex, no 0x prefix is fine)
    POLY_FUNDER       — Funder address (proxy wallet, sig type 2)
    CLOB_API_KEY      — L2 apiKey (from derive_creds.py)
    CLOB_API_SECRET   — L2 secret
    CLOB_API_PASSPHRASE — L2 passphrase
    """
    from py_clob_client.client import ClobClient  # type: ignore[import-untyped]
    from py_clob_client.clob_types import ApiCreds  # type: ignore[import-untyped]

    required = [
        "PK_SIGNER",
        "POLY_FUNDER",
        "CLOB_API_KEY",
        "CLOB_API_SECRET",
        "CLOB_API_PASSPHRASE",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"missing required env vars: {', '.join(missing)}")

    creds = ApiCreds(
        api_key=os.environ["CLOB_API_KEY"],
        api_secret=os.environ["CLOB_API_SECRET"],
        api_passphrase=os.environ["CLOB_API_PASSPHRASE"],
    )
    return ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=os.environ["PK_SIGNER"],
        creds=creds,
        signature_type=2,  # GNOSIS_SAFE per Phase 1A OD-4
        funder=os.environ["POLY_FUNDER"],
    )


def _fetch_balance_allowance(client: Any) -> dict[str, Any]:
    """Query the CLOB for current COLLATERAL balance + allowance."""
    from py_clob_client.clob_types import (
        AssetType,
        BalanceAllowanceParams,
    )

    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
    raw = client.get_balance_allowance(params)
    return _parse_balance_allowance(raw)


def _parse_balance_allowance(raw: Any) -> dict[str, Any]:
    """Normalize the CLOB response to a typed dict.

    Response keys may include 'balance' (USDC.e wei, 6 decimals) and
    'allowance' (also USDC.e wei). We convert to dollars for human
    readability + keep raw values for audit.
    """
    if not isinstance(raw, dict):
        raw = {"raw": str(raw)}
    bal_wei = int(raw.get("balance", 0))
    allow_wei = int(raw.get("allowance", 0))
    return {
        "balance_wei": bal_wei,
        "allowance_wei": allow_wei,
        "balance_usd": bal_wei / 1_000_000.0,
        "allowance_usd": allow_wei / 1_000_000.0,
        "raw": raw,
    }


def _write_audit(snapshot: dict[str, Any], *, mode: str) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts_unix": int(time.time()),
        "mode": mode,
        "snapshot": snapshot,
    }
    AUDIT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    LOG.info("wrote audit to %s", AUDIT_PATH)


def _confirm_apply() -> bool:
    """Interactive operator confirmation before broadcasting an approve tx."""
    print()
    print("=" * 60)
    print("ABOUT TO BROADCAST AN ON-CHAIN APPROVE TX:")
    print("  USDC.e contract:  0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174")
    print("  Spender (CTF):    0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E")
    print("  Amount:           MAX_UINT256  (practical-unlimited)")
    print(f"  Signer/Funder:    {os.environ.get('POLY_FUNDER', '?')}")
    print("  Chain:            Polygon mainnet (137)")
    print()
    print("This will spend gas (~$0.01 in MATIC on Signer)")
    print("and grant unlimited USDC.e spending to the CTF Exchange.")
    print("This is the standard Polymarket trading prerequisite.")
    print("=" * 60)
    response = input("Type 'YES I CONFIRM' to broadcast: ").strip()
    return response == "YES I CONFIRM"


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Broadcast an approve tx via py-clob-client update_balance_allowance (default: verify only)",
    )
    parser.add_argument(
        "--min-usd",
        type=float,
        default=DEFAULT_MIN_ALLOWANCE_USD,
        help=f"Minimum allowance in USD to consider 'sufficient' (default: {DEFAULT_MIN_ALLOWANCE_USD})",
    )
    args = parser.parse_args()

    try:
        client = _build_client_l2()
    except RuntimeError as exc:
        LOG.error("cannot build client: %s", exc)
        return 2

    LOG.info("querying current USDC.e balance + allowance...")
    snapshot = _fetch_balance_allowance(client)
    print()
    print(f"Current USDC.e balance:   ${snapshot['balance_usd']:,.2f}")
    print(f"Current allowance to CTF: ${snapshot['allowance_usd']:,.2f}")
    print(f"Threshold (--min-usd):    ${args.min_usd:,.2f}")
    print()

    sufficient = snapshot["allowance_usd"] >= args.min_usd

    if sufficient:
        print("✓ Allowance is SUFFICIENT for MMB live deploy.")
        _write_audit(snapshot, mode="verify-sufficient")
        return 0

    print("✗ Allowance is INSUFFICIENT — MMB will not be able to place live orders.")
    print()
    if not args.apply:
        print("To set the allowance, use ONE of:")
        print("  1) Polymarket UI: log in at polymarket.com and complete 'Enable Trading'.")
        print("  2) This script with `--apply`: broadcasts an approve via py-clob-client.")
        print("  3) Foundry cast (advanced): see this script's docstring.")
        print()
        print("After any of those, re-run this script (without --apply) to verify.")
        _write_audit(snapshot, mode="verify-insufficient")
        return 1

    # --apply path: explicit operator confirmation required.
    if not _confirm_apply():
        print("Aborted (operator did not type the exact confirmation phrase).")
        return 1

    LOG.info("broadcasting approve via py-clob-client.update_balance_allowance ...")
    from py_clob_client.clob_types import (
        AssetType,
        BalanceAllowanceParams,
    )

    params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2)
    client.update_balance_allowance(params)
    LOG.info("update_balance_allowance returned; re-querying state...")

    # Brief wait for tx confirmation + cache invalidation.
    time.sleep(15)
    post_snapshot = _fetch_balance_allowance(client)
    print()
    print(f"Post-apply allowance:     ${post_snapshot['allowance_usd']:,.2f}")
    if post_snapshot["allowance_usd"] >= args.min_usd:
        print("✓ Allowance now SUFFICIENT.")
        _write_audit(post_snapshot, mode="apply-success")
        return 0

    print("⚠ Allowance still insufficient after apply. Check Polygonscan + Signer MATIC balance.")
    _write_audit(post_snapshot, mode="apply-failed")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
