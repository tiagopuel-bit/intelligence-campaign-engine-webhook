import unittest

from options_dna_calibration import InsufficientEvidence
from options_dna_calibration_dataset import (
    build_entry_calibration_dataset,
    build_position_calibration_dataset,
    freeze_and_apply_v1_targets,
)
from options_dna_targets import PATH_FIELDS, WINDOWS


def target(identity="A1", *, position=False, partition="DISCOVERY", ctype="CALL", dte="14"):
    row = {
        ("snapshot_id" if position else "anchor_id"): identity,
        "ticker": "O:TEST", "partition": partition, "contract_type": ctype,
        "dte_target": dte, "moneyness_target": "0.0",
    }
    for index, window in enumerate(WINDOWS):
        row[f"{window}__status"] = "SCORED_WINDOW"
        row[f"{window}__complete"] = True
        for field in PATH_FIELDS:
            row[f"{window}__{field}"] = float(index + 1)
    return row


def catalyst(identity="A1"):
    return {
        "anchor_id": identity, "mode": "PUBLIC_ACCEPTANCE",
        "source_status": "INACTIVE", "active": False,
        "direction_claim": None,
    }


class CalibrationDatasetTests(unittest.TestCase):
    def test_entry_join_keeps_causal_and_future_rows_separate(self):
        cohort = [{
            "anchor_id": "A1", "ticker": "O:TEST", "partition": "DISCOVERY",
            "contract_type": "CALL", "dte_target": 14, "moneyness_target": 0.0,
            "decision_available_utc": "2026-08-12T14:00:00Z",
            "event_family": "ENTRY_FORMING", "events": "IGNITION",
            "campaign_health": 80, "phase_confidence": 70, "weakness_count": 0,
        }]
        components = [{
            "anchor_id": "A1", "ticker": "O:TEST", "ready": True,
            "relative_response_z": 1.2,
        }]
        result = build_entry_calibration_dataset(cohort, components, [target()], [catalyst()])
        self.assertNotIn("H1__mfe_pct", result["causal"][0])
        self.assertIn("H1__mfe_pct", result["future"][0])
        self.assertTrue(result["joined"][0]["research_only_future_joined"])
        self.assertTrue(result["causal"][0]["calibration_eligible"])

    def test_position_join_requires_covered_catalyst(self):
        snapshot = [{
            "snapshot_id": "S1", "episode_id": "E1", "ticker": "O:TEST",
            "partition": "DISCOVERY", "contract_type": "CALL", "dte_target": 14,
            "moneyness_target": 0.0, "snapshot_decision_available_utc": "2026-08-12T14:00:00Z",
            "snapshot_event_family": "THESIS_PRESSURE", "contract__ready": True,
        }]
        unavailable = dict(catalyst("S1"), source_status="SOURCE_UNAVAILABLE")
        with self.assertRaisesRegex(ValueError, "covered catalyst"):
            build_position_calibration_dataset(
                snapshot, [target("S1", position=True)], [unavailable],
            )

    def test_position_join_uses_episode_as_independence_unit(self):
        snapshot = [{
            "snapshot_id": "S1", "episode_id": "E1", "ticker": "O:TEST",
            "partition": "DISCOVERY", "contract_type": "CALL", "dte_target": 14,
            "moneyness_target": 0.0, "snapshot_decision_available_utc": "2026-08-12T14:00:00Z",
            "snapshot_event_family": "THESIS_PRESSURE", "contract__ready": True,
        }]
        result = build_position_calibration_dataset(
            snapshot, [target("S1", position=True)], [catalyst("S1")],
        )
        self.assertEqual(result["joined"][0]["episode_id"], "E1")
        self.assertEqual(result["joined"][0]["navigation_scope"], "MANAGE_OPEN_LONG_PREMIUM")

    def test_pilot_scale_cannot_freeze_v1_targets(self):
        rows = []
        for index in range(8):
            row = target(f"A{index}")
            row["anchor_id"] = f"A{index}"
            rows.append(row)
        with self.assertRaises(InsufficientEvidence):
            freeze_and_apply_v1_targets(rows, [])


if __name__ == "__main__":
    unittest.main()
