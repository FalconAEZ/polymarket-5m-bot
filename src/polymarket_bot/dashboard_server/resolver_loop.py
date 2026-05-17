"""Background re-resolution loop — keeps state/decisions-resolved/ fresh.

The bot writes raw decisions to state/decisions/*.jsonl using the
Chainlink-local oracle as resolution truth. That truth disagrees with
Polymarket Streams on ~33% of windows (per
runbooks/incidents/2026-05-09-oracle-resolver-mismatch.md), so the
dashboard reads the WRONG PnL when reading those raw files. This loop
periodically re-resolves them via Polymarket Gamma and writes the
corrected JSONL to a SEPARATE directory (state/decisions-resolved/),
which the dashboard's state.snapshot() prefers when present.

Mirrors what runbooks/scripts/sync_staging.sh does on the laptop, but
in-process inside the dashboard backend so the operator-facing
dashboard on the VPS doesn't need a sidecar systemd timer.

Per runbooks/incidents/2026-05-09-dashboard-shows-oracle-truth.md.

Implementation notes:
  * Uses ``asyncio.to_thread`` to wrap the synchronous httpx I/O so the
    event loop stays responsive.
  * Idempotent: ``re_resolve_file`` skips records that already have
    ``resolution_source: "polymarket"``. Repeated invocations are cheap.
  * Writes via tmp+rename to a SEPARATE directory — never in-place over
    the bot's append FDs (orphan-FD failure mode).
  * On Gamma errors / network blips: logs and retries on the next tick.
    The dashboard falls back to oracle-truth automatically if the
    resolved dir is empty or stale.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from polymarket_bot.dashboard.gamma_resolver import re_resolve_dir

log = logging.getLogger("dashboard_server.resolver_loop")

DEFAULT_RAW_SUBDIR = "decisions"
DEFAULT_RESOLVED_SUBDIR = "decisions-resolved"
DEFAULT_INTERVAL_S: float = 300.0  # 5 minutes — balances freshness vs Gamma calls
INITIAL_DELAY_S: float = 2.0  # warm up briefly so the dashboard renders before first pass


@dataclass(slots=True)
class ResolverState:
    """Observable state of the resolver loop. Read by snapshot() so the
    dashboard panel can show 'last resolved 4m ago' / 'last error: ...'.
    """

    last_attempt_utc: datetime | None = None
    last_success_utc: datetime | None = None
    last_error: str | None = None
    n_runs: int = 0
    n_files_processed: int = 0
    n_records_changed: int = 0
    enabled: bool = True


@dataclass(slots=True)
class ResolverConfig:
    """Caller-controllable knobs. Defaults are right for the VPS."""

    raw_subdir: str = DEFAULT_RAW_SUBDIR
    resolved_subdir: str = DEFAULT_RESOLVED_SUBDIR
    interval_s: float = DEFAULT_INTERVAL_S
    initial_delay_s: float = INITIAL_DELAY_S


def _run_one_pass_blocking(state_dir: Path, *, config: ResolverConfig) -> tuple[int, int, int]:
    """Synchronous one-pass body — runs in a worker thread."""
    raw_dir = state_dir / config.raw_subdir
    resolved_dir = state_dir / config.resolved_subdir
    if not raw_dir.is_dir():
        log.info("raw decisions dir missing: %s", raw_dir)
        return (0, 0, 0)
    with httpx.Client() as client:
        return re_resolve_dir(raw_dir, resolved_dir, client=client)


async def resolver_loop(
    state_dir: Path,
    state: ResolverState,
    *,
    config: ResolverConfig | None = None,
) -> None:
    """Periodically re-resolve decisions JSONL into a separate dir.

    Designed to be spawned via ``asyncio.create_task`` from the dashboard
    server's lifespan. Cancellation is honored cleanly.
    """
    cfg = config or ResolverConfig()
    if not state.enabled:
        log.info("resolver loop disabled by config")
        return
    log.info(
        "resolver loop starting: raw=%s resolved=%s interval=%.0fs",
        state_dir / cfg.raw_subdir,
        state_dir / cfg.resolved_subdir,
        cfg.interval_s,
    )
    try:
        await asyncio.sleep(cfg.initial_delay_s)
        while True:
            state.last_attempt_utc = datetime.now(tz=UTC)
            state.n_runs += 1
            try:
                _n_settled, n_changed, _n_unresolvable = await asyncio.to_thread(
                    _run_one_pass_blocking, state_dir, config=cfg
                )
                state.last_success_utc = datetime.now(tz=UTC)
                state.last_error = None
                state.n_files_processed += 1  # one pass — count the pass, not files
                state.n_records_changed += n_changed
                if n_changed:
                    log.info(
                        "resolver pass: %d settled records re-resolved (changed)",
                        n_changed,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                state.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("resolver pass failed: %s", state.last_error)
            await asyncio.sleep(cfg.interval_s)
    except asyncio.CancelledError:
        log.info("resolver loop cancelled")
        raise


def spawn_resolver_task(
    state_dir: Path, state: ResolverState, *, config: ResolverConfig | None = None
) -> asyncio.Task[None]:
    """Convenience wrapper — mirrors ``upstream.spawn_upstream_tasks``."""
    return asyncio.create_task(
        resolver_loop(state_dir, state, config=config), name="dashboard-resolver"
    )


async def cancel_resolver_task(task: asyncio.Task[None]) -> None:
    """Cancel + await — mirrors ``upstream.cancel_upstream_tasks``."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
