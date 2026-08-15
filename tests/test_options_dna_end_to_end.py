import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from options_dna_guidance import read_bundle, write_bundle
from options_dna_promotion import build_shadow_bundle
from options_dna_rule_search import (
    CandidateValidation, CounterTargetAudit, FrozenCandidate, SearchCondition,
)
from options_dna_shadow_acceptance import (
    ShadowAcceptanceCriteria, build_shadow_acceptance_report,
)
from options_dna_shadow_runner import run_shadow_once


CELLS = (("CALL", 14), ("CALL", 30), ("PUT", 14), ("PUT", 30))


def validation(contract_type, dte):
    candidate = FrozenCandidate(
        candidate_id=f"CAND-{contract_type}-{dte}",
        target="EARLY_PREMIUM_CONFIRMATION", scope="OBSERVE_ENTRY",
        contract_type=contract_type, dte_target=str(dte), group_field="anchor_id",
        discovery_rank=1,
        conditions=(
            SearchCondition("underlying__event_family", "==", "ENTRY_FORMING"),
            SearchCondition("contract__relative_response_z", ">=", 1.0),
        ),
        discovery_groups=20, discovery_triggered_groups=10,
        discovery_precision=.8, discovery_recall=.6, discovery_coverage=.5,
        discovery_lift=1.6,
    )
    return CandidateValidation(
        candidate=candidate, holdout_groups=10, holdout_triggered_groups=5,
        holdout_precision=.7, holdout_recall=.5, holdout_coverage=.5,
        holdout_lift=1.4, holdout_lift_ci_low=1.1, holdout_lift_ci_high=1.8,
        bootstrap_probability_lift_above_one=.9,
        validation_status="HOLDOUT_ROBUST_DIRECTION_PRESERVED",
    )


def audit(row):
    return CounterTargetAudit(
        candidate_id=row.candidate.candidate_id,
        target="EARLY_PREMIUM_CONFIRMATION", counter_target="CONFIRMATION_FAILURE",
        scope="OBSERVE_ENTRY", holdout_groups=10, counter_triggered_groups=2,
        counter_precision=.1, counter_lift=.5, audit_status="COUNTERTARGET_CLEAR",
    )


def payload(contract_type, dte, index):
    return {
        "symbol": "AMC",
        "contract_ticker": f"O:AMC-{contract_type}-{dte}-{index}",
        "decision_available_utc": "2026-08-14T15:30:00Z",
        "option_data_as_of_utc": "2026-08-14T15:29:00Z",
        "entitlement": "REALTIME",
        "underlying_context": {"event_family": "ENTRY_FORMING"},
        "contract_components": {
            "ready": True, "relative_response_z": 1.2,
            "contract_type": contract_type, "dte_target": dte,
        },
        "catalyst_context": {"status": "INACTIVE", "direction_claim": None},
        "position_context": {"scope": "OBSERVE_ENTRY"},
    }


class OptionsDnaEndToEndTests(unittest.TestCase):
    def test_robust_candidates_reach_shadow_but_not_production(self):
        validations = [validation(*cell) for cell in CELLS]
        audits = [audit(row) for row in validations]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "rule-search-manifest.json"
            source.write_text(json.dumps({"stage": "HISTORICAL_CANDIDATE_VALIDATION"}))
            built = build_shadow_bundle(
                validations, audits, source_manifest_path=source,
                discovery_end_utc="2026-06-30T23:59:59Z",
                holdout_start_utc="2026-07-01T00:00:00Z",
            )
            bundle_path = root / "shadow-bundle.json"
            write_bundle(bundle_path, built)
            bundle = read_bundle(bundle_path)
            connection = sqlite3.connect(":memory:")
            try:
                for index, (contract_type, dte) in enumerate(CELLS):
                    result = run_shadow_once(
                        connection, payload(contract_type, dte, index), bundle,
                        observed_at_utc="2026-08-14T15:31:00Z",
                    )
                    self.assertEqual(
                        result["observation"]["primary_advisory"]["label"],
                        "ENTRY_WINDOW_FORMING",
                    )
                    self.assertEqual(bundle.status, "FROZEN_SHADOW_ONLY")

                criteria = ShadowAcceptanceCriteria(
                    version="integration-v1", required_cells=CELLS,
                    min_contracts_per_cell=1, min_unique_decisions_per_cell=1,
                    min_calendar_days_per_cell=1, min_transitions_per_cell=0,
                    min_labeled_observations_per_cell=1,
                    max_ineligible_fraction_per_cell=0,
                    max_reversal_fraction_per_cell=0,
                )
                report = build_shadow_acceptance_report(connection, bundle, criteria)
            finally:
                connection.close()
        self.assertTrue(report["ready"])
        self.assertEqual(report["status"], "SHADOW_ACCEPTED")
        self.assertEqual(set(report["readiness"]["cells"]), {
            "CALL:14", "CALL:30", "PUT:14", "PUT:30",
        })


if __name__ == "__main__":
    unittest.main()
