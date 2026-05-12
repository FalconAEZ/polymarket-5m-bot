"""CLI entry — `uv run python -u scripts/run_paper.py` starts paper-mode trading.

Wires the four real WS feeds (Binance, Coinbase, Chainlink oracle, Polymarket)
into a PaperRunner driving the deterministic Strategy. ShadowBook simulates
fills against the latest book per asset_id; DecisionLog writes JSONL to
state/decisions/<UTC-date>.jsonl. A background warmer task keeps the
TokenSideIndex pre-resolved ~1 hour ahead so the SideResolver answers
synchronously when polymarket BookUpdates flow through. SIGTERM/SIGINT
trigger graceful shutdown — drain queue, close files. PID written to
state/paper.pid by the launcher (runbooks/paper-monitor.md), not by this
script.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import os.path
import signal
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polymarket_bot.strategies.every_window import Router

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from polymarket_bot._live.feeds.oracle import OracleFeed  # noqa: E402
from polymarket_bot._live.feeds.polymarket import GammaClient, PolymarketFeed  # noqa: E402
from polymarket_bot._live.feeds.spot_binance import BinanceTradeFeed  # noqa: E402
from polymarket_bot._live.feeds.spot_coinbase import CoinbaseMatchFeed  # noqa: E402
from polymarket_bot._paper.decision_log import DecisionLog  # noqa: E402
from polymarket_bot._paper.runner import PaperRunner  # noqa: E402
from polymarket_bot._paper.shadow_book import ShadowBook  # noqa: E402
from polymarket_bot.alerts import AlertSink, NullAlertSink, RedisAlertSink  # noqa: E402
from polymarket_bot.backtest.side_index import TokenSideIndex  # noqa: E402
from polymarket_bot.feeds.protocols import Feed  # noqa: E402
from polymarket_bot.resolver import WINDOW_SECONDS, active_window_ts  # noqa: E402
from polymarket_bot.strategies.deterministic import (  # noqa: E402
    DEFAULT_THRESHOLD_PCT,
    DeterministicStrategy,
)
from polymarket_bot.strategies.protocol import Strategy  # noqa: E402
from polymarket_bot.strategies.regime_detector import RegimeDetector  # noqa: E402
from polymarket_bot.strategies.spot_aware import SpotAwareStrategy  # noqa: E402
from polymarket_bot.strategies.spot_aware_priors import load_priors  # noqa: E402
from polymarket_bot.strategies.spot_aware_v2 import SpotAwareStrategyV2  # noqa: E402

LOG = logging.getLogger("polymarket_bot.scripts.run_paper")
WARM_LOOKAHEAD_WINDOWS = 12  # ~1 hour of windows pre-resolved
WARMER_INTERVAL_S = 60.0
HALT_SENTINEL_PATH = Path("state/halt.sentinel")
HALT_POLL_INTERVAL_S = 1.0

# Strategy selection. Default promoted spot_aware → spot_aware_v3 per
# phase-prompts/phase-F-final-stage-architecture-audit-2026-05-13.txt:
# the 5-day truth-corrected audit showed spot_aware family (May 9-10)
# beat ensemble+wide_fire (May 11-12) on both WR (52% vs 38-44%) and
# per-trade PnL (+$0.17/+$0.25 vs -$0.40/-$0.96). v3 = v2 + regime
# detector gate (runbooks/gate-evidence/regime-classifier-validation.txt:
# trending WR 70.59% vs chop 47.40%). Override via STRATEGY env var =
# "deterministic" | "spot_aware" | "spot_aware_v2" | "spot_aware_v3" |
# "ensemble". Ensemble + wide_fire stay in the dispatch as research
# artifacts — re-enable via env flip only.
DEFAULT_STRATEGY_NAME = "spot_aware_v3"


def _configure_logging() -> None:
    # nohup-style launchers redirect stdout/stderr to state/paper.log; a
    # second FileHandler would duplicate every line. StreamHandler only.
    Path("state").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )


def _default_feeds() -> list[Feed]:
    return [
        BinanceTradeFeed(),
        CoinbaseMatchFeed(),
        OracleFeed(),
        PolymarketFeed(),
    ]


def _sentinel_present(sentinel_str: str) -> bool:
    """Sync wrapper around os.path.exists.

    Kept sync (and out of any async function) because ruff's ASYNC240 flags
    pathlib/os.path calls inside async defs. The check is a microsecond
    stat() — pushing it to a worker thread would cost more than the syscall.
    """
    return os.path.exists(sentinel_str)


async def _halt_watcher(
    stop: asyncio.Event,
    *,
    sentinel: Path = HALT_SENTINEL_PATH,
    interval_s: float = HALT_POLL_INTERVAL_S,
) -> None:
    """Poll for the halt sentinel; on presence, set the runner stop_event.

    Per design/alerter.md §4.4: the bot reads the sentinel as opaque presence.
    Corrupt JSON inside still halts. The poll interval is 1s, well below any
    operator-perceptible delay between `/halt` and the bot exiting.
    """
    sentinel_str = str(sentinel)
    while not stop.is_set():
        if _sentinel_present(sentinel_str):
            LOG.warning("halt sentinel detected at %s; setting stop_event", sentinel)
            stop.set()
            return
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=interval_s)


async def _warmer(
    index: TokenSideIndex, *, stop: asyncio.Event, lookahead: int = WARM_LOOKAHEAD_WINDOWS
) -> None:
    """Periodically warm the side index for the next `lookahead` windows.

    Runs every WARMER_INTERVAL_S until `stop` is set. Each tick computes
    the current window from wall-clock time and warms current + lookahead
    consecutive windows (TokenSideIndex skips already-warmed windows
    internally). Gamma misses are logged but never crash the runner.
    """
    LOG.info("warmer started; lookahead=%d windows", lookahead)
    while not stop.is_set():
        try:
            current = active_window_ts(int(time.time()))
            windows = [current + i * WINDOW_SECONDS for i in range(lookahead + 1)]
            n_new = await index.warm(windows)
            if n_new > 0:
                LOG.info(
                    "warmer: fetched %d new windows; total tokens=%d",
                    n_new,
                    index.n_known_tokens,
                )
        except Exception:
            LOG.exception("warmer iteration failed; retrying after interval")
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=WARMER_INTERVAL_S)


def _env_float(name: str, default: float | None) -> float | None:
    """Read an optional float-valued env var. Returns default on missing/empty."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise ValueError(f"env var {name}={raw!r} is not a float") from e


def _env_bool(name: str, default: bool = False) -> bool:
    """Read an optional bool env var. '1', 'true', 'yes' (case-insensitive) → True."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _env_csv(name: str) -> tuple[str, ...]:
    """Read a comma-separated env var into a tuple of trimmed strings.
    Empty string -> empty tuple; whitespace-only items dropped."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ()
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _env_csv_dict_float(name: str) -> dict[str, float] | None:
    """Read a 'key:value,key:value' env var into dict[str, float].
    Returns None on unset; raises ValueError on malformed entries."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    out: dict[str, float] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if ":" not in pair:
            raise ValueError(f"env var {name}: expected 'key:value', got {pair!r}")
        key, val = pair.split(":", 1)
        out[key.strip()] = float(val.strip())
    return out


def _build_router_from_env() -> Router:
    """Build a Phase 16.B Router from `EVERY_WINDOW_*` env vars.

    Defaults match `design/phase-16b-every-window-mode.md` §4. Any
    unset env var leaves the RouterConfig field at its locked default.
    """
    from polymarket_bot.strategies.every_window import Router, RouterConfig
    from polymarket_bot.strategies.every_window.config import (
        DEFAULT_REGIME_SCORE,
        DEFAULT_TAKER_FALLBACK_TIERS,
        DEFAULT_TIER_PER_TRADE_CAP_USD,
        DEFAULT_TIER_SCORE,
    )

    size_floor = _env_float("EVERY_WINDOW_SIZE_FLOOR_USD", 5.0) or 5.0
    size_cap = _env_float("EVERY_WINDOW_SIZE_CAP_USD", 30.0) or 30.0
    kink = _env_float("EVERY_WINDOW_CONFIDENCE_KINK", 0.30) or 0.30
    kelly_frac = _env_float("EVERY_WINDOW_KELLY_FRACTION", 0.5) or 0.5
    kelly_cap = _env_float("EVERY_WINDOW_KELLY_MAX_PCT", 0.03) or 0.03
    bankroll = _env_float("EVERY_WINDOW_BANKROLL_USD", 1000.0) or 1000.0
    w_det = _env_float("EVERY_WINDOW_W_DET", 0.25) or 0.25
    w_reg = _env_float("EVERY_WINDOW_W_REG", 0.20) or 0.20
    w_tier = _env_float("EVERY_WINDOW_W_TIER", 0.15) or 0.15
    w_llm = _env_float("EVERY_WINDOW_W_LLM", 0.25) or 0.25
    w_kelly = _env_float("EVERY_WINDOW_W_KELLY", 0.15) or 0.15

    taker_fb = _env_csv("EVERY_WINDOW_TAKER_FALLBACK_TIERS") or DEFAULT_TAKER_FALLBACK_TIERS
    tier_caps = _env_csv_dict_float("EVERY_WINDOW_TIER_PER_TRADE_CAP_USD") or dict(
        DEFAULT_TIER_PER_TRADE_CAP_USD
    )

    config = RouterConfig(
        w_det=w_det,
        w_reg=w_reg,
        w_tier=w_tier,
        w_llm=w_llm,
        w_kelly=w_kelly,
        size_floor_usd=size_floor,
        size_cap_usd=size_cap,
        confidence_kink=kink,
        kelly_fraction=kelly_frac,
        kelly_max_pct=kelly_cap,
        bankroll_usd=bankroll,
        regime_score=dict(DEFAULT_REGIME_SCORE),
        tier_score=dict(DEFAULT_TIER_SCORE),
        tier_per_trade_cap_usd=tier_caps,
        taker_fallback_tiers=taker_fb,
    )
    return Router(config=config)


def _build_strategy(name: str) -> Strategy:
    if name == "deterministic":
        return DeterministicStrategy(threshold_pct=DEFAULT_THRESHOLD_PCT)
    if name == "spot_aware":
        # Optional env overrides for the loose-start exploratory mode
        # documented in runbooks/decisions/loose-start-2026-05-09.md.
        # Unset → strategy uses its own defaults (Δ_min=8, EV_min=0.5¢).
        kwargs: dict[str, float] = {}
        d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
        if d_min is not None:
            kwargs["delta_min_bps"] = d_min
        d_max = _env_float("SPOT_AWARE_DELTA_MAX_BPS", None)
        if d_max is not None:
            kwargs["delta_max_bps"] = d_max
        ev_min = _env_float("SPOT_AWARE_EV_MIN_DOLLARS", None)
        if ev_min is not None:
            kwargs["ev_min_dollars_per_share"] = ev_min
        limit_buf = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
        if limit_buf is not None:
            kwargs["limit_buffer_usd"] = limit_buf
        aggressive = _env_bool("SPOT_AWARE_AGGRESSIVE_MODE", False)
        # Mypy needs the bool kwarg typed separately from the float dict.
        if kwargs or aggressive:
            LOG.warning(
                "spot_aware overrides: delta_min=%s delta_max=%s ev_min=%s aggressive=%s",
                kwargs.get("delta_min_bps"),
                kwargs.get("delta_max_bps"),
                kwargs.get("ev_min_dollars_per_share"),
                aggressive,
            )
        return SpotAwareStrategy(priors=load_priors(), aggressive_mode=aggressive, **kwargs)
    if name == "spot_aware_v2":
        # v2 = tier-restricted, no-fallback variant of spot_aware. Locked
        # spec: design/spot_aware_v2_tier_restricted.md. Drops tier 50-70%
        # explicitly, requires a real priors-table hit (no p_win=0.54
        # fallback), and re-enforces delta_min/max + EV gate. Same env-var
        # overrides as v1 but ignores SPOT_AWARE_AGGRESSIVE_MODE (v2 cannot
        # be put into aggressive bypass mode).
        if _env_bool("SPOT_AWARE_AGGRESSIVE_MODE", False):
            LOG.warning(
                "STRATEGY=spot_aware_v2 IGNORES SPOT_AWARE_AGGRESSIVE_MODE=1; "
                "v2 has no aggressive bypass. Unset the flag to silence this warning."
            )
        v2_kwargs: dict[str, float] = {}
        d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
        if d_min is not None:
            v2_kwargs["delta_min_bps"] = d_min
        d_max = _env_float("SPOT_AWARE_DELTA_MAX_BPS", None)
        if d_max is not None:
            v2_kwargs["delta_max_bps"] = d_max
        ev_min = _env_float("SPOT_AWARE_EV_MIN_DOLLARS", None)
        if ev_min is not None:
            v2_kwargs["ev_min_dollars_per_share"] = ev_min
        limit_buf = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
        if limit_buf is not None:
            v2_kwargs["limit_buffer_usd"] = limit_buf
        # ORACLE_GAP_MIN_BPS — audit 2026-05-10 found aligned spot-vs-
        # oracle gap >= 1 bps gives 62.5% WR vs 49.7% baseline. Default
        # 0 = filter disabled (kill-switch); set to e.g. 1.0 to enable.
        oracle_gap = _env_float("ORACLE_GAP_MIN_BPS", None)
        if oracle_gap is not None and oracle_gap > 0:
            v2_kwargs["oracle_gap_min_bps"] = oracle_gap
        if v2_kwargs:
            LOG.warning("spot_aware_v2 overrides: %s", v2_kwargs)
        return SpotAwareStrategyV2(priors=load_priors(), **v2_kwargs)
    if name == "spot_aware_v3":
        # v3 = v2 + regime-detector gate. Locked spec:
        # design/regime_detector.md. Validation evidence at
        # runbooks/gate-evidence/regime-classifier-validation.txt
        # (2026-05-10): trending bucket WR 70.59% vs chop 47.40%
        # (+23.19pp); per-trade pnl +$1.75 trending vs -$0.22 chop.
        # Same env overrides as v2 plus REGIME_TRENDING_THRESHOLD,
        # REGIME_CHOP_THRESHOLD, REGIME_WINDOW_5M_S, REGIME_WINDOW_10M_S
        # for tuning. v3 fires much less frequently than v2 (~6% of
        # windows qualify as trending) but each fire is much more
        # likely to win.
        from polymarket_bot.strategies.regime_detector import (
            DEFAULT_CHOP_THRESHOLD,
            DEFAULT_TRENDING_THRESHOLD,
            DEFAULT_WINDOW_5M_S,
            DEFAULT_WINDOW_10M_S,
        )
        from polymarket_bot.strategies.spot_aware_v3 import SpotAwareStrategyV3

        v3_kwargs: dict[str, float] = {}
        d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
        if d_min is not None:
            v3_kwargs["delta_min_bps"] = d_min
        d_max = _env_float("SPOT_AWARE_DELTA_MAX_BPS", None)
        if d_max is not None:
            v3_kwargs["delta_max_bps"] = d_max
        ev_min = _env_float("SPOT_AWARE_EV_MIN_DOLLARS", None)
        if ev_min is not None:
            v3_kwargs["ev_min_dollars_per_share"] = ev_min
        limit_buf = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
        if limit_buf is not None:
            v3_kwargs["limit_buffer_usd"] = limit_buf
        trending_th = _env_float("REGIME_TRENDING_THRESHOLD", DEFAULT_TRENDING_THRESHOLD)
        chop_th = _env_float("REGIME_CHOP_THRESHOLD", DEFAULT_CHOP_THRESHOLD)
        win_5m_raw = _env_float("REGIME_WINDOW_5M_S", float(DEFAULT_WINDOW_5M_S))
        win_10m_raw = _env_float("REGIME_WINDOW_10M_S", float(DEFAULT_WINDOW_10M_S))
        win_5m = int(win_5m_raw if win_5m_raw is not None else DEFAULT_WINDOW_5M_S)
        win_10m = int(win_10m_raw if win_10m_raw is not None else DEFAULT_WINDOW_10M_S)
        trending_th_v = trending_th if trending_th is not None else DEFAULT_TRENDING_THRESHOLD
        chop_th_v = chop_th if chop_th is not None else DEFAULT_CHOP_THRESHOLD
        regime = RegimeDetector(
            window_5m_s=win_5m,
            window_10m_s=win_10m,
            trending_threshold=trending_th_v,
            chop_threshold=chop_th_v,
        )
        if v3_kwargs:
            LOG.warning("spot_aware_v3 overrides: %s", v3_kwargs)
        LOG.info(
            "regime detector: 5m=%ss / 10m=%ss thresholds trending>%s chop<%s",
            win_5m,
            win_10m,
            trending_th_v,
            chop_th_v,
        )
        return SpotAwareStrategyV3(priors=load_priors(), regime_detector=regime, **v3_kwargs)
    if name == "ensemble":
        # Phase 5: LLM ensemble wrapping a base strategy. Per
        # design/phase-5-llm-ensemble.md. Reuses the already-built agents
        # (orderbook, oracle_gap, momentum, meta) from polymarket_bot.agents.
        # Mode selection via ENSEMBLE_MODE env var:
        #   "off"    — wrapper passes base verdict through (kill-switch)
        #   "shadow" — ensemble votes logged; base verdict still drives
        #   "gate"   — only fire when base AND meta agree
        # Base strategy via ENSEMBLE_BASE_STRATEGY env var:
        #   "spot_aware_v2" (default) — tier-restricted, priors-gated v2
        #   "wide_fire"               — fires every window with any spot
        #                               move, NO tier/priors/EV gates.
        #                               Operator-approved 2026-05-10:
        #                               max volume + LLM filters.
        from polymarket_bot.agents.anthropic_client import AnthropicAdapter
        from polymarket_bot.agents.budget import BudgetTracker
        from polymarket_bot.agents.meta import MetaDecider
        from polymarket_bot.agents.momentum import MomentumAgent
        from polymarket_bot.agents.oracle_gap import OracleGapAgent
        from polymarket_bot.agents.orderbook import OrderbookAgent
        from polymarket_bot.strategies.ensemble_wrapper import (
            EnsembleMode,
            EnsembleWrapper,
        )

        # Build the base strategy. Default = spot_aware_v2 with whatever
        # knobs operator sets via SPOT_AWARE_* env vars. Override to
        # `wide_fire` for max-volume mode where the LLM ensemble is the
        # only meaningful gate.
        base_strategy_name = (
            os.environ.get("ENSEMBLE_BASE_STRATEGY", "spot_aware_v2").strip().lower()
        )
        base: Strategy
        if base_strategy_name == "wide_fire":
            from polymarket_bot.strategies.wide_fire import WideFireStrategy

            wf_kwargs: dict[str, float] = {}
            wf_d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
            if wf_d_min is not None:
                wf_kwargs["delta_min_bps"] = wf_d_min
            wf_limit = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
            if wf_limit is not None:
                wf_kwargs["limit_buffer_usd"] = wf_limit
            LOG.warning(
                "ensemble base=wide_fire — NO tier/priors/EV gates; LLM is the only filter (%s)",
                wf_kwargs,
            )
            base = WideFireStrategy(**wf_kwargs)
        elif base_strategy_name == "spot_aware_v2":
            base_kwargs: dict[str, float] = {}
            d_min = _env_float("SPOT_AWARE_DELTA_MIN_BPS", None)
            if d_min is not None:
                base_kwargs["delta_min_bps"] = d_min
            d_max = _env_float("SPOT_AWARE_DELTA_MAX_BPS", None)
            if d_max is not None:
                base_kwargs["delta_max_bps"] = d_max
            ev_min = _env_float("SPOT_AWARE_EV_MIN_DOLLARS", None)
            if ev_min is not None:
                base_kwargs["ev_min_dollars_per_share"] = ev_min
            limit_buf = _env_float("SPOT_AWARE_LIMIT_BUFFER_USD", None)
            if limit_buf is not None:
                base_kwargs["limit_buffer_usd"] = limit_buf
            oracle_gap = _env_float("ORACLE_GAP_MIN_BPS", None)
            if oracle_gap is not None and oracle_gap > 0:
                base_kwargs["oracle_gap_min_bps"] = oracle_gap
            base = SpotAwareStrategyV2(priors=load_priors(), **base_kwargs)
        else:
            raise ValueError(
                f"ENSEMBLE_BASE_STRATEGY must be 'spot_aware_v2' or 'wide_fire'; "
                f"got {base_strategy_name!r}"
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        mode_raw = os.environ.get("ENSEMBLE_MODE", "off").strip().lower()
        if mode_raw not in ("off", "shadow", "gate"):
            raise ValueError(f"ENSEMBLE_MODE must be off|shadow|gate; got {mode_raw!r}")
        mode: EnsembleMode = mode_raw  # type: ignore[assignment]
        if mode != "off" and not api_key:
            LOG.warning(
                "ENSEMBLE_MODE=%s requires ANTHROPIC_API_KEY; falling back to off",
                mode,
            )
            mode = "off"
        # BudgetTracker hard cap: $5/day default; operator overrides via
        # ANTHROPIC_DAILY_BUDGET_USD. Beyond cap → adapter returns None
        # and the wrapper falls through to base verdict + alert.
        daily_budget = _env_float("ANTHROPIC_DAILY_BUDGET_USD", 5.0) or 5.0
        budget = BudgetTracker(hard_limit_usd=daily_budget)
        # Phase 14: optional tier blocklist. Default behavior unchanged
        # (env unset OR TIER_GATE_ENABLED=false → empty blocklist → no
        # filtering). When enabled, comma-separated tier labels are
        # validated by EnsembleWrapper against the canonical PRICE_TIER_
        # BUCKETS set at startup; unknown labels raise ValueError.
        tier_gate_enabled = _env_bool("TIER_GATE_ENABLED", False)
        tier_blocklist_raw = os.environ.get("TIER_GATE_BLOCKLIST", "").strip()
        tier_blocklist: tuple[str, ...] = ()
        if tier_gate_enabled and tier_blocklist_raw:
            tier_blocklist = tuple(
                label.strip() for label in tier_blocklist_raw.split(",") if label.strip()
            )
            LOG.warning(
                "TIER_GATE_ENABLED=true with blocklist=%s — refused fires "
                "will emit kind=tier_abstained to state/ensemble/<date>.jsonl",
                tier_blocklist,
            )
        elif tier_gate_enabled:
            LOG.info("TIER_GATE_ENABLED=true but blocklist empty; gate is a no-op")
        # Phase 15: optional regime classifier gate. Same dark-ship
        # pattern as tier gate: defaults to false/empty so the live
        # wrapper has zero-overhead pass-through. When enabled, the
        # wrapper instantiates a separate RegimeDetector (NOT shared with
        # spot_aware_v3 — strategies are runtime-exclusive, but the
        # detector is logically per-strategy state) and consults
        # abstain_regimes on every candidate. Validation against the
        # canonical regime labels happens inside EnsembleWrapper
        # (mirrors tier gate); unknown labels raise at startup.
        regime_gate_enabled = _env_bool("REGIME_GATE_ENABLED", False)
        regime_abstain_raw = os.environ.get("REGIME_GATE_ABSTAIN_REGIMES", "").strip()
        regime_abstain: tuple[str, ...] = ()
        regime_detector: RegimeDetector | None = None
        if regime_gate_enabled:
            regime_detector = RegimeDetector()
            if regime_abstain_raw:
                regime_abstain = tuple(
                    label.strip() for label in regime_abstain_raw.split(",") if label.strip()
                )
                LOG.warning(
                    "REGIME_GATE_ENABLED=true with abstain_regimes=%s — refused "
                    "fires will emit kind=regime_abstained to state/ensemble/<date>.jsonl",
                    regime_abstain,
                )
            else:
                LOG.info(
                    "REGIME_GATE_ENABLED=true but abstain_regimes empty; "
                    "detector observes spot ticks but gate is a no-op"
                )
        # Phase 16.B.4 — every-window router env wiring. Defaults OFF;
        # when EVERY_WINDOW_MODE=true the router takes over the wrapper's
        # FIRE/ABSTAIN dispatch (design/phase-16b-every-window-mode.md
        # §4). Build the Router unconditionally so SHADOW mode can use
        # it for 24h audit even when MASTER is off.
        every_window_mode = _env_bool("EVERY_WINDOW_MODE", False)
        every_window_shadow = _env_bool("EVERY_WINDOW_SHADOW", False)
        router = _build_router_from_env() if (every_window_mode or every_window_shadow) else None
        router_log_root: Path | None = None
        if router is not None:
            router_log_root = Path(os.environ.get("PMB_DASH_STATE_DIR", "state")) / "router"
            LOG.warning(
                "EVERY_WINDOW_MODE=%s SHADOW=%s — router=%s log_root=%s",
                every_window_mode,
                every_window_shadow,
                "WIRED" if router is not None else "OFF",
                router_log_root,
            )

        if mode != "off":
            adapter = AnthropicAdapter(budget=budget, api_key=api_key)
            specialists = [
                OrderbookAgent(adapter),
                OracleGapAgent(adapter),
                MomentumAgent(adapter),
            ]
            meta = MetaDecider(adapter)
            log_root = Path(os.environ.get("PMB_DASH_STATE_DIR", "state")) / "ensemble"
            LOG.info(
                "ensemble ENABLED mode=%s daily_budget=$%.2f log_root=%s",
                mode,
                daily_budget,
                log_root,
            )
            return EnsembleWrapper(
                base=base,
                specialists=specialists,
                meta=meta,
                mode=mode,
                log_root=log_root,
                tier_blocklist=tier_blocklist,
                regime_detector=regime_detector,
                abstain_regimes=regime_abstain,
                router=router,
                every_window_mode=every_window_mode,
                every_window_shadow=every_window_shadow,
                router_log_root=router_log_root,
            )
        if tier_blocklist:
            LOG.warning(
                "TIER_GATE_BLOCKLIST=%s ignored — ENSEMBLE_MODE=off bypasses "
                "the wrapper entirely. Set ENSEMBLE_MODE=shadow|gate to enable.",
                tier_blocklist,
            )
        if regime_abstain:
            LOG.warning(
                "REGIME_GATE_ABSTAIN_REGIMES=%s ignored — ENSEMBLE_MODE=off "
                "bypasses the wrapper entirely. Set ENSEMBLE_MODE=shadow|gate to enable.",
                regime_abstain,
            )
        LOG.info("STRATEGY=ensemble but ENSEMBLE_MODE=off; running base only")
        return base
    raise ValueError(
        f"unknown STRATEGY env value {name!r}; "
        "pick deterministic | spot_aware | spot_aware_v2 | spot_aware_v3 | ensemble"
    )


def _build_alert_sink() -> AlertSink:
    redis_url = os.environ.get("REDIS_URL")
    if not redis_url:
        LOG.info("REDIS_URL not set; using NullAlertSink (alerts dropped)")
        return NullAlertSink()
    LOG.info("RedisAlertSink wired to %s", redis_url)
    return RedisAlertSink(url=redis_url, source="bot-staging")


async def main() -> int:
    _configure_logging()
    LOG.info("paper-mode runtime starting")

    if _sentinel_present(str(HALT_SENTINEL_PATH)):
        LOG.critical(
            "halt sentinel %s present at startup; refusing to run. "
            "Remove it manually before restarting bot-staging.",
            HALT_SENTINEL_PATH,
        )
        return 1

    alert_sink = _build_alert_sink()

    gamma = GammaClient()
    side_index = TokenSideIndex(
        fetch_fn=gamma.fetch_event,
        cache_path=Path("state/token_side_index.json"),
    )
    # Initial warm so the very first BookUpdate has a side mapping ready.
    current = active_window_ts(int(time.time()))
    initial_windows = [current + i * WINDOW_SECONDS for i in range(WARM_LOOKAHEAD_WINDOWS + 1)]
    n = await side_index.warm(initial_windows)
    LOG.info(
        "initial warm: %d new windows; %d tokens mapped overall",
        n,
        side_index.n_known_tokens,
    )

    feeds = _default_feeds()
    strategy = _build_strategy(os.environ.get("STRATEGY", DEFAULT_STRATEGY_NAME))
    LOG.info("active strategy: %s", strategy.name)
    decision_log = DecisionLog(root="state/decisions")

    # Instant-settle: optional Polymarket Gamma poll at T+300+1s before
    # falling back to the local Chainlink-derived resolution. Per
    # design/instant_settlement.md. Disabled by default (legacy behavior);
    # set INSTANT_SETTLE_ENABLED=1 in .envrc to enable. Reduces settle
    # latency from ~60s to ~1-3s. Owns its own httpx.Client so the runner
    # doesn't share the polymarket-feed client.
    import httpx as _httpx

    # Defaults tracked from the runner module so a bump there propagates
    # without an extra edit here.
    from polymarket_bot._paper.runner import (
        DEFAULT_INSTANT_SETTLE_INTERVAL_S as _DEF_GAMMA_INTERVAL,
    )
    from polymarket_bot._paper.runner import (
        DEFAULT_INSTANT_SETTLE_TIMEOUT_S as _DEF_GAMMA_TIMEOUT,
    )
    from polymarket_bot._paper.runner import (
        DEFAULT_POST_HOC_RETRY_INITIAL_DELAY_S as _DEF_POSTHOC_DELAY,
    )
    from polymarket_bot._paper.runner import (
        DEFAULT_POST_HOC_RETRY_INTERVAL_S as _DEF_POSTHOC_INTERVAL,
    )
    from polymarket_bot._paper.runner import (
        DEFAULT_POST_HOC_RETRY_MAX_ATTEMPTS as _DEF_POSTHOC_ATTEMPTS,
    )

    instant_settle_enabled = _env_bool("INSTANT_SETTLE_ENABLED", False)
    instant_settle_timeout_s = (
        _env_float("INSTANT_SETTLE_GAMMA_TIMEOUT_S", _DEF_GAMMA_TIMEOUT) or _DEF_GAMMA_TIMEOUT
    )
    instant_settle_interval_s = (
        _env_float("INSTANT_SETTLE_GAMMA_POLL_INTERVAL_S", _DEF_GAMMA_INTERVAL)
        or _DEF_GAMMA_INTERVAL
    )
    # Orphan-fire recovery — at startup, scan recent decision-log files
    # for fired records that were never settled (e.g., bot was restarted
    # mid-window before its close-side settle ran) and post-hoc resolve
    # them via Polymarket Gamma. Default ON (kill-switch via env). Shares
    # the same httpx.Client as instant-settle.
    orphan_recovery_enabled = _env_bool("ORPHAN_RECOVERY_ENABLED", True)
    # Periodic orphan-recovery sweep — runs orphan_recovery on a timer
    # (default every 5 min, env override PERIODIC_ORPHAN_RECOVERY_INTERVAL_S).
    # Catches windows that were unresolvable at startup-time but have
    # since become resolvable. Audit 2026-05-10: window 1778428800 was
    # permanently orphaned because the bot was restarted mid-settle and
    # gamma was still pending at the new bot's startup. Default ON;
    # kill-switch via PERIODIC_ORPHAN_RECOVERY_ENABLED=0.
    periodic_orphan_recovery_enabled = _env_bool("PERIODIC_ORPHAN_RECOVERY_ENABLED", True)
    periodic_orphan_recovery_interval_s = (
        _env_float("PERIODIC_ORPHAN_RECOVERY_INTERVAL_S", 300.0) or 300.0
    )
    # Post-hoc gamma re-resolution: when the instant-settle path falls
    # through to chainlink-local, schedule a delayed gamma retry so a
    # later-resolving Polymarket truth can correct the chainlink answer.
    # Default ON; kill-switch is POST_HOC_GAMMA_RETRY_ENABLED=0. Per the
    # 2026-05-10 audit (chainlink-local disagrees with gamma on ~33% of
    # windows). Tunables let the operator dial frequency without a deploy.
    post_hoc_retry_enabled = _env_bool("POST_HOC_GAMMA_RETRY_ENABLED", True)
    post_hoc_retry_initial_delay_s = (
        _env_float("POST_HOC_GAMMA_RETRY_INITIAL_DELAY_S", _DEF_POSTHOC_DELAY) or _DEF_POSTHOC_DELAY
    )
    post_hoc_retry_interval_s = (
        _env_float("POST_HOC_GAMMA_RETRY_INTERVAL_S", _DEF_POSTHOC_INTERVAL)
        or _DEF_POSTHOC_INTERVAL
    )
    post_hoc_retry_max_attempts = int(
        _env_float("POST_HOC_GAMMA_RETRY_MAX_ATTEMPTS", float(_DEF_POSTHOC_ATTEMPTS))
        or _DEF_POSTHOC_ATTEMPTS
    )
    needs_gamma_client = instant_settle_enabled or orphan_recovery_enabled or post_hoc_retry_enabled
    gamma_client_for_settle = _httpx.Client() if needs_gamma_client else None
    if instant_settle_enabled:
        LOG.info(
            "instant-settle ENABLED: gamma poll timeout=%ss interval=%ss",
            instant_settle_timeout_s,
            instant_settle_interval_s,
        )
    if orphan_recovery_enabled:
        LOG.info("orphan-fire recovery ENABLED at startup")
    if periodic_orphan_recovery_enabled:
        LOG.info(
            "periodic orphan-recovery ENABLED: interval=%ss",
            periodic_orphan_recovery_interval_s,
        )
    if post_hoc_retry_enabled:
        LOG.info(
            "post-hoc gamma retry ENABLED: initial_delay=%ss interval=%ss max_attempts=%d",
            post_hoc_retry_initial_delay_s,
            post_hoc_retry_interval_s,
            post_hoc_retry_max_attempts,
        )

    runner = PaperRunner(
        feeds=feeds,
        strategy=strategy,
        side_resolver=side_index,
        shadow_book=ShadowBook(),
        decision_log=decision_log,
        alert_sink=alert_sink,
        instant_settle_enabled=instant_settle_enabled,
        gamma_client=gamma_client_for_settle,
        instant_settle_timeout_s=instant_settle_timeout_s,
        instant_settle_interval_s=instant_settle_interval_s,
        orphan_recovery_enabled=orphan_recovery_enabled,
        post_hoc_gamma_retry_enabled=post_hoc_retry_enabled,
        post_hoc_retry_initial_delay_s=post_hoc_retry_initial_delay_s,
        post_hoc_retry_interval_s=post_hoc_retry_interval_s,
        post_hoc_retry_max_attempts=post_hoc_retry_max_attempts,
        periodic_orphan_recovery_enabled=periodic_orphan_recovery_enabled,
        periodic_orphan_recovery_interval_s=periodic_orphan_recovery_interval_s,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    warmer_task = asyncio.create_task(_warmer(side_index, stop=stop_event), name="warmer")
    runner_task = asyncio.create_task(runner.run(stop=stop_event), name="paper-runner")
    halt_task = asyncio.create_task(_halt_watcher(stop_event), name="halt-watcher")

    LOG.info("paper-mode runtime up; waiting for SIGTERM/SIGINT or halt sentinel")
    try:
        await stop_event.wait()
        LOG.info("shutdown signal received")
        runner.stop()
        await asyncio.gather(runner_task, warmer_task, halt_task, return_exceptions=True)
    finally:
        # Always close the gamma httpx.Client to avoid FD leaks across
        # restarts -- audit 2026-05-10 found this as a CRITICAL deploy-blocker.
        if gamma_client_for_settle is not None:
            with contextlib.suppress(Exception):
                gamma_client_for_settle.close()
        alert_sink.close()
    LOG.info("shutdown complete; dropped_records=%d", runner.dropped_records_total)
    return 0


def cli() -> None:
    sys.exit(asyncio.run(main()))


if __name__ == "__main__":
    cli()
