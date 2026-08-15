"""Deterministic P1 tests: proposal engine, persistence, lifecycle, kill
switches, restart-safe due processing, and conservative paper fills.

Includes the v1.1 and v1.2 pre-activation corrections with direct adversarial
bypass tests for every gate.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from paper_execution import db
from paper_execution.engine import auto_mode_allowed, evaluate_very_high, revalidate
from paper_execution.fill import OPTION_CONTRACT_MULTIPLIER, simulate_order
from paper_execution.store import (
    AUTO_MODE,
    TransitionConflict,
    InvalidTransition,
    claim_due_proposal,
    create_experiment,
    create_proposal,
    due_proposals,
    frozen_corrections_hash,
    frozen_corrections_v12_hash,
    frozen_goal_hash,
    frozen_policy_hash,
    kill_switch_active,
    set_kill_switch,
    transition,
)


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _iso(minutes_from_now: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()


def valid_evidence(action="close"):
    now = _now_ms()
    trigger = "DRAW_DOWN_PROTECTION" if action in ("close", "partial_reduce") else None
    return {
        "underlying_dna": {"confirm_tone": "pos", "timing_tone": "pos", "upper_neg": False,
                           "bar_time": now, "source": "live_webhook"},
        "contract_response": {"option_return": 0.5, "matched_bars": 20, "activity_ratio": 0.9,
                              "missing_bar": False, "unchanged_print": False,
                              "bar_time": now, "source": "live_contract_bar"},
        "execution_quality": {"bar_time": now, "price_reference": 1.5, "source": "live", "stale": False},
        "portfolio_risk": {"position_exists": True, "direction": "LONG", "side": "sell_to_close",
                           "trigger": trigger, "exposure_ok": True, "duplicate": False,
                           "conflict": False, "daily_loss_ok": True},
        "catalyst": {"sec_veto": False},
        "stale_underlying": False,
        "stale_option_quote": False,
    }


class EngineTests(unittest.TestCase):
    def test_all_four_roots_pass(self):
        result = evaluate_very_high(valid_evidence("close"), "close")
        self.assertTrue(result["very_high"], result)

    def test_zero_age_freshness_is_live(self):
        result = evaluate_very_high(valid_evidence("close"), "close")
        self.assertNotIn("underlying_dna", result["missing_roots"])

    def test_future_timestamp_rejected(self):
        ev = valid_evidence("close")
        ev["underlying_dna"]["bar_time"] = _now_ms() + 5 * 60 * 1000
        result = evaluate_very_high(ev, "close")
        self.assertIn("FUTURE_TIMESTAMP", result["vetoes"])

    def test_delayed_source_ineligible(self):
        ev = valid_evidence("close")
        ev["contract_response"]["source"] = "massive"
        result = evaluate_very_high(ev, "close")
        self.assertIn("DELAYED_PROVIDER_BAR", result["vetoes"])

    def test_unknown_source_veto(self):
        ev = valid_evidence("close")
        ev["underlying_dna"]["source"] = "mystery_source"
        result = evaluate_very_high(ev, "close")
        self.assertFalse(result["very_high"])
        self.assertIn("UNKNOWN_SOURCE", result["vetoes"])

    def test_live_freshness_two_minutes(self):
        ev = valid_evidence("close")
        ev["underlying_dna"]["bar_time"] = _now_ms() - 3 * 60 * 1000
        result = evaluate_very_high(ev, "close")
        self.assertIn("underlying_dna", result["missing_roots"])

    def test_stale_underlying_blocks(self):
        ev = valid_evidence(); ev["stale_underlying"] = True
        result = evaluate_very_high(ev, "open")
        self.assertIn("STALE_UNDERLYING", result["vetoes"])

    def test_blocked_stale_option_quote(self):
        ev = valid_evidence(); ev["stale_option_quote"] = True
        result = evaluate_very_high(ev, "close")
        self.assertIn("BLOCKED_STALE_OPTION_QUOTE", result["vetoes"])

    def test_reduction_requires_existing_position(self):
        ev = valid_evidence(); ev["portfolio_risk"]["position_exists"] = False
        result = evaluate_very_high(ev, "close")
        self.assertIn("portfolio_risk", result["missing_roots"])

    def test_action_direction_incompatible(self):
        ev = valid_evidence(); ev["portfolio_risk"]["side"] = "buy_to_open"
        result = evaluate_very_high(ev, "close")
        self.assertIn("portfolio_risk", result["missing_roots"])

    def test_unknown_trigger_fails_closed(self):
        ev = valid_evidence(); ev["portfolio_risk"]["trigger"] = "MYSTERY_TRIGGER"
        result = evaluate_very_high(ev, "close")
        self.assertIn("portfolio_risk", result["missing_roots"])

    def test_missing_trigger_fails_closed(self):
        ev = valid_evidence(); ev["portfolio_risk"]["trigger"] = None
        result = evaluate_very_high(ev, "close")
        self.assertIn("portfolio_risk", result["missing_roots"])

    def test_malformed_numeric_fails_closed(self):
        for bad in ("abc", float("nan"), float("inf"), -float("inf")):
            ev = valid_evidence()
            ev["contract_response"]["option_return"] = bad
            result = evaluate_very_high(ev, "open")
            self.assertIn("contract_response", result["missing_roots"], bad)

    def test_missing_option_bar_blocks(self):
        ev = valid_evidence(); ev["contract_response"]["missing_bar"] = True
        result = evaluate_very_high(ev, "open")
        self.assertIn("contract_response", result["missing_roots"])

    def test_unchanged_print_blocks(self):
        ev = valid_evidence(); ev["contract_response"]["option_return"] = 0.0
        result = evaluate_very_high(ev, "open")
        self.assertIn("contract_response", result["missing_roots"])

    def test_conflicting_order_blocks(self):
        ev = valid_evidence(); ev["portfolio_risk"]["conflict"] = True
        result = evaluate_very_high(ev, "open")
        self.assertIn("portfolio_risk", result["missing_roots"])

    def test_sec_catalyst_veto(self):
        ev = valid_evidence(); ev["catalyst"]["sec_veto"] = True
        result = evaluate_very_high(ev, "open")
        self.assertIn("SEC_CATALYST_VETO", result["vetoes"])

    def test_revalidate_returns_invalid_reason(self):
        ev = valid_evidence(); ev["stale_underlying"] = True
        out = revalidate("open", ev)
        self.assertEqual(out["status"], "INVALID")
        self.assertIn("STALE_UNDERLYING", out["reason"])

    def test_very_high_auto_actions_enforced(self):
        self.assertTrue(auto_mode_allowed("close"))
        self.assertTrue(auto_mode_allowed("partial_reduce"))
        self.assertFalse(auto_mode_allowed("open"))
        self.assertFalse(auto_mode_allowed("add"))
        self.assertFalse(auto_mode_allowed("roll"))


class FillTests(unittest.TestCase):
    def test_single_leg_fill(self):
        self.assertEqual(simulate_order([{"price_reference": 1.5, "quantity": 2}])["status"], "FILLED")

    def test_missing_price_is_unscorable(self):
        self.assertEqual(simulate_order([{"price_reference": None, "quantity": 2}])["status"], "UNSCORABLE_EXECUTION_DATA")

    def test_non_finite_and_non_positive_prices_rejected(self):
        for bad in (0.0, -1.0, float("inf"), float("nan")):
            out = simulate_order([{"price_reference": bad, "quantity": 1}])
            self.assertEqual(out["status"], "UNSCORABLE_EXECUTION_DATA", bad)

    def test_non_integer_quantity_rejected(self):
        out = simulate_order([{"price_reference": 1.5, "quantity": 1.5}])
        self.assertEqual(out["status"], "INVALID_QUANTITY")

    def test_roll_requires_both_legs(self):
        out = simulate_order([
            {"price_reference": 1.5, "quantity": 2, "side": "sell_to_close"},
            {"price_reference": None, "quantity": 2, "side": "buy_to_open"},
        ])
        self.assertEqual(out["status"], "UNSCORABLE_EXECUTION_DATA")

    def test_option_multiplier_derived_from_instrument_type(self):
        call = simulate_order([{"price_reference": 1.5, "quantity": 2}], instrument_type="CALL")
        self.assertEqual(call["legs"][0]["notional"], round(1.5 * 2 * 100, 2))
        put = simulate_order([{"price_reference": 1.5, "quantity": 2}], instrument_type="PUT")
        self.assertEqual(put["legs"][0]["notional"], round(1.5 * 2 * 100, 2))
        share = simulate_order([{"price_reference": 1.5, "quantity": 2}], instrument_type="SHARE")
        self.assertEqual(share["legs"][0]["notional"], round(1.5 * 2 * 1, 2))

    def test_signed_roll_debit_credit(self):
        out = simulate_order([
            {"price_reference": 0.80, "quantity": 2, "side": "sell_to_close"},
            {"price_reference": 0.50, "quantity": 2, "side": "buy_to_open"},
        ], instrument_type="CALL")
        self.assertEqual(out["status"], "FILLED")
        self.assertEqual(out["net"], 60.0)


class StoreTests(unittest.TestCase):
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
            self.conn, version=1, symbol="AMC", start_at=_iso(-5), end_at="2027-01-31T16:00:00-08:00",
            starting_cash=100.0, starting_value_method="marked_market_value",
            target_value_jan2027=15000.0, target_return_pct=None, max_drawdown_pct=25.0,
            max_amc_exposure=0.70, max_exposure_per_option_expiry=0.25,
            deposit_policy="ALLOWED_TRACKED_SEPARATELY", allowed_actions="hold,add,open,partial_reduce,close,roll",
            benchmark_symbol="AMC", benchmark_success_criteria="beat buy-and-hold",
            min_observation_count=30, max_daily_paper_loss=0.05, max_orders_per_day=3,
            max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )

    def _proposal(self, experiment_id, key="k1", expires=10, action="close", mode=AUTO_MODE, very_high=True):
        return create_proposal(
            self.conn, experiment_id=experiment_id, idempotency_key=key, action=action,
            mode=mode, symbol="AMC", policy_sha256=frozen_policy_hash(),
            time_sensitive_reason="confirmation", very_high=very_high, very_high_missing_roots=[],
            expires_at=_iso(expires), cancel_condition="stale_underlying",
            evidence_roots=[{"root": "underlying_dna", "present": True, "raw_fields": {}, "missing_evidence": [], "contradictions": [], "veto": False}],
        )

    def test_frozen_hashes_preserved(self):
        import hashlib
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(frozen_policy_hash(), hashlib.sha256(
            (root / "paper_execution" / "policy_v1.json").read_bytes()).hexdigest())
        self.assertEqual(frozen_goal_hash(), hashlib.sha256(
            (root / "paper_execution" / "experiment_goal_v1.json").read_bytes()).hexdigest())
        self.assertEqual(frozen_corrections_hash(), hashlib.sha256(
            (root / "paper_execution" / "policy_corrections_v1.1.json").read_bytes()).hexdigest())
        self.assertEqual(frozen_corrections_v12_hash(), hashlib.sha256(
            (root / "paper_execution" / "policy_corrections_v1.2.json").read_bytes()).hexdigest())

    def test_duplicate_trigger_idempotent(self):
        eid = self._experiment()
        first = self._proposal(eid, key="dup")
        second = self._proposal(eid, key="dup")
        self.assertEqual(first, second)

    def test_double_approval_rejected(self):
        eid = self._experiment()
        pid = self._proposal(eid)
        transition(self.conn, pid, "APPROVED", actor="user", expected_from="PENDING_APPROVAL")
        with self.assertRaises(TransitionConflict):
            transition(self.conn, pid, "APPROVED", actor="user", expected_from="PENDING_APPROVAL")

    def test_invalid_transition_rejected(self):
        eid = self._experiment()
        pid = self._proposal(eid)
        with self.assertRaises(InvalidTransition):
            transition(self.conn, pid, "PAPER_EXECUTED", expected_from="PENDING_APPROVAL")

    def test_cancel_at_deadline(self):
        eid = self._experiment()
        pid = self._proposal(eid, expires=-1)
        due = due_proposals(self.conn, _iso(0))
        self.assertTrue(any(d["id"] == pid for d in due))
        transition(self.conn, pid, "REVALIDATING", actor="runner", expected_from="PENDING_APPROVAL")
        transition(self.conn, pid, "CANCELLED_REVALIDATION", actor="runner", reason="stale_underlying", expected_from="REVALIDATING")

    def test_restart_idempotent_init(self):
        db.init_db(self._tmp.name)
        conn2 = db.connect(self._tmp.name)
        names = {r["name"] for r in conn2.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        conn2.close()
        for table in ("pe_experiments", "pe_order_proposals", "pe_proposal_events", "pe_paper_fills"):
            self.assertIn(table, names)

    def test_kill_switch_wins_over_timer(self):
        eid = self._experiment()
        set_kill_switch(self.conn, eid, "GLOBAL", None, enabled=False)
        self.assertTrue(kill_switch_active(self.conn, eid))

    def test_globally_unique_kill_switch(self):
        eid = self._experiment()
        set_kill_switch(self.conn, eid, "GLOBAL", None, enabled=False)
        set_kill_switch(self.conn, eid, "GLOBAL", None, enabled=True)
        rows = self.conn.execute("SELECT COUNT(*) n FROM pe_auto_switches WHERE experiment_id=? AND scope='GLOBAL'", (eid,)).fetchone()["n"]
        self.assertEqual(rows, 1)

    def test_auto_mode_filtering(self):
        eid = self._experiment()
        auto_pid = self._proposal(eid, key="auto", expires=-1, mode=AUTO_MODE)
        approval_pid = self._proposal(eid, key="approval", expires=-1, mode="APPROVAL_REQUIRED")
        due = {d["id"] for d in due_proposals(self.conn, _iso(0))}
        self.assertIn(auto_pid, due)
        self.assertNotIn(approval_pid, due)

    def test_atomic_due_proposal_claiming(self):
        eid = self._experiment()
        pid = self._proposal(eid, key="claim", expires=-1)
        first = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertTrue(first["claimed"])
        second = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertFalse(second["claimed"])
        self.assertEqual(second["reason"], "RACE_LOST_OR_NOT_DUE")

    def test_claim_rejects_non_auto_mode(self):
        eid = self._experiment()
        pid = self._proposal(eid, key="m", expires=-1, mode="APPROVAL_REQUIRED")
        out = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertFalse(out["claimed"])
        self.assertEqual(out["reason"], "NOT_AUTO_MODE")

    def test_claim_rejects_not_very_high(self):
        eid = self._experiment()
        pid = self._proposal(eid, key="v", expires=-1, very_high=False)
        out = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertEqual(out["reason"], "NOT_VERY_HIGH")

    def test_claim_rejects_not_allowed_action(self):
        eid = self._experiment()
        pid = self._proposal(eid, key="a", expires=-1, action="open")
        out = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertEqual(out["reason"], "ACTION_NOT_AUTO_ALLOWED")

    def test_claim_rejects_inactive_experiment(self):
        eid = self._experiment()
        pid = self._proposal(eid, key="e", expires=-1)
        self.conn.execute("UPDATE pe_experiments SET status='PAUSED' WHERE id=?", (eid,))
        self.conn.commit()
        out = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertEqual(out["reason"], "EXPERIMENT_NOT_ACTIVE")

    def test_claim_rejects_kill_switch(self):
        eid = self._experiment()
        pid = self._proposal(eid, key="k", expires=-1)
        set_kill_switch(self.conn, eid, "GLOBAL", None, enabled=False)
        out = claim_due_proposal(self.conn, pid, _iso(0))
        self.assertEqual(out["reason"], "KILL_SWITCH_ACTIVE")


if __name__ == "__main__":
    unittest.main()
