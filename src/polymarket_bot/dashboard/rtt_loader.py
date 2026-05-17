"""Reader for state/provider_rtt.jsonl — VPS-side RTT samples.

The dashboard calls load_provider_rtt(state_dir) once per refresh and
threads the result through the components.provider_rtt_panel renderer.
Pure read; no Streamlit or httpx imports. Per design/dashboard-v2.md §10.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RttSample:
    provider: str
    ts_utc: datetime
    rtt_ms: float | None
    status_code: int | None


def load_provider_rtt(
    state_dir: Path | str,
    *,
    max_per_provider: int = 6,
    lookback_s: float = 600.0,
    max_bytes: int = 256 * 1024,
) -> dict[str, list[RttSample]]:
    """Reads tail of state/provider_rtt.jsonl and returns up to
    max_per_provider samples per provider, oldest-first. Filters samples
    older than lookback_s. Reads at most the trailing max_bytes of the
    file so the I/O stays bounded for long-lived collectors.
    """
    path = Path(state_dir) / "provider_rtt.jsonl"
    if not path.exists():
        return {}
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                _ = fh.readline()  # discard partial first line
            data = fh.read()
    except OSError:
        return {}
    text = data.decode("utf-8", errors="replace")
    cutoff = datetime.now(tz=UTC) - timedelta(seconds=lookback_s)
    by_provider: dict[str, list[RttSample]] = defaultdict(list)
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        provider = obj.get("provider")
        ts_str = obj.get("ts_utc")
        if not isinstance(provider, str) or not isinstance(ts_str, str):
            continue
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            continue
        if ts < cutoff:
            continue
        rtt_raw = obj.get("rtt_ms")
        status_raw = obj.get("status_code")
        rtt_ms = float(rtt_raw) if isinstance(rtt_raw, int | float) else None
        status_code = int(status_raw) if isinstance(status_raw, int) else None
        by_provider[provider].append(
            RttSample(
                provider=provider,
                ts_utc=ts,
                rtt_ms=rtt_ms,
                status_code=status_code,
            )
        )
    return {p: samples[-max_per_provider:] for p, samples in by_provider.items()}
