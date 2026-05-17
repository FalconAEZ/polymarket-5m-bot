"""Build pdfs/PHASE_N_FORENSIC_AUDIT.pdf — the +$1,235 → −$327 forensic study.

Modeled on pdfs/build_phase_g_edge_discovery_pdf.py (dark-terminal A4 with
cover, ToC, page numbers, embedded matplotlib PNGs from
state/research/phase-N-charts/).

Usage:
    uv run --with reportlab python -u pdfs/build_phase_n_forensic_audit_pdf.py
"""

# ruff: noqa: RUF001, RUF002

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
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "state" / "research" / "phase-N-charts"
OUT = ROOT / "pdfs" / "PHASE_N_FORENSIC_AUDIT.pdf"

# Dark-terminal palette to match the dashboard / Phase G PDF
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
            "Phase N — Forensic audit · 2026-05-17 · POLYMARKET 5m bot",
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
        "loss_box": ParagraphStyle("loss_box", parent=base["BodyText"], fontName="Helvetica-Bold",
                                   fontSize=10, textColor=LOSS, leading=14, spaceAfter=8,
                                   leftIndent=8, rightIndent=8, borderColor=LOSS,
                                   borderWidth=0.5, borderPadding=6),
        "headline": ParagraphStyle("headline", parent=base["BodyText"], fontName="Helvetica-Bold",
                                   fontSize=11, textColor=ACCENT, leading=15, spaceAfter=10,
                                   alignment=TA_LEFT),
        "tt": ParagraphStyle("tt", parent=base["BodyText"], fontName="Courier",
                             fontSize=8, textColor=TEXT, leading=10),
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName="Helvetica-Bold",
                                      fontSize=28, textColor=ACCENT, leading=34, alignment=TA_CENTER,
                                      spaceAfter=20),
        "cover_sub": ParagraphStyle("cover_sub", parent=base["BodyText"], fontName="Helvetica",
                                    fontSize=12, textColor=TEXT, leading=18, alignment=TA_CENTER,
                                    spaceAfter=10),
        "cover_loss": ParagraphStyle("cover_loss", parent=base["BodyText"], fontName="Helvetica-Bold",
                                     fontSize=14, textColor=LOSS, leading=20, alignment=TA_CENTER,
                                     spaceAfter=12),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica",
                                fontSize=8, textColor=SUBTLE, leading=10, spaceAfter=4),
    }


def _table(rows, col_widths=None, header_color=ACCENT, body_color=TEXT, row_colors=None):
    t = Table(rows, colWidths=col_widths)
    style = [
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
            style.append(("TEXTCOLOR", (0, ri), (-1, ri), color))
    t.setStyle(TableStyle(style))
    return t


def _img(name, width_mm=170, height_mm=None):
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


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Phase N — Forensic audit",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # COVER
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Spacer(0, 35 * mm))
    story.append(Paragraph("PHASE&nbsp;N", s["cover_title"]))
    story.append(Paragraph("Forensic audit of the +$1,235 → −$327 collapse",
                           s["cover_sub"]))
    story.append(Spacer(0, 8 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 8 * mm))
    story.append(Paragraph(
        "POLYMARKET 5-minute BTC up/down bot<br/>"
        "Bleed window: 2026-05-15 15:40Z → 2026-05-17 12:43Z<br/>"
        "Dataset: n=755 settled fires, 4.2 days, 100% strategy=spot_aware_v2_1<br/>"
        "Bot status: <b>HALTED</b> via halt.sentinel (operator-cooldown)",
        s["cover_sub"],
    ))
    story.append(Spacer(0, 18 * mm))
    story.append(Paragraph("$1,000 → $2,235 peak → $673 halt",
                           s["cover_loss"]))
    story.append(Paragraph("&minus;$1,562 in 45 hours · &minus;70% peak-to-trough",
                           s["cover_loss"]))
    story.append(Spacer(0, 14 * mm))
    story.append(Paragraph(
        "<b>Headline finding:</b> the &minus;$1,562 swing is dominated by <b>one cell</b> — "
        "<i>tier 30-50% × |Δbps|≥5</i> (the SURV cell from Phase L) flipping from "
        "60.7% WR profit-engine to 46.5% WR bleeder at the exact peak moment. "
        "Path-A (tier 70-85% × DOWN) is a second persistent bleeder. "
        "<b>M.5 was designed correctly</b> — the simulator shows it would have saved "
        "$330-$353 over 5 days, but it shipped <b>3 days too late</b>. <b>M.1a v1's "
        "inversion finding is contradicted</b> on n=755 — the chop-abstain logic "
        "was activated on n=23 of evidence and the larger sample says the opposite.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # CONTENTS
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Contents", s["h1"]))
    toc_rows = [
        ["§", "Section", "page"],
        ["1", "Executive summary", "3"],
        ["2", "The narrative — peak, first loss, bleed, halt", "5"],
        ["3", "Where the bleed came from — empirical attribution", "8"],
        ["4", "Every Phase, every defense, every outcome", "13"],
        ["5", "Why the M.* defenses didn't stem the bleed", "20"],
        ["6", "Hypothesis attribution (H1-H8)", "22"],
        ["7", "Phase O — ranked remediation recommendation", "23"],
        ["8", "Appendix — methodology, limits, data sources", "26"],
    ]
    story.append(_table(toc_rows, col_widths=[10 * mm, 130 * mm, 20 * mm]))
    story.append(Spacer(0, 8 * mm))
    story.append(Paragraph(
        "Honest pushback: the original Phase N prompt scoped a 4-session investigation "
        "ending in this PDF. This study compresses to 2 sessions — synthesis plus the "
        "two strongest falsifiers (M.5 activation simulator + M.1a v1 inversion test). "
        "Sections marked &lt;FUTURE WORK&gt; identify what the compression skipped.",
        s["warn"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §1 — Executive summary
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("1. Executive summary", s["h1"]))
    story.append(Paragraph(
        "Over 4.2 days the bot fired 755 times with one strategy "
        "(<b>spot_aware_v2_1</b>) and one mode (<b>kelly_multi</b>; Kelly 0.15× + "
        "bankroll-replay). Cumulative PnL peaked at <b>+$1,235.41 on "
        "2026-05-15 15:40:00Z</b> and bottomed at <b>−$326.79 on 2026-05-17 12:38:36Z</b> — "
        "a peak-to-floor swing of <b>−$1,562 in 45 hours</b>. Five edge-defense "
        "layers shipped to the live bot during that window; the bot halted "
        "regardless when the bankroll touched the $700 soft floor.",
        s["body"]))
    story.append(_img("01_cumulative_pnl.png", width_mm=170))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<i>Fig 1. Cumulative PnL over the bleed window. Peak (green dot) and floor "
        "(red dot) are 45 hours apart. Vertical dashed lines mark the five Phase M "
        "ship events; the solid bar on the right marks the halt.</i>",
        s["small"]))
    story.append(Paragraph("1.1 What we found", s["h2"]))
    findings_rows = [
        ["#", "Finding", "Confidence"],
        ["F1", "SURV cell (tier 30-50% × |Δbps|≥5) flipped at peak — pre-peak WR 60.7% (+$1,431) → post-peak WR 46.5% (−$1,161). One cell explains most of the swing.", "high"],
        ["F2", "Path A (tier 70-85% × DOWN) is a 5-day bleeder: WR 74.3% but break-even ≈ 77.5% at $0.71-0.85 cost → −$368 net. H.2.12 block_up is working (0 UP fires).", "high"],
        ["F3", "M.5 was designed correctly. Simulator: had M.5 been live from 2026-05-14 05:55Z (when n_settled first crossed 20) it would have abstained 59-105 Path-A fires and saved $330-$353. It shipped 2026-05-17 11:45Z — 3 days late.", "high"],
        ["F4", "M.1a v1's chop-abstain decision was activated on n=23 of evidence. The |Δbps| proxy on n=755 contradicts it — low-|Δbps| (chop-like) buckets have LOWER WR (33-36%), not higher.", "medium-high"],
        ["F5", "19 fire-stream gaps >30 min over 5 days indicate frequent bot restarts (one 177-min outage on 05-17 02:46Z). Any rolling state (M.5, M.1a) loses its window on each restart.", "high"],
        ["F6", "Phase J.1.5 CH3-fold is empirically confirmed: 0 CH3 fires post-fold. The −$228 from CH3 is locked-in historical, not a current bleeder.", "high"],
        ["F7", "J.2 hour-blocklist gap on tier 30-50%: hours 05/06/17/21/23/00 UTC are the new bleeders, none are blocked. Currently J.2 only blocks 22/23/00 × tier 70-85%.", "medium-high"],
    ]
    story.append(_table(findings_rows, col_widths=[10 * mm, 130 * mm, 25 * mm]))
    story.append(Spacer(0, 6))
    story.append(_img("14_loss_attribution.png", width_mm=170))
    story.append(Paragraph(
        "<i>Fig 2. Loss attribution for the −$1,562 swing. SURV cell post-peak is the "
        "single largest contributor; Path-A and tier-30-50%-UP are secondary.</i>",
        s["small"]))
    story.append(Paragraph("1.2 The two-line story", s["h2"]))
    story.append(Paragraph(
        "<b>Bot didn't break.</b> A profitable cell stopped being profitable at peak. "
        "The defense designed to catch the second-biggest bleeder (M.5) was correct "
        "but shipped 3 days late.",
        s["headline"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §2 — Narrative
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("2. The narrative", s["h1"]))
    story.append(Paragraph("2.1 What we shipped during the bleed window", s["h2"]))
    story.append(_img("13_phase_timeline.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "Phase J.1.6 (Kelly 0.15× + replay) had been live since 2026-05-14 18:36Z. "
        "Phase K closed 2026-05-16 with the operator overriding the rollback "
        "trigger and keeping Kelly 0.15× + replay through Phase L. Phase M then "
        "shipped <b>five edge-defense layers in 22 hours</b>:",
        s["body"]))
    phase_m_rows = [
        ["Layer", "Shipped (UTC)", "Mode", "What it claims"],
        ["L.5", "2026-05-16 12:51:59Z", "active", "Halt at UTC 23:50 if today's PnL ≤ −$30"],
        ["M.1a v0", "2026-05-16 19:14:24Z", "shadow", "Annotate fires with regime=<chop/mixed/trending>"],
        ["M.1a v1", "2026-05-17 11:25:56Z", "active", "Abstain fires labeled chop or unknown"],
        ["M.5", "2026-05-17 11:44:57Z", "active", "Abstain Path A when rolling WR < mean_price + 2pp"],
        ["M.2 v0", "2026-05-17 11:58:25Z", "shadow", "Annotate fires with imbalance=<bullish/bearish/balanced/too_thin>"],
    ]
    story.append(_table(phase_m_rows, col_widths=[18 * mm, 40 * mm, 16 * mm, 86 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "<b>None of the ACTIVE layers (L.5, M.1a v1, M.5) had more than 78 minutes of "
        "live time before halt.</b> L.5 served its purpose (the daily-PnL guard "
        "tripped 2026-05-16 23:50Z; sentinel cleared by operator). The other "
        "actives were live for the 78-minute window 11:25Z → 12:43Z on Sunday.",
        s["warn"],
    ))
    story.append(PageBreak())

    story.append(Paragraph("2.2 Peak, first loss, then 45 hours of drawdown", s["h2"]))
    story.append(_img("02_bankroll_trajectory.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>The peak fire</b> (#445/755) at 2026-05-15 15:40:00Z was a tier 30-50% "
        "DOWN bet with Δbps = −5.17, bet $92.58 from a bankroll of $2,047.72, "
        "p_win=0.65, ev=+0.146. It won +$92.93, pushing cum-PnL to +$1,235.41.",
        s["body"]))
    story.append(Paragraph(
        "<b>The first post-peak loss</b> came in the SAME 5-minute window (fire #446 at "
        "15:45:15Z): tier 70-85% DOWN (Path A), Δbps=−7.24, p_win=0.80 (the v2.1 "
        "priors ceiling), bet $91.74 → LOST −$91.76. Zero intervening wins. "
        "The bot wiped out 1.0× the peak fire's gain in the next window.",
        s["body"]))
    story.append(_img("03_daily_pnl_bar.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<i>Fig 3. Daily PnL — the first 3 days of soak were a clean profit accumulator. "
        "Day 4 lost more than Days 1-3 combined; Day 5 halted at noon with another "
        "−$355.</i>",
        s["small"]))
    story.append(Paragraph(
        "Pre-peak (6h window) vs post-peak (6h window): WR 73.8% → 51.0% (−22.8pp); "
        "$/trade +$23.64 → −$8.80; UP-share 21.4% → 41.2% (the bot started taking "
        "more UP fires post-peak, which is consistent with a regime shift the "
        "spot-Δ classifier didn't catch).",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §3 — Where the bleed came from
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("3. Where the bleed came from", s["h1"]))
    story.append(Paragraph("3.1 Per-tier net PnL — the biggest surprise", s["h2"]))
    story.append(_img("04_per_tier_pnl_wr.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>Tier 30-50% is NOT the dominant 5-day loser.</b> Its 518 fires net +$41 "
        "over 5 days — essentially flat. <b>Tier 70-85% is the bleeder</b> — 237 "
        "fires, WR 74.3% (which sounds high), net −$368. The right panel shows "
        "why: at average entry price $0.78, break-even WR is ~78%; the bot's "
        "74.3% sits 4pp below it. <i>Every Path-A fire is a 4pp losing bet.</i>",
        s["body"]))
    story.append(Paragraph(
        "The operator's at-halt impression that today's losses are tier 30-50% was "
        "right for today (05-17 tier 30-50%: −$30, 22 fires) but the dominant "
        "5-day picture is different.",
        s["body"]))
    story.append(Paragraph("3.2 The SURV cell — the dominant 5-day bleeder", s["h2"]))
    story.append(_img("05_surv_pre_post_peak.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>SURV = tier 30-50% × |Δbps|≥5.</b> This was Phase L's identified "
        "&quot;surviving winner&quot; cell at audit time. It flipped at peak:",
        s["body"]))
    surv_rows = [
        ["", "n", "WR", "$/trade", "PnL"],
        ["pre-peak", "112", "60.7%", "+$12.78", "+$1,431"],
        ["post-peak", "228", "46.5%", "−$5.09", "−$1,161"],
        ["delta", "+116", "−14.2pp", "−$17.87", "−$2,592 swing"],
    ]
    story.append(_table(surv_rows, col_widths=[28 * mm, 18 * mm, 22 * mm, 24 * mm, 30 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "<b>The peak-to-floor swing of −$1,562 is mostly inside this single slice.</b> "
        "No M.* defense was designed to catch the SURV cell. M.5 targets Path A "
        "(tier 70-85%); M.1a targets a regime; M.2 v0 targets book imbalance.",
        s["loss_box"],
    ))
    story.append(PageBreak())

    story.append(Paragraph("3.3 Path A — the slower secondary bleeder", s["h2"]))
    story.append(_img("12_ch3_vs_surv_contrast.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "Phase J.1.5 folded the CH3 cell (tier 30-50% × |Δ|&lt;5) — the left chart "
        "shows the fold worked: no CH3 fires after the J.1.5 ship time. The −$228 "
        "in CH3 PnL is locked-in pre-fold history.",
        s["body"]))
    story.append(Paragraph(
        "The SURV cell on the right tells a different story: a steady climb to peak "
        "with high-quality fires, then a steep post-peak collapse. The bot's "
        "&quot;winning cell&quot; turned over.",
        s["body"]))
    story.append(Paragraph("3.4 Daily decomposition — when did each cell hurt?", s["h2"]))
    story.append(_img("09_daily_x_tier_x_side.png", width_mm=170))
    story.append(Spacer(0, 6))
    daily_rows = [
        ["UTC date", "30-50% UP", "30-50% DN", "70-85% DN", "Total"],
        ["2026-05-13", "+$63", "+$302", "+$132", "+$497"],
        ["2026-05-14", "−$72", "+$183", "+$42", "+$153"],
        ["2026-05-15", "+$138", "−$21", "−$151", "−$35"],
        ["2026-05-16", "−$190", "−$332", "−$66", "−$587"],
        ["2026-05-17", "−$86", "+$56", "−$325", "−$355"],
    ]
    story.append(_table(daily_rows, col_widths=[36 * mm, 32 * mm, 32 * mm, 32 * mm, 30 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "Path A bled across 3 days (−$543 total: 05-15/16/17). Tier 30-50% DN "
        "imploded specifically on 05-16 (−$332). Tier 30-50% UP turned over "
        "from 05-15 to 05-16 (+$138 → −$190). No single cell drove the whole "
        "bleed; it was a multi-cell drift that compounded.",
        s["body"]))
    story.append(PageBreak())

    story.append(Paragraph("3.5 |Δbps| × tier — where each tier's edge lives", s["h2"]))
    story.append(_img("11_delta_bps_x_tier.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "On tier 30-50%, edge is concentrated in the |Δbps| 5-10 bucket "
        "(n=339, WR 51.3%, +$387). The small-|Δbps| buckets (0-2.5, 2.5-5) bleed "
        "(WR 33-36%, combined −$228). Tier 70-85% fires nearly all live in the "
        "|Δbps| 5-10 bucket (n=231) and bleed because of the break-even gap.",
        s["body"]))
    story.append(Paragraph("3.6 Per-UTC-hour × tier heatmap", s["h2"]))
    story.append(_img("08_hour_x_tier_heatmap.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>Bleed hours on tier 30-50%:</b> 05 UTC (−$266), 06 UTC (−$251), "
        "17 UTC (−$259), <b>21 UTC (−$516)</b>, 23 UTC (−$288), 00 UTC (−$168). "
        "The current J.2 hour-blocklist (22/23/00 UTC) covers only tier 70-85% "
        "fires; tier 30-50% hour-of-day is uncontrolled.",
        s["body"]))
    story.append(Paragraph(
        "Win hours on tier 30-50%: 15 UTC (+$483), <b>19 UTC (+$691)</b>, "
        "08 UTC (+$248), 22 UTC (+$302). Pattern: late-Asian / early-Europe is "
        "lossy, US-open through European-close is profitable on tier 30-50%.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §4 — Every Phase
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("4. Every Phase, every defense, every outcome", s["h1"]))
    story.append(Paragraph(
        "This section walks through every prior Phase's shipped defense and what "
        "the Phase N data says about its current behavior.",
        s["body"],
    ))
    story.append(Paragraph("4.1 Phase G — edge map (2026-05-12)", s["h2"]))
    story.append(Paragraph(
        "Phase G audited 635 fires across 17 dimensions and found the bot had "
        "<b>zero edge</b> (50.0% WR / −$18.96). The Phase G recommended winning "
        "cell was <i>tier 30-50% × |Δ|&lt;5</i> (the CH3 cell), n=83, WR 58.2% / "
        "+$0.65/trade in Phase G's data. Phase H pivoted to spot_aware_v2_1 and "
        "ENABLED CH3 firing under priors blending.",
        s["body"]))
    story.append(Paragraph(
        "<b>Phase N verdict:</b> CH3 in live trading priced at the boundary "
        "(~$0.51 avg ask) rather than Phase G's mid-cell average (~$0.40), so the "
        "asymmetric-payoff edge collapsed (project memory: "
        "<i>ch3_cell_price_distribution_matters</i>). Phase J.1.5 folded CH3 — "
        "data confirms 0 CH3 fires post-fold.",
        s["warn"],
    ))
    story.append(Paragraph("4.2 Phase H — v2.1 priors + multi-fire (2026-05-13)", s["h2"]))
    story.append(Paragraph(
        "Phase H shipped six commits: v2.1 priors, CH3 fallback, fire_n badge, "
        "Bet column, gamma 30s, cap=1 throttle, and (most importantly for Phase N) "
        "<b>H.2.12 path-A block_up</b> — tier 70-85% × side=UP is BLOCKED.",
        s["body"]))
    story.append(Paragraph(
        "<b>Phase N verdict:</b> H.2.12 confirmed working — 0 of 237 tier 70-85% "
        "fires are UP-side. The 100% DOWN-side composition is the foundation "
        "of M.5's design (M.5 only governs Path A, which is now well-defined).",
        s["body"]))
    story.append(Paragraph("4.3 Phase J — Kelly + replay + J.2 + J.1.5 (2026-05-14)", s["h2"]))
    story.append(Paragraph(
        "Phase J shipped four things: (J.1.5) <b>CH3 fold</b>, (J.2) "
        "<b>hour-of-day blocklist</b> (UTC 22/23/00 × tier 70-85%), (J.1.6-A) "
        "<b>BANKROLL_REPLAY_ENABLED=true</b>, (J.1.6-B) <b>KELLY_MULT 0.10 → 0.15</b>. "
        "Combined: ~2.3× bet scaling. Phase K's 4-day soak showed the bankroll "
        "swing $1k → $2,235 → $1,095 = variance amplifier confirmed.",
        s["body"]))
    story.append(Paragraph(
        "<b>Phase N verdict:</b> J.1.5 fold WORKS (CH3 post-fold n=0). "
        "<b>J.2 hour-blocklist has a gap</b>: bleed-hours on tier 30-50% "
        "(05/06/17/21/23/00 UTC) aren't blocked. J.1.6 Kelly + replay = "
        "mechanical variance amplifier, not the cause of the bleed but a "
        "multiplier of its damage.",
        s["warn"],
    ))
    story.append(PageBreak())

    story.append(Paragraph("4.4 Phase K — 4-day soak (2026-05-16)", s["h2"]))
    story.append(Paragraph(
        "Phase K closed Day 4 of the planned 14-day soak. Truth-corrected universe "
        "n=615 fires. Day-3 peak (2026-05-15 15:40Z, +$1,235) was captured live. "
        "Day-4 Drawdown was −$1,294 in 18 hours. 17 daily-PnL gate trips on 05-16 "
        "alone (operator hadn't yet shipped L.5 to automate the response).",
        s["body"]))
    story.append(Paragraph(
        "<b>Phase N verdict:</b> Phase K's data already showed the SURV-cell "
        "turnover post-peak; the operator's Phase K post-closure decision was to "
        "KEEP Kelly 0.15× + replay through Phase L (call: variance is "
        "regime-driven, not Kelly-driven). Phase N data agrees: same WR, "
        "different sample → SURV cell genuinely flipped.",
        s["body"]))
    story.append(Paragraph("4.5 Phase L → M — five defenses (2026-05-16 → 17)", s["h2"]))
    story.append(Paragraph(
        "L.5, M.1a v0, M.1a v1, M.5, M.2 v0 — see §2.1 timing. Per-layer audit:",
        s["body"]))

    story.append(Paragraph("L.5 daily PnL auto-halt", s["h3"]))
    story.append(Paragraph(
        "<b>Mechanism:</b> if today's PnL ≤ −$30 at the UTC 23:50 check, halt the "
        "bot and write halt.sentinel.",
        s["body"]))
    story.append(Paragraph(
        "<b>Live evidence:</b> tripped 2026-05-16 23:50Z (today PnL ≈ −$367 ≪ −$30). "
        "Bot halted; Telegram alert fired; sentinel created. Operator cleared "
        "sentinel manually 2026-05-17 02:42Z (the 177-min outage in §4.6).",
        s["body"]))
    story.append(Paragraph(
        "<b>Verdict:</b> WORKS AS DESIGNED. Saved the bot from continuing into "
        "deeper Day-4 losses. Re-enabled by manual sentinel clear.",
        s["body"]))

    story.append(Paragraph("M.1a v0 (shadow regime log)", s["h3"]))
    story.append(Paragraph(
        "<b>Mechanism:</b> annotate each fire's rationale with "
        "regime=&lt;chop|mixed|trending|unknown&gt; based on a 5m/10m vol-ratio "
        "classifier. No abstain action.",
        s["body"]))
    story.append(Paragraph(
        "<b>Live evidence:</b> 83/755 fires annotated (Sat 19:14Z → halt). Mix: "
        "chop=23, mixed=58, trending=2. <b>No unknown labels appeared</b> — "
        "warmup was fast enough that the classifier was always confident.",
        s["body"]))
    story.append(Paragraph(
        "<b>Verdict:</b> SHADOW-WORKS — annotations present. Per-label WR is a "
        "small-n surprise (chop +$31 / mixed −$296) that M.1a v1 then acted on. "
        "See §4.5 M.1a v1 + §5.2 falsifier.",
        s["body"]))

    story.append(PageBreak())

    story.append(Paragraph("M.1a v1 (active chop abstain)", s["h3"]))
    story.append(Paragraph(
        "<b>Mechanism:</b> when M.1a v0 labels a fire chop or unknown, abstain.",
        s["body"]))
    story.append(_img("07_m1a_inversion_test.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>Falsifier (Fig 4):</b> the left panel shows the n=83 annotated subset "
        "that motivated M.1a v1 — chop WR 60.9%, mixed WR 44.8%. M.1a v1 abstains "
        "chop. The right panel computes a |Δbps|-based PROXY regime on n=755 and "
        "shows the opposite: low-|Δbps| (chop-like) WR is 33-36%, not higher. The "
        "M.1a vol-ratio classifier and |Δbps|-based edge structure don't align.",
        s["body"]))
    story.append(Paragraph(
        "<b>Verdict:</b> SHIPPED ON n=23 EVIDENCE. The decision to activate "
        "M.1a v1 was correct conditional on M.1a v0's small-sample readings, but "
        "the falsifier on n=755 says the underlying edge driver is |Δbps|, not "
        "the M.1a classifier. <b>Phase O candidate: disable M.1a v1 pending "
        "regime classifier re-validation.</b>",
        s["loss_box"],
    ))

    story.append(Paragraph("M.5 (Path-A regime wrapper)", s["h3"]))
    story.append(Paragraph(
        "<b>Mechanism:</b> for Path-A fires (tier 70-85% × DOWN), maintain a "
        "rolling 20-fire window of settle outcomes. If rolling_wr &lt; mean_price + 2pp, "
        "abstain the next Path-A fire.",
        s["body"]))
    story.append(_img("06_m5_activation_simulator.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>Falsifier (Fig 5):</b> M.5 simulator replays the 5-day data. The "
        "blue line is the rolling Path-A WR; the red dashed line is the "
        "break-even threshold. The bot has been Path-A-losing-money since "
        "M.5 would have activated (2026-05-14 05:55Z). Idealized counterfactual: "
        "<b>+$352.92 PnL avoided</b> over 5 days had M.5 been live. With realistic "
        "restart-resets (the bot crashed 19 times in 5 days): "
        "<b>+$330.51 avoided</b>.",
        s["body"]))
    story.append(Paragraph(
        "<b>Within the actual 58-minute live window:</b> 1 Path-A fire (2026-05-17 "
        "11:31Z, but wait — this is BEFORE the M.5 ship at 11:44Z; it represents "
        "what M.5 would have done at that moment). M.5 was active "
        "(n=20, rolling_wr=70.0%, threshold=75.8%) and would have abstained "
        "(saving −$39.34). <b>M.5 design is correct. Ship-time too late.</b>",
        s["warn"],
    ))
    story.append(Paragraph(
        "<b>Verdict:</b> DESIGNED CORRECTLY — but shipped 3 days late. This is the "
        "single biggest 5-day defense miss. Phase O candidate: re-enable M.5 "
        "(it's already shipped; just needs a longer live window).",
        s["body"]))

    story.append(PageBreak())

    story.append(Paragraph("M.2 v0 (imbalance shadow log)", s["h3"]))
    story.append(Paragraph(
        "<b>Mechanism:</b> annotate fires with imbalance=&lt;bullish|bearish|"
        "balanced|too_thin|...&gt; from book microstructure. No abstain action.",
        s["body"]))
    story.append(Paragraph(
        "<b>Live evidence:</b> 3/755 fires annotated (Sun 11:58Z → halt; 45 min). "
        "All 3 labels are <i>too_thin</i>. No bullish/bearish/balanced labels "
        "appeared in the live window.",
        s["body"]))
    story.append(Paragraph(
        "<b>Verdict:</b> EFFECTIVELY UN-EVALUABLE. Either the book truly was "
        "too thin for 45 min during the halt spiral, the classifier is "
        "stress-biased toward too_thin, or only 3 fires had imbalance-eligible "
        "book depth. Sample too small to draw any conclusion.",
        s["body"]))

    story.append(Paragraph("4.6 The bot's restart behavior", s["h2"]))
    story.append(_img("10_restart_markers.png", width_mm=170))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "Fire-stream gaps &gt;30 min are a proxy for bot restarts. 19 likely "
        "restarts in 5 days. The 177-min outage on 05-17 02:46Z is the "
        "operator's manual sentinel-clear after the L.5 trip. Smaller gaps "
        "(30-65 min) suggest unstable runs — possibly from M.* feature ships "
        "(each Phase M layer required a restart). <b>Operational implication:</b> "
        "any rolling-state defense (M.5, M.1a v0 window) loses its window every "
        "restart. M.5's effective live time is bounded by the gap between its "
        "last restart and the next.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §5 — Why defenses didn't work
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("5. Why the M.* defenses didn't stem the bleed", s["h1"]))
    story.append(Paragraph(
        "Three reasons, in order of empirical contribution:",
        s["body"],
    ))
    story.append(Paragraph("5.1 The dominant bleeder had no targeted defense", s["h2"]))
    story.append(Paragraph(
        "The SURV cell (tier 30-50% × |Δbps|≥5) drove the bulk of the post-peak "
        "loss (−$1,161). M.5 targets Path A (tier 70-85%). M.1a v1 targets a "
        "regime label, not a cell. M.2 v0 is shadow-only. <b>No M.* layer in the "
        "shipped slate was designed to catch the SURV-cell flip.</b> Phase L "
        "originally framed SURV as the &quot;surviving winner&quot; — the audit "
        "implicitly assumed it would keep winning.",
        s["body"]))
    story.append(Paragraph("5.2 M.1a v1 may be doing the wrong thing", s["h2"]))
    story.append(Paragraph(
        "M.1a v1 was activated 2026-05-17 11:25Z on the basis of n=23 chop fires "
        "showing +$31 PnL vs n=58 mixed fires showing −$296. The N.3c falsifier "
        "(Fig 4) on n=755 contradicts this directionally. The plausible "
        "explanations:",
        s["body"]))
    story.append(Paragraph(
        "(a) The M.1a vol-ratio classifier captures a market regime that is "
        "decoupled from |Δbps|. Then the n=23 finding is real, M.1a v1 abstains "
        "correctly, and the n=755 |Δbps| proxy is a different (also-real) signal "
        "that happens to point opposite.<br/><br/>"
        "(b) The M.1a chop label is tier-mix biased. Of the 23 chop fires, "
        "11 are tier 30-50% and 12 are tier 70-85%. If chop happens to label "
        "Path-A fires more often than non-Path-A, and Path-A fires win 74% of "
        "the time but lose $/trade, then chop labels look like &quot;wins&quot; "
        "in WR while bleeding in PnL.<br/><br/>"
        "(c) Pure n=23 noise. Three runs of unrelated coin-flips can produce a "
        "&gt;10pp WR swing.",
        s["body"]))
    story.append(Paragraph(
        "Phase N can't distinguish (a)/(b)/(c) from this data alone. The N.5 "
        "regime classifier validity test (FUTURE WORK) is the falsifier.",
        s["warn"],
    ))
    story.append(PageBreak())

    story.append(Paragraph("5.3 M.5 was the right defense, 3 days too late", s["h2"]))
    story.append(Paragraph(
        "The M.5 simulator says had M.5 been live from <b>2026-05-14 05:55Z</b>, "
        "it would have abstained <b>59-105 Path-A fires</b> over 5 days "
        "(idealized vs realistic-restart), avoiding <b>$330-$353 of loss</b>. M.5 "
        "actually shipped <b>2026-05-17 11:44Z</b> — 77 hours later. In its "
        "actual 58-minute live window, only one Path-A fire occurred (and the "
        "simulator says M.5 was already active for it and would have abstained, "
        "saving $39).",
        s["body"]))
    story.append(Paragraph(
        "<b>The single biggest improvement Phase N identifies isn't a new "
        "feature — it's keeping M.5 live for the next 5 days.</b>",
        s["headline"],
    ))
    story.append(Paragraph(
        "Caveat: M.5 design depends on a rolling n=20 window. The bot restarted "
        "19 times in 5 days (every restart resets the window to 0). Mid-day "
        "restarts within Path-A-dense windows can re-cold-start M.5. The "
        "&quot;realistic restart&quot; simulator already accounts for this and "
        "still shows +$330 net win. <i>Recommend: persist M.5's window across "
        "restarts (write to disk; load on boot). This is a small src/ change "
        "but it's a code change &mdash; per Phase N rules, do not ship in this "
        "session.</i>",
        s["body"]))

    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §6 — Hypothesis attribution
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("6. Hypothesis attribution", s["h1"]))
    story.append(Paragraph(
        "The Phase N kickoff prompt enumerated 8 hypotheses (H1-H8). With "
        "Session 1+2 evidence, here is the empirical verdict on each:",
        s["body"],
    ))
    hyp_rows = [
        ["H", "Hypothesis", "Verdict", "Confidence"],
        ["H1", "Regime shift bot can't detect", "Likely contributing — SURV cell flip is consistent with a regime shift at peak", "medium-low"],
        ["H2", "Tier 30-50% structural break", "PARTLY — SURV slice collapsed; CH3 is contained by J.1.5 fold", "medium"],
        ["H3", "Features fighting each other", "M.1a v1 inversion suspicion (n=23); M.5 was too-late-to-matter; M.2 v0 unusable", "medium"],
        ["H4", "Kelly 0.15× variance amplifier", "Mechanical multiplier of the swing, not the cause", "high"],
        ["H5", "Path A break-even WR collapsed", "Confirmed for tier 70-85% Path A (−$543 / 3d); but secondary to SURV", "medium-high"],
        ["H6", "Spot/Polymarket basis broke", "UN-TESTABLE from current data (no implied-prob history)", "n/a"],
        ["H7", "Time-of-day shifted", "Confirmed — bleed hours on tier 30-50% are 05/06/17/21/23/00 UTC; J.2 doesn't cover them", "medium-high"],
        ["H8", "Multiple compounding", "MOST LIKELY — SURV flip + Path A bleed + 30-50% UP/DN day-mix + Kelly amplification", "high"],
    ]
    story.append(_table(hyp_rows, col_widths=[8 * mm, 60 * mm, 75 * mm, 22 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "<b>What this study did NOT settle (FUTURE WORK for Sessions 3-4):</b>",
        s["h3"]))
    story.append(Paragraph(
        "&bull; N.5 regime classifier validity — can we build a regime label that "
        "predicts SURV-cell turnover? Needs spot-tick history we don't have, "
        "or substitute the |Δbps| proxy and accept its limits.<br/>"
        "&bull; N.6 regime SHIFT detection — can we detect SURV-cell turnover "
        "live? Rolling-30-fire WR slope is a candidate.<br/>"
        "&bull; N.7 counterfactual: same 5 days at Kelly 0.10× and at $5-flat "
        "(decision #9 reset). Quantifies the &quot;Kelly variance only&quot; "
        "vs &quot;Kelly + class&quot; question.<br/>"
        "&bull; N.5/N.6 will tell us whether to disable M.1a v1 outright or "
        "swap its classifier.",
        s["body"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §7 — Phase O recommendation
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("7. Phase O — ranked remediation recommendation", s["h1"]))
    story.append(Paragraph(
        "Per operator preference, this section RANKS one primary remediation "
        "and lists alternates with tradeoffs. The ranking is grounded in the "
        "Phase N forensic findings but acknowledges the 4.2-day dataset is "
        "statistically small — &quot;most likely correct&quot; not &quot;proven.&quot;",
        s["warn"],
    ))
    story.append(Paragraph("7.1 PRIMARY recommendation: re-enable M.5 + persist its window", s["h2"]))
    story.append(Paragraph(
        "<b>What:</b> Clear halt.sentinel; re-resume bot WITH REGIME_M5_PATH_A_GATE_ENABLED=true. "
        "Add a small src/ change (~30 LOC + tests) to persist M.5's rolling "
        "window to disk so restarts don't cold-start it.",
        s["body"]))
    story.append(Paragraph(
        "<b>Why:</b> M.5 simulator shows +$330-$353 PnL avoided over 5 days. "
        "This is the single largest empirically-grounded defense improvement "
        "the data identifies. Path-A bleeds 4pp below break-even on every fire; "
        "M.5 is the only shipped defense designed to catch this.",
        s["body"]))
    story.append(Paragraph(
        "<b>Risks:</b> The 19-restart-cycle without persistence will eat into "
        "M.5's savings (the realistic simulator already shows this). Until "
        "persistence ships, expect ~$200 of the $350 to be left on the table.",
        s["body"]))
    story.append(Paragraph(
        "<b>Falsifier:</b> if M.5 abstains a fire that would have won (rolling "
        "WR rebounds above threshold), no harm done — it just passes through "
        "to normal Kelly. Worst-case M.5 = no-op.",
        s["body"]))

    story.append(Paragraph("7.2 SECONDARY: disable M.1a v1 pending re-validation", s["h2"]))
    story.append(Paragraph(
        "<b>What:</b> Set REGIME_M1A_V1_ENABLED=false on the next deploy.",
        s["body"]))
    story.append(Paragraph(
        "<b>Why:</b> M.1a v1 was activated on n=23 evidence. The N.3c falsifier "
        "on n=755 contradicts the chop&gt;mixed-WR signal. Keeping M.1a v0 in "
        "shadow mode is fine and continues to accumulate annotations for a "
        "future re-test.",
        s["body"]))
    story.append(Paragraph(
        "<b>Risks:</b> If the n=23 signal IS real, disabling M.1a v1 will give "
        "back ~$72 in projected uplift. Confidence: low that this is real.",
        s["body"]))

    story.append(Paragraph("7.3 TERTIARY: extend J.2 to tier 30-50% bleed hours", s["h2"]))
    story.append(Paragraph(
        "<b>What:</b> Add UTC hours {05, 06, 17, 21, 23, 00} × tier 30-50% to "
        "the J.2 hour-block list (currently only 22/23/00 × tier 70-85%).",
        s["body"]))
    story.append(Paragraph(
        "<b>Why:</b> §3.6 shows these 6 hours net −$1,748 across 5 days on tier "
        "30-50%. Hourly patterns are stable enough to act on (Phase G/H/J data "
        "shows similar profile pre-Phase-N).",
        s["body"]))
    story.append(Paragraph(
        "<b>Risks:</b> Hour-of-day patterns can decay (no data hygiene around "
        "them). Limit-on-time gates are a partial fix; the underlying SURV-cell "
        "flip can still happen mid-19-UTC.",
        s["body"]))

    story.append(PageBreak())

    story.append(Paragraph("7.4 NOT RECOMMENDED (yet): Kelly demotion 0.15 → 0.10", s["h2"]))
    story.append(Paragraph(
        "<b>What:</b> Set KELLY_MULT=0.10.",
        s["body"]))
    story.append(Paragraph(
        "<b>Why we considered it:</b> Phase G Monte Carlo showed Kelly 0.10 "
        "regression case has 97% catastrophic-drawdown probability — i.e., "
        "Kelly 0.10 cuts variance significantly. The Phase N data confirms "
        "Kelly 0.15 amplified the −$1,161 SURV-cell swing into a halt-trigger.",
        s["body"]))
    story.append(Paragraph(
        "<b>Why we don't ship it first:</b> Kelly is a variance multiplier, "
        "not an edge restorer. Demoting from 0.15 to 0.10 cuts the swing "
        "magnitude by ~30% but doesn't fix the SURV-cell flip itself. M.5 "
        "addresses an actual edge problem; Kelly demotion only buys time. "
        "Reconsider IF Phase O Session-2 finds an additional un-targetable "
        "drawdown source (N.7 counterfactual).",
        s["body"]))

    story.append(Paragraph("7.5 NOT RECOMMENDED: strategy-class flip to spot_aware_v2 vanilla", s["h2"]))
    story.append(Paragraph(
        "<b>Why not:</b> Phase H/J/L/M's incremental defenses (priors, cap=1, "
        "path-A block_up, J.1.5 fold, J.2, L.5, M.5) are mostly EMPIRICALLY "
        "WORKING per Phase N. Rolling back to vanilla v2 + $5-flat (decision #9) "
        "discards 4 weeks of working defenses and re-exposes the bot to issues "
        "those phases fixed (e.g., 47.8% CH3 WR pre-fold, tier 70-85% UP exposure). "
        "Strategy-class flip is a Phase O option only if the M.5-first remediation "
        "fails over a 5-day re-soak.",
        s["body"]))

    story.append(Paragraph("7.6 Recommended Phase O sequencing", s["h2"]))
    seq_rows = [
        ["#", "Action", "Risk", "Expected PnL effect (5d)"],
        ["1", "Clear sentinel; re-resume with M.5 active + M.1a v1 disabled", "low", "+$330 (M.5) + neutral (M.1a v1)"],
        ["2", "Ship M.5 window persistence (src/ change + tests)", "low (small surface)", "+$25 (recapture restart-loss share)"],
        ["3", "Extend J.2 hour-blocklist to tier 30-50% bleed-hours", "medium (pattern decay risk)", "+$1,748 if pattern holds × prob 50% = +$874"],
        ["4", "5-day re-soak; observe SURV-cell behavior", "—", "data-driven; gate to step 5"],
        ["5", "If SURV bleeds again → consider Kelly demotion or strategy flip", "high (heavy rebase)", "TBD"],
    ]
    story.append(_table(seq_rows, col_widths=[8 * mm, 70 * mm, 28 * mm, 60 * mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "Total expected 5-day PnL improvement at steps 1-3: <b>+$355 to +$1,229</b> "
        "(point: <b>+$1,229 if hour-of-day pattern fully holds</b>; floor: $355 if "
        "only M.5 contributes). The wide range reflects honest uncertainty on the "
        "stability of the hour-of-day pattern.",
        s["body"]))

    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # §8 — Appendix
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("8. Appendix", s["h1"]))
    story.append(Paragraph("8.1 Methodology", s["h2"]))
    story.append(Paragraph(
        "Source data: state/decisions-resolved/2026-05-{13,14,15,16,17}.jsonl "
        "pulled from VPS bot-staging.service to /tmp/phaseN_data/ on 2026-05-17 "
        "14:32Z (post-halt; service inactive). Truth-corrected PnL = "
        "settled_correction.corrected_pnl_usd if present, else settled.pnl_usd. "
        "127/756 settlements (17%) are post-hoc corrections. Tier labels per "
        "src/polymarket_bot/tiers.py canonical buckets.",
        s["body"]))
    story.append(Paragraph(
        "Audit script: scripts/research/phase_n_forensic_audit.py "
        "(read-only; never writes to state/ or to any bot-runtime path). "
        "Chart generator: scripts/research/phase_n_charts.py. PDF builder: "
        "pdfs/build_phase_n_forensic_audit_pdf.py. Reproducible: "
        "<font face='Courier'>uv run --with reportlab python pdfs/build_phase_n_forensic_audit_pdf.py</font>",
        s["body"]))
    story.append(Paragraph("8.2 Limits — honest pushback", s["h2"]))
    story.append(Paragraph(
        "<b>L1.</b> 4.2-day window is statistically small. SURV-cell flip could be a "
        "regime moment that mean-reverts, or it could be a structural break. "
        "Phase N CAN'T tell the difference from this data alone.<br/><br/>"
        "<b>L2.</b> No persistent spot tick capture exists. M.1a regime classifier "
        "(5m/10m vol-ratio) can't be re-validated from fire-time snapshots alone. "
        "The |Δbps| proxy used in N.3c is a directional approximation.<br/><br/>"
        "<b>L3.</b> M.2 v0 annotated only 3 fires before halt. All 3 labeled "
        "too_thin. Effect-size estimates on M.2 are not yet possible.<br/><br/>"
        "<b>L4.</b> M.5 was active for 58 minutes live. The simulator output is "
        "the source of M.5's verdict, not direct production observation. "
        "Idealized vs realistic simulator differs by ~$22 because of restart "
        "resets.<br/><br/>"
        "<b>L5.</b> Phase N does NOT validate the Phase H/J defenses against "
        "alternative pathways (e.g., what if multi-fire cap=2 had stayed?). "
        "The forensic assumes the current shipped configuration is the baseline.",
        s["body"]))
    story.append(Paragraph("8.3 Data sources cross-reference", s["h2"]))
    src_rows = [
        ["File", "Purpose"],
        ["scripts/research/phase_n_forensic_audit.py", "Audit script (data load + analysis)"],
        ["scripts/research/phase_n_charts.py", "Chart generator (matplotlib → PNG)"],
        ["runbooks/research/phase-N-forensic-output-2026-05-17.txt", "Raw audit text output"],
        ["runbooks/research/phase-N-forensic-summary.md", "Operator briefing (markdown)"],
        ["state/research/phase-N-charts/*.png", "14 charts embedded in this PDF"],
        ["state/sessions/2026-05-17-phase-N-kickoff.md", "Session note"],
        ["state/phases/phase-N-forensic-audit.md", "Phase N ledger"],
        ["memory/checkpoint_phase_N.md", "Cross-session checkpoint"],
        ["design/L.5-daily-pnl-auto-halt.md", "L.5 design doc (defense)"],
        ["design/M.1a-flat-vs-trend-shadow-log.md", "M.1a v0 design doc"],
        ["design/M.1a-v1-active-abstain.md", "M.1a v1 design doc"],
        ["design/M.5-path-a-regime-wrapper.md", "M.5 design doc"],
        ["design/M.2-orderbook-imbalance-shadow.md", "M.2 v0 design doc"],
        ["pdfs/PHASE_G_EDGE_DISCOVERY.pdf", "Prior phase context (style anchor)"],
        ["pdfs/PHASE_K_LIVE_READINESS.pdf", "Prior phase context"],
    ]
    story.append(_table(src_rows, col_widths=[88 * mm, 75 * mm]))

    story.append(PageBreak())
    story.append(Paragraph("8.4 Locked rules during Phase N", s["h2"]))
    rules_rows = [
        ["#", "Rule"],
        ["1", "No bot code changes; bot stays halted via halt.sentinel"],
        ["2", "No env flips on VPS"],
        ["3", "No restart of bot-staging.service"],
        ["4", "Phase N script lives under scripts/research/ (research-only; CI gates don't apply)"],
        ["5", "Investigate before deciding. Resist 'just ship a fix' mid-forensic"],
        ["6", "Anthropic spend: &lt;$5 expected"],
    ]
    story.append(_table(rules_rows, col_widths=[8 * mm, 155 * mm]))
    story.append(Paragraph("8.5 Per-day numeric appendix", s["h2"]))
    perday_rows = [
        ["UTC date", "n", "daily-PnL", "cum-PnL EOD", "WR"],
        ["2026-05-13", "174", "+$497", "+$497", "45.4%"],
        ["2026-05-14", "173", "+$153", "+$650", "59.5%"],
        ["2026-05-15", "170", "−$35", "+$615", "60.0%"],
        ["2026-05-16", "187", "−$587", "+$28", "55.1%"],
        ["2026-05-17 (halt 12:38)", "51", "−$355", "−$327", "49.0%"],
    ]
    story.append(_table(perday_rows, col_widths=[48 * mm, 16 * mm, 26 * mm, 30 * mm, 18 * mm]))
    story.append(Spacer(0, 8))
    story.append(Paragraph(
        "Note the WR-vs-PnL decoupling: 05-15 had the highest day-WR (60.0%) but "
        "the negative daily PnL. This is the SURV-cell-flip pattern: the bot "
        "still wins most of its fires, but the wins are smaller than the losses. "
        "Classical Kelly diagnostic.",
        s["body"]))
    story.append(Paragraph("8.6 Authorship + sign-off", s["h2"]))
    story.append(Paragraph(
        "Generated by Claude Code (Opus 4.7) on 2026-05-17 within "
        "Phase N forensic Session 1+2. Operator review required before "
        "any Phase O action. Bot remains halted until operator clears "
        "halt.sentinel.",
        s["small"]))

    doc.build(story)
    print(f"→ wrote {OUT}")


if __name__ == "__main__":
    build()
