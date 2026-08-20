"""Tests for the Unified Relay receiver half (DEEPSEEK_UNIFIED_RELAY_RECEIVER_TASK).

Covers: a batched `events` payload creates rows in the real `alerts` table
(not alerts_relay) tagged `source='live_relay'` and retrievable via
`_last_real_event`; an events-less payload only records the heartbeat; source
precedence keeps `live_webhook`/`live_relay` live while `backfill_replay` and
unrecognized sources never count; native + old alerts_relay paths unchanged.
"""
import os
import sys
import tempfile
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webhook_receiver
from webhook_receiver import app, init_db

TEST_SECRET = "test-manual-secret"
TEST_STATE_TOKEN = "test-state-token"


def _now_ms():
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _relay_payload(symbol="TEST", with_events=True):
    payload = {
        "kind": "UNDERLYING_HEARTBEAT",
        "symbol": symbol,
        "ticker": "BATS:" + symbol,
        "timeframe": "1",
        "time": _now_ms(),
        "close": 2.35,
        "session": "RTH",
    }
    if with_events:
        payload["events"] = [
            {"timeframe": "60", "event": "EXPANSION", "time": _now_ms() - 60000,
             "close": 2.35, "phase": "EXPANSION"},
            {"timeframe": "240", "event": "WAIT", "time": _now_ms() - 60000,
             "close": 2.34, "phase": "WAIT"},
        ]
    return payload


class UnifiedRelayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmpfile.close()
        cls._original_db = webhook_receiver.DB_PATH
        webhook_receiver.DB_PATH = Path(cls._tmpfile.name)
        cls._original_secret = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = TEST_SECRET
        cls._original_state_token = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN
        init_db()
        app.config["TESTING"] = True
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        webhook_receiver.DB_PATH = cls._original_db
        webhook_receiver.WEBHOOK_SECRET = cls._original_secret
        webhook_receiver.STATE_API_TOKEN = cls._original_state_token
        try:
            os.unlink(cls._tmpfile.name)
        except OSError:
            pass
        for sidecar in ("-journal", "-wal", "-shm"):
            try:
                os.unlink(cls._tmpfile.name + sidecar)
            except OSError:
                pass

    def _post(self, payload):
        return self.client.post(
            "/webhook", data=json.dumps(payload),
            headers={"Content-Type": "application/json", "X-Webhook-Secret": TEST_SECRET},
        )

    def test_events_create_alerts_rows_with_live_relay_source(self):
        resp = self._post(_relay_payload("TEST"))
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["events_stored"], 2)
        conn = webhook_receiver.get_db()
        rows = conn.execute(
            "SELECT timeframe, bar_event, source FROM alerts WHERE symbol='TEST' "
            "AND source='live_relay' ORDER BY timeframe"
        ).fetchall()
        conn.close()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["timeframe"], "240")
        self.assertEqual(rows[1]["timeframe"], "60")
        self.assertEqual(rows[0]["bar_event"], "WAIT")
        self.assertEqual(rows[1]["bar_event"], "EXPANSION")
        # heartbeat was also recorded
        conn = webhook_receiver.get_db()
        hb = conn.execute(
            "SELECT close FROM underlying_heartbeats WHERE symbol='TEST' ORDER BY bar_time DESC LIMIT 1"
        ).fetchone()
        conn.close()
        self.assertEqual(hb["close"], 2.35)

    def test_no_events_only_records_heartbeat(self):
        resp = self._post(_relay_payload("TEST2", with_events=False))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["events_stored"], 0)
        conn = webhook_receiver.get_db()
        n = conn.execute("SELECT COUNT(*) n FROM alerts WHERE symbol='TEST2'").fetchone()["n"]
        conn.close()
        self.assertEqual(n, 0)

    def test_last_real_event_prefers_live_relay_but_never_backfill(self):
        conn = webhook_receiver.get_db()
        conn.execute(
            "INSERT INTO alerts (symbol,timeframe,phase,bar_event,close,bar_time,source,received_at) "
            "VALUES ('TEST','60','EXPANSION','EXPANSION',2.35,100,'live_relay','now')"
        )
        conn.execute(
            "INSERT INTO alerts (symbol,timeframe,phase,bar_event,close,bar_time,source,received_at) "
            "VALUES ('TEST','60','EXPANSION','FAIL',2.40,200,'backfill_replay','now')"
        )
        conn.commit()
        ev, ev_time, ev_close = webhook_receiver._last_real_event(conn, "TEST", "60")
        # the newer backfill_replay row must NOT outrank the live_relay row
        self.assertEqual(ev, "EXPANSION")
        self.assertEqual(ev_close, 2.35)
        conn.close()

    def test_unrecognized_source_excluded(self):
        conn = webhook_receiver.get_db()
        conn.execute(
            "INSERT INTO alerts (symbol,timeframe,phase,bar_event,close,bar_time,source,received_at) "
            "VALUES ('TEST','15','EXPANSION','EXPANSION',2.35,300,'future_source','now')"
        )
        conn.commit()
        ev, _, _ = webhook_receiver._last_real_event(conn, "TEST", "15")
        self.assertIsNone(ev)
        conn.close()

    def test_native_alert_and_old_relay_path_unchanged(self):
        # native (no kind) still lands as live_webhook
        native = {
            "symbol": "TEST", "timeframe": "5", "phase": "EXPANSION",
            "health": 75, "score": 70, "confidence": 68, "momentum": "BUILDING",
            "status": "ACTIVE", "action": "BUILD", "exhaustion_warning": False,
            "reload_quality": "CLEAN", "htf_phase": "ACCUMULATION",
            "campaign_alignment": "ALIGNED", "last_fail_type": None,
            "close": 2.40, "rsi": 62.0, "ema21_distance_atr": 0.3,
            "session": "RTH", "time": _now_ms(), "active_trade": 0,
        }
        resp = self._post(native)
        self.assertEqual(resp.status_code, 200)
        conn = webhook_receiver.get_db()
        row = conn.execute(
            "SELECT source FROM alerts WHERE symbol='TEST' AND timeframe='5' AND source='live_webhook'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        # old relay path ("relay":true, no kind) still writes to alerts_relay
        old_relay = {"relay": True, "symbol": "TEST",
                     "events": [{"timeframe": "15", "phase": "EXPANSION", "close": 2.4, "time": _now_ms()}]}
        resp = self._post(old_relay)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["relay"])
        conn = webhook_receiver.get_db()
        n = conn.execute("SELECT COUNT(*) n FROM alerts_relay WHERE symbol='TEST'").fetchone()["n"]
        conn.close()
        self.assertEqual(n, 1)


if __name__ == "__main__":
    unittest.main()
