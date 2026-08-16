"""Tests for the MTF-relay parity comparison module."""
import unittest

from mtf_relay_compare import compare_alerts


def row(symbol, timeframe, bar_time, event, close=100.0, phase="EXPANSION", session="RTH"):
    return {
        "symbol": symbol, "timeframe": timeframe, "bar_time": bar_time,
        "bar_event": event, "close": close, "phase": phase, "session": session,
    }


class RelayCompareTests(unittest.TestCase):
    def test_perfect_parity(self):
        native = [
            row("AMC", "5", "1000", "ADD"),
            row("AMC", "15", "1001", "RELOAD"),
        ]
        relay = list(native)
        r = compare_alerts(native, relay)
        self.assertEqual(r.native_rows, 2)
        self.assertEqual(r.relay_rows, 2)
        self.assertEqual(r.matched_keys, 2)
        self.assertEqual(r.event_match, 2)
        self.assertEqual(r.event_mismatch, 0)
        self.assertEqual(r.missed_by_relay, 0)
        self.assertEqual(r.extra_in_relay, 0)

    def test_event_mismatch_detected(self):
        native = [row("AMC", "5", "1000", "ADD")]
        relay = [row("AMC", "5", "1000", "MANAGE")]
        r = compare_alerts(native, relay)
        self.assertEqual(r.event_mismatch, 1)
        self.assertEqual(r.event_match, 0)

    def test_missed_and_extra_detected(self):
        native = [row("AMC", "5", "1000", "ADD"), row("AMC", "15", "1001", "ADD")]
        relay = [row("AMC", "5", "1000", "ADD")]
        r = compare_alerts(native, relay)
        self.assertEqual(r.missed_by_relay, 1)
        self.assertEqual(r.extra_in_relay, 0)

    def test_close_tolerance(self):
        native = [row("AMC", "5", "1000", "ADD", close=100.0)]
        relay = [row("AMC", "5", "1000", "ADD", close=100.05)]
        self.assertEqual(compare_alerts(native, relay, close_tolerance=0.1).close_within_tolerance, 1)
        self.assertEqual(compare_alerts(native, relay, close_tolerance=0.0).close_mismatch, 1)

    def test_relay_duplicate_bar_flagged(self):
        native = [row("AMC", "5", "1000", "ADD")]
        relay = [row("AMC", "5", "1000", "ADD"), row("AMC", "5", "1000", "ADD")]
        r = compare_alerts(native, relay)
        self.assertEqual(r.relay_duplicate_bars, 1)

    def test_session_boundary_compared(self):
        native = [row("AMC", "D", "2000", "ADD", session="RTH")]
        relay = [row("AMC", "D", "2000", "ADD", session="POST")]
        r = compare_alerts(native, relay)
        self.assertEqual(r.session_mismatch, 1)


if __name__ == "__main__":
    unittest.main()
