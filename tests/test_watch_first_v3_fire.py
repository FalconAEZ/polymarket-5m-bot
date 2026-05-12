"""Tests for scripts/watch_first_v3_fire.py.

Covers: log scanning, since-filter, sentinel idempotency, timeout path,
Telegram-send shape, dry-run flow. All time + HTTP injected as callables
so tests are sync and instant.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import watch_first_v3_fire as wf  # noqa: E402


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")


def _fired(decision_id: str, ts_ns: int, *, strategy: str = "spot_aware_v3") -> dict[str, object]:
    return {
        "kind": "fired",
        "decision_id": decision_id,
        "decision_ts_ns": ts_ns,
        "side": "UP",
        "size_usd": 5.0,
        "price_limit": 0.42,
        "rationale": f"strategy={strategy} delta_bps=+1.0 ttl=30s",
        "fill": None,
    }


# ---------------------------------------------------------------------------
# find_first_v3_fire
# ---------------------------------------------------------------------------


def test_no_files_returns_none(tmp_path: Path) -> None:
    assert wf.find_first_v3_fire(tmp_path, since_ts_ns=0) is None


def test_no_v3_fires_returns_none(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [_fired("a", 1_700_000_000_000_000_000, strategy="wide_fire")],
    )
    assert wf.find_first_v3_fire(tmp_path, since_ts_ns=0) is None


def test_v3_fire_before_since_is_ignored(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [_fired("old", 1_000_000_000_000_000_000)],
    )
    assert wf.find_first_v3_fire(tmp_path, since_ts_ns=2_000_000_000_000_000_000) is None


def test_v3_fire_at_or_after_since_returns_record(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [_fired("new", 2_000_000_000_000_000_000)],
    )
    rec = wf.find_first_v3_fire(tmp_path, since_ts_ns=2_000_000_000_000_000_000)
    assert rec is not None
    assert rec["decision_id"] == "new"


def test_skips_pre_since_returns_post_since(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [
            _fired("old_v3", 1_000_000_000_000_000_000),
            _fired("post_v3", 3_000_000_000_000_000_000),
        ],
    )
    rec = wf.find_first_v3_fire(tmp_path, since_ts_ns=2_000_000_000_000_000_000)
    assert rec is not None
    assert rec["decision_id"] == "post_v3"


def test_skips_settled_records(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [
            {
                "kind": "settled",
                "decision_id": "s",
                "settled_ts_ns": 3_000_000_000_000_000_000,
                "pnl_usd": 5.0,
            },
            _fired("f", 3_000_000_000_000_000_001),
        ],
    )
    rec = wf.find_first_v3_fire(tmp_path, since_ts_ns=0)
    assert rec is not None
    assert rec["decision_id"] == "f"


def test_malformed_lines_skipped(tmp_path: Path) -> None:
    path = tmp_path / "2026-05-12.jsonl"
    with path.open("w") as fh:
        fh.write("not json\n\n")
        fh.write(json.dumps(_fired("ok", 3_000_000_000_000_000_000)) + "\n")
    rec = wf.find_first_v3_fire(tmp_path, since_ts_ns=0)
    assert rec is not None
    assert rec["decision_id"] == "ok"


def test_scans_files_in_order(tmp_path: Path) -> None:
    _write_jsonl(
        tmp_path / "2026-05-12.jsonl",
        [_fired("from_05_12", 4_000_000_000_000_000_000)],
    )
    _write_jsonl(
        tmp_path / "2026-05-13.jsonl",
        [_fired("from_05_13", 5_000_000_000_000_000_000)],
    )
    rec = wf.find_first_v3_fire(tmp_path, since_ts_ns=0)
    assert rec is not None
    assert rec["decision_id"] == "from_05_12"


# ---------------------------------------------------------------------------
# send_telegram
# ---------------------------------------------------------------------------


def test_send_telegram_2xx_returns_true() -> None:
    calls: list[tuple[str, bytes]] = []

    def fake_poster(url: str, body: bytes) -> tuple[int, bytes]:
        calls.append((url, body))
        return 200, b'{"ok":true}'

    ok = wf.send_telegram("TOKEN", "12345", "hello", poster=fake_poster)
    assert ok is True
    assert len(calls) == 1
    url, body = calls[0]
    assert url == "https://api.telegram.org/botTOKEN/sendMessage"
    assert b"chat_id=12345" in body
    assert b"text=hello" in body


def test_send_telegram_4xx_returns_false() -> None:
    def fake_poster(url: str, body: bytes) -> tuple[int, bytes]:
        return 400, b'{"ok":false}'

    assert wf.send_telegram("TOKEN", "12345", "hello", poster=fake_poster) is False


# ---------------------------------------------------------------------------
# main() — full flow
# ---------------------------------------------------------------------------


def test_main_idempotent_when_sentinel_exists(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel.json"
    sentinel.write_text("{}")
    (tmp_path / "decisions").mkdir()
    rc = wf.main(
        [
            "--decisions-dir",
            str(tmp_path / "decisions"),
            "--sentinel",
            str(sentinel),
            "--since-ts-ns",
            "0",
            "--dry-run",
        ]
    )
    assert rc == 0


def test_main_dry_run_finds_fire_immediately(tmp_path: Path, capsys) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    _write_jsonl(decisions / "2026-05-12.jsonl", [_fired("fire1", 3_000_000_000_000_000_000)])
    sentinel = tmp_path / "sentinel.json"

    times = iter([1000.0, 1001.0, 1002.0])

    rc = wf.main(
        [
            "--decisions-dir",
            str(decisions),
            "--sentinel",
            str(sentinel),
            "--since-ts-ns",
            "0",
            "--dry-run",
        ],
        now_fn=lambda: next(times),
    )
    assert rc == 0
    payload = json.loads(sentinel.read_text())
    assert payload["decision_id"] == "fire1"
    assert payload["telegram_sent"] is True  # dry-run treats it as "sent"
    out = capsys.readouterr().out
    assert "fire1" in out
    assert "Phase F" in out


def test_main_polls_then_finds(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    log = decisions / "2026-05-12.jsonl"
    log.write_text("")  # start empty
    sentinel = tmp_path / "sentinel.json"

    sleep_count = {"n": 0}

    def fake_sleep(_s: float) -> None:
        sleep_count["n"] += 1
        if sleep_count["n"] == 2:
            # On the third poll, the bot fires.
            _write_jsonl(log, [_fired("late", 3_000_000_000_000_000_000)])

    times = iter([1000.0] * 100)

    rc = wf.main(
        [
            "--decisions-dir",
            str(decisions),
            "--sentinel",
            str(sentinel),
            "--since-ts-ns",
            "0",
            "--poll-interval",
            "0.01",
            "--dry-run",
        ],
        sleep_fn=fake_sleep,
        now_fn=lambda: next(times),
    )
    assert rc == 0
    payload = json.loads(sentinel.read_text())
    assert payload["decision_id"] == "late"
    assert sleep_count["n"] >= 2


def test_main_timeout_writes_sentinel_returns_1(tmp_path: Path) -> None:
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    sentinel = tmp_path / "sentinel.json"

    # now_fn advances rapidly so the timeout fires on the second loop.
    times = iter([0.0, 0.0, 100.0, 100.0, 100.0])

    rc = wf.main(
        [
            "--decisions-dir",
            str(decisions),
            "--sentinel",
            str(sentinel),
            "--since-ts-ns",
            "0",
            "--poll-interval",
            "0.01",
            "--timeout",
            "10.0",
            "--dry-run",
        ],
        sleep_fn=lambda _s: None,
        now_fn=lambda: next(times),
    )
    assert rc == 1
    payload = json.loads(sentinel.read_text())
    assert payload["status"] == "TIMEOUT"


def test_main_missing_decisions_dir_exits_2(tmp_path: Path) -> None:
    rc = wf.main(
        [
            "--decisions-dir",
            str(tmp_path / "nope"),
            "--sentinel",
            str(tmp_path / "s.json"),
            "--since-ts-ns",
            "0",
            "--dry-run",
        ]
    )
    assert rc == 2


def test_main_missing_telegram_env_exits_2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    rc = wf.main(
        [
            "--decisions-dir",
            str(decisions),
            "--sentinel",
            str(tmp_path / "s.json"),
            "--since-ts-ns",
            "0",
        ]
    )
    assert rc == 2


# ---------------------------------------------------------------------------
# format_message
# ---------------------------------------------------------------------------


def test_format_message_includes_key_fields() -> None:
    rec = _fired("d123", 1_778_596_023_000_000_000)
    msg = wf.format_message(rec, elapsed_s=3700.0)
    assert "d123" in msg
    assert "spot_aware_v3" in msg
    assert "Phase F" in msg
    assert "1h01m" in msg  # elapsed format
