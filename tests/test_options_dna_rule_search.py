import unittest

from options_dna_calibration import InsufficientEvidence
from options_dna_rule_search import (
    FrozenCandidate,
    NumericFeatureSpec,
    SearchCondition,
    _fires,
    audit_active_print_sensitivity,
    audit_counter_targets,
    audit_liquidity_sensitivity,
    collapse_by_triggered_fingerprint,
    evaluate_frozen_candidates,
    reject_tautological_candidates,
    search_discovery_candidates,
)


SPECS = (
    NumericFeatureSpec("underlying__campaign_health", (">=",), (0.5,)),
    NumericFeatureSpec("contract__relative_response_z", (">=",), (0.5,)),
    NumericFeatureSpec("position__unrealized_pnl_pct", ("<=",), (0.5,)),
)


def rows(discovery=24, holdout=12, position=False):
    output = []
    for partition, count in (("DISCOVERY", discovery), ("HOLDOUT", holdout)):
        for ctype in ("CALL", "PUT"):
            for dte in ("14", "30"):
                for index in range(count):
                    positive = index >= count // 2
                    row = {
                        "partition": partition, "anchor_id": f"{partition}-{ctype}-{dte}-{index}",
                        "episode_id": f"{partition}-{ctype}-{dte}-{index}",
                        "contract_type": ctype, "dte_target": dte,
                        "underlying__campaign_health": 90 if positive else 10,
                        "underlying__event_family": (
                            "CONTINUATION" if positive else "THESIS_PRESSURE"
                        ),
                        "contract__relative_response_z": 2 if positive else -2,
                        "position__unrealized_pnl_pct": -10 if positive else 10,
                        "catalyst__active": index % 3 == 0,
                        "TARGET": positive,
                        "TARGET_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
                    }
                    output.append(row)
    return output


class RuleSearchTests(unittest.TestCase):
    def test_serialized_boolean_catalyst_condition_matches(self):
        self.assertTrue(_fires(
            {"catalyst__active": "True"},
            SearchCondition("catalyst__active", "==", True),
        ))

    def test_entry_candidates_require_underlying_and_contract_roots(self):
        candidates = search_discovery_candidates(
            rows(), target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=2,
        )
        self.assertTrue(candidates)
        for candidate in candidates:
            roots = {condition.feature.split("__", 1)[0] for condition in candidate.conditions}
            self.assertTrue({"underlying", "contract"}.issubset(roots))

    def test_position_candidates_also_require_position_context(self):
        candidates = search_discovery_candidates(
            rows(position=True), target="TARGET", scope="MANAGE_OPEN_LONG_PREMIUM",
            group_field="episode_id", feature_specs=SPECS, max_per_cell=2,
        )
        self.assertTrue(candidates)
        for candidate in candidates:
            roots = {condition.feature.split("__", 1)[0] for condition in candidate.conditions}
            self.assertTrue({"underlying", "contract", "position"}.issubset(roots))

    def test_holdout_mutation_cannot_change_frozen_candidates(self):
        data = rows()
        first = search_discovery_candidates(
            data, target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=2,
        )
        for row in data:
            if row["partition"] == "HOLDOUT":
                row["underlying__campaign_health"] = -999
                row["contract__relative_response_z"] = -999
                row["TARGET"] = not row["TARGET"]
        second = search_discovery_candidates(
            data, target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=2,
        )
        self.assertEqual(first, second)

    def test_evaluation_uses_frozen_conditions(self):
        data = rows()
        candidates = search_discovery_candidates(
            data, target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=1,
        )
        validation = evaluate_frozen_candidates(candidates, data, bootstrap_samples=200)
        self.assertTrue(validation)
        self.assertTrue(all(
            item.validation_status == "HOLDOUT_ROBUST_DIRECTION_PRESERVED"
            for item in validation
        ))
        self.assertTrue(all(item.holdout_lift_ci_low > 1.0 for item in validation))

    def test_thin_discovery_is_rejected(self):
        with self.assertRaises(InsufficientEvidence):
            search_discovery_candidates(
                rows(discovery=8), target="TARGET", scope="OBSERVE_ENTRY",
                group_field="anchor_id", feature_specs=SPECS[:2],
            )

    def test_catalyst_never_replaces_required_directional_roots(self):
        bad_specs = (NumericFeatureSpec("catalyst__age_hours", ("<=",), (0.5,)),)
        with self.assertRaisesRegex(InsufficientEvidence, "required causal feature root"):
            search_discovery_candidates(
                rows(), target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
                feature_specs=bad_specs,
            )

    def test_countertarget_rejects_ambiguous_exit_condition(self):
        data = rows()
        for row in data:
            row["COUNTER"] = row["TARGET"]
            row["COUNTER_status"] = "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        candidates = search_discovery_candidates(
            data, target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=1,
        )
        validations = evaluate_frozen_candidates(candidates, data, bootstrap_samples=200)
        audits = audit_counter_targets(
            validations, data, counter_targets={"TARGET": ("COUNTER",)},
        )
        self.assertTrue(audits)
        self.assertTrue(all(
            item.audit_status == "AMBIGUOUS_COUNTERTARGET_REJECTED" for item in audits
        ))

    def test_countertarget_clear_when_opposite_path_not_enriched(self):
        data = rows()
        for row in data:
            row["COUNTER"] = not row["TARGET"]
            row["COUNTER_status"] = "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        candidates = search_discovery_candidates(
            data, target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=1,
        )
        validations = evaluate_frozen_candidates(candidates, data, bootstrap_samples=200)
        audits = audit_counter_targets(
            validations, data, counter_targets={"TARGET": ("COUNTER",)},
        )
        self.assertTrue(audits)
        self.assertTrue(all(item.audit_status == "COUNTERTARGET_CLEAR" for item in audits))

    def test_liquidity_audit_flags_zero_frozen_thresholds(self):
        candidates = search_discovery_candidates(
            rows(), target="TARGET", scope="OBSERVE_ENTRY", group_field="anchor_id",
            feature_specs=SPECS[:2], max_per_cell=1,
        )
        # A frozen target whose H1__mfe cutoff is zero fires on unchanged prints.
        definitions = {
            "TARGET": {
                "name": "TARGET",
                "cells": [
                    {"cell_values": ["CALL", "14", "0.0"],
                     "cutoffs": [{"field": "H1__mfe_pct", "threshold": 0.0}]},
                    {"cell_values": ["PUT", "14", "0.0"],
                     "cutoffs": [{"field": "H1__mfe_pct", "threshold": 5.0}]},
                ],
            }
        }
        audits = audit_liquidity_sensitivity(candidates, definitions)
        by_id = {item.candidate_id: item for item in audits}
        call_audit = next(item for item in audits if item.contract_type == "CALL")
        put_audit = next(item for item in audits if item.contract_type == "PUT")
        self.assertEqual(call_audit.audit_status, "LIQUIDITY_SENSITIVE")
        self.assertEqual(call_audit.near_zero_fields, ("H1__mfe_pct",))
        self.assertEqual(put_audit.audit_status, "ACTIVE_PRINT_SUPPORTED")
        self.assertTrue(len(audits) == len(candidates))

    def _candidate(self, conditions, cid="C1", ctype="CALL", dte="14"):
        return FrozenCandidate(
            candidate_id=cid, target="T", scope="OBSERVE_ENTRY", contract_type=ctype,
            dte_target=dte, group_field="anchor_id", discovery_rank=0,
            conditions=tuple(conditions), discovery_groups=20, discovery_triggered_groups=10,
            discovery_precision=1.0, discovery_recall=1.0, discovery_coverage=1.0,
            discovery_lift=1.0,
        )

    def test_tautological_contract_condition_is_rejected(self):
        rows = [{
            "partition": "DISCOVERY", "anchor_id": f"A{i}", "contract_type": "CALL",
            "dte_target": "14", "contract__close_location": 0.5,
            "underlying__event_family": "CONTINUATION",
        } for i in range(20)]
        tautological = self._candidate([
            SearchCondition("contract__close_location", "<=", 1),
            SearchCondition("underlying__event_family", "==", "CONTINUATION"),
        ])
        discriminating = self._candidate([
            SearchCondition("contract__close_location", "<=", 0.33),
            SearchCondition("underlying__event_family", "==", "CONTINUATION"),
        ], cid="C2")
        rejected = reject_tautological_candidates([tautological, discriminating], rows)
        self.assertEqual([item.candidate_id for item in rejected], ["C1"])

    def test_active_print_audit_requires_observable_activity(self):
        # Unchanged prints (zero return, zero volume) must not count as support.
        rows = []
        for i in range(25):
            rows.append({
                "partition": "DISCOVERY", "anchor_id": f"A{i}", "contract_type": "CALL",
                "dte_target": "14", "T": i % 2 == 0, "T_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
                "contract__option_return": 0.0, "contract__volume_ratio": 0.0,
                "contract__close_location": 0.5,
            })
        for i in range(12):
            rows.append({
                "partition": "HOLDOUT", "anchor_id": f"H{i}", "contract_type": "CALL",
                "dte_target": "14", "T": i % 2 == 0, "T_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
                "contract__option_return": 0.0, "contract__volume_ratio": 0.0,
                "contract__close_location": 0.5,
            })
        candidate = self._candidate([SearchCondition("contract__close_location", "<=", 1)])
        audits = audit_active_print_sensitivity([candidate], rows)
        self.assertEqual(audits[0].audit_status, "INSUFFICIENT_ACTIVE_PRINT_COVERAGE")

    def test_fingerprint_collapse_groups_equivalent_candidates(self):
        rows = []
        for i in range(6):
            rows.append({
                "partition": "HOLDOUT", "anchor_id": f"H{i}", "contract_type": "CALL",
                "dte_target": "14", "contract__close_location": 0.2 if i < 3 else 0.9,
                "underlying__campaign_health": 50.0,
            })
        # Both fire on the same three holdout anchors (close_location <= 0.5).
        a = self._candidate([SearchCondition("contract__close_location", "<=", 0.5)])
        b = self._candidate([SearchCondition("contract__close_location", "<=", 0.4)], cid="C2")
        families = collapse_by_triggered_fingerprint([a, b], rows)
        self.assertEqual(len(families), 1)
        self.assertEqual(len(families[list(families)[0]]), 2)

    def test_fingerprint_collapse_respects_contract_cell(self):
        # Identical conditions and identical triggered anchors in two different
        # contract cells must remain distinct signal families.
        rows = []
        for i in range(6):
            for ctype, dte in (("CALL", "14"), ("CALL", "30")):
                rows.append({
                    "partition": "HOLDOUT", "anchor_id": f"H{i}", "contract_type": ctype,
                    "dte_target": dte, "T": True, "T_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
                    "contract__close_location": 0.2 if i < 3 else 0.9,
                })
        a = self._candidate([SearchCondition("contract__close_location", "<=", 0.5)], cid="C1")
        b = self._candidate([SearchCondition("contract__close_location", "<=", 0.5)], cid="C2", dte="30")
        families = collapse_by_triggered_fingerprint([a, b], rows)
        self.assertEqual(len(families), 2)
        self.assertEqual(sum(len(members) for members in families.values()), 2)


if __name__ == "__main__":
    unittest.main()
