"""CLI entry — `uv run python -u scripts/run_alerter.py` starts tg-alerter.

Reads `REDIS_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` from the
environment (sourced from `.envrc` by the bash wrapper in
`runbooks/systemd/tg-alerter.service`). Constructs the production async
Redis + httpx Telegram clients, then calls `polymarket_bot._live.alerter.
service.main`. Two concurrent loops drain the alert queue and long-poll for
`/halt`. SIGTERM/SIGINT trigger graceful shutdown via the service's stop
event. Per locked decision #7, Telegram is the only operator surface; per
design/alerter.md §5, this process is the only thing that talks to the
Telegram Bot API.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polymarket_bot._live.alerter.halt import write_halt_sentinel  # noqa: E402
from polymarket_bot._live.alerter.redis_queue import RedisQueueImpl  # noqa: E402
from polymarket_bot._live.alerter.service import main as alerter_main  # noqa: E402
from polymarket_bot._live.alerter.telegram_client import TelegramClientImpl  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_alerter")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    # httpx logs the full request URL at INFO, which exposes the Telegram
    # bot token in the systemd journal. Suppress unless something fails.
    logging.getLogger("httpx").setLevel(logging.WARNING)


async def _amain() -> int:
    _configure_logging()
    redis_url = os.environ["REDIS_URL"]
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    LOG.info("tg-alerter starting; redis=%s chat_id=%s", redis_url, chat_id)
    redis_q = RedisQueueImpl(url=redis_url)
    telegram = TelegramClientImpl(bot_token=bot_token)
    return await alerter_main(
        redis_q=redis_q,
        telegram=telegram,
        chat_id=chat_id,
        halt_writer=write_halt_sentinel,
        clock_ns=time.time_ns,
    )


def cli() -> None:
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    cli()
