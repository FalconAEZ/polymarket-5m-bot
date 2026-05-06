"""Pure-function helpers — window arithmetic + Polymarket BTC up/down resolution.

Lives outside both _live and _paper layers so paper-mode replays in Phase 4
can import the same functions production uses. Two distinct resolution
functions are deliberate: hypothetical_now() answers "if this market closed
this instant, which side wins?" — used by the Phase-3 strategy as a
ground-truth signal at every spot tick. actual_resolution() is the real,
end-of-window calculation Polymarket itself performs against the Chainlink
oracle snapshot at T+300. Both must exist, named distinctly, so callers
cannot mistake one for the other.
"""

from __future__ import annotations

from typing import Literal

WINDOW_SECONDS = 300

Side = Literal["UP", "DOWN"]


def active_window_ts(now_utc_s: int) -> int:
    """Floor a unix-second timestamp to the start of its 5m Polymarket window.

    Pinned by MASTERPLAN.md line 27. Used by the Polymarket feed to compute
    the active slug at every boundary, by Phase-3 backtests to bucket
    captured ticks into windows, and by Phase-6 risk checks to identify
    "the current window" without consulting any server.
    """
    return now_utc_s - (now_utc_s % WINDOW_SECONDS)


def active_slug(window_ts: int) -> str:
    """Build the canonical Polymarket BTC 5m slug for a given window.

    Verified against live Gamma 2026-05-07: pattern is `btc-updown-5m-<ts>`,
    one event per window, market opens at window_ts and closes at
    window_ts + 300 per the event payload's startDate / endDate.
    """
    return f"btc-updown-5m-{window_ts}"


def hypothetical_now(window_open_oracle: float, current_oracle: float) -> Side:
    """Which side wins if this market closed *right now* against the live oracle.

    Polymarket convention is ties resolve UP. We follow that. This function
    is used as a per-tick ground-truth signal in Phase 3 — the strategy
    evaluates spot-vs-window-open-oracle and compares the implied direction
    against the current Polymarket book, betting on the gap when it diverges.
    """
    return "UP" if current_oracle >= window_open_oracle else "DOWN"


def actual_resolution(
    window_ts: int,
    oracle_at_window_open: float,
    oracle_at_window_close: float,
) -> Side:
    """The real resolver: Chainlink snapshot at T+300 vs at T (window_ts).

    Distinct from hypothetical_now() so callers cannot confuse "right now"
    with "actually resolved". window_ts is unused in the body but is part
    of the function signature so the caller is forced to thread the
    window context through (and so the call-site reads as "resolve window
    X using these two oracle samples").
    """
    _ = window_ts  # kept in signature for caller-side clarity (rule #5 docstring above)
    return "UP" if oracle_at_window_close >= oracle_at_window_open else "DOWN"
