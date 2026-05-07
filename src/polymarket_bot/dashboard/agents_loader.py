"""Parser for the Phase 3 A/B evidence file — agent-activity dashboard panel.

Loads `runbooks/gate-evidence/phase-3.3-llm-ab.txt`, the only file we have
today that captures what the LLM ensemble did per the A/B run that fed
locked decision #16 (verdict CUT). The file is a free-form text dump
written by `scripts/run_ab.py`; this loader tolerates its loose shape and
extracts the two summary blocks (deterministic and ensemble), the
ensemble cost line, the verdict, and any pydantic schema-validation
warnings (which surface what an actual agent rationale looked like).

When PaperRunner gains live ensemble logging in Phase 8, a sibling loader
will read the extended decision-log JSONL schema directly. For v1 of the
dashboard, this historical view is the only thing to show.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PassSummary:
    """Stats for one strategy pass parsed from the A/B evidence file."""

    label: str
    elapsed_s: float | None
    n_windows: int | None
    n_fired: int | None
    n_filled: int | None
    n_won: int | None
    win_rate: float | None
    total_pnl_usd: float | None
    avg_pnl_usd_per_filled: float | None


@dataclass(frozen=True, slots=True)
class AgentTranscript:
    """All the agent-related slices we can extract from the A/B evidence."""

    source_path: Path
    deterministic: PassSummary | None
    ensemble: PassSummary | None
    sample_rationales: list[str]  # the validation-flagged actual model outputs
    n_anthropic_calls: int  # count of POST /v1/messages lines
    verdict: str | None  # KEPT | CUT, parsed from runbooks/decisions/llm-ab-result.md if available


_PASS_HEADER_RE = re.compile(r"^=== Pass:\s*(?P<label>.+?)\s+===\s*$")
_KV_RE = re.compile(r"^\s*(?P<key>\w+):\s*(?P<value>.+?)\s*$")
_ANTHROPIC_LINE_RE = re.compile(r"https://api\.anthropic\.com/v1/messages")
_RATIONALE_RE = re.compile(r"input_value='(?P<text>[^']+?)'", re.DOTALL)


def load_transcript(
    ab_path: Path | str,
    verdict_path: Path | str | None = None,
) -> AgentTranscript | None:
    """Parse the A/B evidence file. Returns None if the file is absent."""
    p = Path(ab_path)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    passes = list(_iter_passes(lines))
    deterministic = next((s for s in passes if "deterministic" in s.label), None)
    ensemble = next((s for s in passes if "ensemble" in s.label), None)
    n_calls = sum(1 for line in lines if _ANTHROPIC_LINE_RE.search(line))
    rationales = _extract_rationales(text)
    verdict = _read_verdict(verdict_path)
    return AgentTranscript(
        source_path=p,
        deterministic=deterministic,
        ensemble=ensemble,
        sample_rationales=rationales,
        n_anthropic_calls=n_calls,
        verdict=verdict,
    )


def _iter_passes(lines: Iterable[str]) -> Iterable[PassSummary]:
    """Walk lines once; emit a PassSummary at every `=== Pass: ... ===` block.

    A block is the header line followed by KV lines until the next blank
    line OR the next `===` marker. Unknown keys are ignored.
    """
    current_label: str | None = None
    kv: dict[str, str] = {}
    for raw in lines:
        m = _PASS_HEADER_RE.match(raw)
        if m is not None:
            if current_label is not None:
                yield _make_summary(current_label, kv)
            current_label = m.group("label").strip()
            kv = {}
            continue
        if current_label is None:
            continue
        if not raw.strip():
            yield _make_summary(current_label, kv)
            current_label = None
            kv = {}
            continue
        kv_match = _KV_RE.match(raw)
        if kv_match is None:
            continue
        kv[kv_match.group("key")] = kv_match.group("value")
    if current_label is not None:
        yield _make_summary(current_label, kv)


def _make_summary(label: str, kv: dict[str, str]) -> PassSummary:
    return PassSummary(
        label=label,
        elapsed_s=_parse_seconds(kv.get("elapsed")),
        n_windows=_parse_int(kv.get("n_windows")),
        n_fired=_parse_int(kv.get("n_fired")),
        n_filled=_parse_int(kv.get("n_filled")),
        n_won=_parse_int(kv.get("n_won")),
        win_rate=_parse_float(kv.get("win_rate")),
        total_pnl_usd=_parse_float(kv.get("total_pnl_usd")),
        avg_pnl_usd_per_filled=_parse_float(kv.get("avg_pnl_usd_per_filled")),
    )


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_seconds(value: str | None) -> float | None:
    """'21.26s' or '21.26' both parse to 21.26."""
    if value is None:
        return None
    cleaned = value.strip().rstrip("s").strip()
    return _parse_float(cleaned)


def _extract_rationales(text: str) -> list[str]:
    """Pull every input_value='...' string from pydantic validation lines.

    These are the actual model outputs that hit the schema-validation path
    and got flagged for being too long. They're the only verbatim agent
    speech we have today; in v1 of the dashboard they stand in for the
    full transcripts that Phase 8 will log directly.
    """
    out: list[str] = []
    for m in _RATIONALE_RE.finditer(text):
        out.append(m.group("text"))
    return out


def _read_verdict(verdict_path: Path | str | None) -> str | None:
    if verdict_path is None:
        return None
    p = Path(verdict_path)
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("VERDICT:"):
            return line.split(":", 1)[1].strip()
    return None
