import unittest

from options_dna_position_replay import build_position_episode_ledgers


def bar(index, close=1.0):
    t = index * 900_000
    return {"t": t, "o": close, "h": close * 1.05, "l": close * .95, "c": close, "v": 10 + index}


def anchor(index, family="CONTINUATION"):
    from datetime import datetime, timezone
    signal = datetime.fromtimestamp(index * 900, tz=timezone.utc)
    decision = datetime.fromtimestamp((index + 1) * 900, tz=timezone.utc)
    return {
        "signal_bar_open_utc": signal.isoformat(),
        "decision_available_utc": decision.isoformat(),
        "session_date": signal.date().isoformat(), "spot": 2.0,
        "event_family": family, "events": "RELOAD",
        "campaign_health": 80.0, "phase_confidence": 70.0,
        "weakness_count": 0.0,
    }


def cohort():
    row = anchor(20, "ENTRY_FORMING")
    row.update({
        "anchor_id": "ENTRY-1", "ticker": "O:TEST", "contract_type": "CALL",
        "strike": 2.0, "expiration": "1970-02-15", "dte_target": 30,
        "moneyness_target": 0.0, "partition": "DISCOVERY",
    })
    return row


class PositionReplayTests(unittest.TestCase):
    def setUp(self):
        self.underlying = [bar(i, 2.0 + i * .001) for i in range(120)]
        self.options = [bar(i, 1.0 + i * .01) for i in range(120)]

    def test_opens_only_at_exact_next_option_bar_open(self):
        missing = [row for row in self.options if row["t"] != 21 * 900_000]
        result = build_position_episode_ledgers(
            [cohort()], [anchor(30)], {"O:TEST": missing}, self.underlying,
        )
        self.assertEqual(result["episodes"], [])
        self.assertEqual(result["rejections"][0]["reason"], "EXACT_NEXT_BAR_OPEN_ABSENT")

    def test_tracks_same_contract_at_later_dna_event(self):
        result = build_position_episode_ledgers(
            [cohort()], [anchor(30)], {"O:TEST": self.options}, self.underlying,
        )
        self.assertEqual(len(result["episodes"]), 1)
        self.assertEqual(len(result["snapshots"]), 1)
        snapshot = result["snapshots"][0]
        self.assertEqual(snapshot["navigation_scope"], "MANAGE_OPEN_LONG_PREMIUM")
        self.assertAlmostEqual(snapshot["entry_price"], 1.21)
        self.assertAlmostEqual(snapshot["current_premium"], 1.30)
        self.assertAlmostEqual(snapshot["unrealized_pnl_pct"], (1.30 / 1.21 - 1) * 100)

    def test_missing_snapshot_print_is_not_shifted(self):
        missing = [row for row in self.options if row["t"] != 30 * 900_000]
        result = build_position_episode_ledgers(
            [cohort()], [anchor(30)], {"O:TEST": missing}, self.underlying,
        )
        self.assertEqual(result["snapshots"], [])
        self.assertIn("SNAPSHOT_SIGNAL_BAR_ABSENT", {row["reason"] for row in result["rejections"]})

    def test_future_paths_are_separate_from_causal_snapshot(self):
        result = build_position_episode_ledgers(
            [cohort()], [anchor(30)], {"O:TEST": self.options}, self.underlying,
        )
        snapshot = result["snapshots"][0]
        self.assertFalse(any("mfe" in key or "mae" in key or "terminal" in key for key in snapshot))
        self.assertEqual(len(result["outcomes"]), 5)
        self.assertEqual({row["window"] for row in result["outcomes"]}, {"H1", "D1", "D3", "D5", "D10"})


if __name__ == "__main__":
    unittest.main()
