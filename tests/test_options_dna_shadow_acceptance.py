import sqlite3
import unittest

from options_dna_guidance import (
    AdvisoryRule, CellEvidence, FrozenGuidanceBundle, RuleCondition,
)
from options_dna_shadow_acceptance import (
    ShadowAcceptanceCriteria,
    build_shadow_acceptance_report,
    criteria_from_dict,
)
from options_dna_shadow_journal import record_shadow_observation


def bundle(required_cells=(("CALL", 14),)):
    evidence = tuple(
        CellEvidence(contract_type, dte, 20, 10, 1.4, 1.2)
        for contract_type, dte in required_cells
    )
    return FrozenGuidanceBundle(
        version="shadow-v1", status="FROZEN_SHADOW_ONLY",
        source_manifest_sha256="a" * 64,
        discovery_end_utc="2026-06-30T23:59:59Z",
        holdout_start_utc="2026-07-01T00:00:00Z",
        required_cells=required_cells,
        rules=(AdvisoryRule(
            rule_id="shadow-rule", label="PREMIUM_CONFIRMING", scope="BOTH",
            conditions=(RuleCondition("contract.ready", "is_true"),),
            evidence=evidence, rationale_code="TEST", priority=1,
        ),),
    )


def criteria(required_cells=(("CALL", 14),)):
    return ShadowAcceptanceCriteria(
        version="criteria-v1", required_cells=required_cells,
        min_contracts_per_cell=1, min_unique_decisions_per_cell=1,
        min_calendar_days_per_cell=1, min_transitions_per_cell=0,
        min_labeled_observations_per_cell=1,
        max_ineligible_fraction_per_cell=0,
        max_reversal_fraction_per_cell=0,
    )


def observation(contract_type="CALL", dte=14):
    label = {
        "label": "PREMIUM_CONFIRMING", "rule_id": "r1",
        "rationale_code": "TEST", "scope": "OBSERVE_ENTRY", "priority": 1,
        "evidence_paths": [],
    }
    return {
        "observation_id": f"obs-{contract_type}-{dte}", "symbol": "AMC",
        "contract_ticker": f"O:AMC-{contract_type}-{dte}",
        "decision_available_utc": "2026-08-14T15:30:00Z",
        "gate": "READY_FOR_SHADOW_RULES", "fact_signature": "f",
        "navigation_scope": "OBSERVE_ENTRY", "calibration_version": "shadow-v1",
        "bundle_hash": "b" * 64, "candidate_labels": [label],
        "primary_advisory": label, "rule_evaluation_status": "EVALUATED_SHADOW_ONLY",
        "facts": {"contract": {"contract_type": contract_type, "dte_target": dte}},
    }


class OptionsDnaShadowAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_ready_report_hashes_bundle_and_criteria(self):
        record_shadow_observation(
            self.connection, observation(), observed_at_utc="2026-08-14T15:31:00Z",
        )
        report = build_shadow_acceptance_report(
            self.connection, bundle(), criteria(),
        )
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "SHADOW_ACCEPTED")
        self.assertEqual(len(report["criteria_hash"]), 64)

    def test_missing_required_cell_fails_closed(self):
        record_shadow_observation(
            self.connection, observation(), observed_at_utc="2026-08-14T15:31:00Z",
        )
        required = (("CALL", 14), ("PUT", 14))
        report = build_shadow_acceptance_report(
            self.connection, bundle(required), criteria(required),
        )
        self.assertFalse(report["ready"])
        self.assertFalse(report["readiness"]["cells"]["PUT:14"]["ready"])

    def test_criteria_must_exactly_match_bundle_cells(self):
        with self.assertRaisesRegex(ValueError, "exactly match"):
            build_shadow_acceptance_report(
                self.connection, bundle((("CALL", 14),)),
                criteria((("PUT", 14),)),
            )

    def test_criteria_parser_rejects_implicit_or_invalid_thresholds(self):
        with self.assertRaisesRegex(ValueError, "invalid shadow acceptance criteria"):
            criteria_from_dict({"version": "v1", "required_cells": [["CALL", 14]]})
        bad = criteria()
        payload = dict(bad.__dict__)
        payload["max_reversal_fraction_per_cell"] = 1.1
        with self.assertRaisesRegex(ValueError, "within"):
            criteria_from_dict(payload)


if __name__ == "__main__":
    unittest.main()
