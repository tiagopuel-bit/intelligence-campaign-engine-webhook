"""Massive (Polygon) options provider for the positions valuation + chain picker.

Free-plan scope, verified by probe (2026-08-13):
  - options contracts reference (/v3/reference/options/contracts)  -> 200, free
  - option aggregate bars    (/v2/aggs/ticker/O:.../range/...)      -> 200, free
  - options snapshot         (/v3/snapshot/options/<underlying>)    -> 403, paid

So this module exposes the chain and per-contract OHLCV only. "Current price"
is the latest daily close (near-live), not a real-time bid/ask, and there are
no Greeks. Shares the rate limiter and API key with massive_ohlc so the single
free-plan budget isn't double-spent.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from massive_ohlc import api_key, limiter

BASE_URL = "https://api.massive.com"
CHAIN_TTL_SECONDS = 3600
QUOTE_TTL_SECONDS = 900

# Bounded option OHLC ladder for the /options/ohlc chart route.
# canonical timeframe -> (multiplier, span, lookback_days, cache_ttl_seconds)
OPTION_TIMEFRAMES: dict[str, tuple[int, str, int, int]] = {
    "5m": (5, "minute", 30, 300),
    "15m": (15, "minute", 60, 300),
    "30m": (30, "minute", 90, 300),
    "1H": (60, "minute", 180, 600),
    "4H": (240, "minute", 180, 600),
    "D": (1, "day", 400, 3600),
}

# Massive option ticker: O:<underlying><YYMMDD><C|P><8-digit strike x1000>.
_OPTION_TICKER_RE = re.compile(r"^O:[A-Z0-9.\-]{1,10}\d{6}[CP]\d{8}$")


def valid_option_ticker(raw: str) -> str | None:
    ticker = (raw or "").strip().upper()
    return ticker if _OPTION_TICKER_RE.match(ticker) else None


def resolve_option_timeframe(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw in OPTION_TIMEFRAMES:
        return raw
    low = raw.lower()
    aliases = {
        "5": "5m", "5m": "5m",
        "15": "15m", "15m": "15m",
        "30": "30m", "30m": "30m",
        "60": "1H", "1h": "1H",
        "240": "4H", "4h": "4H",
        "1d": "D", "d": "D", "daily": "D", "day": "D",
    }
    return aliases.get(low)


class UpstreamError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


_chain_cache: dict[str, tuple[float, dict]] = {}
_quote_cache: dict[str, tuple[float, dict]] = {}
_option_ohlc_cache: dict[tuple[str, str], tuple[float, tuple[list[dict], dict]]] = {}
_cache_lock = threading.Lock()


def option_ticker(symbol: str, contract_type: str, strike: float, expiration: str) -> str:
    """Build a Massive options ticker, e.g. O:AMC260918C00003000."""
    d = expiration.replace("-", "")
    yy, mm, dd = d[2:4], d[4:6], d[6:8]
    ct = "C" if contract_type.upper() == "CALL" else "P"
    strike_int = int(round(float(strike) * 1000))
    return f"O:{symbol}{yy}{mm}{dd}{ct}{strike_int:08d}"


def _get(url: str, params: dict) -> list[dict]:
    """Rate-limited GET with 429 recovery; returns accumulated `results`."""
    rows: list[dict] = []
    for attempt in range(4):
        limiter.wait()
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 429:
            try:
                delay = min(65.0, max(1.0, float(response.headers.get("Retry-After", 60))))
            except ValueError:
                delay = 60.0
            time.sleep(delay)
            continue
        if response.status_code != 200:
            raise UpstreamError(response.status_code, response.text[:300])
        payload = response.json()
        rows.extend(payload.get("results", []))
        nxt = payload.get("next_url")
        if not nxt:
            return rows
        url = nxt + ("&" if "?" in nxt else "?") + f"apiKey={api_key()}"
        params = {}
    raise UpstreamError(429, "rate limited after retries")


def get_chain(symbol: str) -> dict:
    """Return {symbol, expirations, contracts} for the underlying, cached."""
    clean = (symbol or "").strip().upper()
    now = time.monotonic()
    with _cache_lock:
        cached = _chain_cache.get(clean)
        if cached and now - cached[0] < CHAIN_TTL_SECONDS:
            return cached[1]

    rows = _get(
        f"{BASE_URL}/v3/reference/options/contracts",
        {"underlying_ticker": clean, "limit": "1000", "order": "asc",
         "sort": "expiration_date", "apiKey": api_key()},
    )
    contracts = [
        {
            "ticker": r["ticker"],
            "contract_type": (r.get("contract_type") or "").upper(),
            "strike": r.get("strike_price"),
            "expiration": r.get("expiration_date"),
            "shares_per_contract": r.get("shares_per_contract", 100),
        }
        for r in rows
        if r.get("strike_price") is not None and r.get("expiration_date")
    ]
    contracts.sort(key=lambda c: (c["expiration"], c["strike"], c["contract_type"]))
    result = {
        "symbol": clean,
        "expirations": sorted({c["expiration"] for c in contracts}),
        "contracts": contracts,
    }
    with _cache_lock:
        _chain_cache[clean] = (time.monotonic(), result)
    return result


def get_option_quote(symbol: str, contract_type: str, strike: float, expiration: str) -> dict | None:
    """Return {ticker, current, prev, last_t} for a contract, cached. None if no bars."""
    ticker = option_ticker(symbol, contract_type, strike, expiration)
    now = time.monotonic()
    with _cache_lock:
        cached = _quote_cache.get(ticker)
        if cached and now - cached[0] < QUOTE_TTL_SECONDS:
            return cached[1]

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=10)
    bars = _get(
        f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/1/day/{start:%Y-%m-%d}/{end:%Y-%m-%d}",
        {"adjusted": "true", "sort": "asc", "limit": "50", "apiKey": api_key()},
    )
    if not bars:
        return None
    current = bars[-1]["c"]
    prev = bars[-2]["c"] if len(bars) >= 2 else current
    quote = {"ticker": ticker, "current": current, "prev": prev, "last_t": bars[-1]["t"]}
    with _cache_lock:
        _quote_cache[ticker] = (time.monotonic(), quote)
    return quote


def _shape_bars(rows: list[dict]) -> list[dict]:
    """Normalize raw Massive bars to {t,o,h,l,c,v}, ascending + duplicate-free."""
    bars = [
        {"t": int(r["t"]), "o": r["o"], "h": r["h"], "l": r["l"], "c": r["c"], "v": r["v"]}
        for r in rows
    ]
    bars.sort(key=lambda b: b["t"])
    seen: set[int] = set()
    out: list[dict] = []
    for b in bars:
        if b["t"] not in seen:
            seen.add(b["t"])
            out.append(b)
    return out


def get_option_ohlc(ticker: str, timeframe: str) -> tuple[list[dict], dict]:
    """Return (bars, meta) of full contract OHLCV for a Massive option ticker.

    Raises ValueError for an invalid ticker/timeframe and UpstreamError for
    vendor/auth problems. The caller maps those to HTTP responses. "Latest
    close" here is a delayed daily/aggregate close -- never a live quote.
    """
    clean = valid_option_ticker(ticker)
    if clean is None:
        raise ValueError(f"invalid option ticker: {ticker}")
    canonical = resolve_option_timeframe(timeframe)
    if canonical is None:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    if not api_key():
        raise UpstreamError(503, "Massive API key not configured")

    key = (clean, canonical)
    multiplier, span, days, ttl = OPTION_TIMEFRAMES[canonical]
    now = time.monotonic()
    with _cache_lock:
        cached = _option_ohlc_cache.get(key)
        if cached and now - cached[0] < ttl:
            bars, meta = cached[1]
            return bars, dict(meta, cached=True)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    rows = _get(
        f"{BASE_URL}/v2/aggs/ticker/{clean}/range/{multiplier}/{span}/{start:%Y-%m-%d}/{end:%Y-%m-%d}",
        {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key()},
    )
    bars = _shape_bars(rows)
    meta = {
        "ticker": clean,
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
        _option_ohlc_cache[key] = (time.monotonic(), (bars, meta))
    return bars, meta
