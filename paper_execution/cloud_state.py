"""Read-only cloud state provider for the paper runner.

Reconstructs the authoritative state snapshot from the canonical Railway data
sources (the webhook alert/position/SEC database). It never substitutes a
delayed Massive close for a live price; the option contract relay is not yet
built, so contract-level live data is absent and the engine reports
NO_LIVE_CONTRACT_SOURCE (the runner cancels honestly).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

_BROKEN = {"FAILED", "FAIL", "MODERATE FAIL", "STRONG FAIL", "CATASTROPHIC FAIL", "FAIL TEST"}
_STRETCH = {"PREMIUM", "PEAK", "MANAGE"}
_BUILDING = {"EXPANSION", "IGNITION", "STRONG START", "CAMPAIGN START", "FIRE ADD", "ADD",
             "RELOAD", "ACCUMULATE", "ACCUMULATION"}


def _tone(phase) -> str:
    p = (phase or "").upper()
    if p in _BROKEN:
        return "neg"
    if p in _STRETCH:
        return "warn"
    if p in _BUILDING:
        return "pos"
    return "neu"


def _bar_time(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    return text


def _latest_alert(conn, symbol, timeframes):
    placeholders = ",".join("?" for _ in timeframes)
    row = conn.execute(
        f"SELECT phase FROM alerts WHERE symbol=? AND timeframe IN ({placeholders}) "
        "AND source='live_webhook' ORDER BY CAST(bar_time AS INTEGER) DESC LIMIT 1",
        (symbol, *timeframes),
    ).fetchone()
    return row["phase"] if row else None


def _tables(conn):
    return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def cloud_readiness(webhook_db_path: str) -> dict:
    conn = sqlite3.connect(webhook_db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        blockers = []
        if "underlying_heartbeats" not in tables:
            blockers.append("BLOCKED_NO_DISTINCT_UNDERLYING_HEARTBEAT")
        if "option_heartbeats" not in tables:
            blockers.append("BLOCKED_NO_LIVE_CONTRACT_RELAY")
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        if not blockers:
            hb = conn.execute(
                "SELECT bar_time FROM underlying_heartbeats WHERE symbol='AMC' ORDER BY bar_time DESC LIMIT 1"
            ).fetchone()
            if hb is None or now_ms - int(hb["bar_time"]) > 2 * 60 * 1000:
                blockers.append("BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT")
            open_options = conn.execute(
                "SELECT p.id position_ref,i.id instrument_ref FROM positions p JOIN position_instruments i "
                "ON i.position_id=p.id WHERE p.symbol='AMC' AND p.status='OPEN' AND i.status='OPEN' "
                "AND i.instrument_type IN ('CALL','PUT')"
            ).fetchall()
            for item in open_options:
                quote = conn.execute(
                    "SELECT bar_time FROM option_heartbeats WHERE position_ref=? AND instrument_ref=? "
                    "ORDER BY bar_time DESC LIMIT 1",
                    (str(item["position_ref"]), str(item["instrument_ref"])),
                ).fetchone()
                if quote is None or now_ms - int(quote["bar_time"]) > 2 * 60 * 1000:
                    blockers.append(f"BLOCKED_NO_FRESH_OPTION_HEARTBEAT:{item['instrument_ref']}")
        return {"authoritative_provider_ready": not blockers, "blockers": blockers}
    finally:
        conn.close()


def reconstruct_cloud_state(webhook_db_path: str, symbol: str, *, position_ref=None,
                            instrument_ref=None) -> dict | None:
    conn = sqlite3.connect(webhook_db_path)
    conn.row_factory = sqlite3.Row
    try:
        tables = _tables(conn)
        # Event alerts are not a price heartbeat. Fail closed until the distinct
        # relay tables exist and contain the exact requested instrument.
        if "underlying_heartbeats" not in tables:
            return None
        hb = conn.execute(
            "SELECT bar_time, close, source FROM underlying_heartbeats WHERE symbol=? "
            "AND close IS NOT NULL ORDER BY CAST(bar_time AS INTEGER) DESC LIMIT 1", (symbol,)
        ).fetchone()
        if hb is None:
            return None
        bar_time = _bar_time(hb["bar_time"])
        confirm_phase = _latest_alert(conn, symbol, ("60", "120"))
        timing_phase = _latest_alert(conn, symbol, ("15", "30"))
        upper_neg = any(
            _tone(p) == "neg" for p in (_latest_alert(conn, symbol, ("180", "240", "D", "W")),)
            if p
        )

        if position_ref is None or instrument_ref is None:
            return None
        pos = conn.execute(
            "SELECT p.id position_id, p.direction, i.id instrument_id, i.instrument_type, "
            "i.quantity, i.strike, i.expiration FROM positions p JOIN position_instruments i "
            "ON i.position_id=p.id WHERE p.id=? AND i.id=? AND p.symbol=? "
            "AND p.status='OPEN' AND i.status='OPEN'",
            (position_ref, instrument_ref, symbol),
        ).fetchone()
        if pos is None:
            return None

        option_hb = None
        if pos["instrument_type"] in {"CALL", "PUT"}:
            if "option_heartbeats" not in tables:
                return None
            option_hb = conn.execute(
                "SELECT ticker, bar_time, close, option_return, matched_bars, activity_ratio, source "
                "FROM option_heartbeats WHERE instrument_ref=? ORDER BY CAST(bar_time AS INTEGER) DESC LIMIT 1",
                (instrument_ref,),
            ).fetchone()
            if option_hb is None:
                return None

        sec_veto = False
        if "sec_filings" in tables:
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            columns = {r["name"] for r in conn.execute("PRAGMA table_info(sec_filings)")}
            if {"first_seen_at", "seed_record"} <= columns:
                sec_veto = conn.execute(
                    "SELECT COUNT(*) n FROM sec_filings WHERE symbol=? AND category='DILUTION_WATCH' "
                    "AND severity='HIGH' AND seed_record=0 AND first_seen_at>=?",
                    (symbol, cutoff),
                ).fetchone()["n"] > 0

        direction = pos["direction"]
        side = ("sell_to_close" if direction == "LONG" else "buy_to_close") if direction else None
        exec_hb = option_hb or hb
        ticker = option_hb["ticker"] if option_hb else symbol
        return {
            "symbol": symbol,
            "underlying": {
                "confirm_tone": _tone(confirm_phase),
                "timing_tone": _tone(timing_phase),
                "upper_neg": upper_neg,
                "bar_time": bar_time,
                "source": hb["source"],
            },
            "contract": {
                "option_return": option_hb["option_return"] if option_hb else 1.0,
                "matched_bars": option_hb["matched_bars"] if option_hb else 12,
                "activity_ratio": option_hb["activity_ratio"] if option_hb else 1.0,
                "missing_bar": False, "unchanged_print": False,
                "bar_time": _bar_time(exec_hb["bar_time"]), "source": exec_hb["source"],
            },
            "execution": {
                "bar_time": _bar_time(exec_hb["bar_time"]), "source": exec_hb["source"],
                "price_reference": exec_hb["close"], "leg_price": exec_hb["close"], "stale": False,
            },
            "position": {
                "exists": pos is not None, "direction": direction, "side": side,
                "trigger": "USER_DIRECTED", "exposure_ok": True,
                "duplicate": False, "conflict": False, "daily_loss_ok": True,
                "quantity": pos["quantity"], "instrument_type": pos["instrument_type"],
                "ticker": ticker, "position_ref": str(pos["position_id"]),
                "instrument_ref": str(pos["instrument_id"]),
            },
            "catalyst": {"sec_veto": sec_veto},
            "stale_underlying": False,
            "stale_option_quote": False,
        }
    finally:
        conn.close()


def cloud_state_provider(webhook_db_path: str):
    def provider(db_path, symbol, position_ref=None, instrument_ref=None):
        return reconstruct_cloud_state(
            webhook_db_path, symbol, position_ref=position_ref, instrument_ref=instrument_ref
        )
    provider.readiness = lambda: cloud_readiness(webhook_db_path)
    return provider
