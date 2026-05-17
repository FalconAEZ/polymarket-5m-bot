"""Phase N forensic audit — data-first investigation of the 2026-05-15 → 2026-05-17 bleed.

Reads decisions-resolved/*.jsonl (truth-corrected PnL), joins fires with their
settled / settled_correction records, parses M.* annotations (regime=, imbalance=)
from rationale strings, and emits per-section rollups for N.1 (peak-to-floor) and
N.2 (tier 30-50% deep dive). Intentionally read-only: never writes to state/ or to
any bot-runtime path.

Usage:
    uv run python -u scripts/research/phase_n_forensic_audit.py \
        --data-dir /tmp/phaseN_data/state \
        --out runbooks/research/phase-N-forensic-output-2026-05-17.txt
"""

# ruff: noqa: RUF001, RUF002, RUF003, S108, F841, RUF059

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Inlined from src/polymarket_bot/tiers.py — we don't want to depend on the bot
# import-graph from a research script.
PRICE_TIER_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.15, "<15%"),
    (0.15, 0.30, "15-30%"),
    (0.30, 0.50, "30-50%"),
    (0.50, 0.70, "50-70%"),
    (0.70, 0.85, "70-85%"),
    (0.85, 1.01, "85-100%"),
)


def tier_label_for_price(price: float | None) -> str:
    if price is None:
        return "—"
    for lo, hi, label in PRICE_TIER_BUCKETS:
        if lo <= price < hi:
            return label
    return "—"


# ─── rationale parsing ────────────────────────────────────────────────────────

# Pattern for "key=value" tokens in rationale strings. Values are non-whitespace.
_KV_RE = re.compile(r"(\w+)=([^\s]+)")


def parse_rationale(rat: str | None) -> dict[str, str]:
    if not rat:
        return {}
    return dict(_KV_RE.findall(rat))


def _f(v: str | None) -> float | None:
    if v is None:
        return None
    try:
        return float(v.rstrip("%"))
    except ValueError:
        return None


# ─── data model ───────────────────────────────────────────────────────────────


@dataclass
class Fire:
    decision_id: str
    decision_ts_ns: int
    window_ts: int
    side: str
    size_usd: float
    price_limit: float
    rationale: str
    snapshot: dict
    # parsed annotations
    strategy: str | None = None
    mode: str | None = None
    delta_bps: float | None = None
    p_win: float | None = None
    ev: float | None = None
    kelly_f: float | None = None
    bet_usd: float | None = None
    bankroll: float | None = None
    fire_n: str | None = None
    regime: str | None = None  # M.1a v0 annotation
    imbalance: str | None = None  # M.2 v0 annotation
    # joined later
    pnl_usd: float | None = None
    resolution: str | None = None
    resolution_source: str | None = None
    was_filled: bool | None = None  # from fill_at_settle non-null OR pnl != 0
    # derived
    tier: str = "—"
    won: bool | None = None  # outcome resolution == side
    abs_delta_bps: float | None = None


@dataclass
class Stats:
    n: int = 0
    n_won: int = 0
    pnl_total: float = 0.0
    pnl_list: list[float] = field(default_factory=list)

    def add(self, f: Fire) -> None:
        if f.pnl_usd is None:
            return
        self.n += 1
        if f.won:
            self.n_won += 1
        self.pnl_total += f.pnl_usd
        self.pnl_list.append(f.pnl_usd)

    @property
    def wr(self) -> float:
        return self.n_won / self.n if self.n else 0.0

    @property
    def per_trade(self) -> float:
        return self.pnl_total / self.n if self.n else 0.0


# ─── data loading ─────────────────────────────────────────────────────────────


def load_data(data_dir: Path) -> tuple[list[Fire], dict[str, int]]:
    """Load all fires + settlements; return joined Fire list and a kind-count dict."""
    resolved_dir = data_dir / "decisions-resolved"

    fires_by_id: dict[str, Fire] = {}
    initial_by_id: dict[str, dict] = {}
    correction_by_id: dict[str, dict] = {}
    counts: dict[str, int] = defaultdict(int)

    files = sorted(resolved_dir.glob("2026-05-*.jsonl"))
    for fp in files:
        with fp.open() as f:
            for line in f:
                d = json.loads(line)
                k = d.get("kind", "?")
                counts[k] += 1
                if k == "fired":
                    kv = parse_rationale(d.get("rationale", ""))
                    snap = d.get("snapshot") or {}
                    price = snap.get("best_ask") or d.get("price_limit")
                    db = _f(kv.get("delta_bps"))
                    fire = Fire(
                        decision_id=d["decision_id"],
                        decision_ts_ns=d["decision_ts_ns"],
                        window_ts=d["window_ts"],
                        side=d["side"],
                        size_usd=d["size_usd"],
                        price_limit=d["price_limit"],
                        rationale=d.get("rationale", ""),
                        snapshot=snap,
                        strategy=kv.get("strategy"),
                        mode=kv.get("mode"),
                        delta_bps=db,
                        p_win=_f(kv.get("p_win")),
                        ev=_f(kv.get("ev")),
                        kelly_f=_f(kv.get("kelly_f")),
                        bet_usd=_f(kv.get("bet_usd")),
                        bankroll=_f(kv.get("bankroll")),
                        fire_n=kv.get("fire_n"),
                        regime=kv.get("regime"),
                        imbalance=kv.get("imbalance"),
                        tier=tier_label_for_price(price),
                        abs_delta_bps=abs(db) if db is not None else None,
                    )
                    fires_by_id[fire.decision_id] = fire
                elif k == "settled":
                    initial_by_id[d["decision_id"]] = d
                elif k == "settled_correction":
                    correction_by_id[d["decision_id"]] = d

    # Join: prefer correction over initial.
    for fid, fire in fires_by_id.items():
        if fid in correction_by_id:
            c = correction_by_id[fid]
            fire.pnl_usd = c["corrected_pnl_usd"]
            fire.resolution = c["corrected_resolution"]
            fire.resolution_source = c.get("resolution_source", "post-hoc")
            fire.was_filled = c.get("fill_at_settle") is not None
        elif fid in initial_by_id:
            s = initial_by_id[fid]
            fire.pnl_usd = s.get("pnl_usd", 0.0)
            fire.resolution = s.get("resolution")
            fire.resolution_source = s.get("resolution_source")
            fire.was_filled = (
                s.get("fill_at_settle") is not None or (s.get("pnl_usd") or 0.0) != 0.0
            )
        # else: orphan fire (no settlement yet). Skip.
        if fire.pnl_usd is not None and fire.resolution is not None:
            fire.won = fire.resolution == fire.side

    fires = sorted(fires_by_id.values(), key=lambda f: f.decision_ts_ns)
    return fires, dict(counts)


# ─── presentation helpers ─────────────────────────────────────────────────────


def fmt_ts(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1e9, tz=UTC).strftime("%Y-%m-%d %H:%M:%SZ")


def fmt_row(label: str, s: Stats, w_label: int = 26) -> str:
    return (
        f"  {label:<{w_label}}  n={s.n:>4}  WR={s.wr * 100:5.1f}%  "
        f"$/tr={s.per_trade:+6.2f}  PnL={s.pnl_total:+8.2f}"
    )


# ─── sections ─────────────────────────────────────────────────────────────────


def section_header(out: list[str], title: str) -> None:
    out.append("")
    out.append("=" * 80)
    out.append(title)
    out.append("=" * 80)


def section_n0_dataset(out: list[str], fires: list[Fire], counts: dict[str, int]) -> None:
    section_header(out, "N.0 — DATASET INVENTORY")
    out.append(f"  Record kinds: {dict(counts)}")
    settled = [f for f in fires if f.pnl_usd is not None]
    filled = [f for f in settled if f.was_filled]
    orphan = [f for f in fires if f.pnl_usd is None]
    out.append(f"  Fires total:            {len(fires)}")
    out.append(f"  Fires settled (truth):  {len(settled)}")
    out.append(f"  Fires settled & filled: {len(filled)}  (zero-pnl skipped)")
    out.append(f"  Orphan fires (no settle): {len(orphan)}")
    if settled:
        start = fmt_ts(settled[0].decision_ts_ns)
        end = fmt_ts(settled[-1].decision_ts_ns)
        out.append(f"  Window: {start}  →  {end}")
    # Strategy / mode mix
    strat = defaultdict(int)
    mode = defaultdict(int)
    for f in settled:
        strat[f.strategy or "?"] += 1
        mode[f.mode or "?"] += 1
    out.append(f"  Strategy mix: {dict(strat)}")
    out.append(f"  Mode mix:     {dict(mode)}")
    # Annotation availability
    n_regime = sum(1 for f in settled if f.regime)
    n_imb = sum(1 for f in settled if f.imbalance)
    out.append(f"  Annotated with regime=:    {n_regime} / {len(settled)}")
    out.append(f"  Annotated with imbalance=: {n_imb} / {len(settled)}")
    if n_regime:
        regimes = defaultdict(int)
        for f in settled:
            if f.regime:
                regimes[f.regime] += 1
        out.append(f"    Regime label mix: {dict(regimes)}")
    if n_imb:
        imbalances = defaultdict(int)
        for f in settled:
            if f.imbalance:
                imbalances[f.imbalance] += 1
        out.append(f"    Imbalance label mix: {dict(imbalances)}")


def compute_cum_pnl(fires: list[Fire]) -> list[tuple[Fire, float]]:
    cum = 0.0
    out: list[tuple[Fire, float]] = []
    for f in fires:
        if f.pnl_usd is None:
            continue
        cum += f.pnl_usd
        out.append((f, cum))
    return out


def section_n1_peak(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "N.1 — PEAK-TO-FLOOR FORENSIC")
    traj = compute_cum_pnl(fires)
    if not traj:
        out.append("  no settled fires — abort")
        return

    # Peak: max cum-PnL ever achieved (and the fire that pushed us there).
    peak_idx, (peak_fire, peak_cum) = max(enumerate(traj), key=lambda kv: kv[1][1])
    floor_idx, (floor_fire, floor_cum) = min(enumerate(traj), key=lambda kv: kv[1][1])
    final_fire, final_cum = traj[-1]

    out.append(
        f"  PEAK    cum-PnL = {peak_cum:+8.2f} at {fmt_ts(peak_fire.decision_ts_ns)} "
        f"(fire #{peak_idx + 1} of {len(traj)})"
    )
    out.append(
        f"  FLOOR   cum-PnL = {floor_cum:+8.2f} at {fmt_ts(floor_fire.decision_ts_ns)} "
        f"(fire #{floor_idx + 1})"
    )
    out.append(f"  FINAL   cum-PnL = {final_cum:+8.2f} at {fmt_ts(final_fire.decision_ts_ns)}")
    out.append(f"  Peak→final swing: {final_cum - peak_cum:+8.2f}")
    out.append("")
    out.append("  Peak fire detail:")
    out.append(f"    decision_id   = {peak_fire.decision_id}")
    out.append(f"    side          = {peak_fire.side}")
    out.append(f"    price_limit   = {peak_fire.price_limit}")
    out.append(f"    tier          = {peak_fire.tier}")
    out.append(f"    delta_bps     = {peak_fire.delta_bps}")
    out.append(f"    bet_usd       = {peak_fire.bet_usd}")
    out.append(f"    bankroll(pre) = {peak_fire.bankroll}")
    out.append(f"    pnl_usd       = {peak_fire.pnl_usd:+.2f}")
    out.append(f"    rationale     = {peak_fire.rationale[:220]}")

    # First post-peak fire that lost
    first_loss = None
    for i in range(peak_idx + 1, len(traj)):
        f, _ = traj[i]
        if f.pnl_usd is not None and f.pnl_usd < 0:
            first_loss = (i, f)
            break
    if first_loss:
        idx, f = first_loss
        out.append("")
        out.append(f"  FIRST POST-PEAK LOSS  (#{idx - peak_idx} after peak)")
        out.append(f"    ts            = {fmt_ts(f.decision_ts_ns)}")
        out.append(f"    side / tier   = {f.side} / {f.tier}")
        out.append(f"    delta_bps     = {f.delta_bps}   p_win = {f.p_win}   ev = {f.ev}")
        out.append(f"    bet_usd       = {f.bet_usd}     pnl = {f.pnl_usd:+.2f}")
        out.append(f"    rationale     = {f.rationale[:200]}")

    # Streak between peak and first loss (winners post-peak)
    winners_before_first_loss = 0
    for i in range(peak_idx + 1, len(traj)):
        f, _ = traj[i]
        if f.pnl_usd is None or f.pnl_usd < 0:
            break
        winners_before_first_loss += 1
    out.append(f"  Wins between peak and first loss: {winners_before_first_loss}")

    # 30-min rollups for 6h post-peak
    out.append("")
    out.append("  Per 30-min rollup post-peak (6h forward):")
    out.append("    window-end UTC          n   WR    $/tr     PnL    cumPnL")
    peak_ts = peak_fire.decision_ts_ns
    horizon_ns = 6 * 3600 * 10**9
    bucket_ns = 30 * 60 * 10**9
    buckets: dict[int, Stats] = defaultdict(Stats)
    for f, _ in traj:
        if f.decision_ts_ns <= peak_ts:
            continue
        delta = f.decision_ts_ns - peak_ts
        if delta > horizon_ns:
            break
        b = delta // bucket_ns
        buckets[b].add(f)
    running = peak_cum
    for b in sorted(buckets):
        end_ns = peak_ts + (b + 1) * bucket_ns
        s = buckets[b]
        running += s.pnl_total
        out.append(
            f"    {datetime.fromtimestamp(end_ns / 1e9, tz=UTC).strftime('%m-%d %H:%M')}  "
            f"{s.n:>3}  {s.wr * 100:5.1f}%  {s.per_trade:+6.2f}  {s.pnl_total:+7.2f}  "
            f"{running:+8.2f}"
        )

    # Pre-peak vs post-peak (6h windows)
    pre_window = [f for f, _ in traj if peak_ts - horizon_ns <= f.decision_ts_ns <= peak_ts]
    post_window = [f for f, _ in traj if peak_ts < f.decision_ts_ns <= peak_ts + horizon_ns]
    out.append("")
    out.append("  Pre-peak (6h) vs post-peak (6h) comparison:")
    out.append("    metric           pre-peak    post-peak")
    s_pre = Stats()
    s_post = Stats()
    for f in pre_window:
        s_pre.add(f)
    for f in post_window:
        s_post.add(f)
    out.append(f"    n                {s_pre.n:>8}   {s_post.n:>10}")
    out.append(f"    WR               {s_pre.wr * 100:7.1f}%  {s_post.wr * 100:9.1f}%")
    out.append(f"    $/tr             {s_pre.per_trade:+8.2f}   {s_post.per_trade:+10.2f}")
    out.append(f"    PnL              {s_pre.pnl_total:+8.2f}   {s_post.pnl_total:+10.2f}")
    avg_abs_delta_pre = sum(f.abs_delta_bps or 0 for f in pre_window) / max(1, len(pre_window))
    avg_abs_delta_post = sum(f.abs_delta_bps or 0 for f in post_window) / max(1, len(post_window))
    out.append(f"    avg |Δbps|       {avg_abs_delta_pre:8.2f}   {avg_abs_delta_post:10.2f}")
    avg_ask_pre = sum(f.price_limit for f in pre_window) / max(1, len(pre_window))
    avg_ask_post = sum(f.price_limit for f in post_window) / max(1, len(post_window))
    out.append(f"    avg best_ask     {avg_ask_pre:8.3f}   {avg_ask_post:10.3f}")
    up_pre = sum(1 for f in pre_window if f.side == "UP") / max(1, len(pre_window))
    up_post = sum(1 for f in post_window if f.side == "UP") / max(1, len(post_window))
    out.append(f"    UP-share         {up_pre * 100:7.1f}%  {up_post * 100:9.1f}%")
    # tier mix
    out.append("    tier mix:")
    tiers_pre = defaultdict(int)
    tiers_post = defaultdict(int)
    for f in pre_window:
        tiers_pre[f.tier] += 1
    for f in post_window:
        tiers_post[f.tier] += 1
    all_tiers = sorted(set(tiers_pre) | set(tiers_post))
    for t in all_tiers:
        out.append(f"      {t:<10}    {tiers_pre[t]:>6}   {tiers_post[t]:>10}")

    # Cum-PnL daily timeline (every day's open / close cum-PnL + n)
    out.append("")
    out.append("  Daily timeline:")
    out.append("    UTC date    n  daily-PnL  cumPnL-EOD  WR-day")
    by_day: dict[str, list[Fire]] = defaultdict(list)
    for f, _ in traj:
        day = fmt_ts(f.decision_ts_ns).split(" ")[0]
        by_day[day].append(f)
    cum = 0.0
    for day in sorted(by_day):
        s = Stats()
        for f in by_day[day]:
            s.add(f)
        cum += s.pnl_total
        out.append(f"    {day}  {s.n:>3}  {s.pnl_total:+8.2f}   {cum:+8.2f}   {s.wr * 100:5.1f}%")


def section_n2_tier_30_50(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "N.2 — TIER 30-50% DEEP DIVE")
    settled = [f for f in fires if f.pnl_usd is not None]
    tier_fires = [f for f in settled if f.tier == "30-50%"]
    other_fires = [f for f in settled if f.tier != "30-50%"]

    s_all = Stats()
    for f in settled:
        s_all.add(f)
    s_tier = Stats()
    for f in tier_fires:
        s_tier.add(f)
    s_other = Stats()
    for f in other_fires:
        s_other.add(f)

    out.append(f"  Total settled fires: {s_all.n}")
    out.append(fmt_row("ALL fires", s_all))
    out.append(fmt_row("tier 30-50%", s_tier))
    out.append(fmt_row("OTHER tiers (vs 30-50%)", s_other))

    # Per-tier table for context
    out.append("")
    out.append("  Per-tier breakdown (all 5 days):")
    by_tier: dict[str, Stats] = defaultdict(Stats)
    for f in settled:
        by_tier[f.tier].add(f)
    for t in ("<15%", "15-30%", "30-50%", "50-70%", "70-85%", "85-100%", "—"):
        if by_tier[t].n:
            out.append(fmt_row(f"tier {t}", by_tier[t]))

    # Per-day tier 30-50%
    out.append("")
    out.append("  Tier 30-50% per UTC day:")
    by_day: dict[str, Stats] = defaultdict(Stats)
    for f in tier_fires:
        day = fmt_ts(f.decision_ts_ns).split(" ")[0]
        by_day[day].add(f)
    for day in sorted(by_day):
        out.append(fmt_row(f"  {day}", by_day[day]))

    # Per-side
    out.append("")
    out.append("  Tier 30-50% per side:")
    by_side: dict[str, Stats] = defaultdict(Stats)
    for f in tier_fires:
        by_side[f.side].add(f)
    for side in ("UP", "DOWN"):
        out.append(fmt_row(f"  side={side}", by_side[side]))

    # Per-|Δ| bucket
    out.append("")
    out.append("  Tier 30-50% per |Δ| bucket:")
    buckets = [
        (0, 2.5, "0-2.5"),
        (2.5, 5, "2.5-5"),
        (5, 10, "5-10"),
        (10, 20, "10-20"),
        (20, 1e9, "20+"),
    ]
    by_bucket: dict[str, Stats] = defaultdict(Stats)
    for f in tier_fires:
        ad = f.abs_delta_bps
        if ad is None:
            by_bucket["?"].add(f)
            continue
        for lo, hi, lbl in buckets:
            if lo <= ad < hi:
                by_bucket[lbl].add(f)
                break
    for _, _, lbl in buckets:
        if by_bucket[lbl].n:
            out.append(fmt_row(f"  |Δbps| {lbl}", by_bucket[lbl]))

    # CH3 cell (tier 30-50% × |Δ|<5) and surviving winner (× |Δ|≥5)
    ch3 = [f for f in tier_fires if f.abs_delta_bps is not None and f.abs_delta_bps < 5]
    surv = [f for f in tier_fires if f.abs_delta_bps is not None and f.abs_delta_bps >= 5]
    s_ch3 = Stats()
    for f in ch3:
        s_ch3.add(f)
    s_surv = Stats()
    for f in surv:
        s_surv.add(f)
    out.append("")
    out.append("  CH3 cell (tier 30-50% × |Δ|<5) — Phase G winning cell:")
    out.append(fmt_row("  CH3 (5 days)", s_ch3))
    out.append("")
    out.append("  Surviving winner (tier 30-50% × |Δ|≥5) — Phase L audit:")
    out.append(fmt_row("  SURV (5 days)", s_surv))

    # Pre/post-peak split for tier 30-50%
    traj = compute_cum_pnl(fires)
    if traj:
        peak_idx, (peak_fire, _) = max(enumerate(traj), key=lambda kv: kv[1][1])
        peak_ts = peak_fire.decision_ts_ns
        pre = [f for f in tier_fires if f.decision_ts_ns <= peak_ts]
        post = [f for f in tier_fires if f.decision_ts_ns > peak_ts]
        s_pre = Stats()
        s_post = Stats()
        for f in pre:
            s_pre.add(f)
        for f in post:
            s_post.add(f)
        out.append("")
        out.append("  Tier 30-50% pre-peak vs post-peak:")
        out.append(fmt_row("  pre-peak", s_pre))
        out.append(fmt_row("  post-peak", s_post))

        # CH3 + SURV pre/post-peak
        s_ch3_pre = Stats()
        s_ch3_post = Stats()
        for f in ch3:
            (s_ch3_pre if f.decision_ts_ns <= peak_ts else s_ch3_post).add(f)
        s_surv_pre = Stats()
        s_surv_post = Stats()
        for f in surv:
            (s_surv_pre if f.decision_ts_ns <= peak_ts else s_surv_post).add(f)
        out.append("")
        out.append("  CH3 cell pre/post-peak:")
        out.append(fmt_row("  CH3 pre-peak", s_ch3_pre))
        out.append(fmt_row("  CH3 post-peak", s_ch3_post))
        out.append("")
        out.append("  SURV cell pre/post-peak:")
        out.append(fmt_row("  SURV pre-peak", s_surv_pre))
        out.append(fmt_row("  SURV post-peak", s_surv_post))

    # Per-UTC-hour
    out.append("")
    out.append("  Tier 30-50% per UTC hour:")
    by_hour: dict[int, Stats] = defaultdict(Stats)
    for f in tier_fires:
        h = datetime.fromtimestamp(f.decision_ts_ns / 1e9, tz=UTC).hour
        by_hour[h].add(f)
    for h in sorted(by_hour):
        out.append(fmt_row(f"  hour {h:02d} UTC", by_hour[h]))


def section_path_a_summary(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "ADDENDUM — PATH-A SLICE (block-up tier 70-85%)")
    # Path A is tier 70-85% (specifically block_up — DOWN-side fires on tier 70-85%? No.
    # Per memory, "tier 70-85%" was the loss source and H.2.12 added "path A block UP".
    # Operationally path-A fires are tier 70-85% × side=DOWN (since UP is blocked).
    # We'll show tier 70-85% overall and per-side.
    settled = [f for f in fires if f.pnl_usd is not None]
    s7085 = Stats()
    s7085_up = Stats()
    s7085_dn = Stats()
    for f in settled:
        if f.tier == "70-85%":
            s7085.add(f)
            (s7085_up if f.side == "UP" else s7085_dn).add(f)
    out.append(fmt_row("tier 70-85% ALL", s7085))
    out.append(fmt_row("tier 70-85% UP", s7085_up))
    out.append(fmt_row("tier 70-85% DOWN (path A)", s7085_dn))


def detect_restarts(fires: list[Fire], gap_min: float = 30.0) -> list[tuple[int, int, float]]:
    """Return list of (gap_index, ts_ns_after, gap_minutes) for fire-stream gaps > gap_min."""
    out_gaps: list[tuple[int, int, float]] = []
    for i in range(1, len(fires)):
        gap_ns = fires[i].decision_ts_ns - fires[i - 1].decision_ts_ns
        gap_m = gap_ns / 60e9
        if gap_m > gap_min:
            out_gaps.append((i, fires[i].decision_ts_ns, gap_m))
    return out_gaps


def section_restart_detection(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "N.3a — FIRE-STREAM GAP DETECTION (restart proxy)")
    out.append("  Gaps > 30 min between consecutive fires (likely bot restarts):")
    gaps = detect_restarts(fires, gap_min=30.0)
    if not gaps:
        out.append("    none")
        return
    out.append("    ts                       gap-min   notes")
    for _, ts, m in gaps:
        out.append(f"    {fmt_ts(ts)}    {m:7.1f}   (resume after {m:.0f}-min outage)")
    out.append(f"  Total likely restarts (5d): {len(gaps)}")


def simulate_m5(
    fires: list[Fire],
    *,
    n_warmup: int = 20,
    margin_pp: float = 0.02,
    reset_on_gap_min: float | None = None,
) -> dict:
    """Replay M.5 over the data. Path A = tier 70-85% × side=DOWN (UP is block-up'd).

    For each Path-A fire, M.5 looks at the prior rolling window of Path-A SETTLED
    fires (n=n_warmup). If n < n_warmup → M.5 inactive (cold-start, pass-through).
    Otherwise compute rolling WR; abstain if rolling_wr < mean_price + margin_pp.

    Returns a dict with timeline + counters.
    """
    settled_path_a: list[
        Fire
    ] = []  # in settle-time order; settle_ts approximated by decision_ts + 5min
    last_decision_ns: int | None = None
    timeline: list[dict] = []
    counters = {
        "path_a_fires": 0,
        "m5_active_fires": 0,
        "m5_abstain_fires": 0,
        "m5_first_active_ts_ns": None,
        "counterfactual_pnl_avoided": 0.0,  # PnL of fires M.5 WOULD have abstained (negative => avoided loss)
    }
    for fire in fires:
        # Optional restart-reset behavior
        if reset_on_gap_min is not None and last_decision_ns is not None:
            gap_m = (fire.decision_ts_ns - last_decision_ns) / 60e9
            if gap_m > reset_on_gap_min:
                settled_path_a = []
        last_decision_ns = fire.decision_ts_ns

        is_path_a = fire.tier == "70-85%" and fire.side == "DOWN"
        if is_path_a and fire.pnl_usd is not None:
            counters["path_a_fires"] += 1
            # Snapshot of rolling state at decision time (only settled fires BEFORE this fire's
            # decision time, approximated as those with decision_ts < this one's; settlements
            # arrive ~5min later but for simulation we use decision-time history).
            history = settled_path_a[-n_warmup:] if len(settled_path_a) >= n_warmup else None
            if history is not None:
                wins = sum(1 for f in history if f.won)
                rolling_wr = wins / len(history)
                mean_price = sum(f.price_limit for f in history) / len(history)
                threshold = mean_price + margin_pp
                m5_active = True
                m5_abstain = rolling_wr < threshold
                if counters["m5_first_active_ts_ns"] is None:
                    counters["m5_first_active_ts_ns"] = fire.decision_ts_ns
                counters["m5_active_fires"] += 1
                if m5_abstain:
                    counters["m5_abstain_fires"] += 1
                    counters["counterfactual_pnl_avoided"] -= fire.pnl_usd  # avoided this PnL
                timeline.append(
                    {
                        "ts_ns": fire.decision_ts_ns,
                        "n_history": len(history),
                        "rolling_wr": rolling_wr,
                        "mean_price": mean_price,
                        "threshold": threshold,
                        "m5_abstain": m5_abstain,
                        "actual_pnl": fire.pnl_usd,
                    }
                )
            else:
                timeline.append(
                    {
                        "ts_ns": fire.decision_ts_ns,
                        "n_history": len(settled_path_a),
                        "rolling_wr": None,
                        "mean_price": None,
                        "threshold": None,
                        "m5_abstain": False,
                        "actual_pnl": fire.pnl_usd,
                    }
                )
            # Append fire to history regardless (whether M.5 abstained or not, the actual
            # bot fired and saw a settlement).
            settled_path_a.append(fire)
    counters["timeline"] = timeline
    return counters


def section_n3_m5_simulator(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "N.3b — M.5 ACTIVATION SIMULATOR (Path-A regime wrapper)")
    out.append("  Path A = tier 70-85% × side=DOWN (H.2.12 block_up enforces UP→0)")
    out.append("  M.5 spec: needs ≥20 settled Path-A fires to activate;")
    out.append("            then abstains when rolling_wr < mean_price + 2pp")
    out.append("")

    # Mode 1: WITHOUT restart resets (idealized: state persists across restarts)
    sim_persist = simulate_m5(fires, n_warmup=20, margin_pp=0.02, reset_on_gap_min=None)
    # Mode 2: WITH restart resets at >60min gaps (mirrors actual bot behavior)
    sim_reset = simulate_m5(fires, n_warmup=20, margin_pp=0.02, reset_on_gap_min=60.0)

    for label, sim in [
        ("WITHOUT restart resets (idealized)", sim_persist),
        ("WITH restart resets at >60min gaps (bot-actual)", sim_reset),
    ]:
        out.append(f"  --- {label} ---")
        out.append(f"    total Path-A fires:         {sim['path_a_fires']}")
        out.append(f"    M.5 active fires:           {sim['m5_active_fires']}")
        out.append(f"    M.5 would-abstain fires:    {sim['m5_abstain_fires']}")
        if sim["m5_first_active_ts_ns"]:
            out.append(f"    M.5 first activated at:     {fmt_ts(sim['m5_first_active_ts_ns'])}")
        else:
            out.append("    M.5 first activated at:     NEVER (always cold-start)")
        out.append(f"    counterfactual PnL avoided: {sim['counterfactual_pnl_avoided']:+.2f}")
        out.append("")

    # Highlight: was M.5 EVER active during its actual 58-min live window (Sun 11:45Z → 12:43Z)?
    live_start_ns = 1779017100 * 10**9  # 2026-05-17 11:45:00Z
    live_end_ns = 1779021803 * 10**9  # 2026-05-17 12:43:23Z (halt sentinel ts)
    in_window_active = [
        e for e in sim_persist["timeline"] if live_start_ns <= e["ts_ns"] <= live_end_ns
    ]
    out.append("  Within M.5's actual live window (Sun 11:45Z → 12:43Z):")
    out.append(f"    Path-A fires in window:     {len(in_window_active)}")
    n_active = sum(1 for e in in_window_active if e["rolling_wr"] is not None)
    n_abstain = sum(1 for e in in_window_active if e["m5_abstain"])
    out.append(f"    M.5-active fires in window: {n_active}")
    out.append(f"    M.5 would-abstain in window:{n_abstain}")
    if in_window_active:
        for e in in_window_active:
            ts = fmt_ts(e["ts_ns"])
            if e["rolling_wr"] is None:
                out.append(f"    {ts}  COLD-START (n={e['n_history']})  pnl={e['actual_pnl']:+.2f}")
            else:
                tag = "ABSTAIN" if e["m5_abstain"] else "FIRE"
                out.append(
                    f"    {ts}  n={e['n_history']}  wr={e['rolling_wr'] * 100:5.1f}%  "
                    f"thr={e['threshold'] * 100:5.1f}%  {tag}  pnl={e['actual_pnl']:+.2f}"
                )


def section_n3_m1a_inversion(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "N.3c — M.1a v1 INVERSION TEST")
    settled = [f for f in fires if f.pnl_usd is not None]
    annotated = [f for f in settled if f.regime]

    # Part A: tier × regime cross-tab on the annotated subset (n=83)
    out.append("  Part A — annotated subset (n=83): tier × regime cross-tab")
    out.append("                  chop                mixed               trending")
    out.append("    tier           n    WR    PnL      n    WR    PnL      n    WR    PnL")
    tiers_to_show = ("30-50%", "70-85%")
    for t in tiers_to_show:
        cells = {}
        for r in ("chop", "mixed", "trending"):
            sub = [f for f in annotated if f.tier == t and f.regime == r]
            s = Stats()
            for f in sub:
                s.add(f)
            cells[r] = s
        row = f"    {t:<10}"
        for r in ("chop", "mixed", "trending"):
            s = cells[r]
            row += f"   {s.n:>2}  {s.wr*100:5.1f}% {s.pnl_total:+7.2f}"
        out.append(row)

    # Tier mix of chop-labeled vs mixed-labeled fires
    out.append("")
    out.append(
        "  Tier mix of regime-labeled fires (informs whether chop>mixed is a tier-skew artifact):"
    )
    for r in ("chop", "mixed", "trending"):
        sub = [f for f in annotated if f.regime == r]
        if not sub:
            continue
        tier_mix = defaultdict(int)
        for f in sub:
            tier_mix[f.tier] += 1
        out.append(f"    regime={r} (n={len(sub)}): {dict(tier_mix)}")

    # Part B: |Δbps| proxy regime across n=755
    out.append("")
    out.append("  Part B — |Δbps| proxy regime on ALL n=755 fires:")
    out.append("    proxy regime         |Δbps| range    n      WR     $/tr      PnL")
    proxy_buckets = [
        (0, 2.5, "very-flat (chop-like)"),
        (2.5, 5, "flat"),
        (5, 10, "active"),
        (10, 1e9, "trending-like"),
    ]
    for lo, hi, lbl in proxy_buckets:
        sub = [f for f in settled if f.abs_delta_bps is not None and lo <= f.abs_delta_bps < hi]
        s = Stats()
        for f in sub:
            s.add(f)
        out.append(
            f"    {lbl:<22} [{lo:>4.1f}, {hi if hi < 1e8 else float('inf'):>4.1f})  "
            f"{s.n:>4}  {s.wr*100:5.1f}%  {s.per_trade:+6.2f}  {s.pnl_total:+8.2f}"
        )

    # Part C: |Δbps| proxy × tier — the deeper falsifier
    out.append("")
    out.append("  Part C — |Δbps| proxy × tier (does inversion hold per tier?):")
    out.append("                       tier 30-50%                  tier 70-85%")
    out.append("    proxy regime       n   WR    $/tr    PnL        n   WR    $/tr    PnL")
    for lo, hi, lbl in proxy_buckets:
        row = f"    {lbl[:18]:<18}"
        for t in ("30-50%", "70-85%"):
            sub = [
                f
                for f in settled
                if f.tier == t and f.abs_delta_bps is not None and lo <= f.abs_delta_bps < hi
            ]
            s = Stats()
            for f in sub:
                s.add(f)
            row += f"   {s.n:>3} {s.wr*100:5.1f}% {s.per_trade:+6.2f} {s.pnl_total:+7.2f}"
        out.append(row)

    # Verdict line
    out.append("")
    out.append("  Verdict construct: the inversion hypothesis ('M.1a v1 abstains winners') is")
    out.append("  CONFIRMED if low-|Δbps| (chop-proxy) buckets show HIGHER WR than mid-|Δbps|")
    out.append("  buckets within the same tier. The Part B table answers this empirically.")


def section_n3_daily_breakdown(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "N.3d — DAILY PnL × TIER × SIDE BREAKDOWN")
    settled = [f for f in fires if f.pnl_usd is not None]
    out.append("  UTC day     30-50% UP   30-50% DN   70-85% DN   total")
    by_day_cell: dict[tuple[str, str, str], Stats] = defaultdict(Stats)
    by_day_total: dict[str, Stats] = defaultdict(Stats)
    for f in settled:
        day = fmt_ts(f.decision_ts_ns).split(" ")[0]
        by_day_cell[(day, f.tier, f.side)].add(f)
        by_day_total[day].add(f)
    for day in sorted(by_day_total):
        c1 = by_day_cell.get((day, "30-50%", "UP"), Stats()).pnl_total
        c2 = by_day_cell.get((day, "30-50%", "DOWN"), Stats()).pnl_total
        c3 = by_day_cell.get((day, "70-85%", "DOWN"), Stats()).pnl_total
        tot = by_day_total[day].pnl_total
        out.append(f"    {day}  {c1:+9.2f}   {c2:+9.2f}   {c3:+9.2f}   {tot:+8.2f}")


def section_regime_imbalance(out: list[str], fires: list[Fire]) -> None:
    section_header(out, "ADDENDUM — REGIME + IMBALANCE ANNOTATION PER-LABEL STATS")
    settled = [f for f in fires if f.pnl_usd is not None]
    # regime labels
    out.append("  Per-regime stats (where regime= annotation present):")
    by_regime: dict[str, Stats] = defaultdict(Stats)
    for f in settled:
        if f.regime:
            by_regime[f.regime].add(f)
    for r in sorted(by_regime):
        out.append(fmt_row(f"  regime={r}", by_regime[r]))
    # imbalance labels
    out.append("")
    out.append("  Per-imbalance stats (where imbalance= annotation present):")
    by_imb: dict[str, Stats] = defaultdict(Stats)
    for f in settled:
        if f.imbalance:
            by_imb[f.imbalance].add(f)
    for i in sorted(by_imb):
        out.append(fmt_row(f"  imbalance={i}", by_imb[i]))


# ─── main ─────────────────────────────────────────────────────────────────────


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", default="/tmp/phaseN_data/state", type=Path)
    p.add_argument("--out", default=None, type=Path)
    args = p.parse_args()

    fires, counts = load_data(args.data_dir)

    out: list[str] = []
    out.append("=" * 80)
    out.append("PHASE N — FORENSIC AUDIT (Session 1)")
    out.append(f"  generated: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%SZ')}")
    out.append(f"  data:      {args.data_dir}")
    out.append("=" * 80)

    section_n0_dataset(out, fires, counts)
    section_n1_peak(out, fires)
    section_n2_tier_30_50(out, fires)
    section_path_a_summary(out, fires)
    section_restart_detection(out, fires)
    section_n3_m5_simulator(out, fires)
    section_n3_m1a_inversion(out, fires)
    section_n3_daily_breakdown(out, fires)
    section_regime_imbalance(out, fires)

    text = "\n".join(out)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
        print(f"\n→ wrote {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
