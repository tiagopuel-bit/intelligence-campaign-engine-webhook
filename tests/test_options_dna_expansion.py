import json
import tempfile
import unittest
from pathlib import Path

from options_dna_expansion import acquire_expansion


class FakeClient:
    def __init__(self):
        self.reference_calls = []
        self.bar_calls = []

    def contracts_as_of(self, *, symbol, anchor_date, max_dte):
        self.reference_calls.append((symbol, anchor_date, max_dte))
        return [
            {"ticker": f"O:{anchor_date}-C", "contract_type": "call", "strike_price": 2.0,
             "expiration_date": "2026-02-04", "shares_per_contract": 100},
            {"ticker": "O:SHARED-P", "contract_type": "put", "strike_price": 2.0,
             "expiration_date": "2026-02-04", "shares_per_contract": 100},
        ]

    def option_bars(self, ticker, *, start_date, end_date):
        self.bar_calls.append((ticker, start_date, end_date))
        return [{"t": 1_800_000, "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]


def anchors():
    return [
        {"anchor_id": "A1", "session_date": "2026-01-05", "spot": 1.6,
         "decision_available_utc": "2026-01-05T15:00:00+00:00", "partition": "DISCOVERY",
         "event_family": "ENTRY_FORMING"},
        {"anchor_id": "A2", "session_date": "2026-01-06", "spot": 1.6,
         "decision_available_utc": "2026-01-06T15:00:00+00:00", "partition": "DISCOVERY",
         "event_family": "CONTINUATION"},
    ]


class OptionsDnaExpansionTests(unittest.TestCase):
    def test_reference_dates_and_unique_ticker_windows_are_cached(self):
        with tempfile.TemporaryDirectory() as tmp:
            client = FakeClient()
            first = acquire_expansion(anchors(), client=client, output=tmp, dte_targets=(30,))
            self.assertEqual(first.reference_requests, 2)
            self.assertEqual(first.unique_tickers, 3)
            self.assertEqual(first.bar_requests, 3)
            self.assertEqual(len(first.cohort_rows), 4)
            shared = next(call for call in client.bar_calls if call[0] == "O:SHARED-P")
            self.assertEqual(shared[1:], ("2025-12-29", "2026-01-27"))

            second_client = FakeClient()
            second = acquire_expansion(anchors(), client=second_client, output=tmp, dte_targets=(30,))
            self.assertEqual(second.reference_cache_hits, 2)
            self.assertEqual(second.bar_cache_hits, 3)
            self.assertEqual(second_client.reference_calls, [])
            self.assertEqual(second_client.bar_calls, [])

    def test_incomplete_bar_cache_is_refetched_for_union_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            bars = Path(tmp) / "bars"
            bars.mkdir()
            (bars / "O_SHARED-P.json").write_text(json.dumps({
                "ticker": "O:SHARED-P", "start_date": "2026-01-01",
                "end_date": "2026-01-10", "bars": [],
            }), encoding="utf-8")
            client = FakeClient()
            result = acquire_expansion(anchors(), client=client, output=tmp, dte_targets=(30,))
            self.assertIn("O:SHARED-P", {call[0] for call in client.bar_calls})
            self.assertEqual(result.bar_cache_hits, 0)


if __name__ == "__main__":
    unittest.main()
