"""Server-side reconstruction of proposal evidence from authoritative state.

Clients never submit very_high, evidence roots, freshness, price source or
policy eligibility. The API loads an authoritative state snapshot and this
module deterministically reconstructs the causal evidence that feeds the
engine. No future-outcome data is read.
"""
from __future__ import annotations


def reconstruct_evidence(state: dict | None, symbol: str, action: str) -> dict | None:
    """Build the causal evidence dict from an authoritative state snapshot.

    Returns None when there is no authoritative state (caller must block), so a
    missing/delayed heartbeat never becomes a synthetic fill.
    """
    if not state:
        return None
    underlying = state.get("underlying") or {}
    contract = state.get("contract") or {}
    execution = state.get("execution") or {}
    position = state.get("position") or {}
    catalyst = state.get("catalyst") or {}

    return {
        "underlying_dna": {
            "confirm_tone": underlying.get("confirm_tone"),
            "timing_tone": underlying.get("timing_tone"),
            "upper_neg": bool(underlying.get("upper_neg", False)),
            "bar_time": underlying.get("bar_time"),
            "source": underlying.get("source"),
        },
        "contract_response": {
            "option_return": contract.get("option_return"),
            "matched_bars": contract.get("matched_bars"),
            "activity_ratio": contract.get("activity_ratio"),
            "missing_bar": bool(contract.get("missing_bar", False)),
            "unchanged_print": bool(contract.get("unchanged_print", False)),
            "bar_time": contract.get("bar_time"),
            "source": contract.get("source"),
        },
        "execution_quality": {
            "bar_time": execution.get("bar_time"),
            "source": execution.get("source"),
            "price_reference": execution.get("price_reference"),
            "stale": bool(execution.get("stale", False)),
        },
        "portfolio_risk": {
            "position_exists": bool(position.get("exists", False)),
            "direction": position.get("direction"),
            "side": position.get("side"),
            "trigger": position.get("trigger"),
            "exposure_ok": position.get("exposure_ok", True),
            "duplicate": bool(position.get("duplicate", False)),
            "conflict": bool(position.get("conflict", False)),
            "daily_loss_ok": position.get("daily_loss_ok", True),
        },
        "catalyst": {"sec_veto": bool(catalyst.get("sec_veto", False))},
        "stale_underlying": bool(state.get("stale_underlying", False)),
        "stale_option_quote": bool(state.get("stale_option_quote", False)),
    }


def reconstruct_legs(state: dict | None, symbol: str, action: str):
    """Reconstruct server-side order legs + instrument type from the state.

    The leg price is the contract's own fill price (leg_price), which is
    distinct from the deterministic underlying reference used by the
    execution-quality root. Returns (legs, instrument_type), or (None, None)
    when no authoritative state exists."""
    if not state:
        return None, None
    position = state.get("position") or {}
    execution = state.get("execution") or {}
    instrument_type = str(position.get("instrument_type") or "SHARE").upper()
    if "leg_price" in execution:
        leg_price = execution.get("leg_price")
    else:
        leg_price = execution.get("price_reference")
    if action == "roll":
        roll_legs = state.get("roll_legs") or []
        if len(roll_legs) != 2:
            return None, instrument_type
        legs = [{
            "ticker": leg.get("ticker"), "side": leg.get("side"),
            "quantity": leg.get("quantity", 0), "price_reference": leg.get("price_reference"),
            "instrument_type": str(leg.get("instrument_type") or instrument_type).upper(),
        } for leg in roll_legs]
        return legs, instrument_type
    legs = [{
        "ticker": position.get("ticker") or symbol,
        "side": position.get("side"),
        "quantity": position.get("quantity", 0),
        "price_reference": leg_price,
        "instrument_type": instrument_type,
    }]
    return legs, instrument_type
