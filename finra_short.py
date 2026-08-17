"""FINRA daily short-sale volume (free CDN bulk file, no credential).

FINRA publishes each trading day's short-sale volume as a pipe-delimited text
file::

    Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market

fetched from::

    https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt

This is the zero-credential path (a browser User-Agent is required; the CDN
403s default clients). It is *short activity*, not cost-to-borrow: FINRA does
not publish CTB, locates, or borrow fees here, so no borrow rate is invented.

The aggregated output is a closed-vocabulary short-activity read, not a score:
``LOW / NORMAL / ELEVATED / HIGH / NO_DATA`` from a declared band over the
rolling short-volume ratio (short volume / total volume). The bi-monthly
consolidated short-interest + days-to-cover series is a separate future source
(its Query API requires a FINRA Public credential, not wired here).
"""
from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone

import requests

SHORT_VOLUME_URL = "https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
DEFAULT_DAYS = 20
MAX_DAYS = 252

# Declared heuristic bands for the rolling short-volume ratio. A short sale is
# one side of every reported transaction, so a ~40-55% ratio is ordinary;
# sustained reads outside that band signal an unusual shorting balance.
_LOW = 0.40
_HIGH = 0.70
_NORMAL = 0.55

_FRESHNESS = "DELAYED"  # FINRA publishes daily short volume T+1, never real-time


class UpstreamError(RuntimeError):
    pass


_MISSING = object()


class _Cache:
    """Process-local day cache so a request never re-fetches a static file."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, dict] | None] = {}

    def get(self, key: str, default=_MISSING):
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value


_cache = _Cache()


def _http_fetch_day(day: str) -> dict[str, dict] | None:
    """Fetch + parse one day file. Returns None when the file does not exist
    (a non-trading day / holiday), raises UpstreamError on a real failure."""
    url = SHORT_VOLUME_URL.format(date=day)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    if response.status_code == 404:
        return None
    if response.status_code == 403:
        raise UpstreamError("finra cdn 403 (user-agent required)")
    if response.status_code != 200:
        raise UpstreamError(f"finra cdn HTTP {response.status_code}")
    rows: dict[str, dict] = {}
    for line in response.text.splitlines():
        if not line or line.startswith("Date|"):
            continue
        parts = line.split("|")
        if len(parts) < 5:
            continue
        symbol = parts[1].strip()
        if not symbol:
            continue
        try:
            short = float(parts[2])
            total = float(parts[4])
        except ValueError:
            continue
        rows[symbol] = {"short": short, "total": total}
    return rows


def fetch_day(day: str, *, fetcher=None) -> dict[str, dict] | None:
    """Single-day fetch. An injected ``fetcher`` bypasses the cache (used by
    tests and for a deliberate re-pull); the default HTTP fetcher is cached."""
    if fetcher is not None:
        return fetcher(day)
    cached = _cache.get(day)
    if cached is not _MISSING:
        return cached  # may be None (non-trading day) or a parsed dict
    result = _http_fetch_day(day)
    _cache.set(day, result)
    return result


def _trading_days_back(as_of: date, count: int) -> list[str]:
    """The ``count`` most recent weekdays up to and including ``as_of``."""
    days: list[str] = []
    cursor = as_of
    while len(days) < count:
        if cursor.weekday() < 5:
            days.append(cursor.strftime("%Y%m%d"))
        cursor -= timedelta(days=1)
    return days


def short_volume_ratio(symbol: str, *, days: int = DEFAULT_DAYS,
                       as_of: date | None = None, fetcher=None) -> dict:
    """Rolling short-volume ratio over the last ``days`` trading days."""
    if days < 1:
        raise ValueError("days must be >= 1")
    as_of = as_of or date.today()
    symbol = symbol.strip().upper()
    total_short = 0.0
    total_volume = 0.0
    seen = 0
    for day in _trading_days_back(as_of, days):
        try:
            rows = fetch_day(day, fetcher=fetcher)
        except UpstreamError:
            raise
        if rows is None:
            continue
        seen += 1
        row = rows.get(symbol)
        if row is None:
            continue
        total_short += row["short"]
        total_volume += row["total"]
    ratio = (total_short / total_volume) if total_volume > 0 else None
    return {
        "symbol": symbol,
        "days": days,
        "trading_days_seen": seen,
        "short_volume": round(total_short, 2),
        "total_volume": round(total_volume, 2),
        "short_volume_ratio": round(ratio, 4) if ratio is not None else None,
        "as_of": as_of.isoformat(),
    }


def short_activity(ratio: float | None) -> str:
    """Closed-vocabulary short-activity read from the rolling ratio."""
    if ratio is None:
        return "NO_DATA"
    if ratio < _LOW:
        return "LOW"
    if ratio < _NORMAL:
        return "NORMAL"
    if ratio < _HIGH:
        return "ELEVATED"
    return "HIGH"


def short_context(symbol: str, *, days: int = DEFAULT_DAYS,
                  as_of: date | None = None, fetcher=None) -> dict:
    """Endpoint-shaped summary: ratio + closed-vocabulary activity + freshness."""
    summary = short_volume_ratio(symbol, days=days, as_of=as_of, fetcher=fetcher)
    summary["short_activity"] = short_activity(summary["short_volume_ratio"])
    summary["freshness"] = _FRESHNESS
    summary["source"] = "finra_reg_sho_daily"
    return summary


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)
