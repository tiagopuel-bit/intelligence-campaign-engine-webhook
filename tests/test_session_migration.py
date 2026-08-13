"""Test the session-capture migration against a LOCAL COPY of the DB.

Copies dna_alerts.db to a temp file (never touches the live store), applies the
ALTER TABLE, and asserts: (a) the column exists, (b) row count is unchanged,
(c) existing rows read NULL session (no data loss), (d) a new INSERT with a
session value works.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "dna_alerts.db"
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_add_session_column.sql"


@unittest.skipUnless(DB.exists(), "no local dna_alerts.db to copy")
class TestSessionMigration(unittest.TestCase):
    def test_migration_on_copy(self):
        with tempfile.TemporaryDirectory() as td:
            copy = Path(td) / "dna_alerts_copy.db"
            shutil.copy2(DB, copy)

            conn = sqlite3.connect(copy)
            conn.row_factory = sqlite3.Row

            # Pre-state: row count + column list.
            before = conn.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
            cols_before = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
            self.assertNotIn("session", cols_before)

            # Apply migration.
            conn.execute(MIGRATION.read_text())
            conn.commit()

            # Post-state.
            after = conn.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
            cols_after = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
            self.assertIn("session", cols_after)
            self.assertEqual(before, after, "row count changed (data loss!)")

            # Existing rows read NULL session (no fabricated value).
            null_session = conn.execute(
                "SELECT COUNT(*) n FROM alerts WHERE session IS NULL").fetchone()["n"]
            self.assertEqual(null_session, after)

            # A new INSERT with a session value works.
            conn.execute(
                "INSERT INTO alerts (symbol, timeframe, session, received_at) "
                "VALUES ('TEST_MIG', '5', 'RTH', '2026-08-12T00:00:00+00:00')")
            conn.commit()
            got = conn.execute(
                "SELECT session FROM alerts WHERE symbol='TEST_MIG'").fetchone()["session"]
            self.assertEqual(got, "RTH")
            conn.execute("DELETE FROM alerts WHERE symbol='TEST_MIG'")
            conn.commit()
            conn.close()


if __name__ == "__main__":
    unittest.main()
