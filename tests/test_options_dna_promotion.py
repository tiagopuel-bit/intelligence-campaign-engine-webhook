import json
import tempfile
import unittest
from pathlib import Path

from options_dna_promotion import (
    build_shadow_bundle,
    counter_audit_from_dict,
    validation_from_dict,
)
from options_dna_rule_search import (
    CandidateValidation,
    CounterTargetAudit,
    FrozenCandidate,
    SearchCondition,
)


def validation(*, status="HOLDOUT_ROBUST_DIRECTION_PRESERVED", rank=1,
               target="PERSISTENT_PREMIUM_DAMAGE", event="THESIS_PRESSURE"):
    candidate = FrozenCandidate(
        candidate_id="CAND-123", target=target,
        scope="MANAGE_OPEN_LONG_PREMIUM", contract_type="CALL", dte_target="14",
        group_field="episode_id", discovery_rank=rank,
        conditions=(
            SearchCondition("underlying__event_family", "==", event),
            SearchCondition("contract__relative_response_z", "<=", -1.0),
            SearchCondition("position__unrealized_pnl_pct", "<=", -10.0),
        ),
        discovery_groups=24, discovery_triggered_groups=8,
        discovery_precision=.8, discovery_recall=.6, discovery_coverage=.3,
        discovery_lift=1.6,
    )
    return CandidateValidation(
        candidate=candidate, holdout_groups=12, holdout_triggered_groups=4,
        holdout_precision=.75, holdout_recall=.5, holdout_coverage=.3,
        holdout_lift=1.5, holdout_lift_ci_low=1.1, holdout_lift_ci_high=2.0,
        bootstrap_probability_lift_above_one=.92, validation_status=status,
    )


def audit(status="COUNTERTARGET_CLEAR"):
    return CounterTargetAudit(
        candidate_id="CAND-123", target="PERSISTENT_PREMIUM_DAMAGE",
        counter_target="RUNAWAY_CONTINUATION", scope="MANAGE_OPEN_LONG_PREMIUM",
        holdout_groups=12, counter_triggered_groups=1,
        counter_precision=.1, counter_lift=.5, audit_status=status,
    )


class PromotionTests(unittest.TestCase):
    def test_validation_round_trip_from_json_shape(self):
        original = validation()
        import dataclasses
        rebuilt = validation_from_dict(dataclasses.asdict(original))
        self.assertEqual(rebuilt, original)
        original_audit = audit()
        rebuilt_audit = counter_audit_from_dict(dataclasses.asdict(original_audit))
        self.assertEqual(rebuilt_audit, original_audit)

    def test_damage_plus_pressure_maps_to_exit_risk_not_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text(json.dumps({"status": "VERIFIED"}), encoding="utf-8")
            bundle = build_shadow_bundle(
                [validation()], [audit()], source_manifest_path=manifest,
                discovery_end_utc="2026-01-31T23:59:59Z",
                holdout_start_utc="2026-02-01T00:00:00Z",
            )
        self.assertEqual(bundle.rules[0].label, "EXIT_RISK_ELEVATED")
        self.assertFalse(any(
            word in bundle.rules[0].label for word in ("BUY", "SELL", "CLOSE", "ROLL")
        ))

    def test_ambiguous_countertarget_cannot_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no candidate"):
                build_shadow_bundle(
                    [validation()], [audit("AMBIGUOUS_COUNTERTARGET_REJECTED")],
                    source_manifest_path=manifest,
                    discovery_end_utc="2026-01-31T23:59:59Z",
                    holdout_start_utc="2026-02-01T00:00:00Z",
                )

    def test_only_preregistered_top_discovery_ranks_can_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no candidate"):
                build_shadow_bundle(
                    [validation(rank=4)], [audit()], source_manifest_path=manifest,
                    discovery_end_utc="2026-01-31T23:59:59Z",
                    holdout_start_utc="2026-02-01T00:00:00Z",
                )


if __name__ == "__main__":
    unittest.main()
