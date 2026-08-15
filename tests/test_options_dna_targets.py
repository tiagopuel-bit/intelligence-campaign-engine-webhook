import unittest

from options_dna_calibration import InsufficientEvidence
from options_dna_targets import (
    PATH_FIELDS,
    TARGET_HYPOTHESES_V1,
    WINDOWS,
    build_window_target_matrix,
    build_position_window_target_matrix,
    freeze_target_hypotheses,
)


def window_rows(*, anchors=1, right_censored=None):
    rows = []
    for index in range(anchors):
        for window_index, window in enumerate(WINDOWS):
            status = "SCORED_RIGHT_CENSORED" if window == right_censored else "SCORED_WINDOW"
            rows.append({
                "anchor_id": f"A{index}", "ticker": f"O:TEST{index}",
                "contract_type": "CALL", "strike": 1.0, "expiration": "2026-09-18",
                "dte_target": 14, "moneyness_target": 0.0,
                "partition": "DISCOVERY", "event_family": "CONTINUATION",
                "decision_available_utc": "2026-08-12T14:00:00Z",
                "signal_bar_open_utc": "2026-08-12T13:45:00Z",
                "moneyness_pct": 0.0, "dte": 14, "window": window,
                "cutoff_time_ms": (window_index + 1) * 1000,
                "outcome_status": status, "censor_reason": "END" if right_censored else "",
                "observed_bars": window_index + 1,
                "mfe_pct": 10.0 + index, "mae_pct": -2.0,
                "terminal_return_pct": 5.0, "bars_to_peak": 1,
                "bars_to_trough": 2, "peak_to_terminal_giveback_pct": -5.0,
                "gain_retention": 0.5, "decision_close_mfe_pct": 9.0,
                "decision_close_mae_pct": -3.0,
            })
    return rows


class OptionsDnaTargetTests(unittest.TestCase):
    def test_matrix_has_one_contract_row_and_all_windows(self):
        matrix = build_window_target_matrix(window_rows())
        self.assertEqual(len(matrix), 1)
        self.assertTrue(all(matrix[0][f"{window}__complete"] for window in WINDOWS))

    def test_right_censored_metrics_cannot_define_cutoffs(self):
        matrix = build_window_target_matrix(window_rows(right_censored="D5"))
        self.assertFalse(matrix[0]["D5__complete"])
        self.assertTrue(all(matrix[0][f"D5__{field}"] is None for field in PATH_FIELDS))

    def test_duplicate_window_rejected(self):
        rows = window_rows()
        rows.append(dict(rows[0]))
        with self.assertRaisesRegex(ValueError, "duplicate target window"):
            build_window_target_matrix(rows)

    def test_incomplete_window_set_rejected(self):
        rows = [row for row in window_rows() if row["window"] != "D10"]
        with self.assertRaisesRegex(ValueError, "incomplete target window set"):
            build_window_target_matrix(rows)

    def test_pilot_cannot_freeze_target_hypotheses(self):
        matrix = build_window_target_matrix(window_rows(anchors=8))
        with self.assertRaises(InsufficientEvidence):
            freeze_target_hypotheses(matrix)

    def test_hypotheses_include_entry_failure_giveback_damage_and_runaway(self):
        names = {item.name for item in TARGET_HYPOTHESES_V1}
        self.assertEqual(names, {
            "EARLY_PREMIUM_CONFIRMATION", "CONFIRMATION_FAILURE",
            "RETAINED_EXPANSION", "GIVEBACK_AFTER_EXPANSION",
            "PERSISTENT_PREMIUM_DAMAGE", "RUNAWAY_CONTINUATION",
        })

    def test_position_matrix_preserves_episode_identity(self):
        rows = []
        for index, window in enumerate(WINDOWS):
            rows.append({
                "snapshot_id": "S1", "episode_id": "E1", "entry_anchor_id": "A1",
                "ticker": "O:TEST", "partition": "DISCOVERY",
                "contract_type": "CALL", "dte_target": 14, "moneyness_target": 0.0,
                "snapshot_event_family": "THESIS_PRESSURE",
                "snapshot_signal_bar_open_utc": "2026-08-12T13:45:00Z",
                "snapshot_decision_available_utc": "2026-08-12T14:00:00Z",
                "window": window, "cutoff_time_ms": (index + 1) * 1000,
                "outcome_status": "SCORED_WINDOW", "observed_bars": 2,
                **{field: 1.0 for field in PATH_FIELDS},
            })
        matrix = build_position_window_target_matrix(rows)
        self.assertEqual(len(matrix), 1)
        self.assertEqual(matrix[0]["snapshot_id"], "S1")
        self.assertEqual(matrix[0]["episode_id"], "E1")


if __name__ == "__main__":
    unittest.main()
