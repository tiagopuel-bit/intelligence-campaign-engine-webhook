"""Positions tracking (beta) — validation + shaping helpers.

Manual position log, no broker, no automatic position creation: a human logs
every entry/exit, the system never opens anything. This module only validates
payloads and shapes rows into JSON. All DB access and the Flask route handlers
live in webhook_receiver.py (which owns state_is_authorized(), get_db(), and
_shape_state()); keeping this module import-free avoids a circular import.

Timestamp convention: entry_time/exit_time/opened_at/closed_at are ISO-8601
strings (matching alerts.received_at). The frontend converts to epoch-ms for
chart alignment against /ohlc bars; nothing here is epoch-ms.
"""
from __future__ import annotations

import re

DIRECTIONS = ("LONG", "SHORT")
POSITION_STATUSES = ("OPEN", "CLOSED")
INSTRUMENT_TYPES = ("SHARE", "CALL", "PUT")
INSTRUMENT_STATUSES = ("OPEN", "CLOSED", "ROLLED")

_SYMBOL_RE = re.compile(r"^[A-Z0-9.\-]{1,10}$")


def clean_symbol(value) -> str | None:
    symbol = (value or "").strip().upper()
    return symbol if _SYMBOL_RE.match(symbol) else None


def _opt_str(value, name) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    if not isinstance(value, str):
        return None, f"{name} must be a string"
    stripped = value.strip()
    return (stripped or None), None


def _opt_float(value, name, *, positive=False) -> tuple[float | None, str | None]:
    if value is None or value == "":
        return None, None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"{name} must be a number"
    if positive and number <= 0:
        return None, f"{name} must be > 0"
    return number, None


def _opt_int(value, name) -> tuple[int | None, str | None]:
    if value is None or value == "":
        return None, None
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"{name} must be an integer"


def validate_position_payload(payload) -> tuple[dict | None, str | None]:
    """Validate the position-level fields of a POST /positions body."""
    if not isinstance(payload, dict):
        return None, "body must be a JSON object"
    symbol = clean_symbol(payload.get("symbol"))
    if symbol is None:
        return None, "symbol is required (1-10 characters)"
    direction = (payload.get("direction") or "").strip().upper()
    if direction not in DIRECTIONS:
        return None, f"direction must be one of {list(DIRECTIONS)}"
    origin_timeframe, err = _opt_str(payload.get("origin_timeframe"), "origin_timeframe")
    if err:
        return None, err
    origin_event, err = _opt_str(payload.get("origin_event"), "origin_event")
    if err:
        return None, err
    notes, err = _opt_str(payload.get("notes"), "notes")
    if err:
        return None, err
    return {
        "symbol": symbol,
        "direction": direction,
        "origin_timeframe": origin_timeframe,
        "origin_event": origin_event,
        "notes": notes,
    }, None


def validate_instrument_payload(payload) -> tuple[dict | None, str | None]:
    """Validate an instrument (leg) body — nested for POST /positions, or
    top-level for POST /positions/<id>/instruments."""
    if not isinstance(payload, dict):
        return None, "instrument is required (a JSON object)"
    itype = (payload.get("type") or "").strip().upper()
    if itype not in INSTRUMENT_TYPES:
        return None, f"instrument.type must be one of {list(INSTRUMENT_TYPES)}"

    quantity, err = _opt_float(payload.get("quantity"), "quantity", positive=True)
    if err:
        return None, err
    if quantity is None:
        return None, "quantity is required"
    entry_price, err = _opt_float(payload.get("entry_price"), "entry_price", positive=True)
    if err:
        return None, err
    if entry_price is None:
        return None, "entry_price is required"
    entry_time, err = _opt_str(payload.get("entry_time"), "entry_time")
    if err:
        return None, err
    if not entry_time:
        return None, "entry_time is required"

    strike, err = _opt_float(payload.get("strike"), "strike", positive=True)
    if err:
        return None, err
    if itype == "SHARE" and strike is not None:
        return None, "SHARE must not have a strike"
    if itype != "SHARE" and strike is None:
        return None, f"{itype} requires a strike"

    expiration, err = _opt_str(payload.get("expiration"), "expiration")
    if err:
        return None, err
    notes, err = _opt_str(payload.get("notes"), "notes")
    if err:
        return None, err
    rolled_from_id, err = _opt_int(payload.get("rolled_from_id"), "rolled_from_id")
    if err:
        return None, err

    return {
        "instrument_type": itype,
        "strike": strike,
        "expiration": expiration,
        "quantity": quantity,
        "entry_price": entry_price,
        "entry_time": entry_time,
        "notes": notes,
        "rolled_from_id": rolled_from_id,
    }, None


def validate_position_update(payload) -> tuple[dict, str | None]:
    if not isinstance(payload, dict):
        return None, "body must be a JSON object"
    clean: dict = {}
    if "status" in payload:
        status = (payload.get("status") or "").strip().upper()
        if status not in POSITION_STATUSES:
            return None, f"status must be one of {list(POSITION_STATUSES)}"
        clean["status"] = status
    if "closed_at" in payload:
        closed_at, err = _opt_str(payload.get("closed_at"), "closed_at")
        if err:
            return None, err
        clean["closed_at"] = closed_at
    if "notes" in payload:
        notes, err = _opt_str(payload.get("notes"), "notes")
        if err:
            return None, err
        clean["notes"] = notes
    if not clean:
        return None, "no updatable fields provided (status, closed_at, notes)"
    return clean, None


def validate_instrument_update(payload) -> tuple[dict, str | None]:
    if not isinstance(payload, dict):
        return None, "body must be a JSON object"
    clean: dict = {}
    if "exit_price" in payload:
        exit_price, err = _opt_float(payload.get("exit_price"), "exit_price", positive=True)
        if err:
            return None, err
        clean["exit_price"] = exit_price
    if "exit_time" in payload:
        exit_time, err = _opt_str(payload.get("exit_time"), "exit_time")
        if err:
            return None, err
        clean["exit_time"] = exit_time
    if "status" in payload:
        status = (payload.get("status") or "").strip().upper()
        if status not in INSTRUMENT_STATUSES:
            return None, f"status must be one of {list(INSTRUMENT_STATUSES)}"
        clean["status"] = status
    if "rolled_to_id" in payload:
        rolled_to_id, err = _opt_int(payload.get("rolled_to_id"), "rolled_to_id")
        if err:
            return None, err
        clean["rolled_to_id"] = rolled_to_id
    if "notes" in payload:
        notes, err = _opt_str(payload.get("notes"), "notes")
        if err:
            return None, err
        clean["notes"] = notes
    if not clean:
        return None, "no updatable fields provided (exit_price, exit_time, status, rolled_to_id, notes)"
    return clean, None


def shape_instrument(row) -> dict:
    return {
        "id": row["id"],
        "position_id": row["position_id"],
        "instrument_type": row["instrument_type"],
        "strike": row["strike"],
        "expiration": row["expiration"],
        "quantity": row["quantity"],
        "entry_price": row["entry_price"],
        "entry_time": row["entry_time"],
        "exit_price": row["exit_price"],
        "exit_time": row["exit_time"],
        "status": row["status"],
        "rolled_from_id": row["rolled_from_id"],
        "rolled_to_id": row["rolled_to_id"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def shape_position(row, instrument_count=0, open_instrument_count=0) -> dict:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "direction": row["direction"],
        "status": row["status"],
        "opened_at": row["opened_at"],
        "closed_at": row["closed_at"],
        "origin_timeframe": row["origin_timeframe"],
        "origin_event": row["origin_event"],
        "notes": row["notes"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "instrument_count": instrument_count,
        "open_instrument_count": open_instrument_count,
    }
