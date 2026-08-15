import json
import tempfile
import unittest
from pathlib import Path

from options_dna_guidance import (
    AdvisoryRule,
    CellEvidence,
    FrozenGuidanceBundle,
    InvalidCalibrationBundle,
    RuleCondition,
    apply_shadow_bundle,
    read_bundle,
    validate_bundle,
    write_bundle,
)
from options_dna_shadow import build_shadow_observation


def evidence():
    return (
        CellEvidence("CALL", 14, 24, 12, 1.4, 1.2),
        CellEvidence("CALL", 30, 24, 12, 1.3, 1.1),
        CellEvidence("PUT", 14, 22, 11, 1.3, 1.1),
        CellEvidence("PUT", 30, 22, 11, 1.2, 1.1),
    )


def bundle(*rules):
    return FrozenGuidanceBundle(
        version="options-dna-shadow-v1", status="FROZEN_SHADOW_ONLY",
        source_manifest_sha256="a" * 64, discovery_end_utc="2026-01-31T23:59:59Z",
        holdout_start_utc="2026-02-01T00:00:00Z",
        required_cells=(("CALL", 14), ("CALL", 30), ("PUT", 14), ("PUT", 30)),
        rules=tuple(rules),
    )


def rule(**overrides):
    values = {
        "rule_id": "entry-confirming", "label": "ENTRY_WINDOW_FORMING",
        "scope": "OBSERVE_ENTRY",
        "conditions": (
            RuleCondition("underlying.event_family", "==", "ENTRY_FORMING"),
            RuleCondition("contract.relative_response_z", ">=", 1.0),
            RuleCondition("catalyst.active", "is_false"),
            RuleCondition("position.scope", "==", "OBSERVE_ENTRY"),
        ),
        "evidence": evidence(), "rationale_code": "DNA_AND_PREMIUM_CONFIRM",
        "priority": 10,
    }
    values.update(overrides)
    return AdvisoryRule(**values)


def observation(*, scope="OBSERVE_ENTRY", version="options-dna-shadow-v1", gate_ready=True):
    result = build_shadow_observation(
        symbol="AMC", contract_ticker="O:AMC", decision_available_utc="2026-08-14T15:30:00Z",
        option_data_as_of_utc="2026-08-14T15:15:00Z", entitlement="DELAYED_15M",
        underlying_context={"event_family": "ENTRY_FORMING"},
        contract_components={"ready": True, "relative_response_z": 1.2},
        catalyst_context={"active": False, "severity": None},
        position_context={"scope": scope}, calibration_version=version,
    )
    if not gate_ready:
        result["gate"] = "STALE"
    return result


class OptionsDnaGuidanceTests(unittest.TestCase):
    def test_combined_causal_rule_emits_shadow_advisory(self):
        result = apply_shadow_bundle(observation(), bundle(rule()))
        self.assertEqual(result["rule_evaluation_status"], "EVALUATED_SHADOW_ONLY")
        self.assertEqual([item["label"] for item in result["candidate_labels"]], ["ENTRY_WINDOW_FORMING"])
        self.assertEqual(result["primary_advisory"]["label"], "ENTRY_WINDOW_FORMING")
        self.assertNotIn("price", result["candidate_labels"][0])
        self.assertNotIn("quantity", result["candidate_labels"][0])

    def test_position_scope_prevents_entry_wording_on_open_trade(self):
        result = apply_shadow_bundle(observation(scope="MANAGE_OPEN_LONG_PREMIUM"), bundle(rule()))
        self.assertEqual(result["candidate_labels"], [])

    def test_gate_and_version_mismatch_skip_evaluation(self):
        stale = apply_shadow_bundle(observation(gate_ready=False), bundle(rule()))
        mismatch = apply_shadow_bundle(observation(version="other"), bundle(rule()))
        self.assertEqual(stale["rule_evaluation_status"], "SKIPPED_OBSERVATION_GATE")
        self.assertEqual(mismatch["rule_evaluation_status"], "SKIPPED_VERSION_MISMATCH")

    def test_future_outcome_feature_is_rejected(self):
        bad = rule(conditions=(RuleCondition("contract.mfe_pct", ">=", 20),))
        with self.assertRaisesRegex(InvalidCalibrationBundle, "future outcome"):
            validate_bundle(bundle(bad))

    def test_catalyst_only_direction_rule_is_rejected(self):
        bad = rule(conditions=(RuleCondition("catalyst.severity", "==", "HIGH"),))
        with self.assertRaisesRegex(InvalidCalibrationBundle, "cannot infer direction"):
            validate_bundle(bundle(bad))

    def test_thin_or_unstable_cell_is_rejected(self):
        thin_cells = list(evidence())
        thin_cells[0] = CellEvidence("CALL", 14, 19, 12, 1.4, 1.2)
        unstable_cells = list(evidence())
        unstable_cells[0] = CellEvidence("CALL", 14, 24, 12, 1.4, 0.9)
        thin = rule(evidence=tuple(thin_cells))
        unstable = rule(evidence=tuple(unstable_cells))
        with self.assertRaisesRegex(InvalidCalibrationBundle, "discovery cell minimum"):
            validate_bundle(bundle(thin))
        with self.assertRaisesRegex(InvalidCalibrationBundle, "positive lift"):
            validate_bundle(bundle(unstable))

    def test_broad_rule_must_cover_every_required_contract_cell(self):
        incomplete = rule(evidence=(CellEvidence("CALL", 14, 24, 12, 1.4, 1.2),))
        with self.assertRaisesRegex(InvalidCalibrationBundle, "lacks validation evidence"):
            validate_bundle(bundle(incomplete))

    def test_cell_restricted_rule_may_use_matching_evidence_only(self):
        restricted = rule(
            conditions=(
                RuleCondition("contract.contract_type", "==", "CALL"),
                RuleCondition("contract.dte_target", "==", 14),
                RuleCondition("contract.relative_response_z", ">=", 1.0),
            ),
            evidence=(CellEvidence("CALL", 14, 24, 12, 1.4, 1.2),),
        )
        validate_bundle(bundle(restricted))

    def test_position_management_advisory_owns_primary_precedence(self):
        manage = rule(
            rule_id="manage", label="MANAGE_ATTENTION", scope="MANAGE_OPEN_LONG_PREMIUM",
            conditions=(RuleCondition("contract.relative_response_z", ">=", 1.0),),
        )
        protect = rule(
            rule_id="protect", label="PROTECT_ATTENTION", scope="MANAGE_OPEN_LONG_PREMIUM",
            conditions=(
                RuleCondition("underlying.event_family", "==", "ENTRY_FORMING"),
                RuleCondition("contract.relative_response_z", ">=", 1.0),
            ),
        )
        result = apply_shadow_bundle(
            observation(scope="MANAGE_OPEN_LONG_PREMIUM"), bundle(manage, protect),
        )
        self.assertEqual(result["primary_advisory"]["label"], "PROTECT_ATTENTION")

    def test_entry_label_cannot_be_used_for_open_position_scope(self):
        invalid = rule(scope="MANAGE_OPEN_LONG_PREMIUM")
        with self.assertRaisesRegex(InvalidCalibrationBundle, "incompatible with scope"):
            validate_bundle(bundle(invalid))

    def test_bundle_round_trip_and_tamper_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            original = bundle(rule())
            write_bundle(path, original)
            self.assertEqual(read_bundle(path), original)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["bundle"]["rules"][0]["priority"] = 999
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(InvalidCalibrationBundle, "hash mismatch"):
                read_bundle(path)


if __name__ == "__main__":
    unittest.main()
