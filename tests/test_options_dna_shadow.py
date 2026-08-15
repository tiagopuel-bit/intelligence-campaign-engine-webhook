import unittest

from options_dna_shadow import build_shadow_observation, transition_changed


def observation(**overrides):
    args = {
        "symbol": "AMC",
        "contract_ticker": "O:AMC260918C00002500",
        "decision_available_utc": "2026-08-14T15:30:00Z",
        "option_data_as_of_utc": "2026-08-14T15:15:00Z",
        "entitlement": "DELAYED_15M",
        "underlying_context": {"event_family": "ENTRY_FORMING"},
        "contract_components": {"ready": True, "relative_response_z": 1.2},
        "catalyst_context": {"active": False},
        "position_context": {"scope": "OBSERVE_ENTRY"},
        "calibration_version": None,
    }
    args.update(overrides)
    return build_shadow_observation(**args)


class OptionsDnaShadowTests(unittest.TestCase):
    def test_no_calibration_means_no_candidate_label(self):
        result = observation()
        self.assertEqual(result["gate"], "UNCALIBRATED")
        self.assertFalse(result["eligible_for_intraday_guidance"])
        self.assertEqual(result["candidate_labels"], [])

    def test_eod_entitlement_cannot_claim_intraday_guidance(self):
        result = observation(entitlement="END_OF_DAY", calibration_version="v1")
        self.assertEqual(result["gate"], "EOD_ONLY")
        self.assertFalse(result["eligible_for_intraday_guidance"])

    def test_stale_and_future_data_are_rejected(self):
        stale = observation(
            option_data_as_of_utc="2026-08-14T14:00:00Z",
            calibration_version="v1",
        )
        future = observation(
            option_data_as_of_utc="2026-08-14T15:31:00Z",
            calibration_version="v1",
        )
        self.assertEqual(stale["gate"], "STALE")
        self.assertEqual(future["gate"], "FUTURE_DATA_REJECTED")

    def test_quality_failure_precedes_freshness(self):
        result = observation(
            contract_components={"ready": False, "quality_reasons": ["sparse option activity"]},
            entitlement="END_OF_DAY",
            calibration_version="v1",
        )
        self.assertEqual(result["gate"], "UNRELIABLE")
        self.assertEqual(result["quality_reasons"], ["sparse option activity"])

    def test_frozen_version_and_fresh_data_only_make_rule_evaluation_eligible(self):
        result = observation(calibration_version="options-dna-v1")
        self.assertEqual(result["gate"], "READY_FOR_SHADOW_RULES")
        self.assertTrue(result["eligible_for_intraday_guidance"])
        self.assertEqual(result["candidate_labels"], [])

    def test_observation_identity_is_deterministic(self):
        self.assertEqual(observation()["observation_id"], observation()["observation_id"])

    def test_transition_deduplicates_unchanged_facts(self):
        first = observation()
        same = observation()
        changed = observation(underlying_context={"event_family": "THESIS_PRESSURE"})
        self.assertTrue(transition_changed(None, first))
        self.assertFalse(transition_changed(first, same))
        self.assertTrue(transition_changed(first, changed))


if __name__ == "__main__":
    unittest.main()
