import json
import tempfile
import unittest
from pathlib import Path

from options_dna_calibration_stage import (
    CalibrationStageBlocked,
    _future_labeled,
    run_entry_freeze_stage,
    run_target_freeze_stage,
)


class CalibrationStageTests(unittest.TestCase):
    def test_incomplete_acquisition_cannot_freeze_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "PLAN_ONLY", "anchor_count": 1,
            }), encoding="utf-8")
            with self.assertRaisesRegex(CalibrationStageBlocked, "artifact gate"):
                run_target_freeze_stage(root)

    def test_entry_freeze_stage_blocks_on_artifact_gate_not_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "PLAN_ONLY", "anchor_count": 1,
            }), encoding="utf-8")
            with self.assertRaisesRegex(CalibrationStageBlocked, "artifact gate") as ctx:
                run_entry_freeze_stage(root)
            # The entry-only gate must never reference the position gate.
            self.assertNotIn("position", str(ctx.exception))

    def test_future_label_export_excludes_causal_features(self):
        rows = [{
            "anchor_id": "A1", "ticker": "O:TEST", "partition": "HOLDOUT",
            "contract_type": "CALL", "dte_target": "14", "moneyness_target": "0.0",
            "contract__relative_response_z": 2.0,
            "EARLY_PREMIUM_CONFIRMATION": True,
            "EARLY_PREMIUM_CONFIRMATION_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
        }]
        exported = _future_labeled(rows, ["EARLY_PREMIUM_CONFIRMATION"])[0]
        self.assertNotIn("contract__relative_response_z", exported)
        self.assertIs(exported["EARLY_PREMIUM_CONFIRMATION"], True)


if __name__ == "__main__":
    unittest.main()
