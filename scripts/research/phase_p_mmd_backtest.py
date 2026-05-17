"""Phase P Session 2 — MMD backtest on Phase N n=755 forensic data.

Evaluates two MMD candidates per the operator's prompt:
  A. bukosabino/ta — rule-based ADX + BB-width + momentum (MIT, ~3 MB)
  B. hmmlearn — 4-state Gaussian HMM on (return, vol) features (BSD-3)

Pipeline:
  1. Load fires via phase_n_forensic_audit.load_data (n_settled ≈ 755).
  2. Bulk-fetch BTCUSDT 1m klines from Binance public API for 2026-05-12
     → 2026-05-18 (24h buffer for lookback), cache to parquet.
  3. For each fire ts: window the preceding 60 minutes, classify with each
     adapter → (label ∈ {UP, DOWN, CHOPPY, MIXED}, confidence ∈ [0,1]).
  4. Aggregate per-label n / WR / $tr / mean confidence per adapter.
  5. Write runbooks/research/phase-P-mmd-backtest-2026-05-18.md + 4 charts
     at state/research/phase-P-mmd-charts/.

USEFUL MMD threshold (per prompt P.2.2): ≥10pp WR delta between best and
worst label on n ≥ 20 subsamples.

Usage:
    uv run --with ta --with hmmlearn --with pandas --with matplotlib \\
        --with httpx --with numpy --with pyarrow \\
        python -u scripts/research/phase_p_mmd_backtest.py
"""

# ruff: noqa: RUF001, RUF002, RUF005, RUF100, S108, B905, E402, E741, F541

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

# Use the Phase N audit's data loader (same Fire dataclass + join logic).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from phase_n_forensic_audit import Fire, load_data  # noqa: E402

DATA_DIR = Path("/tmp/phase-P-mmd-data")
ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = ROOT / "state" / "research" / "binance_historical"
CHARTS_DIR = ROOT / "state" / "research" / "phase-P-mmd-charts"
REPORT_PATH = ROOT / "runbooks" / "research" / "phase-P-mmd-backtest-2026-05-18.md"
KLINES_CACHE = CACHE_DIR / "btcusdt_1m_2026-05-12_to_2026-05-18.parquet"

LABELS = ("UP", "DOWN", "CHOPPY", "MIXED")


def fetch_binance_1m(start_ms: int, end_ms: int) -> pd.DataFrame:
    """Bulk-fetch BTCUSDT 1m klines from Binance public REST API."""
    rows: list[list] = []
    cur = start_ms
    sess = httpx.Client(timeout=15.0)
    try:
        while cur < end_ms:
            r = sess.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "startTime": cur,
                    "endTime": end_ms,
                    "limit": 1000,
                },
            )
            r.raise_for_status()
            chunk = r.json()
            if not chunk:
                break
            rows.extend(chunk)
            cur = chunk[-1][0] + 60_000
            time.sleep(0.05)  # gentle pacing
    finally:
        sess.close()
    cols = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "qav",
        "trades",
        "tbb",
        "tbq",
        "ignore",
    ]
    df = pd.DataFrame(rows, columns=cols)
    df = df[["open_time", "open", "high", "low", "close", "volume"]].astype(
        {
            "open_time": "int64",
            "open": "float",
            "high": "float",
            "low": "float",
            "close": "float",
            "volume": "float",
        }
    )
    df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df


def get_klines() -> pd.DataFrame:
    if KLINES_CACHE.exists():
        print(f"  cache HIT: {KLINES_CACHE}")
        return pd.read_parquet(KLINES_CACHE)
    print(f"  cache MISS — fetching from Binance...")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # 2026-05-12 → 2026-05-18 covers all fires + 24h lookback buffer.
    start = int(pd.Timestamp("2026-05-12T00:00:00Z").timestamp() * 1000)
    end = int(pd.Timestamp("2026-05-18T00:00:00Z").timestamp() * 1000)
    df = fetch_binance_1m(start, end)
    df.to_parquet(KLINES_CACHE)
    print(f"  cached {len(df)} bars → {KLINES_CACHE}")
    return df


# ─── MMD A: rule-based via ta ───────────────────────────────────────────────


class TARuleMMD:
    """ADX + BB-width + momentum rule-based 4-state classifier."""

    def __init__(self, lookback_min: int = 60) -> None:
        self.lookback_min = lookback_min
        from ta.trend import ADXIndicator
        from ta.volatility import BollingerBands

        self._ADX = ADXIndicator
        self._BB = BollingerBands

    def classify(self, klines: pd.DataFrame, ts: pd.Timestamp) -> tuple[str, float]:
        win = klines[klines.index <= ts].iloc[-self.lookback_min :]
        if len(win) < 30:
            return ("MIXED", 0.0)
        h, l, c = win["high"], win["low"], win["close"]
        try:
            adx = float(self._ADX(h, l, c, window=14, fillna=True).adx().iloc[-1])
        except Exception:
            adx = 0.0
        try:
            bb = self._BB(c, window=20, window_dev=2, fillna=True)
            bbw = float(
                (bb.bollinger_hband().iloc[-1] - bb.bollinger_lband().iloc[-1]) / c.iloc[-1]
            )
        except Exception:
            bbw = 0.005
        momentum = float((c.iloc[-1] - c.iloc[-30]) / c.iloc[-30])

        adx_strong = adx > 25
        adx_weak = adx < 20
        bb_compressed = bbw < 0.003
        mom_up = momentum > 0.001
        mom_dn = momentum < -0.001

        if adx_strong and mom_up:
            return ("UP", min(1.0, (adx - 25) / 15))
        if adx_strong and mom_dn:
            return ("DOWN", min(1.0, (adx - 25) / 15))
        if adx_weak and bb_compressed:
            return ("CHOPPY", min(1.0, (20 - adx) / 10))
        return ("MIXED", 0.5)


# ─── MMD B: 4-state Gaussian HMM via hmmlearn ───────────────────────────────


class HMMRegimeMMD:
    """4-state Gaussian HMM on (log-return, rolling vol) features.

    Trained in-sample on the full 5-day series — that's an upper bound on
    performance; the Session-3 ship will retrain on a longer rolling window
    or use a pre-trained snapshot. Per-fire classification uses posterior
    over the last bar of the lookback window."""

    def __init__(self, lookback_min: int = 60) -> None:
        self.lookback_min = lookback_min
        self.model = None
        self.label_map: dict[int, str] = {}

    # Scale 1m log-returns + vol into ~unit range so HMM EM stays numerically stable.
    SCALE = 1e4  # 1m BTC log-returns are ~1e-4; scale to ~unit.

    @classmethod
    def _features(cls, closes: np.ndarray) -> np.ndarray:
        # log-return and rolling vol; both length N-1, scaled to ~unit.
        ret = np.diff(np.log(closes)) * cls.SCALE
        vol = pd.Series(ret).rolling(10, min_periods=2).std().bfill().to_numpy()
        X = np.column_stack([ret, vol])
        return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    def fit(self, klines: pd.DataFrame) -> None:
        from hmmlearn.hmm import GaussianHMM

        closes = klines["close"].to_numpy()
        X = self._features(closes)
        # diag covariance is more robust than full for low-variance features.
        m = GaussianHMM(
            n_components=4,
            covariance_type="diag",
            n_iter=120,
            random_state=42,
            tol=1e-3,
            min_covar=1e-3,
        )
        m.fit(X)
        self.model = m
        # State centroids: means_[i] = [mean_log_return, mean_vol]
        means = m.means_
        order = sorted(range(4), key=lambda i: -abs(means[i, 0]))
        s0, s1, s2, s3 = order  # s0/s1 = strongest |mean_ret|; s2/s3 = weakest
        label: dict[int, str] = {}
        # Top-2 |mean_ret|: assign UP if mean_ret>0 else DOWN, ensuring uniqueness.
        for s in (s0, s1):
            wants = "UP" if means[s, 0] > 0 else "DOWN"
            if wants not in label.values():
                label[s] = wants
            else:
                label[s] = "DOWN" if wants == "UP" else "UP"
        # Bottom-2 |mean_ret|: lower vol → CHOPPY, higher → MIXED.
        rem = sorted([s2, s3], key=lambda i: means[i, 1])
        label[rem[0]] = "CHOPPY"
        label[rem[1]] = "MIXED"
        self.label_map = label

    def classify(self, klines: pd.DataFrame, ts: pd.Timestamp) -> tuple[str, float]:
        if self.model is None:
            return ("MIXED", 0.0)
        win = klines[klines.index <= ts].iloc[-self.lookback_min :]
        if len(win) < 12:
            return ("MIXED", 0.0)
        X = self._features(win["close"].to_numpy())
        try:
            posterior = self.model.predict_proba(X)
            state = int(np.argmax(posterior[-1]))
            return (self.label_map[state], float(posterior[-1, state]))
        except Exception:
            return ("MIXED", 0.0)


# ─── reporting ──────────────────────────────────────────────────────────────


def _per_label_stats(labels: list[str], confs: list[float], fires: list[Fire]) -> dict[str, dict]:
    by: dict[str, list[Fire]] = defaultdict(list)
    by_conf: dict[str, list[float]] = defaultdict(list)
    for lab, conf, f in zip(labels, confs, fires):
        by[lab].append(f)
        by_conf[lab].append(conf)
    out: dict[str, dict] = {}
    for lab in LABELS:
        sub = by.get(lab, [])
        confs_lab = by_conf.get(lab, [])
        if not sub:
            out[lab] = {"n": 0, "wr": 0.0, "per_tr": 0.0, "pnl": 0.0, "mean_conf": 0.0}
            continue
        wr = sum(1 for f in sub if f.won) / len(sub)
        pnl = sum(f.pnl_usd for f in sub)
        out[lab] = {
            "n": len(sub),
            "wr": wr,
            "per_tr": pnl / len(sub),
            "pnl": pnl,
            "mean_conf": sum(confs_lab) / len(confs_lab) if confs_lab else 0.0,
        }
    return out


def _wr_delta(
    stats: dict[str, dict], min_n: int = 20
) -> tuple[tuple[str, float, int], tuple[str, float, int]] | None:
    rows = [(lab, s["wr"], s["n"]) for lab, s in stats.items() if s["n"] >= min_n]
    if len(rows) < 2:
        return None
    rows.sort(key=lambda r: r[1])
    return rows[-1], rows[0]


def write_report(
    settled: list[Fire],
    klines: pd.DataFrame,
    a_labels: list[str],
    a_confs: list[float],
    a_stats: dict[str, dict],
    b_labels: list[str],
    b_confs: list[float],
    b_stats: dict[str, dict],
    b_map: dict[int, str],
) -> None:
    out: list[str] = []
    w = out.append

    w("# Phase P Session 2 — MMD backtest report")
    w("")
    w(f"Generated 2026-05-18 (operator UAE local).  ")
    w(f"Settled fires loaded: **n = {len(settled)}**.  ")
    w(
        f"Klines: Binance BTCUSDT 1m, **{len(klines)} bars** from {klines.index[0]} to {klines.index[-1]}.  "
    )
    w("")
    w("Two candidate Market Mode Detectors backtested:")
    w("")
    w(
        "  - **Adapter A — `bukosabino/ta`** (MIT, pure-Python). Rule-based ADX(14) > 25 trend / momentum sign + BB-width(20, 2σ) < 30bps for chop. Lookback 60 min on 1m bars."
    )
    w(
        "  - **Adapter B — `hmmlearn`** (BSD-3). 4-state Gaussian HMM on (log-return, rolling-10 vol) features. In-sample fit on full 5-day series — known upper bound; Session 3 will retrain on rolling window."
    )
    w("")

    def table(stats: dict[str, dict], labels: list[str]) -> None:
        dist = Counter(labels).most_common()
        w(f"Label distribution: {dict(dist)}")
        w("")
        w("| Label | n | WR | $/tr | PnL | mean conf |")
        w("|-------|---|----|------|-----|-----------|")
        for lab in LABELS:
            s = stats[lab]
            if s["n"] == 0:
                w(f"| {lab} | 0 | — | — | — | — |")
                continue
            w(
                f"| {lab} | {s['n']} | {s['wr']*100:.1f}% | ${s['per_tr']:+.2f} | ${s['pnl']:+.0f} | {s['mean_conf']:.2f} |"
            )
        w("")

    w("## Adapter A — `bukosabino/ta` rule-based")
    w("")
    table(a_stats, a_labels)
    d = _wr_delta(a_stats)
    if d:
        best, worst = d
        gap = (best[1] - worst[1]) * 100
        w(
            f"**Best vs worst (n ≥ 20):** {best[0]} WR {best[1]*100:.1f}% n={best[2]} | {worst[0]} WR {worst[1]*100:.1f}% n={worst[2]} | **gap {gap:+.1f}pp**"
        )
    else:
        w("**Best vs worst:** insufficient samples per label (< 20).")
    w("")

    w("## Adapter B — `hmmlearn` 4-state HMM")
    w("")
    w(f"HMM state→label map: {b_map}")
    w("")
    table(b_stats, b_labels)
    d = _wr_delta(b_stats)
    if d:
        best, worst = d
        gap = (best[1] - worst[1]) * 100
        w(
            f"**Best vs worst (n ≥ 20):** {best[0]} WR {best[1]*100:.1f}% n={best[2]} | {worst[0]} WR {worst[1]*100:.1f}% n={worst[2]} | **gap {gap:+.1f}pp**"
        )
    else:
        w("**Best vs worst:** insufficient samples per label (< 20).")
    w("")

    # Co-occurrence
    w("## Co-occurrence A vs B (rows A, cols B)")
    w("")
    co: dict[str, Counter] = {l: Counter() for l in LABELS}
    for la, lb in zip(a_labels, b_labels):
        co[la][lb] += 1
    header = "| A \\ B | " + " | ".join(LABELS) + " |"
    sep = "|---|" + "|".join(["---"] * len(LABELS)) + "|"
    w(header)
    w(sep)
    for la in LABELS:
        cells = " | ".join(str(co[la].get(lb, 0)) for lb in LABELS)
        w(f"| {la} | {cells} |")
    w("")

    w("## Acceptance against prompt P.2.2 USEFUL criterion")
    w("")
    w("Threshold: ≥ 10 pp WR delta between best and worst label on subsamples n ≥ 20.")
    w("")
    for name, stats in [("Adapter A (ta)", a_stats), ("Adapter B (hmm)", b_stats)]:
        d = _wr_delta(stats)
        if not d:
            w(f"- {name}: insufficient — < 2 labels with n ≥ 20.")
            continue
        best, worst = d
        gap = (best[1] - worst[1]) * 100
        verdict = "PASS" if gap >= 10.0 else "FAIL"
        w(f"- {name}: gap {gap:+.1f}pp → **{verdict}**")
    w("")
    w(
        "Charts at `state/research/phase-P-mmd-charts/`. See PHASE_P_SESSION2_MMD_RESEARCH.pdf for the full study."
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(out))
    print(f"Wrote {REPORT_PATH}")


def render_charts(
    settled: list[Fire],
    a_labels: list[str],
    a_stats: dict[str, dict],
    b_labels: list[str],
    b_stats: dict[str, dict],
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    BG, FG, ACC, LOSS, WARN = "#0a0a0a", "#e0e0e0", "#00ff88", "#ff4466", "#ffaa00"
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    def _ax(ax):
        ax.set_facecolor(BG)
        ax.tick_params(colors=FG)
        for sp in ax.spines.values():
            sp.set_color("#888")

    # 1. WR per label (both adapters)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), facecolor=BG)
    for ax, (name, stats) in zip(
        axes, [("Adapter A — ta (rule)", a_stats), ("Adapter B — hmm (HMM)", b_stats)]
    ):
        wrs = [stats[l]["wr"] * 100 for l in LABELS]
        ns = [stats[l]["n"] for l in LABELS]
        bars = ax.bar(LABELS, wrs, color=[ACC, LOSS, WARN, "#888"])
        for bar, n, wr in zip(bars, ns, wrs):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 1,
                f"n={n}\n{wr:.1f}%",
                ha="center",
                va="bottom",
                color=FG,
                fontsize=8,
            )
        ax.set_title(name, color=ACC)
        ax.set_ylabel("WR %", color=FG)
        ax.axhline(50, color="#888", linestyle="--", linewidth=0.5)
        ax.set_ylim(0, max(85, max(wrs + [50]) + 12))
        _ax(ax)
    fig.suptitle(f"Per-label WR — n_settled={len(settled)} backtest", color=ACC)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "01_per_label_wr.png", dpi=130, facecolor=BG)
    plt.close()

    # 2. $/tr per label
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), facecolor=BG)
    for ax, (name, stats) in zip(axes, [("Adapter A — ta", a_stats), ("Adapter B — hmm", b_stats)]):
        pers = [stats[l]["per_tr"] for l in LABELS]
        colors = [ACC if v >= 0 else LOSS for v in pers]
        bars = ax.bar(LABELS, pers, color=colors)
        for bar, v in zip(bars, pers):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"${v:+.2f}",
                ha="center",
                va="bottom" if v >= 0 else "top",
                color=FG,
                fontsize=9,
            )
        ax.set_title(name, color=ACC)
        ax.set_ylabel("$/tr", color=FG)
        ax.axhline(0, color="#888", linewidth=0.5)
        _ax(ax)
    fig.suptitle("Per-label $/trade — n_settled backtest", color=ACC)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "02_per_label_per_trade.png", dpi=130, facecolor=BG)
    plt.close()

    # 3. Label distribution comparison
    fig, ax = plt.subplots(1, 1, figsize=(10, 5), facecolor=BG)
    a_counts = [a_stats[l]["n"] for l in LABELS]
    b_counts = [b_stats[l]["n"] for l in LABELS]
    x = np.arange(len(LABELS))
    w_bar = 0.35
    ax.bar(x - w_bar / 2, a_counts, w_bar, color=ACC, label="A (ta)")
    ax.bar(x + w_bar / 2, b_counts, w_bar, color="#00aaff", label="B (hmm)")
    ax.set_xticks(x)
    ax.set_xticklabels(LABELS)
    ax.set_ylabel("n fires", color=FG)
    ax.set_title("Label distribution", color=ACC)
    ax.legend(facecolor="#1a1a1a", edgecolor="#888", labelcolor=FG)
    _ax(ax)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "03_label_distribution.png", dpi=130, facecolor=BG)
    plt.close()

    # 4. Cum-PnL best vs worst label for chosen adapter (A by default)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5), facecolor=BG)
    for ax, (name, stats, labels) in zip(
        axes,
        [
            ("Adapter A — cum PnL by best vs worst label", a_stats, a_labels),
            ("Adapter B — cum PnL by best vs worst label", b_stats, b_labels),
        ],
    ):
        d = _wr_delta(stats)
        if not d:
            ax.text(
                0.5,
                0.5,
                "insufficient samples",
                ha="center",
                va="center",
                color=FG,
                transform=ax.transAxes,
            )
            ax.set_title(name, color=ACC)
            _ax(ax)
            continue
        best, worst = d
        by_lab: dict[str, list[Fire]] = defaultdict(list)
        for lab, f in zip(labels, settled):
            by_lab[lab].append(f)
        for lab, color in [(best[0], ACC), (worst[0], LOSS)]:
            sub = sorted(by_lab[lab], key=lambda f: f.decision_ts_ns)
            cum = np.cumsum([f.pnl_usd for f in sub])
            ax.plot(
                range(len(cum)),
                cum,
                label=f"{lab} (n={len(cum)} WR={stats[lab]['wr']*100:.1f}%)",
                color=color,
                lw=1.8,
            )
        ax.set_xlabel("fire index within label", color=FG)
        ax.set_ylabel("cumulative PnL ($)", color=FG)
        ax.set_title(name, color=ACC)
        ax.legend(facecolor="#1a1a1a", edgecolor="#888", labelcolor=FG, fontsize=8)
        ax.axhline(0, color="#888", linewidth=0.5)
        _ax(ax)
    plt.tight_layout()
    plt.savefig(CHARTS_DIR / "04_cum_pnl_best_vs_worst.png", dpi=130, facecolor=BG)
    plt.close()

    print(f"Wrote 4 charts to {CHARTS_DIR}")


def main() -> int:
    print("=== Phase P Session 2 — MMD backtest ===")
    print(f"Loading fires from {DATA_DIR}...")
    fires, counts = load_data(DATA_DIR)
    settled = [f for f in fires if f.pnl_usd is not None and f.won is not None]
    print(f"  fires loaded: {len(fires)}, settled with won: {len(settled)}, counts: {dict(counts)}")
    if not settled:
        print("ERROR: no settled fires loaded — check DATA_DIR")
        return 1

    print("Fetching Binance klines...")
    klines = get_klines()
    print(f"  klines: {len(klines)} bars, range {klines.index[0]} → {klines.index[-1]}")

    print("Initializing adapters...")
    mmd_a = TARuleMMD(lookback_min=60)
    mmd_b = HMMRegimeMMD(lookback_min=60)
    print("Fitting HMM (in-sample on 5-day series)...")
    mmd_b.fit(klines)
    print(f"  HMM label map: {mmd_b.label_map}")

    print(f"Classifying {len(settled)} fires...")
    a_labels: list[str] = []
    a_confs: list[float] = []
    b_labels: list[str] = []
    b_confs: list[float] = []
    for i, f in enumerate(settled):
        ts = pd.Timestamp(f.decision_ts_ns, unit="ns", tz="UTC")
        la, ca = mmd_a.classify(klines, ts)
        lb, cb = mmd_b.classify(klines, ts)
        a_labels.append(la)
        a_confs.append(ca)
        b_labels.append(lb)
        b_confs.append(cb)
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(settled)}...")
    print("  done classifying")

    a_stats = _per_label_stats(a_labels, a_confs, settled)
    b_stats = _per_label_stats(b_labels, b_confs, settled)

    write_report(
        settled, klines, a_labels, a_confs, a_stats, b_labels, b_confs, b_stats, mmd_b.label_map
    )
    render_charts(settled, a_labels, a_stats, b_labels, b_stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
