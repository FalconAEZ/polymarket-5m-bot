"""Live demo simulator — writes a moving dashboard against state-demo/.

What it does:
  1. Seeds state-demo/ with historical data (3 days of fired+settled
     decisions, feeds_health.json, paper.log + capture.log, pid files).
  2. Enters a loop and keeps writing new state at three cadences:
       - every 1.5s: append 1-3 log lines to paper.log + capture.log,
         touch the feeds_health snapshot mtime
       - every 4s: increment per-feed msgs_seen counters
       - every 25s (compressed "5-minute window"): fire a new decision
         — append a `fired` JSONL line, then settle the previous open
         window with a `settled` line
  3. SIGINT/SIGTERM: graceful exit; state-demo/ stays on disk.

Run it in one terminal. In another, point the dashboard at the same dir:

    PMB_DASH_STATE_DIR=$(pwd)/state-demo uv run streamlit run scripts/dashboard.py

The dashboard's auto-refresh (default 15s) will pick up the moving data —
KPIs tick, the PnL chart extends, the decisions table grows, log tabs
scroll, feed msg counts tick up, "Last Decision" timer resets each
window. State-demo is gitignored.
"""

from __future__ import annotations

import json
import os
import random
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "state-demo"
DECISIONS_DIR = DEMO_DIR / "decisions"
FEEDS_HEALTH = DEMO_DIR / "feeds_health.json"
PAPER_LOG = DEMO_DIR / "paper.log"
CAPTURE_LOG = DEMO_DIR / "capture.log"

ASSET_UP = "0x" + "11" * 32
ASSET_DOWN = "0x" + "22" * 32
SIZE_USD = 5.0

LOG_TICK_S = 1.5
FEED_TICK_S = 4.0
DECISION_TICK_S = 25.0  # compressed "5-min window" so decisions feel live

_STOP = False
RNG = random.Random(7)  # noqa: S311 — demo data, not security-sensitive


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _ts_ns(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _window_start(dt: datetime) -> int:
    s = int(dt.timestamp())
    return s - (s % 300)


# ----------------------- seed (run once at start) ---------------------------


def _seed_decisions() -> None:
    """Write 3 UTC days of historical fired+settled lines, ~58% win-rate.

    The "today" partition only covers the wall-clock minutes that have
    already elapsed — otherwise "Last Decision" shows a negative age.
    """
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    now = _now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    by_day: dict[str, list[dict[str, object]]] = {}
    for d_offset in range(3):
        day = today - timedelta(days=2 - d_offset)
        date_str = day.strftime("%Y-%m-%d")
        is_today = d_offset == 2
        max_min = int((now - day).total_seconds() // 60) - 5 if is_today else 1380
        if max_min <= 60:
            continue
        n = RNG.randint(min(25, max_min // 30), min(35, max_min // 20))
        for offset_min in sorted(RNG.sample(range(60, max_min), n)):
            dt = day + timedelta(minutes=offset_min)
            fired, settled = _make_decision(dt, want_settled=True)
            by_day.setdefault(date_str, []).extend([fired, settled])
    for date_str, lines in by_day.items():
        out = DECISIONS_DIR / f"{date_str}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, separators=(",", ":")) + "\n")
    total = sum(len(v) for v in by_day.values())
    print(f"  seeded {len(by_day)} day-files, {total} JSONL lines")


def _seed_feeds_health() -> None:
    now_ns = _ts_ns(_now())
    payload = {
        "snapshot_ts_utc": _now().isoformat(),
        "feeds": {
            "binance": _feed_row("binance", 18_472_103, now_ns - 800_000_000, 2),
            "coinbase": _feed_row("coinbase", 5_438_290, now_ns - 1_200_000_000, 0),
            "oracle": _feed_row("oracle", 21_843, now_ns - 9_400_000_000, 1),
            "polymarket": _feed_row("polymarket", 392_017_551, now_ns - 100_000_000, 4),
        },
    }
    _atomic_write_json(FEEDS_HEALTH, payload)
    print(f"  seeded {FEEDS_HEALTH.name}")


def _feed_row(name: str, msgs: int, last_ns: int, reconnects: int) -> dict[str, object]:
    return {
        "name": name,
        "msgs_seen": msgs,
        "healthy": True,
        "reconnects": reconnects,
        "last_error": "",
        "last_seen_ns": last_ns,
    }


def _seed_logs() -> None:
    now = _now()
    paper_lines = []
    capture_lines = []
    for i in range(80):
        when = (now - timedelta(seconds=(80 - i) * 7)).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        paper_lines.append(_paper_log_line(when, i))
        capture_lines.append(_capture_log_line(when, i, msgs_base=391_000_000))
    PAPER_LOG.write_text("\n".join(paper_lines) + "\n", encoding="utf-8")
    CAPTURE_LOG.write_text("\n".join(capture_lines) + "\n", encoding="utf-8")
    print(f"  seeded {PAPER_LOG.name} + {CAPTURE_LOG.name}")


def _seed_pid_files() -> None:
    parent = os.getppid()
    (DEMO_DIR / "capture.pid").write_text(str(parent))
    (DEMO_DIR / "paper.pid").write_text(str(parent))
    print(f"  seeded pid files (capture/paper -> shell pid {parent})")


# ----------------------- live tick (loop forever) ---------------------------


def _tick_logs(state: dict[str, object]) -> None:
    """Append 1-3 lines to each log file."""
    counter = int(state.get("log_counter", 0))
    for _ in range(RNG.randint(1, 3)):
        counter += 1
        when = _now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        # Mostly INFO, occasionally WARN, rarely ERROR
        roll = RNG.random()
        if roll < 0.02:
            line = (
                f"{when} ERROR polymarket_bot._paper.shadow_book: "
                "stale book skipped (out-of-order ts)"
            )
        elif roll < 0.08:
            line = (
                f"{when} WARNING polymarket_bot._paper.runner: "
                "decision rationale missing side= marker; dropping"
            )
        else:
            line = _paper_log_line(when, counter)
        with PAPER_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    for _ in range(RNG.randint(1, 3)):
        when = _now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        msgs_base = int(state.get("capture_msg_base", 392_017_000))
        line = _capture_log_line(when, counter, msgs_base=msgs_base + counter * 7)
        with CAPTURE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    state["log_counter"] = counter


def _tick_feeds(state: dict[str, object]) -> None:
    """Increment per-feed msgs_seen counters and bump snapshot mtime."""
    if not FEEDS_HEALTH.exists():
        return
    payload = json.loads(FEEDS_HEALTH.read_text(encoding="utf-8"))
    feeds = payload.get("feeds", {})
    growth = {
        "binance": RNG.randint(80, 250),
        "coinbase": RNG.randint(20, 80),
        "oracle": RNG.randint(0, 1),  # heartbeat ~33s
        "polymarket": RNG.randint(2000, 6500),
    }
    now_ns = _ts_ns(_now())
    for name, body in feeds.items():
        body["msgs_seen"] = int(body.get("msgs_seen", 0)) + growth.get(name, 0)
        body["last_seen_ns"] = now_ns - RNG.randint(50_000_000, 1_500_000_000)
    payload["snapshot_ts_utc"] = _now().isoformat()
    _atomic_write_json(FEEDS_HEALTH, payload)


def _tick_decision(state: dict[str, object]) -> None:
    """Fire a new decision (fired + settled pair, since the demo doesn't wait
    a real 5 minutes) and append to today's JSONL."""
    dt = _now()
    fired, settled = _make_decision(dt, want_settled=True)
    date_str = dt.strftime("%Y-%m-%d")
    out = DECISIONS_DIR / f"{date_str}.jsonl"
    with out.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(fired, separators=(",", ":")) + "\n")
        fh.write(json.dumps(settled, separators=(",", ":")) + "\n")
    state["last_decision_dt"] = dt
    pnl = settled.get("pnl_usd", 0.0)
    side = fired.get("side", "?")
    print(f"  [decision] {dt.strftime('%H:%M:%S')} side={side} pnl={pnl:+.4f}")


# ----------------------- helpers --------------------------------------------


def _make_decision(
    dt: datetime, *, want_settled: bool
) -> tuple[dict[str, object], dict[str, object]]:
    side = "UP" if RNG.random() > 0.48 else "DOWN"
    asset_id = ASSET_UP if side == "UP" else ASSET_DOWN
    best_ask = round(RNG.uniform(0.42, 0.62), 4)
    limit = round(best_ask + RNG.uniform(0.005, 0.030), 4)
    fill_price = best_ask + RNG.uniform(0.001, 0.008)
    size_filled = SIZE_USD / fill_price
    fee = SIZE_USD * 0.0002
    composite = round(RNG.uniform(0.6, 1.6), 3) * (1 if side == "UP" else -1)
    won = RNG.random() < 0.58
    resolution = side if won else ("DOWN" if side == "UP" else "UP")
    payout = size_filled if won else 0.0
    pnl = payout - SIZE_USD - fee
    decision_id = f"{RNG.getrandbits(64):016x}{RNG.getrandbits(64):016x}"
    decision_ts_ns = _ts_ns(dt)
    window = _window_start(dt)
    fired = {
        "kind": "fired",
        "decision_id": decision_id,
        "window_ts": window,
        "decision_ts_ns": decision_ts_ns,
        "asset_id": asset_id,
        "side": side,
        "size_usd": SIZE_USD,
        "price_limit": limit,
        "ttl_s": RNG.choice([15, 18, 20, 25]),
        "rationale": f"composite={composite:+.3f}pct (|.|>=0.60) ttl=20s side={side}",
        "snapshot": {
            "spot_now": round(67000 + RNG.gauss(0, 350), 2),
            "window_open_spot": round(67000 + RNG.gauss(0, 200), 2),
            "oracle_last": round(67000 + RNG.gauss(0, 250), 2),
            "open_oracle": round(67000 + RNG.gauss(0, 150), 2),
            "best_bid": round(best_ask - 0.005, 4),
            "best_ask": best_ask,
            "ask_size_top": round(RNG.uniform(2000, 18000), 1),
        },
        "composite_pct": composite,
        "fill": {
            "ts_utc_ns": decision_ts_ns + 100_000_000,
            "asset_id": asset_id,
            "size_filled": round(size_filled, 6),
            "price_filled": round(fill_price, 4),
            "fee_usd": round(fee, 4),
        },
    }
    settled = {
        "kind": "settled",
        "decision_id": decision_id,
        "window_ts": window,
        "settled_ts_ns": decision_ts_ns + 300 * 1_000_000_000,
        "open_oracle": round(67000 + RNG.gauss(0, 200), 2),
        "close_oracle": round(67000 + RNG.gauss(0, 250), 2),
        "resolution": resolution,
        "fill_at_settle": {
            "ts_utc_ns": decision_ts_ns + 100_000_000,
            "asset_id": asset_id,
            "size_filled": round(size_filled, 6),
            "price_filled": round(fill_price, 4),
            "fee_usd": round(fee, 4),
        },
        "pnl_usd": round(pnl, 4),
    }
    return fired, settled if want_settled else fired  # type: ignore[return-value]


def _paper_log_line(when: str, idx: int) -> str:
    asset_tail = f"{idx % 99:02d}"
    return (
        f"{when} INFO polymarket_bot._paper.runner: "
        f"event window={1762500000 + idx * 300} kind=BookUpdate asset=0x...{asset_tail}"
    )


def _capture_log_line(when: str, idx: int, *, msgs_base: int) -> str:
    return (
        f"{when} INFO polymarket_bot._live.feeds.polymarket: "
        f"msgs_seen={msgs_base + idx * 12}  healthy=True"
    )


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


# ----------------------- main loop ------------------------------------------


def _signal_handler(signum: int, frame: object | None) -> None:
    global _STOP
    _STOP = True


def main() -> int:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Seeding demo state at {DEMO_DIR}")
    _seed_decisions()
    _seed_feeds_health()
    _seed_pid_files()
    _seed_logs()
    print()
    print("Live simulator starting. Logs tick every 1.5s, feeds every 4s,")
    print("decisions every ~25s. Stop with Ctrl-C.")
    print()
    print(f"Point the dashboard at: PMB_DASH_STATE_DIR={DEMO_DIR}")
    print()

    state: dict[str, object] = {"log_counter": 0}
    last_log = 0.0
    last_feed = 0.0
    last_decision = time.time() - DECISION_TICK_S + 5  # first decision after 5s
    while not _STOP:
        now = time.time()
        try:
            if now - last_log >= LOG_TICK_S:
                _tick_logs(state)
                last_log = now
            if now - last_feed >= FEED_TICK_S:
                _tick_feeds(state)
                last_feed = now
            if now - last_decision >= DECISION_TICK_S:
                _tick_decision(state)
                last_decision = now
        except Exception as e:
            print(f"  [tick error] {e!r}", file=sys.stderr)
        time.sleep(0.5)
    print("Stopping simulator.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
