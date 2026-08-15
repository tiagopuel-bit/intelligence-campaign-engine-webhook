import tempfile
import unittest
from pathlib import Path

from options_dna_rule_stage import RuleStageBlocked, _join, run_rule_stage


class RuleStageTests(unittest.TestCase):
    def test_target_freeze_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(RuleStageBlocked, "target-freeze manifest"):
                run_rule_stage(Path(tmp))

    def test_causal_and_label_identity_must_match_exactly(self):
        with self.assertRaisesRegex(RuleStageBlocked, "label missing"):
            _join(
                [{"anchor_id": "A1", "ticker": "O:ONE"}],
                [{"anchor_id": "A2", "ticker": "O:TWO"}],
                ("anchor_id", "ticker"),
            )


if __name__ == "__main__":
    unittest.main()
