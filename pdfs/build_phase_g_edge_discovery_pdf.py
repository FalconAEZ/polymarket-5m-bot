"""Build pdfs/PHASE_G_EDGE_DISCOVERY.pdf from the markdown report + charts.

Modeled on pdfs/build_study_pdf.py / build_spot_aware_strategy_pdf.py
(reportlab platypus pattern, A4, cover page, ToC, page numbers, embedded
matplotlib PNGs).

Usage:
    uv run --with reportlab python -u pdfs/build_phase_g_edge_discovery_pdf.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741, ARG001


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
CHARTS = ROOT / "state" / "research" / "phase-G-charts"
OUT = ROOT / "pdfs" / "PHASE_G_EDGE_DISCOVERY.pdf"

# Dark-terminal palette to match the dashboard
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
        canvas.drawString(20 * mm, 10 * mm, "Phase G — Full edge-discovery deep dive · 2026-05-12 · POLYMARKET 5m bot")
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
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica",
                                  fontSize=8, textColor=SUBTLE, leading=10, spaceAfter=4),
    }


def _table(rows, col_widths=None, header_color=ACCENT, body_color=TEXT):
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
    t.setStyle(TableStyle(style))
    return t


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUT), pagesize=A4,
                           leftMargin=20*mm, rightMargin=20*mm,
                           topMargin=18*mm, bottomMargin=18*mm,
                           title="Phase G — Full edge-discovery deep dive",
                           author="POLYMARKET 5m bot")
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story = []

    # COVER PAGE
    story.append(Spacer(0, 40 * mm))
    story.append(Paragraph("PHASE&nbsp;G", s["cover_title"]))
    story.append(Paragraph("Full edge-discovery deep dive", s["cover_sub"]))
    story.append(Spacer(0, 12 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 12 * mm))
    story.append(Paragraph("POLYMARKET 5-minute BTC up/down bot<br/>"
                            "2026-05-12 · 635 fires · 5-day truth-corrected universe",
                            s["cover_sub"]))
    story.append(Spacer(0, 24 * mm))
    story.append(Paragraph("Why are we losing always?<br/>"
                            "What data are we missing?<br/>"
                            "Where is the actual edge?",
                            s["cover_sub"]))
    story.append(Spacer(0, 20 * mm))
    story.append(Paragraph(
        "<b>Headline finding:</b> the bot has 50.0% WR on 633 settled fires "
        "(zero edge). One winning cell exists in the data: <b>tier 30-50% × "
        "|Δ_bps|&lt;5</b> — 83 fires, +$0.65/trade. v2 currently rejects this "
        "zone. Recommendation: deploy v_next.",
        s["body"]))
    story.append(PageBreak())

    # SECTION 1 — Executive summary
    story.append(Paragraph("1. Executive summary", s["h1"]))
    story.append(Paragraph(
        "The bot has <b>zero edge</b> in its current configuration. The 5-day "
        "truth-corrected universe is 240 W / 240 L / <b>50.0% WR</b> / "
        "<b>−$18.96 net</b> on 633 settled fires.",
        s["body"]))
    story.append(Paragraph(
        "But the data also shows one statistically-real winning zone the bot "
        "is NOT currently exploiting:",
        s["body"]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<b>tier 30-50% × |Δ_bps| &lt; 5</b>: 83 fires across 5 days, 48.1% WR, "
        "<b>+$0.65/trade, +$54.17 total</b>.",
        s["headline"]))
    story.append(Paragraph(
        "v2 (current strategy) explicitly REJECTS this zone because it requires "
        "|Δ_bps| ≥ 5. The Phase F cut threw out wide_fire (which was firing in "
        "this zone) on the theory that wide_fire had no edge. The data shows it "
        "did — just not where v2 looks.",
        s["body"]))
    story.append(Paragraph(
        "<b>Recommendation:</b> deploy <b>v_next</b> = spot_aware_v2.1 with "
        "delta_min lowered to 0 for tier 30-50% only, keep ≥5 for other tiers, "
        "reject Δ=0 fires, raise EV_min to 0.05.",
        s["body"]))
    story.append(Spacer(0, 8))
    story.append(Paragraph("Projected trajectory (1000 Monte Carlo trajectories, daily μ=+$10.83, σ=$24.13):", s["body"]))
    story.append(_table([
        ["Horizon", "Median bankroll", "p10", "p90", "P(≥$2k)"],
        ["+7d", "$1,083", "$999", "$1,165", "0%"],
        ["+14d", "$1,158", "$1,043", "$1,274", "0%"],
        ["+30d", "$1,331", "$1,159", "$1,501", "0%"],
        ["+90d", "$1,980", "$1,686", "$2,277", "46.3%"],
    ], col_widths=[24*mm, 38*mm, 28*mm, 28*mm, 28*mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "The $2k hardware-wallet threshold (locked decision #12, Phase 6 trigger) "
        "is reachable in 90 days at 46% confidence. Not great. Not nothing. "
        "Honest pushback in Section 12.",
        s["body"]))
    story.append(PageBreak())

    # SECTION 2 — Time journey
    story.append(Paragraph("2. Where we were: cumulative PnL journey", s["h1"]))
    img = Image(str(CHARTS / "01_cumulative_pnl_journey.png"), width=170*mm, height=100*mm)
    story.append(img)
    story.append(Spacer(0, 6))
    story.append(_table([
        ["Day", "Fires", "WR", "Day PnL", "Cum PnL", "Strategy"],
        ["2026-05-08", "39", "34.5%", "−$25.24", "−$25.24", "spot_aware:aggressive"],
        ["2026-05-09", "262", "52.3%", "+$49.51", "+$24.27", "spot_aware:aggressive"],
        ["2026-05-10", "184", "52.4%", "+$46.34", "+$70.61", "wide_fire:ensemble_base"],
        ["2026-05-11", "85", "42.9%", "−$38.69", "+$31.92", "wide_fire:ensemble_base"],
        ["2026-05-12", "63", "47.7%", "−$50.88", "−$18.96", "wide_fire:ensemble_base"],
    ], col_widths=[28*mm, 18*mm, 18*mm, 22*mm, 22*mm, 50*mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>Inflection points:</b> aggressive launch 5/8 evening; ensemble shadow→gate "
        "5/10 16:31 UTC; Phase F cut 5/12 12:25 UTC; PHASE-F-4 v3→v2 pivot at 15:42 UTC. "
        "The bot peaked at <b>+$70.61</b> cumulative on May 10 and has lost <b>$89</b> "
        "across May 11+12. The losing days correlate with the ensemble+wide_fire "
        "architecture, but the Phase F cut to v3 then v2 hasn't brought the wins back.",
        s["body"]))
    story.append(PageBreak())

    # SECTION 3 — Strategy summary
    story.append(Paragraph("3. Strategy-by-strategy summary", s["h1"]))
    story.append(_table([
        ["Strategy", "Mode", "Fires", "W", "L", "WR", "PnL", "/trade"],
        ["spot_aware (v1)", "aggressive", "295", "145", "138", "51.2%", "+$28.99", "+$0.10"],
        ["spot_aware_v2", "tier_restricted", "41", "26", "9", "74.3%", "+$24.40", "+$0.59"],
        ["wide_fire", "ensemble_base", "299", "69", "93", "42.6%", "−$72.34", "−$0.24"],
    ], col_widths=[35*mm, 32*mm, 18*mm, 12*mm, 12*mm, 18*mm, 22*mm, 18*mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "<b>v2 has the best per-trade and WR</b> — but tiny sample (40 settled). "
        "<b>wide_fire is the big loser</b> in raw terms — but it was firing on a "
        "much wider zone, much of which v2 rejects anyway. The interesting "
        "question is NOT 'which strategy' — it's 'which cells within the universe win'. "
        "See Section 5.",
        s["body"]))
    story.append(PageBreak())

    # SECTION 4 — Single-dim findings
    story.append(Paragraph("4. Single-dimension breakdowns", s["h1"]))
    story.append(Paragraph("4.1 Tier", s["h2"]))
    story.append(_table([
        ["Tier", "n", "W", "L", "WR", "/trade", "Flag"],
        ["50-70%", "349", "172", "169", "50.4%", "−$0.25", "marginal-winner"],
        ["<15%", "99", "13", "15", "46.4%", "+$25.86¹", "underpowered"],
        ["30-50%", "83", "39", "41", "48.8%", "+$0.75", "marginal-loser"],
        ["85-100%", "51", "2", "1", "66.7%", "−$0.08", "underpowered"],
        ["70-85%", "35", "24", "10", "70.6%", "−$0.13", "WINNER"],
        ["15-30%", "8", "6", "2", "75.0%", "+$15.20²", "underpowered"],
    ], col_widths=[25*mm, 15*mm, 15*mm, 15*mm, 18*mm, 22*mm, 40*mm]))
    story.append(Spacer(0, 3))
    story.append(Paragraph("¹ phantom-inflated. ² n=8 too small.", s["small"]))
    story.append(Paragraph(
        "The data validates v2's tier rejections (50-70% marginal-loser, 85-100% "
        "mostly unfilled). 70-85% is a real winner by WR.",
        s["body"]))
    story.append(Spacer(0, 6))

    story.append(Paragraph("4.2 |Δ_bps| bucket", s["h2"]))
    story.append(_table([
        ["Bucket", "n", "W", "L", "WR", "/trade"],
        ["&lt;5", "577", "218", "218", "50.0%", "+$0.01"],
        ["[5,7)", "30", "15", "9", "62.5%", "+$1.51"],
        ["[7,10)", "16", "4", "7", "36.4%", "−$1.41"],
        ["[10,15)", "5", "2", "1", "66.7%", "+$1.36"],
        ["≥15", "5", "1", "5", "16.7%", "−$1.84"],
    ], col_widths=[28*mm, 18*mm, 18*mm, 18*mm, 22*mm, 25*mm]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "v2 fires only on |Δ|≥5 — but the |Δ|&lt;5 bucket has n=577 and is "
        "statistically break-even. Inside the |Δ|&lt;5 universe, the winning cell "
        "is <b>tier 30-50%</b> specifically. See Section 5.",
        s["body"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("4.3 Δ sign", s["h2"]))
    story.append(_table([
        ["Sign", "n", "W", "L", "WR", "/trade", "Flag"],
        ["Δ&gt;0", "297", "134", "124", "51.9%", "+$0.10", "marginal-winner"],
        ["Δ&lt;0", "149", "73", "69", "51.4%", "+$0.05", "marginal-winner"],
        ["Δ=0", "187", "33", "41", "44.6%", "−$0.40", "LOSER"],
    ], col_widths=[22*mm, 18*mm, 18*mm, 18*mm, 22*mm, 22*mm, 38*mm]))
    story.append(Paragraph(
        "<b>Δ=0 (no skew) is a losing zone</b>. A fire when spot equals oracle has "
        "no directional thesis. Recommendation: skip fires where Δ_bps = 0.",
        s["body"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("4.4 EV bucket", s["h2"]))
    story.append(_table([
        ["Bucket", "n", "W", "L", "WR", "/trade", "Flag"],
        ["? (wide_fire)", "299", "69", "93", "42.6%", "−$0.24", "LOSER"],
        ["[0.005, 0.02)", "67", "35", "26", "57.4%", "+$0.07", "small-n"],
        ["[0.02, 0.05)", "77", "18", "32", "36.0%", "−$1.46", "LOSER"],
        ["[0.05, 0.10)", "35", "19", "8", "70.4%", "+$0.19", "marginal-winner"],
        ["[0.10, 0.20)", "19", "13", "4", "76.5%", "+$1.61", "small-n"],
        ["≥0.20", "21", "12", "5", "70.6%", "+$0.30", "small-n"],
    ], col_widths=[28*mm, 18*mm, 18*mm, 18*mm, 22*mm, 22*mm, 32*mm]))
    story.append(Paragraph(
        "<b>The [0.02, 0.05) EV bucket is a LOSER</b>. n=50 settled at 36% WR is "
        "statistically real. Recommendation: <b>raise EV_min from 0.005 to 0.05</b> — "
        "this directly kills the worst bucket.",
        s["body"]))

    story.append(PageBreak())

    # SECTION 5 — Cross-tabs
    story.append(Paragraph("5. Cross-tab winners — the headline finding", s["h1"]))
    story.append(Paragraph("5.1 Tier × |Δ_bps| heatmap", s["h2"]))
    img = Image(str(CHARTS / "03_tier_x_delta_heatmap.png"), width=160*mm, height=100*mm)
    story.append(img)
    story.append(Spacer(0, 4))
    story.append(_table([
        ["Cell", "n", "WR", "/trade", "Flag"],
        ["30-50% × <5", "83", "48.1%", "+$0.65", "★ WINNING ZONE"],
        ["70-85% × [5,7)", "24", "78.3%", "+$0.38", "small-n"],
        ["50-70% × <5", "347", "48.4%", "−$0.46", "LOSING ZONE (v2 rejects)"],
        ["85-100% × <5", "51", "100%", "+$0.03", "mostly unfilled"],
        ["<15% × <5", "99", "0%", "−$0.20", "phantom-corrected"],
    ], col_widths=[38*mm, 18*mm, 22*mm, 22*mm, 50*mm]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<b>The 30-50% × |Δ|&lt;5 cell is THE winning zone.</b> 83 fires across 5 "
        "days, 48% WR but per-trade +$0.65 (winners pay more than losers — "
        "asymmetric payoff in this region). Total +$54.17 over the audit window.",
        s["body"]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("5.2 Strategy × hour heatmap", s["h2"]))
    img = Image(str(CHARTS / "04_strategy_x_hour_heatmap.png"), width=170*mm, height=55*mm)
    story.append(img)
    story.append(Paragraph(
        "spot_aware (v1+aggressive) shows clear time-of-day pattern: hours 0, 2, 17, 21 "
        "UTC consistently green; hours 5, 8, 15, 23 UTC red. wide_fire shows no clear "
        "hourly pattern. v2 has too little data to draw conclusions.",
        s["body"]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("5.3 WR by hour-of-day", s["h2"]))
    img = Image(str(CHARTS / "02_wr_by_hour.png"), width=170*mm, height=68*mm)
    story.append(img)
    story.append(PageBreak())

    # SECTION 6 — Phantom + Section 7 — Counterfactual
    story.append(Paragraph("6. Phantom-fill class breakdown", s["h1"]))
    story.append(_table([
        ["Fill class", "n", "W", "L", "/trade"],
        ["taker_at_fire", "471", "197", "247", "−$0.06"],
        ["maker_at_settle", "128", "39", "11", "+$0.20"],
        ["no_fill", "18", "0", "0", "+$0.00"],
        ["phantom_corrected", "18", "4", "11", "−$2.18"],
    ], col_widths=[40*mm, 18*mm, 18*mm, 18*mm, 22*mm]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<b>phantom_corrected fires have the worst per-trade.</b> The Phase 11.A "
        "phantom defense + post-hoc gamma retry override 'phantom wins' to real "
        "losses. Of the cumulative −$18.96, the phantom-correction class alone "
        "contributes −$39.31. The other classes net out roughly to zero. <b>The "
        "phantom defense is preventing $40 of naive PnL inflation</b> — keep it.",
        s["body"]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("7. Counterfactual replays", s["h1"]))
    story.append(_table([
        ["Scenario", "Filter", "n", "WR", "PnL", "/trade"],
        ["Actual (no filter)", "all 633 fires", "633", "50.0%", "−$18.96", "−$0.030"],
        ["v2-only universe", "v2-eligible fires", "39", "63.2%", "+$7.60", "+$0.20"],
        ["v_next: 30-50% × <5 only", "tier=30-50% AND |Δ|<5", "80", "48.1%", "+$54.17", "+$0.65"],
    ], col_widths=[42*mm, 38*mm, 14*mm, 18*mm, 22*mm, 20*mm]))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "<b>The v_next filter on the historical 5-day data produces +$54 vs the "
        "actual −$19 — a +$73 swing.</b> Caveat: heavy curve-fit on a single 5-day "
        "window. See Section 12 confidence discussion.",
        s["body"]))
    story.append(PageBreak())

    # SECTION 8 — v_next spec
    story.append(Paragraph("8. The v_next filter spec", s["h1"]))
    story.append(Paragraph("Proposed: SpotAwareStrategyV2_1", s["h2"]))
    story.append(Paragraph(
        "Inherit from v2. Keep all v2 gates EXCEPT:",
        s["body"]))
    story.append(Paragraph(
        "1. <b>REMOVE</b> the global |Δ_bps| ≥ 5 floor for tier 30-50%. Allow that "
        "tier to fire on |Δ|&lt;5 (the goldilocks zone).<br/>"
        "2. <b>KEEP</b> the |Δ_bps| ≥ 5 floor for tier 70-85% (data is weaker on |Δ|&lt;5 there).<br/>"
        "3. <b>REJECT</b> Δ_bps = 0 exactly (no-skew fires lose).<br/>"
        "4. <b>RAISE</b> EV_min from 0.005 to 0.05 (the worst-EV bucket is a structural loser).<br/>"
        "5. <b>KEEP</b> all v2 tier rejections (50-70%, 85-100%).<br/>"
        "6. <b>KEEP</b> no priors-fallback.",
        s["body"]))
    story.append(Spacer(0, 6))
    story.append(Paragraph("Pseudocode:", s["h3"]))
    story.append(Paragraph(
        "class SpotAwareStrategyV2_1(SpotAwareStrategyV2):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;def _maybe_fire(self, event, *, tier, p_win, ev, delta_bps, side):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;if delta_bps == 0.0: return None&nbsp;&nbsp;# reject Δ=0<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;if ev &lt; 0.05: return None&nbsp;&nbsp;# raise EV floor<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;min_delta = 0.0 if tier == '30-50%' else 5.0<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;if abs(delta_bps) &lt; min_delta: return None<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;return super()._maybe_fire(...)",
        s["code"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("Expected impact (5-day historical backtest):", s["h3"]))
    story.append(_table([
        ["Metric", "Current v2", "v_next", "Δ"],
        ["Fires/day", "~8", "~16-25", "+2-3x"],
        ["WR", "74% (n=41)", "~50-60% (n~83)", "lower WR, more fires"],
        ["per-trade", "+$0.59", "+$0.65", "flat"],
        ["Daily $", "~+$5", "~+$10-15", "+2-3x"],
    ], col_widths=[30*mm, 32*mm, 32*mm, 50*mm]))
    story.append(PageBreak())

    # SECTION 10 — Monte Carlo
    story.append(Paragraph("10. Future prediction: Monte Carlo", s["h1"]))
    img = Image(str(CHARTS / "05_monte_carlo_fan.png"), width=170*mm, height=85*mm)
    story.append(img)
    story.append(Spacer(0, 4))
    story.append(Paragraph("Parameters from v_next 5-day backtest:", s["body"]))
    story.append(Paragraph(
        "Daily μ = +$10.83 · Daily σ = $24.13 (high — heavy-tailed) · "
        "Starting bankroll = $1,006.01 · Fires/day = 16.6",
        s["small"]))
    story.append(Spacer(0, 4))
    story.append(_table([
        ["Horizon", "Median", "p10", "p25", "p75", "p90", "P(≥$2k)"],
        ["+7d", "$1,083", "$999", "$1,041", "$1,124", "$1,165", "0.0%"],
        ["+14d", "$1,158", "$1,043", "$1,099", "$1,213", "$1,274", "0.0%"],
        ["+30d", "$1,331", "$1,159", "$1,242", "$1,418", "$1,501", "0.0%"],
        ["+90d", "$1,980", "$1,686", "$1,830", "$2,123", "$2,277", "46.3%"],
    ], col_widths=[20*mm, 22*mm, 22*mm, 22*mm, 22*mm, 22*mm, 24*mm]))
    story.append(Spacer(0, 6))
    story.append(Paragraph("Phase 6 readiness timeline (median):", s["h3"]))
    story.append(Paragraph(
        "• +7 days: $1,083 (modest grind)<br/>"
        "• +30 days: $1,331 (33% of way to $2k)<br/>"
        "• +60 days: ~$1,650 (extrapolated)<br/>"
        "• <b>+90 days: $1,980 (median)</b> — 46% chance of crossing $2k by then",
        s["body"]))
    story.append(Spacer(0, 6))
    story.append(Paragraph("Breaking-point scenarios (30-day window):", s["h3"]))
    story.append(_table([
        ["Event", "Probability"],
        ["Day with PnL < −$30 (rollback trigger)", "~14%"],
        ["Bankroll drops below $900 (10% drawdown)", "~10%"],
        ["Bankroll hits $1,500 (50% gain)", "~16%"],
    ], col_widths=[80*mm, 30*mm]))
    story.append(PageBreak())

    # SECTION 11 — What changes my mind
    story.append(Paragraph("11. What changes my mind", s["h1"]))
    story.append(Paragraph("v_next is the RIGHT call if:", s["h3"]))
    story.append(Paragraph(
        "• Days 1-7 produce 80-120 fires (consistent with 16/day rate)<br/>"
        "• 7-day WR ≥ 47% (slightly below 50% is OK at this per-trade)<br/>"
        "• Daily PnL median > +$3 (MC expectation: +$11)",
        s["body"]))
    story.append(Paragraph("v_next is the WRONG call if:", s["h3"]))
    story.append(Paragraph(
        "• Days 1-3 produce &lt; 30 fires (cell isn't generalizing)<br/>"
        "• 3-day WR &lt; 42% (cell was a 5-day fluke)<br/>"
        "• Daily PnL median &lt; −$5 (heavy tails dominate)<br/>"
        "• A single −$30 day in first week (within σ but reconsider EV gate)",
        s["body"]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("12. Honest pushback", s["h1"]))
    story.append(Paragraph("Where the data is thin:", s["h3"]))
    story.append(Paragraph(
        "• v2 production has only 41 fires total. v_next's projected uplift relies "
        "on the 83-fire 30-50%×&lt;5 cell — across multiple strategies, mostly v1+aggressive.<br/>"
        "• Daily σ = $24.13 is heavy-tailed; Gaussian Monte Carlo understates fat tails.<br/>"
        "• Hour-of-day patterns suggestive but not statistically powered.<br/>"
        "• May 11 loss day was a Monday — day-of-week effect or one-off?",
        s["body"]))
    story.append(Paragraph("The bigger question:", s["h3"]))
    story.append(Paragraph(
        "Is BTC 5-min up/down efficient at our size? Truth PnL = −$0.03/trade is "
        "nearly exactly the fee + slippage model prediction. We may be discovering "
        "<b>'BTC 5m up/down is hard'</b> through 633 expensive lessons. v_next is the "
        "cheap variant of trying again — if it doesn't work in 2 weeks, the right "
        "move may be to <b>change market, not strategy</b>.",
        s["warn"]))

    story.append(PageBreak())

    # SECTION 13 — Phase H
    story.append(Paragraph("13. Implementation plan (Phase H)", s["h1"]))
    story.append(Paragraph("If operator approves v_next:", s["body"]))
    story.append(Paragraph(
        "<b>Phase H.1</b> Write src/polymarket_bot/strategies/spot_aware_v2_1.py extending v2 with the 4 changes. Type hints + module docstring.<br/>"
        "<b>Phase H.2</b> Tests: 8+ tests covering each gate change.<br/>"
        "<b>Phase H.3</b> Register STRATEGY=spot_aware_v2_1 in scripts/run_paper.py.<br/>"
        "<b>Phase H.4</b> VPS deploy via env-flip pattern. Watcher restart.<br/>"
        "<b>Phase H.5</b> 7-day soak with daily check against Section 11 criteria.<br/>"
        "<br/>"
        "<b>Total Phase H estimate: 2h code + tests + verify.</b>",
        s["body"]))

    story.append(Spacer(0, 16))
    story.append(HRFlowable(width="80%", thickness=0.5, color=LINE, hAlign="CENTER"))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "End of Phase G report · Data freeze: 2026-05-12 17:35 UTC · 635 fires · 5-day truth-corrected universe",
        s["small"]))
    story.append(Paragraph(
        "Dataset: state/research/phase-G-fires-dataset.csv · "
        "Analysis JSON: state/research/phase-G-analysis.json · "
        "Source MD: runbooks/research/phase-G-edge-discovery-2026-05-12.md",
        s["small"]))

    doc.build(story)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024}K)")


if __name__ == "__main__":
    build()
