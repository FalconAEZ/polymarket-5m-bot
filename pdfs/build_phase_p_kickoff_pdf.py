"""Build pdfs/PHASE_P_KICKOFF.pdf — hard revert to J.1.6 + MMD build.

Models the dark-terminal A4 style of pdfs/build_phase_n_forensic_audit_pdf.py.
12-15 pages covering: operator framing, Phase N data summary, J.1.6
baseline confirmation, MMD thesis, bot state proof, 3-session roadmap,
forensic preservation map.

Usage:
    uv run --with reportlab python -u pdfs/build_phase_p_kickoff_pdf.py
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
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "pdfs" / "PHASE_P_KICKOFF.pdf"

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
            "Phase P — Hard revert + MMD build · 2026-05-18 · POLYMARKET 5m bot",
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
        "tt": ParagraphStyle("tt", parent=base["BodyText"], fontName="Courier",
                             fontSize=8, textColor=TEXT, leading=10),
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


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=18 * mm,
        title="Phase P — Hard revert to J.1.6 + MMD build",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])

    s = _styles()
    story: list = []

    # ──────────────────────────────────────────────────────────────────────────
    # COVER
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Spacer(0, 30 * mm))
    story.append(Paragraph("PHASE&nbsp;P", s["cover_title"]))
    story.append(Paragraph("Hard revert to J.1.6 + Market Mode Detector build",
                           s["cover_sub"]))
    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "POLYMARKET 5-minute BTC up/down bot<br/>"
        "Reverted: every Phase L/M/O bot-runtime feature (code + env)<br/>"
        "Restored: J.1.6 peak config (Kelly 0.15× + bankroll replay + cap=1)<br/>"
        "Branch: <b>claude/phase-P-hard-reset</b> @ <b>53e08c9</b> (cut from 83fe119)<br/>"
        "Session 1 close: <b>2026-05-17 21:37:34 UTC</b>",
        s["cover_sub"],
    ))
    story.append(Spacer(0, 18 * mm))
    story.append(Paragraph("Bot LIVE on J.1.6 baseline at $1,000 bankroll — MainPID 1019607",
                           s["cover_ok"]))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "Source-of-truth prompt: ~/Desktop/phase-P-hard-reset-2026-05-18.txt<br/>"
        "Authored by operator after Phase O Session 1 disappointment.",
        s["small"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # TOC
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("Contents", s["h1"]))
    story.append(Spacer(0, 4 * mm))
    toc_rows = [
        ["§1", "What we're reverting and why — operator's framing"],
        ["§2", "Phase N data summary — the 5-day forensic evidence"],
        ["§3", "J.1.6 baseline restored — exact env + branch commit"],
        ["§4", "Market Mode Detector (MMD) — Sessions 2-3 thesis"],
        ["§5", "Bot state confirmation — startup log + dashboard at $1k anchor"],
        ["§6", "Three-session phased roadmap + acceptance criteria"],
        ["§7", "Forensic data preservation — where the 5-day data lives"],
    ]
    story.append(_table(toc_rows, col_widths=[18 * mm, 150 * mm], header=False))
    story.append(Spacer(0, 6 * mm))
    story.append(Paragraph(
        "This kickoff PDF is the Session-1 deliverable for Phase P. It does NOT argue "
        "against the revert. It documents what was reverted, the data that justifies "
        "the verdicts, the exact baseline now LIVE, and the path to Phase Q.",
        s["small"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 1 — Operator framing
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§1 &nbsp;&nbsp; What we're reverting and why", s["h1"]))
    story.append(Paragraph(
        "Operator's verbatim framing (source-of-truth prompt at "
        "<font face='Courier'>~/Desktop/phase-P-hard-reset-2026-05-18.txt</font>):",
        s["body"],
    ))
    story.append(Paragraph(
        "\"I'm really disappointed at the results that we currently have. We're "
        "going to revert back to pre peak. The pre peak — the last ship was "
        "J.1.6, Kelly 0.15× plus replay. So yeah, just let's revert back to "
        "pre peak.\"",
        s["quote"],
    ))
    story.append(Paragraph(
        "\"Use GitHub. Make sure the VPS, the Mac directory, and everything is "
        "aligned together with the same version. We need you to revert. So just "
        "make a plan for that because we have shipped so many fucking features "
        "based on emotions post peak. ... The bot is in a really nice stage. It "
        "can't even make a single trade now. Fully revert to pre peak now.\"",
        s["quote"],
    ))
    story.append(Paragraph(
        "\"I think we're missing one thing only, and I think it's the regime "
        "classifier. Let's not call it regime classifier. ... find this one "
        "GitHub repo that when we turn on and integrate into our bot, it can "
        "detect when Bitcoin is going up, when Bitcoin is going down, and when "
        "Bitcoin is choppy or mixed.\"",
        s["quote"],
    ))
    story.append(Paragraph(
        "\"Make sure to restart the bot, turn it on with one thousand dollar "
        "bankroll. Make sure to reset the chart, the cumulative PnL chart, and "
        "make sure to reset the decision tape. Just reset the full dashboard. "
        "Make a full plan. This is the last chance we have.\"",
        s["quote"],
    ))
    story.append(Paragraph("The story arc this revert is responding to:", s["h3"]))
    arc = [
        ["Phase G", "2026-05-12", "Zero-edge audit. 50% WR / −$19 net on n=633."],
        ["Phase H", "2026-05-13", "v2.1 priors + Kelly + cap=1 + H.2.12 path-A block_up."],
        ["Phase J", "2026-05-14", "J.1.5 CH3 fold + J.2 hour blocklist + J.1.6 Kelly 0.15× + replay. ← THE PEAK CONFIG."],
        ["Phase K", "2026-05-16", "4-day soak. Peak +$1,235 @ 05-15 15:40Z. Day-4 drawdown −$1,294 in 18h."],
        ["Phase L", "2026-05-16", "SUPERSEDED same-day by Phase M."],
        ["Phase M", "2026-05-16/17", "5 layers in 22h: L.5 + M.1a v0 + M.1a v1 + M.5 + M.2 v0."],
        ["Phase N", "2026-05-17", "Forensic PDF (22 pp). M.1a v1 FALSIFIED on n=755. M.5 design CORRECT but shipped 3 days late. SURV-cell flip identified as dominant bleeder."],
        ["Phase O", "2026-05-17", "Session 1 remediation. 3 emergency mid-session pivots ($1k→$3k, L.5 ×3, M.5 lookback). 1 fire / 5h = LOSS −$163. Operator: revert."],
        ["Phase P", "2026-05-18", "THIS PHASE — strip post-peak ware, restore J.1.6, add ONE new thing (MMD) on data-grounded process."],
    ]
    story.append(_table([["Phase", "Date", "What"]] + arc, col_widths=[20 * mm, 24 * mm, 124 * mm]))
    story.append(Spacer(0, 4 * mm))
    story.append(Paragraph(
        "J.1.6 (the revert target) was live at the peak <i>and</i> through the "
        "post-peak drawdown. The operator knows this. The revert isn't a magic "
        "fix — it's a clean baseline from which to add ONE measured ingredient "
        "with backtest + shadow-log discipline.",
        s["body"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 2 — Phase N data summary
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§2 &nbsp;&nbsp; Phase N data summary — what the 5 days proved",
                           s["h1"]))
    story.append(Paragraph(
        "Phase N forensic audit (pdfs/PHASE_N_FORENSIC_AUDIT.pdf, 22 pp, 14 charts) "
        "audited n=755 settled fires across 4.2 days (100% strategy=spot_aware_v2_1, "
        "mode=kelly_multi). It is the data backbone for every KEEP/DROP verdict "
        "below.",
        s["body"],
    ))
    story.append(Paragraph("§2.1 &nbsp; Headline findings (Phase N §3-§5)", s["h2"]))
    findings = [
        ["SURV cell (tier 30-50% × |Δbps|≥5)", "Pre-peak WR 60.7%, PnL +$1,431 → Post-peak WR 46.5%, PnL −$1,161. <b>Dominant bleeder.</b>"],
        ["Tier 70-85% Path A (H.2.12 block_up)", "n=237, 0 UP fires (gate works); DOWN-only WR 74.3% vs ~77.5% break-even. −$368 5-day net. Slower secondary bleed."],
        ["CH3 cell (J.1.5 fold)", "0 fires post-fold across n=755. Fold works as designed."],
        ["M.1a v1 chop-abstain", "FALSIFIED. Annotated n=83: chop n=23 WR 60.9% +$31 vs mixed n=58 WR 44.8% −$296. Falsified by |Δbps| proxy on n=755 (monotonic WR 35.7% / 33.8% / 60.5% / 71.4%) — chop > mixed inversion is small-n artifact."],
        ["M.5 path-A regime wrapper", "Design CORRECT but shipped 3 days late. Idealized simulator: +$352.92 counterfactual avoided. Realistic (with restart resets): +$330.51 avoided. First activatable: 2026-05-14 05:55:25Z."],
        ["M.2 v0 orderbook imbalance shadow", "Lived 45 min; n=3, all <i>too_thin</i>, all lost. Un-evaluable."],
        ["Restart erosion", "19 likely bot restarts in 5 days (one 177-min outage). Per-restart cold-start cost ~$22 to M.5's counterfactual."],
    ]
    story.append(_table([["Finding", "What the data shows"]] + findings,
                        col_widths=[55 * mm, 113 * mm]))

    story.append(Paragraph("§2.2 &nbsp; Why this justifies the revert (not just M.5 ship-late fix)",
                           s["h2"]))
    story.append(Paragraph(
        "Phase O Session 1 already implemented Phase N's #1 recommendation "
        "(disable M.1a v1) but layered on additional remediations "
        "(SURV canary + bankroll override $1k→$3k + L.5 ×3 + M.5 lookback tune). "
        "The 1 post-restart fire = LOSS −$163 didn't refute the design — but the "
        "operator concluded that the Phase M/O <i>stack</i> had become un-tractable "
        "and that compounding fixes on top wasn't going to clear the picture.",
        s["body"],
    ))
    story.append(Paragraph(
        "Hard revert achieves: (1) clean baseline for measuring any new ingredient "
        "in isolation; (2) restoring decision #10 ($1k bankroll), keeping bet sizes "
        "in the $25-150 band where Phase J variance was characterized; (3) clear "
        "decoupling between &quot;the old defenses fight each other&quot; vs "
        "&quot;the underlying strategy has degraded&quot;.",
        s["body"],
    ))
    story.append(Paragraph(
        "Trade-off documented: J.1.6 is the same config that produced the $1,235 "
        "peak <i>and</i> the $1,294 drawdown. The revert does not promise a different "
        "outcome at $1k stakes. It promises a clean slate against which the MMD "
        "(§4) can be measured.",
        s["warn"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 3 — J.1.6 baseline restored
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§3 &nbsp;&nbsp; J.1.6 baseline restored — exact env + branch",
                           s["h1"]))
    story.append(Paragraph("§3.1 &nbsp; Branch state", s["h2"]))
    branch_rows = [
        ["Branch", "claude/phase-P-hard-reset"],
        ["HEAD", "53e08c9 (chore(phase-P): preserve Phase N forensic data)"],
        ["Cut from", "83fe119 — docs(phase-J): design lock for J.3 + J.7 (docs-only, last commit before L.5 shipped)"],
        ["Author of base", "Hamad, 2026-05-13 11:28:23 +0400 (07:28 UTC)"],
        ["Commits dropped vs jovial-hermann@e3133e6", "12 (all Phase L docs + M.* + O.*)"],
        ["Files preserved on new branch", "Phase N PDF + builder + scripts + 14 PNG charts + runbooks + ledgers + 4 session notes"],
    ]
    story.append(_table(branch_rows, col_widths=[60 * mm, 108 * mm], header=False))

    story.append(Paragraph("§3.2 &nbsp; KEEP-LIST (the J.1.6 strategy surface)", s["h2"]))
    keep = [
        ["STRATEGY", "spot_aware_v2_1", "H.2 v2.1"],
        ["KELLY_MULT", "0.15", "J.1.6 B — Tier S1"],
        ["MULTI_FIRE_CAP", "1", "H.5 throttle"],
        ["BANKROLL_REPLAY_ENABLED", "true", "J.1.6 A — Kelly compounds off bankroll"],
        ["PMB_STARTING_BANKROLL", "1000", "decision #10 restored from $3k Phase O override"],
        ["SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK", "0.0", "J.1.5 fold — CH3 cell dead"],
        ["SPOT_AWARE_TIER_RELAX_PRICE_FLOOR", "0.42", "J.1 — H.3 audit n=111 boundary"],
        ["SPOT_AWARE_HOUR_BLOCKLIST_UTC", "22,23,0", "J.2 — catastrophic hours × 70-85%"],
        ["SPOT_AWARE_HOUR_BLOCKLIST_TIERS", "70-85%", "J.2"],
        ["SPOT_AWARE_BLOCK_UP_IN_TIERS", "70-85%", "H.2.12 path-A — block UP in tier 70-85%"],
        ["INSTANT_SETTLE_ENABLED", "1", "cross-phase (latency)"],
        ["INSTANT_SETTLE_GAMMA_TIMEOUT_S", "30", "H.2.10"],
        ["POST_HOC_GAMMA_RETRY_ENABLED", "1", "cross-phase (settle truth)"],
    ]
    story.append(_table([["Env var", "Value", "Origin"]] + keep,
                        col_widths=[65 * mm, 28 * mm, 75 * mm]))

    story.append(Paragraph("§3.3 &nbsp; DROP-LIST (git-reverted + .envrc stripped)", s["h2"]))
    drop = [
        ["L.5 daily-PnL auto-halt", "design + src/_live/auto_halt.py + DAILY_PNL_* env + auto-resume cron"],
        ["M.1a v0 + v1 regime classifier", "design + spot_aware_v2_1.py gate + REGIME_M1A_* + REGIME_CLASSIFIER_V2_SHADOW_ENABLED"],
        ["M.5 path-A regime wrapper", "design + path_a_wr_metrics.py + REGIME_M5_* env"],
        ["M.2 v0 orderbook imbalance shadow", "design + spot_aware_v2_1.py annotation + ORDERBOOK_IMBALANCE_* env"],
        ["O.1 SURV-cell shift canary", "design + surv_canary_metrics.py + SURV_CANARY_* env"],
        ["Dashboard PMB env passthrough", "src/.../dashboard/bankroll.py + dashboard_server/state.py mod + systemd drop-in"],
        ["Phase O bankroll override $1k→$3k", "env-only (PMB_STARTING_BANKROLL=3000, BANKROLL_REPLAY_ENABLED=false)"],
        ["Phase 14 tier-gate env", "kept code (no-op default false); stripped TIER_GATE_ENABLED / TIER_GATE_BLOCKLIST from .envrc"],
        ["Phase 15 regime-gate env", "kept code (no-op default false); stripped REGIME_GATE_ENABLED / REGIME_GATE_ABSTAIN_REGIMES from .envrc"],
    ]
    story.append(_table([["Feature", "How it was removed"]] + drop,
                        col_widths=[58 * mm, 110 * mm]))
    story.append(Paragraph(
        "Full inventory with Phase N verdict per feature at "
        "<font face='Courier'>runbooks/research/phase-P-feature-inventory.md</font>.",
        s["small"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 4 — MMD thesis
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§4 &nbsp;&nbsp; Market Mode Detector (MMD) — Sessions 2-3 thesis",
                           s["h1"]))
    story.append(Paragraph("§4.1 &nbsp; Why MMD (not &quot;regime classifier&quot;)", s["h2"]))
    story.append(Paragraph(
        "Operator-directed rename: the previous &quot;regime classifier&quot; name "
        "is deprecated. The new name is <b>Market Mode Detector (MMD)</b>. The "
        "intent is the same shape but a different lineage from the dead M.1a "
        "vol-ratio classifier:",
        s["body"],
    ))
    mmd_diff = [
        ["Sourced from", "M.1a v0/v1: hand-rolled vol-ratio | MMD: battle-tested GitHub TA library"],
        ["Inputs", "M.1a: single vol-ratio | MMD: multi-indicator (ADX + ATR + BB-width + momentum)"],
        ["Output labels", "M.1a: trending / chop / mixed (3) | MMD: UP / DOWN / CHOPPY / MIXED (4) + optional confidence"],
        ["Validation discipline", "M.1a v1: activated on n=23 annotated subset → falsified on n=755 | MMD: validated against Phase N n=755 BEFORE shipping to bot"],
        ["Ship discipline", "M.1a v0 → v1 in 2 days (DARK → ACTIVE) | MMD: Session 2 backtest → Session 3 SHADOW only → Day-5 audit → Phase Q gate-promote decision"],
    ]
    story.append(_table([["Dimension", "M.1a (dead) vs MMD (this phase)"]] + mmd_diff,
                        col_widths=[40 * mm, 128 * mm]))

    story.append(Paragraph("§4.2 &nbsp; What MMD outputs (target spec)", s["h2"]))
    story.append(Paragraph(
        "Given the spot tick stream (Binance + Coinbase WebSocket already running) "
        "plus a rolling window, output a label:",
        s["body"],
    ))
    labels = [
        ["UP", "sustained uptrend"],
        ["DOWN", "sustained downtrend"],
        ["CHOPPY", "high-frequency low-amplitude oscillation"],
        ["MIXED", "neither clearly trending nor clearly choppy"],
    ]
    story.append(_table([["Label", "Meaning"]] + labels,
                        col_widths=[28 * mm, 140 * mm]))
    story.append(Paragraph(
        "Plus an optional confidence ∈ [0,1] and a forward &quot;what's likely "
        "next&quot; projection (operator framing: &quot;kind of know or predict "
        "what's gonna happen next&quot;).",
        s["body"],
    ))

    story.append(Paragraph("§4.3 &nbsp; Candidate repos Session 2 will evaluate", s["h2"]))
    cands = [
        ["bukosabino/ta", "pure-Python TA (ADX/ATR/BB/momentum). Battle-tested, MIT. Likely the primary candidate."],
        ["twopirllc/pandas-ta", "large TA library on pandas. MIT."],
        ["hudson-and-thames/mlfinlab", "ML-for-finance regime-switching modules. MIT."],
        ["hmmlearn", "Hidden Markov regime models. BSD."],
        ["GitHub search", "top 5 repos ≥100 stars + ≥90d recent activity matching &quot;bitcoin regime detection&quot; / &quot;crypto market regime&quot; / &quot;btc trend classifier&quot;"],
    ]
    story.append(_table([["Repo", "Why on the shortlist"]] + cands,
                        col_widths=[50 * mm, 118 * mm]))
    story.append(Paragraph(
        "Evaluation criteria: tick-input or trivial bar-aggregation; structured "
        "output (label + confidence); license MIT/Apache/BSD (decision #8); "
        "backtestable on Phase N n=755 forensic data; dep footprint &lt; 50 MB "
        "+ no uv.lock conflict.",
        s["body"],
    ))
    story.append(Paragraph(
        "Session 2 will extend scripts/research/phase_n_forensic_audit.py with a "
        "<font face='Courier'>section_p_mmd_backtest()</font> that classifies each "
        "of the 755 fires, joins to outcome, computes per-label WR + $/tr table, "
        "and scores reversal-prediction TPR via a ROC sweep. A USEFUL MMD shows "
        "≥ 10pp WR delta between best and worst label on n=755 AND TPR ≥ 0.6 on "
        "the reversal-prediction task.",
        s["body"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 5 — Bot state confirmation
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§5 &nbsp;&nbsp; Bot state confirmation — $1k anchor proven",
                           s["h1"]))
    story.append(Paragraph("§5.1 &nbsp; systemd state (VPS, 2026-05-17 21:37:34 UTC)",
                           s["h2"]))
    state_rows = [
        ["bot-staging.service", "active / running"],
        ["MainPID", "1019607"],
        ["ExecMainStartTimestamp", "Sun 2026-05-17 21:37:28 UTC"],
        ["dashboard-server.service", "active (restart with bankroll.conf drop-in removed)"],
        ["state/halt.sentinel", "absent"],
        ["VPS HEAD", "53e08c903f4d2a3e53b8da63aed35e2184c8e236"],
        ["VPS branch", "claude/phase-P-hard-reset"],
    ]
    story.append(_table(state_rows, col_widths=[80 * mm, 88 * mm], header=False))

    story.append(Paragraph("§5.2 &nbsp; Bot startup log (canonical J.1.6 signature)",
                           s["h2"]))
    log_lines = [
        "active strategy: spot_aware_v2_1",
        "spot_aware_v2_1: kelly_mult=0.15 max_bet_abs=$500 multi_fire_cap=1",
        "    tier_relax_p_win_fallback=None tier_relax_price_floor=0.420",
        "    block_up_in_tiers=('70-85%',) block_down_in_tiers=()",
        "    hour_blocklist_utc=(22, 23, 0) hour_blocklist_tiers=('70-85%',)",
        "instant-settle ENABLED: gamma poll timeout=30.0s interval=5.0s",
        "post-hoc gamma retry ENABLED: initial_delay=300.0s interval=30.0s",
        "spot_aware_v2_1: bankroll_getter wired (start=$1000.00, replay=True, cap=1)",
        "bankroll replay: starting=$1000.00 current=$1000.00",
        "orphan recovery: 0 orphans found",
    ]
    for line in log_lines:
        story.append(Paragraph(line, s["code"]))
    story.append(Paragraph(
        "Absent (intentional): L.5 / M.5 / M.1a / SURV-canary / orderbook-imbalance "
        "/ MMD lines.",
        s["small"],
    ))

    story.append(Paragraph("§5.3 &nbsp; Dashboard /api/state at session close", s["h2"]))
    api_rows = [
        ["mode.label", "WAITING"],
        ["bankroll.starting_usd", "$1000.0"],
        ["bankroll.current_usd", "$1000.0"],
        ["bankroll.delta_usd", "$0.0"],
        ["today.n_settled", "0"],
        ["decisions[]", "0 entries"],
        ["cumulative_pnl_series", "0 pts"],
        ["scenarios[].n_settled (sample)", "0"],
    ]
    story.append(_table(api_rows, col_widths=[80 * mm, 88 * mm], header=False))

    story.append(Paragraph(
        "Dashboard fully reset per operator directive (&quot;reset the chart, "
        "the cumulative PnL chart, and reset the decision tape. Just reset the "
        "full dashboard&quot;). Systemd drop-in "
        "<font face='Courier'>/etc/systemd/system/dashboard-server.service.d/bankroll.conf</font> "
        "(Phase O env passthrough) was deleted; daemon-reloaded; dashboard restarted.",
        s["body"],
    ))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 6 — Three-session roadmap + acceptance
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§6 &nbsp;&nbsp; Three-session phased roadmap", s["h1"]))
    sessions = [
        ["Session 1", "2026-05-17 21:37 UTC", "DONE", "Hard revert + dashboard reset + this PDF. Bot LIVE on J.1.6 baseline. Vault + memory + MEMORY.md updated. Forensic data preserved on new branch."],
        ["Session 2", "T+1-3 days (operator GO)", "PENDING", "MMD candidate research (top-2 from shortlist). Extend phase_n_forensic_audit.py with section_p_mmd_backtest(). Backtest on n=755 — per-label WR + $/tr + ROC for reversal-prediction. Lock design at design/P.1-market-mode-detector-integration.md. PDF: PHASE_P_SESSION2_MMD_RESEARCH.pdf. No bot changes."],
        ["Session 3", "T+5-7 days after Session 2", "PENDING", "Implement MMD per locked design. ≥12 new tests + mypy strict + ruff + import-linter. Plumb mmd=&lt;label&gt; rationale annotation. VPS deploy with MMD_ENABLED=true MMD_MODE=shadow. Verify first 3 fires get the annotation. PDF: PHASE_P_SESSION3_MMD_SHIP.pdf. 5-day observation window OPENS."],
        ["Phase Q decision", "Day 5 from Session 3 ship", "—", "MMD ≥10pp WR delta → promote to ACTIVE gate (consider also re-introducing M.5). MMD ≤5pp → SHELVE; reconsider strategy class. 5-10pp → KEEP shadow, iterate parameters."],
    ]
    story.append(_table([["Session", "When", "Status", "Outcome"]] + sessions,
                        col_widths=[24 * mm, 36 * mm, 18 * mm, 90 * mm]))

    story.append(Paragraph("§6.1 &nbsp; Session 1 acceptance — all green", s["h2"]))
    accept = [
        "Mac main repo HEAD == VPS HEAD == origin/claude/phase-P-hard-reset",
        "bot-staging.service active on new HEAD; J.1.6 baseline in startup log",
        "Dashboard /api/state: $1,000 starting / $1,000 current / $0 today PnL / empty decisions[] / empty cumulative_pnl_series",
        "state/decisions/2026-05-18.jsonl exists (empty)",
        "state/decisions{,-resolved}/archived/phase-P-reset/*.jsonl preserves 5-day data",
        "Dashboard systemd drop-in bankroll.conf REMOVED",
        "state/halt.sentinel absent",
        "pdfs/PHASE_P_KICKOFF.pdf rendered (this file)",
        "Vault + memory + MEMORY.md updated; Phase O marked SUPERSEDED",
        "No Phase M/O bot-runtime code in src/ on the new branch",
        "Forensic data (Phase N PDF + audit script + charts) survives on new branch",
    ]
    for line in accept:
        story.append(Paragraph(f"✓  {line}", s["ok_box"]))

    story.append(Paragraph("§6.2 &nbsp; Hard DO-NOTs (operator-stated)", s["h2"]))
    donts = [
        "Do not re-add any Phase M/O bot-runtime feature during Session 2 or 3.",
        "Do not change the bankroll from $1,000 (decision #10 restored).",
        "Do not activate MMD on small-n during Session 3 — shadow first, always.",
        "Do not re-introduce M.5 / SURV canary in Phase P — wait for the Phase Q decision after Day-5 MMD re-soak data.",
        "Do not delete the forensic data — archive only.",
        "Do not include preachy honest-pushback sections in the PDFs that argue against the revert.",
    ]
    for line in donts:
        story.append(Paragraph(f"×  {line}", s["warn"]))
    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 7 — Forensic data preservation
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§7 &nbsp;&nbsp; Forensic data preservation map", s["h1"]))
    story.append(Paragraph("§7.1 &nbsp; On the new branch (cherry-picked from e3133e6)",
                           s["h2"]))
    branch_files = [
        ["pdfs/PHASE_N_FORENSIC_AUDIT.pdf", "22 pp, 14 charts, 1.3 MB"],
        ["pdfs/build_phase_n_forensic_audit_pdf.py", "reportlab builder"],
        ["scripts/research/phase_n_forensic_audit.py", "n=755 audit + simulators (380 LOC + Session 2 extensions)"],
        ["scripts/research/phase_n_charts.py", "matplotlib chart pipeline (~400 LOC)"],
        ["runbooks/research/phase-N-forensic-output-2026-05-17.txt", "raw audit output"],
        ["runbooks/research/phase-N-forensic-summary.md", "operator briefing"],
        ["state/research/phase-N-charts/*.png", "14 PNGs (cumulative PnL, bankroll trajectory, daily PnL bar, per-tier PnL/WR, SURV pre/post peak, M.5 simulator, M.1a inversion test, hour×tier heatmap, daily×tier×side, restart markers, |Δbps|×tier, CH3 vs SURV contrast, phase timeline, loss attribution)"],
        ["state/phases/phase-N-forensic-audit.md", "Phase N phase ledger"],
        ["state/phases/phase-O-remediation.md", "Phase O phase ledger (historical)"],
        ["state/sessions/2026-05-17-phase-N-kickoff.md", "Phase N Session 1"],
        ["state/sessions/2026-05-17-phase-N-session-2-pdf-study.md", "Phase N Session 2 (PDF study)"],
        ["state/sessions/2026-05-17-phase-O-session-1-bot-resumed.md", "Phase O Session 1"],
        ["state/sessions/2026-05-18-phase-O-session-2-prep.md", "Phase O Session 2 prep (superseded by Phase P)"],
    ]
    story.append(_table([["Path", "What"]] + branch_files,
                        col_widths=[80 * mm, 88 * mm]))

    story.append(Paragraph("§7.2 &nbsp; On the VPS (archived runtime data)", s["h2"]))
    vps_files = [
        ["state/decisions/archived/phase-P-reset/2026-05-13.jsonl", "240,427 bytes"],
        ["state/decisions/archived/phase-P-reset/2026-05-14.jsonl", "236,536 bytes"],
        ["state/decisions/archived/phase-P-reset/2026-05-15.jsonl", "205,346 bytes (peak day)"],
        ["state/decisions/archived/phase-P-reset/2026-05-16.jsonl", "233,606 bytes (drawdown day)"],
        ["state/decisions/archived/phase-P-reset/2026-05-17.jsonl", "70,993 bytes (partial — Phase O day)"],
        ["state/decisions-resolved/archived/phase-P-reset/2026-05-{13..17}.jsonl", "243K / 240K / 208K / 237K / 72K (post-hoc gamma-truth resolutions)"],
        ["/tmp/phaseN_data/state/decisions{,-resolved}/", "Original Phase N tarball (re-pull command in PHASE_N audit script)"],
        [".envrc.bak.phase-P-revert-2026-05-18", "Pre-revert .envrc (8,404 bytes, contains all Phase M/O env vars for reference)"],
        [".envrc.bak.* (older backups)", "Phase F / Phase H / Phase O / etc. — kept for historical reference"],
    ]
    story.append(_table([["Path", "Size / note"]] + vps_files,
                        col_widths=[85 * mm, 83 * mm]))

    story.append(Paragraph("§7.3 &nbsp; What Session 2 MMD backtest will use", s["h2"]))
    story.append(Paragraph(
        "The Session-2 MMD backtest extension to "
        "<font face='Courier'>scripts/research/phase_n_forensic_audit.py</font> "
        "will: (1) load the JSONL files from "
        "<font face='Courier'>state/decisions{,-resolved}/archived/phase-P-reset/</font>, "
        "(2) for each of the 755 fires reconstruct ~30 minutes of spot trajectory "
        "from snapshot.spot_now + oracle_last, (3) classify each moment with the "
        "candidate MMD, (4) join to per-fire outcome, (5) compute per-label WR + "
        "$/tr + n table + reversal-prediction ROC.",
        s["body"],
    ))

    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 8 — Operator bottom line + Phase Q decision matrix + unlocks
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§8 &nbsp;&nbsp; Operator's bottom line + Phase Q decision matrix",
                           s["h1"]))
    story.append(Paragraph("§8.1 &nbsp; Operator's bottom line (verbatim)", s["h2"]))
    story.append(Paragraph(
        "\"The bot is in a really nice stage. It can't even make a single trade "
        "now. Fully revert to pre peak now. Make a fully phased plan. This is "
        "the last chance we have.\"",
        s["quote"],
    ))
    story.append(Paragraph(
        "— operator, 2026-05-18",
        s["small"],
    ))
    story.append(Paragraph(
        "&quot;The last chance&quot; framing is the operating frame for Phase P, Q "
        "and beyond. The clock isn't capital (J.1.6 + revert leaves the bankroll "
        "intact at $1k); it's the operator's trust in the design loop. The remedy "
        "is process discipline: shadow before active, n=755 backtest before ship, "
        "ONE new thing per phase. Phase P is the demonstration that we can hold "
        "to that.",
        s["body"],
    ))

    story.append(Paragraph("§8.2 &nbsp; Phase Q decision matrix (set NOW so we don't re-decide later)",
                           s["h2"]))
    matrix = [
        ["≥10pp WR delta between best and worst MMD label on n=755 live data AND TPR ≥ 0.6 on reversal-prediction",
         "PROMOTE MMD shadow → ACTIVE gate (MMD_MODE=gate, MMD_LABELS_TO_ABSTAIN=...). Also reconsider M.5 as the path-A-specific layer alongside MMD — Phase N proved M.5 design was right shipped late."],
        ["5-10pp WR delta",
         "KEEP MMD in SHADOW; iterate on indicator parameters (lookback / threshold). Re-audit at Day-10. No M.5 reintroduction."],
        ["≤5pp WR delta",
         "SHELVE MMD; reconsider the strategy class entirely. Path to Phase R: either pivot strategy or accept J.1.6 as the ceiling at this bankroll."],
        ["MMD fails to compute (classifier exception OR ambiguous label)",
         "Pass-through fail-safe (already in design): do not gate. Telemetry counter tracked. If &gt;5% of fires fail-pass, ship a fix as part of Session 4."],
    ]
    story.append(_table([["Phase Q signal", "Action"]] + matrix,
                        col_widths=[78 * mm, 90 * mm]))

    story.append(Paragraph("§8.3 &nbsp; What this whole phase unlocks", s["h2"]))
    unlocks = [
        ["After Session 1 (NOW)", "Bot LIVE on clean J.1.6 at $1k. Mac + VPS + GitHub aligned. Dashboard fully reset. 5-day forensic data archived. PHASE_P_KICKOFF.pdf available. Day-1 baseline observation begins."],
        ["After Session 2", "MMD candidate picked + backtested on n=755. Integration design locked. PHASE_P_SESSION2_MMD_RESEARCH.pdf available. Operator preview of which MMD will ship in Session 3."],
        ["After Session 3", "MMD shipped + shadow-annotating fires (mmd=&lt;label&gt; in rationale). Bot still on J.1.6 (no firing changes). 5-day observation window OPEN. PHASE_P_SESSION3_MMD_SHIP.pdf available."],
        ["After Phase P CLOSED (~Day 5 from Session 3 ship)", "Empirical verdict on MMD as edge source. ~9 days of total data (Phase N's 5 + 5 new). Phase Q plan grounded in real numbers, not feelings."],
        ["Phase Q decision", "KEEP J.1.6 + MMD as Phase R baseline, OR pivot strategy class, OR reconsider entire approach. Operator picks from the decision matrix in §8.2 based on Day-5 numbers."],
    ]
    story.append(_table([["Milestone", "Outcome"]] + unlocks,
                        col_widths=[58 * mm, 110 * mm]))

    story.append(PageBreak())

    # ──────────────────────────────────────────────────────────────────────────
    # SECTION 9 — Glossary + version manifest
    # ──────────────────────────────────────────────────────────────────────────
    story.append(Paragraph("§9 &nbsp;&nbsp; Glossary + version manifest", s["h1"]))
    story.append(Paragraph("§9.1 &nbsp; Acronym + named-element glossary", s["h2"]))
    gloss = [
        ["J.1.6", "Phase J Session 1.6 (2026-05-14 18:36 UTC) — Kelly 0.15× Tier S1 + BANKROLL_REPLAY_ENABLED=true. Env-only flip on top of J.1.5 fold. Peak config."],
        ["J.1.5 fold", "Phase J Session 1.5 (2026-05-14 07:22 UTC) — SPOT_AWARE_TIER_RELAX_P_WIN_FALLBACK 0.48 → 0.0. Disables CH3 priors-fallback fires (cell statistically dead)."],
        ["H.2.12 path A", "Phase H 2.12 (2026-05-13 00:56 UTC, commit c746db3) — SPOT_AWARE_BLOCK_UP_IN_TIERS=70-85%. Block UP fires in tier 70-85% (catastrophic bleeder pre-fix)."],
        ["CH3 cell", "Conservative-Hedge cell: tier 30-50% with |Δbps|&lt;5. Phase G winning cell on n=83; turned out to lose live."],
        ["SURV cell", "Tier 30-50% × |Δbps|≥5. Dominant bleeder identified by Phase N (60.7% → 46.5% WR collapse post-peak)."],
        ["L.5", "Phase M Session 2 (2026-05-16) — daily-PnL auto-halt at -$30 gate, check 23:50 UTC. STRIPPED in Phase P."],
        ["M.1a v0 / v1", "Phase M Session 4/5 — FLAT-vs-TREND regime classifier (vol-ratio). v0 = SHADOW, v1 = ACTIVE chop-abstain. Phase N falsified v1; both STRIPPED in Phase P."],
        ["M.5", "Phase M Session 6 — path-A regime-aware wrapper with rolling-WR threshold. Design correct; shipped 3 days late. STRIPPED in Phase P; may return after Phase Q decision."],
        ["M.2 v0", "Phase M Session 7 — orderbook imbalance shadow-log. n=3 un-evaluable; STRIPPED in Phase P."],
        ["O.1 SURV canary", "Phase O Session 1 — SURV-cell shift detector with rolling-WR margin. n=1 post-restart fire; STRIPPED in Phase P."],
        ["MMD", "Market Mode Detector. Phase P Session 2-3 deliverable. 4 labels (UP/DOWN/CHOPPY/MIXED) + optional confidence. Sourced from GitHub TA library (not invented). Validated against Phase N n=755 before shipping."],
        ["Decision #10", "Locked decision: $1,000 starting bankroll. Overridden in Phase O ($1k → $3k); RESTORED in Phase P."],
    ]
    story.append(_table([["Term", "Meaning"]] + gloss,
                        col_widths=[42 * mm, 126 * mm]))

    story.append(Paragraph("§9.2 &nbsp; Version manifest (Session 1 close)", s["h2"]))
    manifest = [
        ["Branch", "claude/phase-P-hard-reset"],
        ["HEAD", "53e08c9 (chore(phase-P): preserve Phase N forensic data)"],
        ["Base", "83fe119 (docs(phase-J): design lock for J.3 + J.7)"],
        ["GitHub remote", "https://github.com/FalconAEZ/polymarket-5m-bot"],
        ["VPS host:port", "ops@108.132.51.116:2222 (Dublin Lightsail, eu-west-1)"],
        ["VPS service", "bot-staging.service MainPID 1019607 (active since 2026-05-17 21:37:28 UTC)"],
        ["VPS .envrc backup", ".envrc.bak.phase-P-revert-2026-05-18 (8,404 bytes)"],
        ["Bot startup signature", "kelly_mult=0.15 / cap=1 / tier_relax_price_floor=0.420 / block_up_in_tiers=('70-85%',) / hour_blocklist_utc=(22, 23, 0) / bankroll start=$1000 replay=True"],
        ["Dashboard URL", "http://127.0.0.1:8505 (SSH tunnel only; never public)"],
        ["This PDF builder", "pdfs/build_phase_p_kickoff_pdf.py"],
        ["This PDF output", "pdfs/PHASE_P_KICKOFF.pdf"],
        ["Phase ledger", "state/phases/phase-P-hard-reset.md"],
        ["Session note", "state/sessions/2026-05-18-phase-P-session-1-revert.md"],
        ["Memory checkpoint", "~/.claude/projects/-Users-hamad-Desktop-PolyMarket-5m/memory/checkpoint_phase_P.md"],
        ["Feature inventory", "runbooks/research/phase-P-feature-inventory.md"],
        ["Source-of-truth prompt", "~/Desktop/phase-P-hard-reset-2026-05-18.txt"],
    ]
    story.append(_table(manifest, col_widths=[55 * mm, 113 * mm], header=False))

    story.append(Spacer(0, 6 * mm))
    story.append(HRFlowable(width="80%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 4 * mm))
    story.append(Paragraph(
        "End of Phase P Session 1 kickoff.  "
        "Bot is LIVE on J.1.6 baseline at $1,000 bankroll.  "
        "Next: operator GO for Session 2 MMD research.",
        s["headline"],
    ))

    doc.build(story)
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    build()
