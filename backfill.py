"""Historical backfill: replay pine_replay_v12_6_19 over Massive OHLC into alerts.

Bridges the fidelity-tested replay engine (frozen at v12.6.19) with Massive
historical bars, then writes the shaped rows into the live `alerts` table with
`source='backfill_replay'`. Replayed rows must never look like a real
TradingView alert: version-gap fields (session, active_*) and anything the
frozen replay engine doesn't emit (phase, momentum, status, action, ...) are
NULL -- never invented.

Runs inside the webhook process (a background thread) so it can reach the
Railway volume DB. Massive fetches share the global rate limiter.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import requests

from lib import pine_replay_v12_6_19 as replay
from massive_ohlc import BASE_URL, api_key, limiter

SYMBOLS = ("AMC", "GME")

# (db timeframe label, tf_minutes, multiplier, span)
LADDER = [
    ("3", 3, 3, "minute"),
    ("5", 5, 5, "minute"),
    ("15", 15, 15, "minute"),
    ("30", 30, 30, "minute"),
    ("60", 60, 60, "minute"),
    ("120", 120, 120, "minute"),
    ("180", 180, 180, "minute"),
    ("240", 240, 240, "minute"),
    ("1D", 1440, 1, "day"),
    ("1W", 10080, 1, "week"),
]

# Same priority order as Pine's currentBarEvent (STRONG START > ... > IGNITION TEST).
EVENT_PRIORITY = [
    ("STRONG START", "STRONG START"),
    ("CAMPAIGN START", "CAMPAIGN START"),
    ("FIRE ADD", "FIRE ADD"),
    ("ACCUMULATE", "ACCUMULATE"),
    ("IGNITION", "IGNITION"),
    ("ADD", "ADD"),
    ("PREMIUM", "PREMIUM"),
    ("MANAGE", "MANAGE"),
    ("PEAK", "PEAK"),
    ("FAIL (any severity)", "FAIL"),
    ("FAIL TEST", "FAIL TEST"),
    ("RELOAD", "RELOAD"),
    ("START TEST", "START TEST"),
    ("IGNITION TEST", "IGNITION TEST"),
]

INSERT_SQL = """
    INSERT INTO alerts (
        symbol, timeframe, phase, health, score, confidence, momentum, status,
        action, exhaustion_warning, reload_quality, htf_phase, campaign_alignment,
        last_fail_type, close, bar_event, bar_time, rsi, ema21_distance_atr,
        session, active_trade, active_entry, active_stop, active_target,
        active_trade_source, active_trade_open_pct, source, received_at
    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def _fetch(symbol: str, mult: int, span: str, start: str, end: str) -> list[dict]:
    import time

    rows: list[dict] = []
    url = f"{BASE_URL}/v2/aggs/ticker/{symbol}/range/{mult}/{span}/{start}/{end}"
    params = {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": api_key()}
    while url:
        limiter.wait()
        response = requests.get(url, params=params, timeout=90)
        if response.status_code == 429:
            try:
                delay = min(65.0, max(1.0, float(response.headers.get("Retry-After", 60))))
            except ValueError:
                delay = 60.0
            time.sleep(delay)
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Massive {symbol} {mult}/{span}: HTTP {response.status_code}: {response.text[:200]}")
        payload = response.json()
        rows.extend(payload.get("results", []))
        nxt = payload.get("next_url")
        if not nxt:
            break
        url = nxt + ("&" if "?" in nxt else "?") + f"apiKey={api_key()}"
        params = {}
    return rows


def _to_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "Volume", "t_utc"])
    df = pd.DataFrame({
        "open": [r["o"] for r in rows],
        "high": [r["h"] for r in rows],
        "low": [r["l"] for r in rows],
        "close": [r["c"] for r in rows],
        "Volume": [r["v"] for r in rows],
        "t_utc": pd.to_datetime([r["t"] for r in rows], unit="ms", utc=True).tz_localize(None),
    })
    return df.sort_values("t_utc", kind="mergesort").drop_duplicates("t_utc").reset_index(drop=True)


def _epoch_ms(t) -> int:
    return int(pd.Timestamp(t).tz_localize("UTC").timestamp() * 1000)


def _live_cutoff(conn: sqlite3.Connection, symbol: str, label: str) -> int | None:
    """Earliest live_webhook bar_time (epoch ms) for this symbol/timeframe, or None."""
    row = conn.execute(
        "SELECT MIN(CAST(bar_time AS INTEGER)) FROM alerts "
        "WHERE symbol=? AND timeframe=? AND source='live_webhook'",
        (symbol, label),
    ).fetchone()
    return row[0] if row and row[0] not in (None, 0) else None


def _replay_one(symbol: str, label: str, tf_minutes: int, mult: int, span: str,
                start: str, end: str) -> tuple[list[tuple], int]:
    """Fetch + replay one (symbol, timeframe); return (insert_rows, bar_count)."""
    rows = _fetch(symbol, mult, span, start, end)
    df = _to_df(rows)
    if df.empty:
        return [], 0
    out = replay.replay(df, tf_minutes)
    now = datetime.now(timezone.utc).isoformat()

    event_cols = [c for c, _ in EVENT_PRIORITY]
    inserts: list[tuple] = []
    for i in range(len(out)):
        event = None
        for col, label_out in EVENT_PRIORITY:
            if bool(out[col].iloc[i]):
                event = label_out
                break
        if event is None:
            continue
        bar_time = str(_epoch_ms(out["t_utc"].iloc[i]))
        row = (
            symbol, label, None,  # phase
            int(out["campaignHealth"].iloc[i]) if not pd.isna(out["campaignHealth"].iloc[i]) else None,
            int(out["campaignScore"].iloc[i]) if not pd.isna(out["campaignScore"].iloc[i]) else None,
            int(out["phaseConfidence"].iloc[i]) if not pd.isna(out["phaseConfidence"].iloc[i]) else None,
            None, None, None,  # momentum, status, action
            None, None, None, None, None,  # exhaustion_warning, reload_quality, htf_phase, campaign_alignment, last_fail_type
            df["close"].iloc[i],
            event,
            bar_time,
            float(out["rsi"].iloc[i]) if not pd.isna(out["rsi"].iloc[i]) else None,
            float(out["distanceFromEma21Atr"].iloc[i]) if not pd.isna(out["distanceFromEma21Atr"].iloc[i]) else None,
            None, None, None, None, None, None, None,  # session, active_* (version gap)
            "backfill_replay",
            now,
        )
        inserts.append(row)
    return inserts, len(df)


def run_backfill(db_path: str, start: str = "2024-08-12", end: str | None = None) -> dict:
    if end is None:
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    conn = sqlite3.connect(db_path, timeout=60)
    conn.execute("PRAGMA busy_timeout=5000")
    report: dict = {"symbols": {}}
    total_inserted = 0
    for symbol in SYMBOLS:
        report["symbols"][symbol] = {}
        for label, tf_minutes, mult, span in LADDER:
            cutoff = _live_cutoff(conn, symbol, label)
            print(f"[backfill] {symbol} {label}: live_cutoff={cutoff}", flush=True)
            inserts, bar_count = _replay_one(symbol, label, tf_minutes, mult, span, start, end)
            # No-collision: keep only bars strictly before live coverage begins.
            kept = [r for r in inserts if cutoff is None or int(r[16]) < cutoff]
            conn.executemany(INSERT_SQL, kept)
            conn.commit()
            report["symbols"][symbol][label] = {
                "bars": bar_count,
                "event_rows": len(inserts),
                "inserted": len(kept),
            }
            total_inserted += len(kept)
            print(f"[backfill] {symbol} {label}: bars={bar_count} events={len(inserts)} inserted={len(kept)}", flush=True)
    conn.close()
    report["total_inserted"] = total_inserted
    return report


if __name__ == "__main__":
    db = os.environ.get("DATABASE_PATH") or (
        os.path.join(os.environ["RAILWAY_VOLUME_MOUNT_PATH"], "dna_alerts.db")
        if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") else
        os.path.join(os.path.dirname(__file__), "dna_alerts.db")
    )
    import json
    print(json.dumps(run_backfill(db), indent=2))
