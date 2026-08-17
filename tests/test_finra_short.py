"""Tests for finra_short (FINRA daily short-sale volume aggregation).

No network: the fetcher is injected, and the band mapping is pure.
"""
import unittest
from datetime import date

import finra_short


def _fake_fetcher(rows_by_day):
    def fetcher(day):
        return rows_by_day.get(day)
    return fetcher


class ShortActivityTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(finra_short.short_activity(None), "NO_DATA")
        self.assertEqual(finra_short.short_activity(0.10), "LOW")
        self.assertEqual(finra_short.short_activity(0.399), "LOW")
        self.assertEqual(finra_short.short_activity(0.40), "NORMAL")
        self.assertEqual(finra_short.short_activity(0.54), "NORMAL")
        self.assertEqual(finra_short.short_activity(0.55), "ELEVATED")
        self.assertEqual(finra_short.short_activity(0.69), "ELEVATED")
        self.assertEqual(finra_short.short_activity(0.70), "HIGH")


class ShortVolumeRatioTests(unittest.TestCase):
    def test_ratio_sums_across_days_and_skips_weekends(self):
        # Two weekdays with data, plus a weekend date that must be ignored.
        fetcher = _fake_fetcher({
            "20260813": {"AMC": {"short": 60.0, "total": 100.0}},
            "20260814": {"AMC": {"short": 40.0, "total": 100.0}},
            "20260815": {"AMC": {"short": 999.0, "total": 999.0}},  # Saturday, ignored
        })
        result = finra_short.short_volume_ratio(
            "AMC", days=3, as_of=date(2026, 8, 17), fetcher=fetcher
        )
        self.assertEqual(result["trading_days_seen"], 2)
        self.assertEqual(result["short_volume"], 100.0)
        self.assertEqual(result["total_volume"], 200.0)
        self.assertEqual(result["short_volume_ratio"], 0.5)

    def test_missing_symbol_contributes_nothing(self):
        fetcher = _fake_fetcher({
            "20260814": {"OTHER": {"short": 10.0, "total": 10.0}},
        })
        result = finra_short.short_volume_ratio(
            "AMC", days=1, as_of=date(2026, 8, 14), fetcher=fetcher
        )
        self.assertEqual(result["trading_days_seen"], 1)
        self.assertIsNone(result["short_volume_ratio"])

    def test_none_day_is_a_non_trading_day(self):
        fetcher = _fake_fetcher({})
        result = finra_short.short_volume_ratio(
            "AMC", days=1, as_of=date(2026, 8, 14), fetcher=fetcher
        )
        self.assertEqual(result["trading_days_seen"], 0)


class ShortContextTests(unittest.TestCase):
    def test_context_shape(self):
        fetcher = _fake_fetcher({
            "20260814": {"AMC": {"short": 75.0, "total": 100.0}},
        })
        context = finra_short.short_context(
            "AMC", days=1, as_of=date(2026, 8, 14), fetcher=fetcher
        )
        self.assertEqual(context["symbol"], "AMC")
        self.assertEqual(context["short_activity"], "HIGH")
        self.assertEqual(context["freshness"], "DELAYED")
        self.assertEqual(context["source"], "finra_reg_sho_daily")
        self.assertEqual(context["short_volume_ratio"], 0.75)


if __name__ == "__main__":
    unittest.main()
