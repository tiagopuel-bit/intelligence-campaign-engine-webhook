"""Test the session-capture migration SQL (001) against a synthetic old-schema table.

The manual migrations/*.sql files are documentation/fallback now -- webhook_receiver
auto-applies missing columns at startup (see _ensure_alert_columns). This test keeps
verifying that migration 001's SQL still does what it says: adds `session`, keeps row
count, and existing rows read NULL.
"""
from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_add_session_column.sql"


class TestSessionMigration(unittest.TestCase):
    def test_migration_on_old_schema(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                close REAL,
                received_at TEXT NOT NULL
            )
        """)
        conn.execute("INSERT INTO alerts (symbol, timeframe, close, received_at) "
                     "VALUES ('TEST_MIG', '5', 2.5, '2026-08-12T00:00:00+00:00')")
        conn.commit()

        before = conn.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
        cols_before = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
        self.assertNotIn("session", cols_before)

        conn.execute(MIGRATION.read_text())
        conn.commit()

        after = conn.execute("SELECT COUNT(*) n FROM alerts").fetchone()["n"]
        cols_after = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
        self.assertIn("session", cols_after)
        self.assertEqual(before, after, "row count changed (data loss!)")

        null_session = conn.execute(
            "SELECT COUNT(*) n FROM alerts WHERE session IS NULL").fetchone()["n"]
        self.assertEqual(null_session, after)

        conn.execute(
            "INSERT INTO alerts (symbol, timeframe, session, received_at) "
            "VALUES ('TEST_MIG2', '5', 'RTH', '2026-08-12T00:00:00+00:00')")
        conn.commit()
        got = conn.execute(
            "SELECT session FROM alerts WHERE symbol='TEST_MIG2'").fetchone()["session"]
        self.assertEqual(got, "RTH")
        conn.close()


if __name__ == "__main__":
    unittest.main()
