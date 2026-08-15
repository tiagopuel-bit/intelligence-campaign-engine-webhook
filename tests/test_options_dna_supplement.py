import unittest

from options_dna_supplement import build_supplement_plan


def row(index, partition, family):
    year = 2025 if partition == "DISCOVERY" else 2026
    month = 1 + (index % 9)
    day = 1 + (index % 20)
    stamp = f"{year}-{month:02d}-{day:02d}T15:{(index % 4) * 15:02d}:00+00:00"
    return {
        "anchor_id": f"R{index}", "session_date": stamp[:10],
        "signal_bar_open_utc": stamp, "decision_available_utc": stamp,
        "event_family": family,
    }


class OptionsDnaSupplementTests(unittest.TestCase):
    def test_supplement_is_deterministic_disjoint_and_entry_only(self):
        replay = []
        index = 1
        for partition in ("DISCOVERY", "HOLDOUT"):
            for family in ("ENTRY_FORMING", "CONTINUATION", "THESIS_PRESSURE"):
                for _ in range(8):
                    replay.append(row(index, partition, family))
                    index += 1
        base = [dict(replay[0], anchor_id="BASE-1", partition="DISCOVERY")]
        first = build_supplement_plan(
            replay, base, holdout_start="2026-02-01",
            discovery_per_family=3, holdout_per_family=2,
        )
        second = build_supplement_plan(
            replay, base, holdout_start="2026-02-01",
            discovery_per_family=3, holdout_per_family=2,
        )
        self.assertEqual(first.added_rows, second.added_rows)
        self.assertEqual(first.base_anchor_sha256, second.base_anchor_sha256)
        self.assertEqual(first.supplement_anchor_sha256, second.supplement_anchor_sha256)
        self.assertEqual(first.combined_anchor_sha256, second.combined_anchor_sha256)
        self.assertNotEqual(first.base_anchor_sha256, first.combined_anchor_sha256)
        self.assertEqual(len(first.added_rows), 10)
        self.assertEqual(
            {item["event_family"] for item in first.added_rows},
            {"ENTRY_FORMING", "CONTINUATION"},
        )
        identities = {
            (item["signal_bar_open_utc"], item["event_family"])
            for item in first.combined_rows
        }
        self.assertEqual(len(identities), len(first.combined_rows))

    def test_insufficient_unused_pool_fails_before_writing(self):
        replay = [row(1, "DISCOVERY", "ENTRY_FORMING")]
        with self.assertRaisesRegex(ValueError, "pool"):
            build_supplement_plan(
                replay, [], holdout_start="2026-02-01",
                discovery_per_family=2, holdout_per_family=1,
            )


if __name__ == "__main__":
    unittest.main()
