"""CLI: sweep DeterministicStrategy thresholds over captured Parquet ticks.

Driven by the operator's "what's the point lol" question (2026-05-08): the
live bot at threshold 0.6 may go many windows without firing. Rather than
lower the threshold reflexively, this script runs the backtest engine over
recent captured data at thresholds {0.3, 0.4, 0.5, 0.6} and emits
dashboard-readable JSONL so the operator can SEE what each threshold
would have decided across the captured days. Output structure mirrors
`state/decisions/<UTC-date>.jsonl` so `PMB_DASH_STATE_DIR=state/replay/
threshold_0.4 streamlit run scripts/dashboard.py` renders without any
dashboard code change.

Usage:
  uv run python scripts/run_replay_calibration.py \
    --ticks-root /path/to/ticks \
    --dates 2026-05-06,2026-05-07 \
    --thresholds 0.3,0.4,0.5,0.6 \
    --out-root state/replay

Output:
  state/replay/threshold_0.3/decisions/<UTC-date>.jsonl
  state/replay/threshold_0.4/decisions/<UTC-date>.jsonl
  ...
  state/replay/summary.md            # one-page comparison table
  state/replay/summary.json          # machine-readable

This is a calibration / decision-support artifact, NOT a strategy change.
Lowering decision #6's locked threshold still requires a written
`runbooks/decisions/threshold-revision.md` per anti-vibe rule #1; the
output here is the *evidence* that revision would cite, not the revision.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import polars as pl  # noqa: E402

from polymarket_bot._live.feeds.polymarket import GammaClient  # noqa: E402
from polymarket_bot.backtest.fills import FillSimulator  # noqa: E402
from polymarket_bot.backtest.replay import ReplayEngine  # noqa: E402
from polymarket_bot.backtest.runner import (  # noqa: E402
    BacktestRunner,
    WindowResult,
    aggregate_metrics,
)
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.resolver import active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import DeterministicStrategy  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_replay_calibration")

DEFAULT_THRESHOLDS = (0.3, 0.4, 0.5, 0.6)


def _ensure_dir(path: Path) -> None:
    """Sync wrapper around Path.mkdir; called from async main to satisfy ASYNC240."""
    path.mkdir(parents=True, exist_ok=True)


def _discover_windows(ticks_root: Path, dates: list[str]) -> list[int]:
    windows: set[int] = set()
    for date in dates:
        for path in (ticks_root / date).glob("polymarket_*.parquet"):
            try:
                ts_col = pl.read_parquet(path).get_column("ts_utc_ns")
            except Exception as e:
                LOG.warning("skipping %s: %s", path, e)
                continue
            for ts_ns in ts_col:
                windows.add(active_window_ts(ts_ns // 1_000_000_000))
    return sorted(windows)


def _date_str_for_window(window_ts: int) -> str:
    return datetime.fromtimestamp(window_ts, tz=UTC).strftime("%Y-%m-%d")


def _result_to_jsonl_lines(r: WindowResult) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert one WindowResult to (fired_line, settled_line) matching DecisionLog schema."""
    decision_id = uuid.uuid4().hex
    decision_ts_ns = r.window_ts * 1_000_000_000
    side = r.side or "UP"
    asset_id = "replay-asset"
    size_usd = 5.0
    price_limit = r.fill.price_filled if r.fill is not None else 0.0
    composite = None
    if "composite=" in r.rationale:
        try:
            tail = r.rationale.split("composite=")[1]
            num = ""
            for ch in tail:
                if ch.isdigit() or ch in ".+-eE":
                    num += ch
                else:
                    break
            composite = float(num) if num else None
        except (IndexError, ValueError):
            composite = None
    fired = {
        "kind": "fired",
        "decision_id": decision_id,
        "window_ts": r.window_ts,
        "decision_ts_ns": decision_ts_ns,
        "asset_id": asset_id,
        "side": side,
        "size_usd": size_usd,
        "price_limit": price_limit,
        "ttl_s": 30,
        "rationale": r.rationale,
        "snapshot": {},
        "composite_pct": composite,
        "fill": (
            None
            if r.fill is None
            else {
                "ts_utc_ns": r.fill.ts_utc_ns,
                "asset_id": r.fill.asset_id,
                "size_filled": r.fill.size_filled,
                "price_filled": r.fill.price_filled,
                "fee_usd": r.fill.fee_usd,
            }
        ),
    }
    settled = {
        "kind": "settled",
        "decision_id": decision_id,
        "window_ts": r.window_ts,
        "settled_ts_ns": (r.window_ts + 300) * 1_000_000_000,
        "open_oracle": None,
        "close_oracle": None,
        "resolution": r.resolution,
        "fill_at_settle": (
            None
            if r.fill is None
            else {
                "ts_utc_ns": r.fill.ts_utc_ns,
                "asset_id": r.fill.asset_id,
                "size_filled": r.fill.size_filled,
                "price_filled": r.fill.price_filled,
                "fee_usd": r.fill.fee_usd,
            }
        ),
        "pnl_usd": r.pnl_usd,
    }
    return fired, settled


def _write_jsonl_for_threshold(
    threshold: float, results: Sequence[WindowResult], out_root: Path
) -> Path:
    threshold_dir = out_root / f"threshold_{threshold:.1f}"
    decisions_dir = threshold_dir / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    handles: dict[str, Any] = {}
    fired_count = 0
    try:
        for r in results:
            if not r.fired:
                continue
            fired_count += 1
            date = _date_str_for_window(r.window_ts)
            fh = handles.get(date)
            if fh is None:
                fh = (decisions_dir / f"{date}.jsonl").open("a", encoding="utf-8")
                handles[date] = fh
            fired_line, settled_line = _result_to_jsonl_lines(r)
            fh.write(json.dumps(fired_line, separators=(",", ":")) + "\n")
            fh.write(json.dumps(settled_line, separators=(",", ":")) + "\n")
    finally:
        for fh in handles.values():
            fh.close()
    LOG.info(
        "threshold %.1f: wrote %d fired+settled pairs to %s", threshold, fired_count, decisions_dir
    )
    return threshold_dir


async def _run_one_threshold(
    threshold: float,
    *,
    replay_root: Path,
    dates: list[str],
    side_resolver: TokenSideIndex,
) -> list[WindowResult]:
    LOG.info("=== threshold %.1f ===", threshold)
    replay = ReplayEngine(replay_root, dates, side_resolver=side_resolver)
    strategy = DeterministicStrategy(threshold_pct=threshold)
    runner = BacktestRunner(replay, simulator=FillSimulator())
    return await runner.run(strategy)


def _summary_row(threshold: float, results: Sequence[WindowResult]) -> dict[str, Any]:
    metrics = aggregate_metrics(results)
    return {
        "threshold_pct": threshold,
        **metrics,
    }


def _render_summary_md(rows: list[dict[str, Any]], dates: list[str]) -> str:
    lines: list[str] = []
    lines.append("# Replay calibration — DeterministicStrategy threshold sweep")
    lines.append("")
    lines.append(f"Dates replayed: {', '.join(dates)}")
    lines.append("")
    lines.append("| threshold | windows | fires | fill-rate | win-rate | gross-PnL | per-fire |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|")
    for row in rows:
        thr = row.get("threshold_pct", 0.0)
        windows = row.get("n_windows", 0) or row.get("windows", 0)
        fires = row.get("n_fired", 0) or row.get("fired", 0)
        fills = row.get("n_filled", 0) or row.get("filled", 0)
        wins = row.get("n_won", 0) or row.get("wins", 0)
        pnl = row.get("total_pnl_usd", 0.0) or row.get("pnl_usd", 0.0)
        fill_rate = (fills / fires) if fires else 0.0
        win_rate = (wins / fills) if fills else 0.0
        per_fire = (pnl / fires) if fires else 0.0
        lines.append(
            f"| {thr:.1f}pp | {windows} | {fires} | {fill_rate:.1%} | {win_rate:.1%} | "
            f"${pnl:+.2f} | ${per_fire:+.2f} |"
        )
    lines.append("")
    lines.append(
        "**Reading the table.** `windows` = total 5-min windows in the data. "
        "`fires` = how many the strategy decided to bet on. `fill-rate` = "
        "of the fires, how many got a simulated fill. `win-rate` = of the "
        "fills, how many won. `gross-PnL` = sum of realised PnL on the "
        "filled trades (fees included). `per-fire` = gross-PnL ÷ fires "
        "(the strategy's expected return per signal)."
    )
    lines.append("")
    lines.append(
        "**Don't draw strategy conclusions from this alone.** The dataset "
        "is small (a few capture sessions); win-rate variance at low fire "
        "counts is huge. Use this as a sanity check, not as evidence to "
        "revise locked decision #6."
    )
    return "\n".join(lines)


async def main(
    *,
    ticks_root: Path,
    dates: list[str],
    thresholds: list[float],
    out_root: Path,
    cache_path: Path,
) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    print(f"==> discovering windows in {ticks_root} for dates {dates}", flush=True)
    windows = _discover_windows(ticks_root, dates)
    print(f"    found {len(windows)} unique 5m windows", flush=True)
    if not windows:
        print("    no polymarket data found; exiting.")
        return 1

    print(f"==> warming TokenSideIndex (cache={cache_path})", flush=True)
    gamma = GammaClient()
    index = TokenSideIndex(fetch_fn=gamma.fetch_event, cache_path=cache_path)
    n_new = await index.warm(windows)
    print(
        f"    {index.n_known_tokens} tokens mapped ({n_new} new fetches)",
        flush=True,
    )

    _ensure_dir(out_root)
    summary_rows: list[dict[str, Any]] = []
    started_at = time.time()
    for threshold in thresholds:
        results = await _run_one_threshold(
            threshold, replay_root=ticks_root, dates=dates, side_resolver=index
        )
        _write_jsonl_for_threshold(threshold, results, out_root)
        summary_rows.append(_summary_row(threshold, results))
    elapsed = time.time() - started_at

    summary_md = _render_summary_md(summary_rows, dates)
    (out_root / "summary.md").write_text(summary_md, encoding="utf-8")
    (out_root / "summary.json").write_text(
        json.dumps({"dates": dates, "rows": summary_rows}, indent=2),
        encoding="utf-8",
    )
    print()
    print(summary_md)
    print()
    print(f"==> wrote per-threshold JSONL + summary to {out_root}")
    print(f"==> elapsed: {elapsed:.1f}s")
    print()
    print("    open the dashboard for any threshold with:")
    for threshold in thresholds:
        print(
            f"      PMB_DASH_STATE_DIR={out_root}/threshold_{threshold:.1f} "
            f"uv run streamlit run scripts/dashboard.py"
        )
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticks-root", default="ticks", type=Path)
    parser.add_argument(
        "--dates",
        required=True,
        help="Comma-separated UTC dates (YYYY-MM-DD) to replay over.",
    )
    parser.add_argument(
        "--thresholds",
        default=",".join(f"{t:.1f}" for t in DEFAULT_THRESHOLDS),
        help="Comma-separated thresholds to sweep (default: 0.3,0.4,0.5,0.6)",
    )
    parser.add_argument("--out-root", default="state/replay", type=Path)
    parser.add_argument(
        "--cache-path",
        default="state/token_side_index.json",
        type=Path,
        help="TokenSideIndex JSON cache to reuse across runs.",
    )
    args = parser.parse_args()
    dates = [d.strip() for d in args.dates.split(",") if d.strip()]
    thresholds = [float(t.strip()) for t in args.thresholds.split(",") if t.strip()]
    rc = asyncio.run(
        main(
            ticks_root=args.ticks_root,
            dates=dates,
            thresholds=thresholds,
            out_root=args.out_root,
            cache_path=args.cache_path,
        )
    )
    sys.exit(rc)


if __name__ == "__main__":
    cli()
