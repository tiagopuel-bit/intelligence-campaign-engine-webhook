"""Tests for _reconcile_paper_close (2026-08-22): closing a position via the
regular dashboard Manage dialog was never wired to the paper-execution
challenge's cash/holdings at all. This covers the fix -- and, more
importantly, the safety property that it must NEVER submit a close for a
position the paper challenge never actually held (which would otherwise let
apply_paper_fill_ledger's INSERT...ON CONFLICT create a phantom position
with fabricated cash from nothing).
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webhook_receiver
from webhook_receiver import app, init_db
from paper_execution import db as paper_db
from paper_execution.store import create_experiment, frozen_goal_hash

TEST_STATE_TOKEN = "test-state-token"


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _iso():
    return datetime.now(timezone.utc).isoformat()


class PaperCloseReconciliationTests(unittest.TestCase):
    # setUp/tearDown (not setUpClass/tearDownClass): each test needs a fully
    # fresh pair of DBs. A shared class-level DB leaked experiments between
    # tests here initially -- unittest doesn't run methods in source order,
    # so a later-alphabetical test's seeded experiment was already present
    # when an earlier-alphabetical test expected a clean slate, and
    # pe_paper_cash's UNIQUE(experiment_id) then collided across tests too.
    def setUp(self):
        self._wh_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._wh_file.close()
        self._paper_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._paper_file.close()

        self._orig_db_path = webhook_receiver.DB_PATH
        self._orig_paper_db_path = webhook_receiver.PAPER_DB_PATH
        self._orig_state_token = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.DB_PATH = Path(self._wh_file.name)
        webhook_receiver.PAPER_DB_PATH = Path(self._paper_file.name)
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN

        init_db()
        paper_db.init_db(self._paper_file.name)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        webhook_receiver.DB_PATH = self._orig_db_path
        webhook_receiver.PAPER_DB_PATH = self._orig_paper_db_path
        webhook_receiver.STATE_API_TOKEN = self._orig_state_token
        for f in (self._wh_file.name, self._paper_file.name):
            try:
                os.unlink(f)
            except OSError:
                pass
            for sidecar in ("-journal", "-wal", "-shm"):
                try:
                    os.unlink(f + sidecar)
                except OSError:
                    pass

    def _wh_conn(self):
        conn = sqlite3.connect(str(webhook_receiver.DB_PATH))
        conn.row_factory = sqlite3.Row
        return conn

    def _paper_conn(self):
        conn = paper_db.connect(str(webhook_receiver.PAPER_DB_PATH))
        return conn

    def _seed_position(self, symbol, strike=1.5, expiration="2026-09-18", quantity=2.0,
                       instrument_type="CALL"):
        """Regular-tracker position + OPEN instrument, no paper linkage."""
        conn = self._wh_conn()
        now = _iso()
        cur = conn.execute(
            "INSERT INTO positions (symbol, direction, status, opened_at, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (symbol, "LONG", "OPEN", now, now, now),
        )
        pid = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO position_instruments (position_id, instrument_type, strike, expiration, "
            "quantity, entry_price, entry_time, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pid, instrument_type, strike, expiration, quantity, 0.22, now, "OPEN", now, now),
        )
        iid = cur.lastrowid
        conn.commit()
        conn.close()
        return pid, iid

    def _seed_underlying_heartbeat(self, symbol):
        conn = self._wh_conn()
        conn.execute(
            "INSERT INTO underlying_heartbeats (symbol, timeframe, bar_time, close, session, source, received_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (symbol, "1", _now_ms(), 2.5, "RTH", "live_webhook", _iso()),
        )
        conn.commit()
        conn.close()

    def _seed_option_heartbeat(self, instrument_ref, position_ref, symbol, ticker):
        conn = self._wh_conn()
        conn.execute(
            "INSERT INTO option_heartbeats (instrument_ref, position_ref, symbol, ticker, timeframe, "
            "bar_time, close, option_return, matched_bars, activity_ratio, volume, session, source, received_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (str(instrument_ref), str(position_ref), symbol, ticker, "1", _now_ms(), 1.03,
             0.1, 20, 0.9, 5, "RTH", "live_contract_bar", _iso()),
        )
        conn.commit()
        conn.close()

    def _seed_experiment(self, symbol="CLQD"):
        conn = self._paper_conn()
        eid = create_experiment(
            conn, version=1, symbol=symbol, start_at=_iso(), end_at="2027-01-31T16:00:00-08:00",
            starting_cash=100.0, starting_value_method="marked_market_value",
            target_value_jan2027=15000.0, target_return_pct=None, max_drawdown_pct=25.0,
            max_amc_exposure=0.70, max_exposure_per_option_expiry=0.25,
            deposit_policy="ALLOWED_TRACKED_SEPARATELY",
            allowed_actions="hold,add,open,partial_reduce,close,roll",
            benchmark_symbol=symbol, benchmark_success_criteria="beat buy-and-hold",
            min_observation_count=30, max_daily_paper_loss=0.05, max_orders_per_day=3,
            max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )
        # create_experiment already INSERT OR IGNOREs into pe_paper_cash --
        # no separate insert needed here.
        conn.close()
        return eid

    def _seed_paper_holding(self, experiment_id, symbol, ticker, quantity=2.0, instrument_type="CALL"):
        conn = self._paper_conn()
        conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (experiment_id, symbol, instrument_type, ticker, quantity, _iso()),
        )
        conn.commit()
        conn.close()

    def _paper_positions_count(self):
        conn = self._paper_conn()
        n = conn.execute("SELECT COUNT(*) n FROM pe_paper_positions").fetchone()["n"]
        conn.close()
        return n

    # -- 1. no active experiment at all ----------------------------------
    def test_no_active_experiment_returns_not_reconciled(self):
        symbol = "CLQD1"
        pid, iid = self._seed_position(symbol)
        result = webhook_receiver._reconcile_paper_close(symbol, pid, iid)
        self.assertFalse(result["reconciled"])
        self.assertEqual(result["reason"], "NO_ACTIVE_EXPERIMENT")

    # -- 2. active experiment, but tracks a different symbol -------------
    def test_symbol_not_tracked_returns_not_reconciled(self):
        symbol = "CLQD2"
        self._seed_experiment(symbol="OTHERSYM")
        pid, iid = self._seed_position(symbol)
        result = webhook_receiver._reconcile_paper_close(symbol, pid, iid)
        self.assertFalse(result["reconciled"])
        self.assertEqual(result["reason"], "SYMBOL_NOT_TRACKED")

    # -- 3. tracked, but no evidence (no heartbeats at all) ---------------
    def test_no_authoritative_state_returns_not_reconciled(self):
        symbol = "CLQD3"
        self._seed_experiment(symbol=symbol)
        pid, iid = self._seed_position(symbol)
        # No underlying_heartbeats / option_heartbeats rows seeded at all.
        result = webhook_receiver._reconcile_paper_close(symbol, pid, iid)
        self.assertFalse(result["reconciled"])
        self.assertEqual(result["reason"], "NO_AUTHORITATIVE_STATE")

    # -- 4. THE CRITICAL SAFETY TEST: evidence resolves a real ticker, but
    #       the paper challenge never held it -- must NOT create a phantom
    #       pe_paper_positions row or submit any proposal. -----------------
    def test_not_a_paper_holding_never_creates_phantom_position(self):
        symbol = "CLQD4"
        self._seed_experiment(symbol=symbol)
        pid, iid = self._seed_position(symbol, strike=0.5, expiration="2026-09-25")
        self._seed_underlying_heartbeat(symbol)
        self._seed_option_heartbeat(iid, pid, symbol, "OPRA_DLY:CLQD4260925C0.5")
        before = self._paper_positions_count()

        result = webhook_receiver._reconcile_paper_close(symbol, pid, iid)

        self.assertFalse(result["reconciled"])
        self.assertEqual(result["reason"], "NOT_A_PAPER_HOLDING")
        # The whole point: no phantom row, no fabricated cash.
        self.assertEqual(self._paper_positions_count(), before)

    # -- 5. genuine paper holding -> attempts a real proposal submission --
    def test_genuine_paper_holding_attempts_proposal(self):
        symbol = "CLQD5"
        ticker = "OPRA_DLY:CLQD5260918C1.5"
        eid = self._seed_experiment(symbol=symbol)
        pid, iid = self._seed_position(symbol)
        self._seed_underlying_heartbeat(symbol)
        self._seed_option_heartbeat(iid, pid, symbol, ticker)
        self._seed_paper_holding(eid, symbol, ticker, quantity=2.0)

        # The final proposal submission goes through the blueprint's OWN
        # closure-bound paper DB path (captured at module-import time), not
        # this test's temp path -- intercept the internal self-call to
        # verify the correct request would be sent, rather than needing to
        # rebind the already-mounted blueprint's closure.
        with mock.patch.object(app, "test_client") as mock_test_client:
            fake_client = mock.MagicMock()
            fake_resp = mock.MagicMock(status_code=201)
            fake_resp.get_json.return_value = {"proposal_id": 999, "mode": "AUTO_IF_VERY_HIGH_PAPER"}
            fake_client.post.return_value = fake_resp
            mock_test_client.return_value = fake_client

            result = webhook_receiver._reconcile_paper_close(symbol, pid, iid)

        self.assertTrue(result["reconciled"])
        self.assertEqual(result["proposal_id"], 999)
        fake_client.post.assert_called_once()
        call_args = fake_client.post.call_args
        self.assertEqual(call_args[0][0], "/paper/proposals")
        body = call_args[1]["json"]
        self.assertEqual(body["action"], "close")
        self.assertEqual(body["symbol"], symbol)
        self.assertEqual(body["experiment_id"], eid)
        self.assertEqual(body["position_ref"], pid)
        self.assertEqual(body["instrument_ref"], iid)

    # -- 6. the regular close endpoint must ALWAYS succeed even if
    #       reconciliation raises internally -- two independent guards:
    #       _reconcile_paper_close's own try/except, AND a second guard at
    #       the close_instruments() call site (defense in depth). -----------
    def test_close_instruments_route_succeeds_even_if_reconciliation_raises(self):
        symbol = "CLQD6"
        pid, iid = self._seed_position(symbol)
        headers = {"Authorization": f"Bearer {TEST_STATE_TOKEN}"}

        with mock.patch.object(webhook_receiver, "_reconcile_paper_close",
                               side_effect=RuntimeError("boom")):
            resp = self.client.post(
                f"/positions/{pid}/instruments/close",
                json={"instrument_ids": [iid], "quantity": 2.0, "exit_price": 1.03},
                headers=headers,
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["paper_reconciliation"],
                         [{"instrument_id": iid, "reconciled": False, "reason": "INTERNAL_ERROR"}])
        # And the regular close genuinely happened, not just a non-crash.
        conn = self._wh_conn()
        row = conn.execute("SELECT status FROM position_instruments WHERE id=?", (iid,)).fetchone()
        conn.close()
        self.assertEqual(row["status"], "CLOSED")

    # -- 7. _reconcile_paper_close itself never raises out of a real
    #       internal failure (its own try/except is the safety net) ------
    def test_reconcile_paper_close_never_raises(self):
        symbol = "CLQD7"
        pid, iid = self._seed_position(symbol)
        with mock.patch.object(webhook_receiver, "PAPER_DB_PATH", "/nonexistent/path/paper.db"):
            result = webhook_receiver._reconcile_paper_close(symbol, pid, iid)
        self.assertFalse(result["reconciled"])
        self.assertEqual(result["reason"], "INTERNAL_ERROR")


if __name__ == "__main__":
    unittest.main()
