import unittest

from options_dna_catalyst import catalyst_context_at, join_anchor_catalysts


def filing(**overrides):
    row = {
        "accession": "A1",
        "base_form": "424B5",
        "category": "DILUTION_WATCH",
        "severity": "HIGH",
        "acceptance_time": "20260812100000",
        "first_seen_at": "2026-08-12T14:07:00+00:00",
        "seed_record": False,
    }
    row.update(overrides)
    return row


class OptionsDnaCatalystTests(unittest.TestCase):
    def test_future_filing_never_leaks_into_context(self):
        result = catalyst_context_at(
            [filing()], "2026-08-12T13:59:00+00:00", mode="OPERATIONAL_SEEN",
        )
        self.assertFalse(result["active"])

    def test_operational_clock_preserves_polling_delay(self):
        before_poll = catalyst_context_at(
            [filing()], "2026-08-12T14:05:00+00:00", mode="OPERATIONAL_SEEN",
        )
        after_poll = catalyst_context_at(
            [filing()], "2026-08-12T14:08:00+00:00", mode="OPERATIONAL_SEEN",
        )
        public = catalyst_context_at(
            [filing()], "2026-08-12T14:05:00+00:00", mode="PUBLIC_ACCEPTANCE",
        )
        self.assertFalse(before_poll["active"])
        self.assertTrue(after_poll["active"])
        self.assertTrue(public["active"])

    def test_seed_records_are_researchable_but_not_live_alerts(self):
        seeded = filing(seed_record=True)
        operational = catalyst_context_at(
            [seeded], "2026-08-12T15:00:00+00:00", mode="OPERATIONAL_SEEN",
        )
        research = catalyst_context_at(
            [seeded], "2026-08-12T15:00:00+00:00", mode="PUBLIC_ACCEPTANCE",
        )
        self.assertFalse(operational["active"])
        self.assertTrue(research["active"])

    def test_s3_is_capacity_only_and_has_no_direction_claim(self):
        result = catalyst_context_at(
            [filing(base_form="S-3", severity="MEDIUM")],
            "2026-08-12T15:00:00+00:00", mode="PUBLIC_ACCEPTANCE",
        )
        self.assertTrue(result["capacity_only"])
        self.assertIsNone(result["direction_claim"])

    def test_highest_severity_available_filing_owns_context(self):
        rows = [
            filing(accession="LOW", base_form="10-Q", severity="INFO"),
            filing(accession="HIGH"),
        ]
        result = catalyst_context_at(
            rows, "2026-08-12T15:00:00+00:00", mode="PUBLIC_ACCEPTANCE",
        )
        self.assertEqual(result["accession"], "HIGH")
        self.assertEqual(result["filing_count"], 2)

    def test_join_uses_decision_available_not_signal_open(self):
        anchors = [{
            "anchor_id": "A",
            "signal_bar_open_utc": "2026-08-12T13:45:00+00:00",
            "decision_available_utc": "2026-08-12T14:00:00+00:00",
        }]
        joined = join_anchor_catalysts(anchors, [filing(first_seen_at="2026-08-12T13:55:00+00:00")], mode="OPERATIONAL_SEEN")
        self.assertTrue(joined[0]["catalyst"]["active"])


if __name__ == "__main__":
    unittest.main()
