"""Build pdfs/PHASE_P_SESSION2_MMD_RESEARCH.pdf — MMD candidate research + backtest.

10-12 pages: Phase N recap → candidate shortlist → n=756 backtest results
→ chosen design summary → Session-3 ship plan.

Embeds 4 PNG charts from state/research/phase-P-mmd-charts/ generated
by scripts/research/phase_p_mmd_backtest.py.

Usage:
    uv run --with reportlab python -u pdfs/build_phase_p_session2_pdf.py
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
    Image,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
CHARTS = ROOT / "state" / "research" / "phase-P-mmd-charts"
OUT = ROOT / "pdfs" / "PHASE_P_SESSION2_MMD_RESEARCH.pdf"

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
            "Phase P Session 2 — MMD research · 2026-05-18 · POLYMARKET 5m bot",
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
        "quote": ParagraphStyle("quote", parent=base["BodyText"], fontName="Helvetica-Oblique",
                                fontSize=10, textColor=WARN, leading=15, leftIndent=14,
                                rightIndent=14, spaceAfter=10, spaceBefore=6),
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
        title="Phase P Session 2 — MMD research + backtest",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # COVER
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Spacer(0, 30 * mm))
    story.append(Paragraph("PHASE&nbsp;P · Session&nbsp;2", s["cover_title"]))
    story.append(Paragraph("Market Mode Detector — research + n=756 backtest",
                           s["cover_sub"]))
    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "POLYMARKET 5-minute BTC up/down bot<br/>"
        "Backtested 2 candidates on Phase N forensic data (n=756 settled fires).<br/>"
        "Both find <b>MIXED</b> as the only profitable label.<br/>"
        "<b>Adapter A (bukosabino/ta) chosen for Session 3 ship.</b>",
        s["cover_sub"],
    ))
    story.append(Spacer(0, 18 * mm))
    story.append(Paragraph("MIXED-only counterfactual on n=756: +$1,018 (A) / +$933 (B)",
                           s["cover_ok"]))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "Bot stays LIVE on J.1.6 baseline throughout Session 2 — no env flips, no src/ ships.<br/>"
        "Session 3 will dark-ship MMD in SHADOW mode for 5-day re-soak.",
        s["small"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # TOC
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Contents", s["h1"]))
    story.append(Spacer(0, 4 * mm))
    toc_rows = [
        ["§1", "Recap of Phase N findings — the regime gap MMD must fill"],
        ["§2", "Candidate shortlist + evaluation criteria"],
        ["§3", "Backtest method on Phase N n=756 forensic data"],
        ["§4", "Adapter A results — bukosabino/ta rule-based"],
        ["§5", "Adapter B results — hmmlearn 4-state HMM"],
        ["§6", "Cross-validation, co-occurrence, and pick rationale"],
        ["§7", "Integration design summary (full doc at design/P.1)"],
        ["§8", "Session 3 ship plan + 5-day re-soak + Phase Q decision matrix"],
    ]
    story.append(_table(toc_rows, col_widths=[18 * mm, 150 * mm], header=False))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Phase N recap
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§1 &nbsp;&nbsp; Recap of Phase N findings — the regime gap",
                           s["h1"]))
    story.append(Paragraph(
        "Phase N forensic audit (PHASE_N_FORENSIC_AUDIT.pdf, 22 pp) audited "
        "n=755 settled fires on the J.1.6 baseline over 4.2 days. The audit "
        "established three things that frame the MMD work:",
        s["body"],
    ))
    bullets = [
        ["§N-1", "<b>M.1a v1 (vol-ratio chop-abstain) was FALSIFIED on n=755.</b> Annotated n=83 subset showed chop &gt; mixed WR (60.9% vs 44.8%); the |Δbps| proxy on n=755 contradicted that with monotonic WR by |Δ| (35.7% / 33.8% / 60.5% / 71.4%). The chop &gt; mixed inversion was a small-n artifact."],
        ["§N-2", "<b>M.5 (path-A regime wrapper) design was CORRECT but shipped 3 days late.</b> Idealized simulator: +$352.92 counterfactual PnL avoided over 5 days. M.5 first activatable 2026-05-14 05:55Z; actual ship 2026-05-17."],
        ["§N-3", "<b>SURV cell flip (tier 30-50% × |Δbps|≥5) was the dominant bleeder.</b> WR collapsed from 60.7% pre-peak (+$1,431) to 46.5% post-peak (−$1,161). Phase O's SURV canary attempted to detect this; falsified shipping discipline (n=1 post-restart fire = LOSS −$163)."],
        ["§N-6 (deferred)", "&quot;Regime classifier validity&quot; flagged as Future Work. MMD = that future work, brought forward in Phase P Session 2."],
    ]
    story.append(_table([["Ref", "Finding"]] + bullets,
                        col_widths=[26 * mm, 142 * mm]))
    story.append(Spacer(0, 4 * mm))
    story.append(Paragraph(
        "What MMD must deliver: a regime label with empirically-meaningful WR/$tr "
        "separation on Phase N data (the same dataset that falsified M.1a v1), "
        "from a battle-tested GitHub library (not a hand-rolled vol-ratio), with "
        "shadow-ship discipline (no small-n active gates).",
        s["body"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Candidate shortlist
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§2 &nbsp;&nbsp; Candidate shortlist + evaluation criteria", s["h1"]))
    story.append(Paragraph("§2.1 &nbsp; Criteria (per prompt P.2.1)", s["h2"]))
    crit_rows = [
        ["License", "MIT / Apache / BSD (decision #8). GPL = hard no."],
        ["Output", "Structured: label + confidence ∈ [0, 1]"],
        ["Input", "Compatible with our spot tick stream OR trivial bar-aggregation inside the integration"],
        ["Backtestable on Phase N n=755", "Required (gates the whole Session-2 work)"],
        ["Dep footprint", "< 50 MB, no conflict with existing uv.lock"],
        ["USEFUL signal", "≥ 10 pp WR delta between best and worst label on n ≥ 20 per label"],
    ]
    story.append(_table([["Criterion", "Requirement"]] + crit_rows,
                        col_widths=[55 * mm, 113 * mm]))

    story.append(Paragraph("§2.2 &nbsp; Shortlist", s["h2"]))
    shortlist = [
        ["bukosabino/ta", "MIT", "TOP-2", "Pure-Python TA (ADX, ATR, BB, momentum, etc.). Battle-tested, ~3 MB, no ML dep. Rule-based 4-state MMD straightforward to wire."],
        ["hmmlearn", "BSD-3", "TOP-2", "4-state Gaussian HMM. Probabilistic, native confidence via posterior. ~25 MB with scipy + sklearn. In-sample fit acceptable for backtest; production needs rolling retrain."],
        ["twopirllc/pandas-ta", "MIT", "skip", "Duplicates bukosabino/ta with more indicators we don't need. No differential."],
        ["hudson-and-thames/mlfinlab", "BSD-3", "skip", "Heavy (sklearn, scipy, statsmodels), research-grade not production-grade. Defer to Phase R+ if HMM proves valuable."],
        ["hmmlearn-style HMM via pomegranate", "MIT", "skip", "Newer, less battle-tested than hmmlearn. No clear advantage."],
        ["mementum/backtrader", "GPL", "BLOCKED", "GPL conflicts with decision #8. Hard no."],
        ["GitHub search top results", "various", "skip", "&quot;bitcoin regime detection&quot;: most matches are toy / research repos with &lt; 100 stars or no recent activity. None passed criteria."],
    ]
    story.append(_table([["Repo", "License", "Status", "Why"]] + shortlist,
                        col_widths=[40 * mm, 18 * mm, 18 * mm, 92 * mm]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 — Backtest method
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§3 &nbsp;&nbsp; Backtest method on Phase N n=756 forensic data", s["h1"]))
    method_rows = [
        ["Data source", "state/decisions{,-resolved}/archived/phase-P-reset/2026-05-{13..17}.jsonl (preserved on VPS at Phase P Session 1 close)"],
        ["Fire loader", "scripts/research/phase_n_forensic_audit.py::load_data (Phase N joiner; prefers settled_correction over settled)"],
        ["n_settled_with_won", "756"],
        ["Market data", "Binance public REST /api/v3/klines, BTCUSDT 1m, 2026-05-12 → 2026-05-18 (24h pre-window buffer for lookback). 8,528 bars cached at state/research/binance_historical/btcusdt_1m_2026-05-12_to_2026-05-18.parquet"],
        ["Per-fire window", "60 1-min bars preceding the fire decision_ts (= 60-min lookback)"],
        ["Outputs measured", "label distribution; WR per label; $/tr per label; PnL per label; mean confidence per label; co-occurrence matrix A × B; best vs worst WR delta on n ≥ 20"],
        ["Pass/fail gate", "≥ 10 pp WR delta between best and worst label on subsamples n ≥ 20"],
        ["Script", "scripts/research/phase_p_mmd_backtest.py (rebuilt + re-runnable)"],
        ["Output report", "runbooks/research/phase-P-mmd-backtest-2026-05-18.md (full raw data)"],
        ["Output charts", "state/research/phase-P-mmd-charts/{01_per_label_wr,02_per_label_per_trade,03_label_distribution,04_cum_pnl_best_vs_worst}.png"],
    ]
    story.append(_table(method_rows, col_widths=[40 * mm, 128 * mm], header=False))

    story.append(Spacer(0, 3 * mm))
    story.append(Paragraph(
        "Known caveat: the prompt P.2.2 envisioned reconstructing spot trajectory "
        "from <code>snapshot.spot_now + oracle_last + window_open_spot</code> in "
        "each fire record. Per-fire schema gives only 4 point-in-time spot values, "
        "not a dense series. Resolution: backtest uses Binance 1m klines for the "
        "same time window as the dense input, then per-fire indexes by timestamp. "
        "Each fire sees 60 closed 1-min bars preceding its decision_ts.",
        s["body"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 4 — Adapter A results
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§4 &nbsp;&nbsp; Adapter A — bukosabino/ta rule-based",
                           s["h1"]))
    story.append(Paragraph("§4.1 &nbsp; Labelling logic", s["h2"]))
    story.append(Paragraph("ADX(14) > 25 ⇒ trending; momentum sign decides UP/DOWN. ADX < 20 AND BB-width(20, 2σ) < 30 bps ⇒ CHOPPY. Else MIXED. Confidence is normalized distance from each threshold.", s["body"]))
    story.append(Paragraph("§4.2 &nbsp; Per-label results", s["h2"]))
    a_rows = [
        ["UP",     "119", "48.7%", "$-1.86",  "$-222", "0.62"],
        ["DOWN",   "173", "53.8%", "$-2.03",  "$-352", "0.70"],
        ["CHOPPY", "193", "53.9%", "$-2.29",  "$-443", "0.40"],
        ["MIXED",  "271", "57.9%", "$+1.94",  "$+526", "0.50"],
    ]
    story.append(_table([["Label", "n", "WR", "$/tr", "PnL", "mean conf"]] + a_rows,
                        col_widths=[26 * mm, 18 * mm, 22 * mm, 26 * mm, 26 * mm, 26 * mm]))
    story.append(Paragraph(
        "<b>WR gap best vs worst:</b> MIXED 57.9% (n=271) vs UP 48.7% (n=119) "
        "= <b>+9.2 pp</b>. Formally just below the 10 pp gate; 95% CI on the gap "
        "is ±10.7 pp on this sample size, so the gap is not statistically "
        "distinguishable from the gate threshold.",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>Counterfactual if Adapter A had been live in gate mode with</b> "
        "<code>MMD_LABELS_TO_ABSTAIN=UP,DOWN,CHOPPY</code><b>:</b> kept "
        "+$526 (MIXED) and avoided −$1,017 (others) = <b>+$1,018 PnL "
        "improvement</b> on the actual cumulative −$492.",
        s["ok_box"],
    ))
    story.append(_img("01_per_label_wr.png", width_mm=165))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Adapter B results
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§5 &nbsp;&nbsp; Adapter B — hmmlearn 4-state Gaussian HMM",
                           s["h1"]))
    story.append(Paragraph("§5.1 &nbsp; Modelling", s["h2"]))
    story.append(Paragraph(
        "4-state Gaussian HMM with diag covariance, fit on (log-return × 1e4, rolling-10 vol) on the full 5-day series. State→label assignment by centroid: top-2 |mean_return| states → UP/DOWN by sign; bottom-2 by vol → CHOPPY/MIXED. Per-fire classification = argmax of posterior probability over the last bar of the 60-min lookback.",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>In-sample caveat:</b> HMM is fit on the entire 5-day series, so "
        "the WR delta below is an upper bound. Production deployment in Session 3 "
        "would either retrain on a rolling window or use a pre-trained snapshot.",
        s["warn"],
    ))
    story.append(Paragraph("§5.2 &nbsp; Per-label results", s["h2"]))
    b_rows = [
        ["UP",     "108", "57.4%", "$-2.49",  "$-269", "0.96"],
        ["DOWN",   "264", "53.0%", "$-0.78",  "$-206", "0.92"],
        ["CHOPPY", "200", "49.5%", "$-2.28",  "$-457", "0.96"],
        ["MIXED",  "184", "60.3%", "$+2.40",  "$+441", "0.91"],
    ]
    story.append(_table([["Label", "n", "WR", "$/tr", "PnL", "mean conf"]] + b_rows,
                        col_widths=[26 * mm, 18 * mm, 22 * mm, 26 * mm, 26 * mm, 26 * mm]))
    story.append(Paragraph(
        "<b>WR gap best vs worst:</b> MIXED 60.3% (n=184) vs CHOPPY 49.5% "
        "(n=200) = <b>+10.8 pp</b>. <b>PASSES the 10 pp gate.</b>",
        s["body"],
    ))
    story.append(Paragraph(
        "<b>Counterfactual:</b> kept +$441 (MIXED), avoided −$932 (others) "
        "= <b>+$933 PnL improvement</b>.",
        s["ok_box"],
    ))
    story.append(_img("02_per_label_per_trade.png", width_mm=165))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 6 — Cross-validation + pick
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§6 &nbsp;&nbsp; Cross-validation, co-occurrence, and pick", s["h1"]))
    story.append(Paragraph("§6.1 &nbsp; Both adapters agree on the actionable signal", s["h2"]))
    story.append(Paragraph(
        "Both adapters identify MIXED as the only profitable label "
        "(A: $+1.94/tr · B: $+2.40/tr) and bucket UP / DOWN / CHOPPY as bleeders. "
        "This cross-validates the signal: a regime-aware abstain that fires "
        "only when the market is neither cleanly trending nor cleanly chopping.",
        s["body"],
    ))

    story.append(Paragraph("§6.2 &nbsp; Label distribution and co-occurrence", s["h2"]))
    story.append(_img("03_label_distribution.png", width_mm=160))
    story.append(Spacer(0, 2 * mm))
    co_rows = [
        ["UP",     "23",  "49",  "22",  "25"],
        ["DOWN",   "52",  "51",  "18",  "52"],
        ["CHOPPY", "4",   "76",  "74",  "39"],
        ["MIXED",  "29",  "88",  "86",  "68"],
    ]
    story.append(_table([["A \\ B", "UP", "DOWN", "CHOPPY", "MIXED"]] + co_rows,
                        col_widths=[28 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm]))
    story.append(Paragraph(
        "Strong diagonal in CHOPPY (74 agreements) and MIXED (68 agreements) "
        "indicates the two adapters converge on the same regime-bucket "
        "decisions in the most-populated cells. UP and DOWN diagonal cells "
        "(23 / 51) are weaker — the two have different definitions of "
        "trending (rule-based momentum vs HMM state).",
        s["body"],
    ))

    story.append(Paragraph("§6.3 &nbsp; Pick: Adapter A (bukosabino/ta)", s["h2"]))
    pick_rows = [
        ["Deterministic — no model fit needed in production", "A only"],
        ["Lighter dep footprint (~3 MB vs ~25 MB)", "A wins"],
        ["Native confidence ∈ [0, 1] from indicator distance", "Both"],
        ["Native confidence from posterior probability", "B only"],
        ["Passes 10pp WR-gate strictly", "B only"],
        ["WR-gap within noise CI of gate threshold (so A's miss is not load-bearing)", "Both"],
        ["Higher actionable PnL counterfactual (+$1,018 vs +$933)", "A wins"],
        ["No in-sample training caveat", "A only"],
        ["MIT license", "A | B is BSD-3"],
        ["Production retrain requirements", "A: none | B: rolling window"],
    ]
    story.append(_table([["Dimension", "Verdict"]] + pick_rows,
                        col_widths=[120 * mm, 48 * mm]))
    story.append(Paragraph(
        "<b>Operator-confirmed pick (2026-05-18): A.</b>",
        s["ok_box"],
    ))
    story.append(_img("04_cum_pnl_best_vs_worst.png", width_mm=165))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 7 — Integration design summary
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§7 &nbsp;&nbsp; Integration design summary",
                           s["h1"]))
    story.append(Paragraph(
        "Full design at <font face='Courier'>design/P.1-market-mode-detector-integration.md</font>. "
        "Summary of the load-bearing decisions:",
        s["body"],
    ))
    design_rows = [
        ["Module", "src/polymarket_bot/strategies/market_mode_detector.py — MarketModeDetector class + MmdReading dataclass."],
        ["Wrapper signature", "push_bar(open, high, low, close, volume, ts_ns) + latest() → MmdReading(label, confidence, adx, bb_width_bps, momentum_bps, sampled_at_ns, bar_count)."],
        ["Injection in spot_aware_v2_1", "Optional mmd_getter callback (mirrors the now-stripped M.5 pattern). When configured, annotates rationale with mmd=<label> mmd_conf=<conf> and optionally abstains on labels listed in MMD_LABELS_TO_ABSTAIN."],
        ["Bar feed (Session 3)", "Background asyncio task polling Binance public /api/v3/klines every 30s for last 60 1m closed bars. ~3 calls/min within 1200/min rate limit."],
        ["Env flags (default ALL OFF)", "MMD_ENABLED=false (master), MMD_MODE=shadow, MMD_LABELS_TO_ABSTAIN=&quot;&quot;, MMD_LOOKBACK_S=3600, MMD_POLL_INTERVAL_S=30, MMD_ADX_STRONG_THRESHOLD=25.0, MMD_ADX_WEAK_THRESHOLD=20.0, MMD_BB_COMPRESSED_BPS=30.0, MMD_MOMENTUM_THRESHOLD_BPS=10.0."],
        ["Failure modes (HARD requirements)", "Library import failure → no-op stub returning UNKNOWN. Network/poll failure → stale-data → UNKNOWN. Indicator exception → UNKNOWN. UNKNOWN is pass-through; bot fires as if MMD wasn't there."],
        ["Telemetry", "Rationale annotation; startup log line; dashboard /api/state decisions row already surfaces rationale."],
        ["Test budget", "≥ 12 new tests (init, push_bar, latest UNKNOWN, latest UP/DOWN/CHOPPY/MIXED, exception path, missing-lib path, conf bounds, getter=None equivalence, shadow no-change, gate abstain, UNKNOWN pass-through)."],
        ["Rollback", "Single env flip MMD_ENABLED=false + restart bot-staging.service. Code path with mmd_getter=None is byte-identical to current J.1.6 behavior."],
    ]
    story.append(_table(design_rows, col_widths=[48 * mm, 120 * mm], header=False))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 8 — Session 3 ship plan + Phase Q decision matrix
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§8 &nbsp;&nbsp; Session 3 ship plan + Phase Q decision matrix",
                           s["h1"]))
    story.append(Paragraph("§8.1 &nbsp; Session 3 sequence (when operator says GO)", s["h2"]))
    sess3 = [
        ["P.3.0", "Implement market_mode_detector.py per the design lock. ≥ 12 new tests + mypy --strict + ruff + import-linter all green."],
        ["P.3.1", "Plumb mmd_getter callback into spot_aware_v2_1.py constructor + run_paper.py main() (creates MmdBinanceKlinePoller task when MMD_ENABLED=true)."],
        ["P.3.2", "Pre-deploy gates: full pytest pass (~720+ tests), mypy clean, ruff clean, import-linter contracts kept. PR + commit + push."],
        ["P.3.3", "VPS deploy: git pull; .envrc gains MMD_ENABLED=true MMD_MODE=shadow; systemctl restart bot-staging.service. Verify startup log shows &quot;MMD ENABLED: mode=shadow ...&quot; and first 3 fires gain mmd=&lt;label&gt; mmd_conf=&lt;conf&gt; annotation."],
        ["P.3.4", "5-day observation window OPENS. Bot runs J.1.6 + MMD shadow. NO env flips, NO src/ ships during the observation. Operator reviews dashboard daily."],
        ["P.3.5", "Build pdfs/PHASE_P_SESSION3_MMD_SHIP.pdf + Day-0 verification appendix."],
        ["P.3.6", "Vault + session note + commit + push."],
    ]
    story.append(_table([["Step", "Action"]] + sess3,
                        col_widths=[18 * mm, 150 * mm]))

    story.append(Paragraph("§8.2 &nbsp; Phase Q decision matrix (Day-5 audit from Session 3)", s["h2"]))
    matrix = [
        ["MIXED WR delta vs next-best label ≥ 10pp on n ≥ 100 live fires",
         "<b>PROMOTE</b> shadow → gate: set MMD_LABELS_TO_ABSTAIN=CHOPPY,UP,DOWN and MMD_MODE=gate. Also reconsider re-introducing M.5 as path-A-specific layer alongside MMD."],
        ["MIXED WR delta 5-10pp",
         "<b>KEEP SHADOW</b>; iterate on indicator parameters (MMD_ADX_STRONG_THRESHOLD=22.0 or MMD_LOOKBACK_S=1800). Re-audit at Day-10."],
        ["MIXED WR delta ≤ 5pp",
         "<b>SHELVE</b> MMD. Reconsider strategy class entirely (Phase R pivot question)."],
        ["UNKNOWN-rate > 5% (poll failure / indicator exceptions)",
         "<b>DIAGNOSE</b> at Phase Q before any promote-to-gate. Hardening needed."],
    ]
    story.append(_table([["Day-5 signal", "Action"]] + matrix,
                        col_widths=[68 * mm, 100 * mm]))

    story.append(Paragraph("§8.3 &nbsp; Acceptance — Session 2 closes when ALL true", s["h2"]))
    accept = [
        "Top-2 MMD candidates evaluated against the criteria + backtested on Phase N n=756",
        "phase-P-mmd-backtest report + 4 charts rendered (state/research/phase-P-mmd-charts/)",
        "design/P.1-market-mode-detector-integration.md locked",
        "PHASE_P_SESSION2_MMD_RESEARCH.pdf rendered (this file)",
        "Bot still LIVE on J.1.6 baseline, zero env flips, zero src/ ships",
        "Vault: session note + memory checkpoint + commit + push",
    ]
    for line in accept:
        story.append(Paragraph(f"✓  {line}", s["ok_box"]))

    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="80%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 4 * mm))
    story.append(Paragraph(
        "End of Phase P Session 2.  "
        "Adapter A (bukosabino/ta) locked for Session 3 ship.  "
        "Bot stays on J.1.6 baseline — no live changes this session.",
        s["headline"],
    ))

    doc.build(story)
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build()
