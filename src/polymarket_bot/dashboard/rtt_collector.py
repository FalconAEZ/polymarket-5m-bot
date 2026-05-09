"""VPS-side provider RTT collector — runs as its own systemd unit.

Pings the 5 providers (Binance, Coinbase, Chainlink, Polymarket Gamma,
Polymarket CLOB) every SAMPLE_INTERVAL_S seconds and appends one JSONL
line per provider per tick to state/provider_rtt.jsonl. The dashboard
reads from that file via load_provider_rtt() to render the v2 RTT panel.

Lives on the VPS so the measured latency is the *bot's* network RTT to
each provider — not the operator's laptop RTT. Per design/dashboard-v2.md
§10 (revised for VPS architecture).

Run with:
    uv run python -m polymarket_bot.dashboard.rtt_collector

systemd unit at runbooks/staging/rtt-collector.service. Throttled,
async, never raises into the asyncio loop — provider failures are
captured per-line as ok=false.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from polymarket_bot.dashboard.provider_rtt import PROVIDERS

SAMPLE_INTERVAL_S: float = 10.0
TIMEOUT_S: float = 8.0
ROTATE_THRESHOLD_BYTES: int = 5_000_000  # 5MB → keep last MAX_LINES
MAX_LINES_AFTER_ROTATE: int = 5_000


async def _ping_one(client: httpx.AsyncClient, url: str) -> tuple[float | None, int | None]:
    start = time.monotonic()
    try:
        resp = await client.get(url, timeout=TIMEOUT_S)
        rtt_ms = (time.monotonic() - start) * 1000.0
        return rtt_ms, resp.status_code
    except (httpx.HTTPError, TimeoutError):
        return None, None
    except Exception:  # defensive — never crash the loop
        return None, None


def _write_lines_sync(output_path: Path, lines: list[str]) -> None:
    """Synchronous I/O helper — extracted so async _tick can offload to a
    thread via asyncio.to_thread. Keeps the event loop unblocked and
    satisfies ruff's ASYNC240 rule for sync file I/O in async functions.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    try:
        if output_path.stat().st_size > ROTATE_THRESHOLD_BYTES:
            _rotate(output_path, MAX_LINES_AFTER_ROTATE)
    except OSError:
        pass


async def _tick(client: httpx.AsyncClient, output_path: Path) -> None:
    results = await asyncio.gather(
        *(_ping_one(client, p.url) for p in PROVIDERS),
        return_exceptions=False,
    )
    now = datetime.now(tz=UTC).isoformat()
    lines = [
        json.dumps(
            {
                "provider": provider.name,
                "ts_utc": now,
                "rtt_ms": rtt_ms,
                "status_code": status,
                "ok": rtt_ms is not None,
            }
        )
        for provider, (rtt_ms, status) in zip(PROVIDERS, results, strict=True)
    ]
    await asyncio.to_thread(_write_lines_sync, output_path, lines)


def _rotate(path: Path, keep_lines: int) -> None:
    """Keeps the last keep_lines lines of path. Best-effort; on error,
    leaves the file untouched (the next rotation will retry)."""
    try:
        with path.open(encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    keep = lines[-keep_lines:]
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.writelines(keep)
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


async def main(*, output_path: Path | None = None) -> None:
    if output_path is None:
        state_dir = Path(os.environ.get("PMB_DASH_STATE_DIR", "state"))
        output_path = state_dir / "provider_rtt.jsonl"
    print(
        f"[rtt-collector] starting, sampling {len(PROVIDERS)} providers every "
        f"{SAMPLE_INTERVAL_S:.0f}s, writing to {output_path}",
        flush=True,
    )
    async with httpx.AsyncClient() as client:
        while True:
            try:
                await _tick(client, output_path)
            except Exception as exc:  # never let the loop die
                print(f"[rtt-collector] tick error: {exc}", file=sys.stderr, flush=True)
            await asyncio.sleep(SAMPLE_INTERVAL_S)


if __name__ == "__main__":
    asyncio.run(main())
