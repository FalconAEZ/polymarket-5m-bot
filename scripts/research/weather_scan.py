"""Weather-ladder paper scanner (design/W.1-weather-ladder.md): snapshots every open
Polymarket daily-temperature bucket, prices each bucket with an Open-Meteo forecast plus a
lead-time Normal error model, logs the full model-vs-market table for calibration, flags
ladder-zone candidates (ask <= 0.20, EV/$ >= +0.25) net of the 0.05 taker-fee coefficient,
and scores prior snapshots against resolved outcomes. Read-only public APIs; no order path."""

from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
UA = {"User-Agent": "weather-ladder-research/0.1 (paper-only scanner)"}

FEE_COEF = 0.05          # weather taker-fee coefficient, docs.polymarket.com (verify at gate)
SIGMA_C = {0: 1.2, 1: 1.6, 2: 2.2}   # prior stddev (deg C) by lead days; calibrated by the soak
MAX_ASK = 0.20
MIN_BOOK_ASK = 0.02      # below this, quotes are dust/stale (day-0 finding)
MIN_DEPTH_USD = 25.0     # tradeable size at best ask required to count for the gate
MIN_EV_PER_USD = 0.25
MAX_BOOK_LOOKUPS = 25
MAX_SCORE_LOOKUPS = 30

CITY_COORDS: dict[str, tuple[float, float]] = {
    "nyc": (40.78, -73.97), "los-angeles": (34.05, -118.24), "chicago": (41.96, -87.93),
    "miami": (25.79, -80.32), "houston": (29.98, -95.36), "dallas": (32.90, -97.04),
    "austin": (30.19, -97.67), "atlanta": (33.64, -84.43), "philadelphia": (39.87, -75.24),
    "boston": (42.36, -71.01), "phoenix": (33.43, -112.01), "seattle": (47.45, -122.31),
    "denver": (39.85, -104.66), "san-francisco": (37.62, -122.37), "washington": (38.85, -77.04),
    "toronto": (43.68, -79.63), "london": (51.48, -0.45), "paris": (48.82, 2.34),
    "munich": (48.14, 11.58), "milan": (45.46, 9.19), "madrid": (40.41, -3.68),
    "warsaw": (52.16, 20.96), "rome": (41.80, 12.24), "berlin": (52.47, 13.40),
    "amsterdam": (52.31, 4.76), "vienna": (48.11, 16.57), "lisbon": (38.77, -9.13),
    "athens": (37.94, 23.94), "istanbul": (40.98, 28.81), "ankara": (39.95, 32.69),
    "moscow": (55.75, 37.62), "kyiv": (50.40, 30.45), "tel-aviv": (32.10, 34.78),
    "dubai": (25.25, 55.36), "riyadh": (24.71, 46.72), "cairo": (30.11, 31.40),
    "seoul": (37.57, 126.97), "tokyo": (35.69, 139.69), "hong-kong": (22.30, 114.17),
    "singapore": (1.35, 103.99), "taipei": (25.04, 121.51), "shanghai": (31.23, 121.47),
    "beijing": (39.91, 116.39), "wuhan": (30.59, 114.30), "chongqing": (29.56, 106.55),
    "jinan": (36.65, 117.00), "zhengzhou": (34.75, 113.63), "bangkok": (13.69, 100.75),
    "jakarta": (-6.13, 106.66), "manila": (14.51, 121.02), "mumbai": (19.09, 72.87),
    "new-delhi": (28.57, 77.10), "sydney": (-33.95, 151.18), "wellington": (-41.29, 174.78),
    "mexico-city": (19.43, -99.13), "sao-paulo": (-23.55, -46.63),
    "buenos-aires": (-34.58, -58.48), "johannesburg": (-26.14, 28.25), "lagos": (6.58, 3.33),
    "busan": (35.18, 129.08), "cape-town": (-33.97, 18.60), "chengdu": (30.57, 104.07),
    "guangzhou": (23.13, 113.26), "helsinki": (60.32, 24.96), "jeddah": (21.49, 39.19),
    "karachi": (24.91, 67.16), "kuala-lumpur": (2.75, 101.71), "lucknow": (26.85, 80.95),
    "qingdao": (36.07, 120.38), "shenzhen": (22.54, 114.06),
}

MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june",
     "july", "august", "september", "october", "november", "december"])}

SLUG_RE = re.compile(r"^highest-temperature-in-(.+)-on-([a-z]+)-(\d{1,2})(?:-(\d{4}))?$")
BELOW_RE = re.compile(r"^(-?\d+)\s*°([CF]) or (?:below|lower)$")
RANGE_RE = re.compile(r"^(-?\d+)\s*-\s*(-?\d+)\s*°([CF])$")
ABOVE_RE = re.compile(r"^(-?\d+)\s*°([CF]) or (?:above|higher)$")


@dataclass
class BucketRow:
    ts: str
    slug: str
    city: str
    target_date: str
    lead_days: int
    bucket: str
    lo_c: Optional[float]
    hi_c: Optional[float]
    forecast_tmax_c: float
    sigma_c: float
    model_p: float
    bid: Optional[float]
    ask: Optional[float]
    breakeven_p: Optional[float]
    ev_per_usd: Optional[float]
    flagged: bool
    book_ask: Optional[float]
    book_depth_usd: Optional[float]
    verified: bool
    yes_token: str


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.load(resp)


def fetch_weather_events() -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for offset in range(0, 500, 100):
        q = urllib.parse.urlencode(
            {"tag_slug": "weather", "closed": "false", "limit": 100, "offset": offset})
        page = get_json(f"{GAMMA}/events?{q}")
        events.extend(page)
        if len(page) < 100:
            break
    return events


def parse_slug(slug: str) -> Optional[tuple[str, date]]:
    m = SLUG_RE.match(slug)
    if not m:
        return None
    city, month_name, day, year = m.group(1), m.group(2), int(m.group(3)), m.group(4)
    month = MONTHS.get(month_name)
    if month is None:
        return None
    yr = int(year) if year else datetime.now(timezone.utc).year
    try:
        return city, date(yr, month, day)
    except ValueError:
        return None


def parse_bucket(title: str) -> Optional[tuple[Optional[float], Optional[float], str]]:
    """Return (lo, hi, unit) as continuous bounds honoring integer rounding of the report."""
    t = title.replace("°", "°").strip()
    if (m := BELOW_RE.match(t)):
        return None, float(m.group(1)) + 0.5, m.group(2)
    if (m := RANGE_RE.match(t)):
        return float(m.group(1)) - 0.5, float(m.group(2)) + 0.5, m.group(3)
    if (m := ABOVE_RE.match(t)):
        return float(m.group(1)) - 0.5, None, m.group(2)
    return None


def f_to_c(v: float) -> float:
    return (v - 32.0) / 1.8


def normal_cdf(x: float, mu: float, sigma: float) -> float:
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * math.sqrt(2.0))))


def bucket_prob(lo: Optional[float], hi: Optional[float], mu: float, sigma: float) -> float:
    upper = normal_cdf(hi, mu, sigma) if hi is not None else 1.0
    lower = normal_cdf(lo, mu, sigma) if lo is not None else 0.0
    return max(0.0, upper - lower)


def taker_fee(a: float) -> float:
    return FEE_COEF * a * (1.0 - a)


class ForecastCache:
    """One Open-Meteo call per (city, date range); returns tmax deg C and city-local today."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[dict[str, float], date]] = {}

    def lookup(self, city: str, targets: list[date]) -> Optional[tuple[dict[str, float], date]]:
        if city in self._cache:
            return self._cache[city]
        coords = CITY_COORDS.get(city)
        if coords is None:
            return None
        lat, lon = coords
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "daily": "temperature_2m_max",
            "timezone": "auto", "start_date": min(targets).isoformat(),
            "end_date": max(targets).isoformat()})
        data = get_json(f"{OPEN_METEO}?{q}")
        days = data.get("daily", {}).get("time", [])
        temps = data.get("daily", {}).get("temperature_2m_max", [])
        tmax = {d: t for d, t in zip(days, temps) if t is not None}
        local_today = datetime.now(ZoneInfo(data.get("timezone", "UTC"))).date()
        self._cache[city] = (tmax, local_today)
        return self._cache[city]


def best_ask_depth(yes_token: str) -> Optional[tuple[float, float]]:
    """CLOB book best ask + cumulative notional within best+2 cents (a taker fill sweeps
    levels). Levels are worst-first: take min explicitly
    (archive lesson project_polymarket_book_sort_order_2026_05_25)."""
    try:
        book = get_json(f"{CLOB}/book?token_id={yes_token}")
    except Exception:
        return None
    asks = [(float(x["price"]), float(x["size"])) for x in book.get("asks", [])]
    if not asks:
        return None
    best = min(price for price, _ in asks)
    notional = sum(price * size for price, size in asks if price <= best + 0.02)
    return best, notional


def score_resolved(out_dir: Path, warnings: list[str]) -> int:
    """Score flagged candidates from prior snapshots whose city-day has since resolved."""
    results_path = out_dir / "results.jsonl"
    scored: set[str] = set()
    if results_path.exists():
        for line in results_path.read_text().splitlines():
            scored.add(json.loads(line)["key"])
    pending: dict[str, dict[str, Any]] = {}
    for snap in sorted(out_dir.glob("scan-*.jsonl")):
        for line in snap.read_text().splitlines():
            row = json.loads(line)
            key = f"{row['slug']}|{row['bucket']}"
            if row.get("verified") and key not in scored:
                pending[key] = row
    if not pending:
        return 0
    new = 0
    slugs = {r["slug"] for r in pending.values()}
    with results_path.open("a") as fh:
        for slug in sorted(slugs)[:MAX_SCORE_LOOKUPS]:
            try:
                evs = get_json(f"{GAMMA}/events?slug={urllib.parse.quote(slug)}")
            except Exception as exc:
                warnings.append(f"score lookup failed {slug}: {exc}")
                continue
            if not evs or not evs[0].get("closed"):
                continue
            winners = set()
            for mk in evs[0].get("markets", []):
                prices = mk.get("outcomePrices")
                if prices and json.loads(prices)[0] in ("1", "1.0"):
                    winners.add(mk.get("groupItemTitle", ""))
            if not winners:
                continue
            for key, row in pending.items():
                if row["slug"] != slug:
                    continue
                won = row["bucket"] in winners
                fh.write(json.dumps({
                    "key": key, "slug": slug, "bucket": row["bucket"], "won": won,
                    "ask": row["ask"], "model_p": row["model_p"],
                    "breakeven_p": row["breakeven_p"], "scored_at":
                    datetime.now(timezone.utc).isoformat(timespec="seconds")}) + "\n")
                new += 1
    return new


def main() -> int:
    now = datetime.now(timezone.utc)
    repo_root = Path(__file__).resolve().parents[2]
    out_dir = repo_root / "state" / "research" / "weather"
    out_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []

    events = fetch_weather_events()
    city_days: dict[str, tuple[str, date, dict[str, Any]]] = {}
    unknown_cities: set[str] = set()
    for ev in events:
        parsed = parse_slug(ev.get("slug", ""))
        if parsed is None:
            continue
        city, target = parsed
        if target < now.date():          # zombie past-date events stay listed as open
            continue
        if city not in CITY_COORDS:
            unknown_cities.add(city)
            continue
        city_days[ev["slug"]] = (city, target, ev)

    cache = ForecastCache()
    targets_by_city: dict[str, list[date]] = {}
    for city, target, _ in city_days.values():
        targets_by_city.setdefault(city, []).append(target)

    rows: list[BucketRow] = []
    ts = now.isoformat(timespec="seconds")
    for slug, (city, target, ev) in sorted(city_days.items()):
        try:
            fc = cache.lookup(city, targets_by_city[city])
        except Exception as exc:
            warnings.append(f"forecast failed {city}: {exc}")
            continue
        if fc is None:
            continue
        tmax_by_day, local_today = fc
        tmax_c = tmax_by_day.get(target.isoformat())
        if tmax_c is None:
            warnings.append(f"no tmax for {slug}")
            continue
        lead = max(0, (target - local_today).days)
        sigma = SIGMA_C.get(lead, 2.2 + 0.5 * (lead - 2))
        for mk in ev.get("markets", []):
            parsed_bucket = parse_bucket(mk.get("groupItemTitle") or "")
            if parsed_bucket is None:
                continue
            lo, hi, unit = parsed_bucket
            lo_c = f_to_c(lo + 0.0) if (unit == "F" and lo is not None) else lo
            hi_c = f_to_c(hi + 0.0) if (unit == "F" and hi is not None) else hi
            p = bucket_prob(lo_c, hi_c, tmax_c, sigma)
            bid = mk.get("bestBid")
            ask = mk.get("bestAsk")
            breakeven: Optional[float] = None
            ev_usd: Optional[float] = None
            flagged = False
            if isinstance(ask, (int, float)) and 0.0 < ask < 1.0:
                breakeven = ask + taker_fee(ask)
                ev_usd = (p - ask - taker_fee(ask)) / ask
                flagged = (ask <= MAX_ASK and ev_usd >= MIN_EV_PER_USD
                           and p >= 2.0 * breakeven)
            tokens = mk.get("clobTokenIds")
            yes_token = json.loads(tokens)[0] if tokens else ""
            rows.append(BucketRow(
                ts=ts, slug=slug, city=city, target_date=target.isoformat(), lead_days=lead,
                bucket=mk.get("groupItemTitle") or "", lo_c=lo_c, hi_c=hi_c,
                forecast_tmax_c=round(tmax_c, 1), sigma_c=sigma, model_p=round(p, 4),
                bid=bid, ask=ask, breakeven_p=round(breakeven, 4) if breakeven else None,
                ev_per_usd=round(ev_usd, 3) if ev_usd is not None else None,
                flagged=flagged, book_ask=None, book_depth_usd=None, verified=False,
                yes_token=yes_token))

    provisional = sorted(
        (r for r in rows if r.flagged),
        key=lambda r: ((r.ask or 0.0) < MIN_BOOK_ASK, -(r.ev_per_usd or 0.0)))
    for r in provisional[:MAX_BOOK_LOOKUPS]:
        depth = best_ask_depth(r.yes_token) if r.yes_token else None
        if depth is None:
            continue
        r.book_ask, r.book_depth_usd = round(depth[0], 4), round(depth[1], 2)
        if MIN_BOOK_ASK <= depth[0] <= MAX_ASK and depth[1] >= MIN_DEPTH_USD:
            ev_book = (r.model_p - depth[0] - taker_fee(depth[0])) / depth[0]
            r.verified = ev_book >= MIN_EV_PER_USD

    snap_path = out_dir / f"scan-{now.strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    with snap_path.open("w") as fh:
        for row in rows:
            fh.write(json.dumps(asdict(row)) + "\n")

    verified_rows = [r for r in provisional if r.verified]
    print(f"UTC {ts} | events open: {len(events)} | scannable city-days: {len(city_days)} "
          f"| buckets logged: {len(rows)} | provisional: {len(provisional)} "
          f"| verified (tradeable): {len(verified_rows)}")
    if unknown_cities:
        print(f"cities without coords (add to CITY_COORDS): {sorted(unknown_cities)}")
    for r in verified_rows:
        print(f"  {r.target_date} {r.city:<14} {r.bucket:<16} book ask {r.book_ask:.2f} "
              f"depth ${r.book_depth_usd:,.0f} model_p {r.model_p:.2f} "
              f"(breakeven {r.breakeven_p:.2f}) lead {r.lead_days}d")
    if not verified_rows:
        print("  no verified ladder-zone candidates this run "
              "(normal on many days — dust-quote provisionals do not count)")
    scored = score_resolved(out_dir, warnings)
    print(f"resolved outcomes newly scored: {scored} (cumulative file: results.jsonl)")
    for w in warnings[:10]:
        print(f"  warn: {w}")
    print(f"snapshot: {snap_path.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
