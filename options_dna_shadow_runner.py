"""Provider-neutral execution boundary for one Options DNA shadow observation."""
from __future__ import annotations

import sqlite3

from options_dna_guidance import FrozenGuidanceBundle, apply_shadow_bundle
from options_dna_shadow import build_shadow_observation
from options_dna_shadow_journal import record_shadow_observation


REQUIRED_INPUT_FIELDS = {
    "symbol", "contract_ticker", "decision_available_utc",
    "option_data_as_of_utc", "entitlement", "underlying_context",
    "contract_components", "catalyst_context", "position_context",
}


def run_shadow_once(
    connection: sqlite3.Connection, payload: dict, bundle: FrozenGuidanceBundle,
    *, observed_at_utc: str,
) -> dict:
    """Build, evaluate, and append one causal observation without fetching data."""
    missing = sorted(REQUIRED_INPUT_FIELDS - set(payload))
    if missing:
        raise ValueError(f"shadow input missing required fields: {missing!r}")
    observation = build_shadow_observation(
        symbol=payload["symbol"],
        contract_ticker=payload["contract_ticker"],
        decision_available_utc=payload["decision_available_utc"],
        option_data_as_of_utc=payload["option_data_as_of_utc"],
        entitlement=payload["entitlement"],
        underlying_context=payload["underlying_context"],
        contract_components=payload["contract_components"],
        catalyst_context=payload["catalyst_context"],
        position_context=payload["position_context"],
        calibration_version=bundle.version,
    )
    evaluated = apply_shadow_bundle(observation, bundle)
    journal = record_shadow_observation(
        connection, evaluated, observed_at_utc=observed_at_utc,
    )
    return {"observation": evaluated, "journal": journal}
