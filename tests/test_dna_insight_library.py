"""Fixtures proving the DNA insight library selects only from supplied facts.

Every rule in the library is a pure function over the documented API fields.
These tests prove, for each rule family:

1. deterministic output (same input -> same output),
2. fact-only selection (extra/forbidden fields are ignored; missing facts
   degrade to a no-basis label instead of a fabricated read),
3. the vocabulary is closed (intents, conditions, relationships, instruments),
4. the engine never references invented data (no Greeks/IV/probability).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dna_insight_library as lib


# --- minimal, offline fixtures -------------------------------------------
# One state dict per campaign condition, matching research doc §3.3.
CONDITION_FIXTURES = {
    "broken": [{"timeframe": "240", "phase": "FAILED"}],
    "weakening": [{"timeframe": "240", "phase": "PEAK"}],
    "expanding": [{"timeframe": "180", "phase": "EXPANSION"}],
    "repairing": [{"timeframe": "60", "phase": "RELOAD", "recent_event": "RELOAD"}],
    "constructive": [{"timeframe": "15", "phase": "EXPANSION"}],
    "uncertain": [{"timeframe": "15", "phase": "WAIT"}],
}

# The nine representative symbols and their expected conditions, validated
# read-only against live Railway data on 2026-08-14 (research doc §8).
LIVE_VALIDATION = {
    "AMC": "repairing", "SPY": "weakening", "U": "constructive", "GME": "broken",
    "LULU": "uncertain", "PYPL": "expanding", "RBLX": "broken", "TSLA": "constructive",
    "VALE": "broken",
}

# Full, realistic multi-timeframe states for a few symbols (subset of the live
# shapes) to exercise the tier model rather than a single row.
AMC_STATES = [
    {"timeframe": "180", "phase": "WAIT", "recent_event": ""},
    {"timeframe": "60", "phase": "EXPANSION", "recent_event": "ADD"},
    {"timeframe": "15", "phase": "EXPANSION", "recent_event": "ADD"},
    {"timeframe": "3", "phase": "RELOAD", "recent_event": "RELOAD"},
]
VALE_STATES = [
    {"timeframe": "180", "phase": "FAILED"},
    {"timeframe": "60", "phase": "FAILED"},
    {"timeframe": "30", "phase": "FAILED"},
    {"timeframe": "3", "phase": "FAILED"},
]

SHARE_PROFITABLE = {"avg_cost": 1.52, "current_price": 2.0, "total_return_pct": 31.6,
                    "total_pnl": 300.0, "first_entry": "2026-04-20T07:17:00Z"}
CALL_ITM = {"itm": True, "strike": 1.5, "expiration": "2026-09-18", "avg_cost": 0.51,
            "current_price": 1.14, "total_return_pct": 123.5, "first_entry": "2026-04-20T07:17:00Z"}
CALL_NEAR_EXPIRY = {"itm": True, "strike": 1.5, "expiration": "2026-08-15",
                    "avg_cost": 0.22, "total_return_pct": 200.0}

FORBIDDEN_JUNK = {"theta": -0.01, "delta": 0.8, "implied_volatility": 0.5,
                  "probability_of_profit": 0.75, "news_headline": "upgrade",
                  "fair_value": 2.4}


class CampaignConditionTests(unittest.TestCase):
    def test_each_condition_from_minimal_fixture(self):
        for expected, states in CONDITION_FIXTURES.items():
            self.assertEqual(lib.campaign_condition(states), expected)

    def test_live_validated_symbols(self):
        # Encoded expected conditions mirror the live read-only validation.
        self.assertEqual(lib.campaign_condition(AMC_STATES), LIVE_VALIDATION["AMC"])
        self.assertEqual(lib.campaign_condition(VALE_STATES), LIVE_VALIDATION["VALE"])

    def test_condition_is_deterministic(self):
        for states in CONDITION_FIXTURES.values():
            self.assertEqual(lib.campaign_condition(states), lib.campaign_condition(list(states)))

    def test_condition_output_is_closed_vocabulary(self):
        for states in CONDITION_FIXTURES.values():
            self.assertIn(lib.campaign_condition(states), lib.CAMPAIGN_CONDITIONS)


class TfRelationshipTests(unittest.TestCase):
    def test_no_evidence_returns_none(self):
        self.assertIsNone(lib.tf_relationship([{"timeframe": "15", "phase": "WAIT"}]))

    def test_weakness_propagating(self):
        self.assertEqual(lib.tf_relationship(VALE_STATES), "weakness propagating")

    def test_relationship_is_closed_vocabulary(self):
        r = lib.tf_relationship(AMC_STATES)
        self.assertTrue(r is None or r in lib.TF_RELATIONSHIPS)


class HoldingStateTests(unittest.TestCase):
    def test_share_profitable(self):
        hs = lib.holding_state(SHARE_PROFITABLE, "shares")
        self.assertTrue(hs["profitable"])
        self.assertIsNone(hs["moneyness"])

    def test_call_itm_with_dte(self):
        hs = lib.holding_state(CALL_ITM, "long call")
        self.assertEqual(hs["moneyness"], "ITM")
        self.assertIn(hs["dte_pressure"], ("low", "medium"))

    def test_near_expiry_is_high_pressure(self):
        hs = lib.holding_state(CALL_NEAR_EXPIRY, "long call")
        self.assertEqual(hs["dte_pressure"], "high")


class ComposeTests(unittest.TestCase):
    def test_intent_is_closed_vocabulary(self):
        for instrument in lib.INSTRUMENTS:
            for condition in lib.CAMPAIGN_CONDITIONS:
                states = CONDITION_FIXTURES[condition]
                out = lib.compose(states, CALL_ITM, instrument)
                self.assertIn(out["navigation_intent"], lib.INTENTS)

    def test_compose_is_deterministic(self):
        a = lib.compose(AMC_STATES, SHARE_PROFITABLE, "shares")
        b = lib.compose(list(AMC_STATES), dict(SHARE_PROFITABLE), "shares")
        self.assertEqual(a, b)

    def test_broken_campaign_harms_calls_helps_puts(self):
        broken = CONDITION_FIXTURES["broken"]
        self.assertEqual(lib.compose(broken, CALL_ITM, "long call")["navigation_intent"],
                         "close / stand aside")
        self.assertEqual(lib.compose(broken, CALL_ITM, "long put")["navigation_intent"], "hold")

    def test_expanding_campaign_helps_calls_harms_puts(self):
        expanding = CONDITION_FIXTURES["expanding"]
        self.assertEqual(lib.compose(expanding, CALL_ITM, "long call")["navigation_intent"],
                         "consider roll")
        self.assertEqual(lib.compose(expanding, CALL_ITM, "long put")["navigation_intent"],
                         "close / stand aside")

    def test_no_facts_yields_no_basis(self):
        out = lib.compose([], {}, "shares")
        self.assertEqual(out["confidence"], "no-basis")
        self.assertEqual(out["navigation_intent"], "wait")

    def test_fact_only_extra_fields_ignored(self):
        base = lib.compose(AMC_STATES, CALL_ITM, "long call")
        junk = dict(CALL_ITM)
        junk.update(FORBIDDEN_JUNK)
        self.assertEqual(lib.compose(AMC_STATES, junk, "long call"), base)

    def test_output_never_references_forbidden_data(self):
        for instrument in lib.INSTRUMENTS:
            out = lib.compose(CONDITION_FIXTURES["expanding"], CALL_ITM, instrument)
            text = " ".join([out["conclusion"]] + out["evidence"]).lower()
            for bad in ("theta", "delta", "gamma", "vega", "rho", "iv", "implied",
                        "probability", "fair value", "predicted", "guaranteed"):
                self.assertNotIn(bad, text)


class VocabularyClosureTests(unittest.TestCase):
    def test_rule_engine_references_no_greeks(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), "dna_insight_library.py")) as fh:
            src = fh.read()
        for bad in ("theta", "delta", "gamma", "vega", "rho", "implied_volatility",
                    "probability_of_profit"):
            self.assertNotIn(bad, src)

    def test_all_composition_cells_defined(self):
        self.assertEqual(set(lib._COMPOSITION.keys()), set(lib.INSTRUMENTS))
        for instrument in lib.INSTRUMENTS:
            self.assertEqual(set(lib._COMPOSITION[instrument].keys()),
                             set(lib.CAMPAIGN_CONDITIONS))


if __name__ == "__main__":
    unittest.main()
