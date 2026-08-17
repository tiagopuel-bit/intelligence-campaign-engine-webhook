"""Protective bracket (stop-loss + take-profit) validation and trigger decision.

Pure helpers for the paper-execution bracket feature. A bracket is a
pre-registered standing order: the runner evaluates it against the latest bar
close and fires a protective close WITHOUT the approval window. The fill model
is honest bar-close only (no intrabar, no bid/ask).
"""
from __future__ import annotations

import math


def _finite_positive(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if (math.isfinite(number) and number > 0) else None


def validate_bracket_payload(payload) -> tuple[dict | None, str | None]:
    """Validate the client-supplied bracket fields; server derives direction,
    instrument type and symbol from the paper position, never from the client."""
    if not isinstance(payload, dict):
        return None, "body must be a JSON object"
    allowed = {"experiment_id", "ticker", "stop_price", "target_price", "created_by"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        return None, "unsupported fields: " + ", ".join(unknown)
    experiment_id = payload.get("experiment_id")
    if not isinstance(experiment_id, int) or experiment_id <= 0:
        return None, "experiment_id must be a positive integer"
    ticker = (payload.get("ticker") or "").strip().upper()
    if not ticker:
        return None, "ticker is required"
    stop_price = _finite_positive(payload.get("stop_price"))
    if payload.get("stop_price") not in (None, "") and stop_price is None:
        return None, "stop_price must be a positive number"
    target_price = _finite_positive(payload.get("target_price"))
    if payload.get("target_price") not in (None, "") and target_price is None:
        return None, "target_price must be a positive number"
    if stop_price is None and target_price is None:
        return None, "at least one of stop_price or target_price is required"
    created_by = (payload.get("created_by") or "user").strip().lower()
    if created_by not in ("user", "system"):
        return None, "created_by must be 'user' or 'system'"
    return {
        "experiment_id": experiment_id,
        "ticker": ticker,
        "stop_price": stop_price,
        "target_price": target_price,
        "created_by": created_by,
    }, None


def validate_side(direction: str, stop_price, target_price) -> bool:
    """A bracket must sit on the correct side: for a long, stop below target;
    for a short, target below stop."""
    if stop_price is None or target_price is None:
        return True
    if direction == "LONG":
        return stop_price < target_price
    return target_price < stop_price


def bracket_decision(bracket: dict, close_price) -> str | None:
    """Return the crossed side ('STOP' / 'TARGET') when the bar close crosses a
    level, else None. Bar-close only — no intrabar fill."""
    if close_price is None:
        return None
    direction = bracket.get("direction")
    stop = bracket.get("stop_price")
    target = bracket.get("target_price")
    if direction == "LONG":
        if stop is not None and close_price <= stop:
            return "STOP"
        if target is not None and close_price >= target:
            return "TARGET"
    else:
        if stop is not None and close_price >= stop:
            return "STOP"
        if target is not None and close_price <= target:
            return "TARGET"
    return None
