"""Position-context facts for Options DNA navigation.

The current positions API records purchased CALL/PUT instruments. This module
routes the eventual vocabulary between observation and open-position
management, but it does not create entry, exit, size, or roll instructions.
"""
from __future__ import annotations

from datetime import date, datetime, timezone


def _datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value not in (None, "") else None
    except ValueError:
        return None


def observation_context(*, symbol: str, as_of: str) -> dict:
    observed = _datetime(as_of)
    if observed is None:
        raise ValueError("invalid as_of timestamp")
    return {
        "symbol": symbol.upper(),
        "scope": "OBSERVE_ENTRY",
        "has_open_position": False,
        "as_of": observed.isoformat(),
    }


def long_option_position_context(
    option: dict, *, symbol: str, underlying_current: float,
    as_of: str, price_source: str,
) -> dict:
    """Normalize one valuation option row into factual position context."""
    observed = _datetime(as_of)
    contract = option.get("contract") or {}
    ctype = str(contract.get("type") or "").upper()
    expiry = _date(contract.get("expiration"))
    entered = _datetime(option.get("first_entry"))
    try:
        strike = float(contract["strike"])
        current = float(option["current_price"])
        average = float(option["avg_cost"])
        quantity = float(option["contracts"])
        underlying = float(underlying_current)
    except (KeyError, TypeError, ValueError):
        raise ValueError("invalid option valuation fields") from None
    if observed is None or entered is None or expiry is None:
        raise ValueError("invalid position timestamps")
    if ctype not in {"CALL", "PUT"} or min(strike, current, average, quantity, underlying) <= 0:
        raise ValueError("invalid option contract values")

    sign = 1.0 if ctype == "CALL" else -1.0
    intrinsic = max(0.0, underlying - strike) if ctype == "CALL" else max(0.0, strike - underlying)
    extrinsic = max(0.0, current - intrinsic)
    dte = max(0, (expiry - observed.date()).days)
    held_days = max(0, (observed.date() - entered.date()).days)
    lifecycle_days = max(1, (expiry - entered.date()).days)
    return {
        "symbol": symbol.upper(),
        "scope": "MANAGE_OPEN_LONG_PREMIUM",
        "has_open_position": True,
        "instrument_side": "LONG_PREMIUM",
        "contract_type": ctype,
        "strike": strike,
        "expiration": expiry.isoformat(),
        "contracts": quantity,
        "current_price": current,
        "average_cost": average,
        "total_pnl": option.get("total_pnl"),
        "total_return_pct": option.get("total_return_pct"),
        "dte": dte,
        "held_days": held_days,
        "lifecycle_elapsed": min(1.0, held_days / lifecycle_days),
        "moneyness_pct": sign * (underlying - strike) / strike * 100.0,
        "intrinsic_value": intrinsic,
        "extrinsic_value_observed": extrinsic,
        "extrinsic_share_observed": extrinsic / current if current > 0 else None,
        "price_source": price_source,
        "as_of": observed.isoformat(),
        "direction_claim": None,
    }
