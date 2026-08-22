"""Tests for the manual cash-adjustment endpoint (2026-08-22): a deliberate,
audited exception to the evidence-driven /paper/proposals path, for cases the
automated pipeline structurally cannot handle -- e.g. a contract that has
already expired, so no live pricing evidence can ever exist for it again.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask

from paper_execution import db
from paper_execution.api import create_blueprint
from paper_execution.store import create_experiment, frozen_goal_hash

TOKEN = "test-state-token"


def _iso(minutes_from_now=0):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()


def make_experiment(conn, **overrides):
    kwargs = dict(version=1, symbol="AMC", start_at=_iso(-5), end_at="2027-01-31T16:00:00-08:00",
                  starting_cash=100.0, starting_value_method="marked_market_value",
                  target_value_jan2027=15000.0, target_return_pct=None, max_drawdown_pct=25.0,
                  max_amc_exposure=0.70, max_exposure_per_option_expiry=0.25,
                  deposit_policy="ALLOWED_TRACKED_SEPARATELY", allowed_actions="hold,add,open,partial_reduce,close,roll",
                  benchmark_symbol="AMC", benchmark_success_criteria="beat buy-and-hold",
                  min_observation_count=30, max_daily_paper_loss=0.05, max_orders_per_day=3,
                  max_consecutive_failed_proposals=3, milestones_json="[]",
                  amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash())
    kwargs.update(overrides)
    return create_experiment(conn, **kwargs)


class CashAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.experiment_id = make_experiment(conn)
        conn.close()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_blueprint(self._tmp.name, TOKEN, lambda db_path, symbol: None))
        self.client = self.app.test_client()
        self.h = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)

    def _cash(self):
        conn = db.connect(self._tmp.name)
        row = conn.execute(
            "SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (self.experiment_id,)
        ).fetchone()
        conn.close()
        return float(row["cash"])

    def test_unauthorized_returns_401(self):
        resp = self.client.post(f"/paper/experiments/{self.experiment_id}/cash-adjustment",
                                json={"amount": 206.0, "reason": "test"})
        self.assertEqual(resp.status_code, 401)

    def test_credits_cash_and_records_audit_row(self):
        self.assertEqual(self._cash(), 100.0)
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/cash-adjustment",
            json={"amount": 206.0, "reason": "AMC Aug21 $1.5C expiry, exit $1.03 x 2 x 100",
                  "position_ref": 8, "instrument_ref": 10},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["new_cash"], 306.0)
        self.assertEqual(self._cash(), 306.0)

        adjustments = self.client.get(
            f"/paper/experiments/{self.experiment_id}/cash-adjustments", headers=self.h
        ).get_json()
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0]["amount"], 206.0)
        self.assertEqual(adjustments[0]["position_ref"], 8)
        self.assertEqual(adjustments[0]["instrument_ref"], 10)

    def test_negative_amount_debits_cash(self):
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/cash-adjustment",
            json={"amount": -50.0, "reason": "correction"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(self._cash(), 50.0)

    def test_zero_amount_rejected(self):
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/cash-adjustment",
            json={"amount": 0, "reason": "no-op"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._cash(), 100.0)

    def test_missing_reason_rejected(self):
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/cash-adjustment",
            json={"amount": 10.0},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._cash(), 100.0)

    def test_non_numeric_amount_rejected(self):
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/cash-adjustment",
            json={"amount": "not-a-number", "reason": "bad input"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._cash(), 100.0)

    def test_unknown_experiment_returns_404(self):
        resp = self.client.post(
            "/paper/experiments/999999/cash-adjustment",
            json={"amount": 10.0, "reason": "x"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 404)

    def test_inactive_experiment_rejected(self):
        conn = db.connect(self._tmp.name)
        conn.execute("UPDATE pe_experiments SET status='COMPLETED' WHERE id=?", (self.experiment_id,))
        conn.commit()
        conn.close()
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/cash-adjustment",
            json={"amount": 10.0, "reason": "x"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(self._cash(), 100.0)

    def test_multiple_adjustments_accumulate_and_list_newest_first(self):
        self.client.post(f"/paper/experiments/{self.experiment_id}/cash-adjustment",
                         json={"amount": 10.0, "reason": "first"}, headers=self.h)
        self.client.post(f"/paper/experiments/{self.experiment_id}/cash-adjustment",
                         json={"amount": 20.0, "reason": "second"}, headers=self.h)
        self.assertEqual(self._cash(), 130.0)
        adjustments = self.client.get(
            f"/paper/experiments/{self.experiment_id}/cash-adjustments", headers=self.h
        ).get_json()
        self.assertEqual([a["reason"] for a in adjustments], ["second", "first"])


class PositionAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.experiment_id = make_experiment(conn)
        conn.close()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_blueprint(self._tmp.name, TOKEN, lambda db_path, symbol: None))
        self.client = self.app.test_client()
        self.h = {"Authorization": f"Bearer {TOKEN}"}
        self.ticker = "OPRA_DLY:AMC260821C1.5"

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)

    def _seed_position(self, quantity=2.0, instrument_type="CALL"):
        conn = db.connect(self._tmp.name)
        conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (self.experiment_id, "AMC", instrument_type, self.ticker, quantity, _iso()),
        )
        conn.commit()
        conn.close()

    def _quantity(self, instrument_type="CALL"):
        conn = db.connect(self._tmp.name)
        row = conn.execute(
            "SELECT quantity FROM pe_paper_positions WHERE experiment_id=? AND ticker=? AND instrument_type=?",
            (self.experiment_id, self.ticker, instrument_type),
        ).fetchone()
        conn.close()
        return float(row["quantity"])

    def test_unauthorized_returns_401(self):
        resp = self.client.post(f"/paper/experiments/{self.experiment_id}/position-adjustment",
                                json={"ticker": self.ticker, "instrument_type": "CALL",
                                      "quantity_delta": -2, "reason": "x"})
        self.assertEqual(resp.status_code, 401)

    def test_read_route_lists_seeded_positions(self):
        self._seed_position()
        rows = self.client.get(
            f"/paper/experiments/{self.experiment_id}/positions", headers=self.h
        ).get_json()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ticker"], self.ticker)
        self.assertEqual(rows[0]["quantity"], 2.0)

    def test_decrements_existing_position_and_records_audit_row(self):
        self._seed_position(quantity=2.0)
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/position-adjustment",
            json={"ticker": self.ticker, "instrument_type": "CALL", "quantity_delta": -2,
                  "reason": "AMC Aug21 $1.5C expired, position fully closed",
                  "position_ref": 8, "instrument_ref": 10},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.get_json()
        self.assertEqual(body["new_quantity"], 0.0)
        self.assertEqual(self._quantity(), 0.0)

    # -- the critical safety property: never creates a phantom position ---
    def test_unknown_ticker_never_creates_a_new_position(self):
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/position-adjustment",
            json={"ticker": "NEVER_HELD:XYZ", "instrument_type": "CALL",
                  "quantity_delta": -5, "reason": "should be rejected"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.get_json()["error"], "PAPER_POSITION_NOT_FOUND")
        conn = db.connect(self._tmp.name)
        n = conn.execute("SELECT COUNT(*) n FROM pe_paper_positions").fetchone()["n"]
        conn.close()
        self.assertEqual(n, 0)

    def test_zero_delta_rejected(self):
        self._seed_position()
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/position-adjustment",
            json={"ticker": self.ticker, "instrument_type": "CALL", "quantity_delta": 0, "reason": "x"},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._quantity(), 2.0)

    def test_missing_reason_rejected(self):
        self._seed_position()
        resp = self.client.post(
            f"/paper/experiments/{self.experiment_id}/position-adjustment",
            json={"ticker": self.ticker, "instrument_type": "CALL", "quantity_delta": -2},
            headers=self.h,
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self._quantity(), 2.0)


if __name__ == "__main__":
    unittest.main()
