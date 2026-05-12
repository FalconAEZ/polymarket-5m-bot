"""Build pdfs/PHASE_H_v2_1_IMPLEMENTATION.pdf — the v2.1 implementation plan.

Pulls all known edges from bot history (Phase A Bonereaper, edge-discovery
5/9, regime validation 5/10, Phase F audit, Phase G full study), proposes
v2.1 = v2 + filter changes to eliminate confirmed losers + exploit
confirmed winners + Kelly sizing + multi-fire + compounding.

Same dark-terminal palette as Phase G PDF.

Usage:
    uv run --with reportlab python -u pdfs/build_phase_h_implementation_pdf.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741

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
OUT = ROOT / "pdfs" / "PHASE_H_v2_1_IMPLEMENTATION.pdf"
DESKTOP = Path.home() / "Desktop" / "PHASE_H_v2_1_IMPLEMENTATION.pdf"

# Dark-terminal palette (same as Phase G)
BG = HexColor("#0a0a0a")
PANEL = HexColor("#1a1a1a")
TEXT = HexColor("#e0e0e0")
SUBTLE = HexColor("#888888")
ACCENT = HexColor("#00ff88")
WARN = HexColor("#ffaa00")
LOSS = HexColor("#ff4466")
LINE = HexColor("#444444")
KEEP_GREEN = HexColor("#00cc66")
LOSE_RED = HexColor("#cc4444")
SUGGEST_AMBER = HexColor("#aa8800")


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
            "Phase H — v2.1 implementation plan · 2026-05-13 · POLYMARKET 5m bot"
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
                                fontSize=9.5, textColor=TEXT, leading=13, alignment=TA_LEFT, spaceAfter=6),
        "code": ParagraphStyle("code", parent=base["BodyText"], fontName="Courier",
                                fontSize=8.5, textColor=ACCENT, leading=11, leftIndent=12),
        "warn": ParagraphStyle("warn", parent=base["BodyText"], fontName="Helvetica",
                                fontSize=10, textColor=WARN, leading=14, spaceAfter=8,
                                leftIndent=8, rightIndent=8, borderColor=WARN,
                                borderWidth=0.5, borderPadding=6),
        "headline": ParagraphStyle("headline", parent=base["BodyText"], fontName="Helvetica-Bold",
                                    fontSize=11, textColor=ACCENT, leading=15, spaceAfter=10, alignment=TA_LEFT),
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName="Helvetica-Bold",
                                       fontSize=28, textColor=ACCENT, leading=34, alignment=TA_CENTER, spaceAfter=20),
        "cover_sub": ParagraphStyle("cover_sub", parent=base["BodyText"], fontName="Helvetica",
                                     fontSize=12, textColor=TEXT, leading=18, alignment=TA_CENTER, spaceAfter=10),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica",
                                 fontSize=8, textColor=SUBTLE, leading=10, spaceAfter=4),
    }


def _table(rows, col_widths=None, row_colors=None):
    t = Table(rows, colWidths=col_widths)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, LINE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    if row_colors:
        for i, c in row_colors.items():
            style.append(("TEXTCOLOR", (0, i), (-1, i), c))
    t.setStyle(TableStyle(style))
    return t


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title="Phase H — v2.1 implementation plan",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story = []

    # ========== COVER ==========
    story.append(Spacer(0, 40 * mm))
    story.append(Paragraph("PHASE&nbsp;H", s["cover_title"]))
    story.append(Paragraph("v2.1 implementation plan", s["cover_sub"]))
    story.append(Spacer(0, 12 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 12 * mm))
    story.append(Paragraph(
        "Edge consolidation + filter changes + Kelly sizing<br/>"
        "+ multi-fire + compounding<br/>"
        "POLYMARKET 5-minute BTC up/down bot · 2026-05-13",
        s["cover_sub"]))
    story.append(Spacer(0, 16 * mm))
    story.append(Paragraph(
        "<b>What this plan does:</b> pulls every confirmed edge from the bot's "
        "5-day production history + Bonereaper studies + Phase G analysis, "
        "eliminates the 6 confirmed losers, exploits the 5 confirmed winners, "
        "and adds the 3 architectural improvements (Kelly + multi-fire + "
        "compounding) into a single coherent v2.1 strategy.",
        s["body"]))
    story.append(Spacer(0, 10 * mm))
    story.append(Paragraph(
        "Projection (Phase G Conservative scenario): $1,006 bankroll grows "
        "to <b>$116k median by day 90</b> if the v2.1 cell-level edge "
        "(58.2% WR backtest) generalizes.",
        s["headline"]))
    story.append(PageBreak())

    # ========== 1 EXECUTIVE SUMMARY ==========
    story.append(Paragraph("1. Executive summary", s["h1"]))
    story.append(Paragraph(
        "Phase G uncovered that the bot has been firing in losing cells. v2's "
        "filters eliminate the big losers but miss the biggest winner: "
        "<b>tier 30-50% × |Δ_bps|&lt;5</b> (n=83, +$0.65/trade, 48% WR with "
        "asymmetric payoff). v2 currently rejects this zone via its global "
        "|Δ|≥5 floor.",
        s["body"]))
    story.append(Paragraph(
        "v2.1 is v2 + 4 filter changes (CH1-CH4) + Kelly sizing (CH5-CH6) + "
        "multi-fire (CH7-CH8). All changes have data backing from Phase G or "
        "earlier studies. Implementation is ~150 LOC + 15 tests.",
        s["body"]))
    story.append(Paragraph(
        "<b>Recommended Phase H deployment sequence:</b><br/>"
        "  H.1 — this PDF (now)<br/>"
        "  H.2 — code (next session, ~1h)<br/>"
        "  H.3 — tests (next session, ~30min)<br/>"
        "  H.4 — register + .envrc edit (next session, ~5min)<br/>"
        "  H.5 — VPS deploy + 3-stage verify (next session, ~1h)<br/>"
        "  H.6 — 7-day soak gate (+7d after H.5) → PROMOTE/EXTEND/ROLLBACK",
        s["body"]))
    story.append(PageBreak())

    # ========== 2 EDGE INVENTORY ==========
    story.append(Paragraph("2. Edge inventory (full bot history)", s["h1"]))

    story.append(Paragraph("2.1 Confirmed winners (statistically supported)", s["h2"]))
    story.append(_table([
        ["#", "Edge", "Source", "n", "WR / per-trade", "Status"],
        ["W1", "Tier 30-50% × |Δ|<5",
         "Phase G §5.1", "83",
         "48.1% / +$0.65", "★ NEW — exploit"],
        ["W2", "Tier 70-85% (any |Δ|)",
         "Phase G §4.1 + edge-disc 5/9", "35",
         "70.6%", "v2 allows ✓"],
        ["W3", "Regime = trending",
         "regime-validation 5/10", "19",
         "70.59% / +$1.75", "v3 has gate; v2.1 may add"],
        ["W4", "EV ∈ [0.05, 0.20)",
         "Phase G §4.4", "54",
         "72% / +$1.61", "v2 allows ✓ (but allows losers too)"],
        ["W5", "Δ ≠ 0 (any sign)",
         "Phase G §4.3", "446",
         "51.6%", "v2 allows ✓"],
    ], col_widths=[10*mm, 38*mm, 38*mm, 12*mm, 26*mm, 40*mm]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("2.2 Confirmed losers (Wilson CI confirms)", s["h2"]))
    story.append(_table([
        ["#", "Edge", "Source", "n", "WR / per-trade", "Status"],
        ["L1", "Δ_bps = 0 (no skew)",
         "Phase G §4.3", "187",
         "44.6% / −$0.40", "✗ v2.1: REJECT"],
        ["L2", "EV ∈ [0.02, 0.05)",
         "Phase G §4.4", "77",
         "36.0% / −$1.46", "✗ v2.1: REJECT bucket"],
        ["L3", "Tier 50-70%",
         "edge-disc 5/9 + Phase G", "349",
         "50.4% / −$0.25", "✓ v2 already rejects"],
        ["L4", "Tier 85-100% (slow-min)",
         "scout-final 5/8", "n/a",
         "−$3,964/7d Bonereaper", "✓ v2 already rejects"],
        ["L5", "wide_fire + ensemble",
         "Phase F audit", "126",
         "42.2% / −$0.56", "✓ Phase F cut removed"],
        ["L6", "AGGRESSIVE_MODE",
         "May 8/9 split", "299",
         "high variance", "✓ already off"],
    ], col_widths=[10*mm, 38*mm, 38*mm, 12*mm, 26*mm, 40*mm]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("2.3 Suggestive (n&lt;30 or marginal — DEFER)", s["h2"]))
    story.append(_table([
        ["#", "Edge", "Source", "Note"],
        ["S1", "Hour 0/17/21 > 5/14/23 UTC", "Phase G §4.6", "underpowered, defer"],
        ["S2", "spot_dir UP_weak > DOWN_weak", "Phase G §5", "n thin, defer"],
    ], col_widths=[12*mm, 60*mm, 45*mm, 50*mm]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("2.4 Architectural (Phase G additions)", s["h2"]))
    story.append(_table([
        ["#", "Edge", "Source", "Status in v2.1"],
        ["N1", "Kelly sizing", "Phase G §10.1-10.2", "✓ implement (CH5)"],
        ["N2", "Multi-fire per window", "Phase G §10.3", "✓ implement (CH7-CH8)"],
        ["N3", "Cumulative compounding", "Phase G §10.4", "✓ implicit via Kelly + bankroll"],
        ["N4", "Tier-specific Δ floor", "Phase G §5.1", "✓ implement (CH3)"],
    ], col_widths=[12*mm, 50*mm, 45*mm, 60*mm]))
    story.append(PageBreak())

    # ========== 3 DECISION MATRIX ==========
    story.append(Paragraph("3. Decision matrix — what's in v2.1, what's deferred", s["h1"]))
    story.append(_table([
        ["Edge", "v2 currently", "v2.1 change", "Expected impact"],
        ["W1 — 30-50%×|Δ|<5", "REJECTED (|Δ|≥5)", "ALLOW (CH3)", "+ ~16 fires/day in cell"],
        ["W2 — 70-85% any Δ", "ALLOWED", "unchanged", "—"],
        ["W3 — trending regime", "no gate", "OPTIONAL flag", "→ operator Q2"],
        ["W4 — EV [0.05,0.20)", "ALLOWED", "unchanged", "—"],
        ["W5 — Δ ≠ 0", "ALLOWED", "REJECT Δ=0 (CH1)", "− 187 losing fires removed"],
        ["L1 — Δ = 0", "ALLOWED", "REJECT (CH1)", "+$75 PnL recoverable"],
        ["L2 — EV [0.02,0.05)", "ALLOWED", "REJECT (CH2)", "+$112 PnL recoverable"],
        ["L3 — Tier 50-70%", "REJECTED", "unchanged ✓", "—"],
        ["L4 — Tier 85-100%", "REJECTED", "unchanged ✓", "—"],
        ["L5 — wide_fire", "REMOVED", "unchanged ✓", "—"],
        ["L6 — aggressive", "OFF", "unchanged ✓", "—"],
        ["S1 — hour gate", "no gate", "DEFER", "needs more data"],
        ["S2 — spot_dir gate", "no gate", "DEFER", "needs more data"],
        ["N1 — Kelly sizing", "$5 flat", "Kelly (CH5)", "compounding growth"],
        ["N2 — multi-fire", "1/window", "2/window (CH7-8)", "2× fires/day"],
        ["N3 — compounding", "none", "implicit via Kelly", "geometric growth"],
        ["N4 — tier Δ floor", "global 5 bps", "tier-specific (CH3)", "exploits W1"],
    ], col_widths=[40*mm, 30*mm, 32*mm, 50*mm]))
    story.append(PageBreak())

    # ========== 4 v2.1 ARCHITECTURE ==========
    story.append(Paragraph("4. v2.1 architecture", s["h1"]))
    story.append(Paragraph(
        "v2.1 inherits from SpotAwareStrategyV2 and overrides _maybe_fire "
        "with the new filter chain, plus adds a get_size method for Kelly "
        "and lifts the once-per-window invariant.",
        s["body"]))

    story.append(Spacer(0, 4))
    story.append(Paragraph("4.1 Filter chain (per-fire decision)", s["h2"]))
    story.append(Paragraph(
        "class SpotAwareStrategyV2_1(SpotAwareStrategyV2):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;def _maybe_fire(self, *, tier, p_win, ev, delta_bps, side, ...):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# CH1 — reject Δ=0<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;if delta_bps == 0.0: return None<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# CH2 — reject EV in [0.02, 0.05)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;if 0.02 &lt;= ev &lt; 0.05: return None<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# CH3 — tier-specific Δ floor<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;min_d = 0.0 if tier in ('15-30%', '30-50%') else 5.0<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;if abs(delta_bps) &lt; min_d: return None<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;# v2's tier rejection (50-70% + 85-100%) inherited<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;return super()._maybe_fire(...)",
        s["code"]))

    story.append(Spacer(0, 4))
    story.append(Paragraph("4.2 Kelly sizing (per-fire bet)", s["h2"]))
    story.append(Paragraph(
        "@dataclass(frozen=True, slots=True)<br/>"
        "class KellyConfig:<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;kelly_mult: float = 0.10  # fractional Kelly (start conservative)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;min_bet_abs: float = 1.0<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;max_bet_abs: float = 500.0  # Polymarket retail liquidity<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;max_bet_pct: float = 0.10  # never more than 10% of bankroll<br/>"
        "<br/>"
        "def kelly_bet(p_win, price, bankroll, cfg):<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;f = max(0, (p_win - price) / (1 - price))<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;bet = bankroll * cfg.kelly_mult * f<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;bet = min(bet, bankroll * cfg.max_bet_pct, cfg.max_bet_abs)<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;return max(cfg.min_bet_abs, bet) if f &gt; 0 else 0",
        s["code"]))

    story.append(Spacer(0, 4))
    story.append(Paragraph("4.3 Multi-fire per window", s["h2"]))
    story.append(Paragraph(
        "v2.1 tracks fires_this_window instead of fired_for_window. Allows "
        "up to MULTI_FIRE_CAP (default 2) fires per 5-min window. Caller "
        "(PaperRunner) resets at window boundary.",
        s["body"]))
    story.append(Paragraph(
        "Risk note: multi-fire increases capital deployed per window. With "
        "Kelly 0.10× × max 2 fires × ~5% avg bet = ~10% of bankroll per "
        "window peak exposure. Sane.",
        s["body"]))

    story.append(Spacer(0, 4))
    story.append(Paragraph("4.4 Compounding (live bankroll)", s["h2"]))
    story.append(Paragraph(
        "v2.1 constructor takes a bankroll_getter callback. Each fire reads "
        "current bankroll from PaperRunner, sizes accordingly. As bankroll "
        "grows, bet sizes grow proportionally (clamped by max_bet_abs). This "
        "is the geometric compounding that drives the Phase G $116k/90d "
        "projection.",
        s["body"]))
    story.append(PageBreak())

    # ========== 5 IMPLEMENTATION PLAN ==========
    story.append(Paragraph("5. Implementation sub-phases", s["h1"]))
    story.append(_table([
        ["Sub-phase", "When", "Deliverable", "Effort"],
        ["H.1", "this session", "PDF (this doc)", "~30 min"],
        ["H.2", "next session", "src/.../spot_aware_v2_1.py", "~1 h"],
        ["H.3", "next session", "tests/.../test_spot_aware_v2_1.py", "~30 min"],
        ["H.4", "next session", "STRATEGY=spot_aware_v2_1 registered + .envrc", "~5 min"],
        ["H.5", "next session", "VPS deploy + +5/30/24h verify", "~1 h"],
        ["H.6", "+7d after H.5", "soak gate → PROMOTE / EXTEND / ROLLBACK", "passive"],
    ], col_widths=[20*mm, 26*mm, 80*mm, 26*mm]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("5.1 H.2 code skeleton", s["h2"]))
    story.append(Paragraph(
        "File: src/polymarket_bot/strategies/spot_aware_v2_1.py (~150 LOC)<br/>"
        "Type hints + module docstring (≥80 chars) per anti-vibe rule #5/#6.<br/>"
        "Inherits SpotAwareStrategyV2.<br/>"
        "Adds: KellyConfig, bankroll_getter callback, fires_this_window counter.<br/>"
        "Overrides: _maybe_fire (filter chain), get_size (Kelly).<br/>"
        "Lifts: fired_for_window invariant.",
        s["body"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("5.2 H.3 test surface (~15 tests)", s["h2"]))
    story.append(_table([
        ["Test", "What it validates"],
        ["test_v2_1_rejects_delta_zero", "CH1 — Δ=0 returns None"],
        ["test_v2_1_rejects_ev_in_bad_bucket", "CH2 — EV ∈ [0.02, 0.05) returns None"],
        ["test_v2_1_allows_tier_30_50_with_low_delta", "CH3 — tier 30-50% × |Δ|=2 fires"],
        ["test_v2_1_requires_5bps_for_tier_70_85", "CH3 — tier 70-85% × |Δ|=2 returns None"],
        ["test_v2_1_inherits_tier_50_70_reject", "v2 inheritance — 50-70% returns None"],
        ["test_kelly_bet_basic", "CH5 — bet math for known inputs"],
        ["test_kelly_bet_clamps_to_max_abs", "CH5 — never exceeds $500"],
        ["test_kelly_bet_clamps_to_max_pct", "CH5 — never exceeds 10% of bankroll"],
        ["test_kelly_bet_zero_when_no_edge", "CH5 — p_win ≤ price → bet=0"],
        ["test_kelly_bet_min_floor", "CH5 — applies $1 min when positive edge"],
        ["test_multi_fire_two_per_window", "CH7 — fires twice in same window"],
        ["test_multi_fire_blocked_at_cap", "CH8 — third fire same window returns None"],
        ["test_multi_fire_resets_on_window_boundary", "CH8 — new window resets counter"],
        ["test_bankroll_getter_integration", "CH6 — bet scales with bankroll"],
        ["test_v2_1_rationale_includes_kelly_metadata", "telemetry — Kelly info in rationale"],
    ], col_widths=[78*mm, 75*mm]))

    story.append(PageBreak())

    # ========== 6 DEPLOYMENT + VERIFY ==========
    story.append(Paragraph("6. Deployment (H.5) + verify", s["h1"]))
    story.append(Paragraph("6.1 .envrc change", s["h2"]))
    story.append(Paragraph(
        "From: export STRATEGY=spot_aware_v2<br/>"
        "To:   # PHASE-H 2026-05-13: v2.1 deploy<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;# export STRATEGY=spot_aware_v2<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;export STRATEGY=spot_aware_v2_1<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;export KELLY_MULT=0.10<br/>"
        "&nbsp;&nbsp;&nbsp;&nbsp;export MULTI_FIRE_CAP=2",
        s["code"]))
    story.append(Paragraph(
        "Backup pattern: .envrc.phase-H-pre-v2_1-backup-YYYYMMDD-HHMMSS<br/>"
        "Rollback (one-line): cp backup .envrc &amp;&amp; sudo systemctl restart bot-staging",
        s["body"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("6.2 Verify cadence", s["h2"]))
    story.append(_table([
        ["When", "Check"],
        ["+5 min", "active strategy: spot_aware_v2_1 in startup log; 0 errors"],
        ["+5 min", "first fire shows new rationale (kelly bet, fires_this_window)"],
        ["+30 min", "service active, no queue overflow, fire rate ≥ projected"],
        ["+24 h", "fires/day ≈ 30 (multi-fire 2× × baseline 16); WR ≥ 47%"],
        ["+7 d", "soak gate per §7 below"],
    ], col_widths=[24*mm, 130*mm]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("7. Soak gate (H.6) — PROMOTE / EXTEND / ROLLBACK", s["h1"]))
    story.append(_table([
        ["Outcome", "Criteria"],
        ["PROMOTE → Phase I (live trading prep)",
         "WR ≥ 52% on n ≥ 100 AND daily_pnl_min ≥ −$10 AND fires/day ≥ 30 AND queue_overflow == 0"],
        ["EXTEND (re-soak 7d)",
         "WR 45-52% OR fires/day 20-30 OR daily_pnl in [−30,−10) on worst day"],
        ["ROLLBACK to v2",
         "WR < 45% over 48h OR daily_pnl < −$30 any day OR bankroll ≤ $500"],
    ], col_widths=[60*mm, 95*mm]))

    story.append(PageBreak())

    # ========== 7 OPEN QUESTIONS ==========
    story.append(Paragraph("8. Open questions for operator (Q1-Q5)", s["h1"]))
    story.append(Paragraph(
        "These are the implementation knobs the operator decides before H.2 starts.",
        s["body"]))
    story.append(_table([
        ["Q", "Question", "Options", "Recommended"],
        ["Q1", "Hour-of-day gate (S1)?",
         "YES = skip 5/14/23 UTC · NO = no gate",
         "NO (sample too thin)"],
        ["Q2", "Regime gate (W3)?",
         "A no gate · B half-Kelly on chop · C trending-only",
         "A (start simple)"],
        ["Q3", "Multi-fire cap?",
         "2 / 3 per window",
         "2 (conservative)"],
        ["Q4", "Kelly multiplier?",
         "0.10 / 0.25",
         "0.10 (smooth ride)"],
        ["Q5", "Live-trading promotion threshold?",
         "$2k / $5k / $10k",
         "$2k (locked decision #12)"],
    ], col_widths=[10*mm, 50*mm, 60*mm, 35*mm]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("9. What this phase explicitly does NOT do", s["h1"]))
    story.append(Paragraph(
        "• Does NOT deploy v2.1 — H.5 is the deploy step (next session, NOT now)<br/>"
        "• Does NOT touch v2/v3/v1/wide_fire — v2.1 is additive (new file)<br/>"
        "• Does NOT modify any locked decision<br/>"
        "• Does NOT re-engage ensemble (Phase F cut intact)<br/>"
        "• Does NOT skip the 7-day soak gate before promotion",
        s["body"]))

    story.append(Spacer(0, 8))
    story.append(Paragraph("10. Honest pushback", s["h1"]))
    story.append(Paragraph(
        "<b>The 58% WR backtest is from a 5-day window.</b> v2.1's exploitation "
        "of the 30-50%×|Δ|<5 cell assumes that cell's edge generalizes. "
        "Phase G Scenario C showed: at 50% WR (regression), median still "
        "grows but 97% of paths hit catastrophic drawdown.",
        s["warn"]))
    story.append(Paragraph(
        "Mitigations baked into v2.1:<br/>"
        "• Kelly 0.10× (not 0.25×) for first 30 days — smoother trajectory<br/>"
        "• $500 absolute bet cap — Polymarket liquidity realism<br/>"
        "• Multi-fire 2× (not 3×) — limit per-window capital exposure<br/>"
        "• 7-day soak gate before promotion — kill switch on bad data",
        s["body"]))
    story.append(Paragraph(
        "Even with these mitigations: <b>if WR drops below 45% over 48h, "
        "ROLLBACK</b>. The Kelly variance signature is real.",
        s["body"]))

    story.append(Spacer(0, 10))
    story.append(HRFlowable(width="80%", thickness=0.5, color=LINE, hAlign="CENTER"))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "End of Phase H implementation plan · 2026-05-13 · 14 edges inventoried · "
        "4 filter changes + 4 sizing/multi-fire changes · 6 sub-phases · 1 PDF",
        s["small"]))
    story.append(Paragraph(
        "Source prompt: phase-prompts/phase-H-v2.1-implementation-2026-05-13.txt · "
        "Reference: pdfs/PHASE_G_EDGE_DISCOVERY.pdf",
        s["small"]))

    doc.build(story)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024}K)")

    # Copy to desktop
    import shutil
    shutil.copy(OUT, DESKTOP)
    print(f"copied to {DESKTOP}")


if __name__ == "__main__":
    build()
