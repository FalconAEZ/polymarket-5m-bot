"""Build pdfs/PHASE_P_SESSION3_MMD_SHIP.pdf — Session 3 ship deliverable.

8-10 pp: implementation summary → test inventory → pre-deploy gate
evidence → VPS deploy walkthrough → Day-0 verification → 5-day soak
plan → Phase Q decision matrix.

Usage:
    uv run --with reportlab python -u pdfs/build_phase_p_session3_pdf.py
"""

# ruff: noqa: RUF001, RUF002, E501

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pdfs" / "PHASE_P_SESSION3_MMD_SHIP.pdf"

BG = HexColor("#0a0a0a")
PANEL = HexColor("#1a1a1a")
TEXT = HexColor("#e0e0e0")
SUBTLE = HexColor("#888888")
ACCENT = HexColor("#00ff88")
WARN = HexColor("#ffaa00")
LOSS = HexColor("#ff4466")
LINE = HexColor("#444444")


def _page_template(doc):
    frame = Frame(20 * mm, 18 * mm, A4[0] - 40 * mm, A4[1] - 36 * mm, id="body", showBoundary=0)

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFillColor(SUBTLE)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            20 * mm, 10 * mm,
            "Phase P Session 3 — MMD shadow ship · 2026-05-18 · POLYMARKET 5m bot",
        )
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"page {doc.page}")
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.3)
        canvas.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
        canvas.restoreState()

    return PageTemplate(id="body", frames=[frame], onPage=draw)


def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="Helvetica-Bold",
                             fontSize=20, textColor=ACCENT, leading=24, spaceAfter=10, spaceBefore=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                             fontSize=14, textColor=ACCENT, leading=18, spaceAfter=8, spaceBefore=14),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold",
                             fontSize=11, textColor=TEXT, leading=14, spaceAfter=6, spaceBefore=10),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica",
                               fontSize=9.5, textColor=TEXT, leading=13, alignment=TA_LEFT,
                               spaceAfter=6),
        "code": ParagraphStyle("code", parent=base["BodyText"], fontName="Courier",
                               fontSize=8.5, textColor=ACCENT, leading=11, leftIndent=12),
        "warn": ParagraphStyle("warn", parent=base["BodyText"], fontName="Helvetica",
                               fontSize=10, textColor=WARN, leading=14, spaceAfter=8,
                               leftIndent=8, rightIndent=8, borderColor=WARN,
                               borderWidth=0.5, borderPadding=6),
        "ok_box": ParagraphStyle("ok_box", parent=base["BodyText"], fontName="Helvetica-Bold",
                                 fontSize=10, textColor=ACCENT, leading=14, spaceAfter=8,
                                 leftIndent=8, rightIndent=8, borderColor=ACCENT,
                                 borderWidth=0.5, borderPadding=6),
        "headline": ParagraphStyle("headline", parent=base["BodyText"], fontName="Helvetica-Bold",
                                   fontSize=11, textColor=ACCENT, leading=15, spaceAfter=10,
                                   alignment=TA_LEFT),
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName="Helvetica-Bold",
                                      fontSize=28, textColor=ACCENT, leading=34, alignment=TA_CENTER,
                                      spaceAfter=20),
        "cover_sub": ParagraphStyle("cover_sub", parent=base["BodyText"], fontName="Helvetica",
                                    fontSize=12, textColor=TEXT, leading=18, alignment=TA_CENTER,
                                    spaceAfter=10),
        "cover_ok": ParagraphStyle("cover_ok", parent=base["BodyText"], fontName="Helvetica-Bold",
                                   fontSize=14, textColor=ACCENT, leading=20, alignment=TA_CENTER,
                                   spaceAfter=12),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica",
                                fontSize=8, textColor=SUBTLE, leading=10, spaceAfter=4),
    }


def _table(rows, col_widths=None, header=True):
    t = Table(rows, colWidths=col_widths, repeatRows=1 if header else 0)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold" if header else "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT if header else TEXT),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("BACKGROUND", (0, 0), (-1, 0), PANEL if header else BG),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, LINE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    t.setStyle(TableStyle(style))
    return t


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Phase P Session 3 — MMD shadow ship",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # COVER
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Spacer(0, 30 * mm))
    story.append(Paragraph("PHASE&nbsp;P · Session&nbsp;3", s["cover_title"]))
    story.append(Paragraph("Market Mode Detector — SHADOW ship + 5-day observation window",
                           s["cover_sub"]))
    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "POLYMARKET 5-minute BTC up/down bot<br/>"
        "Module: <b>src/polymarket_bot/strategies/market_mode_detector.py</b><br/>"
        "Tests: <b>29 new (697 total green)</b><br/>"
        "Bot HEAD: <b>fd56b61</b> on <b>claude/phase-P-hard-reset</b><br/>"
        "Session 3 ship: <b>2026-05-17 22:41:25 UTC</b> · MainPID <b>1023320</b>",
        s["cover_sub"],
    ))
    story.append(Spacer(0, 16 * mm))
    story.append(Paragraph(
        "MMD live in SHADOW mode — annotates fires, never abstains",
        s["cover_ok"],
    ))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "Phase Q decision opens Day-5: promote shadow → gate, iterate params, or shelve.",
        s["small"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # TOC
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Contents", s["h1"]))
    story.append(Spacer(0, 4 * mm))
    toc_rows = [
        ["§1", "Implementation summary"],
        ["§2", "Test inventory (29 new)"],
        ["§3", "Pre-deploy gate evidence"],
        ["§4", "VPS deploy walkthrough"],
        ["§5", "Day-0 verification"],
        ["§6", "5-day observation window + Phase Q decision matrix"],
        ["§7", "Rollback procedure + failure-mode contract"],
    ]
    story.append(_table(toc_rows, col_widths=[18 * mm, 150 * mm], header=False))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Implementation summary
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§1 &nbsp;&nbsp; Implementation summary", s["h1"]))
    story.append(Paragraph("§1.1 &nbsp; What shipped", s["h2"]))
    impl = [
        ["src/polymarket_bot/strategies/market_mode_detector.py (NEW)",
         "MarketModeDetector class + MmdReading dataclass + MmdBinanceKlinePoller. ~327 LOC. Per design/P.1-market-mode-detector-integration.md."],
        ["src/polymarket_bot/strategies/spot_aware_v2_1.py (modified)",
         "Constructor gains mmd_getter / mmd_mode / mmd_labels_to_abstain. _maybe_fire annotates rationale with mmd=&lt;label&gt; mmd_conf=&lt;conf&gt;; in gate mode (and only then) abstains if label is in abstain set AND label != UNKNOWN."],
        ["scripts/run_paper.py (modified)",
         "_build_strategy reads MMD_MODE + MMD_LABELS_TO_ABSTAIN from env at construction time. main() creates MarketModeDetector + MmdBinanceKlinePoller and binds the getter when MMD_ENABLED=true."],
        ["pyproject.toml + uv.lock", "Added ta>=0.11.0 to runtime deps."],
        ["tests/strategies/test_market_mode_detector.py (NEW)", "29 tests — see §2."],
    ]
    story.append(_table([["File", "Change"]] + impl,
                        col_widths=[68 * mm, 100 * mm]))

    story.append(Paragraph("§1.2 &nbsp; Public API (the only surface bot code touches)", s["h2"]))
    story.append(Paragraph("MarketModeDetector:", s["h3"]))
    api = [
        "MarketModeDetector(lookback_min=60, adx_strong_threshold=25.0, adx_weak_threshold=20.0, bb_compressed_bps=30.0, momentum_threshold_bps=10.0)",
        "push_bar(open_, high, low, close, volume, ts_ns) → None",
        "clear_buffer() → None",
        "bar_count() → int",
        "latest(now_ns=None) → MmdReading(label, confidence, adx, bb_width_bps, momentum_bps, sampled_at_ns, bar_count)",
        "Labels: UP / DOWN / CHOPPY / MIXED / UNKNOWN. UNKNOWN is ALWAYS pass-through.",
    ]
    for line in api:
        story.append(Paragraph(f"&bull; <font face='Courier' size='8.5'>{line}</font>", s["body"]))

    story.append(Paragraph("MmdBinanceKlinePoller:", s["h3"]))
    poller = [
        "MmdBinanceKlinePoller(mmd, symbol='BTCUSDT', poll_interval_s=30.0)",
        "poll_once() → int (bars added, raises on HTTP error / malformed JSON)",
        "run(stop: asyncio.Event) → coroutine (poll loop, never raises; logs warnings on failures)",
    ]
    for line in poller:
        story.append(Paragraph(f"&bull; <font face='Courier' size='8.5'>{line}</font>", s["body"]))

    story.append(Paragraph("Strategy:", s["h3"]))
    strat_api = [
        "SpotAwareStrategyV2_1(..., mmd_getter=None, mmd_mode='shadow', mmd_labels_to_abstain=())",
        "set_mmd_getter(getter) → None  (rebinds post-construction; used by run_paper.main())",
    ]
    for line in strat_api:
        story.append(Paragraph(f"&bull; <font face='Courier' size='8.5'>{line}</font>", s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Test inventory
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§2 &nbsp;&nbsp; Test inventory — 29 new", s["h1"]))
    story.append(Paragraph("tests/strategies/test_market_mode_detector.py:", s["h3"]))
    tests = [
        ["Detector init", "init_defaults_ok / validates_lookback_min / validates_adx_thresholds / validates_positive_bps_thresholds"],
        ["Buffer", "push_bar_accumulates_to_lookback / clear_buffer_empties / unknown_when_buffer_under_30"],
        ["Labels", "up_on_synthetic_uptrend / down_on_synthetic_downtrend / choppy_on_compressed_flat / mixed_when_neither_trend_nor_chop"],
        ["Confidence", "confidence_always_in_unit_interval / latest_returns_unknown_on_classifier_exception / no_op_stub_when_ta_missing / unknown_reading_helper"],
        ["Poller", "poll_once_happy_path / poll_once_http_error_propagates / poll_once_rejects_malformed_payload / run_polls_then_stops / run_survives_a_single_poll_exception"],
        ["Strategy wire", "mmd_getter_none_path_unchanged / shadow_annotates_but_never_abstains / gate_abstains_on_configured_label / gate_fires_on_unblocked_label / gate_treats_unknown_as_passthrough / getter_exception_treated_as_unknown / init_rejects_invalid_mmd_mode / set_mmd_getter_rebinds / mmd_reading_dataclass_is_frozen"],
    ]
    story.append(_table([["Category", "Tests"]] + tests,
                        col_widths=[30 * mm, 138 * mm]))
    story.append(Paragraph(
        "Notable: the strategy-side tests use a duck-typed _FakeReading "
        "instead of importing MmdReading so the strategy ↔ MMD dependency "
        "stays one-way. The 'gate_treats_unknown_as_passthrough' test "
        "explicitly puts UNKNOWN in the abstain set and verifies the fire "
        "still happens — that's the design §6 HARD failure-mode contract.",
        s["body"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 — Pre-deploy gate evidence
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§3 &nbsp;&nbsp; Pre-deploy gate evidence — all green",
                           s["h1"]))
    gates = [
        ["pytest", "667 passed (was 638 pre-Session 3; +29 new)"],
        ["mypy --strict src/", "Success: no issues found in 84 source files"],
        ["ruff check", "All checks passed!"],
        ["import-linter", "Contracts: 3 kept, 0 broken — production never imports paper / paper never imports live runtime, health, storage, or execution / dashboard never imports live, paper-runtime, backtest-runtime, or strategies"],
        ["uv lock", "Resolved 101 packages; Added ta v0.11.0"],
        ["pre-commit hooks", "ruff + ruff-format + forbid TODO/FIXME/hack + enforce module docstrings — all PASSED on commit"],
    ]
    story.append(_table([["Gate", "Evidence"]] + gates,
                        col_widths=[40 * mm, 128 * mm]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 4 — VPS deploy walkthrough
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§4 &nbsp;&nbsp; VPS deploy walkthrough", s["h1"]))
    story.append(Paragraph("§4.1 &nbsp; Sequence (chronological, VPS UTC)", s["h2"]))
    deploy = [
        ["22:39 UTC", "git push origin claude/phase-P-hard-reset — pushed fd56b61"],
        ["22:41:05", "VPS git fetch + git pull --ff-only origin claude/phase-P-hard-reset — 6 files changed, 945 insertions(+), 1 deletion(-)"],
        ["22:41:10", "VPS .envrc backed up to .envrc.bak.phase-P-session-3-pre-mmd"],
        ["22:41:11", "Appended `export MMD_ENABLED=true` + `export MMD_MODE=shadow` to .envrc (other MMD_* defaults)"],
        ["22:41:25", "sudo systemctl restart bot-staging.service — systemd unit's `uv run` rebuilt + installed ta==0.11.0 automatically"],
        ["22:41:26", "MainPID=1023320 ActiveState=active SubState=running. Startup log shows mmd_mode=shadow / MMD ENABLED line / Binance kline poll 200 OK."],
        ["22:41:27", "bankroll_getter wired (start=$1000.00, replay=True, cap=1) — replayed to current=$790.15 (post-Session-1 drawdown preserved)"],
        ["22:42:49", "12 fires today, all pre-restart (no mmd annotation yet); next opportunity to annotate = window 1779057900 = 22:45 UTC"],
    ]
    story.append(_table([["UTC", "Action"]] + deploy,
                        col_widths=[26 * mm, 142 * mm]))

    story.append(Paragraph("§4.2 &nbsp; Startup log signature", s["h2"]))
    log_lines = [
        "spot_aware_v2_1: kelly_mult=0.15 max_bet_abs=$500 multi_fire_cap=1",
        "    tier_relax_p_win_fallback=None tier_relax_price_floor=0.420",
        "    block_up_in_tiers=('70-85%',) hour_blocklist_utc=(22, 23, 0)",
        "    hour_blocklist_tiers=('70-85%',) mmd_mode=shadow mmd_labels_to_abstain=()",
        "active strategy: spot_aware_v2_1",
        "instant-settle ENABLED: gamma poll timeout=30.0s interval=5.0s",
        "post-hoc gamma retry ENABLED: initial_delay=300.0s interval=30.0s",
        "spot_aware_v2_1: bankroll_getter wired (start=$1000.00, replay=True, cap=1)",
        "bankroll replay: starting=$1000.00 current=$790.15",
        "MMD ENABLED: lookback_min=60 poll_interval_s=30.0 adx_strong=25.0",
        "    adx_weak=20.0 bb_compressed_bps=30.0 momentum_bps=10.0",
        "warmer started; lookahead=12 windows",
        "GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60 200 OK",
    ]
    for line in log_lines:
        story.append(Paragraph(line, s["code"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Day-0 verification
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§5 &nbsp;&nbsp; Day-0 verification", s["h1"]))
    story.append(Paragraph(
        "Verification protocol for the first fires post-Session-3 ship:",
        s["body"],
    ))
    verify = [
        ["✓", "bot-staging.service ActiveState=active / SubState=running (MainPID 1023320)"],
        ["✓", "Startup log emits `MMD ENABLED:` line + `spot_aware_v2_1: ... mmd_mode=shadow`"],
        ["✓", "First Binance kline poll succeeds (HTTP 200; 60 bars buffered)"],
        ["✓", "MMD task `mmd-binance-poller` running alongside warmer / runner / halt-watcher"],
        ["○", "First post-restart fire's rationale ends with `mmd=&lt;label&gt; mmd_conf=&lt;conf&gt;` (window ≥ 1779057900 = 22:45 UTC)"],
        ["○", "Dashboard decision tape surfaces the `mmd=` annotation in the rationale field"],
        ["○", "0 mmd-related ERROR lines in journalctl over Day-0"],
    ]
    story.append(_table([["", "Check"]] + verify,
                        col_widths=[10 * mm, 158 * mm]))
    story.append(Paragraph(
        "Items marked ○ are pending the next fire; bot fires sparingly (J.1.6 "
        "spec) so it can take 5-30 minutes between fires. The Day-0 audit script "
        "(re-runnable any time): `grep '\"kind\": \"fired\"' state/decisions/2026-05-1*.jsonl | "
        "python3 -c 'import json,sys; [print(\"[MMD]\" if \"mmd=\" in (j:=json.loads(l)).get(\"rationale\",\"\") else \"[NO]\", j[\"window_ts\"], j[\"side\"]) for l in sys.stdin]'`",
        s["body"],
    ))

    story.append(Paragraph("§5.1 &nbsp; Live bot state at Session-3 ship close", s["h2"]))
    state_rows = [
        ["MainPID", "1023320 since 2026-05-17 22:41:25 UTC"],
        ["HEAD", "fd56b61f4a75134980ba8ec5f69114ae3c0cff15"],
        ["Branch", "claude/phase-P-hard-reset"],
        ["Strategy", "spot_aware_v2_1 (Kelly 0.15× / replay / cap=1 / J.1.5 fold / J.1 floor / J.2 hour blocklist / H.2.12 path-A)"],
        ["MMD config", "MMD_ENABLED=true / MMD_MODE=shadow / labels_to_abstain=() / lookback=60min / poll=30s"],
        ["Bankroll", "starting=$1000.00 / current=$790.15 (post-Session-1 drawdown)"],
        ["Today fires (pre-restart)", "12 (all WITHOUT mmd annotation — old MainPID 1019607)"],
        ["Today fires (post-restart)", "0 (waiting for first window-fire opportunity)"],
    ]
    story.append(_table(state_rows, col_widths=[58 * mm, 110 * mm], header=False))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 6 — 5-day window + Phase Q
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§6 &nbsp;&nbsp; 5-day observation window + Phase Q decision matrix",
                           s["h1"]))
    story.append(Paragraph("§6.1 &nbsp; Rules during observation", s["h2"]))
    rules = [
        "NO env flips during the 5-day window (anti-vibe rule).",
        "NO src/ ships during the 5-day window.",
        "Operator reviews dashboard daily; flags any UNKNOWN-rate &gt; 5% or 0 mmd annotations on fires.",
        "Day-5 audit runs an extended phase_p_mmd_backtest.py against the new live fires + compares to Session-2 backtest numbers.",
        "Halt sentinel (operator manual halt) is the ONLY allowed mid-window intervention.",
    ]
    for line in rules:
        story.append(Paragraph(f"&bull; {line}", s["body"]))

    story.append(Paragraph("§6.2 &nbsp; Phase Q decision matrix (Day-5)", s["h2"]))
    matrix = [
        ["MIXED WR ≥ next-best label by ≥ 10pp on n ≥ 100 live fires",
         "<b>PROMOTE</b> shadow → gate: set MMD_LABELS_TO_ABSTAIN=CHOPPY,UP,DOWN and MMD_MODE=gate. Also reconsider re-introducing M.5 as path-A-specific layer alongside MMD."],
        ["MIXED WR delta 5-10pp",
         "<b>KEEP SHADOW</b>; iterate on indicator parameters (try MMD_ADX_STRONG_THRESHOLD=22.0 or MMD_LOOKBACK_S=1800). Re-audit at Day-10."],
        ["MIXED WR delta ≤ 5pp",
         "<b>SHELVE</b> MMD. Reconsider strategy class entirely (Phase R pivot question)."],
        ["UNKNOWN-rate &gt; 5% (poll failure / indicator exceptions)",
         "<b>DIAGNOSE</b> at Phase Q before any promote-to-gate. Hardening needed in poller or in failure-mode tests."],
        ["MMD annotation missing from any fire's rationale",
         "<b>BUG</b>. Investigate why mmd_getter returned None / threw / wasn't wired. Halt and fix before Day-5 audit."],
    ]
    story.append(_table([["Day-5 signal", "Action"]] + matrix,
                        col_widths=[68 * mm, 100 * mm]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 7 — Rollback + failure-mode contract
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§7 &nbsp;&nbsp; Rollback + failure-mode contract", s["h1"]))
    story.append(Paragraph("§7.1 &nbsp; Rollback (any time, &lt; 60 s)", s["h2"]))
    rollback_lines = [
        "ssh ops@<vps>",
        "cd ~/polymarket-5m-bot",
        "sed -i '/MMD_ENABLED/d; /MMD_MODE/d' .envrc",
        "sudo systemctl restart bot-staging.service",
    ]
    for line in rollback_lines:
        story.append(Paragraph(line, s["code"]))
    story.append(Paragraph(
        "When MMD_ENABLED is absent (or false), run_paper.py never creates "
        "the poller task and never binds the getter. The strategy's "
        "mmd_getter stays None and `_maybe_fire` skips the MMD code path "
        "entirely — byte-identical to J.1.6.",
        s["body"],
    ))

    story.append(Paragraph("§7.2 &nbsp; Failure-mode contract (design/P.1 §6)", s["h2"]))
    contract = [
        ["`ta` library missing at init", "MarketModeDetector.__init__ logs WARN and sets _ta_available=False. latest() returns UNKNOWN forever. Bot keeps running."],
        ["Binance poll network/HTTP failure", "Poller logs warning, retries with backoff. Buffer keeps last-good bars. After ~2 × poll_interval of stale data, classification naturally degrades to UNKNOWN."],
        ["Indicator computation exception", "Caught at latest(); returns UNKNOWN. Strategy treats as pass-through."],
        ["MMD_ENABLED=true but ta missing in env", "Bot still boots (MMD becomes no-op stub). startup logs WARN about ta. Operator sees this immediately."],
        ["MMD_MODE=gate but MMD_LABELS_TO_ABSTAIN empty", "Equivalent to shadow (no abstain). Bot does not fail to start."],
        ["Strategy reads UNKNOWN label", "ALWAYS pass-through. Even in gate mode with UNKNOWN in abstain set. HARD requirement."],
        ["Strategy mmd_getter raises exception", "Caught at fire-time; treated as UNKNOWN; fire proceeds."],
    ]
    story.append(_table([["Failure", "Behavior"]] + contract,
                        col_widths=[60 * mm, 108 * mm]))

    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="80%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 4 * mm))
    story.append(Paragraph(
        "End of Phase P Session 3 ship.  "
        "Bot LIVE on J.1.6 + MMD shadow on claude/phase-P-hard-reset@fd56b61.  "
        "Phase Q decision opens Day-5 from this ship.",
        s["headline"],
    ))

    doc.build(story)
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build()
