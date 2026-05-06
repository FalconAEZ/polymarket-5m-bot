"""Internal helpers — prompt loading + the shared specialist call shape.

Not part of the public agent API. Each specialist agent
(orderbook / oracle_gap / momentum) follows the same call shape: load a
versioned prompt from prompts/<name>.md, build the user JSON from the
AgentContext, call AnthropicAdapter.parse with the AgentVote schema. The
helpers here keep that path in one place so the per-agent files stay
focused on the model + prompt selection.
"""

from __future__ import annotations

from pathlib import Path

# Project root = parent of src/. Prompts live alongside src/, not inside it.
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PROMPTS_DIR = _PROJECT_ROOT / "prompts"


def load_prompt(name: str, override: str | Path | None = None) -> str:
    """Load a prompt file from prompts/<name>.md or the override path.

    Raises FileNotFoundError if the prompt is missing — agents should fail
    fast at construction time, not silently with an empty system prompt.
    """
    path = Path(override) if override is not None else _PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"prompt file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"prompt file {path} is empty")
    return text
