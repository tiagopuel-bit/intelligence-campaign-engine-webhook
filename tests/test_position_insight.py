"""Live-data path tests for GET /positions/<id>/insight.

Proves the endpoint wires the same states + holding facts the pure-function
suite (test_dna_insight_library.py) already covers, and returns
dna_insight_library.compose() output verbatim -- one test per campaign
condition (§3.3), plus auth/404/no-basis guards.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dna_insight_library
import massive_ohlc
import webhook_receiver
from webhook_receiver import app, init_db

TEST_SECRET = "test-manual-secret"
TEST_STATE_TOKEN = "test-state-token"

CONDITIONS = {
    "broken": ("240", "FAILED", ""),
    "weakening": ("240", "PEAK", ""),
    "expanding": ("180", "EXPANSION", ""),
    "repairing": ("60", "RELOAD", "RELOAD"),
    "constructive": ("15", "EXPANSION", ""),
    "uncertain": ("15", "WAIT", ""),
}

FIXED_STOCK = {
    "shares": 100,
    "avg_cost": 1.52,
    "current_price": 2.0,
    "total_return_pct": 31.6,
    "first_entry": "2026-04-20T07:17:00Z",
    "market_value": 200.0,
    "leg_ids": [1],
}

EXPECTED_HOLDING = {
    "avg_cost": 1.52,
    "current_price": 2.0,
    "total_return_pct": 31.6,
    "first_entry": "2026-04-20T07:17:00Z",
}


class PositionInsightEndpointTests(unittest.TestCase):
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

    def _state_headers(self):
        return {"Authorization": f"Bearer {TEST_STATE_TOKEN}"}

    def _post_state(self, symbol, timeframe, phase, event=""):
        payload = {
            "symbol": symbol,
            "timeframe": timeframe,
            "phase": phase,
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
            "event": event,
            "rsi": 52.0,
            "ema21_distance_atr": 0.4,
            "secret": TEST_SECRET,
        }
        return self.client.post("/webhook", data=json.dumps(payload),
                                headers={"Content-Type": "application/json"})

    def _create_position(self, symbol):
        body = {
            "symbol": symbol,
            "direction": "LONG",
            "origin_timeframe": "15",
            "origin_event": "STRONG START",
            "instrument": {
                "type": "SHARE",
                "quantity": 100,
                "entry_price": 2.53,
                "entry_time": "2026-01-01T00:00:00Z",
            },
        }
        return self.client.post("/positions", data=json.dumps(body),
                                content_type="application/json",
                                headers=self._state_headers())

    def _fixed_valuation(self):
        return {"underlying": {"symbol": "AMC", "current": 2.0, "prev": 1.9},
                "options": [], "stock": FIXED_STOCK, "summary": {}}

    def test_insight_requires_auth(self):
        resp = self.client.get("/positions/1/insight")
        self.assertEqual(resp.status_code, 401)

    def test_insight_position_not_found(self):
        resp = self.client.get("/positions/999999/insight", headers=self._state_headers())
        self.assertEqual(resp.status_code, 404)

    def test_insight_per_campaign_condition_matches_compose(self):
        for condition, (timeframe, phase, event) in CONDITIONS.items():
            with self.subTest(condition=condition):
                symbol = "C" + condition[:5].upper()
                self._post_state(symbol, timeframe, phase, event)
                pid = self._create_position(symbol).get_json()["id"]
                with mock.patch.object(webhook_receiver, "_compute_valuation",
                                       return_value=self._fixed_valuation()):
                    resp = self.client.get(f"/positions/{pid}/insight", headers=self._state_headers())
                self.assertEqual(resp.status_code, 200)
                body = resp.get_json()
                self.assertEqual(len(body["holdings"]), 1)
                holding = body["holdings"][0]
                self.assertEqual(holding["instrument"], "shares")

                shaped_states = self.client.get(
                    f"/state_all/{symbol}", headers=self._state_headers()
                ).get_json()["states"]
                expected = dna_insight_library.compose(shaped_states, dict(EXPECTED_HOLDING), "shares")
                self.assertEqual(holding["insight"], expected)
                self.assertEqual(holding["insight"]["campaign_condition"], condition)
                self.assertEqual(holding["insight"]["confidence"], "structural")

    def test_insight_no_basis_when_no_states_and_no_holding_facts(self):
        symbol = "CEMPTY"
        pid = self._create_position(symbol).get_json()["id"]
        empty = {"underlying": {"symbol": symbol, "current": None, "prev": None},
                 "options": [],
                 "stock": {"avg_cost": None, "current_price": None,
                           "total_return_pct": None, "first_entry": None, "leg_ids": [1]},
                 "summary": {}}
        with mock.patch.object(webhook_receiver, "_compute_valuation", return_value=empty):
            resp = self.client.get(f"/positions/{pid}/insight", headers=self._state_headers())
        self.assertEqual(resp.status_code, 200)
        insight = resp.get_json()["holdings"][0]["insight"]
        self.assertEqual(insight["confidence"], "no-basis")
        self.assertEqual(insight["navigation_intent"], "wait")

    def test_insight_upstream_error_maps_to_503(self):
        symbol = "CUPSTRM"
        pid = self._create_position(symbol).get_json()["id"]
        exc = massive_ohlc._UpstreamError(503, "no api key")
        with mock.patch.object(webhook_receiver, "_compute_valuation", side_effect=exc):
            resp = self.client.get(f"/positions/{pid}/insight", headers=self._state_headers())
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.get_json()["error"], "upstream")


if __name__ == "__main__":
    unittest.main()
