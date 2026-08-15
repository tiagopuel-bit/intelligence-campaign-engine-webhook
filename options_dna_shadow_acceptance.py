"""Frozen, auditable acceptance criteria for Options DNA live shadowing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass

from options_dna_guidance import FrozenGuidanceBundle, validate_bundle
from options_dna_shadow_journal import assess_shadow_promotion_readiness


SHADOW_ACCEPTANCE_CRITERIA_V1 = {
    "version": "options-dna-shadow-acceptance-v1",
    "frozen_before_expansion_results": True,
    "required_cells": [
        ["CALL", 14], ["CALL", 30], ["PUT", 14], ["PUT", 30],
    ],
    "min_contracts_per_cell": 3,
    "min_unique_decisions_per_cell": 20,
    "min_calendar_days_per_cell": 20,
    "min_transitions_per_cell": 10,
    "min_labeled_observations_per_cell": 10,
    "max_ineligible_fraction_per_cell": 0.2,
    "max_reversal_fraction_per_cell": 0.2,
    "notes": [
        "Every threshold is evaluated independently by contract type and target DTE.",
        "Unclassified observations cannot satisfy a required cell.",
        "This gate validates freshness and transition stability, not trade profitability.",
        "Passing does not authorize production guidance or exact trade orders.",
    ],
}


@dataclass(frozen=True)
class ShadowAcceptanceCriteria:
    version: str
    required_cells: tuple[tuple[str, int], ...]
    min_contracts_per_cell: int
    min_unique_decisions_per_cell: int
    min_calendar_days_per_cell: int
    min_transitions_per_cell: int
    min_labeled_observations_per_cell: int
    max_ineligible_fraction_per_cell: float
    max_reversal_fraction_per_cell: float

    @property
    def criteria_hash(self) -> str:
        raw = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def criteria_from_dict(payload: dict) -> ShadowAcceptanceCriteria:
    try:
        criteria = ShadowAcceptanceCriteria(
            version=str(payload["version"]),
            required_cells=tuple(
                (str(contract_type).upper(), int(dte))
                for contract_type, dte in payload["required_cells"]
            ),
            min_contracts_per_cell=int(payload["min_contracts_per_cell"]),
            min_unique_decisions_per_cell=int(payload["min_unique_decisions_per_cell"]),
            min_calendar_days_per_cell=int(payload["min_calendar_days_per_cell"]),
            min_transitions_per_cell=int(payload["min_transitions_per_cell"]),
            min_labeled_observations_per_cell=int(
                payload["min_labeled_observations_per_cell"]
            ),
            max_ineligible_fraction_per_cell=float(
                payload["max_ineligible_fraction_per_cell"]
            ),
            max_reversal_fraction_per_cell=float(
                payload["max_reversal_fraction_per_cell"]
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid shadow acceptance criteria: {exc}") from None
    validate_criteria(criteria)
    return criteria


def validate_criteria(criteria: ShadowAcceptanceCriteria) -> None:
    if not criteria.version:
        raise ValueError("criteria version is required")
    if not criteria.required_cells or len(set(criteria.required_cells)) != len(
        criteria.required_cells
    ):
        raise ValueError("required cells must be non-empty and unique")
    if any(
        contract_type not in {"CALL", "PUT"} or dte <= 0
        for contract_type, dte in criteria.required_cells
    ):
        raise ValueError("invalid required shadow cell")
    minimums = (
        criteria.min_contracts_per_cell,
        criteria.min_unique_decisions_per_cell,
        criteria.min_calendar_days_per_cell,
        criteria.min_transitions_per_cell,
        criteria.min_labeled_observations_per_cell,
    )
    if any(value < 0 for value in minimums):
        raise ValueError("shadow minimums cannot be negative")
    if criteria.min_contracts_per_cell == 0 or criteria.min_unique_decisions_per_cell == 0:
        raise ValueError("contract and decision minimums must be positive")
    fractions = (
        criteria.max_ineligible_fraction_per_cell,
        criteria.max_reversal_fraction_per_cell,
    )
    if any(value < 0 or value > 1 for value in fractions):
        raise ValueError("shadow fractions must be within [0, 1]")


def build_shadow_acceptance_report(
    connection: sqlite3.Connection, bundle: FrozenGuidanceBundle,
    criteria: ShadowAcceptanceCriteria,
) -> dict:
    """Evaluate one frozen bundle without allowing cohort substitution."""
    validate_bundle(bundle)
    validate_criteria(criteria)
    bundle_cells = tuple(
        (str(contract_type).upper(), int(dte)) for contract_type, dte in bundle.required_cells
    )
    if set(criteria.required_cells) != set(bundle_cells):
        raise ValueError("criteria cells must exactly match the frozen bundle cells")
    required = [f"{contract_type}:{dte}" for contract_type, dte in criteria.required_cells]
    readiness = assess_shadow_promotion_readiness(
        connection, required_cells=required,
        min_contracts_per_cell=criteria.min_contracts_per_cell,
        min_unique_decisions_per_cell=criteria.min_unique_decisions_per_cell,
        min_calendar_days_per_cell=criteria.min_calendar_days_per_cell,
        min_transitions_per_cell=criteria.min_transitions_per_cell,
        min_labeled_observations_per_cell=criteria.min_labeled_observations_per_cell,
        max_ineligible_fraction_per_cell=criteria.max_ineligible_fraction_per_cell,
        max_reversal_fraction_per_cell=criteria.max_reversal_fraction_per_cell,
    )
    return {
        "status": "SHADOW_ACCEPTED" if readiness["ready"] else "SHADOW_INCOMPLETE",
        "ready": readiness["ready"],
        "bundle_version": bundle.version,
        "bundle_hash": bundle.bundle_hash,
        "criteria_version": criteria.version,
        "criteria_hash": criteria.criteria_hash,
        "readiness": readiness,
    }
