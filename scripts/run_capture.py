"""CLI entry point — `uv run python scripts/run_capture.py` starts the four-feed capture.

Runs polymarket_bot._live.runtime.main() with default feeds, default ticks
directory (./ticks/), and default health snapshot path (./state/feeds_health.json).
Logs to stderr + ./state/capture.log. SIGTERM/SIGINT trigger graceful
shutdown that drains the queue and closes Parquet writers. This script is
the production capture entry point invoked by the tmux session in Task 2.5.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polymarket_bot._live.runtime import configure_logging, main  # noqa: E402


def cli() -> None:
    configure_logging(log_path="state/capture.log")
    total = asyncio.run(main(ticks_root="ticks", health_path="state/feeds_health.json"))
    print(f"capture finished: records_written={total}", file=sys.stderr)


if __name__ == "__main__":
    cli()
