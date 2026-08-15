import math
import unittest

import options_dna


DAY = 86_400_000
START = 1_780_000_000_000


def bars(count=30, *, option=False, missing=None, flat_underlying=False):
    missing = set(missing or [])
    out = []
    for i in range(count):
        if i in missing:
            continue
        if option:
            close = 0.50 * math.exp(0.035 * i)
            volume = 100 + i * 4
        else:
            close = 2.00 if flat_underlying else 2.00 * math.exp(0.007 * i + 0.003 * math.sin(i))
            volume = 10000 + i * 40
        out.append({
            "t": START + i * DAY,
            "o": close * 0.98,
            "h": close * 1.04,
            "l": close * 0.96,
            "c": close,
            "v": volume,
            "vw": close * 0.995,
            "n": 20 + i,
        })
    return out


class OptionsDnaTests(unittest.TestCase):
    def test_alignment_never_forward_fills_missing_option_bars(self):
        aligned = options_dna.align_bars(bars(option=True, missing={5, 7}), bars())
        self.assertEqual(len(aligned), 28)
        self.assertNotIn(START + 5 * DAY, [pair[0]["t"] for pair in aligned])

    def test_component_ledger_emits_causal_free_plan_components(self):
        result = options_dna.component_ledger(
            bars(option=True), bars(), contract_type="CALL", strike=2.0,
            expiration="2026-12-18", lookback=20, min_history=12,
        )
        self.assertTrue(result["ready"], result["quality_reasons"])
        self.assertGreater(result["volume_ratio"], 1.0)
        self.assertGreater(result["transaction_ratio"], 1.0)
        self.assertGreater(result["range_expansion"], 1.0)
        self.assertGreater(result["vwap_distance_pct"], 0.0)
        self.assertGreaterEqual(result["close_location"], 0.0)
        self.assertLessEqual(result["close_location"], 1.0)
        self.assertIsNotNone(result["relative_response_residual"])
        self.assertIsNotNone(result["intrinsic_value"])
        self.assertIsNotNone(result["extrinsic_value_observed"])

    def test_current_bar_does_not_enter_its_volume_baseline(self):
        option = bars(option=True)
        option[-1]["v"] = 100_000
        result = options_dna.component_ledger(
            option, bars(), contract_type="CALL", strike=2.0,
            expiration="2026-12-18", lookback=20,
        )
        expected = option[-1]["v"] / (sum(b["v"] for b in option[-21:-1]) / 20)
        self.assertAlmostEqual(result["volume_ratio"], expected)

    def test_put_inverts_underlying_direction_for_alignment(self):
        call = options_dna.component_ledger(
            bars(option=True), bars(), contract_type="CALL", strike=2.0,
            expiration="2026-12-18",
        )
        put = options_dna.component_ledger(
            bars(option=True), bars(), contract_type="PUT", strike=2.0,
            expiration="2026-12-18",
        )
        self.assertAlmostEqual(call["underlying_directional_return"], -put["underlying_directional_return"])

    def test_sparse_contract_is_not_ready(self):
        option = bars(option=True, missing=set(range(0, 29, 2)))
        result = options_dna.component_ledger(
            option, bars(), contract_type="CALL", strike=2.0,
            expiration="2026-12-18", min_history=5, min_activity_ratio=0.80,
        )
        self.assertFalse(result["ready"])
        self.assertIn("sparse option activity", result["quality_reasons"])

    def test_flat_underlying_rejects_relative_response(self):
        result = options_dna.component_ledger(
            bars(option=True), bars(flat_underlying=True), contract_type="CALL",
            strike=2.0, expiration="2026-12-18",
        )
        self.assertFalse(result["ready"])
        self.assertIn("zero or insufficient underlying variance", result["quality_reasons"])
        self.assertIsNone(result["relative_response_residual"])

    def test_invalid_contract_metadata_fails_honestly(self):
        result = options_dna.component_ledger(
            bars(option=True), bars(), contract_type="OTHER", strike=-1,
            expiration="bad-date",
        )
        self.assertFalse(result["ready"])
        self.assertIn("invalid contract type", result["quality_reasons"])
        self.assertIn("invalid strike", result["quality_reasons"])
        self.assertIn("invalid expiration", result["quality_reasons"])


if __name__ == "__main__":
    unittest.main()
