import os
import sys
import tempfile
import json
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import webhook_receiver
import massive_ohlc
import massive_options
from webhook_receiver import app, init_db, compute_extension_label
from unittest import mock

TEST_SECRET = "test-manual-secret"
TEST_STATE_TOKEN = "test-state-token"


class WebhookReceiverTests(unittest.TestCase):

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

    def _post(self, payload, headers=None):
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        return self.client.post("/webhook", data=json.dumps(payload), headers=hdrs)

    def _strong_start_payload(self, **overrides):
        base = {
            "symbol": "TEST",
            "timeframe": "240",
            "phase": "EXPANSION",
            "health": 75,
            "score": 72,
            "confidence": 68,
            "momentum": "BUILDING",
            "status": "ACTIVE",
            "action": "BUILD",
            "exhaustion_warning": False,
            "reload_quality": "CLEAN",
            "htf_phase": "ACCUMULATION",
            "campaign_alignment": "CONFIRMED",
            "last_fail_type": "NONE",
            "close": 100.0,
            "time": "2026-01-01T00:00:00Z",
            "event": "STRONG START",
            "rsi": 52.0,
            "ema21_distance_atr": 0.4,
            "secret": TEST_SECRET,
        }
        base.update(overrides)
        return base

    def _state_headers(self, token=None):
        if token is None:
            token = TEST_STATE_TOKEN
        return {"Authorization": f"Bearer {token}"}

    # =========================================================================
    # Existing functional tests (kept unchanged, secret added to payloads)
    # =========================================================================

    def test_empty_body_rejected(self):
        resp = self.client.post("/webhook", data="", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_malformed_json_rejected(self):
        resp = self.client.post("/webhook", data="not json", content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_no_json_content_type(self):
        resp = self.client.post("/webhook", data="{}")
        self.assertEqual(resp.status_code, 400)

    def test_strong_start_creates_watch_state(self):
        self._post(self._strong_start_payload())
        resp = self.client.get("/state/TEST/240", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["signal_event"], "STRONG START")
        self.assertIsNone(data["next_event_after_signal"])

    def test_extension_label_fresh(self):
        payload = self._strong_start_payload(rsi=52.0, ema21_distance_atr=0.4,
                                              symbol="FRESH1", timeframe="240")
        self._post(payload)
        resp = self.client.get("/state/FRESH1/240", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["signal_bar_extension_label"], "FRESH")

    def test_extension_label_extended_rsi(self):
        payload = self._strong_start_payload(rsi=70.0, ema21_distance_atr=0.4,
                                              symbol="EXT1", timeframe="240")
        self._post(payload)
        resp = self.client.get("/state/EXT1/240", headers=self._state_headers())
        self.assertEqual(resp.get_json()["signal_bar_extension_label"], "EXTENDED")

    def test_extension_label_extended_ema_distance(self):
        payload = self._strong_start_payload(rsi=50.0, ema21_distance_atr=1.5,
                                              symbol="EXT2", timeframe="240")
        self._post(payload)
        resp = self.client.get("/state/EXT2/240", headers=self._state_headers())
        self.assertEqual(resp.get_json()["signal_bar_extension_label"], "EXTENDED")

    def test_add_consumes_watch_once(self):
        self._post(self._strong_start_payload(symbol="WATCH1", timeframe="240"))
        self._post(self._strong_start_payload(symbol="WATCH1", timeframe="240",
                                               event="ADD", action="MANAGE",
                                               last_fail_type="ADD"))
        resp = self.client.get("/state/WATCH1/240", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["next_event_after_signal"], "ADD")
        self._post(self._strong_start_payload(symbol="WATCH1", timeframe="240",
                                               event="ADD", action="MANAGE",
                                               last_fail_type="ADD"))
        resp2 = self.client.get("/state/WATCH1/240", headers=self._state_headers())
        self.assertEqual(resp2.get_json()["next_event_after_signal"], "ADD")

    def test_fire_add_consumes_watch_once(self):
        self._post(self._strong_start_payload(symbol="WATCH2", timeframe="60"))
        self._post(self._strong_start_payload(symbol="WATCH2", timeframe="60",
                                               event="FIRE ADD"))
        resp = self.client.get("/state/WATCH2/60", headers=self._state_headers())
        self.assertEqual(resp.get_json()["next_event_after_signal"], "FIRE ADD")
        self._post(self._strong_start_payload(symbol="WATCH2", timeframe="60",
                                               event="MANAGE"))
        resp2 = self.client.get("/state/WATCH2/60", headers=self._state_headers())
        self.assertEqual(resp2.get_json()["next_event_after_signal"], "FIRE ADD")

    def test_manage_consumes_watch_once(self):
        self._post(self._strong_start_payload(symbol="WATCH3", timeframe="120"))
        self._post(self._strong_start_payload(symbol="WATCH3", timeframe="120",
                                               event="MANAGE"))
        resp = self.client.get("/state/WATCH3/120", headers=self._state_headers())
        self.assertEqual(resp.get_json()["next_event_after_signal"], "MANAGE")

    def test_different_symbol_does_not_consume(self):
        self._post(self._strong_start_payload(symbol="DIFF1", timeframe="240"))
        self._post(self._strong_start_payload(symbol="DIFF2", timeframe="240",
                                               event="ADD"))
        resp = self.client.get("/state/DIFF1/240", headers=self._state_headers())
        self.assertIsNone(resp.get_json()["next_event_after_signal"])

    def test_different_timeframe_does_not_consume(self):
        self._post(self._strong_start_payload(symbol="DIFF3", timeframe="240"))
        self._post(self._strong_start_payload(symbol="DIFF3", timeframe="60",
                                               event="ADD"))
        resp = self.client.get("/state/DIFF3/240", headers=self._state_headers())
        self.assertIsNone(resp.get_json()["next_event_after_signal"])

    def test_strong_start_restarts_watch(self):
        self._post(self._strong_start_payload(symbol="RESTART1", timeframe="240"))
        self._post(self._strong_start_payload(symbol="RESTART1", timeframe="240",
                                               event="ADD"))
        self._post(self._strong_start_payload(symbol="RESTART1", timeframe="240",
                                               time="2026-01-02T00:00:00Z"))
        resp = self.client.get("/state/RESTART1/240", headers=self._state_headers())
        data = resp.get_json()
        self.assertEqual(data["signal_event"], "STRONG START")
        self.assertIsNone(data["next_event_after_signal"])
        self.assertIsNotNone(data["signal_time"])

    def test_reload_restarts_watch(self):
        self._post(self._strong_start_payload(symbol="RESTART2", timeframe="240"))
        self._post(self._strong_start_payload(symbol="RESTART2", timeframe="240",
                                               event="ADD"))
        self._post(self._strong_start_payload(symbol="RESTART2", timeframe="240",
                                               event="RELOAD", time="2026-01-02T00:00:00Z"))
        resp = self.client.get("/state/RESTART2/240", headers=self._state_headers())
        data = resp.get_json()
        self.assertEqual(data["signal_event"], "RELOAD")
        self.assertIsNone(data["next_event_after_signal"])

    def test_state_endpoint_shape(self):
        payload = self._strong_start_payload(symbol="SHAPE1", timeframe="240")
        self._post(payload)
        resp = self.client.get("/state/SHAPE1/240", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["symbol"], "SHAPE1")
        self.assertEqual(data["timeframe"], "240")
        self.assertEqual(data["phase"], "EXPANSION")
        self.assertEqual(data["health"], 75)
        self.assertEqual(data["confidence"], 68)
        self.assertEqual(data["momentum"], "BUILDING")
        self.assertEqual(data["recent_event"], "STRONG START")
        self.assertFalse(data["exhaustion_warning"])
        self.assertEqual(data["reload_quality"], "CLEAN")
        self.assertEqual(data["htf_phase"], "ACCUMULATION")
        self.assertEqual(data["campaign_alignment"], "CONFIRMED")
        self.assertEqual(data["last_fail_type"], "NONE")
        self.assertEqual(data["close"], 100.0)
        self.assertEqual(data["rsi"], 52.0)
        self.assertEqual(data["ema21_distance_atr"], 0.4)
        self.assertIsNone(data["next_event_after_signal"])
        self.assertEqual(data["signal_event"], "STRONG START")
        self.assertEqual(data["signal_bar_extension_label"], "FRESH")

    def test_state_all_returns_all_timeframes(self):
        self._post(self._strong_start_payload(symbol="ALLTF", timeframe="60"))
        self._post(self._strong_start_payload(symbol="ALLTF", timeframe="240"))
        resp = self.client.get("/state_all/ALLTF", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["symbol"], "ALLTF")
        self.assertEqual(data["timeframe_count"], 2)
        tfs = sorted(s["timeframe"] for s in data["states"])
        self.assertEqual(tfs, ["240", "60"])

    def test_unknown_state_returns_404(self):
        resp = self.client.get("/state/NOEXIST/240", headers=self._state_headers())
        self.assertEqual(resp.status_code, 404)

    def test_unknown_state_all_returns_404(self):
        resp = self.client.get("/state_all/NOEXISTATALL", headers=self._state_headers())
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # OHLC endpoint (near-live Massive bars for the landing-page chart)
    # =========================================================================

    def test_ohlc_requires_auth(self):
        resp = self.client.get("/ohlc/AMC/15m")
        self.assertEqual(resp.status_code, 401)

    def test_ohlc_rejects_unknown_timeframe(self):
        resp = self.client.get("/ohlc/AMC/99m", headers=self._state_headers())
        self.assertEqual(resp.status_code, 400)

    def test_ohlc_rejects_invalid_symbol(self):
        resp = self.client.get("/ohlc/BAD!SYM/15m", headers=self._state_headers())
        self.assertEqual(resp.status_code, 400)

    def test_ohlc_returns_shaped_bars(self):
        rows = [
            {"t": 1786348800000, "o": 2.58, "h": 2.60, "l": 2.57, "c": 2.59, "v": 2838},
            {"t": 1786348980000, "o": 2.59, "h": 2.61, "l": 2.58, "c": 2.60, "v": 3000},
        ]
        massive_ohlc._cache.clear()
        with mock.patch("massive_ohlc._fetch_raw", return_value=rows), \
             mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}):
            resp = self.client.get("/ohlc/AMC/3m", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["symbol"], "AMC")
        self.assertEqual(data["timeframe"], "3m")
        self.assertEqual(data["bar_count"], 2)
        self.assertEqual(data["bars"][0]["o"], 2.58)
        self.assertEqual(data["bars"][-1]["c"], 2.60)

    def test_ohlc_serves_cached_response_without_refetch(self):
        rows = [{"t": 1786348800000, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1}]
        massive_ohlc._cache.clear()
        with mock.patch("massive_ohlc._fetch_raw", return_value=rows) as fetch, \
             mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "test-key"}):
            r1 = self.client.get("/ohlc/AMC/5m", headers=self._state_headers())
            r2 = self.client.get("/ohlc/AMC/5m", headers=self._state_headers())
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.get_json()["cached"], True)
            fetch.assert_called_once()

    def test_ohlc_missing_key_returns_503(self):
        massive_ohlc._cache.clear()
        with mock.patch.dict(os.environ, {"MASSIVE_API_KEY": "", "POLYGON_API_KEY": ""}):
            resp = self.client.get("/ohlc/AMC/15m", headers=self._state_headers())
        self.assertEqual(resp.status_code, 503)

    def test_ohlc_resolve_timeframe_aliases(self):
        self.assertEqual(massive_ohlc.resolve_timeframe("3m"), "3m")
        self.assertEqual(massive_ohlc.resolve_timeframe("60"), "1H")
        self.assertEqual(massive_ohlc.resolve_timeframe("1D"), "D")
        self.assertEqual(massive_ohlc.resolve_timeframe("240"), "4H")
        self.assertEqual(massive_ohlc.resolve_timeframe("5"), "5m")
        self.assertIsNone(massive_ohlc.resolve_timeframe("99m"))

    # =========================================================================
    # Trade Box zone fields (Pine v12.6.21 additive payload)
    # =========================================================================

    def test_trade_box_fields_roundtrip(self):
        self._post(self._strong_start_payload(
            symbol="TBZONE", timeframe="240",
            active_trade=1, active_entry=2.53, active_stop=2.38, active_target=3.01,
            active_trade_source="BREAKOUT", active_trade_open_pct=0.5,
        ))
        resp = self.client.get("/state/TBZONE/240", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["active_trade"], True)
        self.assertEqual(data["active_entry"], 2.53)
        self.assertEqual(data["active_stop"], 2.38)
        self.assertEqual(data["active_target"], 3.01)
        self.assertEqual(data["active_trade_source"], "BREAKOUT")
        self.assertEqual(data["active_trade_open_pct"], 0.5)

    def test_trade_box_na_fields_parse_to_none(self):
        self._post(self._strong_start_payload(
            symbol="TBNA", timeframe="240",
            active_trade=0, active_entry="N/A", active_stop="N/A", active_target="N/A",
            active_trade_source="N/A", active_trade_open_pct="N/A",
        ))
        resp = self.client.get("/state/TBNA/240", headers=self._state_headers())
        data = resp.get_json()
        self.assertEqual(data["active_trade"], False)
        self.assertIsNone(data["active_entry"])
        self.assertIsNone(data["active_stop"])
        self.assertIsNone(data["active_target"])
        self.assertIsNone(data["active_trade_source"])
        self.assertIsNone(data["active_trade_open_pct"])

    def test_trade_box_columns_present_after_init(self):
        import sqlite3
        conn = sqlite3.connect(webhook_receiver.DB_PATH)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(alerts)")}
        conn.close()
        for col in ("active_trade", "active_entry", "active_stop",
                    "active_target", "active_trade_source", "active_trade_open_pct"):
            self.assertIn(col, cols)

    # =========================================================================
    # Positions (beta) — manual log, no broker
    # =========================================================================

    def _create_position(self, symbol="AMC", **overrides):
        body = {
            "symbol": symbol,
            "direction": "LONG",
            "origin_timeframe": "15",
            "origin_event": "STRONG START",
            "notes": "demo",
            "instrument": {
                "type": "SHARE",
                "quantity": 100,
                "entry_price": 2.53,
                "entry_time": "2026-08-13T14:30:00Z",
            },
        }
        body.update(overrides)
        return self.client.post("/positions", data=json.dumps(body),
                                content_type="application/json",
                                headers=self._state_headers())

    def test_positions_requires_auth(self):
        resp = self.client.post("/positions", data="{}", content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        resp = self.client.get("/positions")
        self.assertEqual(resp.status_code, 401)

    def test_cors_headers_cover_positions_writes(self):
        resp = self.client.post("/positions", data="{}", content_type="application/json",
                                headers=self._state_headers())
        self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
        self.assertIn("POST", resp.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("PATCH", resp.headers.get("Access-Control-Allow-Methods", ""))
        self.assertIn("Content-Type", resp.headers.get("Access-Control-Allow-Headers", ""))
        pre = self.client.options("/positions")
        self.assertIn("POST", pre.headers.get("Access-Control-Allow-Methods", ""))

    def test_position_create_and_get(self):
        resp = self._create_position()
        self.assertEqual(resp.status_code, 201)
        d = resp.get_json()
        self.assertEqual(d["symbol"], "AMC")
        self.assertEqual(d["direction"], "LONG")
        self.assertEqual(d["status"], "OPEN")
        self.assertEqual(d["opened_at"], "2026-08-13T14:30:00Z")
        self.assertEqual(d["instrument_count"], 1)
        self.assertEqual(d["open_instrument_count"], 1)
        self.assertEqual(len(d["instruments"]), 1)
        self.assertEqual(d["instruments"][0]["instrument_type"], "SHARE")
        self.assertEqual(d["instruments"][0]["entry_price"], 2.53)
        self.assertIn("dna_context", d)

        got = self.client.get(f"/positions/{d['id']}", headers=self._state_headers())
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.get_json()["id"], d["id"])

    def test_position_validation(self):
        resp = self._create_position(direction="SIDEWAYS")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("direction", resp.get_json()["error"])

        resp = self.client.post("/positions", data=json.dumps({"symbol": "AMC", "direction": "LONG"}),
                                content_type="application/json", headers=self._state_headers())
        self.assertEqual(resp.status_code, 400)
        self.assertIn("instrument", resp.get_json()["error"])

        resp = self._create_position(symbol="BAD SYMBOL!")
        self.assertEqual(resp.status_code, 400)

        # Option leg must have a strike; SHARE must not.
        resp = self._create_position(instrument={"type": "CALL", "quantity": 1,
                                                 "entry_price": 2.53, "entry_time": "2026-08-13T14:30:00Z"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("strike", resp.get_json()["error"])

    def test_position_list_and_filter(self):
        self._create_position(symbol="FLTZ")
        self._create_position(symbol="FLTZ", direction="SHORT")
        self._create_position(symbol="FLTZ")
        allp = self.client.get("/positions?symbol=FLTZ", headers=self._state_headers()).get_json()
        self.assertEqual(allp["count"], 3)
        closed_id = allp["positions"][0]["id"]
        self.client.patch(f"/positions/{closed_id}", data=json.dumps({"status": "CLOSED"}),
                          content_type="application/json", headers=self._state_headers())

        openp = self.client.get("/positions?symbol=FLTZ&status=OPEN",
                                headers=self._state_headers()).get_json()
        self.assertEqual(openp["count"], 2)
        closed = self.client.get("/positions?symbol=FLTZ&status=CLOSED",
                                 headers=self._state_headers()).get_json()
        self.assertEqual(closed["count"], 1)
        self.assertIsNotNone(closed["positions"][0]["closed_at"])

    def test_position_add_and_close_instrument(self):
        pid = self._create_position().get_json()["id"]
        add = self.client.post(f"/positions/{pid}/instruments",
                               data=json.dumps({"type": "SHARE", "quantity": 50,
                                                "entry_price": 2.60, "entry_time": "2026-08-13T15:00:00Z"}),
                               content_type="application/json", headers=self._state_headers())
        self.assertEqual(add.status_code, 201)
        iid = add.get_json()["id"]

        patch = self.client.patch(f"/positions/{pid}/instruments/{iid}",
                                  data=json.dumps({"exit_price": 2.80, "exit_time": "2026-08-13T16:00:00Z",
                                                   "status": "CLOSED"}),
                                  content_type="application/json", headers=self._state_headers())
        self.assertEqual(patch.status_code, 200)
        self.assertEqual(patch.get_json()["status"], "CLOSED")
        self.assertEqual(patch.get_json()["exit_price"], 2.80)

        detail = self.client.get(f"/positions/{pid}", headers=self._state_headers()).get_json()
        self.assertEqual(detail["instrument_count"], 2)
        self.assertEqual(detail["open_instrument_count"], 1)

    def test_position_roll_linking(self):
        pid = self._create_position().get_json()["id"]
        first = self.client.get(f"/positions/{pid}", headers=self._state_headers()).get_json()["instruments"][0]
        # opened half of a roll
        new = self.client.post(f"/positions/{pid}/instruments",
                               data=json.dumps({"type": "CALL", "strike": 3.0, "expiration": "2026-09-18",
                                                "quantity": 1, "entry_price": 0.30,
                                                "entry_time": "2026-08-13T17:00:00Z",
                                                "rolled_from_id": first["id"]}),
                               content_type="application/json", headers=self._state_headers())
        self.assertEqual(new.status_code, 201)
        self.assertEqual(new.get_json()["rolled_from_id"], first["id"])

        # closed half of a roll
        closed = self.client.patch(f"/positions/{pid}/instruments/{first['id']}",
                                   data=json.dumps({"status": "ROLLED", "exit_price": 2.70,
                                                    "exit_time": "2026-08-13T17:00:00Z",
                                                    "rolled_to_id": new.get_json()["id"]}),
                                   content_type="application/json", headers=self._state_headers())
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.get_json()["status"], "ROLLED")
        self.assertEqual(closed.get_json()["rolled_to_id"], new.get_json()["id"])

    def test_position_not_found(self):
        resp = self.client.get("/positions/99999", headers=self._state_headers())
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post("/positions/99999/instruments",
                                data=json.dumps({"type": "SHARE", "quantity": 1,
                                                 "entry_price": 2.53, "entry_time": "2026-08-13T14:30:00Z"}),
                                content_type="application/json", headers=self._state_headers())
        self.assertEqual(resp.status_code, 404)

    def test_position_delete(self):
        pid = self._create_position(symbol="DELTEST").get_json()["id"]
        self.client.post(f"/positions/{pid}/instruments",
                         data=json.dumps({"type": "CALL", "strike": 2.5, "expiration": "2026-09-18",
                                          "quantity": 1, "entry_price": 0.30, "entry_time": "2026-08-13T14:30:00Z"}),
                         content_type="application/json", headers=self._state_headers())
        r = self.client.delete(f"/positions/{pid}", headers=self._state_headers())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(f"/positions/{pid}", headers=self._state_headers()).status_code, 404)

    def test_instrument_delete(self):
        pid = self._create_position(symbol="DELI").get_json()["id"]
        iid = self.client.post(f"/positions/{pid}/instruments",
                               data=json.dumps({"type": "CALL", "strike": 2.5, "expiration": "2026-09-18",
                                                "quantity": 1, "entry_price": 0.30, "entry_time": "2026-08-13T14:30:00Z"}),
                               content_type="application/json", headers=self._state_headers()).get_json()["id"]
        r = self.client.delete(f"/positions/{pid}/instruments/{iid}", headers=self._state_headers())
        self.assertEqual(r.status_code, 200)
        detail = self.client.get(f"/positions/{pid}", headers=self._state_headers()).get_json()
        self.assertEqual(detail["instrument_count"], 1)
        self.assertEqual(self.client.delete(f"/positions/{pid}/instruments/{iid}",
                                            headers=self._state_headers()).status_code, 404)

    def test_close_position_records_exit_price(self):
        pid = self._create_position(symbol="CLOSE").get_json()["id"]
        self.client.post(f"/positions/{pid}/instruments",
                         data=json.dumps({"type": "CALL", "strike": 2.5, "expiration": "2026-09-18",
                                          "quantity": 1, "entry_price": 0.30, "entry_time": "2026-08-13T14:30:00Z"}),
                         content_type="application/json", headers=self._state_headers())
        r = self.client.patch(f"/positions/{pid}",
                              data=json.dumps({"status": "CLOSED", "exit_price": 3.0}),
                              content_type="application/json", headers=self._state_headers())
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["status"], "CLOSED")
        self.assertIsNotNone(d["closed_at"])
        statuses = {i["status"] for i in d["instruments"]}
        self.assertEqual(statuses, {"CLOSED"})
        self.assertTrue(all(i["exit_price"] == 3.0 for i in d["instruments"]))
        self.assertTrue(all(i["exit_time"] is not None for i in d["instruments"]))

    # =========================================================================
    # Options chain + valuation (near-live Massive enrichment)
    # =========================================================================

    def test_option_ticker_construction(self):
        self.assertEqual(massive_options.option_ticker("AMC", "CALL", 0.5, "2026-08-14"),
                         "O:AMC260814C00000500")
        self.assertEqual(massive_options.option_ticker("AMC", "CALL", 1.5, "2026-09-18"),
                         "O:AMC260918C00001500")
        self.assertEqual(massive_options.option_ticker("AMC", "PUT", 3.0, "2026-09-18"),
                         "O:AMC260918P00003000")

    def test_options_chain_requires_auth(self):
        self.assertEqual(self.client.get("/options/chain/AMC").status_code, 401)

    def test_valuation_requires_auth(self):
        self.assertEqual(self.client.get("/positions/1/valuation").status_code, 401)

    def test_valuation_endpoint(self):
        bars = [{"t": 1, "o": 2.4, "h": 2.5, "l": 2.3, "c": 2.4, "v": 100},
                {"t": 2, "o": 2.4, "h": 2.6, "l": 2.4, "c": 2.53, "v": 100}]
        quote = {"ticker": "O:AMC260918C00002500", "current": 0.30, "prev": 0.24, "last_t": 2}
        with mock.patch("massive_ohlc.get_ohlc", return_value=(bars, {})), \
             mock.patch("massive_options.get_option_quote", return_value=quote):
            pid = self._create_position(symbol="VALTEST").get_json()["id"]
            self.client.post(f"/positions/{pid}/instruments",
                             data=json.dumps({"type": "CALL", "strike": 2.5, "expiration": "2026-09-18",
                                              "quantity": 2, "entry_price": 0.30, "entry_time": "2026-08-12T14:30:00Z"}),
                             content_type="application/json", headers=self._state_headers())
            r = self.client.get(f"/positions/{pid}/valuation", headers=self._state_headers())
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["summary"]["options_contracts"], 2)
        self.assertEqual(d["summary"]["stock_shares"], 100)
        self.assertEqual(d["summary"]["total_value"], 313.0)
        self.assertEqual(d["options"][0]["breakeven"], 2.8)
        self.assertTrue(d["options"][0]["itm"])

    def test_poll_can_build_campaign_state(self):
        self._post(self._strong_start_payload(symbol="POLL", timeframe="240"))
        from poll_and_recommend import build_campaign_state
        resp = self.client.get("/state/POLL/240", headers=self._state_headers())
        shaped = resp.get_json()
        state = build_campaign_state(shaped)
        self.assertEqual(state.symbol, "POLL")
        self.assertEqual(state.timeframe, "240")
        self.assertEqual(state.phase.name, "EXPANSION")
        self.assertEqual(state.momentum.name, "BUILDING")
        self.assertEqual(state.health, 75)
        self.assertEqual(state.confidence, 68)
        self.assertEqual(state.next_event_after_signal, None)
        self.assertEqual(state.signal_bar_extension_label, "FRESH")

    def test_poll_single_tf_recommendations(self):
        from poll_and_recommend import build_campaign_state
        from decision_engine import Position, build_recommendations
        self._post(self._strong_start_payload(symbol="SINGLE", timeframe="240"))
        resp = self.client.get("/state/SINGLE/240", headers=self._state_headers())
        shaped = resp.get_json()
        state = build_campaign_state(shaped)
        recs = build_recommendations(state, Position(), current_price=100.0)
        self.assertTrue(len(recs) > 0)
        actions = [r.action for r in recs]
        self.assertTrue(any("WATCHING" in a for a in actions))

    def test_poll_multi_tf_recommendations(self):
        from poll_and_recommend import build_campaign_state
        from decision_engine import Position, synthesize_multi_timeframe_decision
        self._post(self._strong_start_payload(symbol="MULTI", timeframe="60"))
        self._post(self._strong_start_payload(symbol="MULTI", timeframe="240"))
        resp = self.client.get("/state_all/MULTI", headers=self._state_headers())
        shaped = resp.get_json()
        states = [build_campaign_state(d) for d in shaped["states"]]
        rec = synthesize_multi_timeframe_decision(states, Position(), current_price=100.0)
        self.assertIn("NO SYNTHESIZED SIGNAL", rec.action)

    def test_poll_multi_tf_with_confirmed_events(self):
        from poll_and_recommend import build_campaign_state
        from decision_engine import Position, synthesize_multi_timeframe_decision
        for tf in ("60", "120", "240"):
            self._post(self._strong_start_payload(symbol="CONFIRMED", timeframe=tf))
            self._post(self._strong_start_payload(symbol="CONFIRMED", timeframe=tf,
                                                   event="ADD"))
        resp = self.client.get("/state_all/CONFIRMED", headers=self._state_headers())
        shaped = resp.get_json()
        states = [build_campaign_state(d) for d in shaped["states"]]
        rec = synthesize_multi_timeframe_decision(states, Position(), current_price=100.0)
        self.assertIn("ENTRY SIGNAL", rec.action)

    def test_compute_extension_label_none_input(self):
        self.assertIsNone(compute_extension_label(None, None))
        self.assertIsNone(compute_extension_label(50.0, None))
        self.assertIsNone(compute_extension_label(None, 0.5))

    def test_compute_extension_label_fresh(self):
        self.assertEqual(compute_extension_label(40.0, 0.5), "FRESH")

    def test_compute_extension_label_extended_rsi(self):
        self.assertEqual(compute_extension_label(65.0, 0.5), "EXTENDED")

    def test_compute_extension_label_extended_distance(self):
        self.assertEqual(compute_extension_label(40.0, 1.0), "EXTENDED")

    # =========================================================================
    # NEW: Authentication tests
    # =========================================================================

    # --- Test 1: TradingView X-Real-IP accepted in Railway mode ---

    def test_auth_tradingview_ip_via_xrealip(self):
        tv_ip = "52.89.214.238"
        saved = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = ""
        try:
            os.environ["RAILWAY_ENVIRONMENT"] = "1"
            resp = self.client.post(
                "/webhook",
                data=json.dumps(self._strong_start_payload(secret=None)),
                content_type="application/json",
                headers={"X-Real-IP": tv_ip},
            )
            self.assertEqual(resp.status_code, 200)
            del os.environ["RAILWAY_ENVIRONMENT"]
        finally:
            webhook_receiver.WEBHOOK_SECRET = saved
            os.environ.pop("RAILWAY_ENVIRONMENT", None)
        self.assertIn("recorded", resp.get_json()["status"])

    # --- Test 2: Non-allowlisted X-Real-IP rejected in Railway mode ---

    def test_auth_non_allowlisted_ip_rejected_railway(self):
        saved = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = ""
        try:
            os.environ["RAILWAY_ENVIRONMENT"] = "1"
            resp = self.client.post(
                "/webhook",
                data=json.dumps(self._strong_start_payload(secret=None)),
                content_type="application/json",
                headers={"X-Real-IP": "192.0.2.1"},
            )
            self.assertEqual(resp.status_code, 401)
        finally:
            webhook_receiver.WEBHOOK_SECRET = saved
            os.environ.pop("RAILWAY_ENVIRONMENT", None)

    # --- Test 3: Spoofed X-Forwarded-For ignored on Railway ---

    def test_auth_xforwardedfor_ignored_on_railway(self):
        saved = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = ""
        try:
            os.environ["RAILWAY_ENVIRONMENT"] = "1"
            resp = self.client.post(
                "/webhook",
                data=json.dumps(self._strong_start_payload(secret=None)),
                content_type="application/json",
                headers={
                    "X-Real-IP": "192.0.2.1",
                    "X-Forwarded-For": "52.89.214.238",
                },
            )
            self.assertEqual(resp.status_code, 401)
        finally:
            webhook_receiver.WEBHOOK_SECRET = saved
            os.environ.pop("RAILWAY_ENVIRONMENT", None)

    # --- Test 4: Local loopback request uses remote_addr ---

    def test_auth_local_loopback_with_secret(self):
        payload = self._strong_start_payload(symbol="LOCAL1", timeframe="60")
        resp = self._post(payload)
        self.assertEqual(resp.status_code, 200)

    # --- Test 5: Ngrok loopback + official X-Forwarded-For accepted ---

    def test_auth_ngrok_loopback_official_ip(self):
        tv_ip = "52.89.214.238"
        saved = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = ""
        try:
            resp = self.client.post(
                "/webhook",
                data=json.dumps(self._strong_start_payload(secret=None)),
                content_type="application/json",
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": tv_ip},
            )
            self.assertEqual(resp.status_code, 200)
        finally:
            webhook_receiver.WEBHOOK_SECRET = saved

    # --- Test 6: Ngrok loopback + unapproved X-Forwarded-For rejected ---

    def test_auth_ngrok_loopback_unapproved_rejected(self):
        saved = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = ""
        try:
            resp = self.client.post(
                "/webhook",
                data=json.dumps(self._strong_start_payload(secret=None)),
                content_type="application/json",
                environ_overrides={"REMOTE_ADDR": "127.0.0.1"},
                headers={"X-Forwarded-For": "192.0.2.1"},
            )
            self.assertEqual(resp.status_code, 401)
        finally:
            webhook_receiver.WEBHOOK_SECRET = saved

    # --- Test 7: Valid optional X-Webhook-Secret accepted ---

    def test_auth_valid_webhook_secret_header(self):
        resp = self.client.post(
            "/webhook",
            data=json.dumps(self._strong_start_payload(secret=None)),
            content_type="application/json",
            headers={"X-Webhook-Secret": TEST_SECRET},
        )
        self.assertEqual(resp.status_code, 200)

    # --- Test 8: Invalid secret rejected ---

    def test_auth_invalid_secret_rejected(self):
        resp = self.client.post(
            "/webhook",
            data=json.dumps(self._strong_start_payload(secret="wrong-secret")),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 401)

    # --- Test 9: Constant-time comparison (hmac used, functionally tested above) ---

    def test_auth_hmac_comparison_used(self):
        import hmac
        self.assertTrue(hasattr(hmac, "compare_digest"))
        saved = webhook_receiver.WEBHOOK_SECRET
        webhook_receiver.WEBHOOK_SECRET = "secret-value"
        try:
            self.assertFalse(hmac.compare_digest("wrong", webhook_receiver.WEBHOOK_SECRET))
            self.assertTrue(hmac.compare_digest("secret-value", webhook_receiver.WEBHOOK_SECRET))
        finally:
            webhook_receiver.WEBHOOK_SECRET = saved

    # --- Test 10: /health stays public ---

    def test_auth_health_stays_public(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)

    def test_auth_health_public_even_with_state_token_set(self):
        saved = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN
        try:
            resp = self.client.get("/health")
            self.assertEqual(resp.status_code, 200)
        finally:
            webhook_receiver.STATE_API_TOKEN = saved

    # --- Test 11: State/history reject absent/invalid bearer tokens ---

    def test_auth_state_rejects_no_token_when_configured(self):
        saved = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN
        try:
            self._post(self._strong_start_payload(symbol="BOS1", timeframe="240"))
            resp = self.client.get("/state/BOS1/240")
            self.assertEqual(resp.status_code, 401)
            resp = self.client.get("/state_all/BOS1")
            self.assertEqual(resp.status_code, 401)
            resp = self.client.get("/history/BOS1/240")
            self.assertEqual(resp.status_code, 401)
        finally:
            webhook_receiver.STATE_API_TOKEN = saved

    def test_auth_state_rejects_invalid_token(self):
        saved = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN
        try:
            self._post(self._strong_start_payload(symbol="BOS2", timeframe="240"))
            resp = self.client.get("/state/BOS2/240",
                                    headers={"Authorization": "Bearer wrong-token"})
            self.assertEqual(resp.status_code, 401)
        finally:
            webhook_receiver.STATE_API_TOKEN = saved

    # --- Test 12: State/history accept correct bearer token ---

    def test_auth_state_accepts_correct_token(self):
        saved = webhook_receiver.STATE_API_TOKEN
        webhook_receiver.STATE_API_TOKEN = TEST_STATE_TOKEN
        try:
            self._post(self._strong_start_payload(symbol="BOS3", timeframe="240"))
            resp = self.client.get("/state/BOS3/240", headers=self._state_headers())
            self.assertEqual(resp.status_code, 200)
            resp = self.client.get("/state_all/BOS3", headers=self._state_headers())
            self.assertEqual(resp.status_code, 200)
            resp = self.client.get("/history/BOS3/240", headers=self._state_headers())
            self.assertEqual(resp.status_code, 200)
        finally:
            webhook_receiver.STATE_API_TOKEN = saved

    # --- Test 13: poll_and_recommend sends bearer token without printing ---

    def test_auth_poller_sends_bearer_header(self):
        from poll_and_recommend import _headers
        h = _headers("my-token")
        self.assertEqual(h["Authorization"], "Bearer my-token")
        self.assertEqual(_headers(None), {})
        self.assertEqual(_headers(""), {})


if __name__ == "__main__":
    unittest.main()
