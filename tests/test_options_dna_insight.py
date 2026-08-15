"""Tests for the research-only contract-specific insight library.

Includes synthetic end-to-end scenarios that drive every advisory action:
WATCH, MANAGE, PROTECT, REDUCE, CLOSE, ROLL.
"""
import unittest

from options_dna_insight import ACTIONS, contract_insight


def obs(campaign="neu", upper_neg=False, exhaustion=False, sec_veto=False,
        sec_active=False, unchanged=False, dte=None, itm=None,
        premium=None, volume=None, has_position=False, direction="LONG"):
    return {
        "underlying": {
            "campaign_tone": campaign,
            "upper_neg": upper_neg,
            "exhaustion_warning": exhaustion,
        },
        "contract": {
            "unchanged_print": unchanged,
            "dte": dte,
            "itm": itm,
            "premium_return": premium,
            "volume_ratio": volume,
        },
        "catalyst": {"sec_veto": sec_veto, "sec_active": sec_active},
        "position": {"exists": has_position, "direction": direction},
    }


class InsightVocabularyTest(unittest.TestCase):
    def test_actions_are_the_declared_advisory_set(self):
        self.assertEqual(ACTIONS, ("WATCH", "MANAGE", "PROTECT", "REDUCE", "CLOSE", "ROLL"))


class InsightPrecedenceTest(unittest.TestCase):
    def test_sec_veto_protects_open_position(self):
        r = contract_insight(obs(sec_veto=True, has_position=True))
        self.assertEqual(r["action"], "PROTECT")

    def test_sec_veto_watches_when_flat(self):
        r = contract_insight(obs(sec_veto=True, has_position=False))
        self.assertEqual(r["action"], "WATCH")

    def test_sec_veto_outranks_constructive_campaign(self):
        r = contract_insight(obs(campaign="pos", premium=0.4, sec_veto=True, has_position=True))
        self.assertEqual(r["action"], "PROTECT")

    def test_broken_campaign_closes_position(self):
        r = contract_insight(obs(campaign="neg", has_position=True))
        self.assertEqual(r["action"], "CLOSE")

    def test_upper_neg_closes_position(self):
        r = contract_insight(obs(upper_neg=True, has_position=True))
        self.assertEqual(r["action"], "CLOSE")

    def test_broken_campaign_watches_when_flat(self):
        r = contract_insight(obs(campaign="neg", has_position=False))
        self.assertEqual(r["action"], "WATCH")


class InsightRollTest(unittest.TestCase):
    def test_deep_itm_spike_rolls(self):
        r = contract_insight(obs(campaign="pos", itm=True, premium=0.30, dte=30))
        self.assertEqual(r["action"], "ROLL")

    def test_volume_spike_rolls(self):
        r = contract_insight(obs(campaign="pos", itm=True, volume=3.5, dte=30))
        self.assertEqual(r["action"], "ROLL")

    def test_no_roll_when_dte_too_low(self):
        r = contract_insight(obs(campaign="pos", itm=True, premium=0.30, dte=7))
        self.assertEqual(r["action"], "MANAGE")

    def test_no_roll_without_spike(self):
        r = contract_insight(obs(campaign="pos", itm=True, premium=0.05, dte=30))
        self.assertEqual(r["action"], "MANAGE")


class InsightDtePressureTest(unittest.TestCase):
    def test_dte_pressure_otm_closes_position(self):
        r = contract_insight(obs(dte=5, itm=False, has_position=True))
        self.assertEqual(r["action"], "CLOSE")

    def test_dte_pressure_otm_watches_when_flat(self):
        r = contract_insight(obs(dte=5, itm=False, has_position=False))
        self.assertEqual(r["action"], "WATCH")


class InsightWeakeningTest(unittest.TestCase):
    def test_warn_campaign_reduces(self):
        r = contract_insight(obs(campaign="warn", has_position=True))
        self.assertEqual(r["action"], "REDUCE")

    def test_exhaustion_reduces(self):
        r = contract_insight(obs(campaign="pos", exhaustion=True, has_position=True))
        self.assertEqual(r["action"], "REDUCE")


class InsightLiquidityTest(unittest.TestCase):
    def test_unchanged_print_watches(self):
        r = contract_insight(obs(campaign="pos", unchanged=True, premium=0.0))
        self.assertEqual(r["action"], "WATCH")

    def test_conflicting_evidence_watches(self):
        r = contract_insight(obs(campaign="pos", premium=-0.20))
        self.assertEqual(r["action"], "WATCH")


class InsightConstructiveTest(unittest.TestCase):
    def test_constructive_responsive_manages(self):
        r = contract_insight(obs(campaign="pos", premium=0.10))
        self.assertEqual(r["action"], "MANAGE")


class InsightFallbackTest(unittest.TestCase):
    def test_no_signal_watches(self):
        r = contract_insight(obs())
        self.assertEqual(r["action"], "WATCH")


class InsightOutputShapeTest(unittest.TestCase):
    def test_output_keys(self):
        r = contract_insight(obs(campaign="pos", premium=0.10))
        self.assertEqual(
            set(r.keys()),
            {"action", "rationale_code", "evidence", "decision_change_condition", "confidence"},
        )

    def test_action_is_always_in_vocabulary(self):
        for o in (
            obs(),
            obs(campaign="pos", premium=0.10),
            obs(sec_veto=True, has_position=True),
            obs(campaign="neg", has_position=True),
            obs(campaign="pos", itm=True, premium=0.30, dte=30),
            obs(campaign="warn", has_position=True),
        ):
            self.assertIn(contract_insight(o)["action"], ACTIONS)


class InsightNoFutureLeakTest(unittest.TestCase):
    def test_rationale_never_mentions_outcome(self):
        r = contract_insight(obs(campaign="pos", premium=0.10))
        joined = " ".join(r["evidence"])
        for forbidden in ("outcome", "future", "will", "profit", "win"):
            self.assertNotIn(forbidden, joined.lower())


if __name__ == "__main__":
    unittest.main()
