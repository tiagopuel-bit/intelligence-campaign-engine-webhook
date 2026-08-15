"""Research-only live-shadow observation envelope for Options DNA.

The envelope makes data freshness and calibration status explicit. It cannot
emit a near-entry/near-exit label without both a current contract observation
and a named frozen calibration version.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone


ENTITLEMENT_MAX_AGE_MINUTES = {
    "REALTIME": 5.0,
    "DELAYED_15M": 30.0,
}


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"invalid timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_shadow_observation(
    *, symbol: str, contract_ticker: str, decision_available_utc: str,
    option_data_as_of_utc: str, entitlement: str,
    underlying_context: dict, contract_components: dict,
    catalyst_context: dict, position_context: dict,
    calibration_version: str | None = None,
) -> dict:
    decision = _timestamp(decision_available_utc)
    option_time = _timestamp(option_data_as_of_utc)
    age_minutes = (decision - option_time).total_seconds() / 60.0
    entitlement = entitlement.strip().upper()
    if entitlement not in {"END_OF_DAY", "DELAYED_15M", "REALTIME"}:
        raise ValueError("unknown option-data entitlement")

    component_ready = bool(contract_components.get("ready"))
    if not component_ready:
        gate = "UNRELIABLE"
    elif age_minutes < 0:
        gate = "FUTURE_DATA_REJECTED"
    elif entitlement == "END_OF_DAY":
        gate = "EOD_ONLY"
    elif age_minutes > ENTITLEMENT_MAX_AGE_MINUTES[entitlement]:
        gate = "STALE"
    elif not calibration_version:
        gate = "UNCALIBRATED"
    else:
        gate = "READY_FOR_SHADOW_RULES"

    fact_payload = {
        "underlying": underlying_context,
        "contract": contract_components,
        "catalyst": catalyst_context,
        "position": position_context,
        "gate": gate,
    }
    identity = {
        "symbol": symbol.upper(),
        "contract_ticker": contract_ticker.upper(),
        "decision_available_utc": decision.isoformat(),
    }
    return {
        **identity,
        "observation_id": _stable_hash(identity),
        "option_data_as_of_utc": option_time.isoformat(),
        "option_data_age_minutes": age_minutes,
        "option_data_entitlement": entitlement,
        "component_ready": component_ready,
        "quality_reasons": list(contract_components.get("quality_reasons") or []),
        "calibration_version": calibration_version,
        "gate": gate,
        "eligible_for_intraday_guidance": gate == "READY_FOR_SHADOW_RULES",
        # Candidate labels are populated by a separately frozen rule bundle.
        # This pre-calibration envelope must never improvise one.
        "candidate_labels": [],
        "navigation_scope": position_context.get("scope"),
        "fact_signature": _stable_hash(fact_payload),
        "facts": fact_payload,
    }


def transition_changed(previous: dict | None, current: dict) -> bool:
    """True only for the first observation or a material fact/gate change."""
    if previous is None:
        return True
    return (
        previous.get("fact_signature") != current.get("fact_signature")
        or previous.get("gate") != current.get("gate")
        or previous.get("navigation_scope") != current.get("navigation_scope")
    )
