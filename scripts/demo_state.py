"""Populate a fake state/ directory under state-demo/ for the dashboard demo.

Generates realistic-shaped data so the operator can see what every panel
looks like *populated* without waiting for the 14-day paper run:
  - state-demo/decisions/<UTC-date>.jsonl  — 80 fired+settled decisions
    spread across 3 days, ~58% win rate, mixed PnL, plausible rationales
  - state-demo/feeds_health.json — all 4 feeds healthy with growing msg counts
  - state-demo/capture.pid + state-demo/paper.pid — pointing at THIS process so
    psutil reports them alive
  - state-demo/paper.log + state-demo/capture.log — synthetic INFO lines
    (a few WARN / ERROR mixed in for the color-coded log panel)

Run with:
  uv run python scripts/demo_state.py

Then open the dashboard pointing at the demo state-dir:
  uv run streamlit run scripts/dashboard.py
  ... and in the sidebar set "state/ dir" to "state-demo"

Demo state is gitignored alongside real state/. Delete with `rm -rf state-demo`.
"""

from __future__ import annotations

import json
import os
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "state-demo"
DECISIONS_DIR = DEMO_DIR / "decisions"

ASSET_UP = "0x" + "11" * 32
ASSET_DOWN = "0x" + "22" * 32
SIZE_USD = 5.0


def _ts(dt: datetime) -> int:
    return int(dt.timestamp() * 1_000_000_000)


def _window_ts(dt: datetime) -> int:
    s = int(dt.timestamp())
    return s - (s % 300)


def _make_decisions(seed: int = 42) -> dict[str, list[dict[str, object]]]:
    """Generate ~80 decisions over 3 UTC days, ~58% win rate, varied PnL."""
    rng = random.Random(seed)  # noqa: S311 — demo data, not security-sensitive
    by_day: dict[str, list[dict[str, object]]] = {}
    # Three days back to today (UTC)
    today_utc = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    days = [today_utc - timedelta(days=2 - i) for i in range(3)]
    cumulative_pnl = 0.0
    for day in days:
        date_str = day.strftime("%Y-%m-%d")
        # ~25-35 decisions per day, randomly across the window
        n_decisions = rng.randint(25, 35)
        offsets_min = sorted(rng.sample(range(60, 1380), n_decisions))  # within day
        for offset in offsets_min:
            decision_dt = day + timedelta(minutes=offset)
            window_open = _window_ts(decision_dt)
            decision_ts_ns = _ts(decision_dt)
            settled_dt = decision_dt + timedelta(seconds=300)
            side = "UP" if rng.random() > 0.48 else "DOWN"
            asset_id = ASSET_UP if side == "UP" else ASSET_DOWN
            best_ask = round(rng.uniform(0.42, 0.62), 4)
            limit = round(best_ask + rng.uniform(0.005, 0.030), 4)
            fill_price = best_ask + rng.uniform(0.001, 0.008)
            size_filled = SIZE_USD / fill_price
            fee = SIZE_USD * 0.0002
            composite = round(rng.uniform(0.6, 1.6), 3) * (1 if side == "UP" else -1)
            # 58% win-rate
            won = rng.random() < 0.58
            resolution = side if won else ("DOWN" if side == "UP" else "UP")
            payout = size_filled if won else 0.0
            pnl = payout - SIZE_USD - fee
            cumulative_pnl += pnl
            decision_id = f"{rng.getrandbits(64):016x}{rng.getrandbits(64):016x}"

            fired = {
                "kind": "fired",
                "decision_id": decision_id,
                "window_ts": window_open,
                "decision_ts_ns": decision_ts_ns,
                "asset_id": asset_id,
                "side": side,
                "size_usd": SIZE_USD,
                "price_limit": limit,
                "ttl_s": rng.choice([15, 18, 20, 25]),
                "rationale": (f"composite={composite:+.3f}pct (|.|>=0.60) " f"ttl=20s side={side}"),
                "snapshot": {
                    "spot_now": round(67000 + rng.gauss(0, 350), 2),
                    "window_open_spot": round(67000 + rng.gauss(0, 200), 2),
                    "oracle_last": round(67000 + rng.gauss(0, 250), 2),
                    "open_oracle": round(67000 + rng.gauss(0, 150), 2),
                    "best_bid": round(best_ask - 0.005, 4),
                    "best_ask": best_ask,
                    "ask_size_top": round(rng.uniform(2000, 18000), 1),
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
                "window_ts": window_open,
                "settled_ts_ns": _ts(settled_dt),
                "open_oracle": round(67000 + rng.gauss(0, 200), 2),
                "close_oracle": round(67000 + rng.gauss(0, 250), 2),
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
            by_day.setdefault(date_str, []).append(fired)
            by_day[date_str].append(settled)
    return by_day


def _write_decisions(by_day: dict[str, list[dict[str, object]]]) -> None:
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    for date_str, lines in by_day.items():
        out = DECISIONS_DIR / f"{date_str}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for line in lines:
                fh.write(json.dumps(line, separators=(",", ":")) + "\n")


def _write_feeds_health() -> None:
    now_ns = int(datetime.now(tz=UTC).timestamp() * 1_000_000_000)
    payload = {
        "snapshot_ts_utc": datetime.now(tz=UTC).isoformat(),
        "feeds": {
            "binance": {
                "name": "binance",
                "msgs_seen": 18_472_103,
                "healthy": True,
                "reconnects": 2,
                "last_error": "",
                "last_seen_ns": now_ns - 800_000_000,
            },
            "coinbase": {
                "name": "coinbase",
                "msgs_seen": 5_438_290,
                "healthy": True,
                "reconnects": 0,
                "last_error": "",
                "last_seen_ns": now_ns - 1_200_000_000,
            },
            "oracle": {
                "name": "oracle",
                "msgs_seen": 21_843,
                "healthy": True,
                "reconnects": 1,
                "last_error": "",
                "last_seen_ns": now_ns - 9_400_000_000,
            },
            "polymarket": {
                "name": "polymarket",
                "msgs_seen": 392_017_551,
                "healthy": True,
                "reconnects": 4,
                "last_error": "",
                "last_seen_ns": now_ns - 100_000_000,
            },
        },
    }
    (DEMO_DIR / "feeds_health.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_pid_files() -> None:
    own_pid = os.getpid()
    # In a normal run this script exits before the dashboard reads the PIDs.
    # That's a problem for "alive" rendering — so we write the parent shell's
    # PID instead, which is alive for the operator's session.
    parent_pid = os.getppid()
    (DEMO_DIR / "capture.pid").write_text(str(parent_pid))
    (DEMO_DIR / "paper.pid").write_text(str(parent_pid))
    print(f"  PIDs point at parent shell (pid {parent_pid}); demo run pid was {own_pid}")


def _write_logs() -> None:
    now = datetime.now(tz=UTC)
    paper_lines = []
    capture_lines = []
    for i in range(120):
        when = (now - timedelta(seconds=(120 - i) * 7)).strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        paper_lines.append(
            f"{when} INFO polymarket_bot._paper.runner: "
            f"event window={1762500000 + i * 300} kind=BookUpdate asset=0x...{i % 99:02d}"
        )
        capture_lines.append(
            f"{when} INFO polymarket_bot._live.feeds.polymarket: "
            f"msgs_seen={392_017_000 + i * 12}  healthy=True"
        )
    # Sprinkle a few warnings/errors so the color coding shows.
    paper_lines[-30] = (
        f"{(now - timedelta(seconds=210)).strftime('%Y-%m-%d %H:%M:%S,000')} "
        "WARNING polymarket_bot._paper.runner: decision rationale missing side= marker; dropping"
    )
    paper_lines[-12] = (
        f"{(now - timedelta(seconds=84)).strftime('%Y-%m-%d %H:%M:%S,000')} "
        "ERROR polymarket_bot._paper.shadow_book: stale book skipped (out-of-order ts)"
    )
    capture_lines[-50] = (
        f"{(now - timedelta(seconds=350)).strftime('%Y-%m-%d %H:%M:%S,000')} "
        "WARNING polymarket_bot._live.feeds.oracle: WS reconnect attempt 1/5"
    )
    (DEMO_DIR / "paper.log").write_text("\n".join(paper_lines) + "\n", encoding="utf-8")
    (DEMO_DIR / "capture.log").write_text("\n".join(capture_lines) + "\n", encoding="utf-8")


def main() -> int:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing demo state to: {DEMO_DIR}")
    print("  decisions/<UTC-date>.jsonl ...")
    by_day = _make_decisions(seed=42)
    _write_decisions(by_day)
    total_lines = sum(len(v) for v in by_day.values())
    print(f"  -> {len(by_day)} files, {total_lines} lines")
    print("  feeds_health.json ...")
    _write_feeds_health()
    print("  capture.pid + paper.pid ...")
    _write_pid_files()
    print("  paper.log + capture.log ...")
    _write_logs()
    print()
    print("Done. Launch the dashboard against the demo state with:")
    print("  uv run streamlit run scripts/dashboard.py")
    print("Then in the sidebar set 'state/ dir' to:")
    print(f"  {DEMO_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
