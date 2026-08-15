"""Static acceptance checks for the PAPER_ONLY Asset Page challenge UI."""

from html.parser import HTMLParser
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "ui" / "dna_dashboard.html"


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.start_tags = []

    def handle_starttag(self, tag, attrs):
        self.start_tags.append(tag)


class PaperChallengeUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = PAGE.read_text(encoding="utf-8")

    def test_page_structure_remains_single_document(self):
        parser = _Parser()
        parser.feed(self.html)
        self.assertEqual(parser.start_tags.count("html"), 1)
        self.assertEqual(parser.start_tags.count("head"), 1)
        self.assertEqual(parser.start_tags.count("body"), 1)
        self.assertEqual(self.html.count("<style>"), 1)

    def test_challenge_contains_approved_goal_contract(self):
        for text in (
            "AMC Portfolio Challenge",
            "Silver",
            "Gold",
            "Premium",
            "Diamond",
            "Strategic floor 30%",
            "Ends Jan 31, 2027",
        ):
            self.assertIn(text, self.html)

    def test_daily_report_and_decision_queue_are_present(self):
        for text in (
            "Decision queue",
            "Daily AMC report",
            "Portfolio progress",
            "AMC campaign",
            "Decision window",
            "Position decisions",
            "Contract efficiency / catalyst",
            "Paper actions / baseline",
        ):
            self.assertIn(text, self.html)

    def test_execution_controls_fail_closed_on_provider_readiness(self):
        self.assertIn("h.authoritative_provider_ready === true", self.html)
        self.assertIn("P2A integration pending", self.html)
        self.assertIn("Controls remain locked", self.html)
        self.assertIn("Requires P2A provider readiness and VERY_HIGH evidence", self.html)

    def test_paper_mutations_are_authenticated_and_never_call_a_broker(self):
        self.assertIn('Object.assign({ "Content-Type": "application/json" }, authHeaders())', self.html)
        self.assertIn('"/paper/proposals/"', self.html)
        lowered = self.html.lower()
        self.assertNotIn("/broker/order", lowered)
        self.assertNotIn("/orders/live", lowered)

    def test_server_owned_evidence_is_not_sent_by_the_ui(self):
        mutation_start = self.html.index("function paperMutation")
        mutation_end = self.html.index("function wirePaperControls", mutation_start)
        mutation = self.html[mutation_start:mutation_end]
        for forbidden in (
            "very_high:",
            "evidence:",
            "freshness:",
            "price_source:",
            "price_reference:",
            "policy_sha256:",
            "mode:",
        ):
            self.assertNotIn(forbidden, mutation)


if __name__ == "__main__":
    unittest.main()
