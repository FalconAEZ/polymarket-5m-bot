"""Build pdfs/PHASE_S_MMB_OVERVIEW.pdf — operator reference for MMB at deploy time.

Modeled on pdfs/build_phase_n_forensic_audit_pdf.py — dark-terminal A4 with
cover, ToC, page numbers, embedded PNGs from state/research/phase-S-charts/.

Audience: operator (full candor, file refs included).
Length target: 20pp.
Tone: full honesty on Phase J/K/L/M/N/O/P failures; projections banded.

Usage:
    uv run --with matplotlib python -u scripts/research/phase_S_mmb_overview_charts.py
    uv run --with reportlab python -u pdfs/build_phase_S_mmb_overview_pdf.py
"""

# ruff: noqa: RUF001, RUF002, E501

from __future__ import annotations

from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "state" / "research" / "phase-S-charts"
OUT = ROOT / "pdfs" / "PHASE_S_MMB_OVERVIEW.pdf"

# Register DejaVu (Unicode-rich; matplotlib bundles it) so body text can
# render Δ, ≥, ≤, ∈, → and other glyphs that Reportlab's built-in
# Helvetica drops to blank squares.
import matplotlib  # noqa: E402

_FONT_DIR = Path(matplotlib.__file__).parent / "mpl-data" / "fonts" / "ttf"
pdfmetrics.registerFont(TTFont("DejaVu", str(_FONT_DIR / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONT_DIR / "DejaVuSans-Bold.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Oblique", str(_FONT_DIR / "DejaVuSans-Oblique.ttf")))
pdfmetrics.registerFont(TTFont("DejaVuMono", str(_FONT_DIR / "DejaVuSansMono.ttf")))

# Dark-terminal palette — matches build_phase_n_forensic_audit_pdf.py.
BG = HexColor("#0a0a0a")
PANEL = HexColor("#1a1a1a")
TEXT = HexColor("#e0e0e0")
SUBTLE = HexColor("#888888")
ACCENT = HexColor("#00ff88")
WARN = HexColor("#ffaa00")
LOSS = HexColor("#ff4466")
LINE = HexColor("#444444")
WIN_GREEN = HexColor("#7dd3a0")


def _page_template(doc: BaseDocTemplate) -> PageTemplate:
    frame = Frame(20 * mm, 18 * mm, A4[0] - 40 * mm, A4[1] - 36 * mm, id="body", showBoundary=0)

    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BG)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        canvas.setFillColor(SUBTLE)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            20 * mm, 10 * mm,
            "Phase S — MMB overview · 2026-05-20 · POLYMARKET 5m bot · OPERATOR REFERENCE",
        )
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"page {doc.page}")
        # Risk disclaimer footer (small + subtle).
        canvas.setFont("Helvetica-Oblique", 6.5)
        canvas.setFillColor(HexColor("#666666"))
        canvas.drawString(
            20 * mm, 6 * mm,
            "Backtest + research projections. MMB has NOT yet traded live. Real PnL may differ materially.",
        )
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.3)
        canvas.line(20 * mm, 14 * mm, A4[0] - 20 * mm, 14 * mm)
        canvas.restoreState()
    return PageTemplate(id="body", frames=[frame], onPage=draw)


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontName="DejaVu-Bold",
                             fontSize=20, textColor=ACCENT, leading=24, spaceAfter=10, spaceBefore=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="DejaVu-Bold",
                             fontSize=13, textColor=ACCENT, leading=17, spaceAfter=8, spaceBefore=14),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="DejaVu-Bold",
                             fontSize=10.5, textColor=TEXT, leading=14, spaceAfter=6, spaceBefore=10),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="DejaVu",
                               fontSize=9.5, textColor=TEXT, leading=13, alignment=TA_LEFT,
                               spaceAfter=6),
        "code": ParagraphStyle("code", parent=base["BodyText"], fontName="DejaVuMono",
                               fontSize=8.5, textColor=ACCENT, leading=11, leftIndent=12),
        "warn": ParagraphStyle("warn", parent=base["BodyText"], fontName="DejaVu",
                               fontSize=9.5, textColor=WARN, leading=13, spaceAfter=8,
                               leftIndent=8, rightIndent=8, borderColor=WARN,
                               borderWidth=0.5, borderPadding=6),
        "loss_box": ParagraphStyle("loss_box", parent=base["BodyText"], fontName="DejaVu-Bold",
                                   fontSize=9.5, textColor=LOSS, leading=13, spaceAfter=8,
                                   leftIndent=8, rightIndent=8, borderColor=LOSS,
                                   borderWidth=0.5, borderPadding=6),
        "win_box": ParagraphStyle("win_box", parent=base["BodyText"], fontName="DejaVu-Bold",
                                  fontSize=9.5, textColor=WIN_GREEN, leading=13, spaceAfter=8,
                                  leftIndent=8, rightIndent=8, borderColor=WIN_GREEN,
                                  borderWidth=0.5, borderPadding=6),
        "headline": ParagraphStyle("headline", parent=base["BodyText"], fontName="DejaVu-Bold",
                                   fontSize=11, textColor=ACCENT, leading=15, spaceAfter=10,
                                   alignment=TA_LEFT),
        "tt": ParagraphStyle("tt", parent=base["BodyText"], fontName="DejaVuMono",
                             fontSize=8, textColor=TEXT, leading=10),
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName="DejaVu-Bold",
                                      fontSize=30, textColor=ACCENT, leading=36, alignment=TA_CENTER,
                                      spaceAfter=20),
        "cover_sub": ParagraphStyle("cover_sub", parent=base["BodyText"], fontName="DejaVu",
                                    fontSize=12, textColor=TEXT, leading=18, alignment=TA_CENTER,
                                    spaceAfter=10),
        "cover_warn": ParagraphStyle("cover_warn", parent=base["BodyText"], fontName="DejaVu-Bold",
                                     fontSize=11, textColor=WARN, leading=15, alignment=TA_CENTER,
                                     spaceAfter=8),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="DejaVu",
                                fontSize=8, textColor=SUBTLE, leading=10, spaceAfter=4),
    }


def _table(rows, col_widths=None, header_color=ACCENT, body_color=TEXT, row_colors=None):
    t = Table(rows, colWidths=col_widths)
    style_list = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), header_color),
        ("TEXTCOLOR", (0, 1), (-1, -1), body_color),
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, LINE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    if row_colors:
        for ri, color in row_colors:
            style_list.append(("TEXTCOLOR", (0, ri), (-1, ri), color))
    t.setStyle(TableStyle(style_list))
    return t


def _pcell(text: str, fontsize: float = 8.5, color=TEXT, bold: bool = False) -> Paragraph:
    """Wrap a string in a Paragraph for table cells so text wraps + HTML entities decode."""
    font = "DejaVu-Bold" if bold else "DejaVu"
    style = ParagraphStyle(
        "tcell", fontName=font, fontSize=fontsize, textColor=color, leading=fontsize + 2, alignment=TA_LEFT,
    )
    return Paragraph(text, style)


def _img(name: str, width_mm: float = 170, height_mm: float | None = None):
    path = CHARTS / name
    if not path.exists():
        return Paragraph(f"<i>[missing chart: {name}]</i>", _styles()["body"])
    img = Image(str(path))
    iw, ih = img.imageWidth, img.imageHeight
    width = width_mm * mm
    height = (ih / iw) * width if height_mm is None else height_mm * mm
    img.drawWidth = width
    img.drawHeight = height
    return img


def build() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Phase S — MMB overview",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story: list = []

    # ──────────────────────────────────────────────────────────────────────
    # COVER
    # ──────────────────────────────────────────────────────────────────────
    story.append(Spacer(0, 30 * mm))
    story.append(Paragraph("PHASE&nbsp;S", s["cover_title"]))
    story.append(Paragraph("Market-Maker Bot · operator reference at deploy time",
                           s["cover_sub"]))
    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "POLYMARKET 5-minute BTC up/down<br/>"
        "Strategy class: <b>market-maker ladder</b> (continuous maker, both sides)<br/>"
        "Bankroll: <b>$1,000 starting</b> · MetaMask EOA + Polymarket Safe proxy<br/>"
        "Branch: <font name='DejaVuMono'>claude/phase-S-market-maker</font> @ <font name='DejaVuMono'>77bb7b2</font><br/>"
        "VPS HEAD: <font name='DejaVuMono'>22ccab4</font> (1 docs-only commit behind)<br/>"
        "Test baseline: <b>809 passing</b> · mypy --strict + ruff + import-linter clean",
        s["cover_sub"],
    ))
    story.append(Spacer(0, 16 * mm))
    story.append(Paragraph("Current state: code SHIPPED, NOT YET LIVE.",
                           s["cover_warn"]))
    story.append(Paragraph("Awaiting operator pre-deploy steps (env vars, allowance, G11 probes).",
                           s["cover_warn"]))
    story.append(Spacer(0, 12 * mm))
    story.append(Paragraph(
        "<b>The thesis in one sentence:</b> the directional bot exhausted its 5-day-resolution edge "
        "at +$95 cum over 4 days (Phase K) and halted at &minus;$327 (Phase M/N); MMB is the structural "
        "next strategy class — continuous maker ladder anchored to bonereaper's n=306,966 aligned-WR "
        "table — designed to extract spread + late-window edge that the single-fire directional class "
        "couldn't capture.",
        s["body"]))
    story.append(Spacer(0, 8 * mm))
    story.append(Paragraph(
        "<b>Honest expectation:</b> backtest (n=21,633 sim) shows +$1,586/7d on $1k bankroll, but queue "
        "position isn't modeled. Realistic Week 1 is +$30 to +$200. The 7-day soak is the test that "
        "decides whether MMB earns its scale-up.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # CONTENTS
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Contents", s["h1"]))
    toc_rows = [
        ["§", "Section", "page"],
        ["1", "TL;DR — what MMB is and what it's not", "3"],
        ["2", "What the old bot did and where it broke (J → K → L → M → N → O → P)", "4"],
        ["3", "Why MMB is structurally different — the 4 edges + bonereaper priors", "7"],
        ["4", "System architecture", "9"],
        ["5", "Backtest evidence (n=21,633 sim fills)", "12"],
        ["6", "Projections — $1,000 bankroll, 12 weeks", "14"],
        ["7", "Projections — $10,000 bankroll, 12 weeks", "17"],
        ["8", "Kelly + compounding mechanics", "19"],
        ["9", "Risks — what gets us killed", "20"],
        ["10", "The next 7 days — what they decide", "21"],
        ["A", "Appendix — source files cited", "22"],
    ]
    story.append(_table(toc_rows, col_widths=[10 * mm, 130 * mm, 20 * mm]))
    story.append(Spacer(0, 10 * mm))
    story.append(Paragraph(
        "<b>This document is OPERATOR REFERENCE.</b> Full candor on prior failures; "
        "projections include confidence bands, not point estimates; file refs included for verification. "
        "Every PnL number cites a memory checkpoint or runbook file (Appendix A).",
        s["warn"],
    ))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "<b>What this document is NOT:</b> a marketing pitch, a guarantee, or a substitute for the "
        "Day-7 soak gate. The MMB code has never placed a real order. Numbers below are derived from "
        "(a) bonereaper's 306,966-fill 30d table used as Bayesian priors, (b) a 21,633-fill simulator "
        "replay, and (c) the directional bot's actual loss history. All three are evidence; none is "
        "a forecast.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §1 — TL;DR
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("1. TL;DR — what MMB is and what it's not", s["h1"]))
    story.append(Paragraph(
        "MMB (Market-Maker Bot) is the Phase S strategy class. It is structurally different from the "
        "Phase 2&ndash;P directional bot:",
        s["body"]))
    diff_rows = [
        [_pcell("", bold=True), _pcell("Directional bot (Phase 2-P, halted)", bold=True),
         _pcell("MMB (Phase S, this doc)", bold=True)],
        [_pcell("Fire pattern"),
         _pcell("Single TAKER bet per window on a thesis (UP or DOWN)"),
         _pcell("Continuous MAKER ladder, both UP+DOWN, 3 levels each")],
        [_pcell("Win condition"),
         _pcell("Thesis is right at t=300s window close"),
         _pcell("Spread capture + adverse-selection avoidance")],
        [_pcell("Fees"),
         _pcell("Taker fees on every entry"),
         _pcell("Zero maker fees (CTF Exchange) + potential rebates")],
        [_pcell("Sizing"),
         _pcell("Kelly 0.15x × bankroll × edge per trade"),
         _pcell("Per-window inventory caps (5% gross / 2.5% per side)")],
        [_pcell("Edge source"),
         _pcell("Window-delta + oracle-gap + ensemble LLM agents"),
         _pcell("Bonereaper n=306,966 aligned-WR priors + 4 audit edges")],
        [_pcell("Failure mode"),
         _pcell("Wrong-side commit (irreversible)"),
         _pcell("Inventory drift (reversible: cancel + drain)")],
        [_pcell("Bankroll variance"),
         _pcell("Realized: $1k → $2,235 peak → $673 halt"),
         _pcell("Bounded by 5% daily-loss cap → auto-halt")],
    ]
    story.append(_table(diff_rows, col_widths=[28 * mm, 70 * mm, 70 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "<b>Headline:</b> MMB earns money on the spread between maker BUYs and the eventual settlement "
        "($0 or $1 per share). The bonereaper data says ~1.4% PnL on gross notional traded is achievable "
        "at his $766k/week scale. MMB at $1k bankroll runs ~15% of his volume so per-trade economics "
        "should be similar with structural differences in queue position.",
        s["headline"]))
    story.append(Spacer(0, 4))
    story.append(_img("01_directional_history.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 1. Directional-bot bankroll trajectory over Phases J-O — the empirical case for the MMB "
        "pivot. Peak +$1,235 on 2026-05-15; halt at &minus;$327 on 2026-05-17; Phase O attempt "
        "lost &minus;$163 on 1 fire before Phase P hard revert. Solid line = bankroll; markers = ship/peak/halt events.</i>",
        s["small"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §2 — What the old bot did and where it broke
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("2. What the old bot did and where it broke", s["h1"]))
    story.append(Paragraph(
        "Eleven phases of directional-bot work shipped between 2026-05-12 (Phase G) and 2026-05-17 "
        "(Phase P). The headline data: <b>635 fires audited in Phase G showed 50.0% WR / &minus;$18.96 net = "
        "zero edge</b>. Five subsequent phases tried to find and protect specific edges. The full Phase "
        "K-O cycle netted a peak-to-floor swing of <b>&minus;$1,562 in 45 hours</b> followed by a hard revert. "
        "This section walks each shipped defense and what killed it.",
        s["body"]))

    story.append(Paragraph("2.1 Phase J.1.6 — Kelly + bankroll replay (2026-05-14)", s["h2"]))
    story.append(Paragraph(
        "Shipped <b>BANKROLL_REPLAY_ENABLED=true</b> + <b>KELLY_MULT 0.10 → 0.15</b>. Combined ~2.3x "
        "bet scaling per trade. The thesis: replay-from-decision-log restores correct bankroll across "
        "bot restarts, and a higher Kelly multiplier captures more of the (then-believed) per-trade edge. "
        "Source: memory checkpoint_phase_J.md.",
        s["body"]))
    story.append(Paragraph(
        "<b>Outcome:</b> the 2.3x scaling amplified BOTH wins and losses. Phase K's 4-day soak showed "
        "$1,000 → peak $2,235 → trough $1,095. Variance was symmetric: Kelly didn't cause edge loss but "
        "made the realized swing 2-3x what a non-Kelly bot would have seen. <i>The lesson kept: variance "
        "is regime-driven, not Kelly-driven.</i>",
        s["warn"]))

    story.append(Paragraph("2.2 Phase K — 4-day soak (2026-05-16)", s["h2"]))
    story.append(Paragraph(
        "Closed Day 4 of a planned 14-day soak. Truth-corrected universe n=615 fires. Peak-to-trough "
        "in 18 hours was &minus;$1,294; on Day 4 alone the &minus;$30 daily-loss gate tripped <b>17 times</b> "
        "(the operator hadn't yet shipped Phase L.5 to automate the response to a gate trip). The "
        "operator's call: KEEP Kelly 0.15x + replay through Phase L (interpretation: variance is "
        "regime-driven, not Kelly-driven; ripping Kelly out wouldn't fix the regime-shift problem).",
        s["body"]))

    story.append(Paragraph("2.3 Phase L → M — five edge-defense layers in 22 hours", s["h2"]))
    phase_m_rows = [
        [_pcell("Layer", bold=True), _pcell("Shipped (UTC)", bold=True),
         _pcell("Mode", bold=True), _pcell("What it claimed", bold=True)],
        [_pcell("L.5"), _pcell("2026-05-16 12:51:59Z"), _pcell("active"),
         _pcell("Halt at UTC 23:50 if today's PnL ≤ −$30")],
        [_pcell("M.1a v0"), _pcell("2026-05-16 19:14:24Z"), _pcell("shadow"),
         _pcell("Annotate fires with regime=chop/mixed/trending")],
        [_pcell("M.1a v1"), _pcell("2026-05-17 11:25:56Z"), _pcell("active"),
         _pcell("Abstain fires labeled chop or unknown")],
        [_pcell("M.5"), _pcell("2026-05-17 11:44:57Z"), _pcell("active"),
         _pcell("Abstain Path A (tier 70-85% DN) when rolling WR &lt; BE + 2pp")],
        [_pcell("M.2 v0"), _pcell("2026-05-17 11:58:25Z"), _pcell("shadow"),
         _pcell("Annotate fires with imbalance=bullish/bearish/balanced/too_thin")],
    ]
    story.append(_table(phase_m_rows, col_widths=[18 * mm, 40 * mm, 16 * mm, 86 * mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>None of the active layers (L.5, M.1a v1, M.5) had more than 78 minutes of live time before halt.</b> "
        "L.5 served its purpose (daily-PnL guard tripped on 2026-05-16 23:50Z). The Sunday M.* layers were "
        "live for the 78-minute window 11:25Z → 12:43Z. Halt sentinel reason: <font name='DejaVuMono'>operator-cooldown</font>. "
        "Source: memory checkpoint_phase_M.md.",
        s["warn"]))
    story.append(PageBreak())

    story.append(Paragraph("2.4 Phase N — the forensic audit (22-page PDF, 2026-05-17)", s["h2"]))
    story.append(Paragraph(
        "Standalone forensic study at pdfs/PHASE_N_FORENSIC_AUDIT.pdf — n=755 fires, 4.2 days, one "
        "strategy (spot_aware_v2_1). Headline finding: <b>the &minus;$1,562 swing is dominated by ONE cell</b> &mdash; "
        "tier 30-50% × |Δbps|≥5 (the SURV cell from Phase L) flipping from 60.7% WR profit-engine to "
        "46.5% WR bleeder at the exact peak moment.",
        s["body"]))
    forensic_rows = [
        ["Period", "n", "WR", "$/trade", "PnL"],
        ["SURV cell, pre-peak", "112", "60.7%", "+$12.78", "+$1,431"],
        ["SURV cell, post-peak", "228", "46.5%", "−$5.09", "−$1,161"],
        ["delta", "+116", "−14.2pp", "−$17.87", "−$2,592 swing"],
    ]
    story.append(_table(forensic_rows, col_widths=[40 * mm, 22 * mm, 22 * mm, 25 * mm, 30 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "<b>M.5 was designed correctly</b> &mdash; the activation simulator showed it would have saved $330-$353 "
        "had it shipped 3 days earlier. <b>M.1a v1's chop-abstain logic was contradicted</b> on n=755: it was "
        "activated on n=23 of evidence and the larger sample says the opposite (low-|Δbps| buckets have "
        "<i>lower</i> WR, 33-36%, not higher). <i>The bot didn't break; a profitable cell stopped being profitable. "
        "The defense designed for it was right but late.</i>",
        s["loss_box"]))

    story.append(Paragraph("2.5 Phase O / P — Bankroll override (2026-05-17), hard revert (21:37Z)", s["h2"]))
    story.append(Paragraph(
        "Phase O attempted a $1k → $3k bankroll override with M.5 + SURV canary live; n=1 fire = LOSS &minus;$163. "
        "Operator immediately called Phase P. Phase P (2026-05-17 21:37Z) was a full revert: bankroll restored "
        "to $1k, BANKROLL_REPLAY_ENABLED=true preserved, MMD shadow-mode shipped for the bukosabino/ta market-mode "
        "detector. Subsequently, on 2026-05-19, the operator halted ALL six VPS services and disabled the "
        "directional bot entirely. <b>That decision is what made Phase S the next bet.</b>",
        s["body"]))
    story.append(Paragraph(
        "<b>Cumulative directional-bot result, end-to-end (Phases G-P):</b> 1,000 → 1,000 (net flat after $327 "
        "deposit drawdown was made whole; operator-confirmed). Total fires across all phases: ~3,500. <b>Net edge: "
        "zero (Phase G said so; everything subsequent confirmed it).</b> What the directional class can express "
        "in 5-minute resolution windows with single-fire takers reached its limit.",
        s["body"]))

    story.append(Paragraph("2.6 What the directional bot taught us — load-bearing lessons", s["h2"]))
    story.append(Paragraph(
        "1. <b>Cell-level edge is unstable.</b> A 60.7% WR cell can flip to 46.5% in days. "
        "Static blocklists are insufficient; either rolling adaptation or a strategy class that doesn't "
        "depend on single-cell-edge survival is required.<br/>"
        "2. <b>Active edge-defenses must ship in soak BEFORE the bleed.</b> 78 minutes of M.5 live time "
        "couldn't undo 45 hours of drawdown the defense was specifically designed to prevent.<br/>"
        "3. <b>Kelly scaling is a variance amplifier, not an edge creator.</b> Without positive edge, "
        "Kelly is just a faster way to lose. With positive edge, Kelly compounds &mdash; AND its drawdowns.<br/>"
        "4. <b>Single-fire takers are exposed to wrong-side commits.</b> A maker bot can cancel; a taker can't.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §3 — Why MMB is structurally different
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("3. Why MMB is structurally different", s["h1"]))
    story.append(Paragraph(
        "MMB ladders BUY orders on both sides (UP and DOWN tokens) at 3 price levels each within the "
        "300-second window. As taker flow lifts the asks, the bot's makers get filled. As the window "
        "approaches resolution, the bot cancels unfilled orders. The bot is BUY-side only — it never "
        "sells shares (no SELL ladder); shares either resolve to $1 (correct side) or $0 (wrong side). "
        "Source: design/S.1-market-maker-bot.md.",
        s["body"]))

    story.append(Paragraph("3.1 The bonereaper anchor &mdash; n=306,966 aligned fills", s["h2"]))
    story.append(Paragraph(
        "Wallet 0xeebd...eba30 ('bonereaper') has been running an MMB-class strategy on Polymarket BTC "
        "5m markets for 30+ days at ~$766k weekly notional. Phase A bonereaper-microstructure study "
        "extracted n=306,966 aligned BUY fills with WR 67.4%. This is the largest known per-cell edge "
        "dataset for this market class. <b>It is MMB's prior anchor.</b>",
        s["body"]))
    story.append(Paragraph(
        "The J7 priors table at design/j7_priors.json encodes per-tier-side WR and aligned $/trade. "
        "<font name='DejaVuMono'>J7Priors.bet_size(tier, fill_price, bankroll)</font> returns kelly_mult × kelly_f × "
        "bankroll where kelly_f is derived from the prior's p_win and the actual fill_price. "
        "<b>DEFAULT_KELLY_MULT_MMB = 0.10</b> (more conservative than the directional bot's 0.15).",
        s["body"]))
    story.append(_img("02_tier_side_dollar_per_trade.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 2. Per-tier × side $/trade from the fresh weekly bonereaper data (n=21,633 fills "
        "2026-05-12 → 2026-05-19). Hatched red-border bars are blocked by Edge 1 (per-tier-side "
        "blocklist). DOWN-side dominates on the tier extremes; UP-side has the structural leaks.</i>",
        s["small"]))
    story.append(PageBreak())

    story.append(Paragraph("3.2 Edge 1 — Per-tier-side blocklist", s["h2"]))
    story.append(Paragraph(
        "Bonereaper ladders both sides indiscriminately because his $766k/week notional absorbs the "
        "~$3.7k/week leak in three losing cells. At MMB's $1k scale, the same leak ratio would be "
        "&minus;$555/week — fatal. Edge 1 hard-codes a blocklist of three loss-side cells:",
        s["body"]))
    blocklist_rows = [
        ["Tier", "Side", "n", "WR", "$/tr", "Weekly leak"],
        ["50-70%", "DOWN", "3,366", "57.1%", "−$0.76", "−$2,563"],
        ["15-30%", "UP", "1,345", "22.8%", "−$0.61", "−$820"],
        ["30-50%", "UP", "3,079", "40.8%", "−$0.11", "−$325"],
    ]
    story.append(_table(blocklist_rows, col_widths=[20 * mm, 16 * mm, 18 * mm, 18 * mm, 18 * mm, 26 * mm]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "Source: runbooks/research/mmb-deep-edge-audit-2026-05-20.md §2 Edge 1. Implementation: "
        "<font name='DejaVuMono'>LadderPlanner.blocklist</font> early-returns empty levels for these (tier, side) tuples. "
        "Estimated MMB-scale impact: <b>+$450-$750/week</b> from avoided leaks.",
        s["body"]))

    story.append(Paragraph("3.3 Edge 2 &mdash; Late-window 2x size multiplier", s["h2"]))
    story.append(Paragraph(
        "Bonereaper's $/trade is 3-12x higher in the last 60 seconds of a window than in the first 240. "
        "The 0-30s × DOWN bucket alone earns +$12.09/trade across 361 fills. MMB's current design "
        "ladders uniformly across the 300s window. Edge 2 doubles the per-order size in the last 60s.",
        s["body"]))
    story.append(_img("03_late_window_edge.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 3. Late-window edge. The shaded LATE region (0-60s remaining) carries 4x the dataset-wide "
        "average $/trade. Edge 2 doubles MMB's per-order size in this region.</i>",
        s["small"]))

    story.append(Paragraph("3.4 Edge 3 &mdash; pct-bankroll caps (MM_CAPS_MODE flag)", s["h2"]))
    story.append(Paragraph(
        "Current RiskCaps are absolute USD: $25 inventory / $50 gross / $50 daily-loss. As bankroll "
        "compounds these caps stop scaling — at $5k bankroll, the $50 gross cap is 1%, not 5%. The "
        "compounding curve stops. <b>MM_CAPS_MODE=pct_bankroll</b> swaps caps to bankroll fractions "
        "(2.5% inventory / 5% gross / 5% daily) at gate-check time. <b>S.5 ships with mode=fixed_usd "
        "(safer); Day-7 PASS gates the flip to pct_bankroll.</b>",
        s["body"]))

    story.append(Paragraph("3.5 Edge 4 &mdash; MMD label in decision log (data collection only)", s["h2"]))
    story.append(Paragraph(
        "Phase P shipped a MarketModeDetector (chop/mixed/trending labels). The killer cell hypothesis "
        "from Phase Q: MMD=MIXED × side=DOWN was +$3.16/tr on n=226 (vs label-only +$0.78/tr). For MMB "
        "the mechanic differs (ladders not single-fires), so the gate is data collection now and "
        "Day-7 evaluation. Implementation: metadata_getter wired into mm-decisions log; each fill "
        "annotated with the live MMD label for later analysis.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §4 — Architecture
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("4. System architecture", s["h1"]))
    story.append(_img("07_architecture.png", width_mm=175))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 4. Block diagram of MMB at deploy time. On-chain layer (top) handles custody + allowance; "
        "CLOB API (middle) is the order venue; bot core (purple/violet) is the strategy + risk chain; "
        "state layer (light purple) is the persistent decision log + replay; safety ops (orange/teal) "
        "is the always-on monitoring.</i>",
        s["small"]))
    story.append(PageBreak())

    story.append(Paragraph("4.1 On-chain wallet topology", s["h2"]))
    story.append(Paragraph(
        "MMB uses the Polymarket Safe-proxy pattern (<font name='DejaVuMono'>signature_type=2</font>) per "
        "design/S.1-market-maker-bot.md §251. <b>PK_SIGNER</b> is the MetaMask EOA private key; "
        "<b>POLY_FUNDER</b> is the Polymarket-deployed Gnosis Safe proxy address (auto-created on first "
        "polymarket.com MetaMask connection). USDC.e sits in the Safe; the Safe approves the CTF Exchange "
        "(<font name='DejaVuMono'>0x4bFb...8982E</font>) for MAX_UINT256 USDC.e (<font name='DejaVuMono'>0x2791...4174</font>) "
        "spend. Each maker order is signed by the EOA (L1 EIP-712) and authenticated to CLOB (L2 HMAC-SHA256 "
        "via CLOB_API_KEY/SECRET/PASSPHRASE derived once via scripts/derive_creds.py).",
        s["body"]))
    story.append(Paragraph(
        "Phase 1A wallets (Funder <font name='DejaVuMono'>0x512D...5d22</font>, Signer <font name='DejaVuMono'>0x8d97...2B4A</font>) "
        "are <b>NOT used</b> for MMB. Those were generated for the directional bot's "
        "<font name='DejaVuMono'>signature_type=0</font> (EOA-direct) model; the Phase S design intentionally "
        "switched to Safe-proxy for the gasless-relayer path.",
        s["body"]))

    story.append(Paragraph("4.2 Bot-core control flow", s["h2"]))
    story.append(Paragraph(
        "<b>1. <font name='DejaVuMono'>run_mm_live.py</font></b> &mdash; VPS entrypoint. Refuses to start unless all 4 "
        "preflight gates pass: <font name='DejaVuMono'>MM_LIVE_CONFIRM=yes</font>; halt sentinel absent; "
        "<font name='DejaVuMono'>state/mm-allowance.json</font> present + recent + ≥$100 allowance; "
        "CLOB L2 creds + wallet env vars complete. On any gate fail, exits 2; systemd "
        "<font name='DejaVuMono'>Restart=on-failure</font> retries after 30s.",
        s["body"]))
    story.append(Paragraph(
        "<b>2. Market discovery</b> &mdash; queries Gamma API for active BTC 5m markets with slug pattern "
        "<font name='DejaVuMono'>btc-updown-5m-*</font>. Caps concurrent markets at 3 to bound exposure. "
        "For each market, spawns two book-loop tasks (one per UP/DOWN token).",
        s["body"]))
    story.append(Paragraph(
        "<b>3. Book loop</b> &mdash; per (market, token) poll <font name='DejaVuMono'>get_orderbook(token_id)</font> "
        "every 1s. On book update: <font name='DejaVuMono'>MmRunner.on_book_update()</font> → "
        "<font name='DejaVuMono'>MarketMakerStrategy.compute_ladder()</font> → <font name='DejaVuMono'>LadderPlanner.plan_levels()</font>. "
        "Plans 3 price levels per side with size_usd computed via J7Priors.bet_size() × Kelly. "
        "Applies Edge 1 blocklist + Edge 2 late-window multiplier.",
        s["body"]))
    story.append(Paragraph(
        "<b>4. Risk gate</b> &mdash; <font name='DejaVuMono'>RiskGate.can_place()</font> verifies size + "
        "post-place state against RiskCaps: per-token inventory ($25 abs / 2.5% pct), per-window gross "
        "($50 abs / 5% pct), daily realized PnL not below loss cap. Halt-sentinel trip writes a JSON "
        "marker file → bot drains + exits.",
        s["body"]))
    story.append(Paragraph(
        "<b>5. Place / cancel</b> &mdash; <font name='DejaVuMono'>LiveClobOrderClient.place_order()</font> "
        "delegates to py-clob-client's <font name='DejaVuMono'>create_order() + post_order(GTC, post_only=True)</font>. "
        "Post-only ensures zero taker fills. Cancel-replace fires on every book move &gt; <font name='DejaVuMono'>l1_repost_threshold</font> (0.02).",
        s["body"]))
    story.append(PageBreak())

    story.append(Paragraph("4.3 State + replay", s["h2"]))
    story.append(Paragraph(
        "<b>Decision log</b> at <font name='DejaVuMono'>state/mm-decisions/&lt;UTC&gt;.jsonl</font>. One line per planning "
        "decision: market, token, side, tier, plan_levels, bet_size, kelly_f, fill_price, halt_reason. "
        "Used by the soak audit harness (<font name='DejaVuMono'>scripts/research/mmb_soak_audit.py</font>) and the bankroll "
        "replay (<font name='DejaVuMono'>replay_bankroll()</font>).",
        s["body"]))
    story.append(Paragraph(
        "<b>Bankroll replay</b> &mdash; on every restart, <font name='DejaVuMono'>run_mm_live.py:311</font> calls "
        "<font name='DejaVuMono'>replay_bankroll(state/mm-decisions, starting_bankroll=1000.0)</font> which "
        "walks the decision log and reconstructs the current bankroll. This is the same mechanism the "
        "directional bot used for J.1.6; preserved in MMB because it's the cheapest way to ensure "
        "restart-safety without a database.",
        s["body"]))
    story.append(Paragraph(
        "<b>Halt sentinel</b> at <font name='DejaVuMono'>state/halt.sentinel</font>. Writing this file from any source "
        "(operator CLI, Telegram /halt, heartbeat-miss, daily-loss trip) causes the bot to drain all open "
        "orders and exit. Restart blocked until operator removes it.",
        s["body"]))
    story.append(Paragraph(
        "<b>Allowance audit</b> at <font name='DejaVuMono'>state/mm-allowance.json</font> produced by "
        "<font name='DejaVuMono'>scripts/mm_set_allowance.py</font>. Bot's preflight gate refuses start unless "
        "the audit is recent (&lt;24h) and reports ≥$100 allowance.",
        s["body"]))

    story.append(Paragraph("4.4 Always-on safety + ops", s["h2"]))
    story.append(Paragraph(
        "<b>Heartbeat</b> &mdash; <font name='DejaVuMono'>mm_heartbeat_loop</font> writes a no-op CLOB request every 5s. "
        "2 consecutive misses → write halt sentinel + Telegram alert. Detects CLOB connectivity issues "
        "before the bot starts placing orders against a stale view of the book.",
        s["body"]))
    story.append(Paragraph(
        "<b>Telegram alerter</b> &mdash; <font name='DejaVuMono'>tg-alerter.service</font> drains a Redis sink "
        "and forwards alerts to the operator's Telegram. Also listens for <font name='DejaVuMono'>/halt</font> "
        "messages → writes halt sentinel. End-to-end verified via test alert during Phase S Session 4.",
        s["body"]))
    story.append(Paragraph(
        "<b>Dashboard</b> &mdash; <font name='DejaVuMono'>dashboard-server.service</font> on VPS :8505. SSH tunnel: "
        "<font name='DejaVuMono'>ssh -L 8505:127.0.0.1:8505 ops@108.132.51.116</font> → http://localhost:8505. "
        "v3 React+FastAPI; shows live decisions, cumulative PnL, halt sentinel state.",
        s["body"]))
    story.append(Paragraph(
        "<b>Litestream</b> &mdash; <font name='DejaVuMono'>litestream.service</font> backs up "
        "<font name='DejaVuMono'>state/trades.db</font> to AWS S3 eu-west-1 continuously. Restore drill at Phase 5 "
        "(2026-05-08) was md5-identical. Disaster recovery RPO &lt; 1s.",
        s["body"]))
    story.append(Paragraph(
        "<b>systemd hardening</b> &mdash; <font name='DejaVuMono'>bot-mm.service</font> runs as ops user, "
        "<font name='DejaVuMono'>NoNewPrivileges=true</font>, <font name='DejaVuMono'>PrivateTmp=true</font>, "
        "<font name='DejaVuMono'>ProtectSystem=full</font>. <font name='DejaVuMono'>Restart=on-failure</font> with 30s back-off. "
        "<font name='DejaVuMono'>TimeoutStopSec=30</font> gives SIGTERM-driven drain enough headroom.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §5 — Backtest evidence
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("5. Backtest evidence (n=21,633 sim fills)", s["h1"]))
    story.append(Paragraph(
        "Phase S Session 2 ran the strategy code end-to-end against bonereaper's 21,633 fresh weekly "
        "BUY fills (2026-05-12 → 2026-05-19). For each market, the simulator co-fills MMB at every "
        "bonereaper fill price and computes per-tier inventory, applies the risk gate, and books PnL "
        "to settlement. <b>Result: +$1,586.37 sim PnL on $1,000 bankroll over 7 days.</b>",
        s["body"]))

    backtest_summary = [
        [_pcell("Metric", bold=True), _pcell("Value", bold=True)],
        [_pcell("Markets resolved"), _pcell("723")],
        [_pcell("Bonereaper BUY fills processed"), _pcell("21,633")],
        [_pcell("MMB simulated positions"), _pcell("12,332")],
        [_pcell("MMB total sim PnL"), _pcell("+$1,586.37")],
        [_pcell("MMB gross traded"), _pcell("$114,640.47")],
        [_pcell("Bonereaper PnL (same markets)"), _pcell("+$11,089.41")],
        [_pcell("Bonereaper gross traded"), _pcell("$766,011.09")],
        [_pcell("MMB / Bonereaper PnL ratio"), _pcell("+14.31% (matches gross-scale ratio of ~15%)")],
        [_pcell("MMB PnL / notional"), _pcell("1.38% (bonereaper: 1.45% — structurally similar)")],
    ]
    story.append(_table(backtest_summary, col_widths=[80 * mm, 90 * mm]))
    story.append(Spacer(0, 6))
    story.append(_img("08_backtest_tier_pnl.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 5. Per-tier MMB sim PnL (left) and position count (right). 30-50% and 50-70% tiers dominate "
        "PnL. &lt;15% tier loses &minus;$1,441 despite the priors table showing +$8.83/trade aligned-WR — because "
        "MMB simulates filling at ALL bonereaper price points in that tier, but most of bonereaper's "
        "&lt;15% volume is contrarian (n=16,622 contrarian vs n=722 aligned). Co-filling contrarian without "
        "alignment conditioning collapses per-trade EV. Edge 1 blocklist addresses this directly.</i>",
        s["small"]))
    story.append(PageBreak())

    story.append(Paragraph("5.1 What this backtest is NOT", s["h2"]))
    story.append(Paragraph(
        "Per the 2026-05-20 'paper-is-fake' operator pivot, this is a <b>plumbing-only sanity check</b>: "
        "it confirms the strategy code runs end-to-end on real data and the payout math is sane. "
        "It does NOT predict live PnL. Specifically:",
        s["warn"]))
    notable_caveats = [
        [_pcell("Caveat", bold=True), _pcell("Why it matters", bold=True)],
        [_pcell("Queue position not modeled"),
         _pcell("MMB's $5-10/level orders queue BEHIND bonereaper's $30+/level orders. The sim co-fills at the same price/time → upper-bound PnL estimate. Real queue-position penalty: 30-70%.")],
        [_pcell("Orderbook depth not reconstructed"),
         _pcell("Sim uses bonereaper fill prices as proxy for taker-flow level; no per-second best-ask snapshots.")],
        [_pcell("Maker fees assumed zero"),
         _pcell("Empirical answer comes from G11 fee probe (Session 6 operator step). If non-zero, J7Priors.bet_size math gets recalibrated before flip-to-live.")],
        [_pcell("Cancel-and-replace dynamics not simulated"),
         _pcell("Every bonereaper fill is treated as a placement opportunity. Real cancel cadence is bounded by the CLOB rate-limit (G11 probe pending).")],
    ]
    story.append(_table(notable_caveats, col_widths=[55 * mm, 115 * mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>The real edge gate is the S.5 live-micro soak on real orders.</b> A green backtest is necessary "
        "but not sufficient; a red backtest would be alarming and warrant a code review. Source: "
        "runbooks/research/mmb-backtest-2026-05-20.md.",
        s["headline"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §6 — Projections $1k
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("6. Projections — $1,000 bankroll, 12 weeks", s["h1"]))
    story.append(Paragraph(
        "Three projection bands. The mid-band weekly growth rates are derived from the deep-edge-audit "
        "§5 expected weekly returns at MMB's $1k scale, with edges 1 + 2 active and MM_CAPS_MODE flipping "
        "to pct_bankroll from week 2 (i.e. Day-7 PASS). Decay past week 4 reflects market-depth bite — "
        "bonereaper does $766k/wk gross at his bankroll, so MMB's compounding hits a depth ceiling around "
        "$30-50k effective bankroll regardless of edge strength.",
        s["body"]))
    story.append(_img("04_projection_1k.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 6. $1,000 bankroll projection bands over 12 weeks. Y-axis is logarithmic. "
        "LOW band assumes 70% queue-position penalty → ~+15% weekly. MID assumes 50% penalty → "
        "+80% weekly weeks 1-4 then decay. HIGH assumes 30% penalty → +150% weekly weeks 1-4. Dashed "
        "horizontal line at $50k = market-depth ceiling.</i>",
        s["small"]))

    proj_1k_rows = [
        ["Week", "LOW band (70% penalty)", "MID band (50% penalty)", "HIGH band (30% penalty)"],
        ["0 (start)", "$1,000", "$1,000", "$1,000"],
        ["1", "$1,150", "$1,800", "$2,500"],
        ["2", "$1,322", "$3,240", "$6,249"],
        ["4", "$1,749", "$10,488", "$30,219"],
        ["8", "$3,060", "$33,706", "$46,891"],
        ["12", "$5,350", "$45,283", "$49,476"],
    ]
    story.append(_table(proj_1k_rows, col_widths=[20 * mm, 45 * mm, 45 * mm, 45 * mm]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Approximate bankroll at each week under each band. Numbers from the audit's compounding "
        "model with market-depth soft-cap. Real trajectory will be one of these three or a path between them.</i>",
        s["small"]))
    story.append(PageBreak())

    story.append(Paragraph("6.1 The first 7 days &mdash; honest expectation", s["h2"]))
    story.append(Paragraph(
        "Week 1 is the critical window. The deep-edge-audit §6 (honest expectation framing) gives:",
        s["body"]))
    wk1_rows = [
        [_pcell("Scenario", bold=True), _pcell("Cum PnL", bold=True),
         _pcell("Probability framing", bold=True), _pcell("Source", bold=True)],
        [_pcell("Most likely"), _pcell("+$30 to +$200 (3-20% weekly)"),
         _pcell("Edges 1+2 active, queue penalty 50-70%"), _pcell("audit §6")],
        [_pcell("Best case"), _pcell("+$400 to +$700 (40-70%)"),
         _pcell("Queue position better than feared"), _pcell("audit §6")],
        [_pcell("Marginal (extend)"), _pcell("−$30 to +$30 (≈break-even)"),
         _pcell("Edges work but queue penalty severe"), _pcell("audit §6")],
        [_pcell("Gate failure"), _pcell("Cum &lt; −$50 OR any incident"),
         _pcell("Halt + postmortem; Phase S concluded"), _pcell("OPERATOR_HANDOFF §2.3")],
    ]
    story.append(_table(wk1_rows, col_widths=[30 * mm, 40 * mm, 60 * mm, 30 * mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>10x bonereaper</b> framing: bonereaper does ~10-15% weekly at his $100k+ bankroll. The audit "
        "states a target of 100-150% weekly on $1k = $1,000-$1,500/week. That target is in the HIGH band "
        "and only achievable for the first 3-4 weeks; market depth caps compounding by week 6-8 regardless "
        "of edge strength. <b>Don't bet on best-case; budget for realistic.</b>",
        s["warn"]))

    story.append(Paragraph("6.2 How to read the bands honestly", s["h2"]))
    story.append(Paragraph(
        "Three properties of the bands worth internalizing:<br/><br/>"
        "1. <b>The LOW band is plausible.</b> If queue position never improves past back-of-book at our "
        "$5-10/level orders, MMB earns spread but at 30% of the bonereaper-anchored rate. That's still "
        "positive — $1k → $5.4k in 12 weeks = 14% weekly compounded — but it's a slow burn, not a moonshot.<br/><br/>"
        "2. <b>The MID and HIGH bands diverge fastest in weeks 2-4.</b> If Edge 2 (late-window 2x multiplier) "
        "works as designed, the gap between LOW and MID is mostly that single effect. Day-1 + Day-7 audit "
        "data should let us distinguish which band we're tracking.<br/><br/>"
        "3. <b>All bands flatten by week 8.</b> Market depth doesn't care about our edge. Bonereaper himself "
        "isn't doing 100% weekly — he's doing ~12% weekly at scale. Whatever band MMB tracks, by week "
        "10 the per-week growth rate is in the single-digit-percent range regardless.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §7 — Projections $10k
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("7. Projections — $10,000 bankroll, 12 weeks", s["h1"]))
    story.append(Paragraph(
        "$10k is NOT a starting condition. Decision #10 locks $1k starting bankroll; decision #12 requires "
        "a hardware wallet at the $2k trigger; decision #23 reaffirmed $1k for Phase S. <b>$10k bankroll "
        "is the week-4-to-week-8 zone IF the MID or HIGH band tracks.</b> This chart shows what compounding "
        "looks like FROM that starting point — useful as a sanity-check for the 'is there a future' question.",
        s["warn"]))
    story.append(_img("05_projection_10k.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 7. $10,000 bankroll projection bands over 12 weeks. Same model as Fig 6, scaled. The "
        "LOW band trajectory shows compounding still works at this scale; MID and HIGH bands compress "
        "much faster as the market-depth ceiling bites in weeks 2-4 (vs weeks 6-8 at $1k).</i>",
        s["small"]))

    proj_10k_rows = [
        ["Week", "LOW band (70% penalty)", "MID band (50% penalty)", "HIGH band (30% penalty)"],
        ["0 (start)", "$10,000", "$10,000", "$10,000"],
        ["1", "$11,500", "$18,000", "$25,000"],
        ["2", "$13,225", "$30,672", "$43,750"],
        ["4", "$17,490", "$48,650", "$50,000"],
        ["8", "$30,597", "$50,000", "$50,000"],
        ["12", "$50,000 (capped)", "$50,000 (capped)", "$50,000 (capped)"],
    ]
    story.append(_table(proj_10k_rows, col_widths=[20 * mm, 45 * mm, 45 * mm, 45 * mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>Why $50k is a hard ceiling:</b> bonereaper's per-window notional ≈ $750. To do 7-10x that "
        "(needed at $50k bankroll to maintain his per-window edge contribution) would require an operationally "
        "implausible amount of taker flow to absorb our maker orders. The depth model in the audit "
        "(§5) caps realistic MMB bankroll around $30-50k. Beyond that, the strategy class is depth-limited, "
        "not edge-limited.",
        s["headline"]))
    story.append(PageBreak())

    story.append(Paragraph("7.1 Honest framing on $10k — most likely it never happens", s["h2"]))
    story.append(Paragraph(
        "Of the three Week-1 scenarios in §6.1, only the BEST CASE puts us at $10k by week 4-5 of "
        "compounding (week 0 = $1k, weeks 1-5 at +60% weekly ≈ $10.5k). The MOST LIKELY scenario gets us "
        "there in 8-12 weeks if it's also a sustained MID-band run.",
        s["body"]))
    story.append(Paragraph(
        "<b>The $10k question matters because of decision #12.</b> At the $2k bankroll trigger (which the "
        "MID and HIGH bands cross in week 1), hardware wallet wiring becomes a hard prerequisite for any "
        "further bankroll bump. The decision #23 addendum explicitly states: 'If S.5+S.6 succeed and "
        "operator later scales bankroll beyond $2k, HW wallet wiring becomes a hard pre-requisite for "
        "that bankroll-bump phase (separate decision logged at that time).'",
        s["body"]))
    story.append(Paragraph(
        "Practical sequence if MID band tracks: Day-7 PASS (week 1, ~$2k bankroll) → flip MM_CAPS_MODE "
        "to pct_bankroll → buy + wire a Ledger/Trezor for the Signer key → continue soak through week 2 → "
        "if cum > $5k AND no incidents, scale MAX_GROSS_PCT to 10% per audit §6 verdict → continue.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §8 — Kelly + compounding
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("8. Kelly + compounding mechanics", s["h1"]))
    story.append(Paragraph(
        "Kelly is still present in MMB but operates differently than in the directional bot. "
        "<font name='DejaVuMono'>J7Priors.bet_size()</font> at <font name='DejaVuMono'>src/polymarket_bot/strategies/j7_priors.py:178</font> "
        "computes: <font name='DejaVuMono'>raw_bet = kelly_mult × kelly_f × bankroll</font>, where kelly_f is the "
        "classical Kelly fraction <font name='DejaVuMono'>(p × b − q) / b</font> derived from the per-tier prior's p_win "
        "and the actual fill_price (b = (1 − fill_price) / fill_price). The result is then clamped by the "
        "RiskCaps and the per-tier min/max.",
        s["body"]))
    story.append(Paragraph(
        "<b>Current values:</b><br/>"
        "&nbsp;&nbsp;DEFAULT_KELLY_MULT_MMB = <b>0.10</b> (vs directional bot's 0.15; more conservative)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_BET_USD_MMB = <b>$10.00</b> (scale-up target $25.00)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_INVENTORY_PER_TOKEN_USD = <b>$25.00</b> (fixed_usd mode)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_USD = <b>$50.00</b> (fixed_usd mode)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_DAILY_LOSS_USD = <b>$50.00</b> (5% of starting bankroll)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_INVENTORY_PER_TOKEN_PCT = <b>2.5%</b> (pct_bankroll mode)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_GROSS_EXPOSURE_PER_WINDOW_PCT = <b>5.0%</b> (pct_bankroll mode)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_DAILY_LOSS_PCT = <b>5.0%</b> (pct_bankroll mode)<br/>"
        "&nbsp;&nbsp;DEFAULT_MAX_BET_USD_CEILING = <b>$500.00</b> (sanity ceiling at large bankroll)",
        s["body"]))
    story.append(_img("06_caps_mode_compounding.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 8. The MM_CAPS_MODE compounding lock. Assumes +50% weekly mid-band edge. In fixed_usd "
        "mode the $50 gross cap shrinks as a fraction of bankroll (5% at $1k → 1% at $5k → 0.5% at $10k), "
        "throttling compounding. In pct_bankroll mode the cap is always 5% of live bankroll, so "
        "compounding scales until the $50k market-depth ceiling.</i>",
        s["small"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §9 — Risks
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("9. Risks — what gets us killed", s["h1"]))
    story.append(Paragraph(
        "Sorted by realistic-impact-times-likelihood. None of these are theoretical &mdash; each is anchored "
        "in either a Phase A-P incident or an explicit audit gap.",
        s["body"]))
    risk_rows = [
        [_pcell("#", bold=True), _pcell("Risk", bold=True),
         _pcell("Likely impact", bold=True), _pcell("Mitigation", bold=True)],
        [_pcell("R1"), _pcell("Queue position permanently bad at $1k scale"),
         _pcell("−50-70% of sim PnL; LOW band"),
         _pcell("Day-7 measures actual queue position; pct_caps unlocks at $2-5k")],
        [_pcell("R2"), _pcell("Accounting drift (redeemPositions gap)"),
         _pcell("Bot says +$X but wallet doesn't grow"),
         _pcell("Day-1 audit checks USDC.e balance vs sim PnL; if drift, ship Edge E2 immediately")],
        [_pcell("R3"), _pcell("Maker fees non-zero on BTC 5m"),
         _pcell("Per-trade EV shifts by ~0.1-0.5%"),
         _pcell("G11 fee probe before live deploy; J7Priors.bet_size recalibration")],
        [_pcell("R4"), _pcell("Daily-loss cap trip in week 1"),
         _pcell("Bot halts; operator extends soak"),
         _pcell("5% daily-loss cap is conservative; trip = data, not failure")],
        [_pcell("R5"), _pcell("MetaMask key on VPS exposed"),
         _pcell("Total loss of funded bankroll"),
         _pcell("Per decision #12, HW wallet required at $2k; cap stays $1k until then")],
        [_pcell("R6"), _pcell("Heartbeat-miss false positive"),
         _pcell("Bot halts; orphan orders survive 30s"),
         _pcell("TimeoutStopSec=30 drain + Telegram alert; manual rm halt.sentinel")],
        [_pcell("R7"), _pcell("MMD label proves noisy in MMB"),
         _pcell("Edge 4 metadata is noise; no week-2 layer-on"),
         _pcell("Day-7 audit groups fills by mmd_label; if no signal, skip Edge 4")],
        [_pcell("R8"), _pcell("Bonereaper edge regime-shifts"),
         _pcell("Priors become wrong; WR drops 10-15pp"),
         _pcell("Add MMB-specific rolling per-cell estimates post-Day-30 (Edge 6 in audit)")],
        [_pcell("R9"), _pcell("WebSocket-vs-poll book staleness"),
         _pcell("Last-60s late-window cancels lose queue priority"),
         _pcell("Plan Edge E1 (WS subscription) ships post-Day-7 PASS")],
        [_pcell("R10"), _pcell("CLOB rate-limit (429s) under load"),
         _pcell("Cancel-replace cadence chokes"),
         _pcell("G11 rate-limit probe + RiskCaps.max_orders_per_minute (default 30) caps cadence")],
    ]
    story.append(_table(risk_rows, col_widths=[10 * mm, 42 * mm, 50 * mm, 68 * mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>The top three by impact:</b> R1 (queue position) is the existential one — if MMB never gets "
        "good queue position, the LOW band is the actual trajectory and the operator decides at week 4 "
        "whether 14% weekly is worth running. R2 (redeemPositions) is the silent-killer: bot can show "
        "winning paper PnL while the wallet stays flat. R5 (MetaMask key on VPS) is the "
        "operational-vulnerability one and the explicit reason for decision #12's $2k HW-wallet trigger.",
        s["loss_box"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # §10 — Next 7 days
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("10. The next 7 days — what they decide", s["h1"]))
    story.append(Paragraph(
        "Per runbooks/OPERATOR_HANDOFF_PHASE_S.md §2.3, the Day-7 audit is the promotion gate to "
        "Phase S.6 (scale-up). Three outcomes:",
        s["body"]))
    gate_rows = [
        [_pcell("Outcome", bold=True), _pcell("Criteria", bold=True), _pcell("Next step", bold=True)],
        [_pcell("PASS"),
         _pcell("Cum PnL &gt; $0 AND 0 heartbeat-miss-incidents AND 0 daily-loss trips AND fill rate ∈ [0, 1]"),
         _pcell("S.6 scale-up: MM_CAPS_MODE=pct_bankroll; raise inv pct 2.5% → 5%; raise gross pct 5% → 10%; continue soak week 2")],
        [_pcell("MARGINAL"),
         _pcell("Cum PnL ∈ [+$5, +$30] AND no incidents"),
         _pcell("Extend soak 7 more days at live-micro caps; revisit")],
        [_pcell("FAIL"),
         _pcell("Cum PnL ≤ $0 OR any incident requiring halt"),
         _pcell("runbooks/postmortems/2026-05-XX-mmb-s5-failure.md; Phase S possibly concludes 'MMB at $1k not viable'; pivot or shelve")],
    ]
    story.append(_table(gate_rows, col_widths=[24 * mm, 80 * mm, 66 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "<b>Either outcome is informative.</b> A PASS validates the bonereaper-anchored thesis and unlocks "
        "the compounding trajectory. A FAIL is a definitive answer: the directional class hit its limit at "
        "$1k AND the market-maker class hits its limit at $1k → the strategy-class search continues, but "
        "from a known-bad starting position rather than a hopeful one.",
        s["headline"]))
    story.append(Paragraph(
        "<b>What you (operator) do during the 7 days:</b><br/>"
        "&nbsp;&nbsp;Every 12-24h: tail journal for ERRORs (expected: 0); read last 50 lines of mm-decisions log; "
        "read today's Telegram digest.<br/>"
        "&nbsp;&nbsp;On any halt-sentinel trip: do NOT remove without understanding the cause (read the reason "
        "field in the sentinel JSON).<br/>"
        "&nbsp;&nbsp;On any Telegram heartbeat-miss alert: SSH in, check CLOB connectivity, "
        "investigate before restart.<br/>"
        "&nbsp;&nbsp;At T+24h: run <font name='DejaVuMono'>scripts/research/mmb_soak_audit.py --days 1</font>; send me the JSON.<br/>"
        "&nbsp;&nbsp;At T+7d: run <font name='DejaVuMono'>scripts/research/mmb_soak_audit.py --days 7 --gate</font>; we make the call together.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────
    # APPENDIX
    # ──────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Appendix A — source files cited", s["h1"]))
    sources = [
        [_pcell("File / location", bold=True), _pcell("Used in", bold=True)],
        [_pcell("design/S.1-market-maker-bot.md"), _pcell("§3, §4 — strategy design + signature_type=2 lock")],
        [_pcell("design/j7_priors.{json,md}"), _pcell("§3.1, §8 — bonereaper priors anchor + Kelly math")],
        [_pcell("src/polymarket_bot/strategies/market_maker.py"), _pcell("§3, §4.2, §8 — RiskCaps + LadderPlanner")],
        [_pcell("src/polymarket_bot/strategies/j7_priors.py"), _pcell("§8 — Kelly multiplier + bet_size implementation")],
        [_pcell("scripts/run_mm_live.py"), _pcell("§4.2 — VPS entrypoint + preflight gates")],
        [_pcell("scripts/mm_set_allowance.py"), _pcell("§4.1, §10 — USDC.e allowance + audit trail")],
        [_pcell("scripts/research/mmb_g11_probes.py"), _pcell("§9 R3 — empirical fee/cancel-latency/rate-limit probes")],
        [_pcell("scripts/research/mmb_soak_audit.py"), _pcell("§10 — Day-1 + Day-7 audit harness")],
        [_pcell("runbooks/OPERATOR_HANDOFF_PHASE_S.md"), _pcell("§10 — deploy procedure + Day-7 gate criteria")],
        [_pcell("runbooks/research/mmb-deep-edge-audit-2026-05-20.md"),
         _pcell("§3.2-3.4, §6, §7 — 4 edges + projection math + §5 honest framing")],
        [_pcell("runbooks/research/mmb-backtest-2026-05-20.md"), _pcell("§5 — n=21,633 sim backtest")],
        [_pcell("runbooks/research/bonereaper-microstructure-30d-2026-05-08.md"),
         _pcell("§3.1 — n=306,966 priors derivation")],
        [_pcell("runbooks/research/bonereaper-spot-vs-book-30d-2026-05-08.md"),
         _pcell("§3.1 — aligned-WR analysis")],
        [_pcell("memory/checkpoint_phase_{J,K,M,N,O,P}.md"), _pcell("§2 — directional bot failure narrative")],
        [_pcell("memory/checkpoint_phase_S_session_{1,2,3,4,5}.md"),
         _pcell("§3, §4 — Phase S session-by-session progression")],
        [_pcell("memory/project_decisions.md"),
         _pcell("§7.1 (decision #12 HW wallet trigger), §3.1 (#22 carve-out from #19)")],
        [_pcell("memory/project_phase_S_metamask_wallet_topology.md"),
         _pcell("§4.1 — MetaMask + Safe proxy choice")],
        [_pcell("pdfs/PHASE_N_FORENSIC_AUDIT.pdf"), _pcell("§2.4 — Phase N forensic audit standalone")],
        [_pcell("pdfs/PHASE_G_EDGE_DISCOVERY.pdf"), _pcell("§2.6 — Phase G zero-edge finding")],
        [_pcell("state/research/bonereaper/weekly_trades_2026-05-19.json"),
         _pcell("§3.2, §3.3 — fresh weekly n=21,633")],
    ]
    story.append(_table(sources, col_widths=[105 * mm, 65 * mm]))
    story.append(Spacer(0, 10))
    story.append(Paragraph(
        "<b>Document provenance:</b> generated 2026-05-20 by <font name='DejaVuMono'>pdfs/build_phase_S_mmb_overview_pdf.py</font> "
        "from <font name='DejaVuMono'>scripts/research/phase_S_mmb_overview_charts.py</font> output. Reproducible: "
        "<font name='DejaVuMono'>uv run --with matplotlib python scripts/research/phase_S_mmb_overview_charts.py</font> then "
        "<font name='DejaVuMono'>uv run --with reportlab python pdfs/build_phase_S_mmb_overview_pdf.py</font>.",
        s["small"]))

    doc.build(story)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    build()
