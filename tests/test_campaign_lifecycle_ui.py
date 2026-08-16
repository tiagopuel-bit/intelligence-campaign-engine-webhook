"""Static checks for the campaign-lifecycle dashboard feature.

Verifies the closed-vocabulary stage tokens, the lifecycle badge markup, and
that the per-asset reliability mask CSV is present and consistent with the
mask embedded in the dashboard.
"""
import csv
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "dna_dashboard.html"
MASK = ROOT / "tables" / "dna_campaign_lifecycle_reliability.csv"

STAGES = ("idle", "ignition", "establishment", "faded")
RESOLUTIONS = ("cascade_up", "fail_cluster", "stretch_cluster")


class CampaignLifecycleUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_closed_vocabulary_present(self):
        for token in STAGES + RESOLUTIONS:
            self.assertIn(token, self.html)

    def test_lifecycle_function_and_badge_present(self):
        self.assertIn("function lifecycleStage", self.html)
        self.assertIn("dna-lifecycle-", self.html)
        self.assertIn("function phaseFamily", self.html)

    def test_reliability_mask_embedded(self):
        self.assertIn("LIFECYCLE_RELIABILITY", self.html)
        for symbol in ("AMC", "GME", "PYPL", "RBLX", "SPY", "VALE", "U", "MARA"):
            self.assertIn('"%s"' % symbol, self.html)


class CampaignLifecycleMaskTests(unittest.TestCase):
    def test_mask_file_exists_with_columns(self):
        self.assertTrue(MASK.exists())
        with MASK.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 49)
        self.assertEqual(
            set(rows[0].keys()),
            {"symbol", "timeframe", "classified_bars", "agreement_rate", "reliable"},
        )

    def test_mask_covers_eight_assets(self):
        with MASK.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        symbols = {row["symbol"] for row in rows}
        self.assertEqual(symbols, {"AMC", "GME", "PYPL", "RBLX", "SPY", "VALE", "U", "MARA"})

    def test_reliable_flag_is_binary(self):
        with MASK.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            self.assertIn(row["reliable"], {"0", "1"})


if __name__ == "__main__":
    unittest.main()
