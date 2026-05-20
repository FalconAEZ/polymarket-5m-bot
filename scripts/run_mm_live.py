"""MMB live-mode entry script — REAL ORDERS, REAL MONEY, $1k bankroll.

Phase S Session 5 deliverable. Drives `MarketMakerStrategy` against the
Polymarket CLOB via `LiveClobOrderClient`. Designed for VPS deployment
under `bot-mm.service`. The companion paper script (`run_mm_paper.py`)
exercised the same code path with a `MockClobOrderClient`; this script
swaps in the real one.

PRE-DEPLOY CHECKLIST — script refuses to start unless ALL satisfied:

  1. `MM_LIVE_CONFIRM=yes`            — operator explicit consent (env var).
  2. `state/halt.sentinel` ABSENT     — operator manually removes after
                                         verifying allowance + caps + last
                                         paper soak was clean.
  3. `state/mm-allowance.json`        — produced by `mm_set_allowance.py`,
     present + allowance sufficient    showing the Signer can spend USDC.e
                                         to the CTF Exchange.
  4. L2 credentials in env             — CLOB_API_KEY/SECRET/PASSPHRASE.
  5. PK_SIGNER + POLY_FUNDER in env    — Phase 1A wallet (0x8d97... / 0x512D...).

Behavior on startup violation: log + exit non-zero. systemd will retry
after 30s per Restart=on-failure; the operator's job is to fix the
violation, not the script's.

REAL-MONEY GUARDS already in MmRunner + MarketMakerStrategy:
  - RiskGate caps from design/S.1-market-maker-bot.md §2.4 (live-micro).
  - Per-window MAX_INV $25, MAX_GROSS $50, MAX_DAILY_LOSS $50.
  - Daily-loss trip → halt sentinel + Telegram alert (idempotent).
  - Heartbeat 5s cadence, 2-miss → halt sentinel + Telegram.
  - All limit orders post_only=True (no taker fills).

WHAT THIS SCRIPT IS NOT TESTED FOR (S.5 operator-driven exercise):
  - Real CLOB connectivity timing (handle 429s, transient 5xx)
  - Real WebSocket fill notifications (this v1 polls /trades)
  - Real market discovery latency (Gamma API call cadence)
  - Multi-market concurrent state under load

This script is committed for review + VPS deployment, but the first
live fire MUST be operator-supervised. See
`phase-prompts/phase-S-session-5-live-micro.md` for the full procedure.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# After sys.path manipulation.
from polymarket_bot._live.clob_orders import LiveClobOrderClient  # noqa: E402
from polymarket_bot._live.mm_alerts import (  # noqa: E402
    push_to_redis_alerter,
)
from polymarket_bot._live.mm_heartbeat import (  # noqa: E402
    mm_heartbeat_loop,
    write_halt_sentinel_async,
)
from polymarket_bot._paper.mm_runner import (  # noqa: E402
    MmDecisionLog,
    MmRunner,
    replay_bankroll,
)
from polymarket_bot.strategies.j7_priors import J7Priors  # noqa: E402
from polymarket_bot.strategies.market_maker import (  # noqa: E402
    MarketMakerStrategy,
    RiskCaps,
    RiskGate,
    Side,
)

LOG = logging.getLogger("polymarket_bot.scripts.run_mm_live")

WINDOW_SECONDS = 300  # BTC 5-min up/down windows
DEFAULT_BOOK_POLL_S = 1.0
DEFAULT_TICK_SIZE = "0.01"
DEFAULT_MIN_ORDER_SIZE_SHARES = 5.0


# ---------------- pre-flight ----------------


def _check_env_confirm() -> bool:
    return os.environ.get("MM_LIVE_CONFIRM", "").lower() == "yes"


def _check_halt_sentinel(path: Path) -> bool:
    return not path.exists()


def _check_allowance(audit_path: Path, min_usd: float = 100.0) -> bool:
    """Read `state/mm-allowance.json` produced by `mm_set_allowance.py`.
    Returns True iff the snapshot is recent (< 24h) and reports >= min_usd."""
    if not audit_path.exists():
        return False
    try:
        data = json.loads(audit_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    ts = int(data.get("ts_unix", 0))
    age_s = time.time() - ts
    if age_s > 86_400:  # 24h
        LOG.warning("allowance audit is stale (age=%.0fs); refusing to start", age_s)
        return False
    snap = data.get("snapshot") or {}
    allowance_usd = float(snap.get("allowance_usd", 0.0))
    return allowance_usd >= min_usd


def _check_clob_creds() -> bool:
    return all(
        os.environ.get(k)
        for k in (
            "CLOB_API_KEY",
            "CLOB_API_SECRET",
            "CLOB_API_PASSPHRASE",
            "PK_SIGNER",
            "POLY_FUNDER",
        )
    )


def _preflight(halt_sentinel: Path, allowance_audit: Path) -> tuple[bool, str]:
    if not _check_env_confirm():
        return False, "MM_LIVE_CONFIRM != yes — operator must explicitly opt in"
    if not _check_halt_sentinel(halt_sentinel):
        return False, f"halt sentinel present at {halt_sentinel} — remove to start"
    if not _check_allowance(allowance_audit):
        return False, (
            f"allowance audit missing/insufficient at {allowance_audit}; "
            f"run scripts/mm_set_allowance.py"
        )
    if not _check_clob_creds():
        return False, "missing CLOB L2 creds or wallet env vars (see docstring)"
    return True, "ok"


# ---------------- live client setup ----------------


def _build_live_client() -> LiveClobOrderClient:
    from py_clob_client.client import ClobClient  # type: ignore[import-untyped]
    from py_clob_client.clob_types import ApiCreds  # type: ignore[import-untyped]

    creds = ApiCreds(
        api_key=os.environ["CLOB_API_KEY"],
        api_secret=os.environ["CLOB_API_SECRET"],
        api_passphrase=os.environ["CLOB_API_PASSPHRASE"],
    )
    inner = ClobClient(
        host="https://clob.polymarket.com",
        chain_id=137,
        key=os.environ["PK_SIGNER"],
        creds=creds,
        signature_type=2,
        funder=os.environ["POLY_FUNDER"],
    )
    return LiveClobOrderClient(inner=inner)


# ---------------- market discovery ----------------


async def _discover_active_btc_5m_markets(limit: int = 3) -> list[dict[str, Any]]:
    """Fetch the next N active BTC 5m markets from Gamma. Returns list of
    {market_id, token_up, token_dn, slug, end_date}. For S.5 live-micro
    we cap at 3 concurrent markets to bound exposure."""
    import httpx

    async with httpx.AsyncClient(timeout=15.0) as cli:
        # Query active BTC up/down events. Slug convention: btc-updown-5m-<ts>.
        resp = await cli.get(
            "https://gamma-api.polymarket.com/events",
            params={
                "closed": "false",
                "active": "true",
                "tag_id": "100381",
                "limit": str(limit * 3),
            },
        )
        resp.raise_for_status()
        events = resp.json()

    markets: list[dict[str, Any]] = []
    for ev in events:
        slug = ev.get("slug") or ""
        if not slug.startswith("btc-updown-5m-"):
            continue
        mks = ev.get("markets") or []
        if not mks:
            continue
        m = mks[0]
        # clobTokenIds is a JSON-encoded list of strings — outcome 0 = UP, 1 = DOWN.
        ctids_raw = m.get("clobTokenIds")
        if isinstance(ctids_raw, str):
            try:
                ctids = json.loads(ctids_raw)
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            ctids = ctids_raw or []
        if not isinstance(ctids, list) or len(ctids) != 2:
            continue
        markets.append(
            {
                "market_id": m.get("conditionId") or slug,
                "token_up": ctids[0],
                "token_dn": ctids[1],
                "slug": slug,
                "end_date": m.get("endDate") or ev.get("endDate"),
            }
        )
        if len(markets) >= limit:
            break
    return markets


# ---------------- main loop ----------------


async def _book_loop_one_token(
    runner: MmRunner,
    *,
    market_id: str,
    token_id: str,
    side: Side,
    window_close_unix: float,
    poll_interval_s: float,
    tick_size: str,
    min_order_size_shares: float,
    stop_event: asyncio.Event,
) -> None:
    """Poll the orderbook for one (market, token, side) until either the
    window closes or stop_event is set."""
    while not stop_event.is_set():
        now = time.time()
        if now >= window_close_unix:
            return
        seconds_remaining = max(0.0, window_close_unix - now)
        try:
            book = await runner.client.get_orderbook(token_id)
        except Exception:
            LOG.exception("get_orderbook failed for token=%s; sleeping + retrying", token_id)
            await asyncio.sleep(poll_interval_s)
            continue
        if book is None or book.best_ask is None:
            await asyncio.sleep(poll_interval_s)
            continue
        try:
            await runner.on_book_update(
                market_id=market_id,
                token_id=token_id,
                side=side,
                best_ask=book.best_ask,
                tick_size=tick_size,
                min_order_size_shares=min_order_size_shares,
                seconds_remaining=seconds_remaining,
            )
        except Exception:
            LOG.exception("on_book_update raised for token=%s", token_id)
        await asyncio.sleep(poll_interval_s)


async def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--max-markets", type=int, default=3, help="Cap on concurrent markets (default 3)"
    )
    parser.add_argument("--book-poll-s", type=float, default=DEFAULT_BOOK_POLL_S)
    parser.add_argument(
        "--decision-log-root",
        type=Path,
        default=Path("state/mm-decisions"),
    )
    parser.add_argument(
        "--halt-sentinel",
        type=Path,
        default=Path("state/halt.sentinel"),
    )
    parser.add_argument(
        "--allowance-audit",
        type=Path,
        default=Path("state/mm-allowance.json"),
    )
    args = parser.parse_args(argv)

    ok, reason = _preflight(args.halt_sentinel, args.allowance_audit)
    if not ok:
        LOG.error("pre-flight FAIL: %s", reason)
        return 2

    LOG.info("pre-flight OK; building live CLOB client...")
    client = _build_live_client()

    bankroll = replay_bankroll(args.decision_log_root, starting_bankroll=1000.0)
    LOG.info("replayed bankroll: $%.2f", bankroll)

    priors = J7Priors.load()
    LOG.info("loaded priors from %s", priors.source_path)

    def _bankroll_getter() -> float:
        return bankroll

    gate = RiskGate(caps=RiskCaps())
    strategy = MarketMakerStrategy(
        priors=priors,
        bankroll_getter=_bankroll_getter,
        gate=gate,
    )
    decision_log = MmDecisionLog(root=args.decision_log_root)

    runner = MmRunner(
        strategy=strategy,
        client=client,
        decision_log=decision_log,
        halt_sentinel_path=args.halt_sentinel,
        dry_run=False,  # REAL ORDERS
        alert_callback=push_to_redis_alerter,
    )

    # Discover active markets.
    LOG.info("discovering active BTC 5m markets (max %d)...", args.max_markets)
    markets = await _discover_active_btc_5m_markets(limit=args.max_markets)
    LOG.info("found %d markets to trade: %s", len(markets), [m["slug"] for m in markets])
    if not markets:
        LOG.error("no active markets discovered; nothing to do")
        return 1

    stop_event = asyncio.Event()

    # Start heartbeat task.
    heartbeat = asyncio.create_task(
        mm_heartbeat_loop(
            client=client,
            halt_writer=lambda reason: write_halt_sentinel_async(reason, path=args.halt_sentinel),
            interval_s=5.0,
        )
    )

    # Build per-token book loops. Window close = next 5-min boundary
    # (we'll discover new markets on each window roll-over).
    now = time.time()
    window_close = ((int(now) // WINDOW_SECONDS) + 1) * WINDOW_SECONDS

    book_tasks: list[asyncio.Task[None]] = []
    for m in markets:
        for side_label, token_id in (
            (Side.UP, m["token_up"]),
            (Side.DOWN, m["token_dn"]),
        ):
            book_tasks.append(
                asyncio.create_task(
                    _book_loop_one_token(
                        runner=runner,
                        market_id=m["market_id"],
                        token_id=token_id,
                        side=side_label,
                        window_close_unix=window_close,
                        poll_interval_s=args.book_poll_s,
                        tick_size=DEFAULT_TICK_SIZE,
                        min_order_size_shares=DEFAULT_MIN_ORDER_SIZE_SHARES,
                        stop_event=stop_event,
                    )
                )
            )

    LOG.info(
        "started %d book-loop tasks + heartbeat; first window closes at unix=%d",
        len(book_tasks),
        window_close,
    )

    # Wait until the window closes OR halt sentinel detected.
    while time.time() < window_close:
        if await asyncio.to_thread(args.halt_sentinel.exists):
            LOG.warning("halt sentinel detected; draining")
            break
        await asyncio.sleep(1.0)

    stop_event.set()
    for t in book_tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await t

    LOG.info("window closed; draining open orders + shutting down")
    heartbeat.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await heartbeat

    n_drained = await runner.drain()
    decision_log.close()

    LOG.info("run complete: drained %d open orders", n_drained)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
