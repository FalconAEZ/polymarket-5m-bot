"""FastAPI app — wires REST snapshot + WS push + static React build.

Bind to 127.0.0.1:8505 only; the SSH tunnel is the only access path.
Serves the v3 React app from apps/dashboard-v3/dist/ as static files,
plus /api/state (current snapshot JSON) and /api/live (WebSocket diff
stream). Per design/dashboard-v3.md §4.5.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from polymarket_bot.dashboard.loaders import load_decisions
from polymarket_bot.dashboard_server.state import (
    DECISIONS_SUBDIR,
    UpstreamCache,
    snapshot,
)
from polymarket_bot.dashboard_server.upstream import (
    cancel_upstream_tasks,
    spawn_upstream_tasks,
)

log = logging.getLogger("dashboard_server.app")

ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATIC_DIR = ROOT / "apps" / "dashboard-v3" / "dist"

PUSH_INTERVAL_S: float = 1.0
PUSH_FAST_INTERVAL_S: float = 0.25  # when on_update set, push within this


def _state_dir() -> Path:
    return Path(os.environ.get("PMB_DASH_STATE_DIR", str(ROOT / "state")))


def _resolve_current_window_side() -> tuple[int | None, str | None]:
    """Returns (window_ts, side) for the most-recent fired decision so
    the CTF poller can subscribe to the right token. Returns (None, None)
    when no decisions exist yet."""
    state_dir = _state_dir()
    rows = load_decisions(state_dir / DECISIONS_SUBDIR, since_utc_date=None)
    if not rows:
        return (None, None)
    most_recent = max(rows, key=lambda r: r.decision_dt_utc)
    return (most_recent.window_ts, most_recent.side)


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    cache = UpstreamCache()
    on_update = asyncio.Event()
    tasks = spawn_upstream_tasks(
        cache,
        state_dir_resolver=_resolve_current_window_side,
        on_update=on_update,
    )
    app.state.upstream_cache = cache
    app.state.on_update = on_update
    app.state.upstream_tasks = tasks
    try:
        yield
    finally:
        await cancel_upstream_tasks(tasks)


app = FastAPI(title="Polymarket bot dashboard v3", lifespan=lifespan)


@app.get("/api/state")
async def get_state() -> JSONResponse:
    cache: UpstreamCache = app.state.upstream_cache
    snap = snapshot(_state_dir(), upstream=cache)
    return JSONResponse(snap)


@app.get("/api/health")
async def get_health() -> JSONResponse:
    return JSONResponse({"ok": True})


@app.websocket("/api/live")
async def live_ws(ws: WebSocket) -> None:
    await ws.accept()
    cache: UpstreamCache = app.state.upstream_cache
    on_update: asyncio.Event = app.state.on_update
    state_dir = _state_dir()
    try:
        snap = snapshot(state_dir, upstream=cache)
        await ws.send_text(json.dumps({"type": "snapshot", "state": snap}))
        while True:
            try:
                await asyncio.wait_for(on_update.wait(), timeout=PUSH_INTERVAL_S)
                on_update.clear()
                await asyncio.sleep(PUSH_FAST_INTERVAL_S)  # batch quick updates
            except TimeoutError:
                pass
            snap = snapshot(state_dir, upstream=cache)
            await ws.send_text(json.dumps({"type": "snapshot", "state": snap}))
    except WebSocketDisconnect:
        log.info("ws client disconnected")
    except Exception as exc:  # never crash the route
        log.exception("ws error: %s", exc)


def _maybe_mount_static() -> None:
    """Mount the Vite build output if it exists. During dev (vite dev
    server on 5173) the React app proxies /api/* to FastAPI, so the
    static mount is empty — that's fine."""
    if STATIC_DIR.exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="dist")
    else:
        log.info("static build %s does not exist; serving API only", STATIC_DIR)


_maybe_mount_static()
