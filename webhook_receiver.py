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
            bar_time, rsi, ema21_distance_atr, received_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        symbol, timeframe, payload.get("phase"), payload.get("health"),
        payload.get("score"), payload.get("confidence"), payload.get("momentum"),
        payload.get("status"), payload.get("action"),
        int(bool(payload.get("exhaustion_warning"))), payload.get("reload_quality"),
        payload.get("htf_phase"), payload.get("campaign_alignment"),
        payload.get("last_fail_type"), payload.get("close"), event,
        payload.get("time"), payload.get("rsi"), payload.get("ema21_distance_atr"), now,
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


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"DNA webhook receiver starting. Database: {DB_PATH}")
    print(f"Local endpoint: http://localhost:{port}/webhook")
    app.run(host="0.0.0.0", port=port, debug=False)
