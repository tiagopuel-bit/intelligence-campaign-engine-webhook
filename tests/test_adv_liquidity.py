"""Tests for ADV liquidity bands (advisory, dashboard-only).

Covers the pure computation (rolling ADV, band percentiles, flag threshold,
no-basis floor, zero/NaN dropping), the injected-loader table builder, the
precomputed CSV, and the dashboard embedding — mirroring the silence-baseline
and campaign-lifecycle test conventions.
"""
import csv
import statistics
from pathlib import Path
import unittest

from adv_liquidity import (
    COLUMNS,
    adv_band,
    asset_row,
    compute_rows,
    liquidity_flag,
    rolling_adv,
)

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "dna_dashboard.html"
TABLE = ROOT / "tables" / "dna_liquidity_adv.csv"

ASSETS = {"AMC", "GME", "PYPL", "RBLX", "SPY", "VALE", "U"}


def _pairs(base=1000, n=200, last=None):
    last = base if last is None else last
    out = [(f"2026-01-{(i % 28) + 1:02d}-{i:02d}", base) for i in range(n - 1)]
    out.append(("2026-12-31", last))
    return out


class RollingAdvTests(unittest.TestCase):
    def test_window_alignment(self):
        vols = list(range(1, 31))  # 1..30
        adv = rolling_adv(vols, window=20)
        self.assertEqual(len(adv), 30 - 20 + 1)
        self.assertAlmostEqual(adv[0], sum(range(1, 21)) / 20)  # 10.5
        self.assertAlmostEqual(adv[-1], sum(range(11, 31)) / 20)  # 20.5

    def test_shorter_than_window_is_empty(self):
        self.assertEqual(rolling_adv([1, 2, 3], window=20), [])


class AdvBandTests(unittest.TestCase):
    def test_percentiles_match_stdlib(self):
        vols = list(range(1, 101))
        band = adv_band(vols, window=20, min_obs=60)
        adv = rolling_adv(vols, window=20)
        self.assertEqual(band["n_obs"], len(adv))
        self.assertEqual(band["median"], statistics.median(adv))
        deciles = statistics.quantiles(adv, n=10, method="inclusive")
        self.assertEqual(band["p10"], deciles[0])
        self.assertEqual(band["p90"], deciles[8])

    def test_no_basis_below_min_obs(self):
        vols = list(range(1, 40))  # 20 rolling values < 60
        self.assertIsNone(adv_band(vols, window=20, min_obs=60))


class LiquidityFlagTests(unittest.TestCase):
    def _band(self, p10):
        return {"median": 1000.0, "p10": p10, "p90": 2000.0, "n_obs": 100}

    def test_thin_below_p10(self):
        self.assertEqual(liquidity_flag(50.0, self._band(100.0)), "THIN")

    def test_normal_at_or_above_p10(self):
        self.assertEqual(liquidity_flag(100.0, self._band(100.0)), "NORMAL")
        self.assertEqual(liquidity_flag(150.0, self._band(100.0)), "NORMAL")

    def test_no_data_when_missing(self):
        self.assertEqual(liquidity_flag(None, self._band(100.0)), "NO_DATA")
        self.assertEqual(liquidity_flag(50.0, None), "NO_DATA")


class ComputeRowsTests(unittest.TestCase):
    def test_covers_seven_assets_with_closed_vocab(self):
        rows = compute_rows(loaders={sym: _pairs() for sym in ASSETS})
        self.assertEqual({r["symbol"] for r in rows}, ASSETS)
        for r in rows:
            self.assertIn(r["liquidity"], {"THIN", "NORMAL", "NO_DATA"})

    def test_thin_when_latest_far_below(self):
        # 199 bars at 1000, then a 500 tail -> latest clearly below p10.
        rows = compute_rows(loaders={"AMC": _pairs(base=1000, n=200, last=500)})
        self.assertEqual(rows[0]["liquidity"], "THIN")

    def test_normal_when_latest_in_band(self):
        rows = compute_rows(loaders={"AMC": _pairs(base=1000, n=200, last=1000)})
        self.assertEqual(rows[0]["liquidity"], "NORMAL")

    def test_no_data_when_empty(self):
        rows = compute_rows(loaders={"AMC": []})
        self.assertEqual(rows[0]["liquidity"], "NO_DATA")

    def test_zero_and_nan_volume_dropped(self):
        pairs = [(f"d{i}", v) for i, v in enumerate([1000.0] * 199 + [0.0])]
        row = asset_row("AMC", pairs)
        # The zero tail is dropped, so the latest real volume (1000) is used.
        self.assertEqual(row["latest_volume"], 1000)
        self.assertEqual(row["liquidity"], "NORMAL")


class LiquidityAdvTableTests(unittest.TestCase):
    def test_csv_columns_and_coverage(self):
        with TABLE.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(set(rows[0].keys()), set(COLUMNS))
        self.assertEqual({r["symbol"] for r in rows}, ASSETS)

    def test_closed_vocabulary_values(self):
        with TABLE.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            self.assertIn(row["liquidity"], {"THIN", "NORMAL", "NO_DATA"})
            self.assertTrue(row["adv_median"])
            self.assertTrue(row["adv_p10"])
            self.assertTrue(row["adv_p90"])


class LiquidityAdvUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_object_function_and_badge_present(self):
        self.assertIn("LIQUIDITY_ADV", self.html)
        self.assertIn("function liquidityFlag", self.html)
        self.assertIn("dna-liquidity", self.html)

    def test_embedded_object_covers_seven_assets(self):
        for symbol in ASSETS:
            self.assertIn('"%s"' % symbol, self.html)


if __name__ == "__main__":
    unittest.main()
