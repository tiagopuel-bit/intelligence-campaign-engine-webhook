"""Tests for the "last real event" tracking fix (DEEPSEEK_LAST_EVENT_FIX_TASK).

Verifies that `recent_event` surfaces the true most-recent non-empty named
event (with its bar time and close) rather than the latest bar's often-empty
event, in both the receiver state shape and the bracket-suggestion state
loader (whose support/resistance derivation depends on it).
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

import webhook_receiver
from paper_execution.bracket_suggestions import load_campaign_states


def _alerts_db(bars, symbol="U"):
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    conn = sqlite3.connect(f.name)
    conn.executescript("""
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, timeframe TEXT,
            phase TEXT, health INTEGER, score INTEGER, confidence INTEGER,
            momentum TEXT, status TEXT, action TEXT, exhaustion_warning INTEGER,
            reload_quality TEXT, htf_phase TEXT, campaign_alignment TEXT,
            last_fail_type TEXT, close REAL, bar_event TEXT, bar_time TEXT,
            rsi REAL, ema21_distance_atr REAL, session TEXT, active_trade INTEGER,
            active_entry REAL, active_stop REAL, active_target REAL,
            active_trade_source TEXT, active_trade_open_pct REAL,
            source TEXT NOT NULL DEFAULT 'live_webhook', received_at TEXT NOT NULL
        );
        CREATE TABLE watch_state (
            symbol TEXT, timeframe TEXT, signal_event TEXT, signal_extension_label TEXT,
            next_event_after_signal TEXT, signal_time TEXT
        );
    """)
    for b in bars:
        conn.execute(
            "INSERT INTO alerts (symbol,timeframe,phase,momentum,health,confidence,bar_event,close,exhaustion_warning,rsi,ema21_distance_atr,bar_time,source,received_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (symbol, b["timeframe"], "WAIT", "OFF", 50, 50, b.get("event"),
             b["close"], 0, None, None, b["bar_time"], b.get("source", "live_webhook"),
             b.get("received_at", "2026-01-01T00:00:00")),
        )
    conn.commit()
    conn.close()
    return f.name


class ReceiverLastEventTests(unittest.TestCase):
    def test_picks_most_recent_non_empty_event(self):
        # latest bar has no event; an older bar has RELOAD; an even older ADD.
        db = _alerts_db([
            {"timeframe": "30", "event": None, "close": 45.5, "bar_time": 3000},
            {"timeframe": "30", "event": "RELOAD", "close": 45.0, "bar_time": 2000},
            {"timeframe": "30", "event": "ADD", "close": 44.5, "bar_time": 1000},
        ])
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ev, ev_time, ev_close = webhook_receiver._last_real_event(conn, "U", "30")
            conn.close()
            self.assertEqual(ev, "RELOAD")
            self.assertEqual(ev_time, "2000")
            self.assertEqual(ev_close, 45.0)
        finally:
            Path(db).unlink(missing_ok=True)

    def test_shape_state_surfaces_event_name_time_and_close(self):
        db = _alerts_db([
            {"timeframe": "30", "event": "PEAK", "close": 46.0, "bar_time": 2000},
        ])
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            latest = conn.execute(
                "SELECT * FROM alerts WHERE symbol='U' AND timeframe='30' "
                "ORDER BY CAST(bar_time AS INTEGER) DESC LIMIT 1").fetchone()
            ev, ev_time, ev_close = webhook_receiver._last_real_event(conn, "U", "30")
            shape = webhook_receiver._shape_state("U", "30", latest, None, ev, ev_time, ev_close)
            conn.close()
            self.assertEqual(shape["recent_event"], "PEAK")
            self.assertEqual(shape["recent_event_time"], "2000")
            self.assertEqual(shape["recent_event_close"], 46.0)
        finally:
            Path(db).unlink(missing_ok=True)

    def test_no_event_returns_none(self):
        db = _alerts_db([
            {"timeframe": "30", "event": None, "close": 45.5, "bar_time": 1000},
        ])
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ev, ev_time, ev_close = webhook_receiver._last_real_event(conn, "U", "30")
            conn.close()
            self.assertIsNone(ev)
            self.assertIsNone(ev_time)
            self.assertIsNone(ev_close)
        finally:
            Path(db).unlink(missing_ok=True)

    def test_backfill_replay_event_never_surfaces(self):
        # A symbol/timeframe with ONLY backfill-reconstructed events (never a
        # real TradingView alert) must report no recent event at all --
        # surfacing a reconstruction as "last event, X ago" is exactly the
        # fabrication this filter exists to prevent.
        db = _alerts_db([
            {"timeframe": "60", "event": "RELOAD", "close": 772.6, "bar_time": 5000,
             "source": "backfill_replay"},
            {"timeframe": "60", "event": "MANAGE", "close": 757.67, "bar_time": 1000,
             "source": "backfill_replay"},
        ], symbol="SPY")
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ev, ev_time, ev_close = webhook_receiver._last_real_event(conn, "SPY", "60")
            conn.close()
            self.assertIsNone(ev)
            self.assertIsNone(ev_time)
            self.assertIsNone(ev_close)
        finally:
            Path(db).unlink(missing_ok=True)

    def test_live_event_wins_over_more_recent_backfill_event(self):
        # A newer backfill_replay row must not outrank an older but genuinely
        # live-confirmed one.
        db = _alerts_db([
            {"timeframe": "60", "event": "RELOAD", "close": 772.6, "bar_time": 5000,
             "source": "backfill_replay"},
            {"timeframe": "60", "event": "ADD", "close": 750.0, "bar_time": 2000,
             "source": "live_webhook"},
        ], symbol="SPY")
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ev, ev_time, ev_close = webhook_receiver._last_real_event(conn, "SPY", "60")
            conn.close()
            self.assertEqual(ev, "ADD")
            self.assertEqual(ev_time, "2000")
            self.assertEqual(ev_close, 750.0)
        finally:
            Path(db).unlink(missing_ok=True)


class BracketSuggestionLoaderTests(unittest.TestCase):
    def test_loader_uses_true_last_event_and_its_close(self):
        db = _alerts_db([
            {"timeframe": "30", "event": None, "close": 45.5, "bar_time": 3000},
            {"timeframe": "30", "event": "RELOAD", "close": 45.0, "bar_time": 2000},
            {"timeframe": "60", "event": "PEAK", "close": 46.3, "bar_time": 2500},
        ], symbol="U")
        try:
            states = load_campaign_states(db, "U")
            by_tf = {s.timeframe: s for s in states}
            # 30m: latest bar has no event, true last event is RELOAD@45.0
            self.assertEqual(by_tf["30"].recent_event, "RELOAD")
            self.assertEqual(by_tf["30"].recent_support_price, 45.0)
            # 60m: true last event is PEAK@46.3
            self.assertEqual(by_tf["60"].recent_event, "PEAK")
            self.assertEqual(by_tf["60"].recent_resistance_price, 46.3)
        finally:
            Path(db).unlink(missing_ok=True)

    def test_loader_never_surfaces_backfill_only_event(self):
        db = _alerts_db([
            {"timeframe": "60", "event": "RELOAD", "close": 772.6, "bar_time": 5000,
             "source": "backfill_replay"},
        ], symbol="SPY")
        try:
            states = load_campaign_states(db, "SPY")
            by_tf = {s.timeframe: s for s in states}
            self.assertEqual(by_tf["60"].recent_event, "")
            self.assertIsNone(by_tf["60"].recent_support_price)
            self.assertIsNone(by_tf["60"].recent_resistance_price)
        finally:
            Path(db).unlink(missing_ok=True)


class DnaContextTests(unittest.TestCase):
    """`_dna_context` (positions/<id>/insight, position detail) was missed by
    the original last-real-event fix -- it called `_shape_state` without
    `last_event` at all, silently falling back to the latest bar's own
    (possibly empty, possibly backfill) event. Covers both bugs together."""

    def test_picks_true_last_live_event_not_latest_bars_own(self):
        db = _alerts_db([
            {"timeframe": "60", "event": None, "close": 45.5, "bar_time": 3000,
             "received_at": "2026-01-01T00:00:03"},
            {"timeframe": "60", "event": "RELOAD", "close": 45.0, "bar_time": 2000,
             "received_at": "2026-01-01T00:00:02"},
        ], symbol="SPY")
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ctx = webhook_receiver._dna_context(conn, "SPY", "2026-01-01T00:00:00")
            conn.close()
            state = ctx["states"][0]
            self.assertEqual(state["recent_event"], "RELOAD")
            self.assertEqual(state["recent_event_close"], 45.0)
        finally:
            Path(db).unlink(missing_ok=True)

    def test_backfill_only_event_never_surfaces(self):
        db = _alerts_db([
            {"timeframe": "60", "event": "RELOAD", "close": 772.6, "bar_time": 5000,
             "source": "backfill_replay", "received_at": "2026-01-01T00:00:05"},
        ], symbol="SPY")
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ctx = webhook_receiver._dna_context(conn, "SPY", "2026-01-01T00:00:00")
            conn.close()
            state = ctx["states"][0]
            self.assertIsNone(state["recent_event"])
        finally:
            Path(db).unlink(missing_ok=True)

    def test_event_before_position_opened_excluded(self):
        db = _alerts_db([
            {"timeframe": "60", "event": "RELOAD", "close": 45.0, "bar_time": 1000,
             "received_at": "2025-12-31T23:59:00"},
            {"timeframe": "60", "event": None, "close": 46.0, "bar_time": 2000,
             "received_at": "2026-01-01T00:00:01"},
        ], symbol="SPY")
        try:
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            ctx = webhook_receiver._dna_context(conn, "SPY", "2026-01-01T00:00:00")
            conn.close()
            state = ctx["states"][0]
            self.assertIsNone(state["recent_event"])
        finally:
            Path(db).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
