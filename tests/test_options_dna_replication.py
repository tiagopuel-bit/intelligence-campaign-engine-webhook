"""Tests for the multi-asset replication evaluation module."""
import unittest

from options_dna_replication import (
    CONTROLS,
    CONTRACT_TYPE,
    DTE_TARGET,
    FROZEN_CONDITIONS,
    TARGET,
    build_replication_rows,
    evaluate_replication,
)
from options_dna_replication_acquisition import select_call14_contract

SYMBOLS = ("SPY", "TSLA", "GME", "U", "RBLX", "PYPL", "LULU", "VALE")


def _build_asset_rows(symbol: str, discovery: int, holdout: int, seed: int) -> list[dict]:
    rows: list[dict] = []
    for partition, count in (("DISCOVERY", discovery), ("HOLDOUT", holdout)):
        for i in range(count):
            quadrant = (i + seed) % 4
            both_low = quadrant == 0
            close_low = quadrant in (0, 1)
            health_low = quadrant in (0, 2)
            roll = (i * 31 + seed * 17 + 7) % 100
            if quadrant == 0:
                fails = roll < 80
            elif quadrant in (1, 2):
                fails = roll < 50
            else:
                fails = roll < 20
            crowl = (i * 37 + seed * 11 + 3) % 100
            confirms = crowl < 15 if both_low else crowl < 50
            rows.append({
                "symbol": symbol,
                "anchor_id": f"{symbol}-{partition}-{i:03d}",
                "partition": partition,
                "contract_type": CONTRACT_TYPE,
                "dte_target": DTE_TARGET,
                "contract__close_location": 0.25 if close_low else 0.60,
                "underlying__campaign_health": 25.0 if health_low else 50.0,
                "contract__option_return": 1.0,
                TARGET: fails,
                f"{TARGET}_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
                "EARLY_PREMIUM_CONFIRMATION": confirms,
                "EARLY_PREMIUM_CONFIRMATION_status": "SCORED_FROZEN_DISCOVERY_CUTOFFS",
            })
    return rows


def _all_rows() -> list[dict]:
    rows: list[dict] = []
    for index, symbol in enumerate(SYMBOLS):
        rows.extend(_build_asset_rows(symbol, discovery=24, holdout=16, seed=index))
    return rows


class ReplicationConstantsTest(unittest.TestCase):
    def test_frozen_candidate_is_unchanged(self):
        self.assertEqual(
            [(c.feature, c.operator, round(float(c.threshold), 4)) for c in FROZEN_CONDITIONS],
            [
                ("contract__close_location", "<=", 0.3333),
                ("underlying__campaign_health", "<=", 31.6),
            ],
        )

    def test_four_controls_present(self):
        self.assertEqual(
            [name for name, _ in CONTROLS],
            ["unconditional_cell_base_rate", "active_print_only_base_rate",
             "underlying_only", "contract_only"],
        )


class ReplicationEvaluationTest(unittest.TestCase):
    def test_report_structure(self):
        report = evaluate_replication(_all_rows(), symbols=SYMBOLS)
        self.assertEqual(report["target"], TARGET)
        self.assertEqual(report["contract_type"], CONTRACT_TYPE)
        self.assertEqual(set(report["per_asset"]), set(SYMBOLS))
        self.assertIn("pooled", report)
        self.assertIn("replication_status", report)

    def test_assets_reported_separately(self):
        report = evaluate_replication(_all_rows(), symbols=SYMBOLS)
        for symbol in SYMBOLS:
            asset = report["per_asset"][symbol]
            self.assertEqual(asset["symbol"], symbol)
            self.assertGreaterEqual(asset["holdout_scored_groups"], 10)
            self.assertGreaterEqual(asset["discovery_scored_groups"], 20)

    def test_candidate_adds_value_over_base_rate(self):
        report = evaluate_replication(_all_rows(), symbols=SYMBOLS)
        asset = report["per_asset"]["SPY"]
        self.assertGreater(asset["holdout_candidate"]["lift"], 1.0)
        self.assertGreater(
            asset["holdout_candidate"]["lift"],
            asset["controls"]["unconditional_cell_base_rate"]["lift"],
        )

    def test_candidate_beats_single_root_controls(self):
        report = evaluate_replication(_all_rows(), symbols=SYMBOLS)
        asset = report["per_asset"]["SPY"]
        candidate = asset["holdout_candidate"]
        self.assertGreater(candidate["lift"], asset["controls"]["underlying_only"]["lift"])
        self.assertGreater(candidate["lift"], asset["controls"]["contract_only"]["lift"])
        self.assertGreater(candidate["precision"], asset["controls"]["underlying_only"]["precision"])
        self.assertGreater(candidate["precision"], asset["controls"]["contract_only"]["precision"])

    def test_all_assets_pass_with_enriching_signal(self):
        report = evaluate_replication(_all_rows(), symbols=SYMBOLS)
        self.assertEqual(len(report["passing_assets"]), len(SYMBOLS))
        self.assertTrue(report["pooled_pass"])

    def test_unchanged_print_excluded_from_active_scope(self):
        rows = _all_rows()
        for row in rows:
            if row["anchor_id"].endswith("000"):
                row["contract__option_return"] = 0.0
        report = evaluate_replication(rows, symbols=SYMBOLS)
        self.assertIn("pooled_active_print", report)


class ReplicationFailureTest(unittest.TestCase):
    def test_no_enrichment_yields_fail(self):
        rows = _all_rows()
        for row in rows:
            row[TARGET] = True
            row["EARLY_PREMIUM_CONFIRMATION"] = False
        report = evaluate_replication(rows, symbols=SYMBOLS)
        self.assertEqual(len(report["passing_assets"]), 0)
        self.assertFalse(report["pooled_pass"])

    def test_insufficient_coverage_fails_asset(self):
        rows = _all_rows()
        rows = [row for row in rows if row["symbol"] != "SPY" or row["partition"] == "HOLDOUT"]
        report = evaluate_replication(rows, symbols=SYMBOLS)
        self.assertNotIn("SPY", report["passing_assets"])


class ReplicationDatasetBuildTest(unittest.TestCase):
    def test_build_rows_joins_and_labels(self):
        cohort = [{
            "anchor_id": "SPY-0001", "symbol": "SPY", "ticker": "O:SPY",
            "partition": "HOLDOUT", "event_family": "CONTINUATION",
            "contract_type": "CALL", "dte_target": "14", "moneyness_target": "0.0",
            "campaign_health": "20.0",
        }]
        component = [{
            "anchor_id": "SPY-0001", "close_location": "0.20", "option_return": "1.5",
        }]
        matrix = [{
            "anchor_id": "SPY-0001", "ticker": "O:SPY",
            "H1__mfe_pct": "1.0", "D1__mae_pct": "-40.0", "D1__terminal_return_pct": "-30.0",
        }]
        cutoffs = {
            TARGET: (("H1__mfe_pct", "<=", 3.25),
                     ("D1__mae_pct", "<=", -31.25),
                     ("D1__terminal_return_pct", "<=", -20.58)),
            "EARLY_PREMIUM_CONFIRMATION": (("H1__mfe_pct", ">=", 11.67),
                                           ("D1__terminal_return_pct", ">=", -15.19)),
        }
        rows = build_replication_rows(cohort, component, matrix, cutoffs)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row[TARGET])
        self.assertEqual(row[f"{TARGET}_status"], "SCORED_FROZEN_DISCOVERY_CUTOFFS")
        self.assertFalse(row["EARLY_PREMIUM_CONFIRMATION"])
        self.assertEqual(row["contract__close_location"], 0.20)
        self.assertEqual(row["underlying__campaign_health"], 20.0)

    def test_build_rows_missing_cutoff_value_unscored(self):
        cohort = [{
            "anchor_id": "SPY-0001", "symbol": "SPY", "ticker": "O:SPY",
            "partition": "HOLDOUT", "event_family": "CONTINUATION",
            "contract_type": "CALL", "dte_target": "14", "moneyness_target": "0.0",
            "campaign_health": "20.0",
        }]
        component = [{"anchor_id": "SPY-0001", "close_location": "0.20", "option_return": "1.5"}]
        matrix = [{"anchor_id": "SPY-0001", "ticker": "O:SPY", "H1__mfe_pct": None}]
        cutoffs = {TARGET: (("H1__mfe_pct", "<=", 3.25),)}
        rows = build_replication_rows(cohort, component, matrix, cutoffs)
        self.assertEqual(rows[0][f"{TARGET}_status"], "UNSCORED_MISSING_VALUE")


class ContractSelectionTest(unittest.TestCase):
    def _contracts(self):
        return [
            {"contract_type": "CALL", "strike": 99.0, "expiration": "2026-08-28",
             "ticker": "O:X-99", "shares_per_contract": 100},
            {"contract_type": "CALL", "strike": 100.0, "expiration": "2026-08-28",
             "ticker": "O:X-100", "shares_per_contract": 100},
            {"contract_type": "PUT", "strike": 100.0, "expiration": "2026-08-28",
             "ticker": "O:X-P100", "shares_per_contract": 100},
        ]

    def test_select_call14_nearest_strike(self):
        contract = select_call14_contract(
            self._contracts(), spot=100.0, anchor_date="2026-08-14",
        )
        self.assertIsNotNone(contract)
        self.assertEqual(contract["contract_type"], "CALL")
        self.assertEqual(contract["strike"], 100.0)

    def test_select_call14_returns_none_without_call(self):
        contracts = [{
            "contract_type": "PUT", "strike": 100.0, "expiration": "2026-08-28",
            "ticker": "O:X-P100", "shares_per_contract": 100,
        }]
        self.assertIsNone(select_call14_contract(contracts, spot=100.0, anchor_date="2026-08-14"))


if __name__ == "__main__":
    unittest.main()
