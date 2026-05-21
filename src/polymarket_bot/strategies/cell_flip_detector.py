"""CellFlipDetector — abstain when a per-cell rolling WR drops below break-even.

Phase T Improvement #2 per design/phase-T-cell-flip-detector.md. The Phase N
forensic identified the SURV cell (tier 30-50% x |Δbps|>=5) flipping from
60.7% WR pre-peak to 46.5% WR post-peak as the dominant driver of the
-$1,562 peak-to-floor swing. A static blocklist cannot catch this — the
cell was profitable before the flip. Only rolling-WR-with-abstain catches
a mid-flight regime shift on a previously-winning cell.

This module ships the pure-logic detector. The per-cell rolling-fires
state is owned by the strategy (see SpotAwareStrategyV2_1.cell_flip_*),
not the runner — a deviation from the design doc's runner-owned plan but
chosen for minimum-surface implementation. Cross-restart persistence is
NOT shipped here (history resets on restart; first ~min_samples fires
per cell after restart are pass-through). Adding persistence is queued
as a Part C follow-up.

Cell-key formula: f"{tier}|{'hi' if abs(d_bps) >= 5 else 'lo'}".
Matches the audit's bucket granularity exactly. Side-agnostic; per-side
buckets would split n too thin for rolling-20 at this scale.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(slots=True)
class CellFlipDetector:
    """Stateless detector. Given recent fires for a cell + the current
    fill price, decide whether the cell should abstain because rolling
    WR has dropped below break-even by more than a tolerance.

    Break-even for a binary 0/1 settlement at fill_price p is exactly p:
    a fire wins +(1-p) and loses -p, expected = WR*(1-p) - (1-WR)*p =
    WR - p. So EV > 0 iff WR > p. The detector abstains when rolling_wr
    < (break_even - abstain_threshold_pp/100), giving a margin for noise.
    """

    window_size: int = 20
    abstain_threshold_pp: float = 5.0
    min_samples: int = 10

    def __post_init__(self) -> None:
        if self.window_size < 1:
            raise ValueError(f"window_size must be >= 1; got {self.window_size}")
        if not 0.0 <= self.abstain_threshold_pp <= 100.0:
            raise ValueError(
                f"abstain_threshold_pp must be in [0, 100]; got {self.abstain_threshold_pp}"
            )
        if self.min_samples < 1:
            raise ValueError(f"min_samples must be >= 1; got {self.min_samples}")
        if self.min_samples > self.window_size:
            raise ValueError(
                f"min_samples ({self.min_samples}) > window_size ({self.window_size}) "
                f"is contradictory; min_samples must be <= window_size"
            )

    def should_abstain(
        self,
        *,
        fill_price: float,
        recent_wins: Sequence[bool],
    ) -> tuple[bool, str]:
        """Return (abstain, reason). Reason is empty when not abstaining
        (caller logs it into the rationale string when abstain=True)."""
        n = len(recent_wins)
        if n < self.min_samples:
            return (False, "")
        # Only the most-recent window_size fires count; older fires fall
        # out of the rolling window. Convert to list first because deque
        # (which CellFireHistory returns) doesn't support slice indexing.
        as_list = list(recent_wins)
        window = as_list[-self.window_size :] if n >= self.window_size else as_list
        rolling_wr = sum(1 for w in window if w) / len(window)
        break_even = fill_price
        threshold = break_even - self.abstain_threshold_pp / 100.0
        if rolling_wr < threshold:
            return (
                True,
                f"cell_flip:rolling_wr={rolling_wr:.3f}<be={break_even:.3f}"
                f"-{self.abstain_threshold_pp:.0f}pp(n={len(window)})",
            )
        return (False, "")


@dataclass(slots=True)
class CellFireHistory:
    """In-memory per-cell rolling fire-outcome history.

    Owned by the strategy (not the runner per design-doc deviation). Each
    cell-key maps to a bounded deque of bools (True = won, False = lost).
    `apply_settle` appends; `recent_wins` reads. `pop_pending` looks up
    + removes the pending (window_ts, asset_id) -> cell_key registration
    so a settled fire can credit the right cell.

    Persistence: NOT IMPLEMENTED. History resets on restart. The first
    `min_samples` fires per cell after each restart are pass-through (no
    abstain). Cross-restart replay is queued as Part C — see the design
    doc §4 "Persistence — Phase T scope".

    Thread-safety: strategy runs single-threaded on the asyncio main loop;
    apply_settle is called from awaited settle background tasks but never
    concurrently with strategy fires. No locking required.
    """

    max_history_size: int = 100
    _history: dict[str, deque[bool]] = field(default_factory=dict)
    _pending: dict[tuple[int, str], str] = field(default_factory=dict)

    def register_pending(self, *, window_ts: int, asset_id: str, cell_key: str) -> None:
        """Record that a fire was placed for (window_ts, asset_id) on cell_key.
        Called by the strategy at fire time. The pending entry is consumed
        when the settle arrives via `pop_pending`."""
        self._pending[(window_ts, asset_id)] = cell_key

    def pop_pending(self, *, window_ts: int, asset_id: str) -> str | None:
        """Look up + remove the pending cell_key for (window_ts, asset_id).
        Returns None if no fire was registered (e.g. the fire was abstained
        post-registration or the bot restarted between fire and settle)."""
        return self._pending.pop((window_ts, asset_id), None)

    def apply_settle(self, *, cell_key: str, won: bool) -> None:
        """Append the outcome to the cell's rolling history. Bounded by
        max_history_size — oldest entries fall off."""
        bucket = self._history.get(cell_key)
        if bucket is None:
            bucket = deque(maxlen=self.max_history_size)
            self._history[cell_key] = bucket
        bucket.append(won)

    def recent_wins(self, cell_key: str) -> Sequence[bool]:
        """Read the rolling history for a cell. Returns the underlying
        deque if present (callers MUST treat as read-only and not mutate),
        or an empty tuple if no fires recorded."""
        bucket = self._history.get(cell_key)
        if bucket is None:
            return ()
        return bucket

    @staticmethod
    def cell_key_for(tier: str, abs_d_bps: float, *, hi_threshold: float = 5.0) -> str:
        """Compute the canonical cell-key from a tier label + |Δbps| value.
        Centralized so the strategy + tests + future per-cell tooling
        agree on the bucketing rule."""
        bucket = "hi" if abs_d_bps >= hi_threshold else "lo"
        return f"{tier}|{bucket}"
