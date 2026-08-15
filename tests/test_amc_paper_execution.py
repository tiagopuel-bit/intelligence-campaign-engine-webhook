"""Deterministic P0 contract tests for the AMC paper execution experiment.

Proves the frozen artifacts parse, forbid any live mode, enforce append-only
transitions, and never reference future outcomes during proposal generation.
"""
import unittest
from pathlib import Path

from paper_execution.policy import (
    ALLOWED_TRANSITIONS,
    load_policy,
    paper_only,
    validate_transition,
    has_future_fragments,
)

ROOT = Path(__file__).resolve().parents[1]


class PaperPolicyTests(unittest.TestCase):
    def test_policy_parses_and_declares_required_contract(self):
        policy = load_policy()
        self.assertEqual(policy["paper_only"], True)
        self.assertIn("very_high_roots", policy)
        self.assertIn("action_policies", policy)
        self.assertIn("fill_model", policy)
        self.assertIn("only_auto_mode", policy)
        self.assertEqual(policy["only_auto_mode"], "AUTO_IF_VERY_HIGH_PAPER")

    def test_forbidden_live_mode_is_absent(self):
        policy = load_policy()
        self.assertTrue(paper_only(policy))
        for mode in policy["allowed_modes"]:
            self.assertNotIn("LIVE", mode)
            self.assertNotIn("BROKER", mode)
        # The Options DNA finding is explicitly excluded from VERY_HIGH.
        self.assertIn("HISTORICAL_RESEARCH_FINDING_NEEDS_EXTERNAL_REPLICATION",
                      policy["options_dna_relationship"])

    def test_append_only_transitions(self):
        self.assertTrue(validate_transition("DRAFT", "PENDING_APPROVAL"))
        self.assertTrue(validate_transition("PENDING_APPROVAL", "APPROVED"))
        self.assertTrue(validate_transition("PENDING_APPROVAL", "REVALIDATING"))
        self.assertTrue(validate_transition("REVALIDATING", "PAPER_EXECUTED"))
        self.assertTrue(validate_transition("PAPER_EXECUTED", "FILLED"))
        # No response at the deadline must revalidate, not silently execute.
        self.assertFalse(validate_transition("PENDING_APPROVAL", "PAPER_EXECUTED"))
        # No reverse/history-rewriting transitions.
        self.assertFalse(validate_transition("PAPER_EXECUTED", "PENDING_APPROVAL"))
        self.assertFalse(validate_transition("APPROVED", "DRAFT"))

    def test_no_future_outcome_access_in_policy(self):
        policy = load_policy()
        # The causal roots and conditions must reference only causal fields.
        self.assertFalse(has_future_fragments(policy["very_high_roots"]))
        self.assertFalse(has_future_fragments(policy["action_policies"]))

    def test_schema_has_append_only_event_ledger(self):
        schema = (ROOT / "paper_execution" / "schema_v1.sql").read_text(encoding="utf-8")
        self.assertIn("pe_proposal_events", schema)
        self.assertIn("pe_order_proposals", schema)
        self.assertIn("pe_paper_fills", schema)
        self.assertIn("UNIQUE(experiment_id, idempotency_key)", schema)
        self.assertNotIn("UPDATE pe_proposal_events", schema)


if __name__ == "__main__":
    unittest.main()
