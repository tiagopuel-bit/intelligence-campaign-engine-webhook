"""Static checks for the per-timeframe silence-baseline feature."""
import csv
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "dna_dashboard.html"
BASELINE = ROOT / "tables" / "dna_campaign_silence_baseline.csv"

ASSETS = {"AMC", "GME", "PYPL", "RBLX", "SPY", "VALE", "U"}


class SilenceBaselineUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_baseline_object_and_function_present(self):
        self.assertIn("LIFECYCLE_SILENCE_BASELINE", self.html)
        self.assertIn("function silenceFlag", self.html)
        self.assertIn("dna-quiet", self.html)

    def test_baseline_covers_seven_assets(self):
        for symbol in ASSETS:
            self.assertIn('"%s"' % symbol, self.html)


class SilenceBaselineCsvTests(unittest.TestCase):
    def test_csv_columns_and_coverage(self):
        with BASELINE.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(
            set(rows[0].keys()),
            {"symbol", "timeframe", "event_count", "median_gap_min", "p90_gap_min"},
        )
        self.assertEqual({r["symbol"] for r in rows}, ASSETS)

    def test_sample_floor_is_no_basis(self):
        # Tiers below 25 events must have empty median/p90 (no-basis).
        with BASELINE.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            if int(row["event_count"]) < 25:
                self.assertEqual(row["median_gap_min"], "")
                self.assertEqual(row["p90_gap_min"], "")
            else:
                self.assertTrue(row["median_gap_min"])
                self.assertTrue(row["p90_gap_min"])


if __name__ == "__main__":
    unittest.main()
