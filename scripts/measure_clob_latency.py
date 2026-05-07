"""Phase 5.3 — CLOB WebSocket latency measurement.

Measures three distinct latencies to wss://ws-subscriptions-clob.polymarket.com:
1. Handshake: full TCP + TLS + WS upgrade time per connection cycle (informational).
2. PING/PONG RTT on established connection (the gate metric per RUNBOOK §5.3).
3. Subscribe -> first-message RTT (sanity check via real protocol exchange).

Gate criteria from RUNBOOK §5.3: p50 < 5 ms, p99 < 15 ms (applied to PING RTT).
Output is plain-text + machine-readable JSON for runbooks/gate-evidence/.
"""

from __future__ import annotations

import asyncio
import json
import socket
import statistics
import sys
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import websockets

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA_BASE = "https://gamma-api.polymarket.com"
HANDSHAKE_N = 20
PING_N = 100
SUBSCRIBE_N = 10


def stats(samples: list[float]) -> dict[str, float]:
    if not samples:
        return {"n": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "mean": 0.0}
    s = sorted(samples)
    n = len(s)
    return {
        "n": float(n),
        "min": s[0],
        "p50": s[n // 2],
        "p95": s[min(int(n * 0.95), n - 1)],
        "p99": s[min(int(n * 0.99), n - 1)],
        "max": s[-1],
        "mean": statistics.fmean(s),
    }


def fmt(label: str, st: dict[str, float]) -> str:
    return (
        f"{label:<40s} n={int(st['n']):>4d}  "
        f"min={st['min']:6.2f}  p50={st['p50']:6.2f}  "
        f"p95={st['p95']:6.2f}  p99={st['p99']:6.2f}  "
        f"max={st['max']:6.2f}  mean={st['mean']:6.2f}  (ms)"
    )


async def measure_handshake(n: int) -> list[float]:
    samples: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        async with websockets.connect(WS_URL, open_timeout=5.0) as ws:
            samples.append((time.perf_counter() - t0) * 1000.0)
            await ws.close()
        await asyncio.sleep(0.2)
    return samples


async def measure_ping_pong(n: int) -> list[float]:
    samples: list[float] = []
    async with websockets.connect(WS_URL, open_timeout=5.0) as ws:
        # warmup
        for _ in range(3):
            pong = await ws.ping()
            await pong
            await asyncio.sleep(0.05)
        for _ in range(n):
            t0 = time.perf_counter()
            pong_waiter = await ws.ping()
            await pong_waiter
            samples.append((time.perf_counter() - t0) * 1000.0)
            await asyncio.sleep(0.1)
    return samples


async def fetch_active_token_ids() -> list[str]:
    """Resolve the current 5m BTC up/down market token IDs via Gamma."""
    # active_slug for current 5-minute window
    now = int(time.time())
    window_ts = (now // 300) * 300
    slug = f"btc-updown-5m-{window_ts}"
    url = f"{GAMMA_BASE}/events"
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url, params={"slug": slug})
    if resp.status_code != 200:
        return []
    data = resp.json()
    if not isinstance(data, list) or not data:
        return []
    markets = data[0].get("markets") if isinstance(data[0], dict) else None
    if not isinstance(markets, list) or not markets:
        return []
    raw = markets[0].get("clobTokenIds") if isinstance(markets[0], dict) else None
    if not isinstance(raw, str):
        return []
    decoded = json.loads(raw)
    return [tid for tid in decoded if isinstance(tid, str)]


async def measure_subscribe_first_msg(n: int, tokens: list[str]) -> list[float]:
    """Time from subscribe send to first server message arrival.

    Opens a fresh connection per sample to get a clean subscribe RTT.
    """
    if not tokens:
        return []
    samples: list[float] = []
    payload = json.dumps(
        {"type": "market", "assets_ids": tokens, "custom_feature_enabled": True},
        separators=(",", ":"),
    )
    for _ in range(n):
        async with websockets.connect(WS_URL, open_timeout=5.0) as ws:
            t0 = time.perf_counter()
            await ws.send(payload)
            try:
                await asyncio.wait_for(ws.recv(), timeout=5.0)
            except TimeoutError:
                continue
            samples.append((time.perf_counter() - t0) * 1000.0)
        await asyncio.sleep(0.3)
    return samples


async def main() -> int:
    started = datetime.now(UTC).isoformat()
    print(f"# Phase 5.3 CLOB latency — {started}")
    print(f"# endpoint: {WS_URL}")
    print(f"# host: {socket.gethostname()} — expected: AWS Lightsail eu-west-1 (Dublin)")
    print()

    print("[1/3] handshake (TCP + TLS + WS upgrade) ...", flush=True)
    hs = await measure_handshake(HANDSHAKE_N)
    hs_stats = stats(hs)
    print(fmt("handshake (informational)", hs_stats))
    print()

    print("[2/3] PING/PONG round-trip on established connection ...", flush=True)
    pp = await measure_ping_pong(PING_N)
    pp_stats = stats(pp)
    print(fmt("PING/PONG RTT (GATE METRIC)", pp_stats))
    print()

    print("[3/3] subscribe -> first message ...", flush=True)
    tokens = await fetch_active_token_ids()
    if tokens:
        print(f"  resolved {len(tokens)} token_ids for current 5m window")
        sub = await measure_subscribe_first_msg(SUBSCRIBE_N, tokens)
        sub_stats = stats(sub)
        print(fmt("subscribe -> first msg", sub_stats))
    else:
        sub_stats = stats([])
        print("  no active 5m BTC market on Gamma right now (off-window?); skipping subscribe RTT")
    print()

    # Verdict
    p50_ok = pp_stats["p50"] < 5.0
    p99_ok = pp_stats["p99"] < 15.0
    verdict = "PASS" if (p50_ok and p99_ok) else "FAIL"
    print("=" * 72)
    print(
        f"GATE CRITERIA (PING/PONG RTT): p50<5ms={'OK' if p50_ok else 'FAIL'} "
        f"({pp_stats['p50']:.2f}ms), p99<15ms={'OK' if p99_ok else 'FAIL'} "
        f"({pp_stats['p99']:.2f}ms)  -> {verdict}"
    )
    print("=" * 72)
    print()

    out: dict[str, Any] = {
        "phase": "5.3",
        "started_utc": started,
        "endpoint": WS_URL,
        "verdict": verdict,
        "gate_p50_ms": 5.0,
        "gate_p99_ms": 15.0,
        "handshake": hs_stats,
        "ping_pong_rtt": pp_stats,
        "subscribe_first_msg": sub_stats,
    }
    print("# JSON-OUT-START")
    print(json.dumps(out, indent=2))
    print("# JSON-OUT-END")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
