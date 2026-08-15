import unittest

from options_dna_catalyst_ledger import build_catalyst_ledger


def anchor(at="2026-08-12T15:00:00+00:00"):
    return {
        "anchor_id": "A1", "partition": "HOLDOUT",
        "event_family": "THESIS_PRESSURE",
        "signal_bar_open_utc": "2026-08-12T14:45:00+00:00",
        "decision_available_utc": at,
    }


def filing(**overrides):
    row = {
        "accession": "F1", "base_form": "424B5",
        "category": "DILUTION_WATCH", "severity": "HIGH",
        "acceptance_time": "20260812100000",
        "first_seen_at": "2026-08-12T14:07:00+00:00",
        "seed_record": False,
    }
    row.update(overrides)
    return row


def payload(*, public=True, operational=True, filings=None):
    coverage = {}
    if public:
        coverage["PUBLIC_ACCEPTANCE"] = {
            "complete": True, "start_utc": "2026-08-01T00:00:00Z",
            "end_utc": "2026-08-14T00:00:00Z",
        }
    if operational:
        coverage["OPERATIONAL_SEEN"] = {
            "complete": True, "start_utc": "2026-08-10T00:00:00Z",
            "end_utc": "2026-08-14T00:00:00Z",
        }
    return {
        "source": "fixture", "as_of_utc": "2026-08-14T00:00:00Z",
        "coverage": coverage, "filings": [] if filings is None else filings,
    }


class CatalystLedgerTests(unittest.TestCase):
    def test_missing_coverage_is_not_treated_as_inactive(self):
        rows = build_catalyst_ledger([anchor()], payload(public=False))
        public = next(row for row in rows if row["mode"] == "PUBLIC_ACCEPTANCE")
        self.assertEqual(public["source_status"], "SOURCE_UNAVAILABLE")
        self.assertIsNone(public["active"])

    def test_covered_empty_corpus_is_explicitly_inactive(self):
        rows = build_catalyst_ledger([anchor()], payload())
        self.assertTrue(all(row["source_status"] == "INACTIVE" for row in rows))
        self.assertTrue(all(row["active"] is False for row in rows))

    def test_public_and_operational_clocks_remain_separate(self):
        f = filing(first_seen_at="2026-08-12T16:00:00Z")
        rows = build_catalyst_ledger([anchor()], payload(filings=[f]))
        by_mode = {row["mode"]: row for row in rows}
        self.assertEqual(by_mode["PUBLIC_ACCEPTANCE"]["source_status"], "ACTIVE")
        self.assertEqual(by_mode["OPERATIONAL_SEEN"]["source_status"], "INACTIVE")

    def test_seed_is_public_research_only(self):
        rows = build_catalyst_ledger([anchor()], payload(filings=[filing(seed_record=True)]))
        by_mode = {row["mode"]: row for row in rows}
        self.assertEqual(by_mode["PUBLIC_ACCEPTANCE"]["source_status"], "ACTIVE")
        self.assertEqual(by_mode["OPERATIONAL_SEEN"]["source_status"], "INACTIVE")

    def test_outside_declared_bounds_is_unavailable(self):
        rows = build_catalyst_ledger(
            [anchor("2026-07-01T15:00:00Z")], payload(),
        )
        self.assertTrue(all(row["source_status"] == "SOURCE_UNAVAILABLE" for row in rows))
        self.assertTrue(all(row["source_reason"] == "DECISION_OUTSIDE_COVERAGE" for row in rows))

    def test_direction_is_never_claimed(self):
        rows = build_catalyst_ledger([anchor()], payload(filings=[filing()]))
        self.assertTrue(all(row["direction_claim"] is None for row in rows))


if __name__ == "__main__":
    unittest.main()
