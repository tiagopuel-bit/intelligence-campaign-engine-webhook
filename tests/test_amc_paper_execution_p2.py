"""Deterministic P2/P2A tests: authenticated API, server-side reconstruction,
real paper fills, two-path runner, cloud state provider, transactional
modification, evidence snapshots, and schema migration."""
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask

from paper_execution import db
from paper_execution.api import create_blueprint
from paper_execution.cloud_state import cloud_state_provider, cloud_readiness
from paper_execution.state import reconstruct_legs
from paper_execution.runner import health_summary, run_once
from paper_execution.store import (
    create_experiment,
    create_proposal,
    frozen_goal_hash,
    frozen_policy_hash,
    set_kill_switch,
    transition,
)

TOKEN = "test-state-token"


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _iso(minutes_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()


def valid_state(stale=False, source="live_webhook", contract_source="live_contract_bar"):
    now = _now_ms()
    if stale:
        now -= 10 * 60 * 1000
    return {
        "symbol": "AMC",
        "underlying": {"confirm_tone": "pos", "timing_tone": "pos", "upper_neg": False,
                       "bar_time": now, "source": source},
        "contract": {"option_return": 0.5, "matched_bars": 20, "activity_ratio": 0.9,
                     "missing_bar": False, "unchanged_print": False,
                     "bar_time": now, "source": contract_source},
        "execution": {"bar_time": now, "source": "live", "price_reference": 1.5, "stale": False},
        "position": {"exists": True, "direction": "LONG", "side": "sell_to_close",
                     "trigger": "DRAW_DOWN_PROTECTION", "exposure_ok": True,
                     "duplicate": False, "conflict": False, "daily_loss_ok": True,
                     "quantity": 2, "instrument_type": "CALL", "ticker": "O:AMC",
                     "position_ref": "1", "instrument_ref": "11"},
        "catalyst": {"sec_veto": False},
        "stale_underlying": False,
        "stale_option_quote": False,
    }


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


class PaperApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.experiment_id = make_experiment(conn)
        conn.close()
        self._provider_state = valid_state()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_blueprint(self._tmp.name, TOKEN, lambda db_path, symbol: self._provider_state))
        self.client = self.app.test_client()
        self.h = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)

    def _create(self, body=None):
        payload = {"action": "close", "symbol": "AMC", "experiment_id": self.experiment_id,
                   "idempotency_key": "k1", "position_ref": "1", "instrument_ref": "11"}
        if body:
            payload.update(body)
        return self.client.post("/paper/proposals", json=payload, headers=self.h)

    def test_unauthorized_returns_401(self):
        self.assertEqual(self.client.get("/paper/proposals").status_code, 401)

    def test_health_public_no_secrets(self):
        body = self.client.get("/paper/health").get_json()
        self.assertEqual(body["paper_only"], True)
        self.assertEqual(body["active_experiment_id"], self.experiment_id)
        self.assertFalse(body["authoritative_provider_ready"])
        self.assertFalse(body["runner_ready"])
        self.assertIn("BLOCKED_NO_AUTHORITATIVE_PROVIDER_STATUS", body["blockers"])
        for key in body:
            self.assertNotIn("token", key.lower())
            self.assertNotIn("secret", key.lower())

    def test_create_reconstructs_server_side(self):
        r = self._create()
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertTrue(body["very_high"])
        self.assertEqual(body["mode"], "AUTO_IF_VERY_HIGH_PAPER")

    def test_unknown_fields_rejected(self):
        for field in ("very_high", "evidence", "freshness", "price_source", "mode", "policy_sha256", "bogus"):
            r = self._create({field: "attacker"})
            self.assertEqual(r.status_code, 400, field)
            self.assertIn("unknown fields", r.get_json()["error"])

    def test_position_actions_require_exact_references(self):
        r = self.client.post("/paper/proposals", json={
            "action": "close", "symbol": "AMC", "experiment_id": self.experiment_id,
            "idempotency_key": "missing-refs",
        }, headers=self.h)
        self.assertEqual(r.status_code, 400)
        self.assertIn("position_ref", r.get_json()["error"])

    def test_experiment_validation(self):
        self.assertEqual(self._create({"experiment_id": 9999}).status_code, 409)
        self.assertEqual(self._create({"symbol": "TSLA"}).status_code, 409)
        self.assertEqual(self._create({"action": "not_an_action"}).status_code, 409)

    def test_experiment_returns_live_cash(self):
        conn = db.connect(self._tmp.name)
        conn.execute("UPDATE pe_paper_cash SET cash=150.0 WHERE experiment_id=?", (self.experiment_id,))
        conn.commit()
        conn.close()
        body = self.client.get(f"/paper/experiments/{self.experiment_id}", headers=self.h).get_json()
        self.assertEqual(body["starting_cash"], 100.0)
        self.assertEqual(body["live_cash"], 150.0)

    def test_duplicate_idempotency(self):
        first = self._create().get_json()
        second = self._create().get_json()
        self.assertEqual(first["proposal_id"], second["proposal_id"])

    def test_modify_transactional_new_version(self):
        pid = self._create().get_json()["proposal_id"]
        r = self.client.post(f"/paper/proposals/{pid}/modify",
                             json={"action": "partial_reduce", "idempotency_key": "k1-v2"}, headers=self.h)
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["parent_proposal_id"], pid)
        self.assertEqual(body["version"], 2)
        conn = db.connect(self._tmp.name)
        orig = conn.execute("SELECT current_status FROM pe_order_proposals WHERE id=?", (pid,)).fetchone()
        children = conn.execute("SELECT COUNT(*) n FROM pe_order_proposals WHERE parent_proposal_id=?", (pid,)).fetchone()["n"]
        decisions = conn.execute("SELECT COUNT(*) n FROM pe_user_decisions WHERE proposal_id=?", (pid,)).fetchone()["n"]
        conn.close()
        self.assertEqual(orig["current_status"], "CANCELLED")
        self.assertEqual(children, 1)
        self.assertGreaterEqual(decisions, 1)

    def test_expired_approval_rejected(self):
        pid = self._create().get_json()["proposal_id"]
        conn = db.connect(self._tmp.name)
        conn.execute("UPDATE pe_order_proposals SET expires_at=? WHERE id=?", (_iso(-10), pid))
        conn.commit()
        conn.close()
        r = self.client.post(f"/paper/proposals/{pid}/approve", headers=self.h)
        self.assertEqual(r.status_code, 409)
        self.assertIn("expired", r.get_json()["error"])

    def test_evidence_snapshot_roundtrip(self):
        pid = self._create().get_json()["proposal_id"]
        conn = db.connect(self._tmp.name)
        row = conn.execute("SELECT raw_fields FROM pe_proposal_evidence WHERE proposal_id=?", (pid,)).fetchone()
        conn.close()
        stored = json.loads(row["raw_fields"])
        self.assertEqual(stored["evidence"]["portfolio_risk"]["trigger"], "DRAW_DOWN_PROTECTION")
        self.assertIn("policy_sha256", stored)
        self.assertIn("corrections_v12_sha256", stored)

    def test_kill_switch_route_global(self):
        r = self.client.post(
            f"/paper/experiments/{self.experiment_id}/kill-switch",
            json={"scope": "GLOBAL", "enabled": False}, headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        conn = db.connect(self._tmp.name)
        row = conn.execute(
            "SELECT auto_enabled FROM pe_auto_switches WHERE experiment_id=? AND scope='GLOBAL'",
            (self.experiment_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row["auto_enabled"], 0)

    def test_kill_switch_route_position(self):
        r = self.client.post(
            f"/paper/experiments/{self.experiment_id}/kill-switch",
            json={"scope": "POSITION", "position_ref": "7", "enabled": False}, headers=self.h,
        )
        self.assertEqual(r.status_code, 200)
        conn = db.connect(self._tmp.name)
        row = conn.execute(
            "SELECT auto_enabled FROM pe_auto_switches WHERE experiment_id=? AND scope='POSITION' AND position_ref='7'",
            (self.experiment_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row["auto_enabled"], 0)

    def test_kill_switch_route_requires_auth(self):
        r = self.client.post(
            f"/paper/experiments/{self.experiment_id}/kill-switch",
            json={"scope": "GLOBAL", "enabled": False},
        )
        self.assertEqual(r.status_code, 401)

    def test_kill_switch_route_position_requires_ref(self):
        r = self.client.post(
            f"/paper/experiments/{self.experiment_id}/kill-switch",
            json={"scope": "POSITION", "enabled": False}, headers=self.h,
        )
        self.assertEqual(r.status_code, 400)

    def test_kill_switch_route_rejects_unknown_fields(self):
        r = self.client.post(
            f"/paper/experiments/{self.experiment_id}/kill-switch",
            json={"scope": "GLOBAL", "enabled": False, "bogus": 1}, headers=self.h,
        )
        self.assertEqual(r.status_code, 400)

    def test_kill_switch_route_unknown_experiment(self):
        r = self.client.post(
            "/paper/experiments/9999/kill-switch",
            json={"scope": "GLOBAL", "enabled": False}, headers=self.h,
        )
        self.assertEqual(r.status_code, 404)

    def test_hold_requires_auth(self):
        pid = self._create().get_json()["proposal_id"]
        r = self.client.post(f"/paper/proposals/{pid}/hold")
        self.assertEqual(r.status_code, 401)

    def test_hold_pauses_the_clock(self):
        pid = self._create().get_json()["proposal_id"]
        r = self.client.post(f"/paper/proposals/{pid}/hold", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["to"], "ON_HOLD")
        self.assertIsNone(r.get_json()["expires_at"])
        conn = db.connect(self._tmp.name)
        row = conn.execute("SELECT current_status, expires_at FROM pe_order_proposals WHERE id=?",
                           (pid,)).fetchone()
        conn.close()
        self.assertEqual(row["current_status"], "ON_HOLD")
        # Stored as a far-future sentinel (schema is expires_at NOT NULL), not
        # a literal NULL -- the API contract still returns None (see above).
        self.assertEqual(row["expires_at"], "9999-12-31T23:59:59+00:00")

    def test_resume_rearms_a_fresh_window(self):
        pid = self._create().get_json()["proposal_id"]
        self.client.post(f"/paper/proposals/{pid}/hold", headers=self.h)
        r = self.client.post(f"/paper/proposals/{pid}/resume", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["to"], "PENDING_APPROVAL")
        conn = db.connect(self._tmp.name)
        row = conn.execute("SELECT current_status, expires_at FROM pe_order_proposals WHERE id=?",
                           (pid,)).fetchone()
        conn.close()
        self.assertEqual(row["current_status"], "PENDING_APPROVAL")
        self.assertIsNotNone(row["expires_at"])
        self.assertGreater(row["expires_at"], datetime.now(timezone.utc).isoformat())

    def test_approve_directly_from_hold(self):
        pid = self._create().get_json()["proposal_id"]
        self.client.post(f"/paper/proposals/{pid}/hold", headers=self.h)
        r = self.client.post(f"/paper/proposals/{pid}/approve", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["to"], "APPROVED")

    def test_reject_directly_from_hold(self):
        pid = self._create().get_json()["proposal_id"]
        self.client.post(f"/paper/proposals/{pid}/hold", headers=self.h)
        r = self.client.post(f"/paper/proposals/{pid}/reject", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["to"], "REJECTED")

    def test_cancel_directly_from_hold(self):
        pid = self._create().get_json()["proposal_id"]
        self.client.post(f"/paper/proposals/{pid}/hold", headers=self.h)
        r = self.client.post(f"/paper/proposals/{pid}/cancel", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["to"], "CANCELLED")

    def test_hold_rejected_from_non_pending_status(self):
        pid = self._create().get_json()["proposal_id"]
        self.client.post(f"/paper/proposals/{pid}/approve", headers=self.h)
        r = self.client.post(f"/paper/proposals/{pid}/hold", headers=self.h)
        self.assertEqual(r.status_code, 409)

    def test_resume_rejected_from_non_hold_status(self):
        pid = self._create().get_json()["proposal_id"]
        r = self.client.post(f"/paper/proposals/{pid}/resume", headers=self.h)
        self.assertEqual(r.status_code, 409)

    def test_hold_unknown_proposal_404(self):
        r = self.client.post("/paper/proposals/9999/hold", headers=self.h)
        self.assertEqual(r.status_code, 404)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.experiment_id = make_experiment(conn)
        conn.close()
        self._provider_state = valid_state()

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)

    def _proposal(self, action="close", mode="AUTO_IF_VERY_HIGH_PAPER", very_high=True, expires=10):
        conn = db.connect(self._tmp.name)
        pid = create_proposal(
            conn, experiment_id=self.experiment_id, idempotency_key=action + str(expires) + str(mode),
            action=action, mode=mode, symbol="AMC", policy_sha256=frozen_policy_hash(),
            time_sensitive_reason="x", very_high=very_high, very_high_missing_roots=[],
            expires_at=_iso(expires), cancel_condition="stale_underlying",
            evidence_roots=[{"root": "underlying_dna", "present": True, "raw_fields": {},
                             "missing_evidence": [], "contradictions": [], "veto": False}],
            position_ref="1", instrument_ref="11",
        )
        conn.close()
        return pid

    def _provider(self):
        return lambda db_path, symbol: self._provider_state

    def test_approved_path_immediate_fill(self):
        pid = self._proposal(mode="APPROVAL_REQUIRED", expires=10)
        conn = db.connect(self._tmp.name)
        transition(conn, pid, "APPROVED", actor="user", expected_from="PENDING_APPROVAL")
        conn.close()
        results = run_once(self._tmp.name, self._provider())
        self.assertEqual(results[0]["status"], "FILLED")
        conn = db.connect(self._tmp.name)
        orders = conn.execute("SELECT COUNT(*) n FROM pe_paper_orders WHERE proposal_id=?", (pid,)).fetchone()["n"]
        fills = conn.execute("SELECT COUNT(*) n FROM pe_paper_fills f JOIN pe_paper_orders o ON o.id=f.order_id WHERE o.proposal_id=?", (pid,)).fetchone()["n"]
        cash = conn.execute("SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (self.experiment_id,)).fetchone()["cash"]
        paper_position = conn.execute(
            "SELECT quantity FROM pe_paper_positions WHERE experiment_id=? AND ticker='O:AMC'",
            (self.experiment_id,),
        ).fetchone()
        provenance = conn.execute(
            "SELECT price_source, bar_time FROM pe_paper_orders WHERE proposal_id=? LIMIT 1", (pid,)
        ).fetchone()
        conn.close()
        self.assertGreaterEqual(orders, 1)
        self.assertGreaterEqual(fills, 1)
        self.assertEqual(cash, 400.0)
        self.assertEqual(paper_position["quantity"], -2.0)
        self.assertEqual(provenance["price_source"], "live")
        self.assertTrue(provenance["bar_time"])

    def test_reference_mismatch_cancels_without_order(self):
        pid = self._proposal(expires=-1)
        state = valid_state()
        state["position"]["instrument_ref"] = "999"
        self._provider_state = state
        result = run_once(self._tmp.name, self._provider())[0]
        self.assertEqual(result["reason"], "INSTRUMENT_REF_MISMATCH")
        conn = db.connect(self._tmp.name)
        count = conn.execute("SELECT COUNT(*) n FROM pe_paper_orders WHERE proposal_id=?", (pid,)).fetchone()["n"]
        conn.close()
        self.assertEqual(count, 0)

    def test_auto_path_waits_until_deadline(self):
        pid = self._proposal(expires=10)  # not yet due
        results = run_once(self._tmp.name, self._provider())
        self.assertEqual(results, [])  # nothing due
        conn = db.connect(self._tmp.name)
        conn.execute("UPDATE pe_order_proposals SET expires_at=? WHERE id=?", (_iso(-1), pid))
        conn.commit()
        conn.close()
        results = run_once(self._tmp.name, self._provider())
        self.assertEqual(results[0]["status"], "FILLED")

    def test_on_hold_never_auto_claimed_even_past_deadline(self):
        pid = self._proposal(expires=10)
        conn = db.connect(self._tmp.name)
        transition(conn, pid, "ON_HOLD", actor="user", expected_from="PENDING_APPROVAL")
        conn.execute("UPDATE pe_order_proposals SET expires_at=? WHERE id=?",
                     ("9999-12-31T23:59:59+00:00", pid))
        conn.commit()
        conn.close()
        # Force the clock far past what would have been the original deadline.
        results = run_once(self._tmp.name, self._provider())
        self.assertEqual(results, [])
        conn = db.connect(self._tmp.name)
        status = conn.execute("SELECT current_status FROM pe_order_proposals WHERE id=?",
                              (pid,)).fetchone()["current_status"]
        conn.close()
        self.assertEqual(status, "ON_HOLD")

    def test_kill_switch_wins_auto_path(self):
        pid = self._proposal(expires=-1)
        conn = db.connect(self._tmp.name)
        set_kill_switch(conn, self.experiment_id, "GLOBAL", None, enabled=False)
        conn.close()
        results = run_once(self._tmp.name, self._provider())
        self.assertTrue(results[0]["status"] in ("SKIPPED", "CANCELLED_REVALIDATION"))

    def test_missing_delayed_unknown_future_no_order(self):
        pid = self._proposal(expires=-1)
        providers = [
            lambda db_path, symbol: None,
            lambda db_path, symbol: valid_state(source="massive"),
            lambda db_path, symbol: valid_state(source="mystery"),
            lambda db_path, symbol: valid_state(stale=True),
        ]
        for provider in providers:
            conn = db.connect(self._tmp.name)
            conn.execute("UPDATE pe_order_proposals SET current_status='PENDING_APPROVAL', expires_at=? WHERE id=?", (_iso(-1), pid))
            conn.commit()
            conn.close()
            results = run_once(self._tmp.name, provider)
            self.assertEqual(results[0]["status"], "CANCELLED_REVALIDATION")
        conn = db.connect(self._tmp.name)
        orders = conn.execute("SELECT COUNT(*) n FROM pe_paper_orders WHERE proposal_id=?", (pid,)).fetchone()["n"]
        conn.close()
        self.assertEqual(orders, 0)

    def test_unscorable_writes_order_no_fill(self):
        pid = self._proposal(expires=-1)
        state = valid_state()
        state["execution"]["leg_price"] = None  # fill unscorable; execution reference still valid
        self._provider_state = state
        results = run_once(self._tmp.name, self._provider())
        self.assertEqual(results[0]["status"], "UNSCORABLE_EXECUTION_DATA")
        conn = db.connect(self._tmp.name)
        orders = conn.execute("SELECT COUNT(*) n FROM pe_paper_orders WHERE proposal_id=?", (pid,)).fetchone()["n"]
        fills = conn.execute("SELECT COUNT(*) n FROM pe_paper_fills f JOIN pe_paper_orders o ON o.id=f.order_id WHERE o.proposal_id=?", (pid,)).fetchone()["n"]
        conn.close()
        self.assertGreaterEqual(orders, 1)
        self.assertEqual(fills, 0)

    def test_cloud_provider_db_backed(self):
        # A DB-backed provider must be used (not the JSON fixture). Build a
        # synthetic webhook DB with a fresh heartbeat + position; the option
        # relay is absent, so the runner cancels honestly (no fake fill).
        wh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        wh.close()
        wconn = sqlite3.connect(wh.name)
        wconn.execute("CREATE TABLE alerts (symbol TEXT, timeframe TEXT, phase TEXT, close REAL, bar_time INTEGER, source TEXT)")
        wconn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, status TEXT)")
        wconn.execute("CREATE TABLE position_instruments (position_id INTEGER, instrument_type TEXT, quantity REAL, status TEXT)")
        wconn.execute("CREATE TABLE sec_filings (symbol TEXT, category TEXT, severity TEXT)")
        now = _now_ms()
        wconn.execute("INSERT INTO alerts VALUES ('AMC','60','EXPANSION',2.0,?,'live_webhook')", (now,))
        wconn.execute("INSERT INTO alerts VALUES ('AMC','15','EXPANSION',2.0,?,'live_webhook')", (now,))
        wconn.execute("INSERT INTO positions VALUES (1,'AMC','LONG','OPEN')")
        wconn.execute("INSERT INTO position_instruments VALUES (1,'CALL',2,'OPEN')")
        wconn.commit()
        wconn.close()

        pid = self._proposal(expires=-1)
        provider = cloud_state_provider(wh.name)
        results = run_once(self._tmp.name, provider)
        # contract relay absent -> NO_LIVE_CONTRACT_SOURCE -> cancelled, no fill
        self.assertEqual(results[0]["status"], "CANCELLED_REVALIDATION")
        conn = db.connect(self._tmp.name)
        orders = conn.execute("SELECT COUNT(*) n FROM pe_paper_orders WHERE proposal_id=?", (pid,)).fetchone()["n"]
        conn.close()
        self.assertEqual(orders, 0)
        Path(wh.name).unlink(missing_ok=True)

    def test_cloud_provider_requires_exact_ref_and_distinct_relays(self):
        wh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        wh.close()
        conn = sqlite3.connect(wh.name)
        conn.execute("CREATE TABLE alerts (symbol TEXT, timeframe TEXT, phase TEXT, bar_time INTEGER, source TEXT)")
        conn.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT, status TEXT)")
        conn.execute("CREATE TABLE position_instruments (id INTEGER PRIMARY KEY, position_id INTEGER, instrument_type TEXT, quantity REAL, strike REAL, expiration TEXT, status TEXT)")
        conn.execute("CREATE TABLE underlying_heartbeats (symbol TEXT, bar_time INTEGER, close REAL, source TEXT)")
        conn.execute("CREATE TABLE option_heartbeats (instrument_ref TEXT, position_ref TEXT, ticker TEXT, bar_time INTEGER, close REAL, option_return REAL, matched_bars INTEGER, activity_ratio REAL, session TEXT, source TEXT)")
        conn.execute("CREATE TABLE sec_filings (symbol TEXT, category TEXT, severity TEXT, first_seen_at TEXT, seed_record INTEGER)")
        now = _now_ms()
        conn.execute("INSERT INTO alerts VALUES ('AMC','60','EXPANSION',?,'live_webhook')", (now,))
        conn.execute("INSERT INTO alerts VALUES ('AMC','15','EXPANSION',?,'live_webhook')", (now,))
        conn.execute("INSERT INTO positions VALUES (7,'AMC','LONG','OPEN')")
        conn.execute("INSERT INTO position_instruments VALUES (11,7,'CALL',2,1.5,'2026-09-18','OPEN')")
        conn.execute("INSERT INTO underlying_heartbeats VALUES ('AMC',?,2.63,'live_webhook')", (now,))
        conn.execute("INSERT INTO option_heartbeats VALUES ('11','7','O:AMC',?,1.14,0.05,20,0.9,'RTH','live_contract_bar')", (now,))
        # Historical/seeded dilution capacity must not veto forever.
        conn.execute("INSERT INTO sec_filings VALUES ('AMC','DILUTION_WATCH','HIGH','2025-01-01T00:00:00+00:00',1)")
        conn.commit()
        conn.close()
        self.assertTrue(cloud_readiness(wh.name)["authoritative_provider_ready"])
        provider = cloud_state_provider(wh.name)
        state = provider(None, "AMC", position_ref="7", instrument_ref="11")
        self.assertEqual(state["position"]["instrument_ref"], "11")
        self.assertEqual(state["execution"]["source"], "live_contract_bar")
        self.assertFalse(state["catalyst"]["sec_veto"])
        self.assertIsNone(provider(None, "AMC", position_ref="7", instrument_ref="999"))
        Path(wh.name).unlink(missing_ok=True)

    def test_roll_reconstruction_requires_two_legs(self):

        state = valid_state()
        self.assertEqual(reconstruct_legs(state, "AMC", "roll")[0], None)
        state["roll_legs"] = [
            {"ticker": "OLD", "side": "sell_to_close", "quantity": 1, "price_reference": 1.2, "instrument_type": "CALL"},
            {"ticker": "NEW", "side": "buy_to_open", "quantity": 1, "price_reference": 0.8, "instrument_type": "CALL"},
        ]
        legs, instrument_type = reconstruct_legs(state, "AMC", "roll")
        self.assertEqual(len(legs), 2)
        self.assertEqual(instrument_type, "CALL")


class MigrationTests(unittest.TestCase):
    def test_migration_adds_columns_without_losing_rows(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        # Simulate a pre-P2A DB: old pe_order_proposals without parent/version.
        old = sqlite3.connect(tmp.name)
        old.execute("CREATE TABLE pe_order_proposals (id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id INTEGER, idempotency_key TEXT, policy_version INTEGER NOT NULL, policy_sha256 TEXT NOT NULL, action TEXT, mode TEXT, symbol TEXT, time_sensitive_reason TEXT, very_high INTEGER, very_high_missing_roots TEXT, status TEXT, current_status TEXT, expires_at TEXT, cancel_condition TEXT, created_at TEXT)")
        old.execute("INSERT INTO pe_order_proposals (experiment_id, idempotency_key, policy_version, policy_sha256, action, mode, symbol, very_high, status, current_status, expires_at, cancel_condition, created_at) VALUES (1,'k',1,'h','close','APPROVAL_REQUIRED','AMC',0,'PENDING_APPROVAL','PENDING_APPROVAL','2027-01-01T00:00:00Z','x','2026-01-01T00:00:00Z')")
        old.commit()
        old.close()
        # Re-init: new columns/tables added, existing row preserved.
        db.init_db(tmp.name)
        conn = db.connect(tmp.name)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(pe_order_proposals)")}
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        rows = conn.execute("SELECT COUNT(*) n FROM pe_order_proposals").fetchone()["n"]
        conn.close()
        self.assertIn("parent_proposal_id", cols)
        self.assertIn("version", cols)
        self.assertIn("pe_paper_cash", tables)
        self.assertIn("pe_paper_positions", tables)
        self.assertEqual(rows, 1)
        Path(tmp.name).unlink(missing_ok=True)


class SetBracketApiTests(unittest.TestCase):
    """set_bracket proposals flow through approval before any bracket is set."""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        db.init_db(self._tmp.name)
        conn = db.connect(self._tmp.name)
        self.experiment_id = make_experiment(conn)
        conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?)", (self.experiment_id, "AMC", "SHARE", "AMC", 100.0, _iso(0))
        )
        conn.commit()
        conn.close()
        self._provider_state = valid_state()
        self.app = Flask(__name__)
        self.app.register_blueprint(create_blueprint(self._tmp.name, TOKEN, lambda db_path, symbol: self._provider_state))
        self.client = self.app.test_client()
        self.h = {"Authorization": f"Bearer {TOKEN}"}

    def tearDown(self):
        Path(self._tmp.name).unlink(missing_ok=True)

    def _create_bracket(self, **overrides):
        payload = {"action": "set_bracket", "symbol": "AMC", "experiment_id": self.experiment_id,
                   "idempotency_key": "b1", "position_ref": "AMC", "stop_price": 5.0}
        payload.update(overrides)
        return self.client.post("/paper/proposals", json=payload, headers=self.h)

    def _active_brackets(self):
        return self.client.get("/paper/brackets", headers=self.h).get_json()

    def test_proposal_does_not_set_bracket_until_approved(self):
        r = self._create_bracket()
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self._active_brackets(), [])

    def test_approve_sets_bracket_with_exact_prices(self):
        pid = self._create_bracket().get_json()["proposal_id"]
        r = self.client.post(f"/paper/proposals/{pid}/approve", headers=self.h)
        self.assertEqual(r.status_code, 200)
        self.assertIn("bracket_id", r.get_json())
        brackets = self._active_brackets()
        self.assertEqual(len(brackets), 1)
        self.assertEqual(brackets[0]["stop_price"], 5.0)
        self.assertEqual(brackets[0]["ticker"], "AMC")

    def test_reject_never_sets_bracket(self):
        pid = self._create_bracket().get_json()["proposal_id"]
        self.client.post(f"/paper/proposals/{pid}/reject", headers=self.h)
        self.assertEqual(self._active_brackets(), [])

    def test_requires_position_ref(self):
        r = self._create_bracket(position_ref=None)
        self.assertEqual(r.status_code, 400)
        self.assertIn("position_ref", r.get_json()["error"])

    def test_requires_stop_or_target(self):
        r = self._create_bracket(stop_price=None)
        self.assertEqual(r.status_code, 400)

    def test_expired_proposal_cannot_approve(self):
        pid = self._create_bracket().get_json()["proposal_id"]
        conn = db.connect(self._tmp.name)
        conn.execute("UPDATE pe_order_proposals SET expires_at='2020-01-01T00:00:00Z' WHERE id=?", (pid,))
        conn.commit()
        conn.close()
        r = self.client.post(f"/paper/proposals/{pid}/approve", headers=self.h)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self._active_brackets(), [])


if __name__ == "__main__":
    unittest.main()
