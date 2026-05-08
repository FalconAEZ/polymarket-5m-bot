"""Build SPOT_AWARE_STRATEGY.pdf — locked spec for the next strategy.

Focused builder: cover + 14 sections from design/spot_aware_strategy.md.
Uses the same color palette as build_pdf.py for visual consistency with
MASTERPLAN.pdf and BUILD_SPEC.pdf.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ---------- Design system (mirrors pdfs/build_pdf.py) ----------
NAVY = HexColor("#0B1F3A")
NAVY_DARK = HexColor("#06142A")
NAVY_SOFT = HexColor("#1B3358")
AMBER = HexColor("#F5A524")
TEAL = HexColor("#1AA39A")
GREEN = HexColor("#23A26D")
RED = HexColor("#E5484D")
BLUE = HexColor("#3B82F6")
GRAY_900 = HexColor("#0F172A")
GRAY_700 = HexColor("#334155")
GRAY_500 = HexColor("#64748B")
GRAY_300 = HexColor("#CBD5E1")
GRAY_200 = HexColor("#E2E8F0")
GRAY_100 = HexColor("#F1F5F9")
PAPER = HexColor("#FFFFFF")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_Y = 18 * mm

# ---------- Styles ----------
ss = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontName="Helvetica-Bold",
                   fontSize=20, leading=24, textColor=NAVY,
                   spaceBefore=4, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontName="Helvetica-Bold",
                   fontSize=14, leading=18, textColor=NAVY,
                   spaceBefore=10, spaceAfter=6)
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontName="Helvetica-Bold",
                   fontSize=11, leading=14, textColor=NAVY_SOFT,
                   spaceBefore=6, spaceAfter=2)
BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontName="Helvetica",
                     fontSize=9.5, leading=13.5, textColor=GRAY_900,
                     spaceBefore=2, spaceAfter=4, alignment=TA_LEFT)
BODY_SM = ParagraphStyle("BodySm", parent=BODY, fontSize=8.5, leading=12,
                        textColor=GRAY_700)
BULLET = ParagraphStyle("Bullet", parent=BODY, leftIndent=12, bulletIndent=2,
                       spaceBefore=1, spaceAfter=1)
CODE = ParagraphStyle("Code", parent=BODY, fontName="Courier",
                     fontSize=8.5, leading=11.5, textColor=GRAY_900,
                     backColor=GRAY_100, leftIndent=8, rightIndent=8,
                     spaceBefore=4, spaceAfter=4, borderPadding=6)
CALLOUT = ParagraphStyle("Callout", parent=BODY, fontSize=10, leading=14,
                        textColor=NAVY_DARK, leftIndent=10, rightIndent=10,
                        spaceBefore=4, spaceAfter=6, backColor=HexColor("#FFF8E5"),
                        borderPadding=8, borderColor=AMBER, borderWidth=0.5)
COVER_TITLE = ParagraphStyle("CT", parent=ss["Title"], fontName="Helvetica-Bold",
                            fontSize=34, leading=38, textColor=PAPER, alignment=TA_LEFT)
COVER_SUB = ParagraphStyle("CS", parent=ss["Title"], fontName="Helvetica",
                          fontSize=14, leading=20, textColor=HexColor("#CFE3FF"),
                          alignment=TA_LEFT)
COVER_META = ParagraphStyle("CM", parent=ss["Normal"], fontName="Helvetica",
                           fontSize=10, leading=14, textColor=HexColor("#9FB3CF"),
                           alignment=TA_LEFT)
COVER_TAG = ParagraphStyle("CTAG", parent=ss["Normal"], fontName="Helvetica-Bold",
                          fontSize=9.5, leading=13, textColor=AMBER, alignment=TA_LEFT)


# ---------- Page templates ----------
def cover_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY_DARK)
    canvas.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    canvas.setFillColor(AMBER)
    canvas.rect(0, PAGE_H - 12 * mm, 80 * mm, 4, stroke=0, fill=1)
    canvas.restoreState()


def body_page(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY_SOFT)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.drawString(MARGIN_X, PAGE_H - 10 * mm, "SPOT-AWARE STRATEGY · DESIGN")
    canvas.setFillColor(GRAY_500)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 10 * mm,
                           datetime.now(timezone.utc).strftime("%Y-%m-%d UTC"))
    canvas.setStrokeColor(GRAY_200)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN_X, PAGE_H - 12 * mm, PAGE_W - MARGIN_X, PAGE_H - 12 * mm)
    # Footer
    canvas.setFillColor(GRAY_500)
    canvas.setFont("Helvetica", 8)
    canvas.drawCentredString(PAGE_W / 2, 10 * mm, f"Page {doc.page}")
    canvas.restoreState()


def make_doc(out_path: Path) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_Y,
        bottomMargin=MARGIN_Y,
        title="SpotAwareStrategy — Locked Design",
        author="Hamad",
        subject="Polymarket 5m BTC bot — strategy design (Phase 5.7+)",
    )
    cover_frame = Frame(0, 0, PAGE_W, PAGE_H, leftPadding=22 * mm,
                        rightPadding=22 * mm, topPadding=PAGE_H * 0.42,
                        bottomPadding=22 * mm, showBoundary=0)
    body_frame = Frame(MARGIN_X, MARGIN_Y, PAGE_W - 2 * MARGIN_X,
                       PAGE_H - 2 * MARGIN_Y - 6 * mm, showBoundary=0)
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=cover_page),
        PageTemplate(id="body", frames=[body_frame], onPage=body_page),
    ])
    return doc


# ---------- Helpers ----------
def p(text, style=BODY):
    return Paragraph(text, style)


def bullet(text):
    return Paragraph(f"•&nbsp;&nbsp;{text}", BULLET)


def code(lines):
    body = "<br/>".join(line.replace(" ", "&nbsp;") for line in lines)
    return Paragraph(body, CODE)


def section(title, color=AMBER):
    return [Spacer(1, 6), p(f'<font color="{color.hexval()}">▌</font> &nbsp;{title}', H2)]


def table(data, widths=None, header=True):
    style = TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 11),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, GRAY_300),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, GRAY_100]),
        ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ])
    return Table(data, colWidths=widths, style=style, hAlign="LEFT")


# ---------- Build ----------
def build():
    out = Path(__file__).parent / "SPOT_AWARE_STRATEGY.pdf"
    doc = make_doc(out)
    s: list = []

    # Cover
    s.append(p("DESIGN DOCUMENT — LOCKED", COVER_TAG))
    s.append(Spacer(1, 8))
    s.append(p("SpotAwareStrategy", COVER_TITLE))
    s.append(p("Sibling to DeterministicStrategy.<br/>"
               "Driven by the +30.9pp aligned-vs-contrarian gap discovered in "
               "the 30-day Bonereaper analysis. Price-tier discipline borrowed "
               "from the leaderboard scout.", COVER_SUB))
    s.append(Spacer(1, 18))
    s.append(p("Polymarket 5-min BTC bot · Phase 5.7+ · Anti-vibe rule #1", COVER_META))
    s.append(p("Hamad · UAE · 2026-05-08", COVER_META))
    s.append(PageBreak())

    # Switch to body template
    from reportlab.platypus import NextPageTemplate
    s = [Paragraph("DESIGN DOCUMENT — LOCKED", COVER_TAG),
         Spacer(1, 8),
         Paragraph("SpotAwareStrategy", COVER_TITLE),
         Paragraph("Sibling to DeterministicStrategy.<br/>"
                   "Driven by the +30.9pp aligned-vs-contrarian gap discovered in "
                   "the 30-day Bonereaper analysis. Price-tier discipline borrowed "
                   "from the leaderboard scout.", COVER_SUB),
         Spacer(1, 18),
         Paragraph("Polymarket 5-min BTC bot · Phase 5.7+ · Anti-vibe rule #1", COVER_META),
         Paragraph("Hamad · UAE · 2026-05-08", COVER_META),
         NextPageTemplate("body"),
         PageBreak()]

    # 0. Why this strategy exists
    s += section("0. Why this strategy exists right now")
    s.append(p("Three pieces of evidence converged on 2026-05-08:"))
    s.append(bullet("The current <b>DeterministicStrategy fires zero times</b> "
                    "on real 5-min BTC tick data at any threshold from 0.3pp "
                    "to 0.6pp. The signal itself is too quiet."))
    s.append(bullet("A different signal does have measurable edge: the 30-day "
                    "Bonereaper spot-vs-book join (306,966 trades) shows "
                    "<b>aligned trades win 67.4% vs contrarian 36.4%</b> — a "
                    "+30.9pp gap that survives at scale."))
    s.append(bullet("<b>High win rate without price-tier discipline loses money.</b> "
                    "The two small-equity scout candidates had 96-98% scout WR "
                    "and were both net-losing because they bought 95-99¢ shares "
                    "that pay $1."))
    s.append(p("The spot-Δ signal + tier discipline + an EV check together "
               "describe a strategy whose expected value can be computed "
               "<i>before</i> it fires, not after."))

    # 1. Picture
    s += section("1. The picture")
    s.append(code([
        "        spot tick                 book update",
        "             \\                       /",
        "              v                     v",
        "  +-------------------------------------------+",
        "  |              SpotAwareStrategy            |",
        "  |                                           |",
        "  |  1. compute Δ_bps = 10000*(St-S0)/S0     |",
        "  |  2. classify alignment vs candidate side  |",
        "  |  3. price-tier filter (reject ≥90% impl)  |",
        "  |  4. lookup p_win from prior table         |",
        "  |  5. EV check: p_win*$1 > price + fees     |",
        "  |  6. fire BUY at $5 stake on aligned side  |",
        "  |                                           |",
        "  +-------------------+-----------------------+",
        "                      |",
        "                      v",
        "        Decision (state/decisions/<UTC>.jsonl)",
        "                      |",
        "                      v",
        "          PaperRunner sim-fill",
        "                      |",
        "                      v",
        "          Dashboard side-by-side render",
        "          vs DeterministicStrategy decisions",
    ]))
    s.append(p("Sibling, not replacement. Both strategies receive the same "
               "MarketEvent stream; both write Decisions; the dashboard renders "
               "them in adjacent columns."))

    # 2. Signal
    s += section("2. The signal: Δ_bps + alignment")
    s.append(p("For each 5-min Polymarket BTC market with window opening at "
               "<font face='Courier'>t = window_ts</font> and Binance BTCUSDT "
               "spot prices <font face='Courier'>S0</font> at window open and "
               "<font face='Courier'>St</font> at the time the bot considers "
               "entering:"))
    s.append(code(["    Δ_bps = 10000 * (St - S0) / S0"]))
    s.append(p("<b>Sign convention:</b>"))
    s.append(bullet("Δ_bps &gt; 0 ⇒ spot has moved UP since window open."))
    s.append(bullet("Δ_bps &lt; 0 ⇒ spot has moved DOWN since window open."))
    s.append(bullet("Δ_bps ≈ 0 ⇒ spot is flat (|Δ|&lt;5)."))
    s.append(p("<b>Alignment:</b> UP side is aligned with Δ&gt;0; DOWN side is "
               "aligned with Δ&lt;0. The strategy <b>only</b> considers the "
               "aligned side. Contrarian and flat trades are off-table."))

    # 3. Trigger
    s += section("3. The trigger: thresholded + aligned")
    s.append(code([
        "fire BUY on side X iff:",
        "  X is aligned with sign(Δ_bps)         AND",
        "  Δ_min ≤ |Δ_bps| ≤ Δ_max               AND",
        "  price-tier filter passes (§4)          AND",
        "  EV check passes (§5)",
    ]))
    s.append(p("<b>Δ_min default = 8 bps</b> (midpoint of [5, 10] candidate "
               "space). <b>Δ_max ceiling = 50 bps</b> — past this point the "
               "data shows mean-reversion takes over and per-trade PnL flips "
               "negative. First paper-soak measures hit-rate and per-trade "
               "PnL across {5, 7, 8, 10} and locks the value at gate close."))

    # 4. Tier filter
    s += section("4. The price-tier filter (lesson from the scout)")
    s.append(p("Reject any candidate where the entry price is in tier "
               "<b>85–100% implied probability</b>. Reason: Bonereaper's "
               "per-trade PnL in that tier is +$0.40 to +$0.65 before fees, "
               "which 40-60bps fee + slippage cuts to near zero."))
    tier_rows = [
        ["Implied price", "Tier", "Use?", "Why"],
        ["< 0.15", "<15%", "DEFER", "rare; +$8.83/trade but only 722 trades"],
        ["0.15 – 0.30", "15-30%", "small sizing", "aligned WR 25%, $+0.11/trade — thin"],
        ["0.30 – 0.50", "30-50%", "YES — sweet", "aligned WR 45.4%, $+1.17/trade"],
        ["0.50 – 0.70", "50-70%", "YES — sweet", "aligned WR 63.1%, $+0.95/trade"],
        ["0.70 – 0.85", "70-85%", "cautious", "aligned WR 78%, $+0.40/trade"],
        ["0.85 – 1.00", "85-100%", "NO", "aligned WR 91.7%, $+0.65/trade — fees eat it"],
    ]
    s.append(table(tier_rows, widths=[28*mm, 22*mm, 28*mm, 70*mm]))
    s.append(p("The two sweet-spot tiers (30-50% and 50-70%) account for "
               "<b>$55.2k of the $83.1k aligned-trade gross PnL</b> in "
               "Bonereaper's 30-day data — 66% of the alignment edge in 53% of "
               "the alignment trades. That's where our trigger lives.", CALLOUT))

    # 5. EV check
    s += section("5. The EV check")
    s.append(code([
        "p_win  = lookup table value (§6) for (Δ_bps bucket, price tier)",
        "fees   = 0.005 (Polymarket gasless relayer estimate)",
        "edge   = p_win * 1.0  -  (entry_price + fees)",
        "fire iff edge > 0.005   # > 0.5¢ EV per $1 of notional",
    ]))
    s.append(p("This single check is the difference between Bonereaper "
               "(winner) and Slow-Minute (-$3,964 / 7d). Slow-Minute fired on "
               "alignment but never gated on price; bought $0.99 shares and "
               "lost the spread. Our strategy gates explicitly."))

    # 6. Lookup table
    s += section("6. Estimated p_win lookup table")
    s.append(p("Initial values from the 30-day Bonereaper bucket data; updated "
               "weekly from our own paper-soak data, never overwritten without "
               "a ≥200 trades-per-bucket sample. If a (tier, Δ) cell is "
               "missing, the strategy refuses to fire there. "
               "Conservative-by-default."))
    pw_rows = [
        ["Price tier", "Δ_bps bucket", "Initial p_win", "Source-trades"],
        ["30-50%", "5-10 bps", "0.65", "1,200"],
        ["30-50%", "10-20 bps", "0.72", "950"],
        ["30-50%", "20-50 bps", "0.78", "380"],
        ["50-70%", "5-10 bps", "0.74", "6,300"],
        ["50-70%", "10-20 bps", "0.81", "2,100"],
        ["50-70%", "20-50 bps", "0.85", "720"],
        ["70-85%", "5-10 bps", "0.80", "5,200"],
        ["70-85%", "10-20 bps", "0.86", "1,900"],
        ["70-85%", "20-50 bps", "0.88", "600"],
        ["15-30%", "5-10 bps", "0.40", "200"],
        ["15-30%", "10-20 bps", "0.45", "130"],
    ]
    s.append(table(pw_rows, widths=[36*mm, 36*mm, 36*mm, 36*mm]))

    # 7. Architecture
    s += section("7. Architecture: sibling strategy in PaperRunner")
    s.append(code([
        "src/polymarket_bot/strategies/",
        "  __init__.py",
        "  protocol.py            (existing)",
        "  deterministic.py       (existing)",
        "  ensemble.py            (existing — for the LLM ensemble)",
        "  spot_aware.py          (NEW — this strategy)",
        "  spot_aware_priors.py   (NEW — loader + bucket lookup)",
        "data/",
        "  spot_aware_priors.json (NEW — versioned prior table)",
    ]))
    s.append(p("Both strategies share the Strategy protocol. PaperRunner is "
               "extended to host strategies: list[Strategy]; both receive "
               "every event; each Decision is tagged with its strategy name. "
               "Dashboard groups by that field and renders side-by-side."))

    # 8. Sizing
    s += section("8. Sizing")
    s.append(p("<b>$5 flat per trade for the first 100 trades</b> "
               "(locked decision #9). No Kelly logic in this strategy. After "
               "100 paper trades we have a sample to gate against; THAT is "
               "when fractional-Kelly enters the picture. Sizing logic lives "
               "in the executor layer (Phase 6), not this strategy.", CALLOUT))

    # 9. Gate
    s += section("9. Paper-soak gate criteria — REALISTIC")
    s.append(p("This is where the operator's $50–$250/day target gets "
               "reconciled with $1k-bankroll one-market math. The criteria "
               "below are what the strategy must clear in a 7-day paper-soak "
               "before any move toward live trading."))
    s.append(p("<b>Set A — the strategy works:</b>", H3))
    gate_a = [
        ["#", "Metric", "Target", "Why"],
        ["A1", "Fires per day", "30 ≤ fires ≤ 200", "Sanity-check selectivity"],
        ["A2", "Net win rate", "≥ 55%", "Beats coin-flip with margin"],
        ["A3", "Aligned-vs-contrarian gap", "≥ +20pp", "≥ ⅔ of Bonereaper's 30d gap"],
        ["A4", "Per-trade NET PnL", "≥ +$0.20", "After 0.5% fee + slippage"],
        ["A5", "Net daily PnL", "≥ +$5.00", "A1 × A4 lower bound = $6/day"],
        ["A6", "Max drawdown", "≤ 15% of bankroll", "Hard ceiling; halt + review"],
    ]
    s.append(table(gate_a, widths=[12*mm, 50*mm, 36*mm, 50*mm]))
    s.append(p("<b>Set B — the infrastructure works:</b>", H3))
    gate_b = [
        ["#", "Metric", "Target"],
        ["B1", "Zero unhandled exceptions in 7d", "match Phase 5.7 #7"],
        ["B2", "Litestream replicating without errors", "match Phase 5.7 #8"],
        ["B3", "Decision write rate", "≥ 1 per 12h log file"],
        ["B4", "EV-rejection-vs-fire ratio", "log it, don't gate"],
    ]
    s.append(table(gate_b, widths=[12*mm, 80*mm, 56*mm]))

    s.append(p("<b>Why $5/day is the gate, not $50:</b> 288 5-min BTC windows × "
               "30% fire rate = ~86 fires/day max. At $0.30 net per trade scaled to "
               "$5 stake (12.7% of Bonereaper's avg trade size) and a 2× selectivity "
               "boost from our tier filter, the math says $6.55/day NET on a perfect "
               "run. Anything materially higher means we got lucky on a sample, not "
               "that the edge is structural.", CALLOUT))

    # 10. Backtest
    s += section("10. Backtest plan")
    s.append(p("Before the strategy ever runs in paper-soak, it must clear a "
               "backtest against captured ticks + 30 days of Binance BTCUSDT "
               "1m klines (already pulled). For each (Δ_bps, price tier) cell "
               "the backtest's p_win should land within ±5pp of Bonereaper's "
               "bucket WR. Drift beyond that means signal decay or join error."))
    s.append(p("<b>Backtest gate:</b> if A1-A4 cannot be met on 30d of "
               "historical data, do NOT promote to paper-soak. Tighten Δ_min, "
               "expand the tier filter, or re-derive priors from a longer "
               "window. Backtest is a necessary but not sufficient gate; "
               "live microstructure (latency, partial fills, ladder shifts) "
               "still requires paper-soak."))

    # 11. Scaling
    s += section("11. Scaling roadmap to $50–$250/day NET")
    s.append(p("<b>Aspirational, multi-phase. Phases 11.B onward are explicitly "
               "OUT OF SCOPE for this design doc and require their own design "
               "+ gate.</b> Listed here so the long-range target the operator "
               "wants is visible and tracked."))
    scale_rows = [
        ["Phase", "What changes", "Bankroll", "Markets", "Realistic NET ceiling"],
        ["11.A", "$5 stake, 1 market BTC 5m, paper soak", "$1k", "1", "$5–25/day"],
        ["11.B", "Real-money go-live; same stake/market", "$1k", "1", "$5–25/day"],
        ["11.C", "Stake grows with bankroll; $10–25/trade", "$2k–5k", "1", "$20–80/day"],
        ["11.D", "Multi-market: BTC 15m + 1h on top of 5m", "$5k", "3", "$50–150/day"],
        ["11.E", "Cross-asset: ETH 5m/15m/1h", "$7.5k", "6", "$100–250/day"],
        ["11.F", "Sports + calendar effects", "$10k+", "20+", "$200–500/day"],
    ]
    s.append(table(scale_rows, widths=[14*mm, 60*mm, 22*mm, 18*mm, 38*mm]))
    s.append(p("Each phase has its own gate. <b>$50/day is plausible at Phase "
               "11.D — only after</b> 11.A clears the +$5/day paper gate, "
               "11.B clears the same gate live with real fills, and 11.C "
               "demonstrates that bankroll-scaled sizing doesn't break the "
               "per-trade EV math.", CALLOUT))

    # 12. NOT does
    s += section("12. What this doc does NOT do", color=RED)
    s.append(bullet("Does <b>not</b> un-archive locked decision #19 (Bonereaper "
                    "cloning). We are extracting one signal + one discipline, "
                    "not cloning."))
    s.append(bullet("Does <b>not</b> lower locked decision #6's threshold. "
                    "DeterministicStrategy keeps its 0.6pp threshold."))
    s.append(bullet("Does <b>not</b> turn on the LLM ensemble. Decisions #5 "
                    "and #16 stand."))
    s.append(bullet("Does <b>not</b> commit to live trading. Phase 6 still "
                    "gated behind Phase 1B + this strategy's paper-soak gate."))
    s.append(bullet("Does <b>not</b> write code in this commit. Code lands in "
                    "a follow-up commit that imports this doc as the spec."))

    # 13. Icebox
    s += section("13. Open questions / icebox")
    s.append(bullet("Bucket boundary for &lt;15% tier — defer until ≥1k "
                    "paper-soak trades validate the +$8.83/trade headline."))
    s.append(bullet("Δ_min by time-of-day — log it, study after 7d soak."))
    s.append(bullet("Spot source: Binance for now; don't change while priors "
                    "are derived from it."))
    s.append(bullet("Fee model: 0.5% placeholder; measure on real fills at "
                    "Phase 6 prereq."))
    s.append(bullet("Halt sentinel respect: strategy must check "
                    "state/halt.sentinel before firing."))
    s.append(bullet("Decision schema field: confirm 'strategy: str' is on "
                    "Decision before code lands."))

    # 14. Implementation
    s += section("14. Implementation plan (next session)")
    s.append(p("In order, with a failing test before each piece per anti-vibe "
               "rule #2:"))
    impl_rows = [
        ["Step", "What", "LOC est."],
        ["1", "tests/strategies/test_spot_aware.py — failing tests", "~120"],
        ["2", "data/spot_aware_priors.json — initial table", "~50"],
        ["3", "spot_aware.py + spot_aware_priors.py — implementation", "~250"],
        ["4", "_paper/runner.py — host two strategies", "~50"],
        ["5", "scripts/run_backtest.py --strategy=spot_aware", "~30"],
        ["6", "runbooks/gates/spot-aware-paper.sh — 7d audit script", "~80"],
        ["7", "Deploy to VPS, leave running 7 days, dashboard glue", "—"],
        ["8", "Run gate audit, tag spot-aware-paper-pass on green", "—"],
    ]
    s.append(table(impl_rows, widths=[14*mm, 110*mm, 24*mm]))
    s.append(p("Estimated LLM cost: <b>$0</b>. Wall-clock: ~3h code + 7d soak.",
              CALLOUT))

    # Appendix
    s += section("Appendix — quick-reference math")
    s.append(p("<b>Why $5/day net is the gate, not $50:</b>"))
    s.append(code([
        "Bonereaper 30d data:",
        "  306,966 trades × $12.13M notional × 1.94% gross ROI = $234,864 gross",
        "  Net WR = 51.7%; per-trade gross = $0.76; per-trade net ≈ $0.30",
        "",
        "Our scale:",
        "  $5 stake / $39.41 Bonereaper avg = 12.7% of their per-trade size",
        "  288 windows/day × 30% fire rate = 86 fires/day max",
        "  86 × $0.30 × 12.7% = $3.28/day on Bonereaper's blended ROI",
        "",
        "Selectivity boost (we filter heavy favorites):",
        "  86 × $0.30 × 12.7% × 2 = $6.55/day  ⇒  rounded gate = $5/day NET",
    ]))
    s.append(p("<b>Why $50–$250/day appears at scale, not at start:</b>"))
    s.append(p("To 10× from $5/day NET to $50/day NET, we need any combination "
               "of: (a) 2× per-trade EV from better priors after months of "
               "paper data, (b) 2× trade volume from BTC 15m + 1h, (c) 2.5× "
               "stake size from a Kelly-sized larger bankroll. Each is a "
               "separate design + gate. None are in this doc's scope. The "
               "path is visible — that's the operator's actual ask."))

    doc.build(s)
    print(f"wrote {out} ({out.stat().st_size / 1024:.1f} KiB, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    build()
