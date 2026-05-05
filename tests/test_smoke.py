"""Smoke test — confirms the package imports and the test runner is wired.

Phase 0 placeholder. Phase 2 onward replaces this file with real test modules
under tests/feeds/, tests/agents/, tests/kill_switches/, etc.
"""

from __future__ import annotations


def test_package_imports() -> None:
    """Confirm polymarket_bot is importable from the configured src layout."""
    import polymarket_bot

    assert polymarket_bot.__doc__ is not None
    assert len(polymarket_bot.__doc__) >= 80
