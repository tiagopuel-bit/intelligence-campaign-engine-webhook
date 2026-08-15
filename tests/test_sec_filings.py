"""Tests for the SEC EDGAR filing watcher (sec_filings module + endpoint).

Deterministic and offline: every SEC request is mocked (no live network). Each
test proves one rule selects only from supplied facts and that state is
durable, idempotent, and safe.
"""

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sec_filings
import webhook_receiver
from webhook_receiver import app

TEST_SEC_USER_AGENT = "DNA Campaign Engine Test Suite"
TEST_STATE_TOKEN = "test-state-token"


def sec_response(filings):
    """Shape a minimal SEC submissions JSON from a list of filing dicts."""
    return {
        "filings": {
            "recent": {
                "form": [x["form"] for x in filings],
                "filingDate": [x["filing_date"] for x in filings],
                "accessionNumber": [x["accession"] for x in filings],
                "primaryDocument": [x["primary_document"] for x in filings],
                "acceptanceDateTime": [x["acceptance"] for x in filings],
            }
        }
    }


def f(accession, form, date="2026-08-13", doc="abc.htm", acceptance="2026-08-13T16:00:00.000Z"):
    return {"accession": accession, "form": form, "filing_date": date,
            "primary_document": doc, "acceptance": acceptance}


class SecFilingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls.db_path = cls._tmp.name
        cls._orig_db = webhook_receiver.DB_PATH
        webhook_receiver.DB_PATH = Path(cls.db_path)
        cls._orig_token = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN
        webhook_receiver.init_db()

    @classmethod
    def tearDownClass(cls):
        webhook_receiver.DB_PATH = cls._orig_db
        webhook_receiver.STATE_API_TOKEN = cls._orig_token
        os.unlink(cls.db_path)

    def setUp(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("DELETE FROM sec_filings")
        conn.execute("DELETE FROM sec_filing_watch_state")
        conn.commit()
        conn.close()

    def _count_filings(self):
        conn = sqlite3.connect(self.db_path)
        n = conn.execute("SELECT COUNT(*) FROM sec_filings").fetchone()[0]
        conn.close()
        return n

    # 1. Missing SEC_USER_AGENT -> no request, configuration error
    def test_missing_user_agent_makes_no_request(self):
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": ""}), \
             mock.patch.object(sec_filings, "fetch_submissions",
                               side_effect=AssertionError("must not call SEC")) as fetch:
            result = sec_filings.poll_symbol(self.db_path, "AMC")
        fetch.assert_not_called()
        self.assertFalse(result["configured"])
        self.assertIn("SEC_USER_AGENT", result["errors"][0])

    # 2. First poll silently seeds all existing watched accessions
    def test_first_poll_seeds_silently(self):
        filings = [f("A1", "8-K"), f("A2", "10-Q"), f("A3", "4")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}), \
             mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
            result = sec_filings.poll_symbol(self.db_path, "AMC")
        self.assertTrue(result["seeded"])
        self.assertEqual(result["new_filings"], [])
        self.assertEqual(self._count_filings(), 3)

    # 3. Second identical poll produces zero new filings
    def test_second_poll_zero_new(self):
        filings = [f("A1", "8-K"), f("A2", "10-Q")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}):
            with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
                first = sec_filings.poll_symbol(self.db_path, "AMC")
            with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
                second = sec_filings.poll_symbol(self.db_path, "AMC")
        self.assertTrue(first["seeded"])
        self.assertFalse(second["seeded"])
        self.assertEqual(second["new_filings"], [])

    # 4. One new filing produces exactly one durable new record
    def test_one_new_filing_durable(self):
        initial = [f("A1", "8-K"), f("A2", "10-Q")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}):
            with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(initial), [])):
                sec_filings.poll_symbol(self.db_path, "AMC")
            with mock.patch.object(sec_filings, "fetch_submissions",
                                   return_value=(sec_response(initial + [f("A3", "424B5")]), [])):
                result = sec_filings.poll_symbol(self.db_path, "AMC")
        self.assertEqual([x["accession"] for x in result["new_filings"]], ["A3"])
        self.assertEqual(result["new_filings"][0]["seed_record"], False)
        self.assertEqual(result["new_filings"][0]["severity"], "HIGH")
        self.assertEqual(self._count_filings(), 3)

    # 5. Redeploy/re-init against the same DB does not repeat the alert
    def test_reinit_does_not_repeat_alert(self):
        filings = [f("A1", "8-K"), f("A2", "4")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}):
            with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
                sec_filings.poll_symbol(self.db_path, "AMC")
            # simulate redeploy: re-run schema creation + poll identical data
            conn = sqlite3.connect(self.db_path)
            sec_filings.ensure_schema(conn)
            conn.commit()
            conn.close()
            with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
                result = sec_filings.poll_symbol(self.db_path, "AMC")
        self.assertEqual(result["new_filings"], [])
        self.assertEqual(self._count_filings(), 2)

    # 6. Concurrent/idempotent upsert cannot duplicate an accession
    def test_concurrent_upsert_no_duplicate(self):
        filings = [f("A1", "8-K")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}):
            for _ in range(3):
                with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
                    sec_filings.poll_symbol(self.db_path, "AMC")
        self.assertEqual(self._count_filings(), 1)

    # 7. All target form categories and severities are table-tested
    def test_form_category_severity_table(self):
        expected = {
            "424B5": ("DILUTION_WATCH", "HIGH"), "FWP": ("DILUTION_WATCH", "HIGH"),
            "S-3": ("DILUTION_WATCH", "MEDIUM"), "8-K": ("MATERIAL_FILING", "MEDIUM"),
            "10-Q": ("MATERIAL_FILING", "INFO"), "10-K": ("MATERIAL_FILING", "INFO"),
            "3": ("INSIDER_FILING", "INFO"), "4": ("INSIDER_FILING", "INFO"),
            "5": ("INSIDER_FILING", "INFO"),
        }
        for form, (cat, sev) in expected.items():
            self.assertEqual(sec_filings.WATCHED_FORMS[form], (cat, sev))
            self.assertEqual(sec_filings.normalize_form(form), (form, None))

    # 8. Amendments/variants preserve raw form and are labeled honestly
    def test_variants_preserve_raw_form(self):
        self.assertEqual(sec_filings.normalize_form("8-K/A"), ("8-K", "amendment"))
        self.assertEqual(sec_filings.normalize_form("S-3ASR"), ("S-3", "automatic shelf registration"))
        filings = [f("A1", "8-K/A"), f("A2", "S-3ASR")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}), \
             mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
            sec_filings.poll_symbol(self.db_path, "AMC")
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        rows = {r["accession"]: r for r in conn.execute("SELECT * FROM sec_filings")}
        conn.close()
        self.assertEqual(rows["A1"]["form"], "8-K/A")
        self.assertEqual(rows["A1"]["base_form"], "8-K")
        self.assertEqual(rows["A2"]["form"], "S-3ASR")
        self.assertEqual(rows["A2"]["base_form"], "S-3")

    # 9. Unwatched forms are ignored
    def test_unwatched_forms_ignored(self):
        filings = [f("A1", "8-K"), f("A2", "SC 13D"), f("A3", "10-D")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}), \
             mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
            sec_filings.poll_symbol(self.db_path, "AMC")
        conn = sqlite3.connect(self.db_path)
        forms = [r[0] for r in conn.execute("SELECT form FROM sec_filings")]
        conn.close()
        self.assertEqual(forms, ["8-K"])

    # 10. Malformed columnar SEC arrays fail safely
    def test_malformed_arrays_fail_safe(self):
        bad = {"filings": {"recent": {"form": ["8-K", "10-Q"], "filingDate": ["2026-08-13"],
                                       "accessionNumber": ["A1", "A2"],
                                       "primaryDocument": ["a", "b"],
                                       "acceptanceDateTime": ["x", "y"]}}}
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}), \
             mock.patch.object(sec_filings, "fetch_submissions", return_value=(bad, [])):
            result = sec_filings.poll_symbol(self.db_path, "AMC")
        self.assertTrue(any("mismatched" in e for e in result["errors"]))
        self.assertEqual(self._count_filings(), 0)

    # 11. SEC timeout/HTTP/JSON failure preserves prior state, records error
    def test_upstream_failure_preserves_state(self):
        filings = [f("A1", "8-K")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}):
            with mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
                sec_filings.poll_symbol(self.db_path, "AMC")
            before = sec_filings.get_filings_state(self.db_path, "AMC")
            with mock.patch.object(sec_filings, "fetch_submissions",
                                   return_value=(None, ["SEC request timed out"])):
                result = sec_filings.poll_symbol(self.db_path, "AMC")
            after = sec_filings.get_filings_state(self.db_path, "AMC")
        self.assertEqual(self._count_filings(), 1)  # preserved
        self.assertEqual(after["last_success_at"], before["last_success_at"])  # preserved
        self.assertIn("timed out", after["error"])
        self.assertTrue(any("timed out" in e for e in result["errors"]))

    # 12. API requires state auth and validates symbol/window
    def test_endpoint_requires_auth_and_validates(self):
        client = app.test_client()
        self.assertEqual(client.get("/filings/AMC").status_code, 401)
        h = {"Authorization": f"Bearer {TEST_STATE_TOKEN}"}
        self.assertEqual(client.get("/filings/AMC", headers=h).status_code, 200)
        self.assertEqual(client.get("/filings/bad!symbol", headers=h).status_code, 400)
        self.assertEqual(client.get("/filings/SPY", headers=h).status_code, 404)  # unmapped
        self.assertEqual(client.get("/filings/AMC?window_hours=9999", headers=h).status_code, 400)

    # 13. API reads only SQLite and never calls SEC
    def test_endpoint_reads_only_sqlite(self):
        filings = [f("A1", "8-K")]
        with mock.patch.dict(os.environ, {"SEC_USER_AGENT": TEST_SEC_USER_AGENT}), \
             mock.patch.object(sec_filings, "fetch_submissions", return_value=(sec_response(filings), [])):
            sec_filings.poll_symbol(self.db_path, "AMC")
        client = app.test_client()
        with mock.patch.object(sec_filings, "fetch_submissions",
                               side_effect=AssertionError("endpoint must not call SEC")):
            r = client.get("/filings/AMC", headers={"Authorization": f"Bearer {TEST_STATE_TOKEN}"})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertEqual(data["symbol"], "AMC")
        self.assertEqual(data["seeded"], True)
        self.assertEqual(data["recent"][0]["form"], "8-K")

    # 14. Filing URL construction rejects unsafe/non-SEC document paths
    def test_url_construction_rejects_unsafe(self):
        self.assertEqual(
            sec_filings.build_filing_url("0001411579", "0001411579-24-000123", "abc.htm"),
            "https://www.sec.gov/Archives/edgar/data/1411579/000141157924000123/abc.htm")
        self.assertIsNone(sec_filings.build_filing_url("0001411579", "0001411579-24-000123", "../etc/passwd"))
        self.assertIsNone(sec_filings.build_filing_url("0001411579", "0001411579-24-000123", "/abs/path.htm"))
        self.assertIsNone(sec_filings.build_filing_url("0001411579", "0001411579-24-000123", "https://evil.com/x"))
        self.assertIsNone(sec_filings.build_filing_url("0001411579", "notanaccession", "abc.htm"))
        self.assertIsNone(sec_filings.build_filing_url("0001411579", "0001411579-24-000123", ""))

    # 15. Dashboard static checks: /filings/, SEC status handling, advisory wording
    def test_dashboard_static_checks(self):
        html = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "ui" / "dna_dashboard.html"
        src = html.read_text()
        self.assertIn("/filings/", src)
        self.assertIn("SEC_USER_AGENT", src)
        self.assertIn("www.sec.gov", src)
        self.assertIn("secSafeUrl", src)
        self.assertIn("SEC filing", src)
        self.assertIn("not an entry signal", src)  # advisory-only wording
        self.assertIn("offering / dilution watch", src)
        self.assertIn("financing capacity registered", src)


if __name__ == "__main__":
    unittest.main()
