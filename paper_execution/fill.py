"""Deterministic, conservative paper fill simulation (PAPER_ONLY).

Prices must be finite and strictly positive; quantities must be positive
integers. Option notional applies the 100-share-per-contract multiplier. Rolls
report a signed net (credit positive, debit negative) across both legs. A
missing/invalid price resolves to UNSCORABLE_EXECUTION_DATA.
"""
from __future__ import annotations

import math

OPTION_CONTRACT_MULTIPLIER = 100


def _finite_positive(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def _positive_integer(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return number.is_integer() and number > 0


def _flow_sign(side: object) -> int:
    text = str(side or "").lower()
    if text.startswith("sell"):
        return 1  # credit
    if text.startswith("buy"):
        return -1  # debit
    return -1


def _multiplier_for(instrument_type: object) -> int:
    text = str(instrument_type or "").upper()
    return OPTION_CONTRACT_MULTIPLIER if text in ("CALL", "PUT") else 1


def simulate_leg(price_reference: object, quantity: object, multiplier: int = 1) -> dict:
    if not _finite_positive(price_reference):
        return {"status": "UNSCORABLE_EXECUTION_DATA", "fill_price": None, "fill_quantity": 0, "notional": None}
    if not _positive_integer(quantity):
        return {"status": "INVALID_QUANTITY", "fill_price": None, "fill_quantity": 0, "notional": None}
    price = float(price_reference)
    qty = int(quantity)
    return {
        "status": "FILLED",
        "fill_price": price,
        "fill_quantity": qty,
        "notional": round(price * qty * multiplier, 2),
    }


def simulate_order(legs: list[dict], *, instrument_type: str = "SHARE") -> dict:
    """Simulate a paper order from one or two legs.

    Each leg is {price_reference, quantity, side}. The contract multiplier is
    derived from instrument_type (CALL/PUT 100x, SHARE 1x). A roll has two legs
    and a signed net (credit positive, debit negative); a missing price on any
    leg makes the whole order UNSCORABLE_EXECUTION_DATA.
    """
    if not legs:
        return {"status": "EMPTY_ORDER", "legs": [], "net": None}
    multiplier = _multiplier_for(instrument_type)
    results = []
    for leg in legs:
        res = simulate_leg(leg.get("price_reference"), leg.get("quantity"), multiplier)
        if res["status"] == "FILLED":
            res["signed_notional"] = round(_flow_sign(leg.get("side")) * res["notional"], 2)
        results.append(res)
    if any(res["status"] == "UNSCORABLE_EXECUTION_DATA" for res in results):
        return {"status": "UNSCORABLE_EXECUTION_DATA", "legs": results, "net": None}
    if any(res["status"] == "INVALID_QUANTITY" for res in results):
        return {"status": "INVALID_QUANTITY", "legs": results, "net": None}
    if any(res["status"] != "FILLED" for res in results):
        return {"status": "UNFILLED", "legs": results, "net": None}
    net = round(sum(res["signed_notional"] for res in results), 2)
    return {"status": "FILLED", "legs": results, "net": net}
