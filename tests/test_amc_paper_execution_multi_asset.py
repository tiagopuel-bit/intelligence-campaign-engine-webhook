"""Multi-asset expansion: portfolio policy, tracked-set validation, eligibility
gate, per-symbol kill switch, and multi-symbol readiness."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask

from paper_execution import db
from paper_execution.activation import join_symbol_if_ready
from paper_execution.api import create_blueprint
from paper_execution.cloud_state import cloud_readiness
from paper_execution.portfolio import (
    ANCHOR_SYMBOL,
    amc_floor_breached,
    asset_eligible,
    legs_notional,
    non_anchor_weight_cap,
    paper_portfolio_value,
    projected_amc_weight,
)
from paper_execution.store import (
    claim_due_proposal,
    create_experiment,
    create_proposal,
    frozen_goal_hash,
    frozen_policy_hash,
    kill_switch_active,
    set_kill_switch,
    tracked_symbols,
)

TOKEN = "test-state-token"


class PortfolioPolicyTests(unittest.TestCase):
    def test_projected_weight(self):
        self.assertAlmostEqual(projected_amc_weight(30.0, 100.0, 0.0), 0.30)
        # deploying 100 into non-AMC halves the AMC weight
        self.assertAlmostEqual(projected_amc_weight(30.0, 100.0, 100.0), 0.15)

    def test_floor_breached(self):
        self.assertFalse(amc_floor_breached(30.0, 100.0, 0.0))
        self.assertTrue(amc_floor_breached(30.0, 100.0, 100.0))

    def test_equal_weight_cap(self):
        self.assertAlmostEqual(non_anchor_weight_cap(6), 0.70 / 6)

    def test_asset_eligible(self):
        good = {"15m": (30, 1), "30m": (30, 1), "1H": (30, 1), "2H": (30, 1),
                "3H": (30, 1), "4H": (30, 1)}
        self.assertTrue(asset_eligible({"X": good}, "X"))
        bad = dict(good, **{"4H": (0, 0)})
        self.assertFalse(asset_eligible({"X": bad}, "X"))
        thin = dict(good, **{"1H": (10, 1)})
        self.assertFalse(asset_eligible({"X": thin}, "X"))

    def test_legs_notional(self):
        self.assertAlmostEqual(legs_notional([
            {"price_reference": 2.0, "quantity": 1, "instrument_type": "CALL"},
            {"price_reference": 50.0, "quantity": 2, "instrument_type": "SHARE"},
        ]), 2.0 * 1 * 100 + 50.0 * 2)


class TrackedSymbolsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        self.conn = db.connect(self._tmp.name)

    def tearDown(self):
        self.conn.close()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _experiment(self):
        return create_experiment(
            self.conn, version=1, symbol="AMC", start_at="2026-01-01T00:00:00Z",
            end_at="2027-01-31T16:00:00-08:00", starting_cash=100.0,
            starting_value_method="marked_market_value", target_value_jan2027=15000.0,
            target_return_pct=None, max_drawdown_pct=25.0, max_amc_exposure=0.70,
            max_exposure_per_option_expiry=0.25, deposit_policy="ALLOWED_TRACKED_SEPARATELY",
            allowed_actions="hold,add,open,partial_reduce,close,roll", benchmark_symbol="AMC",
            benchmark_success_criteria="x", min_observation_count=30, max_daily_paper_loss=0.05,
            max_orders_per_day=3, max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )

    def test_tracked_symbols_anchor_only(self):
        eid = self._experiment()
        self.assertEqual(tracked_symbols(self.conn, eid), ("AMC",))

    def test_tracked_symbols_with_join_rows(self):
        eid = self._experiment()
        self.conn.execute("INSERT INTO pe_experiment_symbols VALUES (?,?)", (eid, "GME"))
        self.conn.execute("INSERT INTO pe_experiment_symbols VALUES (?,?)", (eid, "SPY"))
        self.conn.commit()
        self.assertEqual(tracked_symbols(self.conn, eid), ("AMC", "GME", "SPY"))

    def test_symbol_kill_switch_blocks_only_that_symbol(self):
        eid = self._experiment()
        p1 = create_proposal(
            self.conn, experiment_id=eid, idempotency_key="s1", action="close", mode="AUTO_IF_VERY_HIGH_PAPER",
            symbol="GME", policy_sha256=frozen_policy_hash(), time_sensitive_reason="x", very_high=True,
            very_high_missing_roots=[], expires_at="2027-01-01T00:00:00Z", cancel_condition="x",
            evidence_roots=[{"root": "x", "present": True, "raw_fields": {}, "missing_evidence": [],
                             "contradictions": [], "veto": False}],
            position_ref="1", instrument_ref="11",
        )
        p2 = create_proposal(
            self.conn, experiment_id=eid, idempotency_key="s2", action="close", mode="AUTO_IF_VERY_HIGH_PAPER",
            symbol="SPY", policy_sha256=frozen_policy_hash(), time_sensitive_reason="x", very_high=True,
            very_high_missing_roots=[], expires_at="2027-01-01T00:00:00Z", cancel_condition="x",
            evidence_roots=[{"root": "x", "present": True, "raw_fields": {}, "missing_evidence": [],
                             "contradictions": [], "veto": False}],
            position_ref="1", instrument_ref="11",
        )
        self.conn.execute("INSERT INTO pe_experiment_symbols VALUES (?,?)", (eid, "GME"))
        self.conn.execute("INSERT INTO pe_experiment_symbols VALUES (?,?)", (eid, "SPY"))
        self.conn.commit()
        set_kill_switch(self.conn, eid, "SYMBOL", "GME", enabled=False)
        self.assertTrue(kill_switch_active(self.conn, eid, symbol="GME"))
        self.assertFalse(kill_switch_active(self.conn, eid, symbol="SPY"))
        # update proposals' expires_at to be due, then claim
        self.conn.execute("UPDATE pe_order_proposals SET expires_at='2020-01-01T00:00:00Z'")
        self.conn.commit()
        blocked = claim_due_proposal(self.conn, p1, "2027-01-02T00:00:00Z")
        allowed = claim_due_proposal(self.conn, p2, "2027-01-02T00:00:00Z")
        self.assertEqual(blocked["reason"], "KILL_SWITCH_ACTIVE")
        self.assertTrue(allowed["claimed"])


class PortfolioValuationTests(unittest.TestCase):
    def test_empty_portfolio(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE pe_paper_cash (experiment_id INTEGER PRIMARY KEY, cash REAL, updated_at TEXT);
            CREATE TABLE pe_paper_positions (experiment_id INTEGER, symbol TEXT, instrument_type TEXT, ticker TEXT, quantity REAL, updated_at TEXT);
            CREATE TABLE pe_paper_fills (id INTEGER PRIMARY KEY, order_id INTEGER, fill_price REAL, fill_quantity REAL, fill_time TEXT, model_note TEXT);
            CREATE TABLE pe_paper_orders (id INTEGER PRIMARY KEY, proposal_id INTEGER, leg_index INTEGER, ticker TEXT, side TEXT, quantity REAL, price_reference TEXT, price_source TEXT, bar_time TEXT, status TEXT, created_at TEXT);
            CREATE TABLE pe_order_proposals (id INTEGER PRIMARY KEY, experiment_id INTEGER);
            CREATE TABLE pe_starting_holdings (id INTEGER PRIMARY KEY, experiment_id INTEGER, instrument_type TEXT, ticker TEXT, strike REAL, expiration TEXT, quantity REAL, entry_price REAL, market_value REAL, frozen_at TEXT);
        """)
        conn.execute("INSERT INTO pe_paper_cash VALUES (1, 100.0, 'x')")
        v = paper_portfolio_value(conn, 1)
        self.assertEqual(v["total_value"], 100.0)
        self.assertEqual(v["amc_value"], 0.0)
        conn.close()


class JoinSymbolTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.eid = create_experiment(
            conn, version=1, symbol="AMC", start_at="2026-01-01T00:00:00Z",
            end_at="2027-01-31T16:00:00-08:00", starting_cash=100.0,
            starting_value_method="marked_market_value", target_value_jan2027=15000.0,
            target_return_pct=None, max_drawdown_pct=25.0, max_amc_exposure=0.70,
            max_exposure_per_option_expiry=0.25, deposit_policy="ALLOWED_TRACKED_SEPARATELY",
            allowed_actions="hold,add,open,partial_reduce,close,roll", benchmark_symbol="AMC",
            benchmark_success_criteria="x", min_observation_count=30, max_daily_paper_loss=0.05,
            max_orders_per_day=3, max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )
        conn.close()
        self._wh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._wh.close()
        wconn = sqlite3.connect(self._wh.name)
        wconn.execute("CREATE TABLE underlying_heartbeats (symbol TEXT, bar_time INTEGER, close REAL, source TEXT)")
        wconn.commit()
        wconn.close()

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)
        Path(self._wh.name).unlink(missing_ok=True)

    def _heartbeat(self, symbol, age_ms=0):
        now = int(datetime.now(timezone.utc).timestamp() * 1000) - age_ms
        conn = sqlite3.connect(self._wh.name)
        conn.execute(
            "INSERT INTO underlying_heartbeats (symbol, bar_time, close, source) VALUES (?,?,?,?)",
            (symbol, now, 2.0, "live_webhook"),
        )
        conn.commit()
        conn.close()

    def test_eligible_symbol_with_fresh_heartbeat_joins(self):
        self._heartbeat("GME")
        out = join_symbol_if_ready(self._tmp.name, self._wh.name, self.eid, "GME")
        self.assertEqual(out["status"], "JOINED")
        conn = db.connect(self._tmp.name)
        self.assertIn("GME", tracked_symbols(conn, self.eid))
        conn.close()

    def test_ineligible_symbol_rejected(self):
        self._heartbeat("MARA")
        out = join_symbol_if_ready(self._tmp.name, self._wh.name, self.eid, "MARA")
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["blocker"], "ASSET_NOT_ELIGIBLE")

    def test_stale_heartbeat_rejected(self):
        self._heartbeat("GME", age_ms=20 * 60 * 1000)
        out = join_symbol_if_ready(self._tmp.name, self._wh.name, self.eid, "GME")
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["blocker"], "BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT")

    def test_already_tracked_anchor_is_noop_with_clear_status(self):
        self._heartbeat("AMC")
        out = join_symbol_if_ready(self._tmp.name, self._wh.name, self.eid, "AMC")
        self.assertEqual(out["status"], "ALREADY_TRACKED")

    def test_experiment_not_active_rejected(self):
        self._heartbeat("GME")
        out = join_symbol_if_ready(self._tmp.name, self._wh.name, 9999, "GME")
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(out["blocker"], "EXPERIMENT_NOT_FOUND")


class JoinSymbolRouteTests(unittest.TestCase):
    """POST /paper/experiments/<id>/symbols wires join_symbol_if_ready."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.eid = create_experiment(
            conn, version=1, symbol="AMC", start_at="2026-01-01T00:00:00Z",
            end_at="2027-01-31T16:00:00-08:00", starting_cash=100.0,
            starting_value_method="marked_market_value", target_value_jan2027=15000.0,
            target_return_pct=None, max_drawdown_pct=25.0, max_amc_exposure=0.70,
            max_exposure_per_option_expiry=0.25, deposit_policy="ALLOWED_TRACKED_SEPARATELY",
            allowed_actions="hold,add,open,partial_reduce,close,roll", benchmark_symbol="AMC",
            benchmark_success_criteria="x", min_observation_count=30, max_daily_paper_loss=0.05,
            max_orders_per_day=3, max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )
        conn.close()
        self._wh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._wh.close()
        wconn = sqlite3.connect(self._wh.name)
        wconn.execute("CREATE TABLE underlying_heartbeats (symbol TEXT, bar_time INTEGER, close REAL, source TEXT)")
        wconn.commit()
        wconn.close()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_blueprint(
            self._tmp.name, TOKEN, lambda db_path, symbol: None, webhook_db_path=self._wh.name))
        self.client = self.app.test_client()
        self.h = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)
        Path(self._wh.name).unlink(missing_ok=True)

    def _heartbeat(self, symbol, age_ms=0):
        now = int(datetime.now(timezone.utc).timestamp() * 1000) - age_ms
        conn = sqlite3.connect(self._wh.name)
        conn.execute(
            "INSERT INTO underlying_heartbeats (symbol, bar_time, close, source) VALUES (?,?,?,?)",
            (symbol, now, 2.0, "live_webhook"),
        )
        conn.commit()
        conn.close()

    def test_unauthorized_returns_401(self):
        response = self.client.post(f"/paper/experiments/{self.eid}/symbols", json={"symbol": "GME"})
        self.assertEqual(response.status_code, 401)

    def test_unknown_field_rejected(self):
        response = self.client.post(f"/paper/experiments/{self.eid}/symbols",
                                    json={"symbol": "GME", "extra": 1}, headers=self.h)
        self.assertEqual(response.status_code, 400)

    def test_eligible_symbol_with_fresh_heartbeat_joins(self):
        self._heartbeat("GME")
        response = self.client.post(f"/paper/experiments/{self.eid}/symbols",
                                    json={"symbol": "GME"}, headers=self.h)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["status"], "JOINED")
        conn = db.connect(self._tmp.name)
        self.assertIn("GME", tracked_symbols(conn, self.eid))
        conn.close()

    def test_already_tracked_symbol_returns_200(self):
        self._heartbeat("AMC")
        response = self.client.post(f"/paper/experiments/{self.eid}/symbols",
                                    json={"symbol": "AMC"}, headers=self.h)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ALREADY_TRACKED")

    def test_ineligible_symbol_returns_409(self):
        self._heartbeat("MARA")
        response = self.client.post(f"/paper/experiments/{self.eid}/symbols",
                                    json={"symbol": "MARA"}, headers=self.h)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["blocker"], "ASSET_NOT_ELIGIBLE")

    def test_stale_heartbeat_returns_409(self):
        self._heartbeat("GME", age_ms=20 * 60 * 1000)
        response = self.client.post(f"/paper/experiments/{self.eid}/symbols",
                                    json={"symbol": "GME"}, headers=self.h)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["blocker"], "BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT")

    def test_unknown_experiment_returns_404(self):
        self._heartbeat("GME")
        response = self.client.post("/paper/experiments/9999/symbols",
                                    json={"symbol": "GME"}, headers=self.h)
        self.assertEqual(response.status_code, 404)


class MultiSymbolReadinessTests(unittest.TestCase):
    def test_cloud_readiness_loops_symbols(self):
        wh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        wh.close()
        conn = sqlite3.connect(wh.name)
        conn.execute("CREATE TABLE underlying_heartbeats (symbol TEXT, bar_time INTEGER, close REAL, source TEXT)")
        conn.execute("CREATE TABLE option_heartbeats (instrument_ref TEXT, position_ref TEXT, ticker TEXT, bar_time INTEGER, close REAL, option_return REAL, matched_bars INTEGER, activity_ratio REAL, session TEXT, source TEXT)")
        conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, status TEXT)")
        conn.execute("CREATE TABLE position_instruments (id INTEGER PRIMARY KEY, position_id INTEGER, instrument_type TEXT, quantity REAL, strike REAL, expiration TEXT, status TEXT)")
        import datetime
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        conn.execute("INSERT INTO underlying_heartbeats VALUES ('AMC', ?, 2.0, 'live_webhook')", (now,))
        conn.execute("INSERT INTO positions VALUES (1, 'AMC', 'LONG', 'OPEN')")
        conn.execute("INSERT INTO position_instruments VALUES (11, 1, 'CALL', 1, 1.5, '2026-09-18', 'OPEN')")
        conn.commit()
        conn.close()
        # AMC fresh, GME missing -> with two symbols, GME heartbeat is a blocker.
        r = cloud_readiness(wh.name, ("AMC", "GME"))
        self.assertTrue(any(b == "BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT:GME" for b in r["blockers"]))
        # single-symbol keeps the un-suffixed legacy code.
        r2 = cloud_readiness(wh.name, ("AMC",))
        self.assertFalse(any(b.startswith("BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT") for b in r2["blockers"]))
        Path(wh.name).unlink(missing_ok=True)

    def test_cloud_readiness_option_uses_same_day_freshness_not_2min(self):
        # cloud_readiness had its own separate 2-min option cutoff, missed by
        # the activation.py same-day-freshness fix (deep-ITM/long-dated legs
        # print every 20-130 min on TradingView's delayed feed, so a flat
        # 2-min window can never pass for a real open option leg).
        import datetime
        wh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        wh.close()
        conn = sqlite3.connect(wh.name)
        conn.execute("CREATE TABLE underlying_heartbeats (symbol TEXT, bar_time INTEGER, close REAL, source TEXT)")
        conn.execute("CREATE TABLE option_heartbeats (instrument_ref TEXT, position_ref TEXT, ticker TEXT, bar_time INTEGER, close REAL, option_return REAL, matched_bars INTEGER, activity_ratio REAL, session TEXT, source TEXT)")
        conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, status TEXT)")
        conn.execute("CREATE TABLE position_instruments (id INTEGER PRIMARY KEY, position_id INTEGER, instrument_type TEXT, quantity REAL, strike REAL, expiration TEXT, status TEXT)")
        now = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
        et = __import__("zoneinfo").ZoneInfo("America/New_York")
        today_et = datetime.datetime.now(et).date()
        stale_but_today = int(datetime.datetime(today_et.year, today_et.month, today_et.day, 0, 0, 1,
                                                  tzinfo=et).timestamp() * 1000)
        conn.execute("INSERT INTO underlying_heartbeats VALUES ('AMC', ?, 2.0, 'live_webhook')", (now,))
        conn.execute("INSERT INTO positions VALUES (1, 'AMC', 'LONG', 'OPEN')")
        conn.execute("INSERT INTO position_instruments VALUES (11, 1, 'CALL', 1, 1.5, '2026-09-18', 'OPEN')")
        conn.execute("INSERT INTO option_heartbeats VALUES ('11','1','O:AMC',?,1.14,0.05,20,0.9,'RTH','live_contract_bar')",
                     (stale_but_today,))
        conn.commit()
        conn.close()
        r = cloud_readiness(wh.name, ("AMC",))
        self.assertFalse(any(b.startswith("BLOCKED_NO_FRESH_OPTION_HEARTBEAT") for b in r["blockers"]))
        self.assertTrue(r["authoritative_provider_ready"])
        Path(wh.name).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
