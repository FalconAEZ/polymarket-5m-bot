"""Feed protocol package — shared by _live and (Phase-4) _paper layers.

Lives outside both _live/ and _paper/ so import-linter contracts allow either
layer to depend on the protocol without cross-layer leakage. Concrete feed
implementations live under polymarket_bot._live.feeds; paper-mode replays in
Phase 4 will live under polymarket_bot._paper.feeds. See design/data_plane.md.
"""
