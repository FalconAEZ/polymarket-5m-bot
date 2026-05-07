"""Tests for polymarket_bot.dashboard.agents_loader."""

from __future__ import annotations

from pathlib import Path

from polymarket_bot.dashboard.agents_loader import load_transcript

SYNTHETIC_AB = """\
Discovering windows...
Found 28 unique 5m windows.

=== Pass: deterministic@0.6pp ===
  elapsed: 21.26s
  n_windows: 28
  n_fired: 0
  n_filled: 0
  n_won: 0
  win_rate: 0.0
  total_pnl_usd: 0.0
  avg_pnl_usd_per_filled: 0.0

=== Pass: ensemble@0.6pp(hard_cap=$30.0) ===
2026-05-07 10:20:41 INFO httpx: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
2026-05-07 10:20:42 INFO httpx: HTTP Request: POST https://api.anthropic.com/v1/messages "HTTP/1.1 200 OK"
anthropic response failed schema validation: 1 validation error for AgentVote
rationale
  String should have at most 240 characters [type=string_too_long, input_value='UP priced 0.74 with momentum and orderbook bullish despite weak oracle.', input_type=str]
  elapsed: 260.91s
  n_windows: 28
  n_fired: 26
  n_filled: 15
  n_won: 9
  win_rate: 0.6
  total_pnl_usd: -6.158
  avg_pnl_usd_per_filled: -0.4105
"""

VERDICT_TEXT = """\
# LLM A/B verdict
VERDICT: CUT
Reasoning: latency + cost gates fail per locked decision #16.
"""


def test_load_transcript_missing_returns_none(tmp_path: Path) -> None:
    assert load_transcript(tmp_path / "no.txt") is None


def test_load_transcript_extracts_two_passes(tmp_path: Path) -> None:
    p = tmp_path / "ab.txt"
    p.write_text(SYNTHETIC_AB)
    t = load_transcript(p)
    assert t is not None
    assert t.deterministic is not None
    assert t.deterministic.n_fired == 0
    assert t.deterministic.win_rate == 0.0
    assert t.deterministic.elapsed_s == 21.26
    assert t.ensemble is not None
    assert t.ensemble.n_fired == 26
    assert t.ensemble.n_filled == 15
    assert t.ensemble.n_won == 9
    assert t.ensemble.win_rate == 0.6
    assert t.ensemble.total_pnl_usd is not None
    assert abs(t.ensemble.total_pnl_usd + 6.158) < 1e-6


def test_load_transcript_counts_anthropic_calls(tmp_path: Path) -> None:
    p = tmp_path / "ab.txt"
    p.write_text(SYNTHETIC_AB)
    t = load_transcript(p)
    assert t is not None
    assert t.n_anthropic_calls == 2


def test_load_transcript_extracts_rationales(tmp_path: Path) -> None:
    p = tmp_path / "ab.txt"
    p.write_text(SYNTHETIC_AB)
    t = load_transcript(p)
    assert t is not None
    assert len(t.sample_rationales) == 1
    assert "UP priced 0.74" in t.sample_rationales[0]


def test_load_transcript_reads_verdict(tmp_path: Path) -> None:
    p = tmp_path / "ab.txt"
    p.write_text(SYNTHETIC_AB)
    v = tmp_path / "verdict.md"
    v.write_text(VERDICT_TEXT)
    t = load_transcript(p, verdict_path=v)
    assert t is not None
    assert t.verdict == "CUT"


def test_load_transcript_no_verdict_path(tmp_path: Path) -> None:
    p = tmp_path / "ab.txt"
    p.write_text(SYNTHETIC_AB)
    t = load_transcript(p)
    assert t is not None
    assert t.verdict is None


def test_load_transcript_against_real_evidence_file() -> None:
    """Smoke test against the actual Phase 3 evidence file in this repo."""
    repo_root = Path(__file__).resolve().parents[2]
    ab = repo_root / "runbooks" / "gate-evidence" / "phase-3.3-llm-ab.txt"
    if not ab.exists():
        # tolerable on a fresh checkout that hasn't run Phase 3 yet
        return
    t = load_transcript(ab)
    assert t is not None
    # The real file has both passes; assert non-None summaries exist.
    assert t.deterministic is not None or t.ensemble is not None
