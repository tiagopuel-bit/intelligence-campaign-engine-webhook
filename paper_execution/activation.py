"""Atomic activation of the January 2027 PAPER_ONLY experiment.

Activation occurs only after AMC has a distinct 1-minute underlying heartbeat
and every open AMC option instrument has an exact fresh contract heartbeat.
The experiment, immutable starting snapshot, isolated paper holdings, cash and
global auto switch are committed together in the paper database.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from paper_execution import db
from paper_execution.portfolio import asset_eligible, load_reliability_mask
from paper_execution.store import frozen_goal_hash, tracked_symbols

ROOT = Path(__file__).resolve().parents[1]
MAX_AGE_MS = 2 * 60 * 1000


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def activate_if_ready(paper_db_path, webhook_db_path, symbols=("AMC",)) -> dict:
    # Normalize: a bare string (legacy single-symbol callers) is one symbol.
    if isinstance(symbols, str):
        symbols = (symbols,)
    symbols = tuple(symbols) or ("AMC",)
    anchor = symbols[0]
    additional = symbols[1:]

    paper = db.connect(paper_db_path)
    existing = paper.execute(
        "SELECT id FROM pe_experiments WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if existing:
        paper.close()
        return {"status": "ALREADY_ACTIVE", "experiment_id": existing["id"]}

    source = sqlite3.connect(str(webhook_db_path))
    source.row_factory = sqlite3.Row
    try:
        holdings = []
        anchor_hb = None
        for symbol in symbols:
            hb = source.execute(
                "SELECT bar_time, close FROM underlying_heartbeats WHERE symbol=? "
                "ORDER BY bar_time DESC LIMIT 1", (symbol,),
            ).fetchone()
            if hb is None or _now_ms() - int(hb["bar_time"]) > MAX_AGE_MS:
                paper.close()
                return {"status": "BLOCKED", "blocker": "BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT",
                        "symbol": symbol}
            if symbol == anchor:
                anchor_hb = hb
            rows = source.execute(
                "SELECT p.id position_ref, i.id instrument_ref, i.instrument_type, i.strike, "
                "i.expiration, i.quantity, i.entry_price FROM positions p JOIN position_instruments i "
                "ON i.position_id=p.id WHERE p.symbol=? AND p.status='OPEN' AND i.status='OPEN' ORDER BY i.id",
                (symbol,),
            ).fetchall()
            if not rows:
                paper.close()
                return {"status": "BLOCKED", "blocker": "BLOCKED_NO_STARTING_HOLDINGS",
                        "symbol": symbol}
            for row in rows:
                instrument_type = row["instrument_type"]
                if instrument_type == "SHARE":
                    ticker, price, quote_time = symbol, float(hb["close"]), int(hb["bar_time"])
                else:
                    quote = source.execute(
                        "SELECT ticker, close, bar_time FROM option_heartbeats WHERE instrument_ref=? "
                        "AND position_ref=? ORDER BY bar_time DESC LIMIT 1",
                        (str(row["instrument_ref"]), str(row["position_ref"])),
                    ).fetchone()
                    if quote is None or _now_ms() - int(quote["bar_time"]) > MAX_AGE_MS:
                        paper.close()
                        return {"status": "BLOCKED", "blocker": "BLOCKED_NO_FRESH_OPTION_HEARTBEAT",
                                "instrument_ref": str(row["instrument_ref"])}
                    ticker, price, quote_time = quote["ticker"], float(quote["close"]), int(quote["bar_time"])
                multiplier = 100 if instrument_type in {"CALL", "PUT"} else 1
                holdings.append({**dict(row), "symbol": symbol, "ticker": ticker, "price": price,
                                 "market_value": price * float(row["quantity"]) * multiplier,
                                 "quote_time": quote_time})
    finally:
        source.close()

    goal = json.loads((ROOT / "paper_execution" / "experiment_goal_v1.json").read_text())
    start_at = datetime.fromtimestamp(int(anchor_hb["bar_time"]) / 1000, tz=timezone.utc).isoformat()
    total_start = 100.0 + sum(item["market_value"] for item in holdings)
    milestones = goal["milestones"]["tiers"]
    try:
        paper.execute("BEGIN IMMEDIATE")
        existing = paper.execute(
            "SELECT id FROM pe_experiments WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if existing:
            paper.rollback()
            return {"status": "ALREADY_ACTIVE", "experiment_id": existing["id"]}
        cur = paper.execute(
            "INSERT INTO pe_experiments (version,symbol,start_at,end_at,starting_cash,starting_value_method,"
            "target_value_jan2027,target_return_pct,max_drawdown_pct,max_amc_exposure,"
            "max_exposure_per_option_expiry,deposit_policy,allowed_actions,benchmark_symbol,"
            "benchmark_success_criteria,min_observation_count,max_daily_paper_loss,max_orders_per_day,"
            "max_consecutive_failed_proposals,milestones_json,amc_target_floor_pct,confidence_status,"
            "auto_mode,auto_enabled_global,status,contract_sha256,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (1, anchor, start_at, goal["chronology"]["end"]["value"], 100.0,
             goal["starting_portfolio"]["valuation_method"]["value"], 15000.0,
             ((15000.0 / total_start) - 1.0) * 100.0 if total_start else None, 25.0, 0.70, 0.25,
             goal["deposits_withdrawals"]["policy"]["value"], ",".join(goal["actions"]["allowed"]),
             "AMC", json.dumps(goal["benchmarks"]["value"]), 30, 0.05, 3, 3,
             json.dumps(milestones), 30.0, "INTACT", "AUTO_IF_VERY_HIGH_PAPER", 1, "ACTIVE",
             frozen_goal_hash(), datetime.now(timezone.utc).isoformat()),
        )
        experiment_id = cur.lastrowid
        frozen_at = datetime.now(timezone.utc).isoformat()
        paper.execute("INSERT INTO pe_paper_cash (experiment_id,cash,updated_at) VALUES (?,?,?)",
                      (experiment_id, 100.0, frozen_at))
        paper.execute(
            "INSERT INTO pe_auto_switches (experiment_id,scope,position_ref,auto_enabled,updated_at) "
            "VALUES (?,?,?,?,?)", (experiment_id, "GLOBAL", "", 1, frozen_at),
        )
        for symbol in additional:
            paper.execute(
                "INSERT INTO pe_experiment_symbols (experiment_id,symbol) VALUES (?,?)",
                (experiment_id, symbol),
            )
        for item in holdings:
            paper.execute(
                "INSERT INTO pe_starting_holdings (experiment_id,instrument_type,ticker,strike,expiration,"
                "quantity,entry_price,market_value,frozen_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (experiment_id, item["instrument_type"], item["ticker"], item["strike"], item["expiration"],
                 item["quantity"], item["entry_price"], item["market_value"], frozen_at),
            )
            paper.execute(
                "INSERT INTO pe_paper_positions (experiment_id,symbol,instrument_type,ticker,quantity,updated_at) "
                "VALUES (?,?,?,?,?,?)", (experiment_id, item["symbol"], item["instrument_type"], item["ticker"],
                                         item["quantity"], frozen_at),
            )
        paper.commit()
        return {"status": "ACTIVATED", "experiment_id": experiment_id,
                "starting_portfolio_value": total_start, "holding_count": len(holdings)}
    except Exception:
        paper.rollback()
        raise
    finally:
        paper.close()


def join_symbol_if_ready(paper_db_path, webhook_db_path, experiment_id, symbol) -> dict:
    """Add a symbol to an already-ACTIVE experiment's tracked set.

    Unlike initial activation, a newly joined asset starts at zero position in
    the shared cash pool; it is funded by a future ``open`` proposal under the
    existing allocation/floor checks in ``runner.py``. No holdings required.

    Fails closed with a clear reason:
    - ``ASSET_NOT_ELIGIBLE`` — symbol fails the reliability-mask eligibility gate.
    - ``BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT`` — no fresh underlying heartbeat.
    - ``ALREADY_TRACKED`` — symbol already in the experiment (anchor or joined).
    - ``EXPERIMENT_NOT_ACTIVE`` / ``EXPERIMENT_NOT_FOUND``.
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"status": "BLOCKED", "blocker": "INVALID_SYMBOL"}

    if not asset_eligible(load_reliability_mask(), symbol):
        return {"status": "BLOCKED", "blocker": "ASSET_NOT_ELIGIBLE", "symbol": symbol}

    source = sqlite3.connect(str(webhook_db_path))
    source.row_factory = sqlite3.Row
    try:
        hb = source.execute(
            "SELECT bar_time FROM underlying_heartbeats WHERE symbol=? "
            "ORDER BY bar_time DESC LIMIT 1", (symbol,),
        ).fetchone()
        if hb is None or _now_ms() - int(hb["bar_time"]) > MAX_AGE_MS:
            return {"status": "BLOCKED", "blocker": "BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT",
                    "symbol": symbol}
    finally:
        source.close()

    paper = db.connect(paper_db_path)
    try:
        exp = paper.execute("SELECT status FROM pe_experiments WHERE id=?", (experiment_id,)).fetchone()
        if exp is None:
            return {"status": "BLOCKED", "blocker": "EXPERIMENT_NOT_FOUND",
                    "experiment_id": experiment_id}
        if exp["status"] != "ACTIVE":
            return {"status": "BLOCKED", "blocker": "EXPERIMENT_NOT_ACTIVE",
                    "experiment_id": experiment_id}
        if symbol in tracked_symbols(paper, experiment_id):
            return {"status": "ALREADY_TRACKED", "experiment_id": experiment_id, "symbol": symbol}
        paper.execute("BEGIN IMMEDIATE")
        paper.execute(
            "INSERT INTO pe_experiment_symbols (experiment_id, symbol) VALUES (?,?)",
            (experiment_id, symbol),
        )
        paper.commit()
        return {"status": "JOINED", "experiment_id": experiment_id, "symbol": symbol}
    except Exception:
        paper.rollback()
        raise
    finally:
        paper.close()
