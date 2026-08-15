import unittest

import options_dna_research


class OptionsDnaResearchTests(unittest.TestCase):
    def test_cohort_balances_call_put_dte_and_directional_moneyness(self):
        contracts = []
        for ctype in ("CALL", "PUT"):
            for strike in (1.8, 2.0, 2.2):
                contracts.append({
                    "ticker": f"O:AMC-{ctype}-{strike}",
                    "contract_type": ctype,
                    "strike": strike,
                    "expiration": "2026-09-13",
                    "shares_per_contract": 100,
                })
        cohort = options_dna_research.select_contract_cohort(
            contracts, spot=2.0, anchor_date="2026-08-14",
            dte_targets=(30,), moneyness_targets=(-10.0, 0.0, 10.0),
        )
        self.assertEqual(len(cohort), 6)
        self.assertEqual({c["contract_type"] for c in cohort}, {"CALL", "PUT"})
        self.assertEqual({c["dte_target"] for c in cohort}, {30})

    def test_cohort_excludes_adjusted_and_nonstandard_contracts(self):
        rows = [
            {"ticker": "ADJUSTED", "contract_type": "CALL", "strike": 2.0,
             "expiration": "2026-09-13", "shares_per_contract": 100,
             "additional_underlyings": [{"underlying": "OTHER"}]},
            {"ticker": "NONSTANDARD", "contract_type": "CALL", "strike": 2.0,
             "expiration": "2026-09-13", "shares_per_contract": 50},
            {"ticker": "STANDARD", "contract_type": "CALL", "strike": 2.0,
             "expiration": "2026-09-13", "shares_per_contract": 100},
        ]
        cohort = options_dna_research.select_contract_cohort(
            rows, spot=2.0, anchor_date="2026-08-14",
            dte_targets=(30,), moneyness_targets=(0.0,),
        )
        self.assertEqual([row["ticker"] for row in cohort], ["STANDARD"])

    def test_adaptive_selection_records_coarse_strike_fallback(self):
        contracts = [
            {"ticker": "C", "contract_type": "call", "strike_price": 2.0,
             "expiration_date": "2026-02-04", "shares_per_contract": 100},
            {"ticker": "P", "contract_type": "put", "strike_price": 2.0,
             "expiration_date": "2026-02-04", "shares_per_contract": 100},
        ]
        selected = options_dna_research.select_contract_cohort(
            contracts, spot=1.60, anchor_date="2026-01-05", dte_targets=(30,),
            moneyness_targets=(0.0,), fallback_to_nearest_strike=True,
        )
        self.assertEqual({row["ticker"] for row in selected}, {"C", "P"})
        self.assertTrue(all(row["selection_policy"] == "NEAREST_REGULAR_STRIKE" for row in selected))
        self.assertEqual({row["moneyness_band"] for row in selected}, {"MODERATE"})

    def test_forward_outcome_is_separate_and_reports_censoring(self):
        bars = [{"t": i, "c": close} for i, close in enumerate((1.0, 1.2, 1.5, 1.1))]
        full = options_dna_research.forward_long_premium_outcome(bars, 0, 3)
        self.assertFalse(full["right_censored"])
        self.assertAlmostEqual(full["mfe_pct"], 50.0)
        self.assertAlmostEqual(full["mae_pct"], 10.0)
        self.assertEqual(full["bars_to_peak"], 2)
        self.assertAlmostEqual(full["gain_retention"], 0.2)
        censored = options_dna_research.forward_long_premium_outcome(bars, 2, 4)
        self.assertTrue(censored["right_censored"])
        self.assertEqual(censored["observed_bars"], 1)

    def test_forward_outcome_rejects_invalid_candidate(self):
        with self.assertRaises(ValueError):
            options_dna_research.forward_long_premium_outcome([{"c": 1.0}], 2, 3)

    def test_path_outcome_starts_at_next_bar_open_and_uses_future_high_low(self):
        rows = [
            {"t": 0, "o": 0.8, "h": 1.4, "l": 0.7, "c": 1.0},  # signal bar: high must be ignored
            {"t": 1, "o": 1.1, "h": 1.3, "l": 1.0, "c": 1.2},
            {"t": 2, "o": 1.2, "h": 1.65, "l": 0.9, "c": 1.0},
            {"t": 3, "o": 1.0, "h": 1.1, "l": 0.8, "c": 0.9},
        ]
        result = options_dna_research.forward_long_premium_path_outcome(rows, 0, 3)
        self.assertAlmostEqual(result["next_bar_open"], 1.1)
        self.assertAlmostEqual(result["decision_to_next_open_gap_pct"], 10.0)
        self.assertAlmostEqual(result["mfe_pct"], 50.0)
        self.assertAlmostEqual(result["mae_pct"], (0.8 / 1.1 - 1.0) * 100.0)
        self.assertEqual(result["bars_to_peak"], 2)
        self.assertEqual(result["bars_to_trough"], 3)
        self.assertTrue(result["peak_before_trough"])
        self.assertAlmostEqual(result["peak_to_terminal_giveback_pct"], (0.9 / 1.65 - 1.0) * 100.0)

    def test_path_outcome_reports_no_next_bar_as_censored(self):
        result = options_dna_research.forward_long_premium_path_outcome(
            [{"t": 0, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0}], 0, 10,
        )
        self.assertEqual(result, {"right_censored": True, "observed_bars": 0})

    def test_time_window_uses_underlying_cutoff_not_option_print_count(self):
        rows = [
            {"t": 0, "o": 1, "h": 1, "l": 1, "c": 1},
            {"t": 900_000, "o": 1, "h": 1.2, "l": .9, "c": 1.1},
            # Sparse late print contains a large move but lies outside cutoff.
            {"t": 7_200_000, "o": 2, "h": 3, "l": 1.8, "c": 2.5},
        ]
        result = options_dna_research.forward_long_premium_path_until(
            rows, 0, cutoff_time_ms=3_600_000,
        )
        self.assertEqual(result["observed_bars"], 1)
        self.assertAlmostEqual(result["mfe_pct"], 20.0)


if __name__ == "__main__":
    unittest.main()
