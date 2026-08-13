"""Near-live OHLC provider for the /ohlc endpoint.

Fetches RAW consolidated aggregate bars from the Massive free plan
(https://api.massive.com) for the DNA Asset Landing Page price chart.

Design notes
------------
- Native Massive aggregate bars are returned as-is (o/h/l/c/v per bar,
  ascending, split-adjusted). Intraday minute bars are anchored to the
  extended-session open (04:00 ET); 2H/3H/4H may drift across DST changes.
  This is honest RAW consolidated price data, not an RTH-filtered study
  ladder -- the same separation the snapshot pipeline enforces.
- The Massive free plan is rate-limited (~5 requests/minute); a process-wide
  fixed-interval limiter plus a per-(symbol, timeframe) TTL cache keep the
  endpoint from hammering the vendor. Caching is in-memory and per-process,
  which matches the single-worker gunicorn deployment.
- Credentials are read from MASSIVE_API_KEY (or POLYGON_API_KEY) only; the
  key is never logged, returned, or written to disk.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

BASE_URL = "https://api.massive.com"
FREE_PLAN_REQUESTS_PER_MINUTE = 5
DEFAULT_CACHE_TTL_SECONDS = 60

# canonical timeframe -> (multiplier, span, lookback_days, cache_ttl_seconds)
TIMEFRAMES: dict[str, tuple[int, str, int, int]] = {
    "3m": (3, "minute", 5, 60),
    "5m": (5, "minute", 7, 120),
    "15m": (15, "minute", 14, 120),
    "30m": (30, "minute", 30, 180),
    "1H": (60, "minute", 60, 300),
    "2H": (120, "minute", 90, 300),
    "3H": (180, "minute", 120, 300),
    "4H": (240, "minute", 180, 300),
    "D": (1, "day", 400, 3600),
}

# Accept the webhook's numeric labels ("5", "120", "1D") and the packet's
# human labels ("3m", "1H", "4H", "D") interchangeably.
_ALIASES: dict[str, str] = {}
for _canon in TIMEFRAMES:
    _ALIASES[_canon.lower()] = _canon
    _ALIASES[_canon.lower().replace("m", "")] = _canon  # 3m -> 3
    if _canon.endswith("H"):
        _ALIASES[_canon[:-1].lower()] = _canon  # 1H -> 1
for _n, _canon in (("5", "5m"), ("15", "15m"), ("30", "30m"),
                   ("60", "1H"), ("120", "2H"), ("180", "3H"), ("240", "4H"),
                   ("1D", "D"), ("1d", "D"), ("daily", "D"), ("day", "D")):
    _ALIASES[_n] = _canon
    _ALIASES[_n.lower()] = _canon

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


class _Limiter:
    """Process-wide fixed-interval limiter for the Massive free plan."""

    def __init__(self, requests_per_minute: int) -> None:
        self._interval = 60.0 / requests_per_minute
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            delay = self._interval - (time.monotonic() - self._last)
            if delay > 0:
                time.sleep(delay)
            self._last = time.monotonic()


_limiter = _Limiter(FREE_PLAN_REQUESTS_PER_MINUTE)
_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def api_key() -> str:
    return os.environ.get("MASSIVE_API_KEY") or os.environ.get("POLYGON_API_KEY") or ""


def resolve_timeframe(raw: str) -> str | None:
    """Map a user-provided timeframe label to a canonical one, or None."""
    if not raw:
        return None
    return _ALIASES.get(raw.strip().lower())


def valid_symbol(raw: str) -> str | None:
    symbol = (raw or "").strip().upper()
    return symbol if _SYMBOL_RE.match(symbol) else None


def _fetch_raw(symbol: str, canonical: str) -> list[dict]:
    multiplier, span, days, _ttl = TIMEFRAMES[canonical]
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    url = (f"{BASE_URL}/v2/aggs/ticker/{symbol}/range/"
           f"{multiplier}/{span}/{start:%Y-%m-%d}/{end:%Y-%m-%d}")
    params = {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key()}
    rows: list[dict] = []
    for attempt in range(4):
        _limiter.wait()
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            try:
                delay = min(65.0, max(1.0, float(retry_after))) if retry_after else 60.0
            except ValueError:
                delay = 60.0
            time.sleep(delay)
            continue
        if response.status_code != 200:
            raise _UpstreamError(response.status_code, response.text[:300])
        payload = response.json()
        rows.extend(payload.get("results", []))
        nxt = payload.get("next_url")
        if not nxt:
            break
        url = nxt + ("&" if "?" in nxt else "?") + f"apiKey={api_key()}"
        params = {}
    else:
        raise _UpstreamError(429, "rate limited after retries")
    return rows


class _UpstreamError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _shape(rows: list[dict]) -> list[dict]:
    bars = [
        {"t": int(r["t"]), "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"]}
        for r in rows
    ]
    bars.sort(key=lambda b: b["t"])
    return bars


def get_ohlc(symbol: str, timeframe: str) -> tuple[list[dict], dict]:
    """Return (bars, meta) for a symbol/timeframe, cached.

    Raises ValueError for an unknown symbol/timeframe and _UpstreamError for
    vendor/auth problems. The caller maps those to HTTP responses.
    """
    canonical = resolve_timeframe(timeframe)
    if canonical is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    clean_symbol = valid_symbol(symbol)
    if clean_symbol is None:
        raise ValueError(f"invalid symbol: {symbol}")
    if not api_key():
        raise _UpstreamError(503, "Massive API key not configured")

    key = (clean_symbol, canonical)
    _mult, _span, _days, ttl = TIMEFRAMES[canonical]
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < ttl:
            bars, meta = cached[1]
            return bars, dict(meta, cached=True)

    rows = _fetch_raw(clean_symbol, canonical)
    bars = _shape(rows)
    meta = {
        "symbol": clean_symbol,
        "timeframe": canonical,
        "source": "massive",
        "adjusted": True,
        "bar_count": len(bars),
        "start": datetime.fromtimestamp(bars[0]["t"] / 1000, tz=timezone.utc).isoformat() if bars else None,
        "end": datetime.fromtimestamp(bars[-1]["t"] / 1000, tz=timezone.utc).isoformat() if bars else None,
        "cached": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    with _cache_lock:
        _cache[key] = (time.monotonic(), (bars, meta))
    return bars, meta
