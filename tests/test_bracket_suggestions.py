"""Tests for DNA-suggested protective brackets (TP/SL recommendation build).

Covers the pure level computation (support/resistance picking, cap clamp,
option-native floor/lookback, target priority), the suggestion builders
(initial share/option, trailing stop/target, exit-signal refusal), the webhook
state loader, and an end-to-end trigger that creates a real set_bracket
proposal with the fatigue guards.
"""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from decision_engine import CampaignState, Phase, Momentum
from paper_execution import db
from paper_execution.bracket_suggestions import (
    TARGET_RR,
    cap_clamp_stop,
    exit_signal_active,
    load_campaign_states,
    maybe_suggest_brackets,
    nearest_resistance,
    option_native_levels,
    suggest_initial_option,
    suggest_initial_share,
    suggest_trailing_stop_update,
    suggest_trailing_target_update,
    target_price,
    tightest_support,
)
from paper_execution.store import (
    create_experiment,
    frozen_goal_hash,
    upsert_bracket,
)


def _iso(offset_seconds=0):
    return datetime.now(timezone.utc).isoformat()


def _state(tf, support=None, resistance=None, recent_event="", next_ev=None):
    return CampaignState(
        symbol="AMC", timeframe=tf, phase=Phase.WAIT, momentum=Momentum.FADING,
        health=50, confidence=50, recent_event=recent_event,
        recent_support_price=support, recent_resistance_price=resistance,
        next_event_after_signal=next_ev,
    )


class LevelPickTests(unittest.TestCase):
    def test_tightest_support_is_highest_valid_below_price(self):
        states = [_state("15", support=2.30), _state("60", support=2.35),
                  _state("240", support=2.50), _state("1D", support=2.60)]
        stop, tfs = tightest_support(states, current_price=2.44)
        self.assertEqual(stop, 2.35)
        self.assertEqual(tfs, ["60"])
        # a level above price is not valid support
        stop2, _ = tightest_support([_state("5", support=2.48)], 2.44)
        self.assertIsNone(stop2)

    def test_nearest_resistance_is_lowest_valid_above_price(self):
        states = [_state("15", resistance=2.60), _state("60", resistance=2.50),
                  _state("240", resistance=3.00)]
        res, tfs = nearest_resistance(states, 2.44)
        self.assertEqual(res, 2.50)
        self.assertEqual(tfs, ["60"])
        self.assertIsNone(nearest_resistance([_state("5", resistance=2.40)], 2.44)[0])

    def test_no_levels(self):
        self.assertIsNone(tightest_support([], 2.44)[0])
        self.assertIsNone(nearest_resistance([], 2.44)[0])


class CapClampTests(unittest.TestCase):
    def test_clamps_wide_stop_to_single_contract_cap(self):
        # qty=100 shares at 2.44 -> notional 244; 15% of TPV(100) = 15
        # max distance = 15/244 = 0.0615 -> floor ~2.3785
        stop = cap_clamp_stop(2.20, 2.44, qty=100, tpv=100, contracts_mult=1.0)
        self.assertGreater(stop, 2.37)
        self.assertLessEqual(stop, 2.44)

    def test_keeps_close_stop_within_cap(self):
        stop = cap_clamp_stop(2.42, 2.44, qty=100, tpv=100, contracts_mult=1.0)
        self.assertEqual(stop, 2.42)

    def test_option_notional_uses_100_multiplier(self):
        # 2 contracts at 1.14 -> notional 228; 15% of TPV(100) = 15 -> dist 0.0658
        stop = cap_clamp_stop(0.50, 1.14, qty=2, tpv=100, contracts_mult=100.0)
        self.assertGreater(stop, 1.07)

    def test_no_clamp_without_positive_notional(self):
        self.assertEqual(cap_clamp_stop(2.20, 2.44, qty=0, tpv=100), 2.20)


class OptionNativeTests(unittest.TestCase):
    def test_insufficient_history_fails_closed(self):
        support, resistance, ok, reason = option_native_levels([1.0] * 10, 1.14)
        self.assertFalse(ok)
        self.assertIn("insufficient", reason)

    def test_uses_20_bar_lookback_from_own_series(self):
        closes = [1.0] * 20 + [1.2] * 10 + [0.9] * 10  # last 20: high 1.2, low 0.9
        support, resistance, ok, reason = option_native_levels(closes, current_price=1.14)
        self.assertTrue(ok)
        self.assertEqual(support, 0.9)
        self.assertEqual(resistance, 1.2)

    def test_levels_require_side_relative_to_price(self):
        closes = [1.5] * 40  # all above current 1.14
        support, resistance, ok, _ = option_native_levels(closes, 1.14)
        self.assertIsNone(support)
        self.assertEqual(resistance, 1.5)


class TargetPriorityTests(unittest.TestCase):
    def test_resistance_then_breakeven_then_rr(self):
        states = [_state("60", resistance=2.60)]
        self.assertEqual(target_price(states, 2.44, breakeven=2.5, stop=2.4)[0], 2.60)
        self.assertEqual(target_price([], 2.44, breakeven=2.5, stop=2.4), (2.5, "breakeven"))
        target, src = target_price([], 2.44, breakeven=None, stop=2.40)
        self.assertAlmostEqual(target, 2.44 + TARGET_RR * 0.04)
        self.assertEqual(src, "rr_2.2")
        self.assertEqual(target_price([], 2.44, breakeven=None, stop=None), (None, None))


class SuggestionBuilderTests(unittest.TestCase):
    def test_initial_share_happy_path(self):
        states = [_state("5", support=2.405, recent_event="RELOAD"),
                  _state("60", support=2.42, recent_event="ADD")]
        suggestion = suggest_initial_share(states, 2.44, qty=100, tpv=1000)
        self.assertIsNotNone(suggestion)
        self.assertEqual(suggestion["kind"], "INITIAL")
        self.assertEqual(suggestion["stop_price"], 2.42)  # tightest support
        self.assertIn("stop", suggestion["reason"])

    def test_initial_share_refuses_on_exit_signal(self):
        states = [_state("5", support=2.405, recent_event="RELOAD")]
        self.assertIsNone(suggest_initial_share(states, 2.44, qty=100, tpv=1000, exit_signal=True))

    def test_initial_share_fail_closed_without_support(self):
        self.assertIsNone(suggest_initial_share([], 2.44, qty=100, tpv=1000))

    def test_initial_option_insufficient_history(self):
        out = suggest_initial_option([1.0] * 5, 1.14, qty=2, tpv=100)
        self.assertEqual(out["outcome"], "NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY")

    def test_initial_option_native_levels(self):
        closes = [1.0] * 20 + [0.8] * 10 + [1.2] * 10  # last 20: low 0.8, high 1.2
        out = suggest_initial_option(closes, 1.14, qty=2, tpv=1000, breakeven=1.2)
        self.assertEqual(out["kind"], "INITIAL_OPTION")
        self.assertEqual(out["stop_price"], 0.8)
        self.assertEqual(out["target_price"], 1.2)
        self.assertEqual(out["freshness"], "DELAYED")

    def test_trailing_stop_is_raise_only(self):
        states = [_state("60", support=2.42, recent_event="ADD")]
        up = suggest_trailing_stop_update(states, 2.44, current_stop=2.30)
        self.assertEqual(up["stop_price"], 2.42)
        # never lowers
        self.assertIsNone(suggest_trailing_stop_update(states, 2.44, current_stop=2.50))
        # refuses on exit signal
        self.assertIsNone(suggest_trailing_stop_update(states, 2.44, current_stop=2.30, exit_signal=True))

    def test_trailing_target_is_raise_only(self):
        states = [_state("60", resistance=2.60, recent_event="PEAK")]
        up = suggest_trailing_target_update(states, 2.44, current_target=2.50)
        self.assertEqual(up["target_price"], 2.60)
        self.assertIsNone(suggest_trailing_target_update(states, 2.44, current_target=2.70))

    def test_exit_signal_gate_from_fail_cluster(self):
        fails = [_state(f, recent_event="FAIL", next_ev=None) for f in ("15", "30", "60")]
        self.assertTrue(exit_signal_active(fails))
        self.assertFalse(exit_signal_active([_state("15", recent_event="FAIL")]))


class _DBSetupMixin:
    def _new_db(self):
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        db.init_db(f.name)
        return f.name

    def _experiment(self, conn, status="ACTIVE"):
        return create_experiment(
            conn, version=1, symbol="AMC", start_at=_iso(), end_at="2027-01-31T16:00:00-08:00",
            starting_cash=100.0, starting_value_method="marked_market_value",
            target_value_jan2027=15000.0, target_return_pct=None, max_drawdown_pct=25.0,
            max_amc_exposure=0.70, max_exposure_per_option_expiry=0.25,
            deposit_policy="ALLOWED_TRACKED_SEPARATELY", allowed_actions="hold,add,open,partial_reduce,close,roll",
            benchmark_symbol="AMC", benchmark_success_criteria="beat buy-and-hold",
            min_observation_count=30, max_daily_paper_loss=0.05, max_orders_per_day=3,
            max_consecutive_failed_proposals=3, milestones_json="[]",
            amc_target_floor_pct=30.0, confidence_status="INTACT", contract_sha256=frozen_goal_hash(),
        )

    def _paper_position(self, conn, eid, qty=100.0, ticker="AMC", itype="SHARE", symbol="AMC"):
        conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?)",
            (eid, symbol, itype, ticker, qty, _iso()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO pe_paper_cash (experiment_id, cash, updated_at) VALUES (?,?,?)",
            (eid, 100.0, _iso()),
        )
        conn.commit()

    def _webhook_db(self, bars=None, watch=None):
        f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        f.close()
        conn = __import__("sqlite3").connect(f.name)
        conn.executescript("""
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, timeframe TEXT,
                phase TEXT, momentum TEXT, health INTEGER, confidence INTEGER,
                bar_event TEXT, close REAL, exhaustion_warning INTEGER,
                rsi REAL, ema21_distance_atr REAL, bar_time INTEGER, received_at TEXT
            );
            CREATE TABLE watch_state (
                symbol TEXT, timeframe TEXT, signal_event TEXT, signal_extension_label TEXT,
                next_event_after_signal TEXT, signal_time TEXT
            );
        """)
        for bar in bars or []:
            conn.execute(
                "INSERT INTO alerts (symbol,timeframe,phase,momentum,health,confidence,bar_event,close,exhaustion_warning,rsi,ema21_distance_atr,bar_time,received_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (bar["symbol"], bar["timeframe"], bar.get("phase", "WAIT"), bar.get("momentum", "OFF"),
                 bar.get("health", 50), bar.get("confidence", 50), bar.get("event"),
                 bar.get("close"), 0, None, None, bar.get("bar_time"), _iso()),
            )
        conn.commit()
        conn.close()
        return f.name


class StateLoaderTests(_DBSetupMixin, unittest.TestCase):
    def test_load_campaign_states_sets_support_and_resistance(self):
        wb = self._webhook_db([
            {"symbol": "AMC", "timeframe": "5", "event": "RELOAD", "close": 2.405, "bar_time": 1000},
            {"symbol": "AMC", "timeframe": "60", "event": "PEAK", "close": 2.55, "bar_time": 2000},
            {"symbol": "AMC", "timeframe": "15", "event": None, "close": 2.44, "bar_time": 3000},
        ])
        try:
            states = load_campaign_states(wb, "AMC")
            by_tf = {s.timeframe: s for s in states}
            self.assertEqual(by_tf["5"].recent_support_price, 2.405)
            self.assertEqual(by_tf["60"].recent_resistance_price, 2.55)
            self.assertIsNone(by_tf["15"].recent_support_price)
        finally:
            Path(wb).unlink(missing_ok=True)


class TriggerTests(_DBSetupMixin, unittest.TestCase):
    def _paper_with_share(self):
        pd = self._new_db()
        conn = db.connect(pd)
        eid = self._experiment(conn)
        self._paper_position(conn, eid, qty=100, ticker="AMC", itype="SHARE")
        conn.close()
        return pd, eid

    def test_creates_initial_set_bracket_proposal(self):
        pd, eid = self._paper_with_share()
        wb = self._webhook_db([
            {"symbol": "AMC", "timeframe": "5", "event": "RELOAD", "close": 2.405, "bar_time": 1000},
            {"symbol": "AMC", "timeframe": "15", "event": None, "close": 2.44, "bar_time": 2000},
        ])
        try:
            results = maybe_suggest_brackets(
                pd, wb, price_provider=lambda s, t: {"close": 2.44})
            self.assertEqual(len(results), 1)
            row = results[0]
            self.assertEqual(row["kind"], "INITIAL")
            self.assertEqual(row["stop_price"], 2.405)
            conn = db.connect(pd)
            prop = conn.execute(
                "SELECT action, mode, current_status, position_ref, stop_price, target_price "
                "FROM pe_order_proposals WHERE id=?", (row["proposal_id"],)).fetchone()
            conn.close()
            self.assertEqual(prop["action"], "set_bracket")
            self.assertEqual(prop["mode"], "APPROVAL_REQUIRED")
            self.assertEqual(prop["current_status"], "PENDING_APPROVAL")
            self.assertEqual(prop["position_ref"], "AMC")
            self.assertEqual(prop["stop_price"], 2.405)
        finally:
            Path(pd).unlink(missing_ok=True)
            Path(wb).unlink(missing_ok=True)

    def test_no_active_experiment_no_suggestions(self):
        pd = self._new_db()
        conn = db.connect(pd)
        eid = self._experiment(conn)
        conn.execute("UPDATE pe_experiments SET status='PAUSED' WHERE id=?", (eid,))
        self._paper_position(conn, eid, qty=100, ticker="AMC", itype="SHARE")
        conn.close()
        wb = self._webhook_db([{"symbol": "AMC", "timeframe": "5", "event": "RELOAD", "close": 2.405, "bar_time": 1000}])
        try:
            self.assertEqual(maybe_suggest_brackets(pd, wb, price_provider=lambda s, t: {"close": 2.44}), [])
        finally:
            Path(pd).unlink(missing_ok=True)
            Path(wb).unlink(missing_ok=True)

    def test_dedup_same_day_no_duplicate_proposal(self):
        pd, _ = self._paper_with_share()
        wb = self._webhook_db([{"symbol": "AMC", "timeframe": "5", "event": "RELOAD", "close": 2.405, "bar_time": 1000}])
        try:
            r1 = maybe_suggest_brackets(pd, wb, price_provider=lambda s, t: {"close": 2.44})
            r2 = maybe_suggest_brackets(pd, wb, price_provider=lambda s, t: {"close": 2.44})
            self.assertEqual(len(r1), 1)
            # second call is suppressed by the outstanding-proposal guard
            self.assertEqual(r2, [])
            conn = db.connect(pd)
            n = conn.execute("SELECT COUNT(*) n FROM pe_order_proposals").fetchone()["n"]
            conn.close()
            self.assertEqual(n, 1)
        finally:
            Path(pd).unlink(missing_ok=True)
            Path(wb).unlink(missing_ok=True)

    def test_option_without_history_fails_closed(self):
        pd = self._new_db()
        conn = db.connect(pd)
        eid = self._experiment(conn)
        self._paper_position(conn, eid, qty=2, ticker="O:AMC26918C00001500", itype="CALL")
        conn.close()
        wb = self._webhook_db([])
        try:
            # no option price and no option history -> no suggestion, no crash
            results = maybe_suggest_brackets(pd, wb, price_provider=lambda s, t: None)
            self.assertEqual(results, [])
            # DELAYED option history available but too thin -> fail-closed outcome
            results = maybe_suggest_brackets(
                pd, wb, price_provider=lambda s, t: {"close": 1.14},
                option_closes={"O:AMC26918C00001500": [1.0] * 10})
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["outcome"], "NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY")
        finally:
            Path(pd).unlink(missing_ok=True)
            Path(wb).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
