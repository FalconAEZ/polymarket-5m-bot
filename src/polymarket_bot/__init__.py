"""Polymarket BTC 5-Min Bot — package root.

Phased build per RUNBOOK.md. Architecture, locked decisions, and discipline
rules live in BUILD_SPEC.pdf and the project memory at
~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/. Submodules are
populated phase-by-phase: _live (production runtime), _paper (simulator),
strategies, agents, kill_switches, research, and dashboard. Production code
NEVER imports from _paper; tests inject paper mocks. See .importlinter.
"""
