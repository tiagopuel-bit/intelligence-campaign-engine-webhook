import sqlite3
import unittest

from options_dna_shadow_journal import (
    assess_shadow_promotion_readiness,
    assess_shadow_readiness,
    record_shadow_observation,
    shadow_summary,
)


def observation(
    *, fact="a", gate="READY_FOR_SHADOW_RULES", label="MANAGE_ATTENTION",
    contract_type="CALL", dte_target=14,
):
    labels = ([{
        "label": label, "rule_id": "r1", "rationale_code": "TEST",
        "scope": "MANAGE_OPEN_LONG_PREMIUM", "priority": 1, "evidence_paths": [],
    }] if label else [])
    return {
        "observation_id": "obs-1", "symbol": "AMC", "contract_ticker": "O:AMC",
        "decision_available_utc": "2026-08-14T15:30:00+00:00",
        "gate": gate, "fact_signature": fact,
        "navigation_scope": "MANAGE_OPEN_LONG_PREMIUM",
        "calibration_version": "v1", "bundle_hash": "b" * 64 if labels else None,
        "candidate_labels": labels,
        "primary_advisory": labels[0] if labels else None,
        "rule_evaluation_status": "EVALUATED_SHADOW_ONLY" if labels else "SKIPPED_OBSERVATION_GATE",
        "facts": {"contract": {
            "relative_response_z": 1.2,
            "contract_type": contract_type,
            "dte_target": dte_target,
        }},
    }


class OptionsDnaShadowJournalTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")

    def tearDown(self):
        self.connection.close()

    def test_identical_state_is_deduplicated_but_change_is_appended(self):
        first = record_shadow_observation(
            self.connection, observation(), observed_at_utc="2026-08-14T15:31:00Z",
        )
        same = record_shadow_observation(
            self.connection, observation(), observed_at_utc="2026-08-14T15:32:00Z",
        )
        changed = record_shadow_observation(
            self.connection, observation(fact="b", label="PROTECT_ATTENTION"),
            observed_at_utc="2026-08-14T15:33:00Z",
        )
        self.assertTrue(first["inserted"])
        self.assertFalse(same["inserted"])
        self.assertTrue(changed["inserted"])
        self.assertEqual(shadow_summary(self.connection)["observations"], 2)

    def test_gated_observation_cannot_carry_label(self):
        with self.assertRaisesRegex(ValueError, "gated observation"):
            record_shadow_observation(
                self.connection, observation(gate="STALE"),
                observed_at_utc="2026-08-14T15:31:00Z",
            )

    def test_future_outcome_fact_is_rejected(self):
        row = observation()
        row["facts"]["contract"]["mfe_pct"] = 20
        with self.assertRaisesRegex(ValueError, "future outcome facts"):
            record_shadow_observation(
                self.connection, row, observed_at_utc="2026-08-14T15:31:00Z",
            )

    def test_readiness_uses_explicit_requirements(self):
        record_shadow_observation(
            self.connection, observation(fact="a"), observed_at_utc="2026-08-14T15:31:00Z",
        )
        second = observation(fact="b")
        second["observation_id"] = "obs-2"
        second["decision_available_utc"] = "2026-08-15T15:30:00+00:00"
        record_shadow_observation(
            self.connection, second, observed_at_utc="2026-08-15T15:31:00Z",
        )
        passed = assess_shadow_readiness(
            self.connection, min_unique_decisions=2, min_calendar_days=2,
            min_labeled_observations=2, max_ineligible_fraction=0,
            max_reversal_fraction=0,
        )
        failed = assess_shadow_readiness(
            self.connection, min_unique_decisions=3, min_calendar_days=2,
            min_labeled_observations=2, max_ineligible_fraction=0,
            max_reversal_fraction=0,
        )
        self.assertTrue(passed["ready"])
        self.assertFalse(failed["ready"])
        self.assertFalse(failed["checks"]["unique_decisions"])

    def test_repeated_unchanged_decisions_are_coverage_not_transitions(self):
        first = observation(fact="same")
        record_shadow_observation(
            self.connection, first, observed_at_utc="2026-08-14T15:31:00Z",
        )
        second = observation(fact="same")
        second["observation_id"] = "obs-2"
        second["decision_available_utc"] = "2026-08-15T15:30:00Z"
        record_shadow_observation(
            self.connection, second, observed_at_utc="2026-08-15T15:31:00Z",
        )
        summary = shadow_summary(self.connection)
        self.assertEqual(summary["unique_decisions"], 2)
        self.assertEqual(summary["transitions"], 0)

        third = observation(fact="changed", label="PROTECT_ATTENTION")
        third["observation_id"] = "obs-3"
        third["decision_available_utc"] = "2026-08-16T15:30:00Z"
        record_shadow_observation(
            self.connection, third, observed_at_utc="2026-08-16T15:31:00Z",
        )
        self.assertEqual(shadow_summary(self.connection)["transitions"], 1)

    def test_same_decision_a_b_a_reversal_is_retained(self):
        record_shadow_observation(
            self.connection, observation(fact="a", label="MANAGE_ATTENTION"),
            observed_at_utc="2026-08-14T15:31:00Z",
        )
        record_shadow_observation(
            self.connection, observation(fact="b", label="PROTECT_ATTENTION"),
            observed_at_utc="2026-08-14T15:32:00Z",
        )
        third = record_shadow_observation(
            self.connection, observation(fact="a", label="MANAGE_ATTENTION"),
            observed_at_utc="2026-08-14T15:33:00Z",
        )
        summary = shadow_summary(self.connection)
        self.assertTrue(third["inserted"])
        self.assertEqual(summary["observations"], 3)
        self.assertEqual(summary["transitions"], 2)
        self.assertEqual(summary["one_step_reversals"], 1)

    def test_legacy_journal_schema_is_migrated_idempotently(self):
        legacy = sqlite3.connect(":memory:")
        try:
            legacy.execute("""
                CREATE TABLE options_dna_shadow_observations (
                    shadow_event_id TEXT PRIMARY KEY, observation_id TEXT NOT NULL,
                    symbol TEXT NOT NULL, contract_ticker TEXT NOT NULL,
                    decision_available_utc TEXT NOT NULL, observed_at_utc TEXT NOT NULL,
                    gate TEXT NOT NULL, navigation_scope TEXT,
                    calibration_version TEXT, bundle_hash TEXT,
                    fact_signature TEXT NOT NULL, primary_label TEXT,
                    labels_json TEXT NOT NULL, payload_json TEXT NOT NULL
                )
            """)
            result = record_shadow_observation(
                legacy, observation(), observed_at_utc="2026-08-14T15:31:00Z",
            )
            columns = {
                row[1] for row in legacy.execute(
                    "PRAGMA table_info(options_dna_shadow_observations)"
                )
            }
            self.assertTrue(result["inserted"])
            self.assertIn("state_signature", columns)
        finally:
            legacy.close()

    def test_out_of_order_or_predecision_observation_is_rejected(self):
        record_shadow_observation(
            self.connection, observation(), observed_at_utc="2026-08-14T15:40:00Z",
        )
        with self.assertRaisesRegex(ValueError, "out-of-order"):
            record_shadow_observation(
                self.connection, observation(fact="later-state"),
                observed_at_utc="2026-08-14T15:39:00Z",
            )
        separate = sqlite3.connect(":memory:")
        try:
            with self.assertRaisesRegex(ValueError, "before its decision"):
                record_shadow_observation(
                    separate, observation(fact="x"),
                    observed_at_utc="2026-08-14T15:29:00Z",
                )
        finally:
            separate.close()

    def test_label_payload_cannot_smuggle_order_fields(self):
        row = observation()
        row["candidate_labels"][0]["price"] = 2.50
        with self.assertRaisesRegex(ValueError, "price, quantity, or order"):
            record_shadow_observation(
                self.connection, row, observed_at_utc="2026-08-14T15:31:00Z",
            )

    def test_promotion_readiness_is_required_per_cell(self):
        record_shadow_observation(
            self.connection, observation(), observed_at_utc="2026-08-14T15:31:00Z",
        )
        report = assess_shadow_promotion_readiness(
            self.connection, required_cells=["CALL:14", "PUT:14"],
            min_contracts_per_cell=1, min_unique_decisions_per_cell=1,
            min_calendar_days_per_cell=1, min_transitions_per_cell=0,
            min_labeled_observations_per_cell=1,
            max_ineligible_fraction_per_cell=0,
            max_reversal_fraction_per_cell=0,
        )
        self.assertFalse(report["ready"])
        self.assertTrue(report["cells"]["CALL:14"]["ready"])
        self.assertFalse(report["cells"]["PUT:14"]["ready"])

    def test_missing_cell_metadata_is_unclassified_and_cannot_satisfy_gate(self):
        record_shadow_observation(
            self.connection, observation(dte_target=None),
            observed_at_utc="2026-08-14T15:31:00Z",
        )
        report = assess_shadow_promotion_readiness(
            self.connection, required_cells=["CALL:14"],
            min_contracts_per_cell=1, min_unique_decisions_per_cell=1,
            min_calendar_days_per_cell=1, min_transitions_per_cell=0,
            min_labeled_observations_per_cell=1,
            max_ineligible_fraction_per_cell=0,
            max_reversal_fraction_per_cell=0,
        )
        self.assertFalse(report["ready"])
        self.assertEqual(report["unclassified"]["observations"], 1)


if __name__ == "__main__":
    unittest.main()
