"""Halt sentinel writer + reader. design/alerter.md §4.3.

The sentinel is a JSON file at state/halt.sentinel. The writer uses a
tmp+rename pattern so the file's appearance is atomic on the same FS — the
bot's supervisor reads only `os.path.exists(...)`, never the contents
(presence is the signal; corrupt JSON still halts per locked decision in
§10). The bot reader is in scripts/run_paper.py; here we only own the
producer side. Path is project-relative because both the bot and the
alerter run with `WorkingDirectory=/home/ops/polymarket-5m-bot`.
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SENTINEL_PATH = Path("state/halt.sentinel")


def write_halt_sentinel(
    reason: str,
    ts_ns: int,
    *,
    path: Path = DEFAULT_SENTINEL_PATH,
    by: str = "telegram-/halt",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "halted_at_ns": ts_ns,
        "halted_by": by,
        "reason": reason,
    }
    tmp.write_text(json.dumps(payload, separators=(",", ":")))
    tmp.replace(path)


def halt_sentinel_present(path: Path = DEFAULT_SENTINEL_PATH) -> bool:
    return path.exists()
