import sqlite3
import unittest

from options_dna_guidance import (
    AdvisoryRule, CellEvidence, FrozenGuidanceBundle, RuleCondition,
)
from options_dna_shadow_runner import run_shadow_once


def bundle():
    return FrozenGuidanceBundle(
        version="shadow-v1", status="FROZEN_SHADOW_ONLY",
        source_manifest_sha256="a" * 64,
        discovery_end_utc="2026-06-30T23:59:59Z",
        holdout_start_utc="2026-07-01T00:00:00Z",
        required_cells=(("CALL", 14),),
        rules=(AdvisoryRule(
            rule_id="confirm-call14", label="PREMIUM_CONFIRMING",
            scope="OBSERVE_ENTRY",
            conditions=(
                RuleCondition("underlying.event_family", "==", "CONTINUATION"),
                RuleCondition("contract.relative_response_z", ">=", 1.0),
                RuleCondition("contract.contract_type", "==", "CALL"),
                RuleCondition("contract.dte_target", "==", 14),
            ),
            evidence=(CellEvidence("CALL", 14, 20, 10, 1.4, 1.2),),
            rationale_code="CONFIRMATION_PRESERVED", priority=10,
        ),),
    )


def payload():
    return {
        "symbol": "AMC", "contract_ticker": "O:AMC260828C00002500",
        "decision_available_utc": "2026-08-14T15:30:00Z",
        "option_data_as_of_utc": "2026-08-14T15:29:00Z",
        "entitlement": "REALTIME",
        "underlying_context": {"event_family": "CONTINUATION"},
        "contract_components": {
            "ready": True, "relative_response_z": 1.2,
            "contract_type": "CALL", "dte_target": 14,
        },
        "catalyst_context": {"status": "INACTIVE"},
        "position_context": {"scope": "OBSERVE_ENTRY"},
    }


class OptionsDnaShadowRunnerTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_provider_neutral_input_is_evaluated_and_journaled(self):
        result = run_shadow_once(
            self.connection, payload(), bundle(),
            observed_at_utc="2026-08-14T15:31:00Z",
        )
        self.assertTrue(result["journal"]["inserted"])
        self.assertEqual(
            result["observation"]["primary_advisory"]["label"],
            "PREMIUM_CONFIRMING",
        )

    def test_stale_input_is_journaled_without_advisory(self):
        row = payload()
        row["option_data_as_of_utc"] = "2026-08-14T14:00:00Z"
        result = run_shadow_once(
            self.connection, row, bundle(),
            observed_at_utc="2026-08-14T15:31:00Z",
        )
        self.assertEqual(result["observation"]["gate"], "STALE")
        self.assertEqual(result["observation"]["candidate_labels"], [])

    def test_missing_input_is_rejected_before_journal(self):
        row = payload()
        del row["contract_components"]
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            run_shadow_once(
                self.connection, row, bundle(),
                observed_at_utc="2026-08-14T15:31:00Z",
            )


if __name__ == "__main__":
    unittest.main()
