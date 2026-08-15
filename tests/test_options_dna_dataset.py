import csv
import gzip
import tempfile
import unittest
from pathlib import Path

import options_dna_dataset


FIELDS = [
    "t_utc", "close", "Event: STRONG START", "Event: CAMPAIGN START",
    "Event: IGNITION", "Event: ADD", "Event: RELOAD", "Event: MANAGE",
    "Event: PEAK", "Event: FAIL (any severity)", "Event: FAIL TEST",
    "campaignHealth", "phaseConfidence", "weaknessCount",
]


class OptionsDnaDatasetTests(unittest.TestCase):
    def test_replay_event_is_available_at_bar_close_and_fail_owns_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "replay.csv.gz"
            with gzip.open(path, "wt", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow({
                    "t_utc": "2026-01-05T14:30:00+00:00", "close": "2.50",
                    "Event: STRONG START": "1", "Event: FAIL TEST": "1",
                    "campaignHealth": "72", "phaseConfidence": "60", "weaknessCount": "2",
                })
            rows = options_dna_dataset.read_replay_anchors(path, timeframe_minutes=15)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["event_family"], "THESIS_PRESSURE")
        self.assertEqual(rows[0]["signal_bar_open_utc"], "2026-01-05T14:30:00+00:00")
        self.assertEqual(rows[0]["decision_available_utc"], "2026-01-05T14:45:00+00:00")

    def test_sample_is_partitioned_and_deterministic(self):
        anchors = []
        for year, partition_date in ((2025, "01-02"), (2026, "03-02")):
            for family, _members in options_dna_dataset.EVENT_FAMILIES:
                for day in range(1, 6):
                    anchors.append({
                        "decision_available_utc": f"{year}-{partition_date}T14:{day:02d}:00+00:00",
                        "session_date": f"{year}-{partition_date}",
                        "event_family": family,
                    })
        first = options_dna_dataset.select_anchor_sample(
            anchors, holdout_start="2026-02-01", per_family_partition=2,
        )
        second = options_dna_dataset.select_anchor_sample(
            list(reversed(anchors)), holdout_start="2026-02-01", per_family_partition=2,
        )
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)
        self.assertEqual({row["partition"] for row in first}, {"DISCOVERY", "HOLDOUT"})

    def test_cohort_rows_keep_anchor_identity(self):
        anchor = {
            "anchor_id": "AMC15-001", "spot": 2.0, "session_date": "2026-08-14",
            "event_family": "ENTRY_FORMING",
        }
        contracts = [
            {"ticker": "CALL", "contract_type": "call", "strike_price": 2.0,
             "expiration_date": "2026-09-13", "shares_per_contract": 100},
            {"ticker": "PUT", "contract_type": "put", "strike_price": 2.0,
             "expiration_date": "2026-09-13", "shares_per_contract": 100},
        ]
        rows = options_dna_dataset.build_cohort_rows(
            anchor, contracts, dte_targets=(30,), moneyness_targets=(0.0,),
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual({row["anchor_id"] for row in rows}, {"AMC15-001"})
        self.assertEqual({row["contract_type"] for row in rows}, {"CALL", "PUT"})

    def test_expansion_sample_uses_more_discovery_than_holdout(self):
        anchors = []
        for year, month in ((2025, 1), (2026, 3)):
            for family, _members in options_dna_dataset.EVENT_FAMILIES:
                for day in range(1, 21):
                    anchors.append({
                        "decision_available_utc": f"{year}-{month:02d}-{day:02d}T15:00:00+00:00",
                        "session_date": f"{year}-{month:02d}-{day:02d}",
                        "event_family": family,
                    })
        sample = options_dna_dataset.select_anchor_sample_by_partition(
            anchors, holdout_start="2026-02-01",
            per_family={"DISCOVERY": 15, "HOLDOUT": 8},
        )
        counts = {
            partition: sum(row["partition"] == partition for row in sample)
            for partition in ("DISCOVERY", "HOLDOUT")
        }
        self.assertEqual(counts, {"DISCOVERY": 60, "HOLDOUT": 32})
        self.assertEqual(len({row["anchor_id"] for row in sample}), 92)


if __name__ == "__main__":
    unittest.main()
