"""Append-only persistence for the paper execution experiment (PAPER_ONLY).

Provides idempotent proposal creation, compare-and-set lifecycle transitions,
global/per-position kill switches, and restart-safe due-proposal queries. No
scheduler, no sleeping, no broker path.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from paper_execution.policy import validate_transition
from paper_execution.engine import auto_mode_allowed

ROOT = Path(__file__).resolve().parents[1]


class ProposalNotFound(KeyError):
    pass


class TransitionConflict(RuntimeError):
    pass


class InvalidTransition(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def frozen_policy_hash() -> str:
    return hashlib.sha256((ROOT / "paper_execution" / "policy_v1.json").read_bytes()).hexdigest()


def frozen_goal_hash() -> str:
    return hashlib.sha256((ROOT / "paper_execution" / "experiment_goal_v1.json").read_bytes()).hexdigest()


def frozen_corrections_hash() -> str:
    return hashlib.sha256((ROOT / "paper_execution" / "policy_corrections_v1.1.json").read_bytes()).hexdigest()


def frozen_corrections_v12_hash() -> str:
    return hashlib.sha256((ROOT / "paper_execution" / "policy_corrections_v1.2.json").read_bytes()).hexdigest()


AUTO_MODE = "AUTO_IF_VERY_HIGH_PAPER"


def create_experiment(conn, *, version, symbol, start_at, end_at, starting_cash,
                      starting_value_method, target_value_jan2027, target_return_pct,
                      max_drawdown_pct, max_amc_exposure, max_exposure_per_option_expiry,
                      deposit_policy, allowed_actions, benchmark_symbol,
                      benchmark_success_criteria, min_observation_count,
                      max_daily_paper_loss, max_orders_per_day,
                      max_consecutive_failed_proposals, milestones_json,
                      amc_target_floor_pct, confidence_status, contract_sha256) -> int:
    cur = conn.execute(
        "INSERT INTO pe_experiments (version, symbol, start_at, end_at, starting_cash, "
        "starting_value_method, target_value_jan2027, target_return_pct, max_drawdown_pct, "
        "max_amc_exposure, max_exposure_per_option_expiry, deposit_policy, allowed_actions, "
        "benchmark_symbol, benchmark_success_criteria, min_observation_count, "
        "max_daily_paper_loss, max_orders_per_day, max_consecutive_failed_proposals, "
        "milestones_json, amc_target_floor_pct, confidence_status, auto_mode, auto_enabled_global, "
        "status, contract_sha256, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (version, symbol, start_at, end_at, starting_cash, starting_value_method,
         target_value_jan2027, target_return_pct, max_drawdown_pct, max_amc_exposure,
         max_exposure_per_option_expiry, deposit_policy, allowed_actions, benchmark_symbol,
         benchmark_success_criteria, min_observation_count, max_daily_paper_loss,
         max_orders_per_day, max_consecutive_failed_proposals, milestones_json,
         amc_target_floor_pct, confidence_status, "APPROVAL_REQUIRED", 0, "ACTIVE",
         contract_sha256, _now_iso()),
    )
    experiment_id = cur.lastrowid
    conn.execute(
        "INSERT OR IGNORE INTO pe_paper_cash (experiment_id, cash, updated_at) VALUES (?,?,?)",
        (experiment_id, starting_cash, _now_iso()),
    )
    conn.commit()
    return experiment_id


def create_proposal(conn, *, experiment_id, idempotency_key, action, mode, symbol,
                    policy_sha256, time_sensitive_reason, very_high,
                    very_high_missing_roots, expires_at, cancel_condition,
                    evidence_roots, parent_proposal_id=None, version=1,
                    position_ref=None, instrument_ref=None) -> int:
    """Create a proposal idempotently. Duplicate idempotency keys return the
    existing proposal id instead of triggering twice."""
    now = _now_iso()
    cur = conn.execute(
        "INSERT OR IGNORE INTO pe_order_proposals "
        "(experiment_id, idempotency_key, parent_proposal_id, version, policy_version, policy_sha256, "
        " action, mode, symbol, position_ref, instrument_ref, time_sensitive_reason, very_high, very_high_missing_roots, "
        " status, current_status, expires_at, cancel_condition, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (experiment_id, idempotency_key, parent_proposal_id, version, 1, policy_sha256,
         action, mode, symbol, position_ref, instrument_ref, time_sensitive_reason, 1 if very_high else 0,
         json.dumps(very_high_missing_roots), "PENDING_APPROVAL", "PENDING_APPROVAL",
         expires_at, cancel_condition, now),
    )
    if cur.rowcount == 1:
        proposal_id = cur.lastrowid
        for root in evidence_roots:
            conn.execute(
                "INSERT INTO pe_proposal_evidence (proposal_id, root, present, raw_fields, "
                " missing_evidence, contradictions, veto) VALUES (?,?,?,?,?,?,?)",
                (proposal_id, root["root"], 1 if root.get("present") else 0,
                 json.dumps(root.get("raw_fields", {})),
                 json.dumps(root.get("missing_evidence", [])),
                 json.dumps(root.get("contradictions", [])),
                 1 if root.get("veto") else 0),
            )
        conn.execute(
            "INSERT INTO pe_proposal_events (proposal_id, from_status, to_status, at, actor, reason) "
            "VALUES (?,?,?,?,?,?)",
            (proposal_id, "DRAFT", "PENDING_APPROVAL", now, "system", ""),
        )
        conn.commit()
        return proposal_id
    row = conn.execute(
        "SELECT id FROM pe_order_proposals WHERE experiment_id=? AND idempotency_key=?",
        (experiment_id, idempotency_key),
    ).fetchone()
    conn.commit()
    return row["id"]


def transition(conn, proposal_id: int, to_status: str, *, actor: str = "system",
               reason: str = "", expected_from: str | None = None,
               commit: bool = True) -> dict:
    """Append-only lifecycle transition with an atomic compare-and-set."""
    row = conn.execute(
        "SELECT current_status FROM pe_order_proposals WHERE id=?", (proposal_id,)
    ).fetchone()
    if row is None:
        raise ProposalNotFound(proposal_id)
    from_status = row["current_status"]
    if expected_from is not None and from_status != expected_from:
        raise TransitionConflict(f"expected {expected_from}, got {from_status}")
    if not validate_transition(from_status, to_status):
        raise InvalidTransition(f"{from_status} -> {to_status}")
    now = _now_iso()
    cur = conn.execute(
        "UPDATE pe_order_proposals SET current_status=?, status=? WHERE id=? AND current_status=?",
        (to_status, to_status, proposal_id, from_status),
    )
    if cur.rowcount != 1:
        raise TransitionConflict(f"{from_status} -> {to_status} lost race")
    conn.execute(
        "INSERT INTO pe_proposal_events (proposal_id, from_status, to_status, at, actor, reason) "
        "VALUES (?,?,?,?,?,?)",
        (proposal_id, from_status, to_status, now, actor, reason),
    )
    if commit:
        conn.commit()
    return {"proposal_id": proposal_id, "from": from_status, "to": to_status}


def set_kill_switch(conn, experiment_id: int, scope: str, position_ref: str | None,
                    enabled: bool) -> None:
    ref = "" if position_ref is None else position_ref
    conn.execute(
        "INSERT INTO pe_auto_switches (experiment_id, scope, position_ref, auto_enabled, updated_at) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT(experiment_id, scope, position_ref) DO UPDATE SET "
        "auto_enabled=excluded.auto_enabled, updated_at=excluded.updated_at",
        (experiment_id, scope, ref, 1 if enabled else 0, _now_iso()),
    )
    conn.commit()


def kill_switch_active(conn, experiment_id: int, scope: str = "GLOBAL",
                       position_ref: str | None = None, symbol: str | None = None) -> bool:
    """A disabled switch wins over any pending timer.

    Checks GLOBAL (full-stop), then per-position, then per-symbol (multi-asset
    expansion). Per-symbol reuses the ``position_ref`` column for the symbol.
    """
    global_off = conn.execute(
        "SELECT auto_enabled FROM pe_auto_switches WHERE experiment_id=? AND scope='GLOBAL'",
        (experiment_id,),
    ).fetchone()
    if global_off is not None and not global_off["auto_enabled"]:
        return True
    if position_ref is not None:
        pos = conn.execute(
            "SELECT auto_enabled FROM pe_auto_switches WHERE experiment_id=? AND scope='POSITION' AND position_ref=?",
            (experiment_id, position_ref),
        ).fetchone()
        if pos is not None and not pos["auto_enabled"]:
            return True
    if symbol is not None:
        sym = conn.execute(
            "SELECT auto_enabled FROM pe_auto_switches WHERE experiment_id=? AND scope='SYMBOL' AND position_ref=?",
            (experiment_id, symbol),
        ).fetchone()
        if sym is not None and not sym["auto_enabled"]:
            return True
    return False


def tracked_symbols(conn, experiment_id: int) -> tuple[str, ...]:
    """The experiment's tracked symbol set: anchor + pe_experiment_symbols."""
    row = conn.execute("SELECT symbol FROM pe_experiments WHERE id=?", (experiment_id,)).fetchone()
    if row is None:
        return ()
    symbols = [str(row["symbol"])]
    for r in conn.execute(
        "SELECT symbol FROM pe_experiment_symbols WHERE experiment_id=?", (experiment_id,)
    ).fetchall():
        symbols.append(str(r["symbol"]))
    return tuple(sorted(set(symbols)))


def due_proposals(conn, now_iso: str, *, auto_only: bool = True) -> list[dict]:
    """Return due proposals. By default only auto-mode proposals are returned
    (auto-mode filtering); non-auto proposals are never auto-executed."""
    query = ("SELECT * FROM pe_order_proposals WHERE current_status='PENDING_APPROVAL' "
             "AND expires_at <= ?")
    params: list = [now_iso]
    if auto_only:
        query += " AND mode=?"
        params.append(AUTO_MODE)
    rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def claim_due_proposal(conn, proposal_id: int, now_iso: str, *, actor: str = "runner") -> dict:
    """Atomically claim a due PENDING_APPROVAL proposal, enforcing every gate.

    Returns {"claimed": bool, "proposal_id": int, "reason": str|None}. Gates
    enforced before the compare-and-set: auto mode, VERY_HIGH, allowed action,
    active experiment, and kill switches. Only one concurrent runner wins the
    CAS; losers get reason RACE_LOST_OR_NOT_DUE.
    """
    row = conn.execute("SELECT * FROM pe_order_proposals WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        return {"claimed": False, "proposal_id": proposal_id, "reason": "PROPOSAL_NOT_FOUND"}
    if row["mode"] != AUTO_MODE:
        return {"claimed": False, "proposal_id": proposal_id, "reason": "NOT_AUTO_MODE"}
    if not row["very_high"]:
        return {"claimed": False, "proposal_id": proposal_id, "reason": "NOT_VERY_HIGH"}
    if not auto_mode_allowed(row["action"]):
        return {"claimed": False, "proposal_id": proposal_id, "reason": "ACTION_NOT_AUTO_ALLOWED"}
    experiment = conn.execute(
        "SELECT status FROM pe_experiments WHERE id=?", (row["experiment_id"],)
    ).fetchone()
    if experiment is None or experiment["status"] != "ACTIVE":
        return {"claimed": False, "proposal_id": proposal_id, "reason": "EXPERIMENT_NOT_ACTIVE"}
    if kill_switch_active(conn, row["experiment_id"], position_ref=row["position_ref"], symbol=row["symbol"]):
        return {"claimed": False, "proposal_id": proposal_id, "reason": "KILL_SWITCH_ACTIVE"}
    cur = conn.execute(
        "UPDATE pe_order_proposals SET current_status='REVALIDATING', status='REVALIDATING' "
        "WHERE id=? AND current_status='PENDING_APPROVAL' AND expires_at <= ?",
        (proposal_id, now_iso),
    )
    if cur.rowcount != 1:
        conn.rollback()
        return {"claimed": False, "proposal_id": proposal_id, "reason": "RACE_LOST_OR_NOT_DUE"}
    conn.execute(
        "INSERT INTO pe_proposal_events (proposal_id, from_status, to_status, at, actor, reason) "
        "VALUES (?,?,?,?,?,?)",
        (proposal_id, "PENDING_APPROVAL", "REVALIDATING", _now_iso(), actor, ""),
    )
    conn.commit()
    return {"claimed": True, "proposal_id": proposal_id, "reason": None}


def outcome_append(conn, proposal_id: int, order_id: int, observed_price: float | None,
                   observed_at: str, source: str) -> None:
    conn.execute(
        "INSERT INTO pe_outcome_snapshots (proposal_id, order_id, observed_price, observed_at, source) "
        "VALUES (?,?,?,?,?)",
        (proposal_id, order_id, observed_price, observed_at, source),
    )
    conn.commit()


def list_approved_proposals(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM pe_order_proposals WHERE current_status='APPROVED'").fetchall()
    return [dict(row) for row in rows]


def claim_approved_proposal(conn, proposal_id: int, *, actor: str = "runner") -> dict:
    """Claim an APPROVED proposal for immediate revalidation (user-approved path).

    Enforces active experiment and kill switches, then atomically transitions
    APPROVED -> REVALIDATING. Freshness/position/direction/trigger/veto checks
    are enforced by revalidation, never bypassed here."""
    row = conn.execute("SELECT * FROM pe_order_proposals WHERE id=?", (proposal_id,)).fetchone()
    if row is None:
        return {"claimed": False, "proposal_id": proposal_id, "reason": "PROPOSAL_NOT_FOUND"}
    if row["current_status"] != "APPROVED":
        return {"claimed": False, "proposal_id": proposal_id, "reason": "NOT_APPROVED"}
    experiment = conn.execute("SELECT status FROM pe_experiments WHERE id=?", (row["experiment_id"],)).fetchone()
    if experiment is None or experiment["status"] != "ACTIVE":
        return {"claimed": False, "proposal_id": proposal_id, "reason": "EXPERIMENT_NOT_ACTIVE"}
    if kill_switch_active(conn, row["experiment_id"], position_ref=row["position_ref"], symbol=row["symbol"]):
        return {"claimed": False, "proposal_id": proposal_id, "reason": "KILL_SWITCH_ACTIVE"}
    cur = conn.execute(
        "UPDATE pe_order_proposals SET current_status='REVALIDATING', status='REVALIDATING' "
        "WHERE id=? AND current_status='APPROVED'",
        (proposal_id,),
    )
    if cur.rowcount != 1:
        conn.rollback()
        return {"claimed": False, "proposal_id": proposal_id, "reason": "RACE_LOST"}
    conn.execute(
        "INSERT INTO pe_proposal_events (proposal_id, from_status, to_status, at, actor, reason) "
        "VALUES (?,?,?,?,?,?)",
        (proposal_id, "APPROVED", "REVALIDATING", _now_iso(), actor, ""),
    )
    conn.commit()
    return {"claimed": True, "proposal_id": proposal_id, "reason": None}


def record_user_decision(conn, proposal_id: int, decision: str, notes: str | None = None) -> None:
    conn.execute(
        "INSERT INTO pe_user_decisions (proposal_id, decision, at, notes) VALUES (?,?,?,?)",
        (proposal_id, decision, _now_iso(), notes),
    )
    conn.commit()


def record_order_and_fills(conn, proposal_id: int, legs: list[dict], order_result: dict, *,
                           price_source: str, bar_time: object, model_note: str) -> str:
    """Append paper orders + fills and return the proposal outcome status.

    An order row is written per leg; fills are written only for simulated fills.
    Never mutates the live/manual position records."""
    result_legs = order_result.get("legs", [])
    for index, leg in enumerate(legs):
        res = result_legs[index] if index < len(result_legs) else {}
        cur = conn.execute(
            "INSERT INTO pe_paper_orders (proposal_id, leg_index, ticker, side, quantity, "
            " price_reference, price_source, bar_time, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (proposal_id, index, leg.get("ticker", ""), leg.get("side", ""),
             leg.get("quantity"), leg.get("price_reference"), price_source, str(bar_time),
             res.get("status", "UNFILLED"), _now_iso()),
        )
        order_id = cur.lastrowid
        if res.get("status") == "FILLED":
            conn.execute(
                "INSERT INTO pe_paper_fills (order_id, fill_price, fill_quantity, fill_time, model_note) "
                "VALUES (?,?,?,?,?)",
                (order_id, res.get("fill_price"), res.get("fill_quantity"), _now_iso(), model_note),
            )
    outcome = order_result.get("status")
    return {
        "FILLED": "FILLED",
        "PARTIALLY_FILLED": "PARTIALLY_FILLED",
        "UNSCORABLE_EXECUTION_DATA": "UNSCORABLE_EXECUTION_DATA",
    }.get(outcome, "UNFILLED")


def apply_paper_fill_ledger(conn, proposal, legs: list[dict], order_result: dict) -> None:
    """Apply filled legs to the isolated paper cash/position ledger.

    This runs in the caller's execution transaction. It never touches manual
    holdings. Option notional uses 100x; shares use 1x.
    """
    results = order_result.get("legs", [])
    experiment_id = proposal["experiment_id"]
    cash_row = conn.execute(
        "SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (experiment_id,)
    ).fetchone()
    if cash_row is None:
        raise RuntimeError("PAPER_CASH_NOT_INITIALIZED")
    cash = float(cash_row["cash"])
    for index, leg in enumerate(legs):
        result = results[index] if index < len(results) else {}
        if result.get("status") != "FILLED":
            continue
        instrument_type = str(leg.get("instrument_type") or "SHARE").upper()
        multiplier = 100 if instrument_type in {"CALL", "PUT"} else 1
        quantity = float(result["fill_quantity"])
        price = float(result["fill_price"])
        side = leg.get("side")
        signed_qty = quantity if side in {"buy_to_open", "buy_to_close"} else -quantity
        cash += (-quantity * price * multiplier) if side.startswith("buy_") else (quantity * price * multiplier)
        ticker = leg.get("ticker") or proposal["symbol"]
        conn.execute(
            "INSERT INTO pe_paper_positions (experiment_id, symbol, instrument_type, ticker, quantity, updated_at) "
            "VALUES (?,?,?,?,?,?) ON CONFLICT(experiment_id,ticker,instrument_type) DO UPDATE SET "
            "quantity=pe_paper_positions.quantity+excluded.quantity, updated_at=excluded.updated_at",
            (experiment_id, proposal["symbol"], instrument_type, ticker, signed_qty, _now_iso()),
        )
    conn.execute(
        "UPDATE pe_paper_cash SET cash=?, updated_at=? WHERE experiment_id=?",
        (cash, _now_iso(), experiment_id),
    )


def modify_proposal_transactional(conn, proposal_id: int, *, new_action: str,
                                  new_idempotency_key: str, policy_sha256: str,
                                  time_sensitive_reason: str | None, very_high: bool,
                                  missing_roots: list, expires_at: str,
                                  cancel_condition: str, position_ref=None,
                                  instrument_ref=None) -> dict:
    """One-transaction supersession: create one versioned child, record the user
    decision, then cancel the parent. Any failure rolls back the whole thing."""
    parent = conn.execute("SELECT * FROM pe_order_proposals WHERE id=?", (proposal_id,)).fetchone()
    if parent is None:
        return {"ok": False, "reason": "PROPOSAL_NOT_FOUND"}
    if parent["current_status"] != "PENDING_APPROVAL":
        return {"ok": False, "reason": "PARENT_NOT_PENDING_APPROVAL"}
    now = _now_iso()
    child_id = _insert_proposal_row(
        conn, experiment_id=parent["experiment_id"], idempotency_key=new_idempotency_key,
        parent_proposal_id=parent["id"], version=parent["version"] + 1,
        action=new_action, mode="APPROVAL_REQUIRED", symbol=parent["symbol"],
        policy_sha256=policy_sha256, time_sensitive_reason=time_sensitive_reason,
        very_high=very_high, missing_roots=missing_roots, expires_at=expires_at,
        cancel_condition=cancel_condition,
        position_ref=position_ref if position_ref is not None else parent["position_ref"],
        instrument_ref=instrument_ref if instrument_ref is not None else parent["instrument_ref"],
    )
    conn.execute(
        "INSERT INTO pe_proposal_events (proposal_id, from_status, to_status, at, actor, reason) "
        "VALUES (?,?,?,?,?,?)",
        (child_id, "DRAFT", "PENDING_APPROVAL", now, "system", ""),
    )
    conn.execute(
        "INSERT INTO pe_user_decisions (proposal_id, decision, at, notes) VALUES (?,?,?,?)",
        (proposal_id, "MODIFY", now, json.dumps({"new_proposal_id": child_id})),
    )
    conn.execute(
        "UPDATE pe_order_proposals SET current_status='CANCELLED', status='CANCELLED' "
        "WHERE id=? AND current_status='PENDING_APPROVAL'",
        (proposal_id,),
    )
    conn.execute(
        "INSERT INTO pe_proposal_events (proposal_id, from_status, to_status, at, actor, reason) "
        "VALUES (?,?,?,?,?,?)",
        (proposal_id, "PENDING_APPROVAL", "CANCELLED", now, "user", "superseded_by_modification"),
    )
    conn.commit()
    return {"ok": True, "proposal_id": child_id, "parent_proposal_id": proposal_id,
            "version": parent["version"] + 1}


def upsert_bracket(conn, *, experiment_id, symbol, ticker, instrument_type,
                   direction, stop_price, target_price, created_by="user") -> int:
    """Replace the ACTIVE bracket for a paper position with a new one.

    Supersedes (cancels) any existing ACTIVE bracket for the ticker, then
    inserts the new ACTIVE row. Historical TRIGGERED/CANCELLED rows are kept.
    """
    now = _now_iso()
    conn.execute(
        "UPDATE pe_position_brackets SET status='CANCELLED', updated_at=? "
        "WHERE experiment_id=? AND ticker=? AND status='ACTIVE'",
        (now, experiment_id, ticker),
    )
    cur = conn.execute(
        "INSERT INTO pe_position_brackets (experiment_id, symbol, ticker, "
        " instrument_type, direction, stop_price, target_price, status, "
        " created_by, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (experiment_id, symbol, ticker, instrument_type, direction,
         stop_price, target_price, "ACTIVE", created_by, now, now),
    )
    conn.commit()
    return cur.lastrowid


def list_active_brackets(conn, experiment_id=None) -> list[dict]:
    """Active brackets (the operational view the runner evaluates)."""
    query = "SELECT * FROM pe_position_brackets WHERE status='ACTIVE'"
    params: list = []
    if experiment_id is not None:
        query += " AND experiment_id=?"
        params.append(experiment_id)
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def cancel_bracket(conn, bracket_id: int) -> bool:
    """Cancel an ACTIVE bracket; returns True when one row was cancelled."""
    cur = conn.execute(
        "UPDATE pe_position_brackets SET status='CANCELLED', updated_at=? "
        "WHERE id=? AND status='ACTIVE'",
        (_now_iso(), bracket_id),
    )
    conn.commit()
    return cur.rowcount == 1


def apply_bracket_trigger(conn, bracket: dict, *, side, trigger_price, fill_price,
                          bar_time, price_source, note) -> None:
    """Mark a bracket TRIGGERED and apply a protective close to the paper ledger.

    Bar-close fill at the trigger price; no intrabar, no bid/ask. Closing a LONG
    sells (cash in); closing a SHORT buys (cash out)."""
    instrument_type = str(bracket["instrument_type"] or "SHARE").upper()
    multiplier = 100 if instrument_type in ("CALL", "PUT") else 1
    pos = conn.execute(
        "SELECT quantity FROM pe_paper_positions WHERE experiment_id=? AND ticker=? AND instrument_type=?",
        (bracket["experiment_id"], bracket["ticker"], instrument_type),
    ).fetchone()
    if pos is not None:
        qty = float(pos["quantity"] or 0.0)
        if abs(qty) > 0:
            closing_sell = bracket["direction"] == "LONG"
            cash_delta = (abs(qty) * fill_price * multiplier) if closing_sell else (-abs(qty) * fill_price * multiplier)
            conn.execute(
                "UPDATE pe_paper_cash SET cash=cash+?, updated_at=? WHERE experiment_id=?",
                (cash_delta, _now_iso(), bracket["experiment_id"]),
            )
            conn.execute(
                "UPDATE pe_paper_positions SET quantity=0, updated_at=? "
                "WHERE experiment_id=? AND ticker=? AND instrument_type=?",
                (_now_iso(), bracket["experiment_id"], bracket["ticker"], instrument_type),
            )
    conn.execute(
        "UPDATE pe_position_brackets SET status='TRIGGERED', triggered_at=?, "
        " triggered_side=?, trigger_price=?, fill_price=?, fill_note=?, updated_at=? "
        "WHERE id=? AND status='ACTIVE'",
        (_now_iso(), side, trigger_price, fill_price, note, _now_iso(), bracket["id"]),
    )
    conn.commit()


def _insert_proposal_row(conn, *, experiment_id, idempotency_key, parent_proposal_id, version,
                         action, mode, symbol, policy_sha256, time_sensitive_reason,
                         very_high, missing_roots, expires_at, cancel_condition,
                         position_ref=None, instrument_ref=None) -> int:
    now = _now_iso()
    cur = conn.execute(
        "INSERT OR IGNORE INTO pe_order_proposals "
        "(experiment_id, idempotency_key, parent_proposal_id, version, policy_version, policy_sha256, "
        " action, mode, symbol, position_ref, instrument_ref, time_sensitive_reason, very_high, very_high_missing_roots, "
        " status, current_status, expires_at, cancel_condition, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (experiment_id, idempotency_key, parent_proposal_id, version, 1, policy_sha256,
         action, mode, symbol, position_ref, instrument_ref, time_sensitive_reason, 1 if very_high else 0,
         json.dumps(missing_roots), "PENDING_APPROVAL", "PENDING_APPROVAL",
         expires_at, cancel_condition, now),
    )
    if cur.rowcount == 0:
        row = conn.execute(
            "SELECT id FROM pe_order_proposals WHERE experiment_id=? AND idempotency_key=?",
            (experiment_id, idempotency_key),
        ).fetchone()
        return row["id"]
    return cur.lastrowid
