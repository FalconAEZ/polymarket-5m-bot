"""Build pdfs/PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf — engineering spec.

This is the operational spec that an engineer can ship v2.1 from. Every
file path, type signature, integration point, test assertion, deployment
command, and past-incident defense is explicit.

Source inputs read while drafting:
  src/polymarket_bot/strategies/spot_aware_v2.py — parent class internals
  src/polymarket_bot/strategies/spot_aware_v3.py — rationale-rewrite pattern
  src/polymarket_bot/strategies/protocol.py — Strategy contract
  src/polymarket_bot/_paper/runner.py — strategy caller + pending_decision invariant
  src/polymarket_bot/dashboard/bankroll.py — bankroll computation
  scripts/run_paper.py — strategy dispatch
  memory/checkpoint_phase_F.md (current live state) + 13 others
  pdfs/PHASE_G_EDGE_DISCOVERY.pdf + PHASE_H_v2_1_IMPLEMENTATION.pdf

Usage:
    uv run --with reportlab python -u pdfs/build_phase_h_final_spec_pdf.py
"""

# ruff: noqa: RUF001, RUF002, RUF003, E741, ARG001

from __future__ import annotations

import shutil
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
OUT = ROOT / "pdfs" / "PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf"
DESKTOP = Path.home() / "Desktop" / "PHASE_H_V2_1_FINAL_IMPLEMENTATION_SPEC.pdf"

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
            "Phase H — v2.1 final implementation spec · 2026-05-13 · POLYMARKET 5m bot"
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
                              fontSize=18, textColor=ACCENT, leading=22, spaceAfter=10, spaceBefore=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontName="Helvetica-Bold",
                              fontSize=13, textColor=ACCENT, leading=17, spaceAfter=8, spaceBefore=12),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontName="Helvetica-Bold",
                              fontSize=10.5, textColor=TEXT, leading=14, spaceAfter=4, spaceBefore=8),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica",
                                fontSize=9, textColor=TEXT, leading=12.5, alignment=TA_LEFT, spaceAfter=5),
        "code": ParagraphStyle("code", parent=base["BodyText"], fontName="Courier",
                                fontSize=8, textColor=ACCENT, leading=10.5, leftIndent=10, spaceAfter=4,
                                backColor=PANEL, borderColor=LINE, borderWidth=0.3, borderPadding=6),
        "warn": ParagraphStyle("warn", parent=base["BodyText"], fontName="Helvetica",
                                fontSize=9.5, textColor=WARN, leading=13, spaceAfter=8,
                                leftIndent=6, rightIndent=6, borderColor=WARN,
                                borderWidth=0.5, borderPadding=5),
        "cover_title": ParagraphStyle("cover_title", parent=base["Title"], fontName="Helvetica-Bold",
                                       fontSize=26, textColor=ACCENT, leading=32, alignment=TA_CENTER, spaceAfter=18),
        "cover_sub": ParagraphStyle("cover_sub", parent=base["BodyText"], fontName="Helvetica",
                                     fontSize=11.5, textColor=TEXT, leading=17, alignment=TA_CENTER, spaceAfter=8),
        "small": ParagraphStyle("small", parent=base["BodyText"], fontName="Helvetica",
                                 fontSize=7.5, textColor=SUBTLE, leading=10, spaceAfter=3),
    }


def _table(rows, col_widths=None):
    t = Table(rows, colWidths=col_widths)
    style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
        ("BACKGROUND", (0, 0), (-1, 0), PANEL),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
        ("LINEBELOW", (0, -1), (-1, -1), 0.3, LINE),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]
    t.setStyle(TableStyle(style))
    return t


def code(s, style):
    """Render a code block from a Python string with HTML escaping."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = s.replace("\n", "<br/>").replace(" ", "&nbsp;")
    return Paragraph(s, style)


def build():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(
        str(OUT), pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=18*mm, bottomMargin=18*mm,
        title="Phase H — v2.1 final implementation spec",
        author="POLYMARKET 5m bot",
    )
    doc.addPageTemplates([_page_template(doc)])
    s = _styles()
    story = []

    # ========== COVER ==========
    story.append(Spacer(0, 35 * mm))
    story.append(Paragraph("PHASE&nbsp;H — v2.1", s["cover_title"]))
    story.append(Paragraph("Final implementation specification", s["cover_sub"]))
    story.append(Spacer(0, 8 * mm))
    story.append(HRFlowable(width="60%", thickness=0.5, color=ACCENT, hAlign="CENTER"))
    story.append(Spacer(0, 8 * mm))
    story.append(Paragraph(
        "Engineering spec — ship-from-this-PDF detail<br/>"
        "Every file path, type signature, integration point, test assertion,<br/>"
        "deployment command, and past-incident defense<br/><br/>"
        "POLYMARKET 5-minute BTC up/down bot · 2026-05-13",
        s["cover_sub"]))
    story.append(Spacer(0, 14 * mm))
    story.append(Paragraph(
        "<b>Scope:</b> a different engineer (or future-you) should be able to ship v2.1 "
        "from this document alone. Each section is grounded in actual code "
        "(read in /src/polymarket_bot/) + Obsidian memory (14 phase checkpoints) + "
        "Phase G analytical findings. Past-incident defenses are explicit.",
        s["body"]))
    story.append(Spacer(0, 8 * mm))
    story.append(Paragraph(
        "<b>Phase H deployment timeline:</b><br/>"
        "H.1 strategic plan PDF ✓ (done today)<br/>"
        "H.1.5 THIS SPEC (now)<br/>"
        "H.2 code (next session, ~1h)<br/>"
        "H.3 tests (next session, ~30min)<br/>"
        "H.4 register + .envrc (next session)<br/>"
        "H.5 VPS deploy + verify (next session)<br/>"
        "H.6 7-day soak gate → PROMOTE / EXTEND / ROLLBACK",
        s["body"]))
    story.append(PageBreak())

    # ========== 1 EXEC SUMMARY ==========
    story.append(Paragraph("1. Executive summary", s["h1"]))
    story.append(Paragraph(
        "v2.1 is v2 + 4 filter changes (CH1-CH4) + Kelly sizing (CH5-CH6) + multi-fire "
        "(CH7-CH8). It exploits the Phase G winning cell (tier 30-50% × |Δ|&lt;5, n=83, "
        "+$0.65/trade, 48% WR with asymmetric payoff that v2 currently REJECTS) while "
        "eliminating the two confirmed loser sub-groups (Δ=0 and EV ∈ [0.02, 0.05)).",
        s["body"]))
    story.append(Paragraph(
        "<b>The big architectural twist this spec adds vs the H.1 PDF:</b> Kelly sizing "
        "requires live bankroll tracking that doesn't exist in PaperRunner today "
        "(bankroll is computed dashboard-side from settled records). And multi-fire "
        "requires lifting the singular `pending_decision` invariant in PaperRunner, not "
        "just the strategy's `_fired_for_window`. Both changes are scoped + tested below.",
        s["headline"] if "headline" in s else s["body"]))
    story.append(Paragraph(
        "<b>Files touched in v2.1 ship:</b>",
        s["body"]))
    story.append(_table([
        ["File", "Action", "Why"],
        ["src/polymarket_bot/strategies/spot_aware_v2_1.py", "NEW", "the new strategy"],
        ["src/polymarket_bot/strategies/kelly_config.py", "NEW", "KellyConfig dataclass"],
        ["src/polymarket_bot/_paper/runner.py", "EDIT", "bankroll tracker + multi-fire support"],
        ["scripts/run_paper.py", "EDIT", "strategy dispatch + bankroll-getter wire"],
        ["tests/strategies/test_spot_aware_v2_1.py", "NEW", "~18 tests"],
        ["tests/strategies/test_kelly_config.py", "NEW", "Kelly math tests"],
        ["tests/paper/test_runner_multi_fire.py", "NEW", "PaperRunner multi-fire regression"],
        ["design/spot_aware_v2_1.md", "NEW", "locked design doc (anti-vibe rule #1)"],
    ], col_widths=[80*mm, 18*mm, 60*mm]))
    story.append(PageBreak())

    # ========== 2 ARCHITECTURE ==========
    story.append(Paragraph("2. Code architecture", s["h1"]))
    story.append(Paragraph("2.1 Class hierarchy", s["h2"]))
    story.append(code(
        "Strategy (Protocol)                                  [protocol.py]\n"
        "  └─ SpotAwareStrategy (v1, 'spot_aware')           [spot_aware.py]\n"
        "       └─ SpotAwareStrategyV2 ('spot_aware_v2')    [spot_aware_v2.py]\n"
        "            ├─ SpotAwareStrategyV3                  [spot_aware_v3.py]\n"
        "            │   (v2 + regime gate; SHELVED post-Phase F)\n"
        "            └─ SpotAwareStrategyV2_1  ★ NEW         [spot_aware_v2_1.py]\n"
        "                (v2 + Kelly + multi-fire + new filters)",
        s["code"]))
    story.append(Paragraph(
        "v2.1 INHERITS from v2 (not from v3). Reason: v3's regime gate is "
        "optional in v2.1 (defaults OFF per Q2). If operator enables it later, "
        "v2.1 will compose RegimeDetector + super.on_event in the v3 style.",
        s["body"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("2.2 Event/decision flow", s["h2"]))
    story.append(code(
        "Feed (WS)         → MarketEvent\n"
        "                       │\n"
        "PaperRunner._on_event ─→ strategy.on_event(event) ──→ Decision | None\n"
        "                       │\n"
        "                       ↓ (Decision returned)\n"
        "             _on_decision(decision)\n"
        "                       │\n"
        "                       ↓\n"
        "             ShadowBook.attempt_fill        (taker simulation)\n"
        "             DecisionLog.record_fired      (JSONL append)\n"
        "             _state.record_decision        (singular pending_decision today)\n"
        "                       │\n"
        "                       ↓ (window close)\n"
        "             _settle_current_window        (gamma → chainlink fallback)\n"
        "             DecisionLog.record_settled    (pnl_usd computed)\n"
        "             BankrollTracker.update        ★ NEW (Kelly feedback loop)",
        s["code"]))
    story.append(Paragraph(
        "<b>The new BankrollTracker</b> is a small in-runner state object that "
        "starts at $1,000 (locked decision #10) and updates on every settled PnL. "
        "v2.1 reads it via a getter callback. Independent of dashboard's "
        "load_bankroll() which derives from JSONL — they converge by construction "
        "but the dashboard remains the source of truth for operator-facing display.",
        s["body"]))
    story.append(PageBreak())

    # ========== 3 STRATEGY CLASS SPEC ==========
    story.append(Paragraph("3. Class definition — SpotAwareStrategyV2_1", s["h1"]))
    story.append(Paragraph("3.1 Constructor signature", s["h2"]))
    story.append(code(
        "from __future__ import annotations\n"
        "from collections.abc import Callable\n"
        "from polymarket_bot.strategies.spot_aware_v2 import SpotAwareStrategyV2\n"
        "from polymarket_bot.strategies.kelly_config import KellyConfig\n"
        "from polymarket_bot.strategies.spot_aware_priors import SpotAwarePriors\n"
        "from polymarket_bot.backtest.types import Decision, MarketEvent\n"
        "\n"
        "\n"
        "class SpotAwareStrategyV2_1(SpotAwareStrategyV2):\n"
        "    name: str = 'spot_aware_v2_1'\n"
        "\n"
        "    def __init__(\n"
        "        self,\n"
        "        *,\n"
        "        priors: SpotAwarePriors,\n"
        "        bankroll_getter: Callable[[], float],\n"
        "        kelly: KellyConfig | None = None,\n"
        "        multi_fire_cap: int = 2,\n"
        "        tier_relax_delta: tuple[str, ...] = ('15-30%', '30-50%'),\n"
        "        ev_bad_bucket: tuple[float, float] = (0.02, 0.05),\n"
        "        **v2_kwargs: object,\n"
        "    ) -> None:\n"
        "        super().__init__(priors=priors, **v2_kwargs)\n"
        "        self._bankroll_getter = bankroll_getter\n"
        "        self._kelly = kelly or KellyConfig()\n"
        "        self._multi_fire_cap = multi_fire_cap\n"
        "        self._tier_relax = frozenset(tier_relax_delta)\n"
        "        self._ev_bad_lo, self._ev_bad_hi = ev_bad_bucket\n"
        "        self._fires_this_window: int = 0\n"
        "        # _fired_for_window inherited from v2 but overridden behavior",
        s["code"]))

    story.append(Spacer(0, 6))
    story.append(Paragraph("3.2 Overridden methods", s["h2"]))
    story.append(_table([
        ["Method", "Override reason"],
        ["_on_boundary", "reset _fires_this_window AND _fired_for_window on window open"],
        ["_maybe_fire", "new filter chain (CH1-CH3); call super; sub Kelly size; rewrite rationale"],
    ], col_widths=[40*mm, 110*mm]))

    story.append(Spacer(0, 4))
    story.append(Paragraph("3.3 _maybe_fire override (exact body)", s["h2"]))
    story.append(code(
        "def _maybe_fire(self, now_ts_utc_ns: int) -> Decision | None:\n"
        "    # Multi-fire gate: stop firing once cap reached for this window.\n"
        "    if self._fires_this_window >= self._multi_fire_cap:\n"
        "        return None\n"
        "\n"
        "    # Pre-compute Δ for the new filters.\n"
        "    if self._spot_now is None or self._window_open_spot is None:\n"
        "        return None\n"
        "    d_bps = delta_bps(self._spot_now, self._window_open_spot)\n"
        "\n"
        "    # CH1 — reject Δ=0 (no skew → confirmed LOSER, Phase G §4.3).\n"
        "    if d_bps == 0.0:\n"
        "        return None\n"
        "\n"
        "    # CH3 — tier-specific Δ floor.\n"
        "    # Determine tier from latest best_ask snapshot.\n"
        "    side_guess: Side = 'UP' if d_bps > 0 else 'DOWN'\n"
        "    ask_guess = self._best_ask_for_side.get(side_guess)\n"
        "    if ask_guess is None:\n"
        "        return None\n"
        "    tier = _tier_label(ask_guess)  # '<15%' / '15-30%' / etc.\n"
        "    min_d = 0.0 if tier in self._tier_relax else self._delta_min\n"
        "    if abs(d_bps) &lt; min_d:\n"
        "        return None\n"
        "\n"
        "    # IMPORTANT: temporarily relax v2's hard self._delta_min for the\n"
        "    # super() call. We do this by setting an instance flag the parent\n"
        "    # checks, OR (simpler) by inlining v2's logic. Spec uses inline.\n"
        "    base_decision = self._maybe_fire_inline(d_bps, side_guess, ask_guess, now_ts_utc_ns)\n"
        "    if base_decision is None:\n"
        "        return None\n"
        "\n"
        "    # CH2 — reject EV ∈ [0.02, 0.05).\n"
        "    ev = _parse_ev(base_decision.rationale)\n"
        "    if self._ev_bad_lo &lt;= ev &lt; self._ev_bad_hi:\n"
        "        # Reset v2's _fired_for_window so the cell can re-evaluate\n"
        "        # later (mirrors v3's regime-gate reset pattern).\n"
        "        self._fired_for_window = None\n"
        "        return None\n"
        "\n"
        "    # CH5/CH6 — Kelly sizing: replace size_usd from bankroll + p_win + price.\n"
        "    bankroll = self._bankroll_getter()\n"
        "    p_win = _parse_p_win(base_decision.rationale)\n"
        "    price = base_decision.price_limit\n"
        "    bet = self._kelly.bet_size(bankroll=bankroll, p_win=p_win, price=price)\n"
        "    if bet &lt; self._kelly.min_bet_abs:\n"
        "        self._fired_for_window = None\n"
        "        return None\n"
        "\n"
        "    # Rewrite rationale (self-tagging; avoids v3 inheritance bug).\n"
        "    new_rationale = _rewrite_rationale_v2_1(\n"
        "        base_decision.rationale,\n"
        "        kelly_f=self._kelly.last_kelly_f,\n"
        "        bet_usd=bet,\n"
        "        bankroll_at_fire=bankroll,\n"
        "        fire_n_in_window=self._fires_this_window + 1,\n"
        "    )\n"
        "    self._fires_this_window += 1\n"
        "    return dc_replace(base_decision, size_usd=bet, rationale=new_rationale)",
        s["code"]))
    story.append(PageBreak())

    # ========== 4 KELLY CONFIG ==========
    story.append(Paragraph("4. KellyConfig dataclass", s["h1"]))
    story.append(Paragraph("File: src/polymarket_bot/strategies/kelly_config.py", s["h3"]))
    story.append(code(
        "\"\"\"Kelly fractional sizing config + bet computation.\"\"\"\n"
        "from __future__ import annotations\n"
        "from dataclasses import dataclass, field\n"
        "\n"
        "@dataclass(slots=True)\n"
        "class KellyConfig:\n"
        "    kelly_mult: float = 0.10        # fractional Kelly (start conservative)\n"
        "    max_bet_pct: float = 0.10       # never more than 10% of bankroll\n"
        "    max_bet_abs: float = 500.0      # Polymarket retail liquidity cap\n"
        "    min_bet_abs: float = 1.00       # below this, drop\n"
        "    last_kelly_f: float = field(default=0.0, init=False)\n"
        "\n"
        "    def __post_init__(self) -> None:\n"
        "        if not 0 &lt; self.kelly_mult &lt;= 1.0:\n"
        "            raise ValueError(f'kelly_mult must be in (0, 1]; got {self.kelly_mult}')\n"
        "        if not 0 &lt; self.max_bet_pct &lt;= 0.5:\n"
        "            raise ValueError(f'max_bet_pct must be in (0, 0.5]; got {self.max_bet_pct}')\n"
        "        if self.max_bet_abs &lt;= 0:\n"
        "            raise ValueError(f'max_bet_abs must be &gt; 0; got {self.max_bet_abs}')\n"
        "\n"
        "    def kelly_f(self, p_win: float, price: float) -> float:\n"
        "        \"\"\"Standard Kelly fraction for a binary bet at given price.\"\"\"\n"
        "        if price &gt;= 1.0 or price &lt;= 0.0 or p_win &lt;= price:\n"
        "            return 0.0\n"
        "        return (p_win - price) / (1.0 - price)\n"
        "\n"
        "    def bet_size(self, *, bankroll: float, p_win: float, price: float) -> float:\n"
        "        \"\"\"Return clamped bet size in USD. Stores last_kelly_f for telemetry.\"\"\"\n"
        "        f = self.kelly_f(p_win, price)\n"
        "        self.last_kelly_f = f\n"
        "        if f == 0.0 or bankroll &lt;= 0:\n"
        "            return 0.0\n"
        "        bet = bankroll * self.kelly_mult * f\n"
        "        bet = min(bet, bankroll * self.max_bet_pct, self.max_bet_abs)\n"
        "        return max(self.min_bet_abs, bet) if bet &gt;= self.min_bet_abs else 0.0",
        s["code"]))
    story.append(Paragraph(
        "<b>Why mutable last_kelly_f?</b> It's a write-once-per-call telemetry cache "
        "consumed by the rationale builder. Could be returned from bet_size() but the "
        "single-return signature keeps callers clean. NOT thread-shared.",
        s["small"]))
    story.append(PageBreak())

    # ========== 5 BANKROLL ==========
    story.append(Paragraph("5. Bankroll-getter integration", s["h1"]))
    story.append(Paragraph("5.1 Why a getter not a static value", s["h2"]))
    story.append(Paragraph(
        "Kelly sizing requires LIVE bankroll. The strategy is constructed once at "
        "startup; bankroll grows/shrinks as fires settle. Inject a callable so the "
        "strategy reads current value at fire time — this is the compounding hook.",
        s["body"]))

    story.append(Paragraph("5.2 PaperRunner changes (BankrollTracker)", s["h2"]))
    story.append(code(
        "# In runner.py, add a small tracker (~30 LOC):\n"
        "@dataclass(slots=True)\n"
        "class BankrollTracker:\n"
        "    starting_usd: float = 1000.0  # locked decision #10\n"
        "    realized_pnl_usd: float = 0.0\n"
        "    # Update on every settled record (fire-and-forget; thread-safe via\n"
        "    # async single-event-loop assumption).\n"
        "    def current(self) -> float:\n"
        "        return self.starting_usd + self.realized_pnl_usd\n"
        "    def apply_settle(self, pnl_usd: float) -> None:\n"
        "        self.realized_pnl_usd += pnl_usd\n"
        "    def apply_correction(self, original_pnl: float, corrected_pnl: float) -> None:\n"
        "        # Phase 15.5 settled_correction overlay support.\n"
        "        self.realized_pnl_usd += (corrected_pnl - original_pnl)\n"
        "\n"
        "# PaperRunner.__init__ adds:\n"
        "#   self._bankroll = BankrollTracker(starting_usd=PMB_STARTING_BANKROLL or 1000)\n"
        "# Then exposes self._bankroll.current as the getter passed to strategy.",
        s["code"]))

    story.append(Paragraph("5.3 Startup recovery (cross-restart consistency)", s["h2"]))
    story.append(Paragraph(
        "On startup, BankrollTracker reads recent settled records from "
        "state/decisions/*.jsonl and replays them to compute the current "
        "bankroll. Avoids the 'restart resets the compound clock' bug. Mirrors "
        "the orphan-fire-recovery pattern already in PaperRunner.",
        s["body"]))
    story.append(Paragraph(
        "Tests must cover: empty log = starting_usd · log with N settles = "
        "starting + Σ pnl · log with corrections = starting + Σ corrected_pnl · "
        "cross-day boundary handling.",
        s["body"]))
    story.append(PageBreak())

    # ========== 6 MULTI-FIRE ==========
    story.append(Paragraph("6. Multi-fire — PaperRunner changes required", s["h1"]))
    story.append(Paragraph(
        "<b>Critical finding from reading runner.py:</b> the singular pending_decision "
        "invariant at _on_decision blocks multi-fire at the runner level. v2.1 cannot "
        "enable multi-fire by itself.",
        s["warn"]))

    story.append(Paragraph("6.1 Current invariant (runner.py:448)", s["h2"]))
    story.append(code(
        "if self._state.pending_decision is not None or self._state.settled_fill is not None:\n"
        "    LOG.warning('second decision in window %s; dropping', self._state.window_ts)\n"
        "    return  # BLOCKED",
        s["code"]))

    story.append(Paragraph("6.2 v2.1-compatible state change", s["h2"]))
    story.append(code(
        "# Refactor _state to support multiple pending decisions per window:\n"
        "@dataclass\n"
        "class _RunnerState:\n"
        "    window_ts: int | None = None\n"
        "    pending_decisions: list[PendingDecision] = field(default_factory=list)\n"
        "    multi_fire_cap: int = 1  # v2 keeps 1; v2.1 sets to 2 from env\n"
        "    \n"
        "    @property\n"
        "    def pending_decision(self) -> Decision | None:\n"
        "        # Backwards-compat read for v1/v2/v3 code paths\n"
        "        return self.pending_decisions[0].decision if self.pending_decisions else None\n"
        "\n"
        "@dataclass\n"
        "class PendingDecision:\n"
        "    decision: Decision\n"
        "    decision_id: str\n"
        "    side: Side\n"
        "    fill: Fill | None  # populated by ShadowBook\n"
        "    settled_fill: Fill | None = None",
        s["code"]))

    story.append(Paragraph("6.3 _on_decision guard relaxation", s["h2"]))
    story.append(code(
        "if len(self._state.pending_decisions) &gt;= self._state.multi_fire_cap:\n"
        "    LOG.info(\n"
        "        'fire %d/%d in window %s; capping',\n"
        "        len(self._state.pending_decisions), self._state.multi_fire_cap,\n"
        "        self._state.window_ts,\n"
        "    )\n"
        "    return\n"
        "# ... otherwise proceed as before, just append rather than assign:\n"
        "self._state.pending_decisions.append(PendingDecision(decision, decision_id, side, fill))",
        s["code"]))

    story.append(Paragraph("6.4 Settle loop changes", s["h2"]))
    story.append(Paragraph(
        "_settle_current_window must iterate all pending_decisions, not just one. "
        "Each settles independently (may have different asset_id and outcome). "
        "BankrollTracker accumulates each settle's pnl_usd.",
        s["body"]))

    story.append(Paragraph("6.5 Per-asset_id NOT per-side (incident defense)", s["h2"]))
    story.append(Paragraph(
        "Per <b>project_per_side_state_pollution_pattern.md</b>: strategies that key "
        "book state by event.side instead of event.asset_id read state from the "
        "WRONG window's token (warmer pre-fetches forward windows). v2.1 must NOT "
        "regress this. Its multi-fire counter is keyed by window_ts, not by side. "
        "The PendingDecision struct carries asset_id explicitly.",
        s["body"]))
    story.append(PageBreak())

    # ========== 7 RATIONALE + LOG SCHEMA ==========
    story.append(Paragraph("7. Rationale + decision-log schema", s["h1"]))
    story.append(Paragraph("7.1 Rationale format (self-tagging)", s["h2"]))
    story.append(Paragraph(
        "<b>Past incident:</b> v3 inherited v2's rationale string unchanged, causing "
        "downstream tooling (audit, watcher) to mis-attribute v3 fires as v2 fires. "
        "Fix in commit 74f7541 was to rewrite rationale at fire time. v2.1 follows "
        "the same pattern.",
        s["warn"]))
    story.append(Paragraph("v2 rationale (from spot_aware_v2.py:285):", s["body"]))
    story.append(code(
        "strategy=spot_aware_v2 mode=tier_restricted delta_bps=+5.02 p_win=0.400 "
        "ev=+0.1650 ttl=30s side=UP",
        s["code"]))
    story.append(Paragraph("v2.1 rationale (new format):", s["body"]))
    story.append(code(
        "strategy=spot_aware_v2_1 mode=kelly_multi delta_bps=+5.02 p_win=0.400 "
        "ev=+0.1650 ttl=30s side=UP kelly_f=0.357 bet_usd=89.50 "
        "bankroll=1006.01 fire_n=1/2",
        s["code"]))
    story.append(Paragraph(
        "Rewrite function (~15 LOC): regex-sub strategy= and mode= tokens, then "
        "append the new telemetry tokens. Word-boundary regex prevents accidental "
        "rewrites of substrings.",
        s["body"]))

    story.append(Paragraph("7.2 Decision-log JSONL additions", s["h2"]))
    story.append(Paragraph(
        "Add these structured fields to the `fired` record so downstream tools "
        "don't have to parse rationale:",
        s["body"]))
    story.append(_table([
        ["Field", "Type", "Source", "Backward-compat"],
        ["kelly_f", "float", "KellyConfig.last_kelly_f", "absent = legacy fire"],
        ["bet_usd", "float", "Decision.size_usd post-Kelly", "fallback to size_usd"],
        ["bankroll_at_fire", "float", "BankrollTracker.current()", "absent = legacy"],
        ["fire_n_in_window", "int", "1-indexed (1 or 2 for v2.1)", "absent = legacy=1"],
        ["multi_fire_cap", "int", "from env", "absent = legacy=1"],
    ], col_widths=[36*mm, 14*mm, 50*mm, 50*mm]))
    story.append(Paragraph(
        "scripts/four_day_audit.py and scripts/watch_first_v3_fire.py need no changes "
        "— they read rationale or kind=fired without these new fields.",
        s["small"]))
    story.append(PageBreak())

    # ========== 8 DASHBOARD ==========
    story.append(Paragraph("8. Dashboard integration", s["h1"]))
    story.append(Paragraph(
        "<b>Outcome of v2.1 shipping:</b> the v3 dashboard (FastAPI + React, port 8505) "
        "reflects v2.1 activity within seconds of the first fire.",
        s["body"]))

    story.append(Paragraph("8.1 Strategy badge (header)", s["h2"]))
    story.append(Paragraph(
        "The badge currently reads SPOT_AWARE (parsed from /api/state.strategy). It "
        "will update to SPOT_AWARE_V2_1 automatically — the dashboard reads from "
        "decision rationale via existing parser. No dashboard code change needed.",
        s["body"]))

    story.append(Paragraph("8.2 Phase label (stale 'PHASE 11.A.2')", s["h2"]))
    story.append(Paragraph(
        "The dashboard header still shows 'PHASE 11.A.2' (hardcoded in React). Phase H "
        "ships an update to display 'PHASE H' or 'PHASE H v2.1'. This is a 1-line "
        "change in the dashboard frontend, ride-along with H.5 deploy.",
        s["body"]))

    story.append(Paragraph("8.3 Decision tape (auto-updates)", s["h2"]))
    story.append(Paragraph(
        "Each v2.1 fire appears in the decision tape with side/tier/limit. Multi-fire "
        "means 2 entries per window. Operator sees this immediately.",
        s["body"]))

    story.append(Paragraph("8.4 New metric panels (Phase H follow-up)", s["h2"]))
    story.append(_table([
        ["Panel", "Source field", "Display"],
        ["Avg Kelly bet (24h)", "rationale.kelly_f", "mean × current bankroll"],
        ["Fires per window distribution", "fire_n_in_window", "histogram: 1 vs 2"],
        ["Compound factor", "bankroll/1000", "X.XXx since start"],
        ["Worst drawdown (rolling)", "bankroll min vs max in window", "DD %"],
    ], col_widths=[58*mm, 40*mm, 60*mm]))
    story.append(Paragraph(
        "These can ship in Phase I (dashboard observability) — not blocking v2.1 deploy.",
        s["small"]))

    story.append(Paragraph("8.5 Cumulative PnL curve continuity", s["h2"]))
    story.append(Paragraph(
        "v2.1's settled records flow through the same load_bankroll() pipeline. The "
        "cumulative PnL curve continues smoothly from current ~-$19 baseline. If "
        "v2.1 hits its Conservative trajectory, the curve bends sharply upward within "
        "days. Visible on /api/state.cumulative_pnl_series.",
        s["body"]))
    story.append(PageBreak())

    # ========== 9 TEST PLAN ==========
    story.append(Paragraph("9. Test plan — 18 tests", s["h1"]))
    story.append(Paragraph("9.1 KellyConfig (5 tests) — tests/strategies/test_kelly_config.py", s["h2"]))
    story.append(_table([
        ["Test", "Setup → Assertion"],
        ["test_kelly_f_zero_when_no_edge", "p_win=0.30, price=0.30 → 0.0"],
        ["test_kelly_f_classic", "p_win=0.55, price=0.30 → 0.357 (±1e-6)"],
        ["test_bet_clamps_to_max_abs", "bankroll=10000, f=0.4 → bet=500"],
        ["test_bet_clamps_to_max_pct", "bankroll=1000, f=0.5 → bet=100 (10%)"],
        ["test_bet_below_min_returns_zero", "bankroll=100, f=0.01 → bet=0 (below $1 floor)"],
    ], col_widths=[56*mm, 96*mm]))

    story.append(Paragraph("9.2 v2.1 filters (6 tests) — tests/strategies/test_spot_aware_v2_1.py", s["h2"]))
    story.append(_table([
        ["Test", "Setup → Assertion"],
        ["test_v2_1_name_marker", "strategy.name == 'spot_aware_v2_1'"],
        ["test_v2_1_rejects_delta_zero", "Δ=0 → on_event returns None"],
        ["test_v2_1_rejects_ev_in_bad_bucket", "EV ∈ [0.02, 0.05) → None"],
        ["test_v2_1_allows_30_50_with_low_delta", "tier 30-50%, |Δ|=2 → Decision"],
        ["test_v2_1_requires_5bps_for_70_85", "tier 70-85%, |Δ|=2 → None"],
        ["test_v2_1_inherits_tier_50_70_reject", "tier 50-70% → None (v2 inheritance)"],
    ], col_widths=[56*mm, 96*mm]))

    story.append(Paragraph("9.3 v2.1 Kelly + rationale (4 tests)", s["h2"]))
    story.append(_table([
        ["Test", "Setup → Assertion"],
        ["test_v2_1_kelly_sizes_replace_default", "Decision.size_usd ≠ DEFAULT (replaced)"],
        ["test_v2_1_rationale_self_tags", "'strategy=spot_aware_v2_1' in rationale"],
        ["test_v2_1_rationale_includes_kelly_metadata", "kelly_f= bet_usd= bankroll= fire_n= present"],
        ["test_v2_1_no_fire_when_bankroll_too_low", "bankroll=$1 → bet below min_bet → None"],
    ], col_widths=[56*mm, 96*mm]))

    story.append(Paragraph("9.4 Multi-fire (3 tests)", s["h2"]))
    story.append(_table([
        ["Test", "Setup → Assertion"],
        ["test_multi_fire_two_per_window", "drive two qualifying ticks → 2 Decisions"],
        ["test_multi_fire_blocked_at_cap", "drive third tick same window → None"],
        ["test_multi_fire_resets_on_window_boundary", "WindowBoundary open → counter reset"],
    ], col_widths=[56*mm, 96*mm]))

    story.append(Paragraph("9.5 BankrollTracker (no strategy) — tests/paper/test_bankroll_tracker.py", s["h2"]))
    story.append(_table([
        ["Test", "Setup → Assertion"],
        ["test_bankroll_starts_at_decision_10_default", "BankrollTracker() → current() == 1000"],
        ["test_bankroll_applies_settle", "apply_settle(+5) → current() == 1005"],
        ["test_bankroll_applies_correction", "apply_correction(orig=2, corr=-3) → delta=-5"],
        ["test_bankroll_recovers_from_jsonl", "feed N settled records → current matches sum"],
    ], col_widths=[56*mm, 96*mm]))
    story.append(Paragraph(
        "<b>Total: 22 tests.</b> The H.1 PDF said ~15; actual count is 22 once "
        "BankrollTracker is broken out as a separate testable unit.",
        s["small"]))
    story.append(PageBreak())

    # ========== 10 .envrc ==========
    story.append(Paragraph("10. .envrc spec", s["h1"]))
    story.append(Paragraph("10.1 Lines to add (above PHASE-F markers)", s["h2"]))
    story.append(code(
        "# PHASE-H 2026-05-13: v2.1 deploy — Kelly + multi-fire + filter changes\n"
        "# Rollback: cp .envrc.phase-H-pre-v2_1-backup-YYYYMMDD-HHMMSS .envrc\n"
        "# export STRATEGY=spot_aware_v2  (commented; was the PHASE-F-4 setting)\n"
        "export STRATEGY=spot_aware_v2_1\n"
        "export KELLY_MULT=0.10\n"
        "export MULTI_FIRE_CAP=2\n"
        "export PMB_STARTING_BANKROLL=1006.01  # current actual bankroll",
        s["code"]))
    story.append(Paragraph("10.2 Backup convention", s["h2"]))
    story.append(code(
        "BACKUP=.envrc.phase-H-pre-v2_1-backup-$(date +%Y%m%d-%H%M%S)\n"
        "cp .envrc $BACKUP",
        s["code"]))

    story.append(Paragraph("11. scripts/run_paper.py dispatch addition", s["h1"]))
    story.append(code(
        "# In _build_strategy, after the spot_aware_v3 branch:\n"
        "if name == 'spot_aware_v2_1':\n"
        "    from polymarket_bot.strategies.spot_aware_v2_1 import SpotAwareStrategyV2_1\n"
        "    from polymarket_bot.strategies.kelly_config import KellyConfig\n"
        "    kelly = KellyConfig(\n"
        "        kelly_mult=_env_float('KELLY_MULT', 0.10) or 0.10,\n"
        "        max_bet_abs=_env_float('KELLY_MAX_BET_ABS', 500.0) or 500.0,\n"
        "    )\n"
        "    multi_fire_cap = int(_env_float('MULTI_FIRE_CAP', 2) or 2)\n"
        "    # bankroll_getter wired in main() after PaperRunner constructed\n"
        "    return SpotAwareStrategyV2_1(\n"
        "        priors=load_priors(),\n"
        "        bankroll_getter=lambda: 1000.0,  # PLACEHOLDER — rebound in main()\n"
        "        kelly=kelly,\n"
        "        multi_fire_cap=multi_fire_cap,\n"
        "    )\n"
        "\n"
        "# In main(), after PaperRunner is constructed:\n"
        "if isinstance(strategy, SpotAwareStrategyV2_1):\n"
        "    strategy._bankroll_getter = runner._bankroll.current",
        s["code"]))
    story.append(PageBreak())

    # ========== 13 DEPLOYMENT ==========
    story.append(Paragraph("12. Deployment runbook (H.5)", s["h1"]))
    story.append(Paragraph("Exact SSH command sequence (model on PHASE-F-4 today):", s["body"]))
    story.append(code(
        "ssh -i $HOME/Downloads/LightsailDefaultKey-eu-west-1.pem -p 2222 ops@108.132.51.116 'set -e\n"
        "cd /home/ops/polymarket-5m-bot\n"
        "\n"
        "# 0. Pre-pull verify\n"
        "git rev-parse --short HEAD\n"
        "systemctl is-active bot-staging.service\n"
        "\n"
        "# 1. Pull latest with v2.1 code\n"
        "git pull --ff-only origin claude/jovial-hermann-7e103f\n"
        "git rev-parse --short HEAD  # confirm expected commit\n"
        "\n"
        "# 2. Backup .envrc (per feedback_vps_deploy_verify_late memory)\n"
        "BACKUP=.envrc.phase-H-pre-v2_1-backup-$(date +%Y%m%d-%H%M%S)\n"
        "cp .envrc $BACKUP\n"
        "echo \"Backup: $BACKUP\"\n"
        "\n"
        "# 3. Apply .envrc edits via sed (atomic; preserves comments)\n"
        "sed -i.tmp -E \"s|^export STRATEGY=spot_aware_v2\\$|# PHASE-H 2026-05-13: v2.1 deploy\\n# export STRATEGY=spot_aware_v2\\nexport STRATEGY=spot_aware_v2_1\\nexport KELLY_MULT=0.10\\nexport MULTI_FIRE_CAP=2\\nexport PMB_STARTING_BANKROLL=1006.01|\" .envrc\n"
        "rm -f .envrc.tmp\n"
        "\n"
        "# 4. Capture DEPLOY_TS_5 (per feedback_vps_timestamp_arithmetic memory —\n"
        "#    NEVER compute from systemctl text; ALWAYS read $(date +%s) on VPS)\n"
        "DEPLOY_TS_5=$(date +%s)\n"
        "echo \"DEPLOY_TS_UNIX_5=${DEPLOY_TS_5}\"\n"
        "\n"
        "# 5. Restart\n"
        "sudo systemctl restart bot-staging.service\n"
        "sleep 3\n"
        "systemctl show bot-staging.service -p MainPID,ActiveEnterTimestamp,NRestarts,ActiveState\n"
        "\n"
        "# 6. Immediate sanity (within 5s of restart)\n"
        "systemctl is-active bot-staging.service\n"
        "journalctl -u bot-staging.service --since \"@${DEPLOY_TS_5}\" --no-pager | grep -E \"(active strategy|kelly|multi.fire|bankroll)\" | head -5\n"
        "'",
        s["code"]))
    story.append(PageBreak())

    # ========== 14 VERIFY ==========
    story.append(Paragraph("13. Verification gates", s["h1"]))
    story.append(_table([
        ["When", "What to check", "Pass criteria", "Failure → "],
        ["+5 min",
         "systemctl active, no errors, startup log has 'active strategy: spot_aware_v2_1'",
         "all 3 pass",
         "ROLLBACK"],
        ["+5 min",
         "first fire log line has kelly_f= and bet_usd= and fire_n=",
         "rationale fully self-tagged",
         "investigate rationale rewrite"],
        ["+30 min",
         "no queue_overflow / dropped_records log lines; Anthropic calls = 0",
         "0 / 0",
         "investigate I/O backpressure"],
        ["+30 min",
         "bankroll tracker matches dashboard /api/state.bankroll.current_usd (±$0.50)",
         "convergence",
         "BankrollTracker bug"],
        ["+24 h",
         "fires/day in range [16, 50]; multi-fire windows present (fire_n=2 records)",
         "in range",
         "EXTEND or investigate"],
        ["+24 h",
         "WR ≥ 47% on settled n ≥ 30 (early signal)",
         "WR ≥ 47%",
         "EXTEND"],
        ["+24 h",
         "daily PnL within [-$15, +$50]",
         "no extreme",
         "ROLLBACK if &lt; -$30"],
        ["+7 d",
         "Soak gate per Section 14",
         "see Section 14",
         "per Section 14"],
    ], col_widths=[16*mm, 56*mm, 36*mm, 38*mm]))
    story.append(PageBreak())

    # ========== 15 PAST INCIDENT DEFENSE ==========
    story.append(Paragraph("14. Past-incident defense matrix", s["h1"]))
    story.append(Paragraph(
        "Every confirmed bug class from the bot's history mapped to v2.1's specific defense:",
        s["body"]))
    story.append(_table([
        ["Past incident", "How v2.1 avoids it"],
        ["v3 rationale-inheritance (today)",
         "v2.1 rewrites rationale at fire time, self-tags 'strategy=spot_aware_v2_1'"],
        ["per-side state pollution (16.B.4)",
         "v2.1 tracks _fires_this_window by window_ts; PendingDecision carries asset_id"],
        ["LLM queue overflow (2026-05-10)",
         "v2.1 has NO async-await on external API in fire path (no LLM)"],
        ["Instant-settle queue overflow (5/9)",
         "v2.1 adds no inline awaits; BankrollTracker.apply_settle is sync"],
        ["FD orphan dashboard incident (5/9)",
         "v2.1 doesn't write to decision log; PaperRunner's existing inode-stable append unchanged"],
        ["Phantom-fill (Phase 11.A)",
         "v2.1 inherits v2's tier rejection; settled_correction overlay continues to work"],
        ["Chainlink-vs-polymarket resolve (5/10)",
         "v2.1 doesn't touch resolution; PaperRunner's gamma retry + correction overlay unchanged"],
        ["Wide_fire ensemble negative selection (5/11)",
         "v2.1 doesn't use LLM ensemble; Phase F cut intact"],
        ["Cross-restart double-fire (5/10)",
         "v2.1 multi-fire CAP scoped to single window_ts; restart resets _fires_this_window"],
        ["VPS timestamp drift (5/12)",
         "Deployment runbook uses VPS $(date +%s); no mental arithmetic"],
        ["Phase 15.5 truth-pass break",
         "settled_correction continues to work; BankrollTracker.apply_correction wired"],
        ["pending_decision singular invariant",
         "_RunnerState refactor to pending_decisions: list; backward-compat property"],
        ["OSError on disk-full kills runner",
         "Existing try/except in _on_decision preserved"],
        ["Aggressive-mode high variance",
         "Kelly bet caps + ROLLBACK gate at WR&lt;45% over 48h"],
    ], col_widths=[64*mm, 90*mm]))
    story.append(PageBreak())

    # ========== 15 ROLLBACK ==========
    story.append(Paragraph("15. Rollback decision tree", s["h1"]))
    story.append(Paragraph("15.1 ROLLBACK now (within H.5 hour)", s["h2"]))
    story.append(Paragraph(
        "Triggers: service fails to start, startup log errors, queue overflow, "
        "rationale missing self-tag, bankroll-getter raises.",
        s["body"]))
    story.append(code(
        "ssh ... 'cd /home/ops/polymarket-5m-bot &amp;&amp; \\\n"
        "  cp .envrc.phase-H-pre-v2_1-backup-YYYYMMDD-HHMMSS .envrc &amp;&amp; \\\n"
        "  sudo systemctl restart bot-staging.service'",
        s["code"]))

    story.append(Paragraph("15.2 ROLLBACK over soak (H.6 trigger)", s["h2"]))
    story.append(Paragraph(
        "Triggers (any of):<br/>"
        "• WR &lt; 45% over 48h continuous<br/>"
        "• daily_pnl &lt; -$30 on any single day<br/>"
        "• bankroll drops below $500 (50% drawdown from start)<br/>"
        "• 3 consecutive losing days (Bonferroni-corrected α ≈ 1.5%)",
        s["body"]))

    story.append(Paragraph("15.3 EXTEND (re-soak)", s["h2"]))
    story.append(Paragraph(
        "Triggers: WR in [45%, 52%), or fires/day in [10, 30), or daily_pnl in [-30, -10) "
        "on worst day. Action: keep v2.1 running another 7 days, re-audit.",
        s["body"]))

    story.append(Paragraph("15.4 PROMOTE", s["h2"]))
    story.append(Paragraph(
        "Triggers (all of):<br/>"
        "• WR ≥ 52% on n ≥ 100 settled fires<br/>"
        "• daily_pnl_min ≥ -$10 over the 7-day window<br/>"
        "• fires/day ≥ 30 (multi-fire 2× expected)<br/>"
        "• queue_overflow_incidents == 0<br/>"
        "• bankroll ≥ $1,500 (50% gain) — sanity check<br/><br/>"
        "Action: schedule Phase I (live trading prep / readiness review).",
        s["body"]))
    story.append(PageBreak())

    # ========== 17 OPEN Q ==========
    story.append(Paragraph("16. Open questions for operator (Q1-Q5)", s["h1"]))
    story.append(_table([
        ["Q", "Question", "Options", "Default (this spec)"],
        ["Q1", "Hour-of-day gate (S1)?",
         "YES skip 5/14/23 UTC · NO no gate",
         "NO (sample too thin)"],
        ["Q2", "Regime gate (W3)?",
         "A no gate · B half-Kelly on chop · C trending-only",
         "A no gate (start simple)"],
        ["Q3", "Multi-fire cap?",
         "2 / 3 per window",
         "2 (conservative)"],
        ["Q4", "Kelly multiplier?",
         "0.10 / 0.25",
         "0.10 (smoother)"],
        ["Q5", "Live-trading promotion threshold?",
         "$2k / $5k / $10k",
         "$2k (locked decision #12)"],
    ], col_widths=[10*mm, 50*mm, 50*mm, 40*mm]))
    story.append(Paragraph(
        "If operator approves all defaults: ship code as specified. If operator overrides "
        "any: only env vars change (KELLY_MULT, MULTI_FIRE_CAP). Code is parameterized; no "
        "logic changes needed.",
        s["body"]))
    story.append(PageBreak())

    # ========== 18 HONEST ==========
    story.append(Paragraph("17. Honest pushback — engineering risks", s["h1"]))
    story.append(Paragraph("17.1 Code paths that need careful review", s["h2"]))
    story.append(Paragraph(
        "• <b>BankrollTracker recovery from JSONL on startup</b>: must handle "
        "settled_correction records (Phase 15.5 overlay). Test coverage critical.<br/>"
        "• <b>PendingDecision list refactor in PaperRunner</b>: pending_decision property "
        "must keep v1/v2 compatibility. Run existing v2 test suite as regression.<br/>"
        "• <b>Multi-fire settle ordering</b>: if window 1's 2 fires settle out of order, "
        "BankrollTracker must still converge. Test with synthetic settle order.",
        s["body"]))

    story.append(Paragraph("17.2 Race conditions to test under load", s["h2"]))
    story.append(Paragraph(
        "Per <b>feedback_test_under_load</b>: async I/O in hot path needs a queue-doesn't-overflow "
        "test. v2.1 adds no async I/O (Kelly is sync), but multi-fire DOUBLES fire-rate "
        "and thus DOUBLES log-write rate. Verify DecisionLog write throughput at 50 fires/day "
        "(no concern), and confirm no compound effect.",
        s["body"]))

    story.append(Paragraph("17.3 What we DON'T know yet", s["h2"]))
    story.append(Paragraph(
        "• Does the v_next 30-50%×|Δ|&lt;5 cell generalize beyond the 5-day backtest? "
        "Phase G honest-pushback covers this. v2.1's ROLLBACK gate is the safety net.<br/>"
        "• Does Polymarket retail liquidity actually support $500 bets at 30-50% tier prices? "
        "May be lower. Monitor fill rate; if it drops, lower max_bet_abs.<br/>"
        "• Does multi-fire 2× actually mean 2× fires/day, or do the signals correlate and "
        "the second fire is rare? First 24h of data will tell.",
        s["body"]))

    story.append(Paragraph("17.4 The big risk", s["h2"]))
    story.append(Paragraph(
        "<b>Kelly compounding amplifies BOTH expected return AND variance.</b> Phase G "
        "Scenario C showed 97% of paths hit catastrophic drawdown at 50% WR (regression). "
        "If the v_next backtest WR (58%) was sample bias, v2.1 with Kelly 0.10× × multi-fire "
        "2× may bleed bankroll fast.",
        s["warn"]))
    story.append(Paragraph(
        "<b>Mitigations baked in:</b> 0.10× (not 0.25×) Kelly, $500 absolute bet cap, "
        "multi-fire 2× (not 3×), ROLLBACK at WR&lt;45% over 48h. Combined: max ~6.4% of "
        "bankroll deployed per window (2 × 0.10 × 0.357 max-edge). Sane.",
        s["body"]))
    story.append(PageBreak())

    # ========== SIGN-OFF ==========
    story.append(Paragraph("18. Sign-off checklist (operator → assistant)", s["h1"]))
    story.append(Paragraph("Before Phase H.2 code work begins, operator confirms:", s["body"]))
    story.append(Paragraph(
        "[&nbsp;&nbsp;] Section 3 — class definition acceptable<br/>"
        "[&nbsp;&nbsp;] Section 4 — KellyConfig fields + defaults OK<br/>"
        "[&nbsp;&nbsp;] Section 5 — BankrollTracker in PaperRunner OK<br/>"
        "[&nbsp;&nbsp;] Section 6 — multi-fire PaperRunner refactor OK<br/>"
        "[&nbsp;&nbsp;] Section 7 — rationale format + new JSONL fields OK<br/>"
        "[&nbsp;&nbsp;] Section 9 — 22-test surface OK<br/>"
        "[&nbsp;&nbsp;] Q1: NO hour gate · Q2: NO regime gate · Q3: cap=2 · Q4: Kelly 0.10× · Q5: $2k promote<br/>"
        "[&nbsp;&nbsp;] Section 14 — past-incident defense matrix understood<br/>"
        "[&nbsp;&nbsp;] Section 15 — ROLLBACK criteria acceptable",
        s["body"]))
    story.append(Spacer(0, 6))
    story.append(Paragraph(
        "Sign-off via: reply 'go phase-H.2' OR 'go with overrides: Q1=YES Q3=3 ...'",
        s["body"]))

    story.append(Spacer(0, 12))
    story.append(HRFlowable(width="80%", thickness=0.5, color=LINE, hAlign="CENTER"))
    story.append(Spacer(0, 4))
    story.append(Paragraph(
        "End of Phase H final implementation spec · 2026-05-13 · 18 sections · "
        "22 tests · 14 past-incident defenses · ~30 pages",
        s["small"]))
    story.append(Paragraph(
        "Source prompt: phase-prompts/phase-H-FINAL-spec-2026-05-13.txt<br/>"
        "Companion docs: PHASE_G_EDGE_DISCOVERY.pdf, PHASE_H_v2_1_IMPLEMENTATION.pdf",
        s["small"]))

    doc.build(story)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024}K)")

    shutil.copy(OUT, DESKTOP)
    print(f"copied to {DESKTOP}")


if __name__ == "__main__":
    build()
