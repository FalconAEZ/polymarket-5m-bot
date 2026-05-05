"""Build BUILD_SPEC.pdf — the comprehensive build specification.

Self-contained: redefines the design system from build_pdf.py so it can be
edited and rebuilt independently. Produces ~24 pages of professional layout
covering every decision, phase, risk, and operating rule.
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


# ===== Design system =====
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
BODY_SM = ParagraphStyle("BodySm", parent=BODY, fontSize=8.5, leading=12, textColor=GRAY_700)
BODY_XS = ParagraphStyle("BodyXs", parent=BODY, fontSize=7.5, leading=10, textColor=GRAY_500)
BULLET = ParagraphStyle(
    "Bullet", parent=BODY, leftIndent=12, bulletIndent=2, spaceBefore=1, spaceAfter=1
)
CODE = ParagraphStyle(
    "Code",
    parent=BODY,
    fontName="Courier",
    fontSize=8,
    leading=11,
    textColor=GRAY_900,
    backColor=GRAY_100,
    leftIndent=6,
    rightIndent=6,
    spaceBefore=3,
    spaceAfter=3,
    borderPadding=6,
)


# ===== Custom flowables =====
class ColorBarHeading(Flowable):
    def __init__(self, text, color=AMBER, fontsize=17, height=24, sub=None):
        Flowable.__init__(self)
        self.text, self.sub, self.color, self.fontsize = text, sub, color, fontsize
        self.h = height + (16 if sub else 0)
        self.width = PAGE_W - 2 * MARGIN_X

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
        self.w = None

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
        self.items, self.h, self.w = items, h, None

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
            for word in words:
                test = (cur + " " + word).strip()
                if stringWidth(test, "Helvetica", 8) <= cw - 22:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            ly = self.h - 36
            for ln in lines[:2]:
                c.drawString(x + 14, ly, ln)
                ly -= 10


class AgentEnsembleDiagram(Flowable):
    """3 agents -> meta-decider -> ensemble valid? -> execute, with Tier-3 branch."""

    def __init__(self, height=420):
        Flowable.__init__(self)
        self.h, self.w = height, None

    def wrap(self, w, h):
        self.w = w
        return (w, self.h)

    def _box(self, c, x, y, w, h, label, sub, accent, fill=PAPER, ink=NAVY):
        c.setFillColor(fill)
        c.setStrokeColor(GRAY_300)
        c.setLineWidth(0.7)
        c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
        c.setFillColor(accent)
        c.roundRect(x, y, 3, h, 1.5, stroke=0, fill=1)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(x + 9, y + h - 14, label)
        if sub:
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 7)
            c.drawString(x + 9, y + h - 24, sub)

    def _arrow(self, c, x1, y1, x2, y2, color=GRAY_500, label=None):
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
            c.setFont("Helvetica", 6.5)
            c.drawString((x1 + x2) / 2 - 12, (y1 + y2) / 2 + 3, label)

    def _diamond(self, c, cx, cy, w, h, label):
        p = c.beginPath()
        p.moveTo(cx, cy + h / 2)
        p.lineTo(cx + w / 2, cy)
        p.lineTo(cx, cy - h / 2)
        p.lineTo(cx - w / 2, cy)
        p.close()
        c.setFillColor(HexColor("#FEF3C7"))
        c.setStrokeColor(AMBER_DK)
        c.setLineWidth(0.8)
        c.drawPath(p, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 7.5)
        from reportlab.pdfbase.pdfmetrics import stringWidth

        tw = stringWidth(label, "Helvetica-Bold", 7.5)
        c.drawString(cx - tw / 2, cy - 2, label)

    def draw(self):
        c = self.canv
        W, H = self.w, self.h

        # input strip top
        c.setFillColor(NAVY_DARK)
        c.roundRect(0, H - 28, W, 22, 4, stroke=0, fill=1)
        c.setFillColor(AMBER)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(8, H - 19, "INPUT (per 5-min window)")
        c.setFillColor(HexColor("#9FB3CF"))
        c.setFont("Helvetica", 7.5)
        c.drawString(
            150,
            H - 19,
            "Binance L2  ·  Coinbase L2  ·  Chainlink last-answer  ·  Polymarket OB  ·  window_ts state",
        )

        # 3 agents
        agent_y = H - 110
        agent_w = (W - 32) / 3
        agents = [
            (
                "Agent 1: Orderbook MS",
                "Binance + Coinbase L2 imbalance, top-5 depth, microprice bias",
                BLUE,
            ),
            (
                "Agent 2: Oracle-Gap",
                "spot vs Chainlink last-answer; cadence; staleness signal",
                PURPLE,
            ),
            ("Agent 3: Momentum", "last-60s tick trend, acceleration, microsecond reversion", TEAL),
        ]
        for i, (name, sub, col) in enumerate(agents):
            x = 8 + i * (agent_w + 8)
            self._box(c, x, agent_y, agent_w, 60, name, sub, col)
            c.setFillColor(GRAY_500)
            c.setFont("Helvetica", 6.5)
            c.drawString(x + 9, agent_y + 6, "Haiku 4.5  ·  cached system  ·  ≤800ms budget")

        # arrows agents -> meta
        meta_x, meta_y, meta_w, meta_h = (W - 320) / 2, agent_y - 80, 320, 56
        for i in range(3):
            ax = 8 + i * (agent_w + 8) + agent_w / 2
            self._arrow(c, ax, agent_y, meta_x + meta_w / 2, meta_y + meta_h, color=GRAY_500)

        # meta-decider
        self._box(
            c,
            meta_x,
            meta_y,
            meta_w,
            meta_h,
            "META-DECIDER (Sonnet 4.6)",
            "weighs 3 votes + deterministic composite; outputs side, conf, rationale",
            AMBER,
            fill=HexColor("#FFF7E6"),
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 6.5)
        c.drawString(
            meta_x + 9,
            meta_y + 6,
            "JSON-schema validated; refusal -> abstain; <2 valid agents -> Tier-3",
        )

        # diamond gate
        gate_y = meta_y - 50
        self._diamond(c, W / 2, gate_y, 110, 36, "ensemble valid?")

        self._arrow(c, W / 2, meta_y, W / 2, gate_y + 18, color=GRAY_500)

        # branches
        # YES -> execute (right)
        exec_x, exec_y = W - 180, gate_y - 24
        self._arrow(c, W / 2 + 60, gate_y, exec_x + 90, exec_y + 24, color=GREEN, label="YES")
        self._box(
            c,
            exec_x,
            exec_y,
            180,
            38,
            "Execute via gasless relayer",
            "size = $5 flat (first 100 trades) -> kelly",
            GREEN,
        )

        # NO -> Tier-3 (left)
        tier3_x, tier3_y = 0, gate_y - 24
        self._arrow(c, W / 2 - 60, gate_y, tier3_x + 90, tier3_y + 24, color=RED, label="NO / fail")
        self._box(
            c,
            tier3_x,
            tier3_y,
            180,
            38,
            "Tier-3 deterministic",
            "window-delta + oracle-gap, threshold ≥ 0.6 composite",
            RED,
            fill=HexColor("#FEE7E9"),
        )

        # tier-3 -> execute path
        self._arrow(c, tier3_x + 180, tier3_y + 19, exec_x, exec_y + 19, color=SLATE)

        # bottom legend
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(
            0,
            6,
            "Tier-3 fires when: any agent 429s, latency budget at T-15s blown, schema-fail, or <2 valid votes.  Never skip a window.",
        )


class WalletTopologyDiagram(Flowable):
    """Funder / Signer separation, sweep flows, cold storage."""

    def __init__(self, height=320):
        Flowable.__init__(self)
        self.h, self.w = height, None

    def wrap(self, w, h):
        self.w = w
        return (w, self.h)

    def _wallet(self, c, x, y, w, h, title, addr, balance, accent, ink=NAVY):
        c.setFillColor(PAPER)
        c.setStrokeColor(GRAY_300)
        c.setLineWidth(0.8)
        c.roundRect(x, y, w, h, 6, stroke=1, fill=1)
        c.setFillColor(accent)
        c.roundRect(x, y + h - 8, w, 8, 3, stroke=0, fill=1)
        c.setFillColor(ink)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(x + 10, y + h - 24, title)
        c.setFillColor(GRAY_700)
        c.setFont("Courier", 7)
        c.drawString(x + 10, y + h - 36, addr)
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 7.5)
        c.drawString(x + 10, y + h - 48, balance)

    def _arrow(self, c, x1, y1, x2, y2, color=GRAY_500, label=None, dashed=False):
        import math

        c.setStrokeColor(color)
        c.setLineWidth(1.0)
        if dashed:
            c.setDash(3, 2)
        c.line(x1, y1, x2, y2)
        c.setDash()
        ang = math.atan2(y2 - y1, x2 - x1)
        s = 5
        c.setFillColor(color)
        p = c.beginPath()
        p.moveTo(x2, y2)
        p.lineTo(x2 - s * math.cos(ang - 0.5), y2 - s * math.sin(ang - 0.5))
        p.lineTo(x2 - s * math.cos(ang + 0.5), y2 - s * math.sin(ang + 0.5))
        p.close()
        c.drawPath(p, stroke=0, fill=1)
        if label:
            c.setFillColor(color)
            c.setFont("Helvetica-Bold", 7)
            c.drawString((x1 + x2) / 2 - 30, (y1 + y2) / 2 + 4, label)

    def draw(self):
        c = self.canv
        W, H = self.w, self.h

        # zone labels
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(10, H - 14, "LAPTOP (cold-ish)")
        c.drawCentredString(W / 2, H - 14, "VPS (Dublin, hot)")
        c.drawRightString(W - 10, H - 14, "COLD STORAGE")
        c.setStrokeColor(GRAY_200)
        c.setDash(2, 3)
        c.line(W / 3, H - 24, W / 3, 30)
        c.line(2 * W / 3, H - 24, 2 * W / 3, 30)
        c.setDash()

        # Funder (left)
        fx, fy, fw, fh = 10, H - 130, W / 3 - 20, 70
        self._wallet(
            c,
            fx,
            fy,
            fw,
            fh,
            "FUNDER (working capital)",
            "0xFundr...",
            "USDC: $50  ·  MATIC: $3",
            NAVY_SOFT,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(fx, fy - 14, "key: ~/secrets/.../funder.age")
        c.drawString(fx, fy - 24, "never on the running bot machine")

        # Signer (middle)
        sx, sy, sw, sh = W / 3 + 10, H - 130, W / 3 - 20, 70
        self._wallet(
            c,
            sx,
            sy,
            sw,
            sh,
            "SIGNER (operator)",
            "0xSignr...",
            "USDC: ≤$50  ·  MATIC: $0.5",
            AMBER,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(sx, sy - 14, "key: VPS .envrc (mode 0600)")
        c.drawString(sx, sy - 24, "max 2 days of bankroll on hand")

        # Cold (right)
        cx, cy, cw, ch = 2 * W / 3 + 10, H - 130, W / 3 - 20, 70
        self._wallet(
            c,
            cx,
            cy,
            cw,
            ch,
            "COLD STORAGE",
            "(hardware wallet at $2k)",
            "profits sweep here",
            GREEN,
        )
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(cx, cy - 14, "Phase 7 onward")

        # arrows
        # Funder -> Signer (top-up)
        self._arrow(
            c,
            fx + fw,
            fy + fh / 2 + 10,
            sx,
            sy + fh / 2 + 10,
            color=BLUE,
            label="manual top-up ($20)",
        )
        # Signer -> Funder (sweep up)
        self._arrow(
            c,
            sx,
            sy + fh / 2 - 10,
            fx + fw,
            fy + fh / 2 - 10,
            color=TEAL,
            label="nightly sweep > $50",
            dashed=True,
        )
        # Funder -> Cold
        self._arrow(
            c,
            sx + sw,
            fy + fh / 2,
            cx,
            cy + fh / 2,
            color=GREEN,
            label="profit sweep > $200",
            dashed=True,
        )

        # Polymarket exchange contract
        py = fy - 90
        c.setFillColor(GRAY_50)
        c.setStrokeColor(GRAY_300)
        c.roundRect(W / 3 + 10, py, W / 3 - 20, 50, 6, stroke=1, fill=1)
        c.setFillColor(NAVY)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(W / 3 + 20, py + 32, "Polymarket Exchange (Polygon)")
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica", 7.5)
        c.drawString(W / 3 + 20, py + 18, "USDC allowance from Signer")
        c.drawString(W / 3 + 20, py + 8, "orders submitted via gasless relayer")

        # Signer -> Polymarket
        self._arrow(
            c,
            sx + sw / 2,
            sy,
            W / 3 + 10 + (W / 3 - 20) / 2,
            py + 50,
            color=AMBER,
            label="signed orders",
        )

        # explainer footer
        c.setFillColor(GRAY_500)
        c.setFont("Helvetica-Oblique", 7)
        c.drawString(
            0,
            8,
            "If Signer key leaks: max loss = USDC currently on Signer (≤2 days bankroll).  Funder + Cold are unaffected.",
        )


class PhaseDetailBlock(Flowable):
    """Compact per-phase card: header + duration/cost + bullets + gate."""

    def __init__(self, n, color, title, duration, cost, intent, items, gate, rollback):
        Flowable.__init__(self)
        self.n, self.color, self.title = n, color, title
        self.duration, self.cost = duration, cost
        self.intent, self.items = intent, items
        self.gate, self.rollback = gate, rollback
        self._height_cache = None

    def wrap(self, w, h):
        from reportlab.pdfbase.pdfmetrics import stringWidth

        self.w = w
        # header 30 + intent ~24 + per-item 14 + gate 30 + rollback 24
        item_h = 14 * len(self.items)
        self._height_cache = 32 + 18 + item_h + 18 + 18 + 16
        return (w, self._height_cache)

    def draw(self):
        c = self.canv
        W = self.w
        H = self._height_cache

        # header strip
        c.setFillColor(self.color)
        c.roundRect(0, H - 26, W, 26, 4, stroke=0, fill=1)
        c.setFillColor(PAPER)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(10, H - 18, f"PHASE {self.n}  ·  {self.title}")
        c.setFont("Helvetica", 9)
        meta = f"{self.duration}   ·   {self.cost}"
        from reportlab.pdfbase.pdfmetrics import stringWidth

        tw = stringWidth(meta, "Helvetica", 9)
        c.drawString(W - tw - 10, H - 18, meta)

        # intent line
        c.setFillColor(GRAY_700)
        c.setFont("Helvetica-Oblique", 8.5)
        c.drawString(0, H - 42, "Intent: " + self.intent)

        # items
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

        # gate
        c.setFillColor(GRAY_50)
        c.setStrokeColor(GRAY_200)
        c.roundRect(0, y - 16, W, 16, 3, stroke=1, fill=1)
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(6, y - 12, "GATE")
        c.setFillColor(GRAY_900)
        c.setFont("Helvetica", 8.5)
        c.drawString(40, y - 12, self.gate)

        # rollback
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
    c.setFillColor(AMBER)
    c.rect(0, PAGE_H - 12, PAGE_W * 0.32, 12, stroke=0, fill=1)
    c.setFillColor(HexColor("#15294A"))
    for gx in range(int(PAGE_W * 0.55), int(PAGE_W), 14):
        for gy in range(20, int(PAGE_H * 0.45), 14):
            c.circle(gx, gy, 1.0, stroke=0, fill=1)
    c.setFillColor(AMBER)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MARGIN_X, PAGE_H - 60, "BUILD SPECIFICATION  ·  v2  ·  2026")
    title_y = PAGE_H - 240
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN_X, title_y, "Polymarket")
    c.drawString(MARGIN_X, title_y - 42, "BTC 5-Minute Bot")
    c.setStrokeColor(AMBER)
    c.setLineWidth(3)
    c.line(MARGIN_X, title_y - 56, MARGIN_X + 90, title_y - 56)
    c.setFillColor(HexColor("#9FB3CF"))
    c.setFont("Helvetica", 13)
    c.drawString(
        MARGIN_X,
        title_y - 82,
        "Comprehensive in-and-out specification for the development process.",
    )
    c.drawString(
        MARGIN_X, title_y - 100, "Decisions, architecture, phases, gates, costs, discipline."
    )
    meta_y = 80
    c.setFillColor(HexColor("#7B93B5"))
    c.setFont("Helvetica-Bold", 8)
    for i, label in enumerate(["OWNER", "STARTED", "OPERATOR JURISDICTION", "STAGE"]):
        c.drawString(MARGIN_X + i * 130, meta_y + 28, label)
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 11)
    for i, val in enumerate(["Hamad", "2026-05-04", "UAE (permitted)", "pre-Phase 0"]):
        c.drawString(MARGIN_X + i * 130, meta_y + 12, val)
    c.setFillColor(AMBER)
    c.rect(0, 0, PAGE_W, 6, stroke=0, fill=1)


def header_footer(c, doc):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    c.setFillColor(AMBER)
    c.rect(0, PAGE_H - 4, PAGE_W * 0.18, 4, stroke=0, fill=1)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, PAGE_H - 14, "POLYMARKET BTC 5-MIN BOT  ·  BUILD SPEC")
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 14, "v2  ·  2026-05-04")
    c.setStrokeColor(GRAY_200)
    c.setLineWidth(0.4)
    c.line(MARGIN_X, 22, PAGE_W - MARGIN_X, 22)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, 12, "Confidential build specification  ·  Hamad")
    c.drawRightString(PAGE_W - MARGIN_X, 12, f"Page {doc.page}")


# ===== Helpers =====
def section_heading(text, color=AMBER, sub=None):
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


def bullet_list(items, marker="●"):
    return [
        Paragraph(f'<font color="#F5A524"><b>{marker}</b></font>&nbsp;&nbsp;{it}', BULLET)
        for it in items
    ]


def section_block(heading, table_or_flowables):
    items = [Paragraph(f"<b>{heading}</b>", H3)]
    if isinstance(table_or_flowables, list):
        items.extend(table_or_flowables)
    else:
        items.append(table_or_flowables)
    return KeepTogether(items)


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
    out = "/Users/hamad/Desktop/PolyMarket-5m/pdfs/BUILD_SPEC.pdf"
    doc = BaseDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_Y + 4,
        bottomMargin=MARGIN_Y + 6,
        title="Polymarket BTC 5-Min Bot — Build Specification",
        author="Hamad",
        subject="Comprehensive build specification, v2",
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
            "Table of Contents", color=NAVY_SOFT, sub="What you'll find in this document"
        )
    )
    toc_rows = [
        ("01", "Executive Summary", "Thesis, edge ranking, win-rate target.", "p. 3"),
        ("02", "Locked Decisions", "All 18 locked decisions with rationale.", "p. 4"),
        ("03", "Tooling Inventory — Claude", "Skills, MCPs, slash commands, plugins.", "p. 5"),
        ("04", "Tooling Inventory — Stack", "Engine, signing, data feeds, deps.", "p. 6"),
        ("05", "Tooling Inventory — Infra", "VPS, monitoring, secrets, CI.", "p. 7"),
        ("06", "Architecture — Runtime", "Three concurrent loops on the VPS.", "p. 8"),
        ("07", "Architecture — Ensemble", "3 agents + meta + Tier-3 fallback.", "p. 9"),
        ("08", "Architecture — Wallets", "Funder/Signer separation, sweeps.", "p. 10"),
        ("09", "Phase 0 — Foundations", "Project skeleton, accounts, wiring.", "p. 11"),
        ("10", "Phase 1 — Wallet & Auth", "Derive creds, test sign, then fund.", "p. 12"),
        ("11", "Phase 2 — Data Plane", "Spot, oracle, market feeds; thesis verify.", "p. 13"),
        ("12", "Phase 3 — Backtest + A/B", "Deterministic vs LLM ensemble.", "p. 14"),
        ("13", "Phase 4 — Paper Trading", "14 days live data, regime coverage.", "p. 15"),
        ("14", "Phase 5 — VPS Provisioning", "Dublin Lightsail, hardening, staging.", "p. 16"),
        ("15", "Phase 6 — Live Trading", "5 kill-switches, $5 flat sizing.", "p. 17"),
        ("16", "Phase 7 + 8", "Scale, hardening, ongoing.", "p. 18"),
        ("17", "Risk Register", "Severity-tagged risks + mitigations.", "p. 19"),
        ("18", "Cost & Timeline", "Cumulative spend per phase.", "p. 20"),
        ("19", "Operating Discipline", "25 anti-drift rules pin-above-desk.", "p. 21"),
        ("20", "Sources & References", "Verified canonical links.", "p. 23"),
    ]
    toc_num_style = ParagraphStyle(
        "tocnum", parent=BODY, fontName="Helvetica-Bold", fontSize=12, textColor=AMBER, leading=14
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
    toc = Table(toc_data, colWidths=[26, 130, 305, 40], hAlign="LEFT")
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
    story.append(
        section_heading("Executive Summary", color=AMBER, sub="The thesis and the numbers")
    )
    story.append(
        Paragraph(
            "Polymarket runs continuous 5-minute binary markets on whether BTC closes higher or lower "
            "than its starting price. Markets are deterministic with windows aligned to "
            "<b>floor(now/300)*300</b>. Resolution = the Chainlink BTC/USD snapshot at <b>window_ts + 300</b> "
            "on Polygon. Chainlink BTC/USD on Polygon is reported as a <b>60s heartbeat with no "
            "deviation threshold</b> (pending on-chain verification in Phase 2) — that gap, combined with "
            "thin orderbooks ($5-50K/window) and the empirical fact that ~15-20% of windows are "
            "decided in the final 10 seconds, is the exploitable inefficiency.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        StatCards(
            [
                ("60s", "Chainlink heartbeat (pending verify)", AMBER),
                ("1-5ms", "Dublin VPS to CLOB", TEAL),
                ("$1k", "Starting bankroll  ·  $5 flat sizing", BLUE),
                ("≥3pp", "LLM uplift vs baseline to keep agents", GREEN),
            ]
        )
    )
    story.append(Spacer(1, 12))

    story.append(Paragraph("<b>Edge sources (ranked)</b>", H3))
    edge_rows = [
        ("Oracle latency", "60s heartbeat, no deviation; spot moves while oracle is silent"),
        ("Window-delta dominance", "single highest-weight signal — bigger than RSI/EMA combined"),
        ("Last-10s dynamics", "~15-20% of windows decided here; tokens still sub-$0.95"),
        ("Maker rebates", "100% of taker fees redistributed daily under CLOB v2"),
        ("Cross-venue spot arb", "Binance/Coinbase WS ahead of Polymarket UI by 100ms+"),
    ]
    story.append(kv_table(edge_rows, col_widths=[150, 368]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>What's NOT the edge</b>", H3))
    for it in bullet_list(
        [
            "TA on 5-min timeframe — RSI/EMA on 1m candles is mostly noise.",
            "Manual trading — humans cannot react fast enough at T-10s.",
            "Deep-volume markets — the inefficiency lives in thin books.",
            "Raw round-trip latency — co-located bots in eu-west-2 beat us; our edge is signal quality + last-second timing.",
        ]
    ):
        story.append(it)

    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "<b>Cost-to-first-live-dollar:</b> ~30 calendar days from Phase 0; ~$170 setup spend "
            "(VPS + APIs + RPC + minor tools); $1,000 working capital that is at risk, not consumed. "
            "Sustained ops once live: ~$200/mo budget driven primarily by Anthropic API "
            "(empirically $0.19-0.58/hour on a similar bot the operator already runs).",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Locked Decisions =====
    story.append(
        section_heading(
            "Locked Decisions", color=NAVY_SOFT, sub="Do not relitigate without explicit go"
        )
    )
    decisions = [
        ("01", "UAE-resident operator", "Polymarket-permitted jurisdiction"),
        ("02", "Dublin AWS Lightsail eu-west-1", "Sub-5ms to Polymarket CLOB; avoids UK geo-block"),
        (
            "03",
            "NautilusTrader engine + py-clob-client",
            "Production-grade; official Polymarket adapter",
        ),
        (
            "04",
            "Anthropic API only — no OpenAI fallback",
            "Simpler matrix; deterministic Tier-3 catches LLM failures",
        ),
        (
            "05",
            "3 agents + meta-decider",
            "Orderbook, oracle-gap, momentum, weighted by Sonnet meta",
        ),
        (
            "06",
            "Tier-3 = window-delta + oracle-gap, threshold ≥ 0.6",
            "Fires on strong signal; never skip a window",
        ),
        (
            "07",
            "Telegram bot via BotFather for alerts",
            "Reliable global push; supports inbound /halt",
        ),
        ("08", "GitHub private repo", "Default code host; CI via GitHub Actions"),
        (
            "09",
            "$5 flat per trade for first 100 trades",
            "Pre-Kelly learning budget; clears $4.75 min; 0.5% sizing at $1k bankroll",
        ),
        (
            "10",
            "$1,000 starting bankroll",
            "Real capital; HW wallet trigger ($2k) one rung away; meaningful Kelly transition",
        ),
        (
            "11",
            "Funder/Signer wallet separation from Phase 1",
            "Funder = working capital; Signer ≤ 2 days bankroll",
        ),
        (
            "12",
            "Hardware wallet at $2k bankroll trigger",
            "One rung past $1k start; first scaling step ($3k) triggers purchase",
        ),
        (
            "13",
            "Phase 1 order: derive creds → test sign → fund",
            "Don't strand $20 on an unverifiable wallet",
        ),
        (
            "14",
            "Anthropic budget: $50 → $150 (Phase 4) → $300 (Phase 6)",
            "Empirical $0.19-0.58/hr; sustained $200/mo OPEX",
        ),
        (
            "15",
            "UTC everywhere — logs, DB, daily notes",
            "Mixing TZ + window timestamps is a future bug",
        ),
        (
            "16",
            "LLM A/B in Phase 3; keep only if uplift ≥ 3pp",
            "LLM ensemble retained only if it earns its cost",
        ),
        (
            "17",
            "Polymarket gasless relayer for all order submission",
            "Closes the public-mempool MEV attack surface",
        ),
        (
            "18",
            "Obsidian vault on laptop only; bot writes to git state/",
            "Single source of truth; no VPS Obsidian plumbing",
        ),
    ]
    story.append(
        kv_table(
            rows=[(r[0], r[1], r[2]) for r in decisions],
            col_widths=[28, 220, 270],
            header=["#", "Decision", "Rationale"],
        )
    )
    story.append(PageBreak())

    # ===== Tooling: Claude side =====
    story.append(
        section_heading(
            "Tooling Inventory — Claude side",
            color=BLUE,
            sub="Every skill, MCP, slash command, plugin",
        )
    )
    story.append(
        section_block(
            "Claude skills",
            kv_table(
                header=["Item", "Source / install", "Where", "Phase"],
                col_widths=[110, 180, 130, 90],
                rows=[
                    (
                        "agent-skills (Polymarket official)",
                        "<font face='Courier' size='7'>git clone github.com/Polymarket/agent-skills</font>",
                        "~/.claude/skills/agent-skills/",
                        "0 (clone), 1+ (use)",
                    ),
                    ("anthropic-skills:pdf", "built-in", "Skill tool", "as needed"),
                    ("anthropic-skills:docx", "built-in", "Skill tool", "as needed"),
                    (
                        "custom: poly-bot-skills",
                        "write in Phase 0",
                        "~/.claude/skills/poly-bot/",
                        "0 onward",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "MCP servers",
            kv_table(
                header=["MCP", "Purpose", "Where", "Phase"],
                col_widths=[140, 200, 110, 60],
                rows=[
                    (
                        "iansinnott/obsidian-claude-code-mcp",
                        "Read/write the laptop vault under ./state/",
                        "Obsidian plugin",
                        "0+",
                    ),
                    (
                        "caiovicentino/polymarket-mcp-server",
                        "45 tools, real-time WS, exposure caps (research only)",
                        "stdio, ~/.mcp/",
                        "2+",
                    ),
                    (
                        "artvandelay/polymarket-agents",
                        "10 tools: odds, orderbook, spread, history",
                        "stdio",
                        "2+",
                    ),
                    (
                        "agent-next/polymarket-paper-trader",
                        "Paper-trading sim from chat",
                        "stdio",
                        "3-4",
                    ),
                    ("github (gh CLI)", "Read repos, file issues, manage PRs", "Bash", "0+"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Slash commands & plugins",
            kv_table(
                header=["Command / plugin", "When", "Phase"],
                col_widths=[150, 290, 70],
                rows=[
                    ("/init", "Seed project CLAUDE.md once layout is on disk", "0"),
                    (
                        "/security-review",
                        "Before each phase touching signing or fund movement",
                        "1, 5, 6",
                    ),
                    ("/loop", "Periodic check (e.g. monitor backtest) — sparing use", "3-4"),
                    ("/schedule", "Recurring agent tasks — only after Phase 6", "7+"),
                    ("/clear", "After drift detected mid-conversation", "any"),
                    (
                        "design suite (skills:design-critique)",
                        "Optional UI / dashboard work",
                        "later",
                    ),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Tooling: Stack =====
    story.append(
        section_heading(
            "Tooling Inventory — Stack", color=TEAL, sub="Engine, signing, data feeds, deps"
        )
    )
    story.append(
        section_block(
            "Core runtime",
            kv_table(
                header=["Layer", "Choice", "Repo / package", "Phase"],
                col_widths=[110, 130, 220, 60],
                rows=[
                    ("Language", "Python 3.11+", "system + uv", "0"),
                    (
                        "Package manager",
                        "uv",
                        "<font face='Courier' size='7'>astral.sh/uv</font>",
                        "0",
                    ),
                    (
                        "Trading engine",
                        "NautilusTrader",
                        "github.com/nautechsystems/nautilus_trader",
                        "3+",
                    ),
                    (
                        "Order client",
                        "py-clob-client",
                        "github.com/Polymarket/py-clob-client",
                        "1+",
                    ),
                    (
                        "Backtest scaffold",
                        "fork as needed",
                        "github.com/evan-kolberg/prediction-market-backtesting",
                        "3",
                    ),
                    ("Type check", "mypy --strict", "uv add --dev mypy", "0+"),
                    ("Lint + format", "ruff", "uv add --dev ruff", "0+"),
                    (
                        "Test framework",
                        "pytest + pytest-asyncio",
                        "uv add --dev pytest pytest-asyncio",
                        "0+",
                    ),
                    ("Import boundaries", "import-linter", "uv add --dev import-linter", "0+"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Data plane",
            kv_table(
                header=["Source", "Endpoint / library", "Use", "Phase"],
                col_widths=[100, 240, 120, 60],
                rows=[
                    (
                        "Binance WS",
                        "wss://stream.binance.com:9443/ws/btcusdt@trade",
                        "Spot ticks (primary)",
                        "2+",
                    ),
                    (
                        "Coinbase WS",
                        "wss://advanced-trade-ws.coinbase.com",
                        "Spot ticks (redundant)",
                        "2+",
                    ),
                    (
                        "Polygon RPC",
                        "Alchemy free tier (default)",
                        "Chainlink AnswerUpdated subscription",
                        "2+",
                    ),
                    (
                        "Polymarket WS",
                        "wss://ws-subscriptions-clob.polymarket.com/ws/market",
                        "Active 5m market orderbook + trades",
                        "2+",
                    ),
                    (
                        "Storage",
                        "SQLite (trades.db) + Parquet (ticks/)",
                        "Local, durable, no external deps",
                        "2+",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Reference repos (read-only mining)",
            kv_table(
                header=["Repo", "Why we cloned it", "Status"],
                col_widths=[230, 230, 60],
                rows=[
                    ("Polymarket/py-clob-client", "Auth flow, signing primitives", "clone"),
                    ("Polymarket/agents", "Patterns for autonomous agent design", "mine"),
                    ("Polymarket/poly-market-maker", "Reference market-maker keeper", "mine"),
                    (
                        "evan-kolberg/prediction-market-backtesting",
                        "Polymarket adapter for NautilusTrader BT",
                        "fork",
                    ),
                    (
                        "aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
                        "Production-grade 15m bot architecture",
                        "mine",
                    ),
                    ("ThinkEnigmatic/polymarket-bot-arena", "Multi-strategy arena pattern", "mine"),
                    ("Archetapp gist (5m bot)", "Best timing/window logic in the wild", "mine"),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Tooling: Infra =====
    story.append(
        section_heading(
            "Tooling Inventory — Infra", color=PURPLE, sub="VPS, monitoring, secrets, CI, ops"
        )
    )
    story.append(
        section_block(
            "Hosting + ops",
            kv_table(
                header=["Layer", "Choice", "Why"],
                col_widths=[130, 140, 248],
                rows=[
                    ("VPS", "AWS Lightsail eu-west-1 Dublin", "Sub-5ms to CLOB; ~$5/mo"),
                    ("OS", "Ubuntu 24.04 LTS", "Long-term stability, security updates"),
                    ("Process supervisor", "systemd", "Auto-restart, journalctl logs"),
                    ("Time discipline", "chrony", "Clock skew < 10ms enforced"),
                    ("Inter-process state", "redis", "Coordinate kill-switches, alert queue"),
                    ("DB replication", "litestream", "trades.db → S3-compatible offsite"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Monitoring + alerts",
            kv_table(
                header=["Tool", "Use"],
                col_widths=[170, 348],
                rows=[
                    ("prometheus-node-exporter", "System metrics on the VPS (CPU, RAM, disk, net)"),
                    ("Bot Prometheus exporter", "Decision counts, win-rate, fill latency, balance"),
                    ("Grafana Cloud free tier", "Dashboards, 14d retention; warn/info"),
                    ("Telegram bot (BotFather)", "CRITICAL alerts; inbound /halt; mobile push"),
                    (
                        "Backblaze B2 (default OD-2)",
                        "Offsite backup of trades.db via litestream; ~$0.005/GB/mo",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Secrets, CI, deployment",
            kv_table(
                header=["Tool", "Use"],
                col_widths=[140, 378],
                rows=[
                    ("direnv + .envrc", "Project-scoped env vars; .envrc gitignored"),
                    ("age", "Encrypted backup of wallet keys; offline-only"),
                    ("1Password CLI (or pass)", "Secrets injection at runtime via op run --"),
                    (
                        "GitHub Actions",
                        "CI on push: lint, type, test, header-check, TODO-grep, import-linter",
                    ),
                    ("pre-commit", "Local enforcement of the same checks before push"),
                    (
                        "Deployment",
                        "git pull + systemctl restart (no second VPS until $1k bankroll)",
                    ),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Architecture: Runtime =====
    story.append(section_heading("Architecture — Runtime (three loops)", color=PURPLE))
    story.append(
        Paragraph(
            "Three concurrent loops on the Dublin VPS. Resolution loop continuously knows "
            "<i>'what does the active market resolve as if it ended right now.'</i> Execution loop "
            "fires orders by deadline at T-30s / T-10s / T-5s, never skipping a window. "
            "Supervisor loop runs every minute checking heartbeat, balance reconciliation, "
            "kill-switch state.",
            BODY,
        )
    )
    story.append(Spacer(1, 8))

    # We re-use a simpler block diagram inline here
    class RuntimeDiagram(Flowable):
        def __init__(self, h=420):
            Flowable.__init__(self)
            self.h, self.w = h, None

        def wrap(self, w, h):
            self.w = w
            return (w, self.h)

        def _wbox(self, c, x, y, w, h, label, sub, accent):
            c.setFillColor(PAPER)
            c.setStrokeColor(GRAY_300)
            c.setLineWidth(0.7)
            c.roundRect(x, y, w, h, 4, stroke=1, fill=1)
            c.setFillColor(accent)
            c.roundRect(x, y, 3, h, 1.5, stroke=0, fill=1)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(x + 9, y + h - 13, label)
            if sub:
                c.setFillColor(GRAY_500)
                c.setFont("Helvetica", 7)
                c.drawString(x + 9, y + h - 22, sub)

        def _arrow(self, c, x1, y1, x2, y2, color=GRAY_500):
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

        def draw(self):
            c = self.canv
            W, H = self.w, self.h

            # VPS container
            c.setFillColor(GRAY_50)
            c.setStrokeColor(GRAY_300)
            c.roundRect(0, 70, W, H - 70, 8, stroke=1, fill=1)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(12, H - 18, "Dublin VPS  ·  AWS Lightsail eu-west-1")

            # Resolution loop column (left)
            ext_y = H - 70
            ext_w = 110
            srcs = [
                ("Binance WS", "BTC/USDT", BLUE),
                ("Coinbase WS", "BTC/USD", BLUE),
                ("Polygon RPC", "Chainlink oracle", PURPLE),
                ("Polymarket WS", "orderbook + fills", AMBER),
            ]
            for i, (n, s, col) in enumerate(srcs):
                self._wbox(c, 14, ext_y - 32 - i * 36, ext_w, 28, n, s, col)

            # Resolution + Execution + Supervisor center column
            mid_x = 14 + ext_w + 22
            mid_w = 145
            procs = [
                ("Resolution loop", "spot + oracle + window state", AMBER),
                ("Execution loop", "T-30s / T-10s / T-5s deadlines", GREEN),
                ("Supervisor loop", "heartbeat, balance, kill-switches", RED),
                ("Strategy + agents", "Tier-3 + meta-decider", TEAL),
            ]
            for i, (n, s, col) in enumerate(procs):
                self._wbox(c, mid_x, ext_y - 32 - i * 36, mid_w, 28, n, s, col)

            # Right column: order_router + CLOB
            ex_x = mid_x + mid_w + 22
            ex_w = 150
            execs = [
                ("risk_manager", "kelly cap + drift detector", RED),
                ("order_router", "py-clob-client + gasless", AMBER),
                ("Polymarket CLOB", "REST + WS  ·  eu-west-2", NAVY),
                ("trades.db", "SQLite + litestream", NAVY_SOFT),
            ]
            for i, (n, s, col) in enumerate(execs):
                if n == "Polymarket CLOB":
                    c.setFillColor(NAVY)
                    c.setStrokeColor(NAVY_DARK)
                    c.roundRect(ex_x, ext_y - 32 - i * 36, ex_w, 28, 4, stroke=1, fill=1)
                    c.setFillColor(PAPER)
                    c.setFont("Helvetica-Bold", 8.5)
                    c.drawString(ex_x + 8, ext_y - 32 - i * 36 + 14, n)
                    c.setFillColor(HexColor("#9FB3CF"))
                    c.setFont("Helvetica", 7)
                    c.drawString(ex_x + 8, ext_y - 32 - i * 36 + 4, s)
                else:
                    self._wbox(c, ex_x, ext_y - 32 - i * 36, ex_w, 28, n, s, col)

            # arrows
            for i in range(4):
                y = ext_y - 18 - i * 36
                self._arrow(c, 14 + ext_w + 1, y, mid_x - 1, y)
                self._arrow(c, mid_x + mid_w + 1, y, ex_x - 1, y)

            # observability bar
            c.setFillColor(NAVY_DARK)
            c.roundRect(14, 78, W - 28, 8, 4, stroke=0, fill=1)
            c.setFillColor(AMBER)
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(20, 80, "PROMETHEUS  ·  GRAFANA CLOUD  ·  TELEGRAM (BotFather, /halt)")

            # laptop
            c.setFillColor(HexColor("#FEF3C7"))
            c.setStrokeColor(AMBER_DK)
            c.roundRect(0, 0, W, 60, 8, stroke=1, fill=1)
            c.setFillColor(NAVY)
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(12, 46, "Laptop  ·  Obsidian + Claude Code")
            c.setFillColor(GRAY_700)
            c.setFont("Helvetica", 8)
            c.drawString(
                12, 32, "Vault indexes ./state/  ←  bot writes runbooks/postmortems via git push"
            )
            c.drawString(
                12,
                18,
                "Read/review/decide.  No live trading from laptop.  Funder key never on VPS.",
            )

    story.append(RuntimeDiagram())
    story.append(PageBreak())

    # ===== Architecture: Ensemble =====
    story.append(
        section_heading(
            "Architecture — Agent Ensemble + Tier-3",
            color=AMBER,
            sub="3 Anthropic agents, 1 meta-decider, deterministic fallback",
        )
    )
    story.append(
        Paragraph(
            "Each window: 3 specialized Haiku 4.5 agents return JSON-validated votes "
            "(side, confidence, rationale). Meta-decider Sonnet 4.6 weighs the 3 votes plus "
            "the deterministic composite signal. Schema-fail or refusal → that agent abstains. "
            "If fewer than 2 valid votes, the deterministic Tier-3 fires standalone with a raised "
            "confidence threshold (composite ≥ 0.6). Tier-3 also catches API rate-limits, latency "
            "budget breaches, and any case where the LLM stack would skip a window.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(AgentEnsembleDiagram(height=380))
    story.append(PageBreak())

    # ===== Architecture: Wallets =====
    story.append(
        section_heading(
            "Architecture — Wallet Topology", color=GREEN, sub="Funder / Signer / Cold; sweep flows"
        )
    )
    story.append(
        Paragraph(
            "Three wallet zones with explicit sweep policy. Funder lives on the laptop "
            "(age-encrypted key, never on the VPS). Signer lives on the VPS (mode-0600 "
            ".envrc, max 2 days of bankroll on hand). Cold storage starts at $2k bankroll "
            "(hardware wallet, Phase 7). Profit cascade: Signer balance > $50 sweeps nightly "
            "to Funder; Funder > $200 sweeps to Cold.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(WalletTopologyDiagram(height=300))
    story.append(PageBreak())

    # ===== Phase pages =====
    phase_color = {
        0: SLATE,
        1: BLUE,
        2: TEAL,
        3: PURPLE,
        4: AMBER,
        5: NAVY_SOFT,
        6: GREEN,
        7: AMBER_DK,
        8: RED,
    }

    phases_detail = [
        (
            0,
            "Foundations",
            "1 day",
            "$0",
            "Stand up the dev environment, verify all account prerequisites, seed the project skeleton. No money, no keys.",
            [
                "Initialize project skeleton with uv (Python 3.11, mypy --strict, ruff, pytest, import-linter, pre-commit).",
                "Init git, create GitHub private repo (gh repo create), push CI workflow with TODO-grep + header-check.",
                "Create Telegram bot via BotFather; capture token + chat_id; smoke-test sendMessage from CLI.",
                "Drop Polymarket/agent-skills into ~/.claude/skills/; verify Claude can answer auth questions citing skill.",
                "Clone reference repos into references/ (gitignored): py-clob-client, agents, poly-market-maker, etc.",
                "Wire Obsidian to vault rooted at ./state/; install obsidian-claude-code-mcp plugin.",
                "Run /init to seed CLAUDE.md with locked decisions + anti-vibe rules + RUNBOOK pointer.",
            ],
            "bash runbooks/gates/phase-0.sh exits 0 (mypy/ruff/test green; remote exists; agent-skills present; Telegram smoke received).",
            "rm -rf and start over; nothing of value lost.",
        ),
        (
            1,
            "Wallet & Auth",
            "0.5 day",
            "~$5 gas",
            "Generate Funder + Signer wallet pair. Derive L2 creds. Prove signing works BEFORE funding. Then $5 gasless test.",
            [
                "Resolve OD-4: read agent-skills/gasless.md; confirm relayer flow; document in design/gasless.md.",
                "Generate Funder + Signer offline; age-encrypt to ~/secrets/polymarket-5m/.",
                "Derive Polymarket L2 creds from Signer privkey via py-clob-client (no funds needed).",
                "Run scripts/test_auth.py — signed read-only call against /info, returns Signer address.",
                "ONLY THEN: fund Funder $50 USDC + $5 MATIC; sweep $20 USDC + 0.5 MATIC to Signer.",
                "Approve Polymarket exchange contract for Signer USDC (one-time on-chain tx).",
                "Place + cancel a $5 limit order on a non-time-critical market via gasless relayer.",
            ],
            "bash runbooks/gates/phase-1.sh exits 0 (auth test green, $20 funded, allowance set, $5 order placed and canceled, evidence captured).",
            "If auth test fails before funding: debug .envrc. If order stuck: wait 5 min, then contact Polymarket support.",
        ),
        (
            2,
            "Read-only Data Plane",
            "2-3 days dev + 7 days capture",
            "~$5 RPC",
            "Three reliable feeds (spot, oracle, market). 7 days of clean capture. Verify the Chainlink heartbeat thesis.",
            [
                "Resolve OD-1: choose Polygon RPC (default Alchemy free tier); get WSS URL into .envrc.",
                "Design data plane: Feed protocol, per-source files, Parquet writer per UTC-day.",
                "Implement spot_feed.py (Binance + Coinbase WS, fan-in aggregator).",
                "Implement oracle_watcher.py (Chainlink BTC/USD AnswerUpdated subscription on Polygon).",
                "Implement market_feed.py (Polymarket WS for active 5m BTC market).",
                "Implement resolver.py: hypothetical_now() vs actual_resolution(window_ts).",
                "Run continuously for 7 calendar days under tmux/launchd; daily file-growth check.",
                "Run scripts/analyze_oracle.py over the 7-day capture; verify median heartbeat ∈ [55s, 65s] and zero sub-30s deviation triggers.",
            ],
            "bash runbooks/gates/phase-2.sh exits 0 (mypy/ruff/test green, 7 daily ticks files exist, oracle analysis criteria all pass).",
            "Feeds drop overnight: investigate cause (WS provider hiccup), restart, EXTEND capture window. Do not advance with gaps.",
        ),
        (
            3,
            "Backtest + LLM A/B Test",
            "3-4 days",
            "$15-50 (with cache discipline)",
            "Build deterministic baseline. Run on 21 days walk-forward. Test if LLM ensemble adds ≥3pp uplift. If not, ship deterministic alone.",
            [
                "Confirm Anthropic credits ≥ $50 + cost-tracker hard-kill at $35/pass.",
                "Wire NautilusTrader Polymarket adapter (or fork evan-kolberg's BT scaffold) to captured Parquet.",
                "Implement deterministic strategy: composite = w_wd*window_delta + w_og*oracle_gap; fire if |composite| ≥ 0.6 AND TTL ∈ [10,30].",
                "Implement fill simulator: top-5 orderbook history + self-impact model (calibrate later from real fills).",
                "Walk-forward: rolling 7-day train, 1-day test, 30 days total (after 7-day warmup).",
                "Implement 3 agents (orderbook, oracle-gap, momentum) + Sonnet meta-decider; explicit prompt-cache layout.",
                "Run A/B: deterministic-only vs deterministic+ensemble; report win-rate, latency, $/decision.",
                "Resolve OD-5: keep ensemble iff uplift ≥ 3pp AND p99 latency ≤ 4s AND $/decision ≤ $0.01.",
            ],
            "bash runbooks/gates/phase-3.sh exits 0 (≥2,500 trades, deterministic ≥ 53%, A/B verdict file committed, total spend ≤ $50).",
            "Deterministic < 53%: don't introduce LLMs. Iterate weights, fee model, threshold. Extend capture if regime-biased.",
        ),
        (
            4,
            "Paper Trading on Live Venue",
            "14 calendar days",
            "$50-195 (top up Anthropic to $150 first)",
            "Run chosen strategy in paper mode against live data for 14 days. Validate the simulator. Catch every bug backtest didn't.",
            [
                "Top up Anthropic to $150 (covers 14d × 24/7 at empirical $0.19-0.58/hr upper bound).",
                "Implement _paper/shadow_book.py — receives strategy decisions, simulates fills against live orderbook.",
                "Implement schema validation + refusal handling: invalid response → agent abstains; <2 valid → Tier-3.",
                "Validate simulator: 100 hypothetical decisions over 24h; ≥90% within 1¢ of real top-of-book.",
                "Plan start date so 14d covers ≥1 CPI/FOMC, ≥1 weekend, ≥1 BTC daily move > 2%; extend if not covered.",
                "Pre-trade decision logging: full input snapshot per decision into state/decisions/<date>.jsonl.",
                "Daily ritual: review previous day's PnL, anomalies, simulator divergence vs backtest > 20%.",
            ],
            "bash runbooks/gates/phase-4.sh exits 0 (14 days clean logs, regime coverage met, simulator ≥90%, paper PnL within 20% of backtest).",
            "Paper diverges > 20%: debug simulator, NOT strategy. Extend if cause unclear.",
        ),
        (
            5,
            "VPS Provisioning",
            "0.5 day setup + 24h staging",
            "$5/mo VPS",
            "Move execution to Dublin. Verify WS-specific latency. Stand up monitoring + Telegram. Stage 24h before going live.",
            [
                "Provision Lightsail eu-west-1 Dublin: 2vCPU/4GB/80GB NVMe, Ubuntu 24.04, static IP.",
                "Harden: SSH key-only on port 2222, ufw, fail2ban, unattended-upgrades, non-root user, chrony.",
                "Install: Python 3.11, uv, redis, prometheus-node-exporter, litestream.",
                "Latency-check WS specifically: wscat round-trip to wss://ws-subscriptions-clob.polymarket.com/ws/market — p50 < 5ms, p99 < 15ms.",
                "Create two systemd units: bot-staging (paper, port 9101) and bot (live, port 9100, disabled).",
                "Wire Prometheus → Grafana Cloud; tg-alerter.service for Telegram CRITICAL alerts; /halt inbound test.",
                "Move Signer key via age-encrypted SSH transfer; .envrc mode 0600. Funder key NEVER touches VPS.",
                "Run bot-staging for 24h watching metrics + alerts.",
            ],
            "bash runbooks/gates/phase-5.sh exits 0 (staging healthy 24h, WS p99 < 15ms, chrony offset < 10ms, /halt test passed, litestream replicating).",
            "Latency > 15ms: try a different AZ within eu-west-1. /halt fails: debug tg-alerter polling.",
        ),
        (
            6,
            "Live with Kill-Switches",
            "14 calendar days",
            "$1,000 capital + ~$50-195 LLM",
            "$1,000 funded. $5 flat per trade (0.5% sizing). Five kill-switches all tested. Postmortem any anomaly > $3.",
            [
                "Top up Anthropic to $300 (covers Phase 6 14d × 24/7 + buffer).",
                "Implement 5 kill-switches: heartbeat, slippage, drawdown -$50/-$100, reconciliation drift, win-rate drift.",
                "Synthetic-trip every kill-switch in test before live: tests/kill_switches/*.",
                "Strategy sizing.py: $5 flat for first 100 trades; then max($5, kelly * bankroll * conf), cap 10% = $100.",
                "Funder/Signer split: Funder $900, Signer ≤$100; nightly sweep Signer > $100 back to Funder.",
                "Daily 12:00 UTC ritual: scripts/daily_recon.py → Telegram + state/daily/.",
                "Postmortem any kill-switch trip OR > $3 unexplained loss in state/postmortems/.",
                "Optional after 7 stable days: maker-rebate layer (cap 25% of bankroll in resting orders).",
            ],
            "bash runbooks/gates/phase-6.sh exits 0 (14d live, ≥100 trades, all 5 kill-switches synthetic-tripped, no recon drift > $0.50, no daily breaker trip).",
            "Drawdown breaker trips: 24h cooling-off MANDATORY. Postmortem signed off by user before re-enable.",
        ),
        (
            7,
            "Scale + Maker Rebates",
            "ongoing — 7d per rung minimum",
            "bankroll-driven",
            "Step bankroll only after positive 7-day run on previous rung. $1k → $3k → $10k → $30k. Hardware wallet at the $3k step.",
            [
                "Rung 7.1 — $3,000: Kelly × 0.25; resolve OD-6 (Ledger for Funder, ~$80); breaker -$150/day.",
                "Rung 7.2 — $10,000: Kelly × 0.20; multi-account proxy wallets; per-account caps; breaker -$500/day.",
                "Rung 7.3 — $30,000: Kelly × 0.15; LLC consideration; Koinly tax integration; breaker -$1,500/day.",
                "Variant arena: second strategy in shadow; weekly compete-and-allocate (pattern from polymarket-bot-arena).",
                "Quarterly: scripts/refit_weights.py over last 30d; promote only if uplift ≥ 1pp AND 48h paper validation matches.",
            ],
            "Per-rung: 7+ days positive PnL, zero kill-switch trips, no unexplained losses on prior rung.",
            "Step back one rung; never skip rungs.",
        ),
        (
            8,
            "Hardening",
            "ongoing",
            "TBD",
            "Production-grade ops. Migrations. Standby. Multi-account. Re-evaluate dropped LLM ensemble if deterministic decays.",
            [
                "Track USDC.e → native USDC migration; double-write/read during rollout.",
                "Frankfurt warm standby Lightsail; litestream replication; failover playbook.",
                "Multi-account proxy wallets at > $50k; per-account caps and daily reconciliation.",
                "Quarterly Polymarket changelog review (1 day/quarter budgeted).",
                "Re-evaluate dropped LLM ensemble if deterministic strategy decays > 3pp.",
                "Re-evaluate OpenAI fallback once Tier 4 Anthropic limits are insufficient.",
            ],
            "Each item has its own design doc + implementation + test pass.",
            "Items can be deferred; none block live ops.",
        ),
    ]

    for n, title, dur, cost, intent, items, gate, rollback in phases_detail:
        story.append(
            PhaseDetailBlock(n, phase_color[n], title, dur, cost, intent, items, gate, rollback)
        )
        story.append(Spacer(1, 12))
        # only one phase per page for readability
        story.append(PageBreak())

    # ===== Risk Register =====
    story.append(
        section_heading(
            "Risk Register", color=RED, sub="Severity-tagged. Read at every phase boundary."
        )
    )
    risks = [
        (
            "BLOCKER",
            "Jurisdiction (resolved: UAE permitted)",
            "Polymarket geofences US/UK/FR/BE/SG/TH/AU/Ontario.",
            "UAE confirmed permitted. If user moves jurisdictions, project may need to halt.",
        ),
        (
            "BLOCKER",
            "MEV / public-mempool front-running",
            "Public RPC orders can be sandwiched by Polygon MEV bots.",
            "Use Polymarket gasless relayer for ALL order submission (locked decision #17). Never public-RPC orders.",
        ),
        (
            "BLOCKER",
            "Obsidian-on-VPS architectural mismatch",
            "Obsidian is desktop GUI; can't run on the bot VPS.",
            "Vault stays on laptop; bot writes markdown to ./state/ in git, laptop pulls (locked decision #18).",
        ),
        (
            "MAJOR",
            "Wallet compromise / single key blast radius",
            "Leaked private key drains everything immediately.",
            "Funder/Signer separation. Signer ≤2 days bankroll. Hardware wallet for Funder at $2k.",
        ),
        (
            "MAJOR",
            "Strategy edge defensibility",
            "Co-located bots in eu-west-2 may beat Dublin's 1-5ms.",
            "Compete on signal quality + last-10s timing, not raw round-trips. Win-rate drift detector halts on regime change.",
        ),
        (
            "MAJOR",
            "Settlement migration USDC.e → native USDC",
            "Mid-trade migration could leave positions inconsistent.",
            "Phase 8 explicit migration runbook; double-write/read during rollout.",
        ),
        (
            "MAJOR",
            "Oracle stuck / Polygon reorg",
            "Stale oracle while bot has open position.",
            "Oracle staleness > 90s halts entries. Reorg: re-fetch from chain, accept ground truth.",
        ),
        (
            "MAJOR",
            "Schema/refusal failures from LLM",
            "Sonnet meta could return malformed JSON or safety-refuse.",
            "validate_or_retry wrapper on every call; <2 valid agents → Tier-3 fires.",
        ),
        (
            "MAJOR",
            "Bankroll reconciliation drift",
            "Internal state ≠ on-chain USDC after partial fill / settled position.",
            "Reconciler kill-switch: drift > $0.50 sustained 60s halts entries.",
        ),
        (
            "MINOR",
            "Min-order math",
            "Polymarket 5-share / $4.75 min must always be coverable.",
            "$5 flat for first 100 trades (clears minimum). At $1k bankroll this is 0.5% sizing — fine. Kelly only after empirical win-rate exists.",
        ),
        (
            "MINOR",
            "Anthropic Tier 1 RPM limits",
            "$50 credit account is Tier 1 until $40 spent + 7 days.",
            "Phase 3 fits in Tier 1; top up to $150 (Tier 2) before Phase 4 starts.",
        ),
        (
            "MINOR",
            "Tax / regulatory tracking",
            "Per-trade tax basis at scale.",
            "Manual CSV export through Phase 7; integrate Koinly at first profitable quarter.",
        ),
    ]
    story.append(risk_table_styled(risks))
    story.append(PageBreak())

    # ===== Cost & Timeline =====
    story.append(section_heading("Cost & Timeline", color=BLUE, sub="Cumulative spend per phase"))
    story.append(
        kv_table(
            header=["Phase", "Wall-clock", "Phase USD cost", "Cumulative", "What drives the cost"],
            col_widths=[100, 90, 90, 90, 148],
            rows=[
                ("0 — Foundations", "1 day", "$0", "$0", "—"),
                ("1 — Wallet & Auth", "0.5 day", "$5", "$5", "Polygon gas"),
                ("2 — Data Plane", "3d + 7d capture", "$5", "$10", "Alchemy free tier covers most"),
                (
                    "3 — Backtest + A/B",
                    "3-4 days",
                    "$15-50",
                    "$25-60",
                    "Anthropic API (cache-disciplined)",
                ),
                (
                    "4 — Paper Trading",
                    "14 calendar days",
                    "$50-195",
                    "$75-255",
                    "Anthropic 24/7 (top up to $150)",
                ),
                (
                    "5 — VPS Provisioning",
                    "0.5d + 24h staging",
                    "$5/mo",
                    "$80-260",
                    "Lightsail Dublin",
                ),
                (
                    "6 — Live",
                    "14 calendar days",
                    "$50-195 + $1,000 capital",
                    "$1,130-1,455",
                    "Anthropic 24/7 (top up to $300) + at-risk capital",
                ),
                (
                    "7 — Scale (per rung)",
                    "7d per rung minimum",
                    "bankroll-driven",
                    "+capital",
                    "Larger sums at risk; ops costs flat",
                ),
                ("8 — Hardening", "ongoing", "TBD", "TBD", "Per-item cost; ongoing OPEX"),
            ],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            "<b>Sustained ops:</b> ~$200/month budget driven primarily by Anthropic API at "
            "empirical $0.19-0.58/hour × 24/7. Optional reductions: cache discipline (system "
            "prompt as cache breakpoint), agent count reduction, lower-frequency meta-decider.",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Operating Discipline (page 1 of 2) =====
    story.append(
        section_heading(
            "Operating Discipline (1/2)",
            color=AMBER,
            sub="25 anti-drift rules — pin above the desk",
        )
    )

    rule_groups_1 = [
        (
            "Session discipline",
            AMBER,
            [
                (
                    "One Claude Code session = one phase task. End the session when the task ends.",
                    "Long sessions accumulate context rot; decisions get rationalized backwards.",
                ),
                (
                    "Start each session by pasting the next task verbatim from RUNBOOK.md as the first prompt.",
                    "Forces you to know what you're starting.",
                ),
                (
                    "Stop at 50% context use if no gate yet. Don't /compact mid-task.",
                    "Compaction summarizes Claude's perceived state — drift point.",
                ),
                (
                    "Cap focused session length at 4 hours.",
                    "Tired operators accept first proposals.",
                ),
                (
                    "End every session with a 2-line note in state/sessions/<date>.md.",
                    "Future-you and future-Claude both need this anchor.",
                ),
            ],
        ),
        (
            "Decision logging",
            BLUE,
            [
                (
                    "Code change → git commit, conventional-commits format. No WIP commits.",
                    "Small named commits make rollback surgical.",
                ),
                (
                    "Architecture change → memory file edit + commit in same PR.",
                    "Code without preserved rationale dies on resumption.",
                ),
                (
                    "Bug → GitHub issue with reproduction, even if fixed in the same hour.",
                    "Bug history is your taxonomy; recurrences signal a pattern.",
                ),
                (
                    '"Maybe later" → GitHub issue with `icebox` label, never a TODO in code.',
                    "TODOs grow silently; icebox is visible and prunable.",
                ),
            ],
        ),
        (
            "Manual checkpoints",
            TEAL,
            [
                (
                    "Read every diff Claude proposes before accepting. Never blanket-accept.",
                    "Drift happens in small unreviewed edits.",
                ),
                (
                    "Run the gate command yourself in your own terminal. Watch it exit 0.",
                    "Claude can hallucinate gate output; your terminal cannot.",
                ),
                (
                    "Tag green gates by hand: git tag phase-N-pass && git push --tags.",
                    "Tags are immovable rollback points.",
                ),
                (
                    "Before advancing a phase, re-read the previous checkpoint memory file.",
                    "Gates exist to break momentum.",
                ),
            ],
        ),
    ]

    for group, color, items in rule_groups_1:
        story.append(Paragraph(f"<b>{group}</b>", H3))
        for rule, why in items:
            row = Table(
                [
                    [
                        Table(
                            [[""]],
                            colWidths=[6],
                            rowHeights=[28],
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
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(row)
        story.append(Spacer(1, 4))

    story.append(PageBreak())

    # ===== Operating Discipline (page 2 of 2) =====
    story.append(section_heading("Operating Discipline (2/2)", color=AMBER))
    rule_groups_2 = [
        (
            "macOS tooling",
            PURPLE,
            [
                (
                    "iTerm2 + tmux, one named tmux session per project. Windows: bot, repl, gates, git.",
                    "Separates concerns visually; survives terminal close.",
                ),
                (
                    "VS Code (or Cursor) for diff review with GitLens, ruff, mypy. Even for code Claude wrote.",
                    "Editor view is more honest than chat view.",
                ),
                (
                    "uv for Python on Apple Silicon. Skip system Python, skip pyenv, skip Anaconda.",
                    "Apple Silicon + scientific Python has a long tail of arch pain; uv handles it.",
                ),
                (
                    "1Password CLI (or pass) for secrets. Use `op run -- python script.py` to inject at runtime.",
                    "Secrets never live on disk in plaintext.",
                ),
                (
                    "Two browser profiles: one for Polymarket / Anthropic / GitHub, one for personal.",
                    "Scoped session cookies prevent cross-pollination of trading auth.",
                ),
            ],
        ),
        (
            "Anti-drift triggers",
            RED,
            [
                (
                    "Same bug, two iterations → stop and write runbooks/incidents/<date>-<slug>.md before iteration #3.",
                    "That's the 3-fix rule. Writing the incident usually surfaces the real root cause.",
                ),
                (
                    "src/ changed but no design/ change in the same commit → reject the commit.",
                    "Silent design drift is the slowest, deadliest kind.",
                ),
                (
                    'Gate criteria softened ("close enough", "flaky test") without an approved decision doc → revert, escalate.',
                    "Once you soften one gate, you'll soften them all.",
                ),
                (
                    'Any "let me just" or "I\'ll quickly" from Claude → freeze the conversation, ask why.',
                    "Those phrases precede out-of-scope edits.",
                ),
            ],
        ),
        (
            "Recovery",
            GREEN,
            [
                (
                    "When drift suspected: git log --oneline -20 first. Understand state before acting.",
                    "Panic-rollback loses real work.",
                ),
                (
                    "Hard-reset to last green gate is your actual reset button: git reset --hard phase-N-pass.",
                    "Anything between gates is by definition unverified.",
                ),
                (
                    "Post-recovery: write runbooks/postmortems/drift-<date>.md (what drifted, when noticed, what reset to).",
                    "Drift patterns repeat; the postmortem is how you spot the pattern.",
                ),
            ],
        ),
    ]
    for group, color, items in rule_groups_2:
        story.append(Paragraph(f"<b>{group}</b>", H3))
        for rule, why in items:
            row = Table(
                [
                    [
                        Table(
                            [[""]],
                            colWidths=[6],
                            rowHeights=[28],
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
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(row)
        story.append(Spacer(1, 4))

    story.append(PageBreak())

    # ===== Sources =====
    story.append(
        section_heading("Sources & References", color=BLUE, sub="Verified canonical links")
    )
    story.append(
        section_block(
            "Polymarket — Official",
            kv_table(
                rows=[
                    ("Polymarket Developer Docs", "docs.polymarket.com/developers/"),
                    ("py-clob-client (Python, primary)", "github.com/Polymarket/py-clob-client"),
                    ("rs-clob-client (Rust)", "github.com/Polymarket/rs-clob-client"),
                    ("agent-skills (drop into Claude)", "github.com/Polymarket/agent-skills"),
                    ("agents (TS autonomous framework)", "github.com/Polymarket/agents"),
                    ("poly-market-maker (reference MM)", "github.com/Polymarket/poly-market-maker"),
                    (
                        "Authentication (L1 + L2)",
                        "docs.polymarket.com/developers/CLOB/authentication",
                    ),
                    ("Maker Rebates Program", "help.polymarket.com/en/articles/13364471"),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Reference bot implementations",
            kv_table(
                rows=[
                    (
                        "Archetapp 5m bot gist",
                        "gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69",
                    ),
                    (
                        "aulekator 15m bot",
                        "github.com/aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
                    ),
                    ("ThinkEnigmatic 5m arena", "github.com/ThinkEnigmatic/polymarket-bot-arena"),
                    (
                        "evan-kolberg backtest adapters",
                        "github.com/evan-kolberg/prediction-market-backtesting",
                    ),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
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
                        "Chainlink BTC/USD on Polygon",
                        "data.chain.link/feeds/polygon/mainnet/btc-usd",
                    ),
                    ("USDC.e to native USDC migration (Block)", "theblock.co/post/388670"),
                ],
                col_widths=[260, 258],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Claude tooling",
            kv_table(
                rows=[
                    (
                        "iansinnott/obsidian-claude-code-mcp",
                        "github.com/iansinnott/obsidian-claude-code-mcp",
                    ),
                    ("MarkusPfundstein/mcp-obsidian", "github.com/MarkusPfundstein/mcp-obsidian"),
                    (
                        "caiovicentino/polymarket-mcp-server",
                        "github.com/caiovicentino/polymarket-mcp-server",
                    ),
                    ("artvandelay/polymarket-agents", "github.com/artvandelay/polymarket-agents"),
                    (
                        "agent-next/polymarket-paper-trader",
                        "github.com/agent-next/polymarket-paper-trader",
                    ),
                ],
                col_widths=[260, 258],
            ),
        )
    )

    story.append(Spacer(1, 14))
    story.append(HBar(color=GRAY_300, thickness=0.6))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "<font color='#64748B'><i>This document is a living specification. The companion files "
            "<b>RUNBOOK.md</b> (execution source-of-truth) and the locked-decisions memory file "
            "win when in conflict. Update at every phase gate.</i></font>",
            BODY_SM,
        )
    )

    doc.build(story)
    return out


if __name__ == "__main__":
    out = build()
    print(f"Built: {out}")
