"""Entry point — `python -m polymarket_bot.dashboard_server`.

Reads PMB_DASHBOARD_HOST + PMB_DASHBOARD_PORT (defaults 127.0.0.1:8505)
and launches the FastAPI app via uvicorn. systemd unit at
runbooks/staging/dashboard-server.service. Per design/dashboard-v3.md
§10.
"""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("PMB_DASHBOARD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    host = os.environ.get("PMB_DASHBOARD_HOST", "127.0.0.1")
    port = int(os.environ.get("PMB_DASHBOARD_PORT", "8505"))
    uvicorn.run(
        "polymarket_bot.dashboard_server.app:app",
        host=host,
        port=port,
        log_level=os.environ.get("PMB_DASHBOARD_LOG_LEVEL", "info").lower(),
        access_log=False,
    )


if __name__ == "__main__":
    main()
