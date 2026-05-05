"""
Build a professional, designed PDF of the Polymarket 5m bot master plan.
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, inch
from reportlab.lib import colors
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
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
    HRFlowable,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.pdfgen import canvas
from reportlab.graphics.shapes import (
    Drawing,
    Rect,
    String,
    Line,
    Polygon,
    Circle,
    Path,
    Group,
    PolyLine,
)
from reportlab.graphics import renderPDF


# ---------- Design system ----------
NAVY = HexColor("#0B1F3A")
NAVY_DARK = HexColor("#06142A")
NAVY_SOFT = HexColor("#1B3358")
AMBER = HexColor("#F5A524")
AMBER_DK = HexColor("#C77D00")
TEAL = HexColor("#1AA39A")
GREEN = HexColor("#23A26D")
RED = HexColor("#E5484D")
PURPLE = HexColor("#7C5CFF")
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
INK = HexColor("#0B1220")

PAGE_W, PAGE_H = A4
MARGIN_X = 18 * mm
MARGIN_Y = 18 * mm

# ---------- Styles ----------
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
H2 = ParagraphStyle(
    "H2",
    parent=styles["Heading2"],
    fontName="Helvetica-Bold",
    fontSize=15,
    leading=20,
    textColor=NAVY,
    spaceBefore=10,
    spaceAfter=6,
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
BODY_SM = ParagraphStyle(
    "BodySm",
    parent=BODY,
    fontSize=8.5,
    leading=12,
    textColor=GRAY_700,
)
BULLET = ParagraphStyle(
    "Bullet",
    parent=BODY,
    leftIndent=12,
    bulletIndent=2,
    spaceBefore=1,
    spaceAfter=1,
)
CALLOUT = ParagraphStyle(
    "Callout",
    parent=BODY,
    fontSize=10,
    leading=14,
    textColor=NAVY_DARK,
)
COVER_TITLE = ParagraphStyle(
    "CoverTitle",
    parent=styles["Title"],
    fontName="Helvetica-Bold",
    fontSize=40,
    leading=44,
    textColor=PAPER,
    alignment=TA_LEFT,
    spaceAfter=8,
)
COVER_SUB = ParagraphStyle(
    "CoverSub",
    parent=styles["Title"],
    fontName="Helvetica",
    fontSize=15,
    leading=20,
    textColor=HexColor("#CFE3FF"),
    alignment=TA_LEFT,
    spaceAfter=14,
)
COVER_TAG = ParagraphStyle(
    "CoverTag",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=9.5,
    leading=13,
    textColor=AMBER,
    alignment=TA_LEFT,
)
COVER_META = ParagraphStyle(
    "CoverMeta",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=10,
    leading=14,
    textColor=HexColor("#9FB3CF"),
    alignment=TA_LEFT,
)
TOC_ENTRY = ParagraphStyle(
    "TOC",
    parent=BODY,
    fontSize=10.5,
    leading=18,
    textColor=GRAY_900,
    leftIndent=0,
)
LINK = ParagraphStyle(
    "Link",
    parent=BODY_SM,
    textColor=BLUE,
)
CODE = ParagraphStyle(
    "Code",
    parent=BODY,
    fontName="Courier",
    fontSize=8.5,
    leading=11.5,
    textColor=GRAY_900,
    backColor=GRAY_100,
    leftIndent=8,
    rightIndent=8,
    spaceBefore=4,
    spaceAfter=4,
    borderPadding=8,
)


# ---------- Custom Flowables ----------


class ColorBarHeading(Flowable):
    """A heading with a colored vertical accent bar on the left."""

    def __init__(self, text, color=AMBER, fontsize=15, height=22, sub=None):
        Flowable.__init__(self)
        self.text = text
        self.sub = sub
        self.color = color
        self.fontsize = fontsize
        self.h = height + (16 if sub else 0)
        self.width = PAGE_W - 2 * MARGIN_X

    def wrap(self, w, h):
        self.width = w
        return (w, self.h)

    def draw(self):
        c = self.canv
        # Color bar
        c.setFillColor(self.color)
        c.rect(0, 4, 4, self.h - 4, stroke=0, fill=1)
        # Title
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", self.fontsize)
        c.drawString(14, self.h - self.fontsize, self.text)
        if self.sub:
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 9)
            c.drawString(14, self.h - self.fontsize - 12, self.sub)


class HBar(Flowable):
    def __init__(self, color=GRAY_200, thickness=0.6, width=None, top=4, bot=4):
        Flowable.__init__(self)
        self.color = color
        self.t = thickness
        self.w = width
        self.top = top
        self.bot = bot

    def wrap(self, w, h):
        self.w = self.w or w
        return (w, self.t + self.top + self.bot)

    def draw(self):
        c = self.canv
        c.setStrokeColor(self.color)
        c.setLineWidth(self.t)
        y = self.bot
        c.line(0, y, self.w, y)


class StatCards(Flowable):
    """Row of stat cards used near the cover/exec summary."""

    def __init__(self, items, width=None, h=58):
        # items: list of (value, label, color)
        Flowable.__init__(self)
        self.items = items
        self.w = width
        self.h = h

    def wrap(self, w, h):
        self.w = self.w or w
        return (self.w, self.h)

    def draw(self):
        c = self.canv
        n = len(self.items)
        gap = 8
        cw = (self.w - gap * (n - 1)) / n
        for i, (val, label, col) in enumerate(self.items):
            x = i * (cw + gap)
            # card body
            c.setFillColor(GRAY_50)
            c.setStrokeColor(GRAY_200)
            c.setLineWidth(0.6)
            c.roundRect(x, 0, cw, self.h, 6, stroke=1, fill=1)
            # left accent
            c.setFillColor(col)
            c.roundRect(x, 0, 4, self.h, 2, stroke=0, fill=1)
            # value
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 16)
            c.drawString(x + 14, self.h - 24, str(val))
            # label
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 8)
            # wrap label manually if too long
            label_lines = self._wrap(label, cw - 22, 8)
            ly = self.h - 36
            for ln in label_lines[:2]:
                c.drawString(x + 14, ly, ln)
                ly -= 10

    @staticmethod
    def _wrap(text, max_w, font_size):
        # crude wrap by char count
        from reportlab.pdfbase.pdfmetrics import stringWidth

        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if stringWidth(test, "Helvetica", font_size) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines


class PhaseTimeline(Flowable):
    """Vertical phase timeline with colored chips."""

    def __init__(self, phases, width=None, row_h=46):
        # phases: list of dicts: {n, title, dur, color, bullets:[..], gate}
        Flowable.__init__(self)
        self.phases = phases
        self.w = width
        self.row_h = row_h

    def wrap(self, w, h):
        self.w = self.w or w
        return (self.w, self.row_h * len(self.phases) + 4)

    def draw(self):
        c = self.canv
        x_chip = 0
        chip_d = 28
        line_x = chip_d / 2
        y = self.row_h * (len(self.phases) - 1)
        # main spine
        c.setStrokeColor(GRAY_200)
        c.setLineWidth(2)
        c.line(line_x, 6, line_x, y + chip_d / 2)

        for i, p in enumerate(self.phases):
            yy = (len(self.phases) - 1 - i) * self.row_h
            # chip
            c.setFillColor(p["color"])
            c.circle(line_x, yy + chip_d / 2, chip_d / 2, stroke=0, fill=1)
            c.setFillColor(PAPER)
            c.setFont("Helvetica-Bold", 11)
            label = str(p["n"])
            tw = c.stringWidth(label, "Helvetica-Bold", 11)
            c.drawString(line_x - tw / 2, yy + chip_d / 2 - 3.6, label)
            # title
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 10.5)
            c.drawString(chip_d + 10, yy + chip_d - 6, p["title"])
            # duration pill
            dur = p.get("dur", "")
            if dur:
                pill_w = c.stringWidth(dur, "Helvetica", 7.5) + 12
                pill_x = self.w - pill_w
                c.setFillColor(GRAY_100)
                c.roundRect(pill_x, yy + chip_d - 16, pill_w, 14, 7, stroke=0, fill=1)
                c.setFillColor(GRAY_700)
                c.setFont("Helvetica", 7.5)
                c.drawString(pill_x + 6, yy + chip_d - 12, dur)
            # gate
            if p.get("gate"):
                c.setFillColor(GRAY_500)
                c.setFont("Helvetica-Oblique", 8.5)
                c.drawString(chip_d + 10, yy + chip_d - 20, "Gate: " + p["gate"])


class ArchitectureDiagram(Flowable):
    """Hand-drawn architecture diagram."""

    def __init__(self, width=None, height=380):
        Flowable.__init__(self)
        self.w = width
        self.h = height

    def wrap(self, w, h):
        self.w = self.w or w
        return (self.w, self.h)

    def _box(self, c, x, y, w, h, label, color, sub=None):
        c.setFillColor(color)
        c.setStrokeColor(NAVY_DARK)
        c.setLineWidth(0.7)
        c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
        c.setFillColor(PAPER)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + 8, y + h - 14, label)
        if sub:
            c.setFillColor(HexColor("#E2E8F0"))
            c.setFont("Helvetica", 7)
            c.drawString(x + 8, y + h - 24, sub)

    def _white_box(self, c, x, y, w, h, label, sub=None, accent=AMBER):
        c.setFillColor(PAPER)
        c.setStrokeColor(GRAY_300)
        c.setLineWidth(0.7)
        c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
        # left accent bar
        c.setFillColor(accent)
        c.roundRect(x, y, 3, h, 1.5, stroke=0, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + 9, y + h - 13, label)
        if sub:
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 7)
            c.drawString(x + 9, y + h - 22, sub)

    def _arrow(self, c, x1, y1, x2, y2, color=GRAY_500, dashed=False):
        c.setStrokeColor(color)
        c.setLineWidth(0.9)
        if dashed:
            c.setDash(2, 2)
        c.line(x1, y1, x2, y2)
        c.setDash()
        # arrowhead
        import math

        ang = math.atan2(y2 - y1, x2 - x1)
        s = 4
        c.setFillColor(color)
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - s * math.cos(ang - 0.5), y2 - s * math.sin(ang - 0.5))
        p.lineTo(x2 - s * math.cos(ang + 0.5), y2 - s * math.sin(ang + 0.5))
        p.close()
        c.drawPath(p, stroke=0, fill=1)

    def draw(self):
        c = self.canv
        W, H = self.w, self.h

        # outer container - VPS
        c.setFillColor(GRAY_50)
        c.setStrokeColor(GRAY_300)
        c.setLineWidth(1.0)
        c.roundRect(0, 70, W, H - 70, 8, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(12, H - 18, "Dublin VPS  ·  AWS Lightsail eu-west-1  ·  ~1-5 ms to CLOB")

        # external sources column (left, inside the VPS area top)
        ext_x = 14
        ext_y = H - 70
        ext_w = 110
        sources = [
            ("Binance WS", "BTC/USDT spot ticks"),
            ("Coinbase WS", "BTC/USD redundant feed"),
            ("Polygon RPC", "Chainlink BTC/USD oracle"),
            ("Polymarket WS", "orderbook + fills"),
        ]
        sy = ext_y
        for name, sub in sources:
            self._white_box(c, ext_x, sy - 32, ext_w, 28, name, sub, accent=BLUE)
            sy -= 36

        # processing column (middle)
        mid_x = ext_x + ext_w + 22
        mid_w = 145
        procs = [
            ("spot_feed.py", "Binance + Coinbase aggregator", AMBER),
            ("oracle_watcher.py", "AnswerUpdated subscription", PURPLE),
            ("market_feed.py", "active 5m market WS", TEAL),
            ("signal_engine.py", "window-delta + oracle gap", GREEN),
        ]
        my = ext_y
        for name, sub, col in procs:
            self._white_box(c, mid_x, my - 32, mid_w, 28, name, sub, accent=col)
            my -= 36

        # exec column (right)
        ex_x = mid_x + mid_w + 22
        ex_w = 150
        execs = [
            ("risk_manager.py", "kelly + caps + circuit breaker", RED),
            ("order_router.py", "py-clob-client signed orders", AMBER),
            ("Polymarket CLOB", "REST + WS  ·  eu-west-2", NAVY),
        ]
        ey = ext_y
        for name, sub, col in execs:
            if name == "Polymarket CLOB":
                self._box(c, ex_x, ey - 32, ex_w, 28, name, NAVY, sub)
            else:
                self._white_box(c, ex_x, ey - 32, ex_w, 28, name, sub, accent=col)
            ey -= 36

        # arrows: ext -> mid (4 horizontal)
        for i in range(4):
            y = ext_y - 18 - i * 36
            self._arrow(c, ext_x + ext_w + 1, y, mid_x - 1, y, color=GRAY_500)

        # arrows: mid -> exec (only signal/order)
        # signal_engine -> risk_manager
        self._arrow(c, mid_x + mid_w + 1, ext_y - 18 - 3 * 36, ex_x - 1, ext_y - 18, color=GREEN)
        # risk -> order_router
        self._arrow(c, ex_x + ex_w / 2, ext_y - 32, ex_x + ex_w / 2, ext_y - 36 - 4, color=RED)
        # order_router -> CLOB
        self._arrow(
            c, ex_x + ex_w / 2, ext_y - 36 - 32, ex_x + ex_w / 2, ext_y - 36 - 36 - 4, color=AMBER
        )

        # storage row (bottom inside VPS)
        store_y = 90
        store_w = (W - 28 - 12) / 2
        self._white_box(
            c, 14, store_y, store_w, 30, "trades.db (SQLite)", "PnL & fill log", accent=NAVY_SOFT
        )
        self._white_box(
            c,
            14 + store_w + 12,
            store_y,
            store_w,
            30,
            "ticks/*.parquet",
            "tick + bar archive",
            accent=NAVY_SOFT,
        )

        # observability strip
        c.setFillColor(NAVY_DARK)
        c.setStrokeColor(NAVY_DARK)
        c.roundRect(14, 78, W - 28, 8, 4, stroke=0, fill=1)
        c.setFillColor(AMBER)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(20, 80, "PROMETHEUS  ·  GRAFANA CLOUD  ·  DISCORD ALERTS")

        # Laptop block (outside VPS, bottom)
        c.setFillColor(HexColor("#FEF3C7"))
        c.setStrokeColor(AMBER_DK)
        c.setLineWidth(0.7)
        c.roundRect(0, 0, W, 60, 8, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(12, 46, "Your laptop  ·  Claude Code session")
        c.setFillColor(GRAY_700)
        c.setFont("Helvetica", 8)
        c.drawString(12, 32, "Obsidian vault  <-  obsidian-claude-code-mcp  <-  Claude Code")
        c.drawString(12, 18, "/runbooks  /research  /postmortems  /strategy-notes  /daily")
        c.setFillColor(AMBER_DK)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(12, 6, "Read/write only. NO live trading from laptop.")


class EdgeBars(Flowable):
    """Edge sources ranked bar chart."""

    def __init__(self, items, width=None):
        # items: [(name, weight 0-100, color, sub)]
        Flowable.__init__(self)
        self.items = items
        self.w = width
        self.row_h = 30

    def wrap(self, w, h):
        self.w = self.w or w
        return (self.w, self.row_h * len(self.items))

    def draw(self):
        c = self.canv
        label_w = 165
        bar_x = label_w + 10
        bar_max = self.w - bar_x - 50
        for i, (name, val, col, sub) in enumerate(self.items):
            yy = (len(self.items) - 1 - i) * self.row_h
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(0, yy + 16, name)
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 7.5)
            c.drawString(0, yy + 6, sub)
            # bar bg
            c.setFillColor(GRAY_100)
            c.roundRect(bar_x, yy + 6, bar_max, 14, 3, stroke=0, fill=1)
            # bar fill
            c.setFillColor(col)
            c.roundRect(bar_x, yy + 6, bar_max * (val / 100.0), 14, 3, stroke=0, fill=1)
            # value
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(bar_x + bar_max + 6, yy + 10, f"{val}")


# ---------- Cover & frames ----------


def cover_page(c, doc):
    """First page: bold gradient-feel cover."""
    # background
    c.setFillColor(NAVY_DARK)
    c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)

    # diagonal accent shapes
    c.setFillColor(NAVY_SOFT)
    p = c.beginPath()
    p.moveTo(0, PAGE_H)
    p.lineTo(PAGE_W * 0.55, PAGE_H)
    p.lineTo(0, PAGE_H * 0.55)
    p.close()
    c.drawPath(p, stroke=0, fill=1)

    # amber bar
    c.setFillColor(AMBER)
    c.rect(0, PAGE_H - 12, PAGE_W * 0.32, 12, stroke=0, fill=1)

    # subtle dot grid bottom-right
    c.setFillColor(HexColor("#15294A"))
    for gx in range(int(PAGE_W * 0.55), int(PAGE_W), 14):
        for gy in range(20, int(PAGE_H * 0.45), 14):
            c.circle(gx, gy, 1.0, stroke=0, fill=1)

    # category tag
    c.setFillColor(AMBER)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MARGIN_X, PAGE_H - 60, "MASTER PLAN  ·  v1  ·  2026")

    # main title
    title_y = PAGE_H - 250
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN_X, title_y, "Polymarket")
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN_X, title_y - 42, "BTC 5-Minute Bot")

    # underline
    c.setStrokeColor(AMBER)
    c.setLineWidth(3)
    c.line(MARGIN_X, title_y - 56, MARGIN_X + 90, title_y - 56)

    # subtitle
    c.setFillColor(HexColor("#9FB3CF"))
    c.setFont("Helvetica", 13)
    c.drawString(
        MARGIN_X, title_y - 82, "A phased, design-first build for the up/down prediction markets"
    )
    c.drawString(MARGIN_X, title_y - 100, "on Polygon, settled by Chainlink BTC/USD.")

    # meta row
    meta_y = 80
    c.setFillColor(HexColor("#7B93B5"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(MARGIN_X, meta_y + 28, "OWNER")
    c.drawString(MARGIN_X + 130, meta_y + 28, "STARTED")
    c.drawString(MARGIN_X + 260, meta_y + 28, "VENUE")
    c.drawString(MARGIN_X + 380, meta_y + 28, "HOSTING")

    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(MARGIN_X, meta_y + 12, "Hamad")
    c.drawString(MARGIN_X + 130, meta_y + 12, "2026-05-04")
    c.drawString(MARGIN_X + 260, meta_y + 12, "Polymarket CLOB")
    c.drawString(MARGIN_X + 380, meta_y + 12, "AWS Dublin")

    # bottom strip
    c.setFillColor(AMBER)
    c.rect(0, 0, PAGE_W, 6, stroke=0, fill=1)


def header_footer(c, doc):
    """Header and footer for content pages."""
    # Top thin bar
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    c.setFillColor(AMBER)
    c.rect(0, PAGE_H - 4, PAGE_W * 0.18, 4, stroke=0, fill=1)

    # Header text
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, PAGE_H - 14, "POLYMARKET BTC 5-MIN BOT  ·  MASTER PLAN")
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 14, f"v1  ·  2026-05-04")

    # Footer
    c.setStrokeColor(GRAY_200)
    c.setLineWidth(0.4)
    c.line(MARGIN_X, 22, PAGE_W - MARGIN_X, 22)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, 12, "Confidential planning document  ·  Hamad")
    c.drawRightString(PAGE_W - MARGIN_X, 12, f"Page {doc.page}")


# ---------- Content helpers ----------


def section_heading(text, color=AMBER, sub=None):
    return ColorBarHeading(text, color=color, fontsize=17, height=24, sub=sub)


def section_block(heading, table_or_flowables):
    """Keep an H3 heading with its table together to avoid orphaned headings."""
    items = [Paragraph(f"<b>{heading}</b>", H3)]
    if isinstance(table_or_flowables, list):
        items.extend(table_or_flowables)
    else:
        items.append(table_or_flowables)
    return KeepTogether(items)


def kv_table(rows, col_widths=None, header=None):
    """Two/three column key-value reference table."""
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
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("GRID", (0, 0), (-1, -1), 0.4, GRAY_200),
        ("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [PAPER, GRAY_50]),
    ]
    if header:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR", (0, 0), (-1, 0), PAPER),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, NAVY_DARK),
        ]
    t.setStyle(TableStyle(style))
    return t


def risk_table(rows):
    """Risk register table with color-coded severity."""
    sev_color = {"HIGH": RED, "MED": AMBER, "LOW": TEAL}
    header = ["#", "Severity", "Risk", "Mitigation"]
    data = [
        [
            Paragraph(
                f"<b>{h}</b>",
                ParagraphStyle("th", parent=BODY_SM, textColor=PAPER, fontName="Helvetica-Bold"),
            )
            for h in header
        ]
    ]
    for i, r in enumerate(rows, 1):
        sev = r[0]
        sev_para = Paragraph(
            f'<font color="{sev_color[sev].hexval()}"><b>{sev}</b></font>',
            BODY_SM,
        )
        data.append(
            [
                Paragraph(f"<b>{i:02}</b>", BODY_SM),
                sev_para,
                Paragraph(
                    f'<b>{r[1]}</b><br/><font color="#475569" size="7.5">{r[2]}</font>', BODY_SM
                ),
                Paragraph(r[3], BODY_SM),
            ]
        )
    t = Table(data, colWidths=[18, 50, 200, 240], hAlign="LEFT", repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("GRID", (0, 0), (-1, -1), 0.4, GRAY_200),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [PAPER, GRAY_50]),
            ]
        )
    )
    return t


def bullet_list(items, style=BULLET, marker="•"):
    out = []
    for it in items:
        out.append(
            Paragraph(f'<font color="#F5A524"><b>{marker}</b></font>&nbsp;&nbsp;{it}', style)
        )
    return out


# ---------- Build the document ----------


def build():
    output = "/Users/hamad/Desktop/PolyMarket-5m/pdfs/MASTERPLAN.pdf"

    doc = BaseDocTemplate(
        output,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_Y + 4,
        bottomMargin=MARGIN_Y + 6,
        title="Polymarket BTC 5-Min Bot — Master Plan",
        author="Hamad",
        subject="Phased build plan for a Polymarket BTC 5-min up/down trading bot",
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

    # ---- Cover (just a page break onto the cover template) ----
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    # ---- Table of Contents page ----
    story.append(
        section_heading(
            "Table of Contents", color=NAVY_SOFT, sub="What you'll find in this document"
        )
    )
    toc_rows = [
        ("01", "Executive Summary", "The thesis, edge ranking, and what won't work.", "p. 3"),
        ("02", "Tooling Layout", "The decided stack, Claude integrations, MCP inventory.", "p. 4"),
        ("03", "Architecture", "One diagram, three loops, why the laptop doesn't trade.", "p. 5"),
        (
            "04",
            "Phased Plan (0 - 8)",
            "Foundations through hardening. Each phase has a concrete gate.",
            "p. 6",
        ),
        ("05", "Risk Register", "Severity-tagged risks and their mitigations.", "p. 8"),
        ("06", "Next 60 Minutes", "Decisions to make before Phase 0 begins.", "p. 8"),
        (
            "07",
            "Sources & References",
            "Canonical Polymarket / NautilusTrader / oracle / MCP links.",
            "p. 9",
        ),
    ]
    toc_num_style = ParagraphStyle(
        "tocnum", parent=BODY, fontName="Helvetica-Bold", fontSize=14, textColor=AMBER, leading=16
    )
    toc_data = [
        [
            Paragraph(n, toc_num_style),
            Paragraph(f"<b>{title}</b>", BODY),
            Paragraph(f"<font color='{GRAY_500.hexval()}'>{desc}</font>", BODY_SM),
            Paragraph(f"<font color='{GRAY_500.hexval()}'>{p}</font>", BODY_SM),
        ]
        for (n, title, desc, p) in toc_rows
    ]
    toc = Table(toc_data, colWidths=[34, 122, 305, 40], hAlign="LEFT")
    toc.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                ("LINEBELOW", (0, 0), (-1, -1), 0.4, GRAY_200),
            ]
        )
    )
    story.append(toc)

    story.append(Spacer(1, 18))
    story.append(HBar(color=GRAY_200, top=0, bot=0))
    story.append(Spacer(1, 10))

    # Quick reference legend on TOC page
    story.append(Paragraph("<b>How to read this plan</b>", H3))
    legend_items = [
        ("Phase gates", "Concrete success criteria. Don't advance until they're met.", AMBER),
        (
            "Risk severity",
            "<font color='#E5484D'><b>HIGH</b></font> blocks live trading until mitigated. <font color='#F5A524'><b>MED</b></font> needs a runbook. <font color='#1AA39A'><b>LOW</b></font> is tracked.",
            RED,
        ),
        (
            "Decision points",
            "Bold-marked items in <b>Next 60 Minutes</b> need your sign-off before Phase 0 starts.",
            BLUE,
        ),
        (
            "Living document",
            "Mirror this into the Obsidian vault under /runbooks/MASTERPLAN.md and update at every gate.",
            TEAL,
        ),
    ]
    legend_data = []
    for title, desc, col in legend_items:
        legend_data.append(
            [
                Table(
                    [[""]],
                    colWidths=[10],
                    rowHeights=[28],
                    style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), col)]),
                ),
                Paragraph(
                    f"<b>{title}</b><br/><font color='{GRAY_700.hexval()}' size='8.5'>{desc}</font>",
                    BODY_SM,
                ),
            ]
        )
    legend = Table(legend_data, colWidths=[10, 490], hAlign="LEFT")
    legend.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, -1), 0),
                ("LEFTPADDING", (1, 0), (1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(legend)

    story.append(PageBreak())

    # ---- Page 1: Executive summary / Thesis ----
    story.append(section_heading("Executive Summary", color=AMBER, sub="The thesis in 60 seconds"))
    story.append(Spacer(1, 4))

    story.append(
        Paragraph(
            "Polymarket runs a continuous series of 5-minute binary markets on whether BTC closes higher "
            "or lower than its starting price. Markets are deterministic with windows aligned to "
            "<b>floor(now / 300) * 300</b> and slugs <b>btc-updown-5m-{window_ts}</b>. Resolution is "
            "the Chainlink BTC/USD snapshot at <b>window_ts + 300</b> on Polygon.",
            BODY,
        )
    )
    story.append(
        Paragraph(
            "The exploitable inefficiency: Chainlink BTC/USD on Polygon uses a <b>60-second heartbeat with "
            "no deviation threshold</b>. Spot can move 0.3-0.5% while the resolution oracle is silent. "
            "Pair that with thin orderbooks ($5K-$50K per window) and the empirical fact that "
            "~15-20% of windows resolve based on the final 10 seconds, and there is a real edge if your "
            "infrastructure can read all three signals (spot, oracle, book) faster than the median trader.",
            BODY,
        )
    )

    story.append(Spacer(1, 8))
    story.append(
        StatCards(
            [
                ("60s", "Chainlink heartbeat (no deviation trigger)", AMBER),
                ("1-5ms", "Dublin VPS round-trip to CLOB", TEAL),
                ("$4.75", "Polymarket minimum order size", BLUE),
                ("55-60%", "Backtest target win rate after fees", GREEN),
            ]
        )
    )
    story.append(Spacer(1, 14))

    # Edge ranking
    story.append(Paragraph("<b>Where the edge comes from, ranked</b>", H3))
    story.append(
        EdgeBars(
            [
                ("Oracle latency", 90, AMBER, "60s heartbeat, no deviation threshold"),
                ("Window-delta dominance", 82, GREEN, "single highest-weight signal"),
                ("Last-10s dynamics", 70, PURPLE, "~15-20% of windows decided here"),
                ("Maker rebates (CLOB v2)", 55, TEAL, "100% of taker fees redistributed daily"),
                ("Cross-venue spot arb", 45, BLUE, "Binance/Coinbase ahead of Polymarket UI"),
            ]
        )
    )
    story.append(Spacer(1, 8))

    # Where the edge is NOT
    story.append(Paragraph("<b>Where the edge is NOT</b>", H3))
    not_items = [
        "TA on a 5-minute timeframe — RSI/EMA on 1-min candles is mostly noise.",
        "Manual trading — humans cannot react fast enough at T-10s.",
        "Deep-volume markets — the inefficiency lives in thin orderbooks.",
        "Raw latency racing in eu-west-2 — co-located rivals beat you on round-trips; your edge is signal quality and last-second timing.",
    ]
    for it in bullet_list(not_items):
        story.append(it)

    story.append(PageBreak())

    # ---- Page: Tooling layout ----
    story.append(section_heading("Tooling Layout", color=TEAL, sub="The decided stack"))

    story.append(
        section_block(
            "Core stack",
            kv_table(
                header=["Layer", "Choice", "Why"],
                col_widths=[100, 145, 273],
                rows=[
                    [
                        "Language",
                        "Python 3.11+",
                        "py-clob-client + NautilusTrader native; speed-to-correctness wins for 5-min cadence.",
                    ],
                    [
                        "Trading engine",
                        "NautilusTrader",
                        "Production-grade, deterministic event-driven, official Polymarket adapter, real backtest engine.",
                    ],
                    [
                        "Order client",
                        "Polymarket/py-clob-client",
                        "Official; handles L1 EIP-712 + L2 HMAC-SHA256 signing.",
                    ],
                    [
                        "Spot data",
                        "Binance + Coinbase WS",
                        "Free, low-latency, redundant feeds for BTC/USDT and BTC/USD.",
                    ],
                    [
                        "Oracle truth",
                        "Chainlink BTC/USD on Polygon",
                        "Read via Chainstack / Alchemy / QuickNode RPC.",
                    ],
                    [
                        "Storage",
                        "SQLite + Parquet",
                        "trades.db for fills/PnL, ticks/*.parquet for archive. No external deps.",
                    ],
                    [
                        "VPS",
                        "AWS Lightsail eu-west-1 Dublin",
                        "Sub-5ms to CLOB (London eu-west-2). Avoids UK geo-block.",
                    ],
                    [
                        "Memory vault",
                        "Obsidian + obsidian-claude-code-mcp",
                        "All research / runbooks / postmortems live in vault, MCP-readable.",
                    ],
                    [
                        "Risk",
                        "Kelly fraction + per-window cap + daily breaker",
                        "Standard, audited.",
                    ],
                    [
                        "Monitoring",
                        "Prometheus + Grafana Cloud + Discord",
                        "Free, ops-grade, mobile-friendly alerts.",
                    ],
                    [
                        "Secrets",
                        "direnv + age-encrypted backup",
                        "No cloud secret manager required at this scale.",
                    ],
                    [
                        "Process supervisor",
                        "systemd unit",
                        "Auto-restart, journalctl logs, no extra install.",
                    ],
                ],
            ),
        )
    )

    story.append(Spacer(1, 12))
    story.append(
        section_block(
            "Claude Code integrations",
            kv_table(
                header=["Tool", "Use"],
                col_widths=[170, 348],
                rows=[
                    ["Claude Code (this CLI)", "Primary dev environment."],
                    [
                        "obsidian-claude-code-mcp",
                        "Read/write the memory vault. Every research note, runbook, postmortem.",
                    ],
                    [
                        "Polymarket/agent-skills",
                        "Drop into ~/.claude/skills/ — official skills for auth, orders, WS, token ops, bridging, neg-risk, gasless.",
                    ],
                    ["gh CLI", "Pulling reference repos: py-clob-client, NautilusTrader, etc."],
                    ["/init", "Generate the project's CLAUDE.md once layout is on disk."],
                    [
                        "/security-review",
                        "Run before each phase that touches signing or fund movement.",
                    ],
                    [
                        "No autonomous trading via MCP",
                        "All live trading runs from the bot binary on Dublin VPS, never from Claude Code.",
                    ],
                ],
            ),
        )
    )

    story.append(Spacer(1, 12))
    story.append(
        section_block(
            "Polymarket-specific MCPs (research / paper only)",
            kv_table(
                header=["Server", "Use"],
                col_widths=[210, 308],
                rows=[
                    [
                        "caiovicentino/polymarket-mcp-server",
                        "45 tools, real-time WS, exposure / order-size limits.",
                    ],
                    [
                        "artvandelay/polymarket-agents",
                        "Research MCP (10 tools): odds, orderbook, spread, history.",
                    ],
                    ["berlinbra/polymarket-mcp", "Read-only market data MCP (lighter)."],
                    [
                        "agent-next/polymarket-paper-trader",
                        "Paper-trading simulator with order books and backtests.",
                    ],
                ],
            ),
        )
    )

    story.append(Spacer(1, 14))

    # ---- Architecture diagram page ----
    story.append(section_heading("Architecture", color=PURPLE, sub="One diagram, three loops"))
    story.append(
        Paragraph(
            "Three concurrent loops keep the bot honest: a <b>resolution loop</b> (per-second) that "
            'answers "what does this market resolve as if it ended now," an <b>execution loop</b> '
            "(T-30s, T-10s, T-5s deadlines) that fires orders by deadline and never skips, and a "
            "<b>supervisor loop</b> (every minute) that runs heartbeat checks, balance reconciliation, "
            "and kill-switch evaluation.",
            BODY,
        )
    )
    story.append(Spacer(1, 8))
    story.append(ArchitectureDiagram(width=PAGE_W - 2 * MARGIN_X, height=420))

    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>Why this shape:</b> the laptop never trades — it edits the vault and reviews paper PnL. "
            "The Dublin VPS owns the live execution path. Storage and observability live alongside the "
            "bot so a network blip can't lose data or alerts.",
            BODY_SM,
        )
    )

    story.append(PageBreak())

    # ---- Phased plan page(s) ----
    story.append(
        section_heading("Phased Plan", color=GREEN, sub="Each phase has a gate. No skipping.")
    )

    # Define phases
    phases = [
        {
            "n": "0",
            "color": SLATE,
            "title": "Foundations",
            "dur": "~½ day",
            "gate": "Claude can read/write Obsidian; references cloned; CLAUDE.md committed.",
        },
        {
            "n": "1",
            "color": BLUE,
            "title": "Wallet & Auth",
            "dur": "~½ day",
            "gate": "Sign requests, read account state, place + cancel a $1 mainnet order.",
        },
        {
            "n": "2",
            "color": TEAL,
            "title": "Read-only Data Plane",
            "dur": "1-2 days",
            "gate": "24h clean capture for spot, oracle, market WS. No gaps.",
        },
        {
            "n": "3",
            "color": PURPLE,
            "title": "Backtest Harness",
            "dur": "2-3 days",
            "gate": "≥55% win-rate after fees on ≥500 simulated trades.",
        },
        {
            "n": "4",
            "color": AMBER,
            "title": "Paper Trading Live",
            "dur": "1 week",
            "gate": "Paper PnL within 20% of backtest. Zero unhandled exceptions / 7 days.",
        },
        {
            "n": "5",
            "color": NAVY_SOFT,
            "title": "VPS Provisioning",
            "dur": "~½ day",
            "gate": "systemctl healthy; latency p99 < 15ms confirmed.",
        },
        {
            "n": "6",
            "color": GREEN,
            "title": "Live with Kill-switches",
            "dur": "1 week",
            "gate": "7 days live, all kill-switches tested, zero unexplained losses.",
        },
        {
            "n": "7",
            "color": AMBER_DK,
            "title": "Scale + Maker Rebates",
            "dur": "ongoing",
            "gate": "Stepped scaling: $100 → $500 → $2k → $10k after each positive 7d.",
        },
        {
            "n": "8",
            "color": RED,
            "title": "Hardening",
            "dur": "ongoing",
            "gate": "USDC migration handled, warm standby in Frankfurt, multi-account.",
        },
    ]

    story.append(PhaseTimeline(phases, width=PAGE_W - 2 * MARGIN_X))
    story.append(Spacer(1, 14))

    # Phase detail tables (split for readability)
    phase_details = [
        (
            "0",
            "Foundations (laptop)",
            [
                "Install Python 3.11, uv (or poetry), Node (for Obsidian MCP).",
                "Install Obsidian; create vault polymarket-bot/. Folders: runbooks/, research/, postmortems/, strategy-notes/, daily/.",
                "Wire iansinnott/obsidian-claude-code-mcp to Claude Code. Verify read/write.",
                "Clone reference repos into references/: py-clob-client, agent-skills, agents, poly-market-maker, Archetapp gist, evan-kolberg backtesting, aulekator 15m bot.",
                "Drop Polymarket/agent-skills into ~/.claude/skills/.",
                "Run /init to seed CLAUDE.md.",
            ],
        ),
        (
            "1",
            "Wallet & Auth (laptop)",
            [
                "Create a fresh dedicated Polygon EOA. Never reuse a personal wallet.",
                "Fund with ~$5 MATIC for gas + small USDC test deposit ($20).",
                "Use setup_creds pattern from py-clob-client to derive L2 creds (apiKey, secret, passphrase).",
                "Store secrets in .envrc (gitignored) and back up an age-encrypted copy.",
                "Read your own positions; place + cancel a $1 limit order on a non-time-critical market.",
            ],
        ),
        (
            "2",
            "Read-only Data Plane (laptop)",
            [
                "market_feed.py: subscribe to active 5m BTC market via WS, archive to Parquet.",
                "spot_feed.py: Binance + Coinbase WS for BTC, archive ticks.",
                "oracle_watcher.py: subscribe to Chainlink BTC/USD AnswerUpdated events on Polygon.",
                'Sanity check: at any time, answer "resolves as if now" within 50ms of last spot tick.',
            ],
        ),
        (
            "3",
            "Backtest Harness (laptop)",
            [
                "Wire NautilusTrader's Polymarket adapter (or fork evan-kolberg) to captured data.",
                "v0 strategy: window-delta + oracle-vs-spot gap. Trade only when |signal| > threshold AND time-to-close in [10s, 30s].",
                "Realistic fills using top-5 orderbook history, $4.75 minimum, slippage model.",
                "Run on 30 days. Report win-rate, edge, Sharpe, max drawdown, P50/P95 fill latency.",
            ],
        ),
        (
            "4",
            "Paper Trading Live (laptop, 1 week min)",
            [
                "Add mode: paper switch — live data, shadow SQLite book, fill marks.",
                "Run 7 calendar days unattended.",
                "Diagnose any divergence > 20% between paper PnL and backtest expectation.",
            ],
        ),
        (
            "5",
            "VPS Provisioning",
            [
                "AWS Lightsail eu-west-1 Dublin, 2 vCPU / 4GB / 80GB NVMe, Ubuntu 24.04.",
                "Harden: ssh-key only, ufw, fail2ban, auto security updates, non-root user.",
                "Install Python 3.11, uv, redis, prometheus-node-exporter.",
                "Latency check: mtr clob.polymarket.com; wscat round-trip. p50 < 5ms, p99 < 15ms.",
                "systemd unit with restart policy; journalctl 30d retention.",
                "Prometheus → Grafana Cloud, Discord webhook for unhealthy state.",
            ],
        ),
        (
            "6",
            "Live with Kill-switches",
            [
                "Initial bankroll $100. Per-trade 1% (~$1). Daily loss circuit breaker -$10.",
                "Three kill-switches:  (a) any feed silent > 10s halts entries.  (b) avg fill slippage > 2¢ halts.  (c) -$10 daily or -$25 total = systemd stop + Discord page.",
                "Daily ritual: live PnL vs paper-mode prediction. Investigate every >$3 divergence.",
            ],
        ),
        (
            "7",
            "Scale + Maker Rebates (ongoing)",
            [
                "Scale only after a positive 7-day live run. Steps: $100 → $500 → $2k → $10k. No skipping.",
                "Maker layer: park resting limits near mid on weak-signal windows; earn the daily rebate.",
                "Add a second strategy variant in shadow mode; winning variant takes capital (compete-and-allocate pattern).",
                "Quarterly postmortem in Obsidian; refit weights on last 30 days.",
            ],
        ),
        (
            "8",
            "Hardening (ongoing)",
            [
                "Migrate USDC.e → native Polymarket USD as the rollout completes.",
                "Second VPS in Frankfurt as warm standby; DB replicates via litestream.",
                "Multi-account proxy wallets for size > $50k (per-account exposure caps).",
                "On-call rotation with phone alerts.",
            ],
        ),
    ]

    for n, title, items in phase_details:
        # phase header
        keep = []
        keep.append(Spacer(1, 6))
        keep.append(
            Table(
                [
                    [
                        Paragraph(
                            f"<font color='{PAPER.hexval()}'><b>PHASE {n}</b></font>", BODY_SM
                        ),
                        Paragraph(f"<font color='{NAVY.hexval()}'><b>{title}</b></font>", BODY),
                    ]
                ],
                colWidths=[60, PAGE_W - 2 * MARGIN_X - 60],
                style=TableStyle(
                    [
                        (
                            "BACKGROUND",
                            (0, 0),
                            (0, 0),
                            [p["color"] for p in phases if p["n"] == n][0],
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                        ("BACKGROUND", (1, 0), (1, 0), GRAY_50),
                    ]
                ),
            )
        )
        for it in bullet_list(items, marker="▸"):
            keep.append(it)
        story.append(KeepTogether(keep))
        story.append(Spacer(1, 4))

    story.append(PageBreak())

    # ---- Risk register ----
    story.append(
        section_heading("Risk Register", color=RED, sub="Read every phase. Update each postmortem.")
    )

    risks = [
        (
            "HIGH",
            "Wallet compromise",
            "A leaked private key drains everything instantly.",
            "Fresh wallet only. age-encrypt the key. Never paste in chat. Never check in. Hardware wallet for owner key once size > $5k.",
        ),
        (
            "HIGH",
            "Geo-restriction",
            "Polymarket geofences UK + US + others.",
            "Run from Dublin (eu-west-1), never eu-west-2 or US regions. Don't connect personal wallet via UI from blocked geos.",
        ),
        (
            "HIGH",
            "Adverse selection",
            "Co-located bots in eu-west-2 beat raw round-trips.",
            "Compete on signal quality + last-10-second timing, not raw latency. Track fill-vs-mid slippage daily.",
        ),
        (
            "MED",
            "Settlement migration",
            'USDC.e → native USDC ("Polymarket USD") rollout in progress.',
            "Bot must double-write/read during transition. Subscribe to Polymarket announcements; keep migration runbook in Obsidian.",
        ),
        (
            "MED",
            "Oracle reorg / stuck oracle",
            "Polygon reorgs are rare but possible; Chainlink can miss a heartbeat.",
            'Design assumes "last answer at end-time" semantics. If oracle stale > 90s, halt new entries.',
        ),
        (
            "MED",
            "Min-order math",
            "5-share × $0.95 = $4.75 minimum spend per limit order.",
            "Don't try near-the-money limits with $100 bankroll and 1% sizing. Use takers until size > $20.",
        ),
        (
            "LOW",
            "Tax / regs",
            "Per-trade tax tracking is jurisdiction-dependent.",
            "Export trades.db to CSV monthly. Categorize as appropriate; consult an accountant once PnL > 4-figure.",
        ),
    ]
    story.append(risk_table(risks))

    story.append(Spacer(1, 14))

    # ---- What to do right now ----
    story.append(section_heading("Next 60 Minutes", color=AMBER, sub="Decide and ship Phase 0"))
    do_items = [
        "<b>Confirm the plan above is what you want.</b> Push back on any choice before code is written.",
        "<b>Paste the three tweet texts</b> (X.com server-side fetch is paywalled). They'll be folded into the right phase.",
        "<b>Decide bankroll cap for Phase 6</b> ($100 default, can go lower to $50).",
        "<b>Decide Obsidian vault location</b> (default: ~/Documents/polymarket-bot-vault/).",
    ]
    for it in bullet_list(do_items, marker="●"):
        story.append(it)
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "<i>After sign-off:</i> Phase 0 begins — clone references, set up Obsidian MCP, scaffold the project. "
            "Pause at every phase gate for review.",
            CALLOUT,
        )
    )

    story.append(PageBreak())

    # ---- Sources / Appendix ----
    story.append(
        section_heading(
            "Sources & References", color=BLUE, sub="Canonical links used to compile this plan"
        )
    )

    polymarket_links = [
        ("Polymarket Developer Docs", "docs.polymarket.com/developers/"),
        ("py-clob-client (Python, primary)", "github.com/Polymarket/py-clob-client"),
        ("rs-clob-client (Rust)", "github.com/Polymarket/rs-clob-client"),
        ("agent-skills (drop into Claude)", "github.com/Polymarket/agent-skills"),
        ("agents (TS autonomous framework)", "github.com/Polymarket/agents"),
        ("poly-market-maker (reference MM)", "github.com/Polymarket/poly-market-maker"),
        ("Authentication (L1 + L2)", "docs.polymarket.com/developers/CLOB/authentication"),
        ("Maker Rebates Program", "help.polymarket.com/en/articles/13364471"),
    ]
    story.append(
        section_block(
            "Polymarket — Official", kv_table(rows=polymarket_links, col_widths=[260, 258])
        )
    )

    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Reference bot implementations",
            kv_table(
                rows=[
                    (
                        "Archetapp 5m bot gist (best timing/window logic)",
                        "gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69",
                    ),
                    (
                        "aulekator 15m production-grade bot",
                        "github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
                    ),
                    (
                        "ThinkEnigmatic adaptive 5m arena",
                        "github.com/ThinkEnigmatic/polymarket-bot-arena",
                    ),
                    (
                        "evan-kolberg NautilusTrader backtest adapters",
                        "github.com/evan-kolberg/prediction-market-backtesting",
                    ),
                ],
                col_widths=[260, 258],
            ),
        )
    )

    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Infrastructure & oracle",
            kv_table(
                rows=[
                    (
                        "NautilusTrader Polymarket integration",
                        "nautilustrader.io/docs/latest/integrations/polymarket/",
                    ),
                    (
                        "QuantVPS — Polymarket server location",
                        "quantvps.com/blog/polymarket-servers-location",
                    ),
                    (
                        "Chainlink BTC/USD on Polygon (60s heartbeat)",
                        "data.chain.link/feeds/polygon/mainnet/btc-usd",
                    ),
                    ("USDC.e to native USDC migration (Block)", "theblock.co/post/388670"),
                ],
                col_widths=[260, 258],
            ),
        )
    )

    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Claude tooling",
            kv_table(
                rows=[
                    (
                        "iansinnott/obsidian-claude-code-mcp",
                        "github.com/iansinnott/obsidian-claude-code-mcp",
                    ),
                    (
                        "MCPVault (Obsidian MCP, no plugin)",
                        "medium.com/@ai_transfer_lab/mcpvault-...",
                    ),
                    ("MarkusPfundstein/mcp-obsidian", "github.com/MarkusPfundstein/mcp-obsidian"),
                    (
                        "caiovicentino/polymarket-mcp-server",
                        "github.com/caiovicentino/polymarket-mcp-server",
                    ),
                    ("artvandelay/polymarket-agents", "github.com/artvandelay/polymarket-agents"),
                    ("berlinbra/polymarket-mcp", "github.com/berlinbra/polymarket-mcp"),
                    (
                        "agent-next/polymarket-paper-trader",
                        "github.com/agent-next/polymarket-paper-trader",
                    ),
                ],
                col_widths=[260, 258],
            ),
        )
    )

    story.append(Spacer(1, 8))
    story.append(
        section_block(
            "Strategy / edge research",
            kv_table(
                rows=[
                    (
                        "Benjamin-Cup — 5-min market edges (Medium)",
                        "medium.com/@benjamin.bigdev/...db8efcb5c196",
                    ),
                    (
                        "ILLUMINATION — Beyond simple arbitrage (Medium)",
                        "medium.com/illumination/...ddacc92c5b4f",
                    ),
                    (
                        "FinanceMagnates — Prediction markets are bot playground",
                        "financemagnates.com/trending/...",
                    ),
                    (
                        "CoinMarketCap — Polymarket 5-Min BTC launch",
                        "coinmarketcap.com/academy/article/polymarket-debuts-5-minute-...",
                    ),
                ],
                col_widths=[260, 258],
            ),
        )
    )

    story.append(Spacer(1, 14))
    story.append(HBar(color=GRAY_300, thickness=0.6, top=2, bot=2))
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "<font color='#64748B'><i>This document is a living plan. Mirror it into the Obsidian vault under "
            "/runbooks/MASTERPLAN.md and update at every phase gate.</i></font>",
            BODY_SM,
        )
    )

    doc.build(story)
    return output


if __name__ == "__main__":
    out = build()
    print(f"Built: {out}")
