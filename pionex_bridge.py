"""Read-only Pionex spot-wallet bridge.

Railway credentials come from environment variables. For local development
only, the existing sibling ``Pionex/.env`` file is accepted as a fallback.
This module never places orders and the balance API excludes bot/earn funds.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path


BASE_URL = "https://api.pionex.com"
LOCAL_ENV_PATH = Path(__file__).resolve().parent.parent / "Pionex" / ".env"
STABLECOINS = {
    "USDT", "USDC", "TUSD", "BUSD", "DAI", "FDUSD", "USDP", "UST",
    "USD1", "USD",
}
USER_AGENT = "DNA-Portfolio/1.0 (read-only Pionex wallet)"


def load_env(path: Path = LOCAL_ENV_PATH) -> dict[str, str]:
    """Load a local development env file without mutating ``os.environ``."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _credentials() -> tuple[str, str]:
    local = load_env()
    key = os.environ.get("PIONEX_API_KEY") or local.get("PIONEX_API_KEY", "")
    secret = os.environ.get("PIONEX_API_SECRET") or local.get(
        "PIONEX_API_SECRET", ""
    )
    if not key or not secret:
        raise RuntimeError("Pionex credentials are not configured")
    return key, secret


def _read_json(request: urllib.request.Request) -> dict:
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("result") is False:
        raise RuntimeError(
            f"Pionex API error {payload.get('code')}: {payload.get('message')}"
        )
    return payload.get("data", {})


def _signed_request(method: str, path: str, params: dict | None = None) -> dict:
    key, secret = _credentials()
    signed = dict(params or {})
    signed["timestamp"] = str(int(time.time() * 1000))
    signature_query = "&".join(f"{k}={v}" for k, v in sorted(signed.items()))
    message = f"{method}{path}?{signature_query}"
    signature = hmac.new(
        secret.encode(), message.encode(), hashlib.sha256
    ).hexdigest()
    url = BASE_URL + path + "?" + urllib.parse.urlencode(sorted(signed.items()))
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("PIONEX-KEY", key)
    request.add_header("PIONEX-SIGNATURE", signature)
    return _read_json(request)


def get_balances() -> list[dict]:
    return _signed_request("GET", "/api/v1/account/balances").get("balances", [])


def get_tickers() -> list[dict]:
    request = urllib.request.Request(BASE_URL + "/api/v1/market/tickers")
    request.add_header("User-Agent", USER_AGENT)
    return _read_json(request).get("tickers", [])


def _price_map(tickers: list[dict]) -> dict[str, float]:
    prices: dict[str, float] = {}
    btc_pairs: list[tuple[str, float]] = []
    btc_usdt = None
    for ticker in tickers:
        symbol = str(ticker.get("symbol") or "")
        try:
            close = float(ticker["close"])
            base, quote = symbol.split("_", 1)
        except (KeyError, TypeError, ValueError):
            continue
        if symbol == "BTC_USDT":
            btc_usdt = close
        if quote in STABLECOINS:
            prices[base] = close
        elif quote == "BTC":
            btc_pairs.append((base, close))
    if btc_usdt is not None:
        for base, close in btc_pairs:
            prices.setdefault(base, close * btc_usdt)
    return prices


def portfolio_summary() -> dict:
    """Return priced spot-wallet balances; bot and earn funds are unavailable."""
    prices = _price_map(get_tickers())
    rows = []
    total_value = 0.0
    for raw in get_balances():
        coin = str(raw.get("coin") or "").upper()
        try:
            free = float(raw.get("free") or 0)
            frozen = float(raw.get("frozen") or 0)
        except (TypeError, ValueError):
            continue
        total = free + frozen
        price = 1.0 if coin in STABLECOINS else prices.get(coin)
        value = total * price if price is not None else None
        if value is not None:
            total_value += value
        rows.append({
            "coin": coin,
            "free": free,
            "frozen": frozen,
            "total": total,
            "price_usd": price,
            "value_usd": value,
        })
    rows.sort(
        key=lambda row: -(row["value_usd"] if row["value_usd"] is not None else -1)
    )
    return {
        "balances": rows,
        "total_value_usd": round(total_value, 2),
        "unpriced_coins": [row["coin"] for row in rows if row["value_usd"] is None],
    }
