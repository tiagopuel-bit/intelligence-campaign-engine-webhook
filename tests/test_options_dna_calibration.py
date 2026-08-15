import unittest

from options_dna_calibration import (
    InsufficientEvidence,
    OutcomeCondition,
    apply_frozen_outcome,
    evaluate_frozen_rule,
    fit_threshold_rules,
    freeze_quantile_outcome,
)


def dataset(discovery=24, holdout=12):
    rows = []
    for partition, count, offset in (("DISCOVERY", discovery, 0), ("HOLDOUT", holdout, 100)):
        for i in range(count):
            for contract in ("CALL", "PUT"):
                rows.append({
                    "partition": partition,
                    "anchor_id": f"{partition}-{i}",
                    "contract_type": contract,
                    "relative_response_z": float(i + offset),
                    "entry_target": i >= count // 2,
                })
    return rows


class OptionsDnaCalibrationTests(unittest.TestCase):
    def test_pilot_is_too_small_to_fit_guidance(self):
        with self.assertRaisesRegex(InsufficientEvidence, "20 independent discovery"):
            fit_threshold_rules(
                dataset(discovery=8, holdout=8), target="entry_target",
                features=("relative_response_z",),
            )

    def test_fit_uses_discovery_only(self):
        rows = dataset()
        first = fit_threshold_rules(rows, target="entry_target", features=("relative_response_z",))
        for row in rows:
            if row["partition"] == "HOLDOUT":
                row["relative_response_z"] = -9999.0
                row["entry_target"] = not row["entry_target"]
        second = fit_threshold_rules(rows, target="entry_target", features=("relative_response_z",))
        self.assertEqual(first, second)

    def test_contract_count_does_not_inflate_independent_groups(self):
        rows = dataset()
        exemplar = next(row for row in rows if row["anchor_id"] == "DISCOVERY-23")
        rows.extend(dict(exemplar, contract_type=f"EXTRA-{i}") for i in range(50))
        rules = fit_threshold_rules(rows, target="entry_target", features=("relative_response_z",))
        self.assertTrue(rules)
        self.assertTrue(all(rule.discovery_groups == 24 for rule in rules))

    def test_holdout_evaluates_frozen_threshold(self):
        rows = dataset()
        rule = fit_threshold_rules(rows, target="entry_target", features=("relative_response_z",))[0]
        result = evaluate_frozen_rule(rule, rows)
        self.assertEqual(result["threshold"], rule.threshold)
        self.assertEqual(result["holdout_groups"], 12)

    def test_holdout_has_an_independent_minimum(self):
        rows = dataset(holdout=8)
        rule = fit_threshold_rules(rows, target="entry_target", features=("relative_response_z",))[0]
        with self.assertRaisesRegex(InsufficientEvidence, "10 independent holdout"):
            evaluate_frozen_rule(rule, rows)

    @staticmethod
    def outcome_dataset(discovery=24, holdout=12):
        rows = []
        for partition, count, offset in (("DISCOVERY", discovery, 0), ("HOLDOUT", holdout, 1000)):
            for contract_type in ("CALL", "PUT"):
                for dte in (14, 30):
                    for i in range(count):
                        rows.append({
                            "partition": partition,
                            "anchor_id": f"{partition}-{i}",
                            "contract_type": contract_type,
                            "dte_target": dte,
                            "moneyness_target": 0.0,
                            "mfe_from_next_open": float(i + offset + (100 if contract_type == "PUT" else 0)),
                            "mae_from_next_open": -float(i + offset),
                        })
        return rows

    def test_outcome_cutoffs_use_discovery_only(self):
        rows = self.outcome_dataset()
        conditions = (
            OutcomeCondition("mfe_from_next_open", ">=", 0.75),
            OutcomeCondition("mae_from_next_open", ">=", 0.25),
        )
        first = freeze_quantile_outcome(rows, name="useful_path", conditions=conditions)
        for row in rows:
            if row["partition"] == "HOLDOUT":
                row["mfe_from_next_open"] = -99999.0
                row["mae_from_next_open"] = -99999.0
        second = freeze_quantile_outcome(rows, name="useful_path", conditions=conditions)
        self.assertEqual(first, second)
        self.assertEqual(first.source_partition, "DISCOVERY")

    def test_outcome_cells_freeze_separate_call_put_cutoffs(self):
        definition = freeze_quantile_outcome(
            self.outcome_dataset(), name="useful_path",
            conditions=(OutcomeCondition("mfe_from_next_open", ">=", 0.50),),
        )
        call = next(cell for cell in definition.cells if cell.cell_values[:2] == ("CALL", 14))
        put = next(cell for cell in definition.cells if cell.cell_values[:2] == ("PUT", 14))
        self.assertEqual(put.cutoffs[0].threshold - call.cutoffs[0].threshold, 100.0)

    def test_apply_outcome_uses_frozen_threshold_on_holdout(self):
        rows = self.outcome_dataset()
        definition = freeze_quantile_outcome(
            rows, name="useful_path",
            conditions=(OutcomeCondition("mfe_from_next_open", ">=", 0.50),),
        )
        call = next(cell for cell in definition.cells if cell.cell_values[:2] == ("CALL", 14))
        probe = {
            "partition": "HOLDOUT", "anchor_id": "probe", "contract_type": "CALL",
            "dte_target": 14, "moneyness_target": 0.0,
            "mfe_from_next_open": call.cutoffs[0].threshold,
        }
        labeled = apply_frozen_outcome(definition, [probe])[0]
        self.assertIs(labeled["useful_path"], True)
        self.assertEqual(labeled["useful_path_status"], "SCORED_FROZEN_DISCOVERY_CUTOFFS")

    def test_outcome_rejects_small_cells(self):
        with self.assertRaisesRegex(InsufficientEvidence, "20 independent discovery"):
            freeze_quantile_outcome(
                self.outcome_dataset(discovery=8), name="useful_path",
                conditions=(OutcomeCondition("mfe_from_next_open", ">=", 0.50),),
            )

    def test_outcome_rejects_duplicate_anchor_within_cell(self):
        rows = self.outcome_dataset()
        duplicate = dict(next(row for row in rows if row["partition"] == "DISCOVERY"))
        rows.append(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate anchor_id"):
            freeze_quantile_outcome(
                rows, name="useful_path",
                conditions=(OutcomeCondition("mfe_from_next_open", ">=", 0.50),),
            )

    def test_unfrozen_cell_is_not_guessed(self):
        definition = freeze_quantile_outcome(
            self.outcome_dataset(), name="useful_path",
            conditions=(OutcomeCondition("mfe_from_next_open", ">=", 0.50),),
        )
        row = {
            "contract_type": "CALL", "dte_target": 60, "moneyness_target": 0.0,
            "mfe_from_next_open": 999.0,
        }
        labeled = apply_frozen_outcome(definition, [row])[0]
        self.assertIsNone(labeled["useful_path"])
        self.assertEqual(labeled["useful_path_status"], "UNSCORED_UNFROZEN_CELL")

    def test_outcome_cutoffs_accept_csv_string_values(self):
        # A CSV round-trip delivers numeric fields as strings; the freeze must
        # still parse them instead of dropping every row as non-finite.
        rows = []
        for partition, count in (("DISCOVERY", 20), ("HOLDOUT", 10)):
            for i in range(count):
                rows.append({
                    "partition": partition,
                    "anchor_id": f"{partition}-{i}",
                    "contract_type": "CALL",
                    "dte_target": "14",
                    "moneyness_target": "0.0",
                    "mfe_from_next_open": str(float(i)),  # string, not float
                })
        definition = freeze_quantile_outcome(
            rows, name="useful_path",
            conditions=(OutcomeCondition("mfe_from_next_open", ">=", 0.50),),
        )
        self.assertEqual(len(definition.cells), 1)
        self.assertEqual(definition.cells[0].discovery_groups, 20)
        self.assertTrue(definition.cells[0].cutoffs[0].threshold >= 0.0)


if __name__ == "__main__":
    unittest.main()
