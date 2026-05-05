"""Build BONEREAPER_STUDY.pdf — focused master plan for the behavioral study system.

A separate, research-focused document from BUILD_SPEC.pdf. Phases labelled A-I
to distinguish from the main bot phases 0-8. Cover and accents shift to purple
to signal "this is the research stream."
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT
from reportlab.platypus import (
    BaseDocTemplate,
    PageTemplate,
    Frame,
    Paragraph,
    Spacer,
    PageBreak,
    Table,
    TableStyle,
    KeepTogether,
    Flowable,
    NextPageTemplate,
)


# ===== Design system (purple accent for research stream) =====
NAVY = HexColor("#0B1F3A")
NAVY_DARK = HexColor("#06142A")
NAVY_SOFT = HexColor("#1B3358")
AMBER = HexColor("#F5A524")
TEAL = HexColor("#1AA39A")
GREEN = HexColor("#23A26D")
RED = HexColor("#E5484D")
PURPLE = HexColor("#7C5CFF")
PURPLE_DK = HexColor("#5B3FE0")
LAVENDER = HexColor("#E6E0FF")
BLUE = HexColor("#3B82F6")
SLATE = HexColor("#475569")
GRAY_900 = HexColor("#0F172A")
GRAY_700 = HexColor("#334155")
GRAY_500 = HexColor("#64748B")
GRAY_300 = HexColor("#CBD5E1")
GRAY_200 = HexColor("#E2E8F0")
GRAY_100 = HexColor("#F1F5F9")
GRAY_50 = HexColor("#F8FAFC")
PAPER = HexColor("#FFFFFF")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_Y = 18 * mm

styles = getSampleStyleSheet()
H1 = ParagraphStyle(
    "H1",
    parent=styles["Heading1"],
    fontName="Helvetica-Bold",
    fontSize=22,
    leading=26,
    textColor=NAVY,
    spaceBefore=4,
    spaceAfter=8,
)
H3 = ParagraphStyle(
    "H3",
    parent=styles["Heading3"],
    fontName="Helvetica-Bold",
    fontSize=11.5,
    leading=15,
    textColor=NAVY_SOFT,
    spaceBefore=8,
    spaceAfter=2,
)
BODY = ParagraphStyle(
    "Body",
    parent=styles["BodyText"],
    fontName="Helvetica",
    fontSize=9.5,
    leading=13.5,
    textColor=GRAY_900,
    spaceBefore=2,
    spaceAfter=4,
    alignment=TA_LEFT,
)
BODY_SM = ParagraphStyle("BodySm", parent=BODY, fontSize=8.5, leading=12, textColor=GRAY_700)
BODY_XS = ParagraphStyle("BodyXs", parent=BODY, fontSize=7.5, leading=10, textColor=GRAY_500)
BULLET = ParagraphStyle(
    "Bullet", parent=BODY, leftIndent=12, bulletIndent=2, spaceBefore=1, spaceAfter=1
)


# ===== Custom flowables =====
class ColorBarHeading(Flowable):
    def __init__(self, text, color=PURPLE, fontsize=17, height=24, sub=None):
        Flowable.__init__(self)
        self.text, self.sub, self.color, self.fontsize = text, sub, color, fontsize
        self.h = height + (16 if sub else 0)

    def wrap(self, w, h):
        self.width = w
        return (w, self.h)

    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.rect(0, 4, 4, self.h - 4, stroke=0, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", self.fontsize)
        c.drawString(14, self.h - self.fontsize, self.text)
        if self.sub:
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 9)
            c.drawString(14, self.h - self.fontsize - 12, self.sub)


class HBar(Flowable):
    def __init__(self, color=GRAY_200, thickness=0.6, top=4, bot=4):
        Flowable.__init__(self)
        self.color, self.t, self.top, self.bot = color, thickness, top, bot

    def wrap(self, w, h):
        self.w = w
        return (w, self.t + self.top + self.bot)

    def draw(self):
        c = self.canv
        c.setStrokeColor(self.color)
        c.setLineWidth(self.t)
        c.line(0, self.bot, self.w, self.bot)


class StatCards(Flowable):
    def __init__(self, items, h=58):
        Flowable.__init__(self)
        self.items, self.h = items, h

    def wrap(self, w, h):
        self.w = w
        return (w, self.h)

    def draw(self):
        c = self.canv
        n = len(self.items)
        gap = 8
        cw = (self.w - gap * (n - 1)) / n
        for i, (val, label, col) in enumerate(self.items):
            x = i * (cw + gap)
            c.setFillColor(GRAY_50)
            c.setStrokeColor(GRAY_200)
            c.setLineWidth(0.6)
            c.roundRect(x, 0, cw, self.h, 6, stroke=1, fill=1)
            c.setFillColor(col)
            c.roundRect(x, 0, 4, self.h, 2, stroke=0, fill=1)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(x + 14, self.h - 24, str(val))
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 8)
            from reportlab.pdfbase.pdfmetrics import stringWidth

            words = label.split()
            lines, cur = [], ""
            for w in words:
                test = (cur + " " + w).strip()
                if stringWidth(test, "Helvetica", 8) <= cw - 22:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = w
            if cur:
                lines.append(cur)
            ly = self.h - 36
            for ln in lines[:2]:
                c.drawString(x + 14, ly, ln)
                ly -= 10


class DataPipelineDiagram(Flowable):
    """Linear-ish flow: chain → ingest → replay → features → AI → dashboard + weights."""

    def __init__(self, height=380):
        Flowable.__init__(self)
        self.h = height

    def wrap(self, w, h):
        self.w = w
        return (w, self.h)

    def _box(self, c, x, y, w, h, label, sub, accent, fill=PAPER, ink=NAVY):
        c.setFillColor(fill)
        c.setStrokeColor(GRAY_300)
        c.setLineWidth(0.7)
        c.roundRect(x, y, w, h, 5, stroke=1, fill=1)
        c.setFillColor(accent)
        c.roundRect(x, y, 3, h, 1.5, stroke=0, fill=1)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + 9, y + h - 14, label)
        if sub:
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 7)
            c.drawString(x + 9, y + h - 24, sub)

    def _arrow(self, c, x1, y1, x2, y2, color=GRAY_500, label=None, label_above=True):
        import math

        c.setStrokeColor(color)
        c.setLineWidth(0.9)
        c.line(x1, y1, x2, y2)
        ang = math.atan2(y2 - y1, x2 - x1)
        s = 4
        c.setFillColor(color)
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - s * math.cos(ang - 0.5), y2 - s * math.sin(ang - 0.5))
        p.lineTo(x2 - s * math.cos(ang + 0.5), y2 - s * math.sin(ang + 0.5))
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        if label:
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 7)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            c.drawString(mx - 24, my + (6 if label_above else -10), label)

    def draw(self):
        c = self.canv
        W, H = self.w, self.h

        # Source row
        src_y = H - 60
        self._box(
            c, 0, src_y, 145, 44, "bonereaper wallet", "0xeebd...eba30", PURPLE, fill=LAVENDER
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(9, src_y + 4, "polymarket.com/@bonereaper")

        self._box(c, 165, src_y, 130, 44, "Polygon RPC", "Alchemy free tier", BLUE)
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(174, src_y + 4, "Polymarket exchange events")

        self._box(
            c, 315, src_y, 200, 44, "Phase 2 captured archives", "ticks/<date>/*.parquet", TEAL
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(324, src_y + 4, "Binance + Coinbase + Chainlink + Polymarket WS")

        # Ingest row
        ing_y = src_y - 70
        self._box(
            c,
            0,
            ing_y,
            295,
            44,
            "src/research/bonereaper_ingest.py",
            "events → trades.parquet",
            AMBER,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(9, ing_y + 4, "(block_ts, decision_ts, slug, side, size, fill, pnl)")

        self._box(
            c,
            315,
            ing_y,
            200,
            44,
            "src/research/state_replay.py",
            "rebuild state at T-30/-15/-10/-5s",
            AMBER,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(324, ing_y + 4, "spot, oracle, OB top-5, our composite")

        # Arrows: src → ingest
        self._arrow(c, 145 / 2, src_y, 145 / 2, ing_y + 44, color=PURPLE)
        self._arrow(c, 165 + 65, src_y, 165 + 65, ing_y + 44, color=BLUE)
        self._arrow(c, 315 + 100, src_y, 315 + 100, ing_y + 44, color=TEAL)

        # Feature extraction
        feat_y = ing_y - 70
        self._box(
            c,
            0,
            feat_y,
            515,
            44,
            "src/research/features.py",
            "labelled dataset:  features → (bonereaper_side, bonereaper_outcome)",
            GREEN,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(
            9,
            feat_y + 4,
            "window-delta, oracle-gap, OB imbalance, last-60s momentum, ttl, oracle staleness, time-of-day",
        )

        self._arrow(c, 145, ing_y, 200, feat_y + 44, color=AMBER)
        self._arrow(c, 415, ing_y, 350, feat_y + 44, color=AMBER)

        # AI agents row
        ai_y = feat_y - 70
        agents = [
            ("Pattern-Hypothesis", "Sonnet 4.6  ·  per-trade rationale", PURPLE),
            ("Anomaly-Spotter", "Haiku 4.5  ·  fingerprint deviations", BLUE),
            ("Disagreement-Narrator", "Sonnet 4.6  ·  bucket-(ii) reports", AMBER),
        ]
        aw = (W - 16) / 3
        for i, (name, sub, col) in enumerate(agents):
            self._box(c, i * (aw + 8), ai_y, aw, 44, name, sub, col, fill=LAVENDER)

        self._arrow(c, 80, feat_y, 80, ai_y + 44, color=GREEN)
        self._arrow(c, W / 2, feat_y, W / 2, ai_y + 44, color=GREEN)
        self._arrow(c, W - 80, feat_y, W - 80, ai_y + 44, color=GREEN)

        # Outputs row
        out_y = ai_y - 70
        self._box(
            c,
            0,
            out_y,
            240,
            50,
            "Streamlit dashboard",
            "dashboard/research.py  ·  localhost only",
            PURPLE,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(
            9,
            out_y + 4,
            "7 tabs: profile, explorer, importance, disagreement, decay, hypotheses, live",
        )

        self._box(
            c, 275, out_y, 240, 50, "weights/<date>.yaml", "feeds main bot Phase 3 backtest", AMBER
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(284, out_y + 4, "feature weights + Tier-3 thresholds derived from study")

        self._arrow(c, 100, ai_y, 100, out_y + 50, color=PURPLE)
        self._arrow(c, W / 2, ai_y, 395, out_y + 50, color=PURPLE)
        self._arrow(c, W - 100, ai_y, 395, out_y + 50, color=AMBER)

        # Footer note
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(
            0,
            6,
            "All offline / batched.  No live trading code path.  Output is features and reports, never orders.",
        )


class DashboardMockup(Flowable):
    """7-tab dashboard layout sketch."""

    def __init__(self, height=300):
        Flowable.__init__(self)
        self.h = height

    def wrap(self, w, h):
        self.w = w
        return (w, self.h)

    def _tab(self, c, x, y, w, h, n, name, desc, color, mvp=False):
        c.setFillColor(GRAY_50)
        c.setStrokeColor(GRAY_300)
        c.setLineWidth(0.6)
        c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
        # title bar
        c.setFillColor(color)
        c.roundRect(x, y + h - 18, w, 18, 3, stroke=0, fill=1)
        c.setFillColor(PAPER)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + 6, y + h - 13, f"{n}. {name}")
        # MVP badge
        if mvp:
            c.setFillColor(AMBER)
            c.setFont("Helvetica-Bold", 6.5)
            c.drawRightString(x + w - 4, y + h - 13, "MVP")
        # description
        c.setFillColor(GRAY_700)
        c.setFont("Helvetica", 7)
        # crude wrap
        from reportlab.pdfbase.pdfmetrics import stringWidth

        words = desc.split()
        lines, cur = [], ""
        for word in words:
            test = (cur + " " + word).strip()
            if stringWidth(test, "Helvetica", 7) <= w - 12:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        ly = y + h - 30
        for ln in lines[:5]:
            c.drawString(x + 6, ly, ln)
            ly -= 8

    def draw(self):
        c = self.canv
        W, H = self.w, self.h

        tabs = [
            (
                "01",
                "Profile",
                "Total trades, rolling 7d/30d/90d win-rate with binomial CI, P&L curve, size dist, UP/DOWN balance, time-of-day heatmap.",
                PURPLE_DK,
                True,
            ),
            (
                "02",
                "Trade Explorer",
                "Sortable/filterable table; click row → reconstructed market state at T-30/-15/-10/-5s with mini spot/oracle/OB charts.",
                BLUE,
                True,
            ),
            (
                "03",
                "Disagreement Matrix",
                "4-bucket heatmap (us_vote × their_vote × outcome). Click cells to drill into specific trades.",
                AMBER,
                True,
            ),
            (
                "04",
                "Feature Importance",
                "Coefficient bars from logistic regression + GBM importance; per-trade SHAP-style local explanation.",
                GREEN,
                False,
            ),
            (
                "05",
                "Edge-Decay",
                "Rolling win-rate with CIs, trade volume timeline, behavior-shift markers, signal-weight history.",
                RED,
                False,
            ),
            (
                "06",
                "AI Hypotheses",
                "Pattern-Hypothesis agent narratives per trade, searchable. Anomaly-Spotter flags. Disagreement-Narrator reports.",
                PURPLE,
                False,
            ),
            (
                "07",
                "Live Comparison",
                "Activates Phase 4+. Side-by-side our decision vs bonereaper's (delayed) on the active window with both rationales.",
                TEAL,
                False,
            ),
        ]

        # 4 + 3 grid
        cols = 4
        gap = 8
        tw = (W - gap * (cols - 1)) / cols
        th = 90
        for i, (n, name, desc, col, mvp) in enumerate(tabs):
            row = i // cols
            colpos = i % cols
            x = colpos * (tw + gap)
            y = H - (row + 1) * (th + gap)
            self._tab(c, x, y, tw, th, n, name, desc, col, mvp)

        # legend
        c.setFillColor(AMBER)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(0, 6, "MVP")
        c.setFillColor(GRAY_700)
        c.setFont("Helvetica", 7)
        c.drawString(
            20,
            6,
            "ships in Phase G (1-3); 4-7 are stretch tabs gated on each prior shipping cleanly.",
        )


class StudyPhaseBlock(Flowable):
    """Per-study-phase card."""

    def __init__(self, letter, color, title, duration, cost, intent, items, gate, rollback):
        Flowable.__init__(self)
        self.letter, self.color, self.title = letter, color, title
        self.duration, self.cost = duration, cost
        self.intent, self.items = intent, items
        self.gate, self.rollback = gate, rollback

    def wrap(self, w, h):
        self.w = w
        item_h = 14 * len(self.items)
        self.H = 32 + 18 + item_h + 18 + 18 + 16
        return (w, self.H)

    def draw(self):
        c = self.canv
        W = self.w
        H = self.H

        c.setFillColor(self.color)
        c.roundRect(0, H - 26, W, 26, 4, stroke=0, fill=1)
        c.setFillColor(PAPER)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(10, H - 18, f"PHASE {self.letter}  ·  {self.title}")
        c.setFont("Helvetica", 9)
        meta = f"{self.duration}   ·   {self.cost}"
        from reportlab.pdfbase.pdfmetrics import stringWidth

        tw = stringWidth(meta, "Helvetica", 9)
        c.drawString(W - tw - 10, H - 18, meta)

        c.setFillColor(GRAY_700)
        c.setFont("Helvetica-Oblique", 8.5)
        c.drawString(0, H - 42, "Intent: " + self.intent)

        y = H - 60
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(0, y, "Tasks")
        y -= 12
        c.setFont("Helvetica", 8.5)
        for it in self.items:
            c.setFillColor(self.color)
            c.circle(4, y + 3, 1.6, stroke=0, fill=1)
            c.setFillColor(GRAY_900)
            c.drawString(12, y, it)
            y -= 14

        c.setFillColor(GRAY_50)
        c.setStrokeColor(GRAY_200)
        c.roundRect(0, y - 16, W, 16, 3, stroke=1, fill=1)
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(6, y - 12, "GATE")
        c.setFillColor(GRAY_900)
        c.setFont("Helvetica", 8.5)
        c.drawString(40, y - 12, self.gate)

        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(0, y - 30, "Rollback: " + self.rollback)


# ===== Cover & frames =====
def cover_page(c, doc):
    c.setFillColor(NAVY_DARK)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(NAVY_SOFT)
    p = c.beginPath()
    p.moveTo(0, PAGE_H)
    p.lineTo(PAGE_W * 0.55, PAGE_H)
    p.lineTo(0, PAGE_H * 0.55)
    p.close()
    c.drawPath(p, stroke=0, fill=1)
    c.setFillColor(PURPLE)
    c.rect(0, PAGE_H - 12, PAGE_W * 0.32, 12, stroke=0, fill=1)
    c.setFillColor(HexColor("#1F1A40"))
    for gx in range(int(PAGE_W * 0.55), int(PAGE_W), 14):
        for gy in range(20, int(PAGE_H * 0.45), 14):
            c.circle(gx, gy, 1.0, stroke=0, fill=1)
    c.setFillColor(PURPLE)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MARGIN_X, PAGE_H - 60, "BEHAVIORAL STUDY  ·  v1  ·  2026")
    title_y = PAGE_H - 240
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN_X, title_y, "bonereaper")
    c.setFillColor(LAVENDER)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(MARGIN_X, title_y - 38, "Behavioral Study")
    c.setStrokeColor(PURPLE)
    c.setLineWidth(3)
    c.line(MARGIN_X, title_y - 56, MARGIN_X + 90, title_y - 56)
    c.setFillColor(HexColor("#9FB3CF"))
    c.setFont("Helvetica", 13)
    c.drawString(
        MARGIN_X, title_y - 82, "AI-led decomposition of one of Polymarket's top 5-min BTC wallets."
    )
    c.drawString(
        MARGIN_X,
        title_y - 100,
        "Output is features, weights, and a research dashboard — not orders.",
    )
    meta_y = 80
    c.setFillColor(HexColor("#7B93B5"))
    c.setFont("Helvetica-Bold", 8)
    for i, label in enumerate(["TARGET WALLET", "PROFILE", "OUTPUT", "STAGE"]):
        c.drawString(MARGIN_X + i * 130, meta_y + 28, label)
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 9)
    addrs = [
        "0xeebd...eba30",
        "polymarket.com/@bonereaper",
        "labelled features + dashboard",
        "pre-Phase A",
    ]
    for i, val in enumerate(addrs):
        c.drawString(MARGIN_X + i * 130, meta_y + 12, val)
    c.setFillColor(PURPLE)
    c.rect(0, 0, PAGE_W, 6, stroke=0, fill=1)


def header_footer(c, doc):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    c.setFillColor(PURPLE)
    c.rect(0, PAGE_H - 4, PAGE_W * 0.18, 4, stroke=0, fill=1)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, PAGE_H - 14, "BONEREAPER BEHAVIORAL STUDY  ·  v1")
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 14, "2026-05-04")
    c.setStrokeColor(GRAY_200)
    c.setLineWidth(0.4)
    c.line(MARGIN_X, 22, PAGE_W - MARGIN_X, 22)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, 12, "Confidential research plan  ·  Hamad")
    c.drawRightString(PAGE_W - MARGIN_X, 12, f"Page {doc.page}")


# ===== Helpers =====
def section_heading(text, color=PURPLE, sub=None):
    return ColorBarHeading(text, color=color, fontsize=17, height=24, sub=sub)


def kv_table(rows, col_widths=None, header=None):
    data = []
    if header:
        data.append(
            [
                Paragraph(
                    f"<b>{h}</b>",
                    ParagraphStyle(
                        "th", parent=BODY_SM, textColor=PAPER, fontName="Helvetica-Bold"
                    ),
                )
                for h in header
            ]
        )
    for r in rows:
        data.append([Paragraph(str(c), BODY_SM) for c in r])
    t = Table(data, colWidths=col_widths, hAlign="LEFT", repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, GRAY_200),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [PAPER, GRAY_50]),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), PAPER),
        ]
    t.setStyle(TableStyle(style))
    return t


def section_block(heading, table_or_flowables):
    items = [Paragraph(f"<b>{heading}</b>", H3)]
    if isinstance(table_or_flowables, list):
        items.extend(table_or_flowables)
    else:
        items.append(table_or_flowables)
    return KeepTogether(items)


def bullet_list(items, marker="●", color="#7C5CFF"):
    return [
        Paragraph(f'<font color="{color}"><b>{marker}</b></font>&nbsp;&nbsp;{it}', BULLET)
        for it in items
    ]


def risk_table_styled(rows):
    sev_color = {"BLOCKER": RED, "MAJOR": AMBER, "MINOR": TEAL}
    data = [
        [
            Paragraph(
                f"<b>{h}</b>",
                ParagraphStyle("th", parent=BODY_SM, textColor=PAPER, fontName="Helvetica-Bold"),
            )
            for h in ["#", "Severity", "Risk", "Mitigation"]
        ]
    ]
    for i, r in enumerate(rows, 1):
        sev = r[0]
        sev_p = Paragraph(f'<font color="{sev_color[sev].hexval()}"><b>{sev}</b></font>', BODY_SM)
        data.append(
            [
                Paragraph(f"<b>{i:02}</b>", BODY_SM),
                sev_p,
                Paragraph(
                    f"<b>{r[1]}</b><br/><font color='#475569' size='7.5'>{r[2]}</font>", BODY_SM
                ),
                Paragraph(r[3], BODY_SM),
            ]
        )
    t = Table(data, colWidths=[18, 60, 200, 230], hAlign="LEFT", repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, GRAY_200),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, GRAY_50]),
            ]
        )
    )
    return t


# ===== Build =====
def build():
    out = "/Users/hamad/Desktop/PolyMarket-5m/pdfs/BONEREAPER_STUDY.pdf"
    doc = BaseDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_Y + 4,
        bottomMargin=MARGIN_Y + 6,
        title="Bonereaper Behavioral Study — Master Plan",
        author="Hamad",
        subject="Behavioral decomposition of a top Polymarket BTC wallet",
    )
    cover_frame = Frame(
        0, 0, PAGE_W, PAGE_H, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0
    )
    content_frame = Frame(
        MARGIN_X,
        MARGIN_Y,
        PAGE_W - 2 * MARGIN_X,
        PAGE_H - 2 * MARGIN_Y - 6,
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame], onPage=cover_page),
            PageTemplate(id="content", frames=[content_frame], onPage=header_footer),
        ]
    )

    story = []
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    # ===== TOC =====
    story.append(
        section_heading(
            "Table of Contents", color=NAVY_SOFT, sub="A focused research-stream master plan"
        )
    )
    toc_rows = [
        ("01", "Executive Summary", "What we're studying and why.", "p. 3"),
        ("02", "Why Study, Not Copy", "Six failure modes of direct copy-trading.", "p. 4"),
        ("03", "Target Profile", "bonereaper wallet identity, observable signals.", "p. 5"),
        ("04", "System Architecture", "Data pipeline diagram end-to-end.", "p. 6"),
        ("05", "AI Agent Roles", "3 offline analyzers; their inputs/outputs/cost.", "p. 7"),
        ("06", "Dashboard Layout", "7-tab Streamlit research console.", "p. 8"),
        ("07", "Phase A — Pre-flight", "Validate target is worth studying. Abort gate.", "p. 9"),
        ("08", "Phase B — Data Ingestion", "Pull on-chain trade history.", "p. 10"),
        ("09", "Phase C — State Reconstruction", "Rebuild market context per trade.", "p. 11"),
        ("10", "Phase D — Feature Engineering", "Build labelled dataset.", "p. 12"),
        ("11", "Phase E — Statistical Analysis", "Fingerprint, importance, disagreement.", "p. 13"),
        ("12", "Phase F — AI-Narrated Insights", "Run the 3 analysis agents.", "p. 14"),
        ("13", "Phase G — Dashboard Build", "Streamlit MVP first; stretch tabs gated.", "p. 15"),
        ("14", "Phase H — Bot Integration", "Feed weights into Phase 3 backtest.", "p. 16"),
        ("15", "Phase I — Decay & Adversarial", "Daily monitor, quarterly check.", "p. 17"),
        ("16", "Output Schemas", "What we ship from this study.", "p. 18"),
        ("17", "Risk Register", "Study-specific risks.", "p. 19"),
        ("18", "Cost & Timeline", "Cumulative spend per phase.", "p. 20"),
        ("19", "Operating Discipline", "Anti-vibe rules apply here too.", "p. 21"),
        ("20", "Sources", "On-chain + Polymarket + ML references.", "p. 22"),
    ]
    toc_num_style = ParagraphStyle(
        "tocnum", parent=BODY, fontName="Helvetica-Bold", fontSize=12, textColor=PURPLE, leading=14
    )
    toc_data = [
        [
            Paragraph(n, toc_num_style),
            Paragraph(f"<b>{title}</b>", BODY_SM),
            Paragraph(f"<font color='{GRAY_500.hexval()}'>{desc}</font>", BODY_XS),
            Paragraph(f"<font color='{GRAY_500.hexval()}'>{p}</font>", BODY_XS),
        ]
        for (n, title, desc, p) in toc_rows
    ]
    toc = Table(toc_data, colWidths=[26, 150, 285, 40], hAlign="LEFT")
    toc.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRAY_200),
            ]
        )
    )
    story.append(toc)
    story.append(PageBreak())

    # ===== Executive Summary =====
    story.append(section_heading("Executive Summary", color=PURPLE, sub="What this document is"))
    story.append(
        Paragraph(
            "This is a focused research-stream master plan: an AI-led behavioral decomposition of "
            "<b>bonereaper</b> (Polymarket wallet <font face='Courier' size='8.5'>0xeebde7a0e019a63e6b476eb425505b7b3e6eba30</font>), "
            "one of the most profitable wallets on the 5-minute BTC up/down markets. "
            "We do not copy-trade. We treat each of their on-chain trades as a high-confidence "
            "label for the market state at decision time, learn what features predict their "
            "entries, and feed the resulting weights into our main bot's strategy.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        StatCards(
            [
                ("≥60%", "Pre-flight win-rate gate (else abort study)", PURPLE),
                ("3", "Offline analysis agents (Anthropic API)", BLUE),
                ("7", "Streamlit dashboard tabs (3 MVP + 4 stretch)", AMBER),
                ("$10-50", "One-time analysis cost; ~$1/wk ongoing", GREEN),
            ]
        )
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>Output of this study:</b>", H3))
    for it in bullet_list(
        [
            "<b>Labelled dataset</b> at <font face='Courier' size='8.5'>state/research/bonereaper/labelled.parquet</font> — every observable trade with reconstructed market state and AI-narrated rationale.",
            "<b>Feature weights</b> at <font face='Courier' size='8.5'>weights/&lt;date&gt;.yaml</font> — versioned, A/B'd against current weights before promotion.",
            "<b>Streamlit research dashboard</b> — localhost only, indexes the labelled dataset live.",
            "<b>Edge-decay monitor</b> — daily cron, Telegram-alerted when bonereaper's edge weakens.",
            "<b>Adversarial-resistance report</b> — quarterly, checks for bait-shaped market correlation.",
        ]
    ):
        story.append(it)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>What we will NEVER build:</b> a real-time copy-trade execution path, a "
            'replay-with-1-second-lag bot, a "buy what they buy" service. This study is '
            "off the live trading critical path entirely.",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Why Study Not Copy =====
    story.append(
        section_heading(
            "Why Study, Not Copy", color=RED, sub="Six reasons direct copy-trading fails"
        )
    )
    fail_modes = [
        (
            "01",
            "Confirmation lag",
            "On Polygon, on-chain confirmation is 1-2s. On a 300s market, by the time you observe their trade, the orderbook has already absorbed it and the edge is gone. Copy-trade returns approach zero as the source approaches sub-second decision latency.",
        ),
        (
            "02",
            "Sample-of-one risk",
            "If bonereaper blows up next month — strategy decay, market regime shift, smart contract bug — your strategy dies with theirs. You have no diagnostic, no recovery, no alternative.",
        ),
        (
            "03",
            "No understanding",
            "When their behavior shifts (and it will), you can't tell why. You can't decide whether to keep mimicking, demote signal weight, or stop. You're reading their actions but not their reasoning.",
        ),
        (
            "04",
            "Adversarial trapping",
            "If a profitable wallet detects copiers, they can place a string of small loss-leader trades to bait copiers into bad positions, then reverse course. Public on-chain wallets are observable by anyone — including the wallet's own operators.",
        ),
        (
            "05",
            "Survivorship bias",
            "bonereaper may be the visible winner of a multi-wallet portfolio — the operator runs N wallets, and we only see the lucky one. Copying any single wallet is biased toward exactly the strategies that look successful in retrospect.",
        ),
        (
            "06",
            "Cost-basis mismatch",
            "They may have maker rebates, fee discounts, or co-located infrastructure that materially changes their breakeven point. The same trade for them at $0.94 fill might be profitable; for you at $0.96 fill, it isn't.",
        ),
    ]
    for n, title, body in fail_modes:
        row = Table(
            [
                [
                    Paragraph(
                        f"<font color='{RED.hexval()}'><b>{n}</b></font>",
                        ParagraphStyle(
                            "big",
                            parent=BODY,
                            fontSize=14,
                            textColor=RED,
                            fontName="Helvetica-Bold",
                            leading=16,
                        ),
                    ),
                    Paragraph(
                        f"<b>{title}</b><br/><font color='{GRAY_700.hexval()}' size='8.5'>{body}</font>",
                        BODY_SM,
                    ),
                ]
            ],
            colWidths=[30, 480],
            hAlign="LEFT",
        )
        row.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRAY_200),
                ]
            )
        )
        story.append(row)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>The reframe:</b> Each bonereaper trade is a high-confidence <i>label</i>. "
            "We learn what <i>features</i> of the market state predict their entries, and use "
            "those features in our own strategy. Output is feature weights, not copy-orders.",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Target Profile =====
    story.append(
        section_heading(
            "Target Profile", color=PURPLE, sub="What we know about bonereaper before we start"
        )
    )
    story.append(
        Paragraph(
            "This page is what we know <i>now</i>. Phase A pulls actual on-chain numbers and "
            "either confirms or kills the study.",
            BODY,
        )
    )
    story.append(Spacer(1, 4))
    story.append(
        section_block(
            "Identifiers",
            kv_table(
                header=["Field", "Value"],
                col_widths=[170, 348],
                rows=[
                    (
                        "Wallet address (Polygon)",
                        "<font face='Courier' size='9'>0xeebde7a0e019a63e6b476eb425505b7b3e6eba30</font>",
                    ),
                    ("Polymarket profile", "polymarket.com/@bonereaper"),
                    (
                        "Markets traded",
                        "Polymarket BTC 5-min up/down (slug pattern: btc-updown-5m-{window_ts})",
                    ),
                    ("Settlement chain", "Polygon mainnet (chainId 137)"),
                    ("Settlement asset", "USDC.e (migration to native USDC tracked separately)"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Observable signals (public on-chain)",
            kv_table(
                header=["Signal", "How we read it"],
                col_widths=[180, 338],
                rows=[
                    (
                        "Trade entries",
                        "Polymarket exchange-contract events filtered by wallet address; events expose market, side, size, fill price.",
                    ),
                    (
                        "Entry timing",
                        "Block timestamp + transaction order; estimate decision time as block_ts − latency budget (typically T-15s to T-5s relative to window close).",
                    ),
                    (
                        "Position outcomes",
                        "Resolution event from Polymarket UMA oracle proposal once the window closes; pair with entry to compute per-trade P&L.",
                    ),
                    (
                        "Bankroll trajectory",
                        "USDC balance over time on the wallet; growth rate and volatility characterize their risk regime.",
                    ),
                    (
                        "Behavior shifts",
                        "Changes in average size, frequency, time-of-day distribution, or UP/DOWN balance signal a strategy change — log them as eras.",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 10))
    story.append(Paragraph("<b>Pre-flight unknowns (Phase A resolves):</b>", H3))
    for it in bullet_list(
        [
            "30/90-day rolling win-rate after fees.",
            "Total trade count over observable window.",
            "Average size + size distribution.",
            "UP/DOWN balance.",
            "Time-of-day entry heatmap.",
            "Behavior-shift dates (visible regime changes).",
        ]
    ):
        story.append(it)
    story.append(PageBreak())

    # ===== System Architecture =====
    story.append(
        section_heading("System Architecture", color=PURPLE, sub="End-to-end data pipeline")
    )
    story.append(
        Paragraph(
            "Three input sources flow into a four-stage offline pipeline. No live trading code "
            "path. Output drops into the main bot's Phase 3 backtest as data, never as orders.",
            BODY,
        )
    )
    story.append(Spacer(1, 4))
    story.append(DataPipelineDiagram(height=380))
    story.append(PageBreak())

    # ===== AI Agent Roles =====
    story.append(
        section_heading(
            "AI Agent Roles",
            color=PURPLE,
            sub="Three offline analyzers — Anthropic API, batched, cached",
        )
    )
    story.append(
        Paragraph(
            "All three agents run offline against the labelled dataset. None are on the live "
            "trading hot path. Total one-time cost ~$10-50 with prompt caching; <$5/week ongoing "
            "as new bonereaper trades land.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Pattern-Hypothesis (Sonnet 4.6)",
            kv_table(
                header=["", ""],
                col_widths=[110, 408],
                rows=[
                    (
                        "<b>Input</b>",
                        "Reconstructed market state at T-30/-15/-10/-5s plus bonereaper's choice.",
                    ),
                    (
                        "<b>Output</b>",
                        "1-paragraph natural-language hypothesis for *why* this trade — written into a `rationale` field on each labelled record.",
                    ),
                    (
                        "<b>Why useful</b>",
                        "Surfaces patterns simple feature extraction misses (e.g. 'oracle is 47s stale; spot has rallied 0.4% in the last 30s; orderbook is selling off — they're betting on the resolution catching up to spot').",
                    ),
                    (
                        "<b>When run</b>",
                        "Once per trade, batched. Re-run for new trades on a daily cron.",
                    ),
                    ("<b>Cost est.</b>", "~$0.005/trade with cache. 5k trades = $25 one-time."),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Anomaly-Spotter (Haiku 4.5)",
            kv_table(
                header=["", ""],
                col_widths=[110, 408],
                rows=[
                    (
                        "<b>Input</b>",
                        "Trade where bonereaper deviates from their typical fingerprint (oversize, off-hour, UP-when-typically-DOWN, etc.).",
                    ),
                    (
                        "<b>Output</b>",
                        'Structured "what\'s different" report: `{deviation_type, magnitude, possible_cause, urgency}`.',
                    ),
                    (
                        "<b>Why useful</b>",
                        "Powers the edge-decay monitor. A spike in anomalies = strategy shift = demote weight.",
                    ),
                    ("<b>When run</b>", "Daily cron over the latest 7 days of trades."),
                    ("<b>Cost est.</b>", "~$0.0005/trade with cache. <$1/week ongoing."),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Disagreement-Narrator (Sonnet 4.6)",
            kv_table(
                header=["", ""],
                col_widths=[110, 408],
                rows=[
                    (
                        "<b>Input</b>",
                        "A bucket-(ii) trade — bonereaper was right, our deterministic strategy was wrong.",
                    ),
                    (
                        "<b>Output</b>",
                        "Structured `{missed_feature, threshold_should_be, context, weight_recommendation}`.",
                    ),
                    (
                        "<b>Why useful</b>",
                        "This is the goldmine output. Feeds directly into weight refits — these reports become the changelog for `weights/<date>.yaml`.",
                    ),
                    (
                        "<b>When run</b>",
                        "Once per phase-D analysis cycle (initial study + quarterly refits).",
                    ),
                    (
                        "<b>Cost est.</b>",
                        "~$0.01/trade with cache. ~500 bucket-(ii) trades = $5 one-time.",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "All three: schema-validated JSON; refusal/malformed → manual review queue. No "
            "agent decision touches a live order.",
            BODY_SM,
        )
    )
    story.append(PageBreak())

    # ===== Dashboard Layout =====
    story.append(
        section_heading(
            "Dashboard Layout",
            color=PURPLE,
            sub="7-tab Streamlit research console — localhost only",
        )
    )
    story.append(
        Paragraph(
            "Built on Streamlit + Plotly + Polars + DuckDB. Reads labelled dataset directly. "
            "Auto-refreshes during dev. <b>Tabs 1-3 are MVP and ship in Phase G.</b> "
            "Tabs 4-7 are stretch goals, each gated on the previous tab shipping cleanly. "
            "This guards against dashboard scope creep eating the analysis budget.",
            BODY,
        )
    )
    story.append(Spacer(1, 4))
    story.append(DashboardMockup(height=240))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "Run via <font face='Courier' size='8.5'>make dashboard</font> → opens "
            "<font face='Courier' size='8.5'>localhost:8501</font>. No deployment, no auth, no "
            "external network access. Cache invalidates when underlying Parquet changes.",
            BODY_SM,
        )
    )
    story.append(PageBreak())

    # ===== Per-phase pages =====
    phase_color = {
        "A": PURPLE,
        "B": BLUE,
        "C": TEAL,
        "D": GREEN,
        "E": AMBER,
        "F": PURPLE_DK,
        "G": NAVY_SOFT,
        "H": SLATE,
        "I": RED,
    }
    phases = [
        (
            "A",
            "Pre-flight & Validation",
            "0.5 day",
            "$0",
            "Pull bonereaper's on-chain history. Compute the abort criteria. If the wallet doesn't justify a study, stop here.",
            [
                "Set up read-only Polygon RPC access (Alchemy free tier; same as main bot Phase 2).",
                "Implement scripts/research/quick_audit.py: enumerate Polymarket exchange events from address, parse to (block_ts, market, side, size, fill, pnl).",
                "Compute: total trades, 30/90-day rolling win-rate after fees, total volume, average size, behavior-shift dates.",
                "Plot quick-look matplotlib figures (no Streamlit yet) into runbooks/study/quick-audit.html.",
                "Document the abort criteria pass/fail in runbooks/study/preflight-decision.md.",
            ],
            "30-day rolling win-rate ≥ 60% AND ≥500 trades observable AND no >40% volume drop in last 30 days. If any criterion fails: abort the entire study; do not design Phase B.",
            "If abort: pick a different reference wallet or skip the study. Time spent: ½ day. No code in src/, only scripts/.",
        ),
        (
            "B",
            "Data Ingestion",
            "1-2 days",
            "$0",
            "Production-grade pipeline that captures every bonereaper trade going forward and backfills history.",
            [
                "Design doc: design/research/ingest.md — schema, retry policy, idempotency.",
                "Implement src/research/bonereaper_ingest.py with backfill mode (historical) and tail mode (new blocks).",
                "Schema for trades.parquet: (block_ts_utc, decision_ts_estimate, tx_hash, market_slug, window_ts, side, size_usd, fill_price, eventual_pnl, settled_at).",
                "Idempotency: re-running the backfill with the same start block produces an identical Parquet (deterministic).",
                "Tests: replay a fixture log, assert exact match on schema.",
            ],
            "make verify-phase-B exits 0 (mypy + ruff green; backfill produces ≥ Phase A audit count; tail mode runs 24h without gaps).",
            "Schema mismatch: bump schema version, write migrator. Idempotency broken: investigate; never commit non-deterministic ingestion.",
        ),
        (
            "C",
            "Market-State Reconstruction",
            "1-2 days",
            "$0",
            "For every bonereaper trade, rebuild the market state at T-30s/T-15s/T-10s/T-5s relative to window close, from our captured Phase 2 archives.",
            [
                "Design doc: design/research/state_replay.md — how we map block_ts → window_ts → window_open_ts → reconstruction timestamps.",
                "Implement src/research/state_replay.py.",
                "For each trade: read Phase 2 ticks/<date>/{binance,coinbase,oracle,polymarket}.parquet around window_ts ± 5 min.",
                "Compute snapshots: spot top-of-book + microprice (both venues), Chainlink last-answer + age, Polymarket OB top-5, our deterministic composite at that instant.",
                "Tests: synthetic fixtures with known state, assert reconstruction matches.",
            ],
            "make verify-phase-C exits 0 (reconstruction succeeds for ≥98% of phase-B trades; failed trades logged with cause; spot/oracle timestamps internally consistent).",
            "Phase-2 data gaps: extend Phase 2 capture window. Don't fake state.",
        ),
        (
            "D",
            "Feature Engineering",
            "1 day",
            "$0",
            "Build the labelled dataset that everything else feeds off.",
            [
                "Design doc: design/research/features.md — exact feature definitions with units and edge cases.",
                "Implement src/research/features.py producing labelled.parquet.",
                "Feature catalog: window-delta (%), oracle-vs-spot gap (%), oracle staleness (s), last-60s tick momentum, OB imbalance (top-5), time-to-close (s), recent realized vol, time-of-day (UTC hour bucket), implied confidence (from token price paid).",
                "Outcome columns: bonereaper_side ∈ {UP, DOWN}, bonereaper_outcome ∈ {WIN, LOSE}.",
                "Tests: every feature has a deterministic computation and a unit test.",
            ],
            "make verify-phase-D exits 0 (mypy + ruff + tests green; labelled.parquet has ≥99% non-null feature rows).",
            "High null rate in a feature: that feature isn't reliably reconstructible from current data; drop it or extend Phase 2 capture.",
        ),
        (
            "E",
            "Statistical Analysis",
            "1-2 days",
            "$0",
            "Three analyses on the labelled dataset. No LLMs yet — pure stats and ML.",
            [
                "Behavioral fingerprint: distributions of size, time-of-day, UP/DOWN, implied conf, time-to-close at entry. Output: runbooks/study/fingerprint.md + plots.",
                "Feature importance: logistic regression first, gradient-boosted trees second, both predicting bonereaper_side from features. Output: runbooks/study/feature_importance.md with coefficient bars.",
                "Disagreement matrix: for each trade, compute what our deterministic Tier-3 + ensemble would have done at the same instant; bucket (i)-(iv); count + drill-down.",
                "All three analyses reproducible from labelled.parquet via a single make analysis command.",
            ],
            "make verify-phase-E exits 0 (three reports exist; bucket-(ii) count > 0; importance ranking has at least one feature with |coef| > 2× the mean).",
            "If bucket-(ii) is empty: either we're already aligned with bonereaper (great — but suspicious), or our reconstruction is wrong (investigate).",
        ),
        (
            "F",
            "AI-Narrated Insights",
            "2-3 days",
            "$10-50 one-time + ~$1/wk",
            "Run the three Anthropic agents over the labelled dataset.",
            [
                "Top up Anthropic credits to ≥$50 for a clean one-time run.",
                "Implement src/research/agents/{pattern_hypothesis,anomaly_spotter,disagreement_narrator}.py with cached system prompts and per-trade dynamic blocks.",
                "JSON schemas committed in design/research/agent_schemas.md; pydantic validation; refusal → manual review queue (state/research/review/).",
                "Cost-tracker hard-kill at $50 one-time, $5/day ongoing.",
                "Output: rationale, anomaly_flag, narrator_report fields on labelled.parquet (or a sidecar table joined on tx_hash).",
            ],
            "make verify-phase-F exits 0 (≥95% of trades have valid rationale; refusal rate <5%; total spend ≤ $50).",
            "Refusal rate >5%: tighten prompt, retry. If still high: that's a real signal that some trades are too ambiguous — log and review.",
        ),
        (
            "G",
            "Dashboard Build",
            "2-3 days for MVP; stretch ongoing",
            "$0",
            "Streamlit MVP first (3 tabs). Stretch tabs gated on each prior shipping clean.",
            [
                "Design doc: design/research/dashboard.md — wireframes for all 7 tabs, MVP cut.",
                "Implement dashboard/research.py with tabs: 01 Profile, 02 Trade Explorer, 03 Disagreement Matrix.",
                "Stack: Streamlit + Plotly + Polars + DuckDB; reads labelled.parquet directly; no copies.",
                "make dashboard launches localhost:8501.",
                "Stretch tabs (in order): 04 Feature Importance, 05 Edge-Decay, 06 AI Hypotheses, 07 Live Comparison.",
                "Each stretch tab is its own design doc + impl + ship. Don't start tab N+1 until tab N is in use.",
            ],
            "MVP gate: bash runbooks/gates/phase-G.sh exits 0 (3 tabs render; click-through smoke test on each; no Python exceptions in logs over 1h interaction).",
            "Streamlit perf issues at scale: pre-aggregate in DuckDB. Don't compute live on every interaction.",
        ),
        (
            "H",
            "Bot Integration",
            "0.5-1 day",
            "$0",
            "Take the study's outputs and wire them into the main bot. Same uplift gate as the LLM ensemble: ≥3pp or it doesn't ship.",
            [
                "Generate weights/<date>.yaml from feature importance ranking (D) + disagreement-narrator recommendations (F).",
                "Run main bot Phase 3 backtest with new weights vs current weights as A/B.",
                "If uplift ≥ 3pp after fees AND no new failure mode: promote weights. Else: shelve the run, document why in runbooks/study/weight-runs/<date>.md.",
                "Optional 4th ensemble agent (`behavioral_mimic`): fires only when reconstructed features strongly match bonereaper's historical entry pattern. Same ≥3pp uplift gate to retain.",
            ],
            "Promotion gate: A/B uplift ≥ 3pp after fees AND no regression in any kill-switch metric.",
            "Promotion blocked: do not ship. Shelved weights are still useful research; no harm.",
        ),
        (
            "I",
            "Decay & Adversarial Monitoring",
            "ongoing",
            "<$5/wk",
            "Daily monitor on bonereaper's edge. Quarterly adversarial-resistance check.",
            [
                "Daily cron: rolling 30-day win-rate + volume; trigger if win-rate < 60% sustained 14 days OR volume drop > 50% MoM. Action: demote signal weight, write runbooks/incidents/edge-decay-<date>.md, page Telegram.",
                "Weekly: re-run Anomaly-Spotter on last 7 days of trades; flagged anomaly count > 2× baseline → page Telegram.",
                "Quarterly: adversarial-resistance check — correlation between bonereaper entries and bait-shaped market states (deep liq gaps, extreme OB imbalance, news event windows). High correlation → weight against mimicking on those state shapes.",
                "All monitors run on the laptop or VPS as systemd-timer units, not interactive.",
            ],
            "Monitors are running for ≥ 14 calendar days with no missed runs and no false-positive cascades.",
            "Monitor false-positives: tighten thresholds. False-negatives (missed obvious decay): widen lookback or add features.",
        ),
    ]

    for letter, title, dur, cost, intent, items, gate, rollback in phases:
        story.append(
            StudyPhaseBlock(
                letter, phase_color[letter], title, dur, cost, intent, items, gate, rollback
            )
        )
        story.append(PageBreak())

    # ===== Output Schemas =====
    story.append(
        section_heading(
            "Output Schemas", color=GREEN, sub="What every phase ships, in concrete form"
        )
    )
    story.append(
        section_block(
            "trades.parquet (Phase B output)",
            kv_table(
                header=["Column", "Type", "Description"],
                col_widths=[160, 70, 288],
                rows=[
                    ("block_ts_utc", "datetime[ns]", "On-chain block timestamp, UTC."),
                    (
                        "decision_ts_estimate",
                        "datetime[ns]",
                        "block_ts minus typical confirmation latency (≈2s on Polygon).",
                    ),
                    ("tx_hash", "str", "Polygon transaction hash, primary key."),
                    ("market_slug", "str", "btc-updown-5m-{window_ts}."),
                    (
                        "window_ts",
                        "int64",
                        "Unix-seconds window-open timestamp (divisible by 300).",
                    ),
                    ("side", "enum", "{UP, DOWN}."),
                    ("size_usd", "float64", "Stake in USDC."),
                    ("fill_price", "float64", "Token price paid, in [0,1]."),
                    (
                        "eventual_pnl",
                        "float64",
                        "Realized after settlement (NULL until window resolves).",
                    ),
                    ("settled_at", "datetime[ns]", "Resolution timestamp, UTC."),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "labelled.parquet (Phase D output, joined on tx_hash)",
            kv_table(
                header=["Column group", "Examples"],
                col_widths=[170, 348],
                rows=[
                    ("Identity", "tx_hash, window_ts, side, eventual_pnl"),
                    (
                        "State T-30s",
                        "spot_binance_30, spot_coinbase_30, oracle_30, oracle_age_30, ob_top5_30, our_composite_30",
                    ),
                    ("State T-15s", "(same fields suffixed _15)"),
                    ("State T-10s", "(same fields suffixed _10)"),
                    ("State T-5s", "(same fields suffixed _5)"),
                    (
                        "Features",
                        "window_delta, oracle_gap, ob_imbalance, momentum_60s, ttl_s, oracle_staleness, time_of_day_bucket, implied_conf",
                    ),
                    (
                        "Outcomes",
                        "bonereaper_side, bonereaper_outcome, our_side_at_decision, our_outcome_if_traded",
                    ),
                    ("Bucket", "i_aligned_correct, ii_we_missed, iii_we_caught, iv_both_wrong"),
                    (
                        "AI annotations",
                        "rationale (str), anomaly_flag (bool), narrator_report (json)",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "weights/<date>.yaml (Phase H output)",
            kv_table(
                header=["Field", "Description"],
                col_widths=[170, 348],
                rows=[
                    ("version", "ISO date + git sha of the producing study."),
                    ("source", "always 'bonereaper-study'."),
                    ("features.<name>.weight", "feature weights for the deterministic strategy."),
                    ("tier3_threshold", "composite confidence threshold at which Tier-3 fires."),
                    ("ab_uplift_pp", "measured win-rate uplift over the previous weights."),
                    (
                        "decay_signal_weight",
                        "[0,1] multiplier; reduced when bonereaper edge weakens.",
                    ),
                    (
                        "notes",
                        "freeform — what changed and why; cites which disagreement-narrator reports drove the weight changes.",
                    ),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Risk Register =====
    story.append(
        section_heading("Risk Register", color=RED, sub="Study-specific risks and mitigations")
    )
    risks = [
        (
            "BLOCKER",
            "Pre-flight wallet underperforms",
            "If bonereaper's actual on-chain win-rate is below ~60%, the entire premise dies.",
            "Phase A is a hard gate. Abort the study cleanly; pick a different wallet or skip.",
        ),
        (
            "BLOCKER",
            "Phase-2 data gaps",
            "State reconstruction needs the captured archives; gaps make it impossible.",
            "Don't start Phase C until Phase 2 of the main bot has 30+ days clean. If gaps appear: extend capture, never fake state.",
        ),
        (
            "MAJOR",
            "Survivorship bias",
            "bonereaper may be the visible winner of a multi-wallet portfolio; mimicking biases toward retrospect-lucky strategies.",
            "In Phase E, check for clustering of similar-style wallets at similar IPs/timing. Note in the report. Apply inverse-probability-weighted feature importance if multi-wallet pattern detected.",
        ),
        (
            "MAJOR",
            "Adversarial baiting",
            "If bonereaper detects copiers/observers, they can plant loss-leader trades to corrupt the labelled set.",
            "Phase I quarterly check. If correlation with bait-shaped states is high, weight strongly against mimicking those state shapes — possibly invert.",
        ),
        (
            "MAJOR",
            "Cost-basis mismatch",
            "Their breakeven might differ from ours due to maker rebates, fee discounts, or co-location.",
            "Phase D includes implied_conf (from price paid); Phase H A/B explicitly tests our cost basis, not theirs. Don't promote weights that need their cost basis to be profitable.",
        ),
        (
            "MAJOR",
            "Edge decay between study and live",
            "Their strategy ages; weights from a 3-month-old study may already be stale by the time we ship.",
            "Phase I daily monitor. Weight refits gated on live A/B at promotion. Quarterly full refit minimum.",
        ),
        (
            "MINOR",
            "Schema drift",
            "Feature definitions may evolve; older labelled rows become incompatible.",
            "Schema versioning on labelled.parquet. Migrators committed alongside any schema change.",
        ),
        (
            "MINOR",
            "Anthropic credit blow-up during F",
            "Pattern-Hypothesis over a large dataset can chew $50 fast without cache discipline.",
            "Cost-tracker hard-kill at $50 one-time. Cache the system prompt as an explicit breakpoint.",
        ),
        (
            "MINOR",
            "Streamlit perf at scale",
            "5k-trade dashboard with on-the-fly aggregation can hang the browser tab.",
            "Pre-aggregate in DuckDB. Don't render >500 raw points in any chart; bin/sample as needed.",
        ),
        (
            "MINOR",
            "Reading public on-chain data — ToS",
            "Polymarket positions are public on-chain — but always sanity-check ToS.",
            "Quote the relevant ToS section in design/research/ingest.md before shipping the ingester. If ambiguous, escalate.",
        ),
    ]
    story.append(risk_table_styled(risks))
    story.append(PageBreak())

    # ===== Cost & Timeline =====
    story.append(section_heading("Cost & Timeline", color=BLUE, sub="Per-phase cumulative spend"))
    story.append(
        kv_table(
            header=["Phase", "Wall-clock", "Cost", "Cumulative", "Driver"],
            col_widths=[100, 90, 90, 90, 148],
            rows=[
                ("A — Pre-flight", "0.5 day", "$0", "$0", "—"),
                ("B — Ingestion", "1-2 days", "$0", "$0", "Alchemy free tier"),
                ("C — State Replay", "1-2 days", "$0", "$0", "Local compute on Phase 2 archives"),
                ("D — Feature Eng.", "1 day", "$0", "$0", "Pure Python"),
                ("E — Stat. Analysis", "1-2 days", "$0", "$0", "scikit-learn local"),
                (
                    "F — AI Insights",
                    "2-3 days",
                    "$10-50 one-time",
                    "$10-50",
                    "Anthropic API (cached)",
                ),
                ("G — Dashboard MVP", "2-3 days", "$0", "$10-50", "Streamlit local"),
                (
                    "H — Bot Integration",
                    "0.5-1 day",
                    "API calls in main bot Phase 3",
                    "$10-50 + main-bot Phase 3",
                    "Backtest re-run",
                ),
                ("I — Monitoring", "ongoing", "<$5/wk", "ongoing", "Daily Anomaly-Spotter calls"),
            ],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "<b>Total elapsed:</b> ~10-14 working days across Phases A-G if focused. Phase H is "
            "gated on the main bot reaching its own Phase 3. Phase I runs forever as a daemon. "
            "<b>Total one-time cost:</b> $10-50 (Anthropic). <b>Ongoing:</b> &lt;$5/week.",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Operating Discipline =====
    story.append(
        section_heading(
            "Operating Discipline", color=AMBER, sub="Same anti-vibe-coding rules apply"
        )
    )
    story.append(
        Paragraph(
            "The 25 rules from BUILD_SPEC apply identically here. Three additions specific to a "
            "research stream:",
            BODY,
        )
    )
    story.append(Spacer(1, 8))

    extra_rules = [
        (
            "Research stream",
            PURPLE,
            [
                (
                    "Every analysis is reproducible from labelled.parquet via a single make command. If you can't reproduce it tomorrow morning from a clean checkout, it doesn't ship.",
                    "Notebooks-as-source-of-truth is exactly the kind of drift this project is built to avoid.",
                ),
                (
                    "Findings without a causal story are entertainment, not research. Every shipped weight change cites at least one Disagreement-Narrator report and one feature-importance result.",
                    "Without the story, you can't tell whether the win is real or noise — and you can't defend it next month when it stops working.",
                ),
                (
                    "The dashboard is a tool, not a deliverable. If you spent a day on dashboard polish and didn't change weights or insights, it was a wasted day.",
                    "Streamlit is fast to prototype precisely because it's also fast to over-prototype.",
                ),
            ],
        ),
    ]
    for group, color, items in extra_rules:
        story.append(Paragraph(f"<b>{group}</b>", H3))
        for rule, why in items:
            row = Table(
                [
                    [
                        Table(
                            [[""]],
                            colWidths=[6],
                            rowHeights=[34],
                            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), color)]),
                        ),
                        Paragraph(
                            f"<b>{rule}</b><br/>"
                            f"<font color='{GRAY_500.hexval()}' size='8'>{why}</font>",
                            BODY_SM,
                        ),
                    ],
                ],
                colWidths=[6, 504],
                hAlign="LEFT",
            )
            row.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (0, -1), 0),
                        ("RIGHTPADDING", (0, 0), (0, -1), 0),
                        ("LEFTPADDING", (1, 0), (1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                )
            )
            story.append(row)
        story.append(Spacer(1, 6))
    story.append(PageBreak())

    # ===== Sources =====
    story.append(
        section_heading(
            "Sources & References", color=BLUE, sub="Primary data sources, tooling, prior art"
        )
    )
    story.append(
        section_block(
            "Target & Polymarket",
            kv_table(
                rows=[
                    ("bonereaper Polymarket profile", "polymarket.com/@bonereaper"),
                    ("Polymarket Developer Docs", "docs.polymarket.com/developers/"),
                    (
                        "Polymarket Exchange contract",
                        "Polygon mainnet — see py-clob-client constants",
                    ),
                    ("py-clob-client (event parsing)", "github.com/Polymarket/py-clob-client"),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Polygon / on-chain",
            kv_table(
                rows=[
                    ("Alchemy Polygon RPC", "alchemy.com (free tier sufficient)"),
                    ("PolygonScan", "polygonscan.com (manual verification)"),
                    (
                        "Chainlink BTC/USD on Polygon",
                        "data.chain.link/feeds/polygon/mainnet/btc-usd",
                    ),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "ML / analysis",
            kv_table(
                rows=[
                    ("scikit-learn (logistic, GBM)", "scikit-learn.org"),
                    ("SHAP (feature importance)", "shap.readthedocs.io"),
                    ("Polars (fast Parquet)", "pola-rs.github.io"),
                    ("DuckDB (ad-hoc SQL)", "duckdb.org"),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Dashboard",
            kv_table(
                rows=[
                    ("Streamlit", "streamlit.io"),
                    ("Plotly Python", "plotly.com/python/"),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Companion documents",
            kv_table(
                rows=[
                    ("Main bot master plan", "/Users/hamad/Desktop/PolyMarket-5m/MASTERPLAN.md"),
                    (
                        "Main bot build spec PDF",
                        "/Users/hamad/Desktop/PolyMarket-5m/BUILD_SPEC.pdf",
                    ),
                    ("Main bot execution runbook", "/Users/hamad/Desktop/PolyMarket-5m/RUNBOOK.md"),
                    ("Locked decisions memory", "memory/project_decisions.md"),
                ],
                col_widths=[260, 258],
            ),
        )
    )

    story.append(Spacer(1, 12))
    story.append(HBar(color=GRAY_300, thickness=0.6))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "<font color='#64748B'><i>Living document. The labelled dataset and dashboard are "
            "the persistent artifacts; this PDF is the spec they implement. Refresh quarterly.</i></font>",
            BODY_SM,
        )
    )

    doc.build(story)
    return out


if __name__ == "__main__":
    out = build()
    print(f"Built: {out}")
