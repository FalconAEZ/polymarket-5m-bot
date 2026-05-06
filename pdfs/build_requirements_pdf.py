"""Build REQUIREMENTS.pdf — bootstrap shopping list for the entire project.

What Claude Code (and the operator) needs to pull, install, configure, and
create from the web before the first line of bot code is written. Distinct
from BUILD_SPEC.pdf (architecture) and BONEREAPER_STUDY.pdf (research stream).
Green accent signals "go / setup / kickstart."
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


# ===== Design system (green accent for setup/go) =====
NAVY = HexColor("#0B1F3A")
NAVY_DARK = HexColor("#06142A")
NAVY_SOFT = HexColor("#1B3358")
AMBER = HexColor("#F5A524")
TEAL = HexColor("#1AA39A")
GREEN = HexColor("#23A26D")
GREEN_DK = HexColor("#16794D")
MINT = HexColor("#D9F2E5")
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
    def __init__(self, text, color=GREEN, fontsize=17, height=24, sub=None):
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


class CodeBlock(Flowable):
    """Styled multi-line code block with title."""

    def __init__(self, title, lines, accent=GREEN):
        Flowable.__init__(self)
        self.title = title
        self.lines = lines
        self.accent = accent
        self.line_h = 11

    def wrap(self, w, h):
        self.w = w
        self.H = 22 + self.line_h * len(self.lines) + 8
        return (w, self.H)

    def draw(self):
        c = self.canv
        H = self.H
        # title strip
        c.setFillColor(NAVY)
        c.roundRect(0, H - 18, self.w, 18, 3, stroke=0, fill=1)
        c.setFillColor(self.accent)
        c.rect(0, H - 18, 4, 18, stroke=0, fill=1)
        c.setFillColor(PAPER)
        c.setFont("Helvetica-Bold", 8)
        c.drawString(10, H - 13, self.title)
        # body
        body_h = H - 22
        c.setFillColor(GRAY_50)
        c.setStrokeColor(GRAY_200)
        c.setLineWidth(0.4)
        c.roundRect(0, 0, self.w, body_h, 3, stroke=1, fill=1)
        c.setFillColor(GRAY_900)
        c.setFont("Courier", 7.8)
        y = body_h - 12
        for ln in self.lines:
            c.drawString(8, y, ln)
            y -= self.line_h


class PhaseBadge(Flowable):
    """Small rounded phase pill — used inline in tables."""

    def __init__(self, text, color):
        Flowable.__init__(self)
        self.text, self.color = text, color

    def wrap(self, w, h):
        return (40, 12)

    def draw(self):
        c = self.canv
        c.setFillColor(self.color)
        c.roundRect(0, 0, 40, 12, 5, stroke=0, fill=1)
        c.setFillColor(PAPER)
        c.setFont("Helvetica-Bold", 7)
        c.drawCentredString(20, 3, self.text)


class ChecklistRow(Flowable):
    """Single row with [ ] checkbox + text."""

    def __init__(self, items):
        Flowable.__init__(self)
        self.items = items

    def wrap(self, w, h):
        self.w = w
        self.H = 14 * len(self.items) + 4
        return (w, self.H)

    def draw(self):
        c = self.canv
        for i, it in enumerate(self.items):
            y = self.H - (i + 1) * 14 + 2
            # checkbox
            c.setStrokeColor(GREEN)
            c.setLineWidth(0.8)
            c.rect(0, y, 8, 8, stroke=1, fill=0)
            # text
            c.setFillColor(GRAY_900)
            c.setFont("Helvetica", 9)
            c.drawString(14, y + 1, it)


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
    c.setFillColor(GREEN)
    c.rect(0, PAGE_H - 12, PAGE_W * 0.32, 12, stroke=0, fill=1)
    c.setFillColor(HexColor("#102B1F"))
    for gx in range(int(PAGE_W * 0.55), int(PAGE_W), 14):
        for gy in range(20, int(PAGE_H * 0.45), 14):
            c.circle(gx, gy, 1.0, stroke=0, fill=1)
    c.setFillColor(GREEN)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(MARGIN_X, PAGE_H - 60, "REQUIREMENTS  ·  v1  ·  2026")
    title_y = PAGE_H - 240
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 38)
    c.drawString(MARGIN_X, title_y, "Project")
    c.drawString(MARGIN_X, title_y - 42, "Bootstrap")
    c.setStrokeColor(GREEN)
    c.setLineWidth(3)
    c.line(MARGIN_X, title_y - 56, MARGIN_X + 90, title_y - 56)
    c.setFillColor(HexColor("#9FB3CF"))
    c.setFont("Helvetica", 13)
    c.drawString(
        MARGIN_X,
        title_y - 82,
        "Everything Claude Code needs to pull, install, or create from the web",
    )
    c.drawString(MARGIN_X, title_y - 100, "before the first line of bot code is written.")
    meta_y = 80
    c.setFillColor(HexColor("#7B93B5"))
    c.setFont("Helvetica-Bold", 8)
    for i, label in enumerate(["TIME TO COMPLETE", "TOTAL COST NOW", "OS", "STAGE"]):
        c.drawString(MARGIN_X + i * 130, meta_y + 28, label)
    c.setFillColor(PAPER)
    c.setFont("Helvetica-Bold", 11)
    for i, val in enumerate(["~2-3 hours", "$0 (creds in hand)", "macOS", "pre-Phase 0"]):
        c.drawString(MARGIN_X + i * 130, meta_y + 12, val)
    c.setFillColor(GREEN)
    c.rect(0, 0, PAGE_W, 6, stroke=0, fill=1)


def header_footer(c, doc):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - 4, PAGE_W, 4, stroke=0, fill=1)
    c.setFillColor(GREEN)
    c.rect(0, PAGE_H - 4, PAGE_W * 0.18, 4, stroke=0, fill=1)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, PAGE_H - 14, "PROJECT BOOTSTRAP  ·  REQUIREMENTS  ·  v1")
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - 14, "2026-05-04")
    c.setStrokeColor(GRAY_200)
    c.setLineWidth(0.4)
    c.line(MARGIN_X, 22, PAGE_W - MARGIN_X, 22)
    c.setFillColor(GRAY_500)
    c.setFont("Helvetica", 8)
    c.drawString(MARGIN_X, 12, "Pre-flight setup  ·  Hamad")
    c.drawRightString(PAGE_W - MARGIN_X, 12, f"Page {doc.page}")


# ===== Helpers =====
def section_heading(text, color=GREEN, sub=None):
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
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
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


def bullet_list(items, marker="●", color="#23A26D"):
    return [
        Paragraph(f'<font color="{color}"><b>{marker}</b></font>&nbsp;&nbsp;{it}', BULLET)
        for it in items
    ]


# ===== Build =====
def build():
    out = "/Users/hamad/Desktop/PolyMarket-5m/pdfs/REQUIREMENTS.pdf"
    doc = BaseDocTemplate(
        out,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_Y + 4,
        bottomMargin=MARGIN_Y + 6,
        title="Project Bootstrap — Requirements",
        author="Hamad",
        subject="What Claude Code needs to pull or create from the web",
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
            "Table of Contents",
            color=NAVY_SOFT,
            sub="Run sections in order — each one assumes the prior is done",
        )
    )
    toc_rows = [
        ("01", "How to use this doc", "What's in / what's not.", "p. 3"),
        ("02", "Pre-flight checklist", "Hard prerequisites — verify before any installs.", "p. 4"),
        ("03", "Web accounts to create", "GitHub, Anthropic, Telegram, Alchemy.", "p. 5"),
        ("04", "macOS tools to install", "brew packages: uv, gh, direnv, age, etc.", "p. 6"),
        ("05", "Python toolchain", "uv-managed; mypy/ruff/pytest pinned.", "p. 7"),
        ("06", "Claude Code skills", "Drop into ~/.claude/skills/.", "p. 8"),
        (
            "07",
            "Built-in skills + slash commands",
            "What you already have; when to use it.",
            "p. 9",
        ),
        ("08", "MCP servers", "Obsidian + research-only Polymarket MCPs.", "p. 10"),
        ("09", "Reference repos to clone", "py-clob-client, agents, etc.", "p. 11"),
        ("10", "Reference docs to read", "Polymarket / NautilusTrader / Chainlink.", "p. 12"),
        ("11", "Polymarket-specific", "Auth flow, gasless relayer, contracts.", "p. 13"),
        ("12", "Bonereaper study extras", "RPC, ML libs, Streamlit.", "p. 14"),
        ("13", "Deferred to Phase 5", "VPS, Lightsail, Backblaze (NOT now).", "p. 15"),
        ("14", "Bootstrap script", "Single bash to install most things.", "p. 16"),
        ("15", "Verification checklist", 'Run before declaring "ready for Phase 0".', "p. 18"),
        ("16", "Cost summary", "What costs money now / later.", "p. 19"),
    ]
    toc_num_style = ParagraphStyle(
        "tocnum", parent=BODY, fontName="Helvetica-Bold", fontSize=12, textColor=GREEN, leading=14
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
    toc = Table(toc_data, colWidths=[26, 165, 270, 40], hAlign="LEFT")
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

    # ===== How to use =====
    story.append(
        section_heading("How to use this doc", color=GREEN, sub="In / out scope and reading order")
    )
    story.append(
        StatCards(
            [
                ("~2-3h", "Total wall-clock to complete bootstrap", GREEN),
                ("$0", "Cost today (creds already in hand)", BLUE),
                ("16", "Sections — run sequentially", AMBER),
                ("0", "Lines of bot code (that comes after)", PURPLE),
            ]
        )
    )
    story.append(Spacer(1, 12))
    story.append(Paragraph("<b>What this doc IS</b>", H3))
    for it in bullet_list(
        [
            "Sequential bootstrap: web accounts, local tools, Claude skills, MCPs, reference repos, docs to bookmark.",
            "Verification checklist that proves you're ready for RUNBOOK.md Phase 0.",
            "A bootstrap shell script that automates the install steps you'd otherwise type yourself.",
            "Costs surfaced honestly — what you pay now ($0), what you'll pay at Phase 4 ($150 Anthropic top-up), what at Phase 5 ($5/mo VPS).",
        ]
    ):
        story.append(it)
    story.append(Spacer(1, 6))
    story.append(Paragraph("<b>What this doc IS NOT</b>", H3))
    for it in bullet_list(
        [
            "Architecture or strategy — that's BUILD_SPEC.pdf.",
            "Phase-by-phase execution — that's RUNBOOK.md.",
            "The bonereaper research stream — that's BONEREAPER_STUDY.pdf.",
            "Locked decisions — those live in memory/project_decisions.md.",
        ],
        marker="○",
        color="#E5484D",
    ):
        story.append(it)
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>Reading order:</b> finish §02 (pre-flight) before doing anything. Then §03 → §10 in order. "
            "§14 (bootstrap script) automates §04-§09 if you'd rather not type it all by hand. "
            "§15 verifies you're ready for Phase 0.",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Pre-flight checklist =====
    story.append(
        section_heading(
            "Pre-flight checklist",
            color=RED,
            sub="Hard prerequisites — verify these BEFORE any installs",
        )
    )
    story.append(
        Paragraph(
            "Each item is a non-negotiable. Failing any of them means stop bootstrap and resolve "
            "the underlying issue. Do not work around them.",
            BODY,
        )
    )
    story.append(Spacer(1, 8))

    pf_groups = [
        (
            "Identity & jurisdiction",
            RED,
            [
                "I am physically resident in the UAE (Polymarket-permitted).",
                "I am NOT in US/UK/FR/BE/SG/TH/AU/Ontario.",
                "I will not connect a personal wallet from a restricted geography via VPN.",
            ],
        ),
        (
            "Hardware (laptop)",
            AMBER,
            [
                "macOS laptop with at least 16GB RAM and 80GB free disk.",
                "Apple Silicon (M1/M2/M3/M4) preferred for speed; Intel works.",
                "Stable network — fiber or 50+ Mbps cable. WS feeds need it.",
            ],
        ),
        (
            "Existing accounts I should already have",
            BLUE,
            [
                "GitHub account with SSH key configured.",
                "Anthropic Console account with API key + ≥$50 credits loaded.",
                "Telegram on phone (any account; we'll create a bot in §03).",
                "An existing exchange account where I can withdraw ~$1,050 USDC + ~$5 MATIC to Polygon (Phase 1, not now).",
            ],
        ),
        (
            "Tools I might already have (not blocking bootstrap)",
            TEAL,
            [
                "Homebrew installed (brew --version returns).",
                "Python 3.11+ available (python3 --version).",
                "git installed and configured with name + email.",
                "VS Code or Cursor (any modern editor).",
                "Obsidian app installed (we'll set up the vault in §04).",
            ],
        ),
    ]
    for group, color, items in pf_groups:
        story.append(Paragraph(f"<b>{group}</b>", H3))
        for it in items:
            row = Table(
                [
                    [
                        Table(
                            [[""]],
                            colWidths=[6],
                            rowHeights=[14],
                            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), color)]),
                        ),
                        Paragraph(it, BODY_SM),
                        Paragraph(
                            "☐", ParagraphStyle("cb", parent=BODY, fontSize=11, textColor=color)
                        ),
                    ],
                ],
                colWidths=[6, 482, 22],
                hAlign="LEFT",
            )
            row.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (0, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (1, 0), (1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(row)
        story.append(Spacer(1, 4))
    story.append(PageBreak())

    # ===== Web accounts =====
    story.append(
        section_heading(
            "Web accounts to create", color=BLUE, sub="Sign-ups + API keys + a Telegram bot"
        )
    )
    story.append(
        section_block(
            "Anthropic API",
            kv_table(
                rows=[
                    ("Sign up at", "console.anthropic.com"),
                    (
                        "What to do",
                        "Generate an API key under Settings → API Keys; load $50 credits via Settings → Plans & Billing.",
                    ),
                    (
                        "Save where",
                        ".envrc as ANTHROPIC_API_KEY (do this in §05 after we install direnv).",
                    ),
                    ("Phase", "Used Phase 0 (Telegram smoke) onward; agents start Phase 3."),
                    ("Cost today", "$0 if you already loaded $50 (locked decision #14)."),
                ],
                col_widths=[100, 418],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "GitHub (private repo)",
            kv_table(
                rows=[
                    (
                        "Required",
                        "Personal account (free), SSH key configured, gh CLI installed (§04).",
                    ),
                    (
                        "Repo creation",
                        "Done by bootstrap script in §14: gh repo create polymarket-5m-bot --private.",
                    ),
                    ("CI", "Free GitHub Actions tier — sufficient at this scale."),
                    ("Phase", "0+."),
                ],
                col_widths=[100, 418],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Telegram bot via @BotFather",
            kv_table(
                rows=[
                    (
                        "Step 1",
                        "On phone Telegram, open @BotFather → /newbot → name it (e.g. polymarket-5m-ops) → username ending in -bot.",
                    ),
                    ("Step 2", "BotFather returns a bot token. Save."),
                    ("Step 3", "Message your new bot once (any text) so it has a chat with you."),
                    (
                        "Step 4",
                        'On laptop: curl "https://api.telegram.org/bot&lt;TOKEN&gt;/getUpdates" → find your chat.id.',
                    ),
                    ("Save where", ".envrc as TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."),
                    (
                        "Test send",
                        'curl -X POST "https://api.telegram.org/bot&lt;TOKEN&gt;/sendMessage" -d "chat_id=&lt;ID&gt;&amp;text=hello" → confirm message arrives on phone.',
                    ),
                    ("Phase", "0+ (smoke test in Phase 0 gate)."),
                ],
                col_widths=[100, 418],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Alchemy (Polygon RPC)",
            kv_table(
                rows=[
                    ("Sign up at", "alchemy.com"),
                    (
                        "What to do",
                        "Create a Polygon Mainnet app → copy the WSS URL (the wss:// one, not https://).",
                    ),
                    ("Save where", ".envrc as POLYGON_RPC_URL."),
                    (
                        "Cost",
                        "Free tier: 300M compute units/month — covers everything through Phase 6.",
                    ),
                    ("Phase", "Used Phase 2 onward (oracle subscription + bonereaper ingest)."),
                ],
                col_widths=[100, 418],
            ),
        )
    )
    story.append(PageBreak())

    # ===== macOS tools =====
    story.append(
        section_heading("macOS tools to install", color=AMBER, sub="brew handles most of it")
    )
    story.append(
        Paragraph(
            "If you already have these, skip them. Verify with the listed check command. "
            "Bootstrap script (§14) installs anything missing.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))

    story.append(
        section_block(
            "Core tools",
            kv_table(
                header=["Tool", "Purpose", "Install (Homebrew)", "Verify"],
                col_widths=[80, 170, 160, 110],
                rows=[
                    ("brew", "Package manager", "see brew.sh", "brew --version"),
                    ("git", "Version control", "brew install git", "git --version"),
                    ("gh", "GitHub CLI", "brew install gh", "gh auth status"),
                    ("uv", "Python pkg/env manager", "see astral.sh/uv", "uv --version"),
                    ("node", "JS runtime (some MCPs)", "brew install node", "node --version"),
                    (
                        "direnv",
                        "Project-scoped env vars",
                        "brew install direnv",
                        "direnv --version",
                    ),
                    ("age", "Encrypt wallet keys offline", "brew install age", "age --version"),
                    ("jq", "JSON munging on CLI", "brew install jq", "jq --version"),
                    (
                        "wscat",
                        "WS round-trip latency check",
                        "brew install node + npm i -g wscat",
                        "wscat --version",
                    ),
                    ("chrony", "Clock skew (Phase 5 VPS only)", "—", "(N/A locally)"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Recommended (not strictly required)",
            kv_table(
                header=["Tool", "Why"],
                col_widths=[150, 368],
                rows=[
                    ("iTerm2 + tmux", "tmux session per project; survives terminal close"),
                    ("VS Code or Cursor", "diff review, GitLens / ruff / mypy extensions"),
                    ("1Password CLI (op)", "secrets injection at runtime (op run -- python ...)"),
                    ("Obsidian", "memory vault on laptop"),
                    ("Postman or Insomnia", "manual probing of Polymarket REST endpoints"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        CodeBlock(
            "install verification (run from any dir)",
            [
                "for cmd in brew git gh uv node direnv age jq wscat; do",
                '  if command -v $cmd >/dev/null; then echo "OK   $cmd"; else echo "MISS $cmd"; fi',
                "done",
            ],
        )
    )
    story.append(PageBreak())

    # ===== Python toolchain =====
    story.append(
        section_heading("Python toolchain", color=AMBER, sub="uv-managed; lockfile committed")
    )
    story.append(
        Paragraph(
            "All Python deps managed via uv. Versions pinned in pyproject.toml; lockfile uv.lock "
            "committed to git. CI runs uv sync --frozen so prod and CI agree exactly.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Dev dependencies (Phase 0 install)",
            kv_table(
                header=["Package", "Why", "Phase"],
                col_widths=[140, 318, 60],
                rows=[
                    ("mypy", "Strict static typing; gate from Phase 2", "0+"),
                    ("ruff", "Lint + format; gate from Phase 0", "0+"),
                    ("pytest", "Test runner", "0+"),
                    ("pytest-asyncio", "async test fixtures", "2+"),
                    ("pytest-cov", "Coverage report", "2+"),
                    ("import-linter", "Production never imports paper-mocks", "2+"),
                    ("pre-commit", "Local-side hooks (mirror CI)", "0+"),
                    ("anthropic", "Anthropic SDK for the agent ensemble", "3+"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Runtime dependencies (added later, per-phase)",
            kv_table(
                header=["Package", "Why", "Phase"],
                col_widths=[140, 318, 60],
                rows=[
                    ("eth-account", "Generate wallets, sign EIP-712", "1"),
                    ("web3", "Polygon RPC interactions", "1+"),
                    ("py-clob-client", "Polymarket signing + orders", "1+"),
                    ("websockets", "Native WS client for Binance/Coinbase/Polymarket", "2+"),
                    ("polars", "Fast Parquet IO", "2+"),
                    ("pyarrow", "Parquet engine for Polars", "2+"),
                    ("nautilus-trader", "Backtest engine + Polymarket adapter", "3"),
                    ("scikit-learn", "Logistic + GBM for feature importance", "3+ / study D"),
                    ("shap", "Local feature explanations", "study E"),
                    ("duckdb", "Ad-hoc SQL on Parquet", "study G"),
                    ("streamlit", "Research dashboard", "study G"),
                    ("plotly", "Charts in dashboard + reports", "study G"),
                    ("python-telegram-bot", "(or just requests) — Telegram alerts", "0+"),
                    ("prometheus-client", "Bot metrics endpoint", "5+"),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Claude Code skills =====
    story.append(
        section_heading(
            "Claude Code skills", color=PURPLE, sub="Drop into ~/.claude/skills/ before Phase 0"
        )
    )
    story.append(
        Paragraph(
            "Claude skills are markdown files with optional metadata. Drop them into "
            "<font face='Courier' size='8.5'>~/.claude/skills/</font> and Claude Code reads them on session start. "
            "Pull these BEFORE Phase 0 — they encode hard-won Polymarket primitives we'd otherwise have to learn.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Polymarket/agent-skills (REQUIRED)",
            kv_table(
                header=["", ""],
                col_widths=[110, 408],
                rows=[
                    ("<b>Source</b>", "github.com/Polymarket/agent-skills"),
                    (
                        "<b>Install</b>",
                        "<font face='Courier' size='8'>git clone https://github.com/Polymarket/agent-skills.git ~/.claude/skills/agent-skills</font>",
                    ),
                    (
                        "<b>Contains</b>",
                        "authentication.md (L1+L2), trading.md, websocket.md, gasless.md, markets.md, neg-risk.md, token-ops.md, bridging.md",
                    ),
                    (
                        "<b>Verify</b>",
                        "<font face='Courier' size='8'>test -f ~/.claude/skills/agent-skills/gasless.md</font>",
                    ),
                    ("<b>Phase</b>", "0 (clone), 1+ (used heavily)"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Custom skill: poly-bot-skills (write yourself in Phase 0)",
            kv_table(
                header=["", ""],
                col_widths=[110, 408],
                rows=[
                    (
                        "<b>What</b>",
                        "Project-specific skills covering OUR locked decisions (gasless-only, $5 flat sizing, deterministic Tier-3, etc.) so future Claude sessions don't re-litigate.",
                    ),
                    (
                        "<b>Where</b>",
                        "<font face='Courier' size='8'>~/.claude/skills/poly-bot/</font>",
                    ),
                    (
                        "<b>Files</b>",
                        "decisions.md (mirror of memory file), kill-switches.md, gasless-flow.md, sizing.md, telegram-alerts.md",
                    ),
                    ("<b>Phase</b>", "0 (write), all (used)"),
                    (
                        "<b>Discipline</b>",
                        "Update on every locked-decision change; commit alongside code.",
                    ),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Built-in skills =====
    story.append(
        section_heading(
            "Built-in skills + slash commands", color=PURPLE, sub="What you already have on tap"
        )
    )
    story.append(
        Paragraph(
            "These are part of the Claude Code runtime. Nothing to install — just know which "
            "ones matter for this project and when to use them.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Slash commands you'll use",
            kv_table(
                header=["Command", "Use", "Phase"],
                col_widths=[150, 308, 60],
                rows=[
                    ("/init", "Seed the project's CLAUDE.md once layout is on disk", "0"),
                    (
                        "/security-review",
                        "Run before every phase that touches signing or fund movement",
                        "1, 5, 6",
                    ),
                    (
                        "/loop",
                        "Periodic check (e.g. monitor backtest progress) — sparing use",
                        "3-4",
                    ),
                    ("/schedule", "Recurring agent tasks — only after Phase 6 lives", "7+"),
                    ("/clear", "After drift detected mid-conversation", "any"),
                    ("/config", "Quick settings adjustments (theme, model)", "any"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Built-in skills relevant here",
            kv_table(
                header=["Skill", "Use", "Phase"],
                col_widths=[180, 278, 60],
                rows=[
                    (
                        "update-config",
                        "Add hooks to settings.json (e.g. block git push without lint)",
                        "0+",
                    ),
                    ("fewer-permission-prompts", "Auto-allow common read tool calls", "0+"),
                    ("simplify", "Code review pass on changed files before commit", "all"),
                    ("anthropic-skills:pdf", "Build dashboard exports / report PDFs", "research"),
                    ("anthropic-skills:docx", "Generate human-readable postmortems", "research"),
                    ("claude-api", "Building the 3-agent ensemble against Anthropic SDK", "3+"),
                    ("design:design-handoff", "Spec the Streamlit dashboard tabs", "study G"),
                    ("init", "Create the initial CLAUDE.md (=/init)", "0"),
                    ("review", "PR review on ensemble changes", "3+"),
                    ("security-review", "Branch-level security check before merge", "1, 5, 6"),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== MCP servers =====
    story.append(
        section_heading(
            "MCP servers",
            color=BLUE,
            sub="Obsidian (required) + Polymarket research MCPs (optional)",
        )
    )
    story.append(
        Paragraph(
            "MCP servers expose tools to Claude. We need exactly one (Obsidian) for the project. "
            "The Polymarket MCPs are research aids — read-only chat exploration of markets — and "
            "are <b>NEVER</b> used for live order flow.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Obsidian — REQUIRED for memory vault",
            kv_table(
                header=["", ""],
                col_widths=[120, 398],
                rows=[
                    ("<b>Source</b>", "github.com/iansinnott/obsidian-claude-code-mcp"),
                    (
                        "<b>Install</b>",
                        "Within Obsidian: Community Plugins → Browse → search 'Claude Code MCP' → Install. Then Settings → Claude Code MCP → Enable + copy URL.",
                    ),
                    (
                        "<b>Wire to Claude Code</b>",
                        "Add to ~/.claude/settings.json under mcpServers. Exact JSON in §14 bootstrap.",
                    ),
                    (
                        "<b>Vault location</b>",
                        "/Users/hamad/Desktop/PolyMarket-5m/state/  (laptop-only, locked decision #18)",
                    ),
                    ("<b>Phase</b>", "0+"),
                    (
                        "<b>Verify</b>",
                        "In Claude Code: 'Read state/runbooks/README.md' returns content (not tool error).",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Polymarket research MCPs (OPTIONAL — chat exploration only)",
            kv_table(
                header=["MCP", "What it gives Claude in chat", "Install"],
                col_widths=[170, 230, 118],
                rows=[
                    (
                        "caiovicentino/polymarket-mcp-server",
                        "45 tools: market data, real-time WS, exposure caps. Read-only mode supported.",
                        "stdio: clone + npm i + add to ~/.claude/settings.json",
                    ),
                    (
                        "artvandelay/polymarket-agents",
                        "10 research tools: odds, orderbook, spread, history.",
                        "stdio: pip install + config",
                    ),
                    (
                        "berlinbra/polymarket-mcp",
                        "Lighter read-only market data MCP.",
                        "stdio: clone + config",
                    ),
                    (
                        "agent-next/polymarket-paper-trader",
                        "Paper-trading sim accessible via chat. Useful Phase 3-4.",
                        "stdio: clone + config",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "<font color='#E5484D'><b>RULE:</b></font> none of these MCPs ever issue real orders. "
            "Live trading is exclusively from the bot binary on the Dublin VPS. Research MCPs are "
            "for ad-hoc chat exploration during dev only (e.g. 'what's the current spread on the active 5m market?').",
            BODY_SM,
        )
    )
    story.append(PageBreak())

    # ===== Reference repos =====
    story.append(
        section_heading(
            "Reference repos to clone",
            color=TEAL,
            sub="Mining-only — never imported as runtime deps",
        )
    )
    story.append(
        Paragraph(
            "All repos go under <font face='Courier' size='8.5'>references/</font> in the project, "
            "which is <i>gitignored</i>. We read them, learn patterns, sometimes copy specific functions "
            "(with attribution), but never depend on them as runtime imports.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Polymarket — official",
            kv_table(
                header=["Repo", "Why we keep it local"],
                col_widths=[180, 338],
                rows=[
                    (
                        "Polymarket/py-clob-client",
                        "Auth flow + signing primitives — we DO use this as a runtime dep, but mining the README + source for patterns is invaluable.",
                    ),
                    (
                        "Polymarket/rs-clob-client",
                        "Rust client, fastest. Reference for performance-critical patterns. Not used as dep.",
                    ),
                    (
                        "Polymarket/agents",
                        "TS autonomous-agent framework. Mine for design patterns.",
                    ),
                    ("Polymarket/poly-market-maker", "Reference market-maker keeper bot."),
                    (
                        "Polymarket/agent-skills",
                        "Already cloned into ~/.claude/skills/ — leave that copy alone; clone again into references/ for code-level grep if needed.",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Reference 5m bot implementations",
            kv_table(
                header=["Repo", "Why"],
                col_widths=[270, 248],
                rows=[
                    (
                        "Archetapp gist 7680adabc48f812a561ca79d73cbac69",
                        "Best in-the-wild 5m bot. Window/timing logic gold.",
                    ),
                    (
                        "aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
                        "Production-grade 15m bot — adapt sizing/risk patterns.",
                    ),
                    (
                        "ThinkEnigmatic/polymarket-bot-arena",
                        "Multi-strategy arena pattern — Phase 7.",
                    ),
                    (
                        "evan-kolberg/prediction-market-backtesting",
                        "NautilusTrader Polymarket adapter — fork in Phase 3.",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        CodeBlock(
            "clone all into references/  (idempotent — re-runnable)",
            [
                "mkdir -p references && cd references",
                "for repo in \\",
                "  Polymarket/py-clob-client Polymarket/rs-clob-client \\",
                "  Polymarket/agents Polymarket/poly-market-maker \\",
                "  evan-kolberg/prediction-market-backtesting \\",
                "  aulekator/Polymarket-BTC-15-Minute-Trading-Bot \\",
                "  ThinkEnigmatic/polymarket-bot-arena ; do",
                '    [ -d "$(basename $repo)" ] || git clone --depth 1 https://github.com/$repo.git',
                "done",
                "[ -d archetapp-5m-bot ] || git clone --depth 1 \\",
                "    https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69 archetapp-5m-bot",
                "cd ..",
            ],
        )
    )
    story.append(PageBreak())

    # ===== Reference docs =====
    story.append(
        section_heading(
            "Reference docs to read / bookmark",
            color=TEAL,
            sub="Verified canonical URLs — bookmark to the project profile",
        )
    )
    story.append(
        section_block(
            "Polymarket",
            kv_table(
                rows=[
                    ("Developer Docs", "docs.polymarket.com/developers/"),
                    ("Auth flow (L1 + L2)", "docs.polymarket.com/developers/CLOB/authentication"),
                    ("WebSocket subscriptions", "docs.polymarket.com/developers/CLOB/websocket"),
                    ("Maker Rebates Program", "help.polymarket.com/en/articles/13364471"),
                    ("ToS (verify UAE permitted)", "polymarket.com/tos"),
                ],
                col_widths=[200, 318],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "On-chain primitives (Polygon)",
            kv_table(
                rows=[
                    (
                        "Chainlink BTC/USD on Polygon",
                        "data.chain.link/feeds/polygon/mainnet/btc-usd",
                    ),
                    ("Polygon block explorer", "polygonscan.com"),
                    ("USDC.e → native USDC migration tracking", "theblock.co/post/388670"),
                ],
                col_widths=[230, 288],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Trading engine + ML libs",
            kv_table(
                rows=[
                    (
                        "NautilusTrader Polymarket integration",
                        "nautilustrader.io/docs/latest/integrations/polymarket/",
                    ),
                    ("scikit-learn user guide", "scikit-learn.org/stable/user_guide.html"),
                    ("Polars docs", "pola.rs"),
                    ("DuckDB docs", "duckdb.org/docs/"),
                    ("Streamlit docs", "docs.streamlit.io"),
                ],
                col_widths=[230, 288],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Anthropic",
            kv_table(
                rows=[
                    ("Anthropic API docs", "docs.anthropic.com"),
                    (
                        "Prompt caching guide",
                        "docs.anthropic.com/en/docs/build-with-claude/prompt-caching",
                    ),
                    ("Models & pricing", "anthropic.com/pricing"),
                    ("Rate-limit tiers", "docs.anthropic.com/en/api/rate-limits"),
                ],
                col_widths=[230, 288],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Polymarket-specific =====
    story.append(
        section_heading("Polymarket-specific", color=AMBER, sub="Auth, gasless, contract addresses")
    )
    story.append(
        section_block(
            "Endpoints (verify before coding)",
            kv_table(
                header=["Use", "URL / address"],
                col_widths=[170, 348],
                rows=[
                    ("REST API base", "https://clob.polymarket.com"),
                    ("WebSocket — markets", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
                    (
                        "WebSocket — user events",
                        "wss://ws-subscriptions-clob.polymarket.com/ws/user",
                    ),
                    ("Gamma API (markets list)", "https://gamma-api.polymarket.com"),
                    ("Polygon chain ID", "137"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Auth flow (memorize)",
            kv_table(
                header=["Step", "What"],
                col_widths=[80, 438],
                rows=[
                    (
                        "L1",
                        "EIP-712 signature with the Signer wallet's private key — produces apiKey + secret + passphrase. One-time.",
                    ),
                    (
                        "L2",
                        "HMAC-SHA256 of (timestamp + method + path + body) using the L2 secret. Sent on every request via 5 POLY_* headers.",
                    ),
                    (
                        "Headers",
                        "POLY_ADDRESS, POLY_SIGNATURE, POLY_TIMESTAMP, POLY_NONCE, POLY_API_KEY",
                    ),
                    ("Library", "py-clob-client wraps both L1 and L2 — never roll your own."),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Gasless relayer (locked decision #17)",
            kv_table(
                header=["Field", "Value"],
                col_widths=[140, 378],
                rows=[
                    ("Why", "Avoid public Polygon mempool exposure (MEV / sandwiching)."),
                    ("Reference", "~/.claude/skills/agent-skills/gasless.md (cloned in §06)."),
                    (
                        "Coverage",
                        "Order placement is gasless. USDC approval to the exchange contract is NOT (one-time on-chain in Phase 1).",
                    ),
                    ("Phase", "1.0 design doc, 1.5 first test order, 6 live."),
                ],
            ),
        )
    )
    story.append(PageBreak())

    # ===== Bonereaper study extras =====
    story.append(
        section_heading(
            "Bonereaper study extras",
            color=PURPLE,
            sub="Adds nothing the main bot doesn't already need + a few ML libs",
        )
    )
    story.append(
        Paragraph(
            "The behavioral study (BONEREAPER_STUDY.pdf) reuses everything the main bot uses: "
            "Polygon RPC, captured Phase 2 archives, Anthropic API. Three extras specific to the study:",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Extras",
            kv_table(
                header=["Item", "Why", "Phase (study)"],
                col_widths=[170, 280, 68],
                rows=[
                    (
                        "Bonereaper wallet address",
                        "0xeebde7a0e019a63e6b476eb425505b7b3e6eba30 — verify on PolygonScan that account is active.",
                        "A",
                    ),
                    (
                        "scikit-learn",
                        "Logistic regression + gradient-boosted trees for feature importance.",
                        "D, E",
                    ),
                    ("SHAP", "Local feature explanations on the dashboard.", "E, G"),
                    ("DuckDB", "Ad-hoc SQL on labelled.parquet — drives the dashboard.", "G"),
                    ("Streamlit + Plotly + Polars", "Research dashboard stack.", "G"),
                    (
                        "Pre-flight audit script",
                        "scripts/research/quick_audit.py — runs against Alchemy free tier.",
                        "A",
                    ),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "<b>Hard abort gate (Phase A):</b> if bonereaper's actual on-chain 30-day rolling win-rate "
            "is below 60% OR observable trades < 500 OR volume drop > 40% in last 30 days — "
            "abort the entire study. Don't anchor weights to a degrading source. "
            "<i>This audit happens before any other study work.</i>",
            BODY,
        )
    )
    story.append(PageBreak())

    # ===== Deferred to Phase 5 =====
    story.append(
        section_heading(
            "Deferred to Phase 5 (DON'T do now)",
            color=GRAY_500,
            sub="VPS, observability, backups — not part of bootstrap",
        )
    )
    story.append(
        Paragraph(
            "Mentioned here only so you don't try to set them up early. Each is provisioned in "
            "Phase 5 with explicit gates.",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Phase 5+ services",
            kv_table(
                header=["Service", "When", "Cost"],
                col_widths=[170, 270, 78],
                rows=[
                    ("AWS Lightsail eu-west-1 Dublin", "Phase 5 — sub-5ms VPS", "~$5/mo"),
                    ("Grafana Cloud free tier", "Phase 5 — warn/info dashboards", "$0"),
                    ("Backblaze B2", "Phase 5 — trades.db offsite backup", "~$0.005/GB/mo"),
                    (
                        "Hardware wallet (Ledger Nano S)",
                        "Phase 7 step 7.1 ($3k bankroll)",
                        "~$80 one-time",
                    ),
                    ("PagerDuty / SMS escalation", "Phase 7+ at $1k+ bankroll", "depends on tier"),
                    ("Frankfurt warm-standby VPS", "Phase 8 — DR", "~$5/mo"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>Why deferred:</b> none of these are needed for laptop-only Phases 0-4. Provisioning "
            "early adds cost, attack surface, and lifecycle headache before there's anything to host.",
            BODY_SM,
        )
    )
    story.append(PageBreak())

    # ===== Bootstrap script =====
    story.append(
        section_heading(
            "Bootstrap script", color=GREEN, sub="One bash to install most of the local stack"
        )
    )
    story.append(
        Paragraph(
            "Write to <font face='Courier' size='8.5'>scripts/bootstrap.sh</font>, "
            "<font face='Courier' size='8.5'>chmod +x</font>, run from project root. "
            "Idempotent — re-runs are safe. Does not create any web accounts (those need browser); "
            "does not load Anthropic credits (you do that on console.anthropic.com).",
            BODY,
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        CodeBlock(
            "scripts/bootstrap.sh — full content (1/2)",
            [
                "#!/usr/bin/env bash",
                "set -euo pipefail",
                "",
                'echo "== Polymarket BTC 5-Min Bot — bootstrap =="',
                "",
                "# 1. brew + brew packages",
                'command -v brew >/dev/null || { echo "Install Homebrew: https://brew.sh"; exit 1; }',
                "for p in git gh node direnv age jq; do",
                "  brew list $p >/dev/null 2>&1 || brew install $p",
                "done",
                "command -v wscat >/dev/null || npm install -g wscat",
                "",
                "# 2. uv (Python pkg manager)",
                "command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh",
                "",
                "# 3. project skeleton",
                "uv init --python 3.11 --package 2>/dev/null || true",
                "uv add --dev mypy ruff pytest pytest-asyncio pytest-cov import-linter pre-commit anthropic",
                "mkdir -p src/polymarket_bot tests design references state config",
                "mkdir -p runbooks/incidents runbooks/gates runbooks/postmortems runbooks/scripts",
                "mkdir -p state/runbooks state/postmortems state/research/bonereaper",
                "touch src/polymarket_bot/__init__.py tests/__init__.py",
            ],
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        CodeBlock(
            "scripts/bootstrap.sh — full content (2/2)",
            [
                "# 4. drop Polymarket/agent-skills into ~/.claude/skills/",
                "mkdir -p ~/.claude/skills",
                "[ -d ~/.claude/skills/agent-skills ] || \\",
                "  git clone https://github.com/Polymarket/agent-skills.git ~/.claude/skills/agent-skills",
                "",
                "# 5. clone reference repos",
                "mkdir -p references && pushd references >/dev/null",
                "for repo in Polymarket/py-clob-client Polymarket/rs-clob-client \\",
                "            Polymarket/agents Polymarket/poly-market-maker \\",
                "            evan-kolberg/prediction-market-backtesting \\",
                "            aulekator/Polymarket-BTC-15-Minute-Trading-Bot \\",
                "            ThinkEnigmatic/polymarket-bot-arena ; do",
                '  [ -d "$(basename $repo)" ] || git clone --depth 1 https://github.com/$repo.git',
                "done",
                "[ -d archetapp-5m-bot ] || git clone --depth 1 \\",
                "  https://gist.github.com/Archetapp/7680adabc48f812a561ca79d73cbac69 archetapp-5m-bot",
                "popd >/dev/null",
                "",
                "# 6. .gitignore protects secrets and big files",
                "cat > .gitignore <<'EOF'",
                ".envrc",
                "*.age",
                "references/",
                "state/",
                "runbooks/gate-evidence/",
                "ticks/",
                "trades.db",
                "*.db-shm",
                "*.db-wal",
                "EOF",
                "",
                "# 7. .envrc.example (committed) and reminder to fill .envrc",
                "cat > .envrc.example <<'EOF'",
                'export ANTHROPIC_API_KEY="sk-ant-..."',
                'export TELEGRAM_BOT_TOKEN="..."',
                'export TELEGRAM_CHAT_ID="..."',
                'export POLYGON_RPC_URL=""',
                'export POLY_PRIVATE_KEY=""',
                'export POLY_API_KEY=""',
                'export POLY_API_SECRET=""',
                'export POLY_API_PASSPHRASE=""',
                "EOF",
                "",
                "# 8. Done",
                'echo ""',
                'echo "== bootstrap complete =="',
                'echo "NEXT: cp .envrc.example .envrc; fill in real values; direnv allow"',
                'echo "THEN: review § 15 verification checklist before Phase 0"',
            ],
        )
    )
    story.append(PageBreak())

    # ===== Verification checklist =====
    story.append(
        section_heading(
            "Verification checklist", color=GREEN, sub='Run before declaring "ready for Phase 0"'
        )
    )
    story.append(
        Paragraph(
            "Tick every box. If anything fails, fix the underlying issue and re-tick. Don't start "
            "Phase 0 with red checks.",
            BODY,
        )
    )
    story.append(Spacer(1, 8))

    verify_groups = [
        (
            "System tools",
            AMBER,
            [
                "command -v brew git gh uv node direnv age jq wscat   →  all OK",
                "python3 --version   →  3.11 or higher",
                "node --version   →  v20 or higher",
                "uv run python -c 'import sys; assert sys.version_info >= (3,11)'   →  exits 0",
            ],
        ),
        (
            "Web accounts ready",
            BLUE,
            [
                "GitHub: gh auth status   →  authenticated",
                "Anthropic: ANTHROPIC_API_KEY exported and starts with sk-ant-",
                "Telegram: smoke message arrives on phone via curl",
                "Alchemy: POLYGON_RPC_URL set and starts with wss://",
            ],
        ),
        (
            "Project skeleton on disk",
            GREEN,
            [
                "ls pyproject.toml uv.lock   →  both exist",
                "ls -la state/ references/   →  both exist (gitignored)",
                "test -f ~/.claude/skills/agent-skills/gasless.md   →  exists",
                "test -d references/py-clob-client   →  exists",
                "make verify   →  exits 0 (mypy + ruff + pytest all green on empty src)",
            ],
        ),
        (
            "Documents read at least once",
            PURPLE,
            [
                "Read MASTERPLAN.md end-to-end (rationale).",
                "Read RUNBOOK.md sections A, B, D (Phase 0 has all the gates).",
                "Read BUILD_SPEC.pdf (skim — 24 pages).",
                "Skim BONEREAPER_STUDY.pdf — know the abort gate (Phase A win-rate ≥ 60%).",
                "memory/project_decisions.md — read all 18 locked decisions.",
            ],
        ),
        (
            "Vault + skills wired",
            TEAL,
            [
                "Obsidian vault opens at /Users/hamad/Desktop/PolyMarket-5m/state/",
                "obsidian-claude-code-mcp plugin enabled in Obsidian.",
                "Claude Code can read state/runbooks/README.md (test in a session).",
            ],
        ),
    ]
    for group, color, items in verify_groups:
        story.append(Paragraph(f"<b>{group}</b>", H3))
        for it in items:
            row = Table(
                [
                    [
                        Table(
                            [[""]],
                            colWidths=[6],
                            rowHeights=[14],
                            style=TableStyle([("BACKGROUND", (0, 0), (-1, -1), color)]),
                        ),
                        Paragraph(it, BODY_SM),
                        Paragraph(
                            "☐", ParagraphStyle("cb", parent=BODY, fontSize=11, textColor=color)
                        ),
                    ],
                ],
                colWidths=[6, 482, 22],
                hAlign="LEFT",
            )
            row.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (0, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                        ("LEFTPADDING", (1, 0), (1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(row)
        story.append(Spacer(1, 4))
    story.append(PageBreak())

    # ===== Cost summary =====
    story.append(section_heading("Cost summary", color=BLUE, sub="What costs money now / later"))
    story.append(
        section_block(
            "Today (bootstrap)",
            kv_table(
                header=["Item", "Cost"],
                col_widths=[300, 218],
                rows=[
                    ("Anthropic API credits (already loaded)", "$50 (decision #14)"),
                    ("Brew packages, GitHub, Telegram, Alchemy free tier", "$0"),
                    ("Reference repos (clones)", "$0"),
                    ("Obsidian + plugin", "$0"),
                    ("<b>Total bootstrap cost</b>", "<b>$0 incremental</b>"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 6))
    story.append(
        section_block(
            "Per-phase forward look",
            kv_table(
                header=["Phase", "Cost", "Driver"],
                col_widths=[160, 150, 208],
                rows=[
                    ("Phase 0 — Foundations", "$0", "—"),
                    ("Phase 1 — Wallet & Auth", "~$5", "Polygon gas + small USDC test"),
                    ("Phase 2 — Data Plane", "~$5", "Alchemy free tier covers most"),
                    ("Phase 3 — Backtest A/B", "$15-50", "Anthropic API (cache-disciplined)"),
                    ("Top up before Phase 4", "+$100 (to ~$150)", "Anthropic 14d × 24/7 paper"),
                    ("Phase 5 — VPS", "$5/mo recurring", "Lightsail Dublin"),
                    ("Top up before Phase 6", "+$150 (to ~$300)", "Anthropic 14d × 24/7 live"),
                    ("Phase 6 — Live", "$1,000 capital", "Working capital — at risk, not consumed"),
                    ("Phase 7 — Scale ($3k)", "+$80 one-time", "Hardware wallet (Ledger)"),
                ],
            ),
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            "<b>Sustained ops</b> (post Phase 6): ~$200/month — primarily Anthropic API at "
            "empirical $0.19-0.58/hour (decision #14). Cache discipline can cut this in half.",
            BODY,
        )
    )
    story.append(Spacer(1, 8))
    story.append(
        StatCards(
            [
                ("$0", "Bootstrap cost today", GREEN),
                ("~$170", "Setup spend through Phase 5", AMBER),
                ("$1,000", "Working capital at Phase 6", BLUE),
                ("$200/mo", "Sustained OPEX", PURPLE),
            ]
        )
    )
    story.append(Spacer(1, 14))
    story.append(HBar(color=GRAY_300, thickness=0.6))
    story.append(Spacer(1, 4))
    story.append(
        Paragraph(
            "<font color='#64748B'><i>When this checklist is fully ticked, you are ready for "
            "RUNBOOK.md Phase 0. Open the runbook, paste task 0.1 verbatim into Claude Code as "
            "your first prompt, and start.</i></font>",
            BODY_SM,
        )
    )

    doc.build(story)
    return out


if __name__ == "__main__":
    out = build()
    print(f"Built: {out}")
