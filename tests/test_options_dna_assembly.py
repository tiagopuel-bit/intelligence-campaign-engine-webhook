import csv
import gzip
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import assemble_options_dna_ledger


class OptionsDnaAssemblyTests(unittest.TestCase):
    def test_exact_signal_bar_path_and_sparse_activity_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bars_dir = root / "bars"
            bars_dir.mkdir()
            replay = root / "underlying.csv.gz"
            start = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)
            underlying = []
            with gzip.open(replay, "wt", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=("t_utc", "open", "high", "low", "close", "Volume"))
                writer.writeheader()
                for i in range(24):
                    opened = start + timedelta(minutes=15 * i)
                    close = 2.0 + i * 0.01
                    writer.writerow({
                        "t_utc": opened.isoformat(), "open": close - .005,
                        "high": close + .01, "low": close - .01, "close": close,
                        "Volume": 100 + i,
                    })
                    underlying.append(int(opened.timestamp() * 1000))

            # Contract A has enough history but skips five underlying bars.
            # Contract B lacks the exact signal bar and must not be shifted.
            signal_i = 20
            option_a_indices = list(range(15)) + [signal_i, 21, 22, 23]
            option_b_indices = list(range(15)) + [19, 21, 22, 23]
            for ticker, indices in (("O:A", option_a_indices), ("O:B", option_b_indices)):
                bars = []
                for i in indices:
                    close = 0.5 + i * 0.01
                    bars.append({
                        "t": underlying[i], "o": close - .01, "h": close + .03,
                        "l": close - .02, "c": close, "v": i + 1, "n": i + 1,
                        "vw": close,
                    })
                (bars_dir / f"{ticker.replace(':', '_')}.json").write_text(json.dumps({
                    "ticker": ticker, "bars": bars,
                }), encoding="utf-8")

            signal = start + timedelta(minutes=15 * signal_i)
            decision = signal + timedelta(minutes=15)
            fields = (
                "anchor_id", "ticker", "contract_type", "strike", "expiration",
                "dte_target", "moneyness_target", "partition", "event_family",
                "decision_available_utc", "signal_bar_open_utc", "bar_count", "bars_file",
            )
            with (root / "cohort_ledger.csv").open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                for ticker, indices in (("O:A", option_a_indices), ("O:B", option_b_indices)):
                    writer.writerow({
                        "anchor_id": ticker, "ticker": ticker, "contract_type": "CALL",
                        "strike": 2.0, "expiration": "2026-02-05", "dte_target": 30,
                        "moneyness_target": 0, "partition": "DISCOVERY",
                        "event_family": "ENTRY_FORMING",
                        "decision_available_utc": decision.isoformat(),
                        "signal_bar_open_utc": signal.isoformat(), "bar_count": len(indices),
                        "bars_file": f"bars/{ticker.replace(':', '_')}.json",
                    })

            with patch.object(sys, "argv", ["assemble", "--replay", str(replay), "--output", str(root)]):
                self.assertEqual(assemble_options_dna_ledger.main(), 0)

            with gzip.open(root / "component_ledger.csv.gz", "rt", newline="") as handle:
                components = {row["ticker"]: row for row in csv.DictReader(handle)}
            with (root / "forward_outcomes.csv").open(newline="") as handle:
                outcomes = {row["ticker"]: row for row in csv.DictReader(handle)}
            with (root / "forward_outcome_windows.csv").open(newline="") as handle:
                windows = list(csv.DictReader(handle))

        self.assertEqual(components["O:A"]["signal_bar_exists"], "True")
        self.assertEqual(components["O:A"]["coverage_at"], "1")
        self.assertLess(float(components["O:A"]["activity_ratio"]), 1.0)
        self.assertEqual(outcomes["O:A"]["next_bar_open"], str(0.5 + 21 * .01 - .01))
        self.assertIn("bars_to_trough", outcomes["O:A"])
        self.assertIn("peak_to_terminal_giveback_pct", outcomes["O:A"])

        self.assertEqual(components["O:B"]["signal_bar_exists"], "False")
        self.assertEqual(components["O:B"]["coverage_at"], "0")
        self.assertEqual(components["O:B"]["ready"], "False")
        self.assertIn("signal option bar absent", components["O:B"]["quality_reasons"])
        self.assertEqual(outcomes["O:B"]["observed_bars"], "0")
        self.assertEqual(outcomes["O:B"]["outcome_status"], "UNSCORED_SIGNAL_BAR_ABSENT")
        self.assertEqual(outcomes["O:B"]["right_censored"], "")
        self.assertEqual(outcomes["O:B"]["next_bar_open"], "")
        self.assertEqual(len(windows), 10)
        self.assertEqual(
            {row["window"] for row in windows}, {"H1", "D1", "D3", "D5", "D10"},
        )
        self.assertTrue(all(
            row["outcome_status"] == "UNSCORED_SIGNAL_BAR_ABSENT"
            for row in windows if row["ticker"] == "O:B"
        ))


if __name__ == "__main__":
    unittest.main()
