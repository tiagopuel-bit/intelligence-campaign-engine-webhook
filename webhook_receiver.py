"""
Webhook receiver for the DNA (CIF) Pine script's alert() calls.

Run locally:   python3 webhook_receiver.py
Railway:       gunicorn --bind 0.0.0.0:$PORT webhook_receiver:app

Then point TradingView's alert webhook URL at the public address + /webhook.

WHAT THIS ACTUALLY DOES:
1. Receives the JSON payload the Pine script already sends via alert()
2. Stores every alert in a local SQLite database, one row per event, per
   symbol+timeframe.
3. Watches STRONG START/RELOAD signals and records the next follow-up event.
4. Exposes CampaignState-shaped JSON endpoints for decision_engine.py.

WHAT THIS DOES NOT DO:
- Does not place any trades. Read-only, informational.

AUTHENTICATION:
- TradingView alerts are authenticated by source IP (official webhook IPs).
  No secret field is required in the alert() JSON.
- An optional WEBHOOK_SECRET may be configured for manual smoke-test clients.
- Read endpoints (/state, /state_all, /history) are protected by
  STATE_API_TOKEN (Authorization: Bearer) when configured.

UPDATED v12.6.19: TradingView IP allowlist replaces secret-based auth.
The Pine script's alert() call sends its existing JSON unchanged."""
from __future__ import annotations
from flask import Flask, request, jsonify, send_from_directory
import sqlite3
import hmac
import os
import ipaddress
import uuid
import threading
import email.utils
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

import dna_insight_library
import massive_ohlc
import massive_options
import finra_short
import pionex_bridge
import positions
import sec_filings
from paper_execution import db as paper_db
from paper_execution.activation import activate_if_ready
from paper_execution.api import create_blueprint as create_paper_blueprint
from paper_execution.cloud_state import cloud_state_provider
from paper_execution.runner import run_once as run_paper_once


# -- Database path -----------------------------------------------------------

def resolve_db_path() -> Path:
    if os.environ.get("DATABASE_PATH"):
        return Path(os.environ["DATABASE_PATH"]).expanduser()
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "dna_alerts.db"
    return Path(__file__).parent / "dna_alerts.db"


DB_PATH = resolve_db_path()


def resolve_paper_db_path() -> Path:
    if os.environ.get("PAPER_DATABASE_PATH"):
        return Path(os.environ["PAPER_DATABASE_PATH"]).expanduser()
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "paper.db"
    return Path(__file__).parent / "paper_execution" / "paper.db"


PAPER_DB_PATH = resolve_paper_db_path()

# -- Auth configuration ------------------------------------------------------

TRADINGVIEW_WEBHOOK_IPS = {
    ip.strip()
    for ip in os.environ.get(
        "TRADINGVIEW_WEBHOOK_IPS",
        "52.89.214.238,34.212.75.30,54.218.53.128,52.32.178.7",
    ).split(",")
    if ip.strip()
}

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
STATE_API_TOKEN = os.environ.get("STATE_API_TOKEN", "")

app = Flask(__name__)

CONTINUATION_EVENTS = {"ADD", "FIRE ADD", "MANAGE"}
SIGNAL_EVENTS = {"STRONG START", "RELOAD"}
INVALIDATING_EVENTS = {"FAIL TEST"}


# -- Database helpers --------------------------------------------------------

def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# Columns added to the alerts table over time via migrations. Kept here so both
# the CREATE TABLE (fresh DBs) and the idempotent migration (existing DBs) stay
# in sync -- and so an old DB that predates a column is repaired on startup.
_ALERT_MIGRATION_COLUMNS = {
    "session": "TEXT",  # migration 001 (Pine v12.6.20)
    "active_trade": "INTEGER",  # migration 003 (Pine v12.6.21)
    "active_entry": "REAL",
    "active_stop": "REAL",
    "active_target": "REAL",
    "active_trade_source": "TEXT",
    "active_trade_open_pct": "REAL",
    "source": "TEXT NOT NULL DEFAULT 'live_webhook'",  # migration 004 (backfill provenance)
}


def _ensure_alert_columns(conn):
    """Idempotently add any migrated alerts columns that are missing.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, so we consult PRAGMA table_info
    and only ALTER what is missing. Safe to run on every startup against a
    live DB: existing rows keep their data and simply read NULL for the new
    columns.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)")}
    for name, ddl in _ALERT_MIGRATION_COLUMNS.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE alerts ADD COLUMN {name} {ddl}")


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            phase TEXT,
            health INTEGER,
            score INTEGER,
            confidence INTEGER,
            momentum TEXT,
            status TEXT,
            action TEXT,
            exhaustion_warning INTEGER,
            reload_quality TEXT,
            htf_phase TEXT,
            campaign_alignment TEXT,
            last_fail_type TEXT,
            close REAL,
            bar_event TEXT,
            bar_time TEXT,
            rsi REAL,
            ema21_distance_atr REAL,
            session TEXT,
            active_trade INTEGER,
            active_entry REAL,
            active_stop REAL,
            active_target REAL,
            active_trade_source TEXT,
            active_trade_open_pct REAL,
            source TEXT NOT NULL DEFAULT 'live_webhook',
            received_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS watch_state (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            signal_event TEXT,
            signal_time TEXT,
            signal_extension_label TEXT,
            next_event_after_signal TEXT,
            PRIMARY KEY (symbol, timeframe)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED')),
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            origin_timeframe TEXT,
            origin_event TEXT,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS position_instruments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
            instrument_type TEXT NOT NULL CHECK(instrument_type IN ('SHARE','CALL','PUT')),
            strike REAL,
            expiration TEXT,
            quantity REAL NOT NULL,
            entry_price REAL NOT NULL,
            entry_time TEXT NOT NULL,
            exit_price REAL,
            exit_time TEXT,
            status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','ROLLED')),
            rolled_from_id INTEGER REFERENCES position_instruments(id),
            rolled_to_id INTEGER REFERENCES position_instruments(id),
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_positions_symbol_status ON positions(symbol, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_instruments_position ON position_instruments(position_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS underlying_heartbeats (
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            bar_time INTEGER NOT NULL,
            close REAL NOT NULL,
            session TEXT NOT NULL DEFAULT 'UNKNOWN',
            source TEXT NOT NULL,
            received_at TEXT NOT NULL,
            PRIMARY KEY (symbol, bar_time)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS option_heartbeats (
            instrument_ref TEXT NOT NULL,
            position_ref TEXT NOT NULL,
            symbol TEXT NOT NULL,
            ticker TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            bar_time INTEGER NOT NULL,
            close REAL NOT NULL,
            option_return REAL,
            matched_bars INTEGER NOT NULL,
            activity_ratio REAL NOT NULL,
            volume REAL,
            session TEXT NOT NULL DEFAULT 'UNKNOWN',
            source TEXT NOT NULL,
            received_at TEXT NOT NULL,
            PRIMARY KEY (instrument_ref, bar_time)
        )
    """)
    _ensure_alert_columns(conn)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alerts_relay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            phase TEXT,
            health INTEGER,
            score INTEGER,
            confidence INTEGER,
            momentum TEXT,
            status TEXT,
            action TEXT,
            exhaustion_warning INTEGER,
            reload_quality TEXT,
            htf_phase TEXT,
            campaign_alignment TEXT,
            last_fail_type TEXT,
            close REAL,
            bar_event TEXT,
            bar_time TEXT,
            rsi REAL,
            ema21_distance_atr REAL,
            session TEXT,
            active_trade INTEGER,
            active_entry REAL,
            active_stop REAL,
            active_target REAL,
            active_trade_source TEXT,
            active_trade_open_pct REAL,
            source TEXT NOT NULL DEFAULT 'relay',
            received_at TEXT NOT NULL
        )
    """)
    sec_filings.ensure_schema(conn)
    conn.commit()
    conn.close()


# -- IP resolution -----------------------------------------------------------

def resolve_client_ip() -> str:
    """Resolve the authenticated client IP.

    On Railway the edge injects X-Real-IP reliably.
    Locally we use remote_addr. For ngrok (loopback origin) we fall back
    to a single valid IP from X-Forwarded-For so the TradingView allowlist
    still works through the tunnel.
    """
    if os.environ.get("RAILWAY_ENVIRONMENT"):
        real_ip = request.headers.get("X-Real-IP", "")
        if real_ip:
            return real_ip.strip()
        return ""

    remote = (request.remote_addr or "").strip()
    try:
        addr = ipaddress.ip_address(remote)
        if addr.is_loopback:
            ff = (request.headers.get("X-Forwarded-For") or "").split(",")
            for candidate in ff:
                candidate = candidate.strip()
                try:
                    ipaddress.ip_address(candidate)
                    return candidate
                except ValueError:
                    continue
    except ValueError:
        pass
    return remote


# -- Authorization -----------------------------------------------------------

def webhook_is_authorized(payload: dict) -> bool:
    """POST /webhook authorization.

    Authorized if:
    1. The resolved client IP is in the TradingView allowlist, OR
    2. The optional WEBHOOK_SECRET matches (X-Webhook-Secret header or JSON "secret" field).
    """
    client_ip = resolve_client_ip()
    if client_ip and client_ip in TRADINGVIEW_WEBHOOK_IPS:
        return True

    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Webhook-Secret") or payload.get("secret")
        if isinstance(supplied, str) and hmac.compare_digest(supplied, WEBHOOK_SECRET):
            return True

    return False


def _tradingview_ip_authorized() -> bool:
    client_ip = resolve_client_ip()
    return bool(client_ip and client_ip in TRADINGVIEW_WEBHOOK_IPS)


def _manual_secret_authorized(payload: dict) -> bool:
    if not WEBHOOK_SECRET:
        return False
    supplied = request.headers.get("X-Webhook-Secret") or payload.get("secret")
    return isinstance(supplied, str) and hmac.compare_digest(supplied, WEBHOOK_SECRET)


def state_is_authorized() -> bool:
    """GET state/history authorization via STATE_API_TOKEN.

    When STATE_API_TOKEN is configured (production), require Bearer match.
    When not configured (local dev), allow loopback only.
    """
    if STATE_API_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            return hmac.compare_digest(token, STATE_API_TOKEN)
        return False

    try:
        addr = ipaddress.ip_address((request.remote_addr or "").strip())
        return addr.is_loopback
    except ValueError:
        return False


# -- Auth helper -------------------------------------------------------------

def _safe_log(method: str, req_id: str) -> None:
    print(f"[{req_id}] auth_method={method}", flush=True)


# -- Payload helpers ---------------------------------------------------------

def infer_event_from_payload(payload: dict) -> str | None:
    # v12.6.13+ always sends "event" (empty string = no discrete event). Use it
    # verbatim. Do NOT infer from "action": "BUILD" is a persistent
    # recommendation during ACCUMULATION/EXPANSION and was mislabeling every
    # health-change alert as "STRONG START".
    if "event" in payload:
        return payload.get("event") or None
    # Legacy payloads (pre-v12.6.13) carry no "event" field; infer as before.
    if payload.get("last_fail_type") not in (None, "NONE", ""):
        return payload["last_fail_type"]
    action = (payload.get("action") or "").upper()
    if "RELOAD" in action:
        return "RELOAD"
    if "BUILD" in action:
        return "STRONG START"
    return None


def compute_extension_label(rsi: float | None, ema21_distance_atr: float | None) -> str | None:
    if rsi is None or ema21_distance_atr is None:
        return None
    if rsi >= 65 or ema21_distance_atr >= 1.0:
        return "EXTENDED"
    return "FRESH"


def _parse_float_or_none(value) -> float | None:
    """Parse a Trade Box numeric field; Pine emits "N/A" when the box is closed."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value in ("", "N/A", "NONE", "NaN", "na", "null"):
            return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int_flag(value) -> int:
    """Parse active_trade, which Pine emits as a bare JSON 1/0."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return 1 if value else 0
    if isinstance(value, str):
        return 1 if value.strip().lower() in ("1", "true", "yes") else 0
    return 0


def _parse_str_or_none(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return None if value in ("", "N/A", "null") else value
    return str(value)


def _record_price_heartbeat(conn, payload: dict, now: str):
    """Persist an explicit TradingView heartbeat without creating a DNA event.

    Heartbeats must be emitted on every 1-minute bar by the separate relay
    script. Ordinary DNA event alerts never enter these tables.
    """
    kind = str(payload.get("kind") or "").strip().upper()
    if kind not in {"UNDERLYING_HEARTBEAT", "OPTION_HEARTBEAT"}:
        return None
    symbol = str(payload.get("symbol") or "").strip().upper()
    timeframe = str(payload.get("timeframe") or "").strip().lower()
    close = _parse_float_or_none(payload.get("close"))
    try:
        bar_time = int(payload.get("time"))
    except (TypeError, ValueError):
        bar_time = 0
    if not symbol or timeframe not in {"1", "1m"} or close is None or close <= 0 or bar_time <= 0:
        return jsonify({"error": "heartbeat requires symbol, 1m timeframe, positive close and epoch-ms time"}), 400
    if bar_time > int(datetime.now(timezone.utc).timestamp() * 1000) + 60_000:
        return jsonify({"error": "future heartbeat timestamp rejected"}), 400
    if kind == "UNDERLYING_HEARTBEAT":
        session = str(payload.get("session") or "UNKNOWN").strip().upper()
        conn.execute(
            "INSERT INTO underlying_heartbeats (symbol,timeframe,bar_time,close,session,source,received_at) "
            "VALUES (?,?,?,?,?,?,?) ON CONFLICT(symbol,bar_time) DO UPDATE SET "
            "close=excluded.close, received_at=excluded.received_at",
            (symbol, timeframe, bar_time, close, session, "live_webhook", now),
        )
        conn.commit()
        _paper_tick_safely()
        return jsonify({"status": "heartbeat_recorded", "kind": kind, "symbol": symbol, "bar_time": bar_time})

    position_ref = str(payload.get("position_ref") or "").strip()
    instrument_ref = str(payload.get("instrument_ref") or "").strip()
    ticker = str(payload.get("ticker") or "").strip().upper()
    if not position_ref.isdigit() or not instrument_ref.isdigit() or not ticker:
        return jsonify({"error": "option heartbeat requires numeric position_ref/instrument_ref and ticker"}), 400
    exact = conn.execute(
        "SELECT i.id FROM positions p JOIN position_instruments i ON i.position_id=p.id "
        "WHERE p.id=? AND i.id=? AND p.symbol=? AND p.status='OPEN' AND i.status='OPEN' "
        "AND i.instrument_type IN ('CALL','PUT')",
        (int(position_ref), int(instrument_ref), symbol),
    ).fetchone()
    if exact is None:
        return jsonify({"error": "option heartbeat does not match an open option instrument"}), 409
    option_return = _parse_float_or_none(payload.get("option_return"))
    activity_ratio = _parse_float_or_none(payload.get("activity_ratio"))
    volume = _parse_float_or_none(payload.get("volume"))
    session = str(payload.get("session") or "UNKNOWN").strip().upper()
    try:
        matched_bars = max(0, int(payload.get("matched_bars", 0)))
    except (TypeError, ValueError):
        matched_bars = 0
    if activity_ratio is None or not 0 <= activity_ratio <= 1:
        return jsonify({"error": "option heartbeat requires activity_ratio between 0 and 1"}), 400
    conn.execute(
        "INSERT INTO option_heartbeats (instrument_ref,position_ref,symbol,ticker,timeframe,bar_time,close,"
        "option_return,matched_bars,activity_ratio,volume,session,source,received_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(instrument_ref,bar_time) DO UPDATE SET close=excluded.close, option_return=excluded.option_return, "
        "matched_bars=excluded.matched_bars, activity_ratio=excluded.activity_ratio, volume=excluded.volume, "
        "received_at=excluded.received_at",
        (instrument_ref, position_ref, symbol, ticker, timeframe, bar_time, close, option_return,
         matched_bars, activity_ratio, volume, session, "live_contract_bar", now),
    )
    conn.commit()
    _paper_tick_safely()
    return jsonify({"status": "heartbeat_recorded", "kind": kind, "symbol": symbol,
                    "instrument_ref": instrument_ref, "bar_time": bar_time})


def _paper_tick_safely() -> None:
    """Event-driven cloud runner tick; errors never corrupt webhook ingestion."""
    if app.config.get("TESTING"):
        return
    try:
        activation = activate_if_ready(PAPER_DB_PATH, DB_PATH, "AMC")
        if activation.get("status") in {"ACTIVATED", "ALREADY_ACTIVE"}:
            run_paper_once(str(PAPER_DB_PATH), cloud_state_provider(str(DB_PATH)))
    except Exception as exc:  # fail closed and keep the heartbeat durable
        print(f"paper_tick_blocked={type(exc).__name__}", flush=True)


# -- Routes ------------------------------------------------------------------

def _insert_alert(conn, table: str, symbol: str, timeframe: str, event: str,
                  fields: dict, now: str) -> None:
    """Insert one alert row into `table` (``alerts`` or ``alerts_relay``).

    `fields` is the per-timeframe payload dict (the whole native payload, or
    one item of a relay ``events`` batch). The four identity fields the rest of
    the pipeline depends on — symbol, source timeframe, event identity and bar
    timestamp — plus price and the DNA fields are stored verbatim.
    """
    conn.execute(
        f"INSERT INTO {table} (symbol, timeframe, phase, health, score, confidence, "
        "momentum, status, action, exhaustion_warning, reload_quality, "
        "htf_phase, campaign_alignment, last_fail_type, close, bar_event, "
        "bar_time, rsi, ema21_distance_atr, session, active_trade, "
        "active_entry, active_stop, active_target, active_trade_source, "
        "active_trade_open_pct, received_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (symbol, timeframe, fields.get("phase"), fields.get("health"),
         fields.get("score"), fields.get("confidence"), fields.get("momentum"),
         fields.get("status"), fields.get("action"),
         int(bool(fields.get("exhaustion_warning"))), fields.get("reload_quality"),
         fields.get("htf_phase"), fields.get("campaign_alignment"),
         fields.get("last_fail_type"), fields.get("close"), event,
         fields.get("time"), fields.get("rsi"), fields.get("ema21_distance_atr"),
         fields.get("session"),
         _parse_int_flag(fields.get("active_trade")),
         _parse_float_or_none(fields.get("active_entry")),
         _parse_float_or_none(fields.get("active_stop")),
         _parse_float_or_none(fields.get("active_target")),
         _parse_str_or_none(fields.get("active_trade_source")),
         _parse_float_or_none(fields.get("active_trade_open_pct")),
         now),
    )


@app.route("/webhook", methods=["POST"])
def webhook():
    req_id = str(uuid.uuid4())[:8]
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not payload:
        return jsonify({"error": "no JSON payload"}), 400

    if _tradingview_ip_authorized():
        _safe_log("tradingview_ip", req_id)
    elif _manual_secret_authorized(payload):
        _safe_log("manual_secret", req_id)
    else:
        return jsonify({"error": "unauthorized"}), 401

    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    heartbeat_response = _record_price_heartbeat(conn, payload, now)
    if heartbeat_response is not None:
        conn.close()
        return heartbeat_response

    # MTF relay: one anchor-bar alert may carry several tracked timeframes'
    # events in a single batch (multiple bars closed on the same anchor tick).
    # Relay rows go to the separate alerts_relay table so they never feed the
    # native DNA read — the relay runs *alongside* native for comparison.
    relay_events = payload.get("events") if payload.get("relay") else None
    if relay_events is not None:
        if not isinstance(relay_events, list) or not relay_events:
            conn.close()
            return jsonify({"error": "relay events must be a non-empty list"}), 400
        symbol = str(payload.get("symbol", "")).strip().upper() or "UNKNOWN"
        stored = 0
        for item in relay_events:
            if not isinstance(item, dict):
                continue
            tf = item.get("timeframe", "UNKNOWN")
            ev = infer_event_from_payload(item)
            _insert_alert(conn, "alerts_relay", symbol, tf, ev, item, now)
            stored += 1
        conn.commit()
        conn.close()
        return jsonify({"status": "recorded", "symbol": symbol, "relay": True, "events_stored": stored})

    symbol = payload.get("symbol", "UNKNOWN")
    timeframe = payload.get("timeframe", "UNKNOWN")
    event = infer_event_from_payload(payload)
    _insert_alert(conn, "alerts", symbol, timeframe, event, payload, now)

    row = conn.execute(
        "SELECT * FROM watch_state WHERE symbol=? AND timeframe=?", (symbol, timeframe)
    ).fetchone()

    if event in SIGNAL_EVENTS:
        extension_label = compute_extension_label(payload.get("rsi"), payload.get("ema21_distance_atr"))
        conn.execute("""
            INSERT INTO watch_state (symbol, timeframe, signal_event, signal_time, signal_extension_label, next_event_after_signal)
            VALUES (?,?,?,?,?,NULL)
            ON CONFLICT(symbol, timeframe) DO UPDATE SET
                signal_event=excluded.signal_event, signal_time=excluded.signal_time,
                signal_extension_label=excluded.signal_extension_label, next_event_after_signal=NULL
        """, (symbol, timeframe, event, now, extension_label))
    elif row is not None and row["next_event_after_signal"] is None and event is not None:
        conn.execute("""
            UPDATE watch_state SET next_event_after_signal=? WHERE symbol=? AND timeframe=?
        """, (event, symbol, timeframe))

    conn.commit()
    conn.close()
    return jsonify({"status": "recorded", "symbol": symbol, "timeframe": timeframe, "event": event})


@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except sqlite3.Error:
        return jsonify({"status": "unhealthy"}), 503
    return jsonify({"status": "ok"})


@app.route("/dashboard", methods=["GET"])
def serve_dashboard():
    """Serve the dashboard UI straight from the deployment, so it always
    reflects whatever is currently live (no local file / manual git pull)."""
    path = Path(__file__).parent / "ui" / "dna_dashboard.html"
    if not path.exists():
        return jsonify({"error": "dashboard not found"}), 404
    return app.response_class(path.read_text(encoding="utf-8"), mimetype="text/html")


@app.route("/dashboard/vendor/<path:filename>", methods=["GET"])
def serve_vendor(filename):
    """Serve vendored static assets (e.g. lightweight-charts) referenced by the
    dashboard via a relative path, so the same HTML loads under file:// and the
    Railway /dashboard route."""
    return send_from_directory(str(Path(__file__).parent / "ui" / "vendor"), filename)


def _shape_state(symbol, timeframe, latest, watch):
    return {
        "symbol": symbol, "timeframe": timeframe,
        "phase": latest["phase"], "health": latest["health"], "confidence": latest["confidence"],
        "momentum": latest["momentum"], "recent_event": latest["bar_event"],
        "exhaustion_warning": bool(latest["exhaustion_warning"]),
        "reload_quality": latest["reload_quality"], "htf_phase": latest["htf_phase"],
        "campaign_alignment": latest["campaign_alignment"], "last_fail_type": latest["last_fail_type"],
        "close": latest["close"], "bar_time": latest["bar_time"],
        "rsi": latest["rsi"], "ema21_distance_atr": latest["ema21_distance_atr"],
        "session": latest["session"] if "session" in latest.keys() else None,
        "active_trade": bool(latest["active_trade"]) if "active_trade" in latest.keys() else False,
        "active_entry": latest["active_entry"] if "active_entry" in latest.keys() else None,
        "active_stop": latest["active_stop"] if "active_stop" in latest.keys() else None,
        "active_target": latest["active_target"] if "active_target" in latest.keys() else None,
        "active_trade_source": latest["active_trade_source"] if "active_trade_source" in latest.keys() else None,
        "active_trade_open_pct": latest["active_trade_open_pct"] if "active_trade_open_pct" in latest.keys() else None,
        "source": latest["source"] if "source" in latest.keys() else "live_webhook",
        "next_event_after_signal": watch["next_event_after_signal"] if watch else None,
        "signal_event": watch["signal_event"] if watch else None,
        "signal_time": watch["signal_time"] if watch else None,
        "signal_bar_extension_label": watch["signal_extension_label"] if watch else None,
    }


@app.route("/state/<symbol>/<timeframe>", methods=["GET"])
def get_state(symbol, timeframe):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    latest = conn.execute("""
        SELECT * FROM alerts WHERE symbol=? AND timeframe=? ORDER BY CAST(bar_time AS INTEGER) DESC, id DESC LIMIT 1
    """, (symbol, timeframe)).fetchone()
    watch = conn.execute("""
        SELECT * FROM watch_state WHERE symbol=? AND timeframe=?
    """, (symbol, timeframe)).fetchone()
    conn.close()
    if latest is None:
        return jsonify({"error": "no alerts recorded yet for this symbol/timeframe"}), 404
    return jsonify(_shape_state(symbol, timeframe, latest, watch))


@app.route("/state_all/<symbol>", methods=["GET"])
def get_state_all(symbol):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    timeframes = [r["timeframe"] for r in conn.execute(
        "SELECT DISTINCT timeframe FROM alerts WHERE symbol=?", (symbol,)
    ).fetchall() if r["timeframe"] not in _HIDDEN_TIMEFRAMES]
    if not timeframes:
        conn.close()
        return jsonify({"error": f"no alerts recorded yet for {symbol} on any timeframe"}), 404
    states = []
    for tf in timeframes:
        latest = conn.execute("""
            SELECT * FROM alerts WHERE symbol=? AND timeframe=? ORDER BY CAST(bar_time AS INTEGER) DESC, id DESC LIMIT 1
        """, (symbol, tf)).fetchone()
        watch = conn.execute("""
            SELECT * FROM watch_state WHERE symbol=? AND timeframe=?
        """, (symbol, tf)).fetchone()
        if latest is not None:
            states.append(_shape_state(symbol, tf, latest, watch))
    conn.close()
    return jsonify({"symbol": symbol, "timeframe_count": len(states), "states": states})


# -- News stream (media sources) ---------------------------------------------

_YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
_GOOGLE_RSS_URL = "https://news.google.com/rss/search"
_NEWS_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_NEWS_CACHE_TTL_SECONDS = 300
_NEWS_CACHE = {}
_NEWS_CACHE_LOCK = threading.Lock()


def _fetch_yahoo_news(symbol, limit):
    resp = requests.get(
        _YAHOO_SEARCH_URL,
        params={"q": symbol, "quotesCount": 0, "newsCount": limit, "enableFuzzyQuery": "false"},
        headers={"User-Agent": _NEWS_UA},
        timeout=8,
    )
    resp.raise_for_status()
    items = []
    for n in resp.json().get("news") or []:
        items.append({
            "title": n.get("title"),
            "publisher": n.get("publisher") or "Yahoo Finance",
            "url": n.get("link"),
            "published": int(n["providerPublishTime"]) * 1000 if n.get("providerPublishTime") else None,
            "kind": n.get("type"),
            "source": "yahoo",
        })
    return items


def _fetch_google_news(symbol, limit):
    resp = requests.get(
        _GOOGLE_RSS_URL,
        params={"q": f"{symbol} stock", "hl": "en-US", "gl": "US", "ceid": "US:en"},
        headers={"User-Agent": _NEWS_UA},
        timeout=8,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for node in root.iter("item"):
        title = node.findtext("title")
        if not title:
            continue
        published = None
        pubdate = node.findtext("pubDate")
        if pubdate:
            try:
                published = int(email.utils.parsedate_to_datetime(pubdate).timestamp() * 1000)
            except Exception:  # noqa: BLE001
                published = None
        items.append({
            "title": title,
            "publisher": node.findtext("source") or "Google News",
            "url": node.findtext("link"),
            "published": published,
            "kind": "STORY",
            "source": "google",
        })
        if len(items) >= limit:
            break
    return items


@app.route("/news/<symbol>", methods=["GET"])
def get_news(symbol):
    """Aggregated headline feed for one symbol from public media sources.

    Server-side proxy: the browser can't call Yahoo/Google News directly
    (no CORS headers), so this endpoint fetches them and returns a normalized
    JSON list. Gated by state_is_authorized() like every other read endpoint.
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    symbol = massive_ohlc.valid_symbol(symbol)
    if not symbol:
        return jsonify({"error": "invalid symbol"}), 400
    now = datetime.now(timezone.utc).timestamp()
    with _NEWS_CACHE_LOCK:
        cached = _NEWS_CACHE.get(symbol)
        if cached and now - cached[0] < _NEWS_CACHE_TTL_SECONDS:
            body = dict(cached[1])
            body["cached"] = True
            return jsonify(body)
    items = []
    errors = []
    for fetch in (_fetch_yahoo_news, _fetch_google_news):
        try:
            items.extend(fetch(symbol, 12))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{fetch.__name__}: {exc}")
    seen = set()
    unique = []
    for it in items:
        key = it.get("url") or (it.get("title") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(it)
    unique.sort(key=lambda x: x.get("published") or 0, reverse=True)
    body = {"symbol": symbol, "count": len(unique), "news": unique, "errors": errors, "cached": False}
    with _NEWS_CACHE_LOCK:
        _NEWS_CACHE[symbol] = (now, body)
    return jsonify(body)


@app.route("/portfolio/pionex", methods=["GET"])
def get_pionex_portfolio():
    """Return the read-only Pionex spot wallet (bot/earn funds unavailable)."""
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        data = pionex_bridge.portfolio_summary()
    except Exception:  # noqa: BLE001 -- provider failures map to one safe boundary
        return jsonify({
            "error": "pionex_unavailable",
            "detail": "Pionex spot wallet is temporarily unavailable",
        }), 502
    return jsonify({
        "source": "pionex",
        "scope": "spot_wallet_only",
        "bots_included": False,
        **data,
    })


@app.route("/filings/<symbol>", methods=["GET"])
def get_filings(symbol):
    """Read-only SEC filing watch state for one symbol (SQLite only).

    Returns recent watched filings plus those first seen within a bounded alert
    window, along with configuration/seed/health status. Never makes a
    synchronous SEC request and never acknowledges/consumes an alert — the
    scheduled poll command is the sole writer.
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    clean = positions.clean_symbol(symbol)
    if not clean:
        return jsonify({"error": "invalid symbol"}), 400
    if clean not in sec_filings.SYMBOL_TO_CIK:
        return jsonify({"error": f"symbol {clean} is not mapped for SEC filings"}), 404
    window_hours = request.args.get("window_hours", type=int)
    if window_hours is None:
        window_hours = sec_filings.DEFAULT_ALERT_WINDOW_HOURS
    if not (1 <= window_hours <= 720):
        return jsonify({"error": "window_hours must be between 1 and 720"}), 400
    return jsonify(sec_filings.get_filings_state(DB_PATH, clean, window_hours))


@app.route("/short/<symbol>", methods=["GET"])
def get_short_context(symbol):
    """Read-only FINRA daily short-sale-volume context for one symbol.

    Aggregates the rolling short-volume ratio into a closed-vocabulary
    short-activity read (LOW/NORMAL/ELEVATED/HIGH/NO_DATA). FINRA publishes
    daily short volume T+1, so freshness is DELAYED, never live. This is short
    activity, not cost-to-borrow (FINRA publishes no CTB/locate here).
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    clean = positions.clean_symbol(symbol)
    if not clean:
        return jsonify({"error": "invalid symbol"}), 400
    days = request.args.get("days", type=int)
    if days is None:
        days = finra_short.DEFAULT_DAYS
    if not (1 <= days <= finra_short.MAX_DAYS):
        return jsonify({"error": f"days must be between 1 and {finra_short.MAX_DAYS}"}), 400
    try:
        return jsonify(finra_short.short_context(clean, days=days))
    except finra_short.UpstreamError as exc:
        return jsonify({"error": "upstream", "detail": str(exc)}), 502


# Symbols excluded from the asset list: internal pipeline smoke-test rows,
# not real market data. Same allowlist as scripts/cleanup_test_symbols.py.
_TEST_SYMBOLS = {"PUBTEST", "TEST", "TEST2", "TEST_PING"}

# Timeframes that exist only as a price tick (a 1m DNA alert feeding a fresher
# close), not real campaign rungs. Hidden from /state_all and /assets so they
# don't surface in the dashboard, but the live-close valuation still reads them.
_HIDDEN_TIMEFRAMES = {"1"}


@app.route("/assets", methods=["GET"])
def get_assets():
    """Phase 1 landing page: list of real symbols with any recorded alerts.

    Read-only aggregate over the existing alerts table -- no new state,
    no coordinator dependency. Test-symbol rows are excluded so the page
    doesn't need to know about pipeline-internal smoke-test data.
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    hidden = ",".join("?" * len(_HIDDEN_TIMEFRAMES))
    rows = conn.execute(f"""
        SELECT symbol,
               COUNT(DISTINCT timeframe) AS timeframe_count,
               COUNT(*) AS alert_count,
               MAX(received_at) AS last_updated,
               SUM(CASE WHEN source = 'backfill_replay' THEN 1 ELSE 0 END) AS backfill_count,
               SUM(CASE WHEN source = 'live_webhook' THEN 1 ELSE 0 END) AS live_count
        FROM alerts
        WHERE timeframe NOT IN ({hidden})
        GROUP BY symbol
        ORDER BY symbol
    """, list(_HIDDEN_TIMEFRAMES)).fetchall()
    conn.close()
    assets = [
        {
            "symbol": r["symbol"],
            "timeframe_count": r["timeframe_count"],
            "alert_count": r["alert_count"],
            "last_updated": r["last_updated"],
            "source_counts": {
                "live_webhook": r["live_count"] or 0,
                "backfill_replay": r["backfill_count"] or 0,
            },
        }
        for r in rows if r["symbol"] not in _TEST_SYMBOLS
    ]
    return jsonify({"asset_count": len(assets), "assets": assets})


@app.route("/ohlc/<symbol>/<timeframe>", methods=["GET"])
def get_ohlc(symbol, timeframe):
    """Near-live RAW OHLC bars for the landing-page price chart.

    Read-only, gated by state_is_authorized() exactly like /state_all. Bars
    come from the Massive free plan via massive_ohlc.get_ohlc, which caches
    per (symbol, timeframe) and rate-limits the vendor. Supports the ladder
    3m/5m/15m/30m/1H/2H/3H/4H/D (and the webhook's numeric labels 5/15/30/
    60/120/180/240/1D).
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        bars, meta = massive_ohlc.get_ohlc(symbol, timeframe)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except massive_ohlc._UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status
    if not bars:
        return jsonify({"error": f"no bars for {symbol} {timeframe}"}), 404
    return jsonify({**meta, "bars": bars})


@app.route("/options/chain/<symbol>", methods=["GET"])
def get_options_chain(symbol):
    """Massive free-plan options chain for an underlying (contract picker)."""
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    clean = positions.clean_symbol(symbol)
    if clean is None:
        return jsonify({"error": "invalid symbol"}), 400
    try:
        chain = massive_options.get_chain(clean)
    except massive_options.UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status
    return jsonify(chain)


@app.route("/options/ohlc/<contract_ticker>/<timeframe>", methods=["GET"])
def get_options_ohlc(contract_ticker, timeframe):
    """RAW option-aggregate bars for one Massive option contract.

    Read-only, gated by state_is_authorized() exactly like /ohlc. The ticker is
    a Massive contract ticker (e.g. O:AMC260821C00004000); URL-encoding of the
    colon is handled by the client. Returns the same normalized bar schema as
    stock OHLC: {t,o,h,l,c,v} with epoch-ms t, ascending + duplicate-free. The
    latest close is a delayed aggregate close, never a live quote.
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        bars, meta = massive_options.get_option_ohlc(contract_ticker, timeframe)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except massive_options.UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status
    if not bars:
        return jsonify({"error": f"no bars for {contract_ticker} {timeframe}"}), 404
    return jsonify({**meta, "bars": bars})


@app.after_request
def _add_cors_headers(response):
    """Permissive CORS for the static dashboard/landing pages.

    These pages may be opened from any origin (a local file, or hosted
    separately from Railway) and talk to the API in the browser. Every
    endpoint below is gated by state_is_authorized() (STATE_API_TOKEN or
    loopback) -- CORS here only affects which browser origins may read or
    send a request, not whether the request itself is authorized. POST/PATCH
    are the positions write endpoints; Content-Type must be allowed so the
    browser's JSON preflight (OPTIONS) is not blocked.
    """
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, DELETE, OPTIONS"
    return response


@app.route("/history/<symbol>/<timeframe>", methods=["GET"])
def get_history(symbol, timeframe):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    rows = conn.execute("""
        SELECT bar_event, phase, health, close, bar_time, received_at, source
        FROM alerts WHERE symbol=? AND timeframe=? ORDER BY CAST(bar_time AS INTEGER) DESC LIMIT 50
    """, (symbol, timeframe)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# -- Historical backfill (replay v12.6.19 over Massive OHLC) -----------------

_backfill_state = {"status": "idle", "report": None}


def _run_backfill_job(symbols=None):
    global _backfill_state
    _backfill_state = {"status": "running", "report": None}
    try:
        import backfill
        report = backfill.run_backfill(str(DB_PATH), symbols=symbols)
        _backfill_state = {"status": "done", "report": report}
    except Exception as exc:  # noqa: BLE001
        _backfill_state = {"status": "error", "report": str(exc)}


@app.route("/backfill", methods=["POST"])
def trigger_backfill():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    if _backfill_state.get("status") == "running":
        return jsonify({"status": "already_running"}), 409
    payload = request.get_json(silent=True) or {}
    symbols = None
    if payload.get("symbols"):
        symbols = tuple(str(s).strip().upper() for s in payload["symbols"] if str(s).strip())
        if not symbols:
            return jsonify({"error": "empty symbols"}), 400
    threading.Thread(target=_run_backfill_job, args=(symbols,), daemon=True).start()
    return jsonify({"status": "started"})


@app.route("/backfill/status", methods=["GET"])
def backfill_status():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    return jsonify(_backfill_state)


@app.route("/export/db", methods=["GET"])
def export_db():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    import tempfile
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    try:
        src = get_db()
        dest = sqlite3.connect(tmp.name)
        src.backup(dest)
        dest.close()
        src.close()
        with open(tmp.name, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
    return app.response_class(
        data,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": "attachment; filename=dna_alerts.db"},
    )


@app.route("/export/csv", methods=["GET"])
def export_csv():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    import io
    import csv
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM alerts ORDER BY id"
    ).fetchall()
    conn.close()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "symbol", "timeframe", "phase", "health", "score",
                      "confidence", "momentum", "status", "action",
                      "exhaustion_warning", "reload_quality", "htf_phase",
                      "campaign_alignment", "last_fail_type", "close",
                      "bar_event", "bar_time", "rsi", "ema21_distance_atr",
                      "received_at"])
    for row in rows:
        writer.writerow([row["id"], row["symbol"], row["timeframe"],
                         row["phase"], row["health"], row["score"],
                         row["confidence"], row["momentum"], row["status"],
                         row["action"], row["exhaustion_warning"],
                         row["reload_quality"], row["htf_phase"],
                         row["campaign_alignment"], row["last_fail_type"],
                         row["close"], row["bar_event"], row["bar_time"],
                         row["rsi"], row["ema21_distance_atr"],
                         row["received_at"]])
    return app.response_class(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=dna_alerts.csv"},
    )


# -- Positions (beta) --------------------------------------------------------

def _dna_context(conn, symbol, opened_at):
    """Most recent alert per timeframe for a symbol, since the position opened.

    Reuses the get_state_all() query pattern (DISTINCT timeframe + latest alert
    per timeframe, shaped by _shape_state) with a received_at >= opened_at
    filter, per the positions task packet.
    """
    timeframes = [r["timeframe"] for r in conn.execute(
        "SELECT DISTINCT timeframe FROM alerts WHERE symbol=? AND received_at>=?",
        (symbol, opened_at),
    ).fetchall() if r["timeframe"] not in _HIDDEN_TIMEFRAMES]
    states = []
    for tf in timeframes:
        latest = conn.execute(
            "SELECT * FROM alerts WHERE symbol=? AND timeframe=? AND received_at>=? ORDER BY CAST(bar_time AS INTEGER) DESC, id DESC LIMIT 1",
            (symbol, tf, opened_at),
        ).fetchone()
        watch = conn.execute(
            "SELECT * FROM watch_state WHERE symbol=? AND timeframe=?", (symbol, tf),
        ).fetchone()
        if latest is not None:
            states.append(_shape_state(symbol, tf, latest, watch))
    return {"symbol": symbol, "timeframe_count": len(states), "states": states}


def _position_detail(conn, position_id):
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if row is None:
        return None
    instruments = conn.execute(
        "SELECT * FROM position_instruments WHERE position_id=? ORDER BY id", (position_id,),
    ).fetchall()
    shaped = [positions.shape_instrument(r) for r in instruments]
    open_count = sum(1 for i in shaped if i["status"] == "OPEN")
    detail = positions.shape_position(row, len(shaped), open_count)
    detail["instruments"] = shaped
    detail["dna_context"] = _dna_context(conn, row["symbol"], row["opened_at"])
    return detail


def _compute_valuation(symbol, instruments):
    """Enrich open legs with live prices (underlying + option bars).

    `instruments` is a list of shaped (open) instrument dicts. Option legs are
    grouped by (type, strike, expiration); stock legs are pooled. The
    underlying "current" prefers the latest live_webhook alert close (the
    TradingView webhook carries a near-real-time close) and falls back to the
    Massive daily close -- the Massive free plan lags ~1 day, so without this
    every held asset would value at yesterday's close. Option "current" is the
    latest option daily close (no live option source on the free plan; no
    Greeks).
    """
    bars, _meta = massive_ohlc.get_ohlc(symbol, "D")
    massive_current = bars[-1]["c"] if bars else None
    massive_prev = bars[-2]["c"] if len(bars) >= 2 else massive_current

    conn = get_db()
    live = conn.execute(
        "SELECT close FROM alerts WHERE symbol=? AND source='live_webhook' "
        "AND close IS NOT NULL ORDER BY CAST(bar_time AS INTEGER) DESC LIMIT 1",
        (symbol,),
    ).fetchone()
    conn.close()

    if live is not None and live["close"] is not None:
        underlying_current = live["close"]
        underlying_prev = massive_current
    else:
        underlying_current = massive_current
        underlying_prev = massive_prev

    option_groups: dict[tuple, list] = {}
    stock_legs: list = []
    for inst in instruments:
        itype = inst["instrument_type"]
        if itype == "SHARE":
            stock_legs.append(inst)
        elif itype in ("CALL", "PUT") and inst["strike"] is not None and inst["expiration"]:
            option_groups.setdefault((itype, inst["strike"], inst["expiration"]), []).append(inst)

    options = []
    for (ctype, strike, exp), legs in option_groups.items():
        contracts = sum(l["quantity"] for l in legs)
        cost_basis = sum(l["entry_price"] * l["quantity"] for l in legs)
        avg_cost = cost_basis / contracts if contracts else None
        quote = massive_options.get_option_quote(symbol, ctype, strike, exp)
        current = quote["current"] if quote else None
        prev = quote["prev"] if quote else None
        mult = 100
        itm = None
        if underlying_current is not None and strike is not None:
            itm = underlying_current > strike if ctype == "CALL" else underlying_current < strike
        options.append({
            "contract": {"type": ctype, "strike": strike, "expiration": exp},
            "contracts": contracts,
            "avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
            "current_price": current,
            "prev_price": prev,
            "market_value": round(current * contracts * mult, 2) if current is not None else None,
            "cost_basis": round(cost_basis, 2),
            "first_entry": min(l["entry_time"] for l in legs) if legs else None,
            "breakeven": round((strike + avg_cost) if ctype == "CALL" else (strike - avg_cost), 4)
            if (strike is not None and avg_cost is not None) else None,
            "itm": itm,
            "today_pnl": round((current - prev) * contracts * mult, 2)
            if (current is not None and prev is not None) else None,
            "today_return_pct": round((current - prev) / prev * 100, 2)
            if (current is not None and prev) else None,
            "total_pnl": round((current - avg_cost) * contracts * mult, 2)
            if (current is not None and avg_cost is not None) else None,
            "total_return_pct": round((current - avg_cost) / avg_cost * 100, 2)
            if (current is not None and avg_cost) else None,
            "leg_ids": [l["id"] for l in legs],
        })

    stock = None
    if stock_legs:
        shares = sum(l["quantity"] for l in stock_legs)
        cost_basis = sum(l["entry_price"] * l["quantity"] for l in stock_legs)
        avg_cost = cost_basis / shares if shares else None
        cur = underlying_current
        stock = {
            "shares": shares,
            "avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
            "current_price": cur,
            "prev_price": underlying_prev,
            "market_value": round(cur * shares, 2) if cur is not None else None,
            "cost_basis": round(cost_basis, 2),
            "first_entry": min(l["entry_time"] for l in stock_legs) if stock_legs else None,
            "today_pnl": round((cur - underlying_prev) * shares, 2)
            if (cur is not None and underlying_prev is not None) else None,
            "today_return_pct": round((cur - underlying_prev) / underlying_prev * 100, 2)
            if (cur is not None and underlying_prev) else None,
            "total_pnl": round((cur - avg_cost) * shares, 2)
            if (cur is not None and avg_cost is not None) else None,
            "total_return_pct": round((cur - avg_cost) / avg_cost * 100, 2)
            if (cur is not None and avg_cost) else None,
            "leg_ids": [l["id"] for l in stock_legs],
        }

    def _sum(items, key):
        return sum((x.get(key) or 0) for x in items)

    options_value = _sum(options, "market_value")
    options_today = _sum(options, "today_pnl")
    options_total = _sum(options, "total_pnl")
    stock_value = stock["market_value"] if stock and stock["market_value"] is not None else 0
    stock_today = stock["today_pnl"] if stock and stock["today_pnl"] is not None else 0
    stock_total = stock["total_pnl"] if stock and stock["total_pnl"] is not None else 0

    return {
        "underlying": {"symbol": symbol, "current": underlying_current, "prev": underlying_prev},
        "options": options,
        "stock": stock,
        "summary": {
            "options_contracts": _sum(options, "contracts"),
            "options_value": round(options_value, 2),
            "options_today_pnl": round(options_today, 2),
            "options_total_pnl": round(options_total, 2),
            "stock_shares": stock["shares"] if stock else 0,
            "stock_value": round(stock_value, 2),
            "stock_today_pnl": round(stock_today, 2),
            "stock_total_pnl": round(stock_total, 2),
            "total_value": round(options_value + stock_value, 2),
            "total_today_pnl": round(options_today + stock_today, 2),
            "total_pnl": round(options_total + stock_total, 2),
        },
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


@app.route("/positions", methods=["POST"])
def create_position():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True)
    position, err = positions.validate_position_payload(payload)
    if err:
        return jsonify({"error": err}), 400
    instrument, err = positions.validate_instrument_payload(payload.get("instrument"))
    if err:
        return jsonify({"error": err}), 400

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    cur = conn.execute("""
        INSERT INTO positions (symbol, direction, status, opened_at, origin_timeframe,
            origin_event, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (
        position["symbol"], position["direction"], "OPEN", instrument["entry_time"],
        position["origin_timeframe"], position["origin_event"], position["notes"], now, now,
    ))
    position_id = cur.lastrowid
    conn.execute("""
        INSERT INTO position_instruments (position_id, instrument_type, strike, expiration,
            quantity, entry_price, entry_time, status, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (
        position_id, instrument["instrument_type"], instrument["strike"],
        instrument["expiration"], instrument["quantity"], instrument["entry_price"],
        instrument["entry_time"], "OPEN", instrument["notes"], now, now,
    ))
    conn.commit()
    detail = _position_detail(conn, position_id)
    conn.close()
    return jsonify(detail), 201


@app.route("/positions", methods=["GET"])
def list_positions():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    query = "SELECT * FROM positions"
    clauses, params = [], []
    symbol = request.args.get("symbol")
    if symbol:
        clean = positions.clean_symbol(symbol)
        if clean is None:
            return jsonify({"error": "invalid symbol filter"}), 400
        clauses.append("symbol=?")
        params.append(clean)
    status = request.args.get("status")
    if status:
        status = status.strip().upper()
        if status not in positions.POSITION_STATUSES:
            return jsonify({"error": "invalid status filter"}), 400
        clauses.append("status=?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC"

    conn = get_db()
    rows = conn.execute(query, params).fetchall()
    out = []
    for row in rows:
        count = conn.execute(
            "SELECT COUNT(*) n FROM position_instruments WHERE position_id=?", (row["id"],),
        ).fetchone()["n"]
        open_count = conn.execute(
            "SELECT COUNT(*) n FROM position_instruments WHERE position_id=? AND status='OPEN'",
            (row["id"],),
        ).fetchone()["n"]
        out.append(positions.shape_position(row, count, open_count))
    conn.close()
    return jsonify({"count": len(out), "positions": out})


@app.route("/positions/<int:position_id>", methods=["GET"])
def get_position(position_id):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    detail = _position_detail(conn, position_id)
    conn.close()
    if detail is None:
        return jsonify({"error": "position not found"}), 404
    return jsonify(detail)


@app.route("/positions/<int:position_id>", methods=["PATCH"])
def update_position(position_id):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True)
    clean, err = positions.validate_position_update(payload)
    if err:
        return jsonify({"error": err}), 400

    # Optional exit price/time: when closing, these are applied to every open
    # leg so the close records what the position was actually exited at.
    exit_price = None
    if payload.get("exit_price") not in (None, ""):
        try:
            exit_price = float(payload["exit_price"])
        except (TypeError, ValueError):
            return jsonify({"error": "exit_price must be a number"}), 400
        if exit_price <= 0:
            return jsonify({"error": "exit_price must be > 0"}), 400
    exit_time = (payload.get("exit_time") or "").strip() or None

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "position not found"}), 404
    if clean.get("status") == "CLOSED":
        if "closed_at" not in clean:
            clean["closed_at"] = now
        conn.execute(
            "UPDATE position_instruments SET status='CLOSED', exit_price=?, exit_time=?, updated_at=? "
            "WHERE position_id=? AND status='OPEN'",
            (exit_price, exit_time or now, now, position_id),
        )
    sets = [f"{key}=?" for key in clean]
    params = list(clean.values()) + [now, position_id]
    conn.execute(f"UPDATE positions SET {', '.join(sets)}, updated_at=? WHERE id=?", params)
    conn.commit()
    detail = _position_detail(conn, position_id)
    conn.close()
    return jsonify(detail)


@app.route("/positions/<int:position_id>/instruments", methods=["POST"])
def add_instrument(position_id):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True)
    instrument, err = positions.validate_instrument_payload(payload)
    if err:
        return jsonify({"error": err}), 400
    conn = get_db()
    pos = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if pos is None:
        conn.close()
        return jsonify({"error": "position not found"}), 404
    if instrument["rolled_from_id"] is not None:
        src = conn.execute(
            "SELECT id FROM position_instruments WHERE id=? AND position_id=?",
            (instrument["rolled_from_id"], position_id),
        ).fetchone()
        if src is None:
            conn.close()
            return jsonify({"error": "rolled_from_id does not reference an instrument of this position"}), 400
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("""
        INSERT INTO position_instruments (position_id, instrument_type, strike, expiration,
            quantity, entry_price, entry_time, status, rolled_from_id, notes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        position_id, instrument["instrument_type"], instrument["strike"],
        instrument["expiration"], instrument["quantity"], instrument["entry_price"],
        instrument["entry_time"], "OPEN", instrument["rolled_from_id"], instrument["notes"], now, now,
    ))
    iid = cur.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM position_instruments WHERE id=?", (iid,)).fetchone()
    conn.close()
    return jsonify(positions.shape_instrument(row)), 201


@app.route("/positions/<int:position_id>/instruments/<int:iid>", methods=["PATCH"])
def update_instrument(position_id, iid):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    payload = request.get_json(silent=True)
    clean, err = positions.validate_instrument_update(payload)
    if err:
        return jsonify({"error": err}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM position_instruments WHERE id=? AND position_id=?", (iid, position_id),
    ).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "instrument not found"}), 404
    if clean.get("rolled_to_id") is not None:
        dst = conn.execute(
            "SELECT id FROM position_instruments WHERE id=? AND position_id=?",
            (clean["rolled_to_id"], position_id),
        ).fetchone()
        if dst is None:
            conn.close()
            return jsonify({"error": "rolled_to_id does not reference an instrument of this position"}), 400
    now = datetime.now(timezone.utc).isoformat()
    sets = [f"{key}=?" for key in clean]
    params = list(clean.values()) + [now, iid]
    conn.execute(f"UPDATE position_instruments SET {', '.join(sets)}, updated_at=? WHERE id=?", params)
    conn.commit()
    updated = conn.execute("SELECT * FROM position_instruments WHERE id=?", (iid,)).fetchone()
    conn.close()
    return jsonify(positions.shape_instrument(updated))


@app.route("/positions/<int:position_id>", methods=["DELETE"])
def delete_position(position_id):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    row = conn.execute("SELECT id FROM positions WHERE id=?", (position_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "position not found"}), 404
    conn.execute("DELETE FROM position_instruments WHERE position_id=?", (position_id,))
    conn.execute("DELETE FROM positions WHERE id=?", (position_id,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": position_id})


@app.route("/positions/<int:position_id>/instruments/<int:iid>", methods=["DELETE"])
def delete_instrument(position_id, iid):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM position_instruments WHERE id=? AND position_id=?", (iid, position_id),
    ).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "instrument not found"}), 404
    conn.execute("DELETE FROM position_instruments WHERE id=?", (iid,))
    conn.commit()
    conn.close()
    return jsonify({"deleted": iid})


@app.route("/positions/<int:position_id>/valuation", methods=["GET"])
def get_position_valuation(position_id):
    """Live valuation of a position's open legs (near-live Massive prices).

    Groups option legs by contract (type/strike/expiration) and pools stock
    legs, then enriches with current/prev price, market value, breakeven, ITM,
    today's and total return -- plus a summary roll-up.
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "position not found"}), 404
    instruments = conn.execute(
        "SELECT * FROM position_instruments WHERE position_id=? AND status='OPEN' ORDER BY id",
        (position_id,),
    ).fetchall()
    conn.close()
    shaped = [positions.shape_instrument(r) for r in instruments]
    try:
        valuation = _compute_valuation(row["symbol"], shaped)
    except massive_options.UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status
    except massive_ohlc._UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status
    return jsonify({"position_id": position_id, "symbol": row["symbol"], **valuation})


def _canonical_timeframe(tf):
    tf = str(tf or "")
    if tf in ("1D", "1d"):
        return "D"
    if tf in ("1W", "1w"):
        return "W"
    return tf


def _insight_holding_for_stock(stock):
    return {
        "avg_cost": stock.get("avg_cost"),
        "current_price": stock.get("current_price"),
        "total_return_pct": stock.get("total_return_pct"),
        "first_entry": stock.get("first_entry"),
    }


def _insight_holding_for_option(option):
    contract = option.get("contract") or {}
    return {
        "avg_cost": option.get("avg_cost"),
        "current_price": option.get("current_price"),
        "total_return_pct": option.get("total_return_pct"),
        "itm": option.get("itm"),
        "expiration": contract.get("expiration"),
        "first_entry": option.get("first_entry"),
    }


@app.route("/positions/<int:position_id>/insight", methods=["GET"])
def get_position_insight(position_id):
    """Deterministic position guidance from the DNA insight library.

    Pulls the same open instruments and states as /positions/<id>/valuation and
    /state_all/<symbol>, then runs dna_insight_library.compose() per holding.
    The `insight` field is the library's output verbatim -- no reshaping, no
    free text. Upstream (Massive) failures map to 502/503 like valuation.
    """
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "position not found"}), 404
    instruments = conn.execute(
        "SELECT * FROM position_instruments WHERE position_id=? AND status='OPEN' ORDER BY id",
        (position_id,),
    ).fetchall()
    states = _dna_context(conn, row["symbol"], row["opened_at"])["states"]
    conn.close()
    shaped = [positions.shape_instrument(r) for r in instruments]
    for state in states:
        state["timeframe"] = _canonical_timeframe(state.get("timeframe"))

    try:
        valuation = _compute_valuation(row["symbol"], shaped)
    except massive_options.UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status
    except massive_ohlc._UpstreamError as exc:
        status = 503 if exc.status in (429, 503) else 502
        return jsonify({"error": "upstream", "detail": exc.detail, "upstream_status": exc.status}), status

    is_short = (row["direction"] or "").upper() == "SHORT"
    holdings = []
    stock = valuation.get("stock")
    if stock:
        instrument = "short shares" if is_short else "shares"
        holdings.append({
            "leg_ids": stock.get("leg_ids") or [],
            "instrument": instrument,
            "insight": dna_insight_library.compose(states, _insight_holding_for_stock(stock), instrument),
        })
    for option in valuation.get("options") or []:
        contract_type = (option.get("contract") or {}).get("type")
        if is_short:
            instrument = "short call" if contract_type == "CALL" else "short put"
        else:
            instrument = "long call" if contract_type == "CALL" else "long put"
        holdings.append({
            "leg_ids": option.get("leg_ids") or [],
            "instrument": instrument,
            "insight": dna_insight_library.compose(states, _insight_holding_for_option(option), instrument),
        })
    return jsonify({
        "position_id": position_id,
        "symbol": row["symbol"],
        "direction": row["direction"],
        "holdings": holdings,
    })


init_db()
paper_db.init_db(PAPER_DB_PATH)
app.register_blueprint(
    create_paper_blueprint(str(PAPER_DB_PATH), STATE_API_TOKEN, cloud_state_provider(str(DB_PATH)))
)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"DNA webhook receiver starting. Database: {DB_PATH}")
    print(f"Local endpoint: http://localhost:{port}/webhook")
    app.run(host="0.0.0.0", port=port, debug=False)
