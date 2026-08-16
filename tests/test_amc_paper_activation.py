import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from paper_execution import db
from paper_execution.activation import activate_if_ready


class PaperActivationTests(unittest.TestCase):
    def setUp(self):
        self.paper_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.paper_file.close()
        self.webhook_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.webhook_file.close()
        db.init_db(self.paper_file.name)
        conn = sqlite3.connect(self.webhook_file.name)
        conn.executescript("""
            CREATE TABLE underlying_heartbeats(symbol TEXT,timeframe TEXT,bar_time INTEGER,close REAL,source TEXT,received_at TEXT);
            CREATE TABLE option_heartbeats(instrument_ref TEXT,position_ref TEXT,symbol TEXT,ticker TEXT,timeframe TEXT,bar_time INTEGER,close REAL,option_return REAL,matched_bars INTEGER,activity_ratio REAL,volume REAL,source TEXT,received_at TEXT);
            CREATE TABLE positions(id INTEGER PRIMARY KEY,symbol TEXT,direction TEXT,status TEXT);
            CREATE TABLE position_instruments(id INTEGER PRIMARY KEY,position_id INTEGER,instrument_type TEXT,strike REAL,expiration TEXT,quantity REAL,entry_price REAL,status TEXT);
        """)
        now = int(datetime.now(timezone.utc).timestamp() * 1000)
        conn.execute("INSERT INTO underlying_heartbeats VALUES ('AMC','1',?,2.50,'live_webhook','now')", (now,))
        conn.execute("INSERT INTO positions VALUES (7,'AMC','LONG','OPEN')")
        conn.execute("INSERT INTO position_instruments VALUES (10,7,'SHARE',NULL,NULL,100,1.50,'OPEN')")
        conn.execute("INSERT INTO position_instruments VALUES (11,7,'CALL',2.5,'2026-09-18',2,0.50,'OPEN')")
        conn.commit()
        conn.close()
        self.now = now

    def tearDown(self):
        Path(self.paper_file.name).unlink(missing_ok=True)
        Path(self.webhook_file.name).unlink(missing_ok=True)

    def test_blocks_until_every_option_has_fresh_exact_quote(self):
        result = activate_if_ready(self.paper_file.name, self.webhook_file.name)
        self.assertEqual(result["blocker"], "BLOCKED_NO_FRESH_OPTION_HEARTBEAT")
        conn = db.connect(self.paper_file.name)
        self.assertEqual(conn.execute("SELECT COUNT(*) n FROM pe_experiments").fetchone()["n"], 0)
        conn.close()

    def test_atomic_activation_snapshots_cash_and_holdings(self):
        conn = sqlite3.connect(self.webhook_file.name)
        conn.execute(
            "INSERT INTO option_heartbeats VALUES ('11','7','AMC','O:AMC','1',?,1.25,0.1,20,0.9,10,'live_contract_bar','now')",
            (self.now,),
        )
        conn.commit()
        conn.close()
        result = activate_if_ready(self.paper_file.name, self.webhook_file.name)
        self.assertEqual(result["status"], "ACTIVATED")
        self.assertEqual(result["holding_count"], 2)
        self.assertEqual(result["starting_portfolio_value"], 600.0)
        paper = db.connect(self.paper_file.name)
        exp = paper.execute("SELECT * FROM pe_experiments").fetchone()
        cash = paper.execute("SELECT cash FROM pe_paper_cash").fetchone()["cash"]
        holdings = paper.execute("SELECT COUNT(*) n FROM pe_starting_holdings").fetchone()["n"]
        positions = paper.execute("SELECT COUNT(*) n FROM pe_paper_positions").fetchone()["n"]
        switch = paper.execute("SELECT auto_enabled FROM pe_auto_switches WHERE scope='GLOBAL'").fetchone()["auto_enabled"]
        paper.close()
        self.assertEqual(exp["status"], "ACTIVE")
        self.assertEqual(exp["auto_enabled_global"], 1)
        self.assertEqual(cash, 100.0)
        self.assertEqual(holdings, 2)
        self.assertEqual(positions, 2)
        self.assertEqual(switch, 1)

    def test_single_symbol_default_is_unchanged(self):
        conn = sqlite3.connect(self.webhook_file.name)
        conn.execute(
            "INSERT INTO option_heartbeats VALUES ('11','7','AMC','O:AMC','1',?,1.25,0.1,20,0.9,10,'live_contract_bar','now')",
            (self.now,),
        )
        conn.commit()
        conn.close()
        result = activate_if_ready(self.paper_file.name, self.webhook_file.name)
        self.assertEqual(result["status"], "ACTIVATED")
        paper = db.connect(self.paper_file.name)
        exp = paper.execute("SELECT symbol FROM pe_experiments").fetchone()
        symbols = paper.execute("SELECT COUNT(*) n FROM pe_experiment_symbols").fetchone()["n"]
        paper.close()
        self.assertEqual(exp["symbol"], "AMC")
        self.assertEqual(symbols, 0)  # no additional tracked symbols

    def test_multi_symbol_populates_join_table(self):
        conn = sqlite3.connect(self.webhook_file.name)
        conn.execute(
            "INSERT INTO option_heartbeats VALUES ('11','7','AMC','O:AMC','1',?,1.25,0.1,20,0.9,10,'live_contract_bar','now')",
            (self.now,),
        )
        # second symbol: GME share-only
        conn.execute("INSERT INTO underlying_heartbeats VALUES ('GME','1',?,30.0,'live_webhook','now')", (self.now,))
        conn.execute("INSERT INTO positions VALUES (8,'GME','LONG','OPEN')")
        conn.execute("INSERT INTO position_instruments VALUES (12,8,'SHARE',NULL,NULL,10,28.0,'OPEN')")
        conn.commit()
        conn.close()
        result = activate_if_ready(self.paper_file.name, self.webhook_file.name, ("AMC", "GME"))
        self.assertEqual(result["status"], "ACTIVATED")
        self.assertEqual(result["holding_count"], 3)  # AMC share + AMC call + GME share
        paper = db.connect(self.paper_file.name)
        exp = paper.execute("SELECT symbol FROM pe_experiments").fetchone()
        tracked = paper.execute("SELECT symbol FROM pe_experiment_symbols ORDER BY symbol").fetchall()
        gme_pos = paper.execute("SELECT COUNT(*) n FROM pe_paper_positions WHERE symbol='GME'").fetchone()["n"]
        paper.close()
        self.assertEqual(exp["symbol"], "AMC")  # anchor unchanged
        self.assertEqual([r["symbol"] for r in tracked], ["GME"])
        self.assertEqual(gme_pos, 1)

    def test_legacy_string_call_equivalent_to_tuple(self):
        conn = sqlite3.connect(self.webhook_file.name)
        conn.execute(
            "INSERT INTO option_heartbeats VALUES ('11','7','AMC','O:AMC','1',?,1.25,0.1,20,0.9,10,'live_contract_bar','now')",
            (self.now,),
        )
        conn.commit()
        conn.close()
        result = activate_if_ready(self.paper_file.name, self.webhook_file.name, "AMC")
        self.assertEqual(result["status"], "ACTIVATED")
        paper = db.connect(self.paper_file.name)
        self.assertEqual(paper.execute("SELECT COUNT(*) n FROM pe_experiment_symbols").fetchone()["n"], 0)
        paper.close()


if __name__ == "__main__":
    unittest.main()
