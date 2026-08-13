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
from flask import Flask, request, jsonify
import sqlite3
import hmac
import os
import ipaddress
import uuid
from datetime import datetime, timezone
from pathlib import Path

import massive_ohlc
import positions


# -- Database path -----------------------------------------------------------

def resolve_db_path() -> Path:
    if os.environ.get("DATABASE_PATH"):
        return Path(os.environ["DATABASE_PATH"]).expanduser()
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "dna_alerts.db"
    return Path(__file__).parent / "dna_alerts.db"


DB_PATH = resolve_db_path()

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


# Columns added by Pine v12.6.21's additive webhook payload (Trade Box zones).
# Kept here so both the CREATE TABLE (fresh DBs) and the idempotent migration
# (existing DBs) stay in sync.
_TRADE_BOX_COLUMNS = {
    "active_trade": "INTEGER",
    "active_entry": "REAL",
    "active_stop": "REAL",
    "active_target": "REAL",
    "active_trade_source": "TEXT",
    "active_trade_open_pct": "REAL",
}


def _ensure_trade_box_columns(conn):
    """Idempotently add Trade Box columns to an existing alerts table.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, so we consult PRAGMA table_info
    and only ALTER what is missing. Safe to run on every startup against a
    live DB: existing rows keep their data and simply read NULL for the new
    columns.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(alerts)")}
    for name, ddl in _TRADE_BOX_COLUMNS.items():
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
    _ensure_trade_box_columns(conn)
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
    if payload.get("event"):
        return payload["event"]
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


# -- Routes ------------------------------------------------------------------

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

    symbol = payload.get("symbol", "UNKNOWN")
    timeframe = payload.get("timeframe", "UNKNOWN")
    event = infer_event_from_payload(payload)
    now = datetime.now(timezone.utc).isoformat()

    conn = get_db()
    conn.execute("""
        INSERT INTO alerts (symbol, timeframe, phase, health, score, confidence,
            momentum, status, action, exhaustion_warning, reload_quality,
            htf_phase, campaign_alignment, last_fail_type, close, bar_event,
            bar_time, rsi, ema21_distance_atr, session, active_trade,
            active_entry, active_stop, active_target, active_trade_source,
            active_trade_open_pct, received_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        symbol, timeframe, payload.get("phase"), payload.get("health"),
        payload.get("score"), payload.get("confidence"), payload.get("momentum"),
        payload.get("status"), payload.get("action"),
        int(bool(payload.get("exhaustion_warning"))), payload.get("reload_quality"),
        payload.get("htf_phase"), payload.get("campaign_alignment"),
        payload.get("last_fail_type"), payload.get("close"), event,
        payload.get("time"), payload.get("rsi"), payload.get("ema21_distance_atr"),
        payload.get("session"),
        _parse_int_flag(payload.get("active_trade")),
        _parse_float_or_none(payload.get("active_entry")),
        _parse_float_or_none(payload.get("active_stop")),
        _parse_float_or_none(payload.get("active_target")),
        _parse_str_or_none(payload.get("active_trade_source")),
        _parse_float_or_none(payload.get("active_trade_open_pct")),
        now,
    ))

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
        SELECT * FROM alerts WHERE symbol=? AND timeframe=? ORDER BY id DESC LIMIT 1
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
    ).fetchall()]
    if not timeframes:
        conn.close()
        return jsonify({"error": f"no alerts recorded yet for {symbol} on any timeframe"}), 404
    states = []
    for tf in timeframes:
        latest = conn.execute("""
            SELECT * FROM alerts WHERE symbol=? AND timeframe=? ORDER BY id DESC LIMIT 1
        """, (symbol, tf)).fetchone()
        watch = conn.execute("""
            SELECT * FROM watch_state WHERE symbol=? AND timeframe=?
        """, (symbol, tf)).fetchone()
        if latest is not None:
            states.append(_shape_state(symbol, tf, latest, watch))
    conn.close()
    return jsonify({"symbol": symbol, "timeframe_count": len(states), "states": states})


# Symbols excluded from the asset list: internal pipeline smoke-test rows,
# not real market data. Same allowlist as scripts/cleanup_test_symbols.py.
_TEST_SYMBOLS = {"PUBTEST", "TEST", "TEST2", "TEST_PING"}


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
    rows = conn.execute("""
        SELECT symbol,
               COUNT(DISTINCT timeframe) AS timeframe_count,
               COUNT(*) AS alert_count,
               MAX(received_at) AS last_updated
        FROM alerts
        GROUP BY symbol
        ORDER BY symbol
    """).fetchall()
    conn.close()
    assets = [
        {
            "symbol": r["symbol"],
            "timeframe_count": r["timeframe_count"],
            "alert_count": r["alert_count"],
            "last_updated": r["last_updated"],
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
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, OPTIONS"
    return response


@app.route("/history/<symbol>/<timeframe>", methods=["GET"])
def get_history(symbol, timeframe):
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    conn = get_db()
    rows = conn.execute("""
        SELECT bar_event, phase, health, close, bar_time, received_at
        FROM alerts WHERE symbol=? AND timeframe=? ORDER BY id DESC LIMIT 50
    """, (symbol, timeframe)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


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
    ).fetchall()]
    states = []
    for tf in timeframes:
        latest = conn.execute(
            "SELECT * FROM alerts WHERE symbol=? AND timeframe=? AND received_at>=? ORDER BY id DESC LIMIT 1",
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
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db()
    row = conn.execute("SELECT * FROM positions WHERE id=?", (position_id,)).fetchone()
    if row is None:
        conn.close()
        return jsonify({"error": "position not found"}), 404
    if clean.get("status") == "CLOSED" and "closed_at" not in clean:
        clean["closed_at"] = now
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


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"DNA webhook receiver starting. Database: {DB_PATH}")
    print(f"Local endpoint: http://localhost:{port}/webhook")
    app.run(host="0.0.0.0", port=port, debug=False)
