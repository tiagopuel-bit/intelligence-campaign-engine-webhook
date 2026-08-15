import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from options_dna_acceptance import (
    REQUIRED_CATALYST_FIELDS,
    audit_bar_payload,
    audit_pilot_directory,
)


class OptionsDnaAcceptanceTests(unittest.TestCase):
    def test_bar_audit_accepts_sparse_but_valid_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.json"
            path.write_text(json.dumps({"ticker": "O:TEST", "bars": [
                {"t": 900000, "o": 1, "h": 1.2, "l": .9, "c": 1.1, "v": 2},
                {"t": 3600000, "o": 1.1, "h": 1.1, "l": 1, "c": 1, "v": 1},
            ]}))
            issues = audit_bar_payload(path, expected_ticker="O:TEST")
        self.assertEqual(issues, [])

    def test_bar_audit_rejects_duplicate_off_grid_and_bad_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bars.json"
            path.write_text(json.dumps({"ticker": "WRONG", "bars": [
                {"t": 1, "o": 2, "h": 1, "l": 1.5, "c": 2, "v": -1},
                {"t": 1, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
            ]}))
            codes = {issue.code for issue in audit_bar_payload(path, expected_ticker="O:TEST")}
        self.assertTrue({
            "BAR_TICKER_MISMATCH", "BAR_OFF_15M_GRID", "BAR_GEOMETRY_INVALID",
            "BAR_TIME_NOT_STRICT",
        }.issubset(codes))

    def test_partial_provider_run_is_explicitly_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
            }), encoding="utf-8")
            report = audit_pilot_directory(root)
        self.assertEqual(report.status, "INCOMPLETE_ACQUISITION")
        self.assertFalse(report.ready_for_review)
        self.assertIn("REQUIRED_ARTIFACT_PENDING", {issue.code for issue in report.issues})

    def test_complete_synthetic_run_passes_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bars").mkdir()
            signal = "1970-01-01T00:15:00+00:00"
            decision = "1970-01-01T00:30:00+00:00"
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHED", "anchor_count": 1, "cohort_count": 1,
            }), encoding="utf-8")
            bars = {"ticker": "O:TEST", "bars": [
                {"t": 900000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},
                {"t": 1800000, "o": 1, "h": 1.1, "l": 1, "c": 1.1, "v": 2},
            ]}
            (root / "bars" / "O_TEST.json").write_text(json.dumps(bars), encoding="utf-8")
            fields = [
                "anchor_id", "partition", "event_family", "signal_bar_open_utc",
                "decision_available_utc", "ticker", "contract_type", "dte_target",
                "moneyness_target", "bar_count", "bars_file",
            ]
            with (root / "cohort_ledger.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    "anchor_id": "A1", "partition": "DISCOVERY", "event_family": "ENTRY_FORMING",
                    "signal_bar_open_utc": signal, "decision_available_utc": decision,
                    "ticker": "O:TEST", "contract_type": "CALL", "dte_target": 14,
                    "moneyness_target": 0, "bar_count": 2, "bars_file": "bars/O_TEST.json",
                })
            with gzip.open(root / "component_ledger.csv.gz", "wt") as handle:
                handle.write(
                    "anchor_id,ticker,signal_bar_exists,coverage_at,ready,matched_bars,"
                    "activity_ratio,quality_reasons\nA1,O:TEST,True,1,True,2,1.0,\n"
                )
            (root / "forward_outcomes.csv").write_text(
                "anchor_id,ticker,signal_bar_exists,coverage_at,observed_bars,outcome_status,right_censored,"
                "decision_close,next_bar_open,decision_to_next_open_gap_pct,mfe_pct,mae_pct,"
                "terminal_return_pct,bars_to_peak,bars_to_trough,peak_to_terminal_giveback_pct,"
                "gain_retention,decision_close_mfe_pct,decision_close_mae_pct,peak_before_trough\n"
                "A1,O:TEST,True,1,1,SCORED_RIGHT_CENSORED,True,1,1,0,10,-5,2,1,1,-7,.2,10,-5,True\n",
                encoding="utf-8",
            )
            window_header = (
                "anchor_id,ticker,signal_bar_exists,coverage_at,observed_bars,outcome_status,"
                "right_censored,decision_close,next_bar_open,decision_to_next_open_gap_pct,"
                "mfe_pct,mae_pct,terminal_return_pct,bars_to_peak,bars_to_trough,"
                "peak_to_terminal_giveback_pct,gain_retention,decision_close_mfe_pct,"
                "decision_close_mae_pct,peak_before_trough,window,underlying_bars_forward,"
                "cutoff_time_ms,censor_reason\n"
            )
            window_rows = "".join(
                f"A1,O:TEST,True,1,1,SCORED_WINDOW,False,1,1,0,10,-5,2,1,1,-7,.2,10,-5,True,{name},{bars},3600000,\n"
                for name, bars in (("H1", 4), ("D1", 26), ("D3", 78), ("D5", 130), ("D10", 260))
            )
            (root / "forward_outcome_windows.csv").write_text(
                window_header + window_rows, encoding="utf-8",
            )
            for name in ("coverage_by_cell.csv", "quality_rejections.csv"):
                (root / name).write_text("anchor_id,ticker\nA1,O:TEST\n", encoding="utf-8")
            (root / "failures.json").write_text("[]", encoding="utf-8")
            (root / "DEEPSEEK_EXECUTION_REPORT.md").write_text("verified", encoding="utf-8")
            report = audit_pilot_directory(root)
        self.assertEqual(report.status, "READY_FOR_REVIEW")
        self.assertTrue(report.ready_for_review)
        self.assertFalse(report.calibration_coverage_ready)

    def test_old_close_only_outcomes_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text("anchor_id\nA1\n", encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHED", "anchor_count": 1,
            }), encoding="utf-8")
            # The rest can remain pending; the key assertion is that a present
            # legacy outcome schema is a fidelity error, not merely incomplete.
            (root / "forward_outcomes.csv").write_text(
                "anchor_id,ticker,mfe_pct,mae_pct\nA1,O:TEST,10,-5\n", encoding="utf-8",
            )
            report = audit_pilot_directory(root)
        self.assertIn("OUTCOME_COLUMNS_MISSING", {issue.code for issue in report.issues})

    def test_calibration_minimum_counts_independent_exact_signal_anchors(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\nA2,HOLDOUT\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 2,
                "contract_design": {"types": ["CALL", "PUT"], "dte_targets": [14, 30]},
                "acceptance_targets": {
                    "cell_fields": ["contract_type", "dte_target"],
                    "discovery_independent_exact_signal_anchors_per_contract_cell": 2,
                    "holdout_independent_exact_signal_anchors_per_contract_cell": 1,
                },
            }), encoding="utf-8")
            with gzip.open(root / "component_ledger.csv.gz", "wt") as handle:
                handle.write(
                    "anchor_id,ticker,partition,contract_type,dte_target,signal_bar_exists,"
                    "coverage_at,ready,matched_bars,activity_ratio,quality_reasons\n"
                    "A1,C1,DISCOVERY,CALL,14,True,1,True,20,1.0,\n"
                    "A1,C2,DISCOVERY,CALL,14,True,1,True,20,1.0,\n"
                    "A2,C3,HOLDOUT,CALL,14,True,1,True,20,1.0,\n"
                )
            report = audit_pilot_directory(root)
        call14_discovery = next(
            row for row in report.calibration_cell_counts
            if row["partition"] == "DISCOVERY" and row["contract_type"] == "CALL"
            and row["dte_target"] == "14"
        )
        self.assertEqual(call14_discovery["independent_exact_signal_anchors"], 1)
        self.assertFalse(report.calibration_coverage_ready)
        self.assertIn("CALIBRATION_CELL_DEFICIT", {issue.code for issue in report.issues})

    def test_required_catalyst_artifacts_cannot_be_silently_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
                "catalyst_design": {
                    "required": True, "required_modes": ["PUBLIC_ACCEPTANCE"],
                },
            }), encoding="utf-8")
            report = audit_pilot_directory(root)
        pending = {
            issue.detail for issue in report.issues
            if issue.code == "REQUIRED_ARTIFACT_PENDING"
        }
        self.assertIn("catalyst_ledger.csv", pending)
        self.assertIn("catalyst_manifest.json", pending)

    def test_required_catalyst_coverage_rejects_unknown_as_inactive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
                "catalyst_design": {
                    "required": True, "required_modes": ["PUBLIC_ACCEPTANCE"],
                },
            }), encoding="utf-8")
            fields = sorted(REQUIRED_CATALYST_FIELDS)
            with (root / "catalyst_ledger.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerow({
                    **{field: "" for field in fields},
                    "anchor_id": "A1", "partition": "DISCOVERY",
                    "mode": "PUBLIC_ACCEPTANCE",
                    "source_status": "SOURCE_UNAVAILABLE",
                    "source_reason": "DECISION_OUTSIDE_COVERAGE",
                })
            (root / "catalyst_manifest.json").write_text("{}", encoding="utf-8")
            report = audit_pilot_directory(root)
        self.assertIn(
            "CATALYST_REQUIRED_COVERAGE_UNAVAILABLE",
            {issue.code for issue in report.issues},
        )

    def test_required_future_target_artifacts_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
                "target_design": {"required": True, "future_only": True},
            }), encoding="utf-8")
            report = audit_pilot_directory(root)
        pending = {
            issue.detail for issue in report.issues
            if issue.code == "REQUIRED_ARTIFACT_PENDING"
        }
        self.assertIn("future_target_matrix.csv", pending)
        self.assertIn("target_hypotheses_v1.json", pending)

    def test_required_position_replay_artifacts_cannot_be_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
                "position_replay_design": {"required": True},
            }), encoding="utf-8")
            report = audit_pilot_directory(root)
        pending = {
            issue.detail for issue in report.issues
            if issue.code == "REQUIRED_ARTIFACT_PENDING"
        }
        self.assertTrue({
            "position_episode_ledger.csv", "position_snapshot_ledger.csv.gz",
            "position_snapshot_anchor_plan.csv",
            "position_snapshot_outcome_windows.csv", "position_snapshot_rejections.csv",
            "position_future_target_matrix.csv", "position_replay_manifest.json",
            "position_catalyst_ledger.csv", "position_catalyst_manifest.json",
        }.issubset(pending))

    def test_required_shadow_criteria_cannot_be_silently_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
                "shadow_acceptance_design": {
                    "required": True,
                    "criteria_file": "shadow_acceptance_criteria_v1.json",
                },
            }), encoding="utf-8")
            report = audit_pilot_directory(root)
        pending = {
            issue.detail for issue in report.issues
            if issue.code == "REQUIRED_ARTIFACT_PENDING"
        }
        self.assertIn("shadow_acceptance_criteria_v1.json", pending)

    def test_shadow_criteria_hash_is_frozen_by_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "anchor_plan.csv").write_text(
                "anchor_id,partition\nA1,DISCOVERY\n", encoding="utf-8",
            )
            criteria = root / "shadow_acceptance_criteria_v1.json"
            criteria.write_text("{}\n", encoding="utf-8")
            expected = hashlib.sha256(criteria.read_bytes()).hexdigest()
            (root / "manifest.json").write_text(json.dumps({
                "status": "FETCHING", "anchor_count": 1,
                "shadow_acceptance_design": {
                    "required": True,
                    "criteria_file": criteria.name,
                    "criteria_file_sha256": expected,
                },
            }), encoding="utf-8")
            criteria.write_text('{"changed": true}\n', encoding="utf-8")
            report = audit_pilot_directory(root)
        self.assertIn(
            "SHADOW_CRITERIA_HASH_MISMATCH",
            {issue.code for issue in report.issues},
        )


if __name__ == "__main__":
    unittest.main()
