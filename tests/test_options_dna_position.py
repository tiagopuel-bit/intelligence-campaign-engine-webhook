import unittest

from options_dna_position import long_option_position_context, observation_context


class OptionsDnaPositionTests(unittest.TestCase):
    def test_no_position_routes_to_observation(self):
        result = observation_context(symbol="amc", as_of="2026-08-14T16:00:00Z")
        self.assertEqual(result["scope"], "OBSERVE_ENTRY")
        self.assertFalse(result["has_open_position"])

    def test_long_call_context_is_factual_and_position_specific(self):
        option = {
            "contract": {"type": "CALL", "strike": 2.5, "expiration": "2026-09-18"},
            "contracts": 2,
            "avg_cost": 0.30,
            "current_price": 0.55,
            "first_entry": "2026-08-01T14:30:00Z",
            "total_pnl": 50.0,
            "total_return_pct": 83.33,
        }
        result = long_option_position_context(
            option, symbol="AMC", underlying_current=2.70,
            as_of="2026-08-14T16:00:00Z", price_source="massive_eod",
        )
        self.assertEqual(result["scope"], "MANAGE_OPEN_LONG_PREMIUM")
        self.assertEqual(result["dte"], 35)
        self.assertGreater(result["moneyness_pct"], 0)
        self.assertAlmostEqual(result["intrinsic_value"], 0.20)
        self.assertAlmostEqual(result["extrinsic_value_observed"], 0.35)
        self.assertIsNone(result["direction_claim"])

    def test_put_uses_direction_aware_moneyness(self):
        option = {
            "contract": {"type": "PUT", "strike": 3.0, "expiration": "2026-09-18"},
            "contracts": 1,
            "avg_cost": 0.40,
            "current_price": 0.60,
            "first_entry": "2026-08-01T14:30:00Z",
        }
        result = long_option_position_context(
            option, symbol="AMC", underlying_current=2.70,
            as_of="2026-08-14T16:00:00Z", price_source="massive_eod",
        )
        self.assertGreater(result["moneyness_pct"], 0)
        self.assertAlmostEqual(result["intrinsic_value"], 0.30)

    def test_invalid_position_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid option valuation fields"):
            long_option_position_context(
                {}, symbol="AMC", underlying_current=2.7,
                as_of="2026-08-14T16:00:00Z", price_source="massive_eod",
            )


if __name__ == "__main__":
    unittest.main()
