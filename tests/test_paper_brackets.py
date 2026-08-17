"""Tests for the paper-execution protective bracket (stop-loss + take-profit).

Pure validation/decision tests plus a store + runner round-trip proving a
crossed level closes the paper position and adjusts cash without a proposal.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from paper_execution import db
from paper_execution.brackets import (
    bracket_decision,
    validate_bracket_payload,
    validate_side,
)
from paper_execution.store import (
    apply_bracket_trigger,
    cancel_bracket,
    create_experiment,
    frozen_goal_hash,
    list_active_brackets,
    set_kill_switch,
    upsert_bracket,
)
from paper_execution.runner import run_once


def _iso(offset_seconds=0):
    return (datetime.now(timezone.utc)).isoformat()


class BracketValidationTests(unittest.TestCase):
    def test_payload_requires_stop_or_target(self):
        _, err = validate_bracket_payload({"experiment_id": 1, "ticker": "AMC"})
        self.assertEqual(err, "at least one of stop_price or target_price is required")

    def test_payload_requires_positive_prices(self):
        _, err = validate_bracket_payload({"experiment_id": 1, "ticker": "AMC", "stop_price": -5})
        self.assertEqual(err, "stop_price must be a positive number")

    def test_payload_accepts_stop_only(self):
        clean, err = validate_bracket_payload(
            {"experiment_id": 1, "ticker": "AMC", "stop_price": 5}
        )
        self.assertIsNone(err)
        self.assertEqual(clean["stop_price"], 5.0)
        self.assertIsNone(clean["target_price"])

    def test_payload_rejects_unknown_fields(self):
        _, err = validate_bracket_payload(
            {"experiment_id": 1, "ticker": "AMC", "stop_price": 5, "greek": 0.1}
        )
        self.assertIn("unsupported fields", err)

    def test_side_ordering(self):
        self.assertTrue(validate_side("LONG", 5.0, 8.0))
        self.assertFalse(validate_side("LONG", 8.0, 5.0))
        self.assertTrue(validate_side("SHORT", 8.0, 5.0))
        self.assertFalse(validate_side("SHORT", 5.0, 8.0))
        # single-sided brackets have no ordering to violate
        self.assertTrue(validate_side("LONG", 5.0, None))

    def test_decision(self):
        long_bracket = {"direction": "LONG", "stop_price": 5.0, "target_price": 8.0}
        self.assertEqual(bracket_decision(long_bracket, 4.9), "STOP")
        self.assertEqual(bracket_decision(long_bracket, 8.1), "TARGET")
        self.assertIsNone(bracket_decision(long_bracket, 6.0))
        short_bracket = {"direction": "SHORT", "stop_price": 8.0, "target_price": 5.0}
        self.assertEqual(bracket_decision(short_bracket, 8.1), "STOP")
        self.assertEqual(bracket_decision(short_bracket, 4.9), "TARGET")
        self.assertIsNone(bracket_decision(short_bracket, 6.0))
        self.assertIsNone(bracket_decision(long_bracket, None))


class BracketStoreTests(unittest.TestCase):
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
            self.conn, version=1, symbol="AMC", start_at=_iso(), end_at="2027-01-31T16:00:00-08:00",
            starting_cash=100.0, starting_value_method="marked_market_value",
            target_value_jan2027=15000.0, target_return_pct=None, max_drawdown_pct=25.0,
            max_amc_exposure=0.70, max_exposure_per_option_expiry=0.25,
            deposit_policy="ALLOWED_TRACKED_SEPARATELY", allowed_actions="hold,add,open,partial_reduce,close,roll",
            benchmark_symbol="AMC", benchmark_success_criteria="beat buy-and-hold",
            min_observation_count=30, max_daily_paper_loss=0.05, max_orders_per_day=3,
            max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )

    def _paper_position(self, eid, qty=100.0, ticker="AMC", itype="SHARE"):
        self.conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (eid, "AMC", itype, ticker, qty, _iso()),
        )
        self.conn.commit()

    def test_upsert_replaces_active_and_preserves_history(self):
        eid = self._experiment()
        self._paper_position(eid)
        first = upsert_bracket(self.conn, experiment_id=eid, symbol="AMC", ticker="AMC",
                               instrument_type="SHARE", direction="LONG", stop_price=5.0, target_price=None)
        second = upsert_bracket(self.conn, experiment_id=eid, symbol="AMC", ticker="AMC",
                                instrument_type="SHARE", direction="LONG", stop_price=6.0, target_price=None)
        self.assertNotEqual(first, second)
        active = list_active_brackets(self.conn, experiment_id=eid)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], second)
        self.assertEqual(active[0]["stop_price"], 6.0)
        # the first bracket was superseded, not deleted
        cancelled = self.conn.execute(
            "SELECT COUNT(*) n FROM pe_position_brackets WHERE experiment_id=? AND status='CANCELLED'",
            (eid,),
        ).fetchone()["n"]
        self.assertEqual(cancelled, 1)

    def test_trigger_closes_long_position_and_adds_cash(self):
        eid = self._experiment()
        self._paper_position(eid, qty=100.0)
        bid = upsert_bracket(self.conn, experiment_id=eid, symbol="AMC", ticker="AMC",
                             instrument_type="SHARE", direction="LONG", stop_price=8.0, target_price=None)
        bracket = list_active_brackets(self.conn, experiment_id=eid)[0]
        apply_bracket_trigger(self.conn, bracket, side="STOP", trigger_price=7.5,
                              fill_price=7.5, bar_time=123, price_source="test",
                              note="test fill")
        cash = self.conn.execute("SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (eid,)).fetchone()["cash"]
        self.assertAlmostEqual(cash, 100.0 + 100 * 7.5)
        qty = self.conn.execute(
            "SELECT quantity FROM pe_paper_positions WHERE experiment_id=? AND ticker=?", (eid, "AMC")
        ).fetchone()["quantity"]
        self.assertEqual(qty, 0)
        row = self.conn.execute("SELECT status, triggered_side FROM pe_position_brackets WHERE id=?", (bid,)).fetchone()
        self.assertEqual(row["status"], "TRIGGERED")
        self.assertEqual(row["triggered_side"], "STOP")

    def test_trigger_closes_short_position_and_spends_cash(self):
        eid = self._experiment()
        self._paper_position(eid, qty=-100.0)
        upsert_bracket(self.conn, experiment_id=eid, symbol="AMC", ticker="AMC",
                       instrument_type="SHARE", direction="SHORT", stop_price=10.0, target_price=None)
        bracket = list_active_brackets(self.conn, experiment_id=eid)[0]
        apply_bracket_trigger(self.conn, bracket, side="STOP", trigger_price=11.0,
                              fill_price=11.0, bar_time=123, price_source="test",
                              note="test fill")
        cash = self.conn.execute("SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (eid,)).fetchone()["cash"]
        self.assertAlmostEqual(cash, 100.0 - 100 * 11.0)

    def test_cancel_bracket(self):
        eid = self._experiment()
        self._paper_position(eid)
        bid = upsert_bracket(self.conn, experiment_id=eid, symbol="AMC", ticker="AMC",
                             instrument_type="SHARE", direction="LONG", stop_price=5.0, target_price=None)
        self.assertTrue(cancel_bracket(self.conn, bid))
        self.assertEqual(list_active_brackets(self.conn, experiment_id=eid), [])


class _Provider:
    def __init__(self, close):
        self.close = close

    def latest_close(self, symbol, ticker):
        return {"close": self.close, "bar_time": 123, "source": "test"}

    def __call__(self, db_path, symbol, position_ref=None, instrument_ref=None):
        return None


class BracketRunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        self.conn = db.connect(self._tmp.name)

    def tearDown(self):
        self.conn.close()
        Path(self._tmp.name).unlink(missing_ok=True)

    def _setup(self, stop=8.0, qty=100.0):
        eid = create_experiment(
            self.conn, version=1, symbol="AMC", start_at=_iso(), end_at="2027-01-31T16:00:00-08:00",
            starting_cash=100.0, starting_value_method="marked_market_value",
            target_value_jan2027=15000.0, target_return_pct=None, max_drawdown_pct=25.0,
            max_amc_exposure=0.70, max_exposure_per_option_expiry=0.25,
            deposit_policy="ALLOWED_TRACKED_SEPARATELY", allowed_actions="hold,add,open,partial_reduce,close,roll",
            benchmark_symbol="AMC", benchmark_success_criteria="beat buy-and-hold",
            min_observation_count=30, max_daily_paper_loss=0.05, max_orders_per_day=3,
            max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )
        self.conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?)", (eid, "AMC", "SHARE", "AMC", qty, _iso())
        )
        self.conn.commit()
        upsert_bracket(self.conn, experiment_id=eid, symbol="AMC", ticker="AMC",
                       instrument_type="SHARE", direction="LONG", stop_price=stop, target_price=None)
        return eid

    def test_runner_fires_stop_on_cross(self):
        eid = self._setup(stop=8.0)
        results = run_once(self._tmp.name, _Provider(close=7.5))
        self.assertTrue(any(r.get("status") == "TRIGGERED" and r.get("side") == "STOP" for r in results))

    def test_runner_skips_without_cross(self):
        self._setup(stop=8.0)
        results = run_once(self._tmp.name, _Provider(close=9.0))
        self.assertFalse(any(r.get("status") == "TRIGGERED" for r in results))

    def test_runner_skips_on_kill_switch(self):
        eid = self._setup(stop=8.0)
        set_kill_switch(self.conn, eid, "GLOBAL", None, False)
        results = run_once(self._tmp.name, _Provider(close=7.5))
        self.assertTrue(any(r.get("status") == "SKIPPED" and r.get("reason") == "KILL_SWITCH_ACTIVE" for r in results))


if __name__ == "__main__":
    unittest.main()
