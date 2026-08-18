"""Authenticated paper-execution API (PAPER_ONLY).

A Flask blueprint with read/write endpoints for experiments, proposals,
evidence, approval, modification, rejection, cancellation and reports. Every
mutation requires bearer auth and idempotency/compare-and-set. Clients submit
only intent; very_high, evidence roots, freshness, price source and policy
eligibility are reconstructed server-side from an authoritative state provider
and can never be overridden by the client. Request fields are strictly
allowlisted, and modification is one transaction.
"""
from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from paper_execution.db import connect
from paper_execution.activation import join_symbol_if_ready
from paper_execution.brackets import validate_bracket_payload, validate_side
from paper_execution.engine import auto_mode_allowed, evaluate_very_high
from paper_execution.portfolio import (
    ANCHOR_SYMBOL,
    amc_floor_breached,
    asset_eligible,
    load_reliability_mask,
    non_anchor_weight_cap,
    paper_portfolio_value,
)
from paper_execution.runner import health_summary
from paper_execution.state import reconstruct_evidence
from paper_execution.store import (
    cancel_bracket,
    create_proposal,
    frozen_corrections_hash,
    frozen_corrections_v12_hash,
    frozen_policy_hash,
    list_active_brackets,
    modify_proposal_transactional,
    record_user_decision,
    set_kill_switch,
    tracked_symbols,
    transition,
    upsert_bracket,
)

CREATE_ALLOWED = {"action", "symbol", "experiment_id", "idempotency_key", "time_sensitive_reason",
                  "position_ref", "instrument_ref", "stop_price", "target_price"}
MODIFY_ALLOWED = {"action", "idempotency_key", "time_sensitive_reason", "position_ref", "instrument_ref",
                  "stop_price", "target_price"}

APPROVAL_WINDOW_SECONDS = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _num_or_none(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bracket_position(conn, proposal):
    ticker = proposal["position_ref"]
    if not ticker:
        return None, "BRACKET_MISSING_TICKER"
    pos = conn.execute(
        "SELECT symbol, instrument_type, quantity FROM pe_paper_positions "
        "WHERE experiment_id=? AND ticker=?",
        (proposal["experiment_id"], ticker),
    ).fetchone()
    if pos is None or float(pos["quantity"] or 0.0) == 0.0:
        return None, "PAPER_POSITION_NOT_FOUND"
    return pos, None


def _bracket_check(conn, proposal) -> dict:
    pos, reason = _bracket_position(conn, proposal)
    if reason:
        return {"ok": False, "reason": reason}
    direction = "LONG" if float(pos["quantity"]) > 0 else "SHORT"
    if not validate_side(direction, proposal["stop_price"], proposal["target_price"]):
        return {"ok": False, "reason": "BRACKET_SIDE_INVALID"}
    return {"ok": True}


def _apply_approved_bracket(conn, proposal) -> dict:
    pos, reason = _bracket_position(conn, proposal)
    if reason:
        return {"ok": False, "reason": reason}
    direction = "LONG" if float(pos["quantity"]) > 0 else "SHORT"
    bracket_id = upsert_bracket(
        conn, experiment_id=proposal["experiment_id"], symbol=pos["symbol"],
        ticker=proposal["position_ref"],
        instrument_type=str(pos["instrument_type"] or "SHARE").upper(),
        direction=direction, stop_price=proposal["stop_price"],
        target_price=proposal["target_price"], created_by="user",
    )
    return {"ok": True, "bracket_id": bracket_id}


_reliability_mask_cache: dict | None = None


def _eligibility_mask() -> dict:
    """Lazily load the reliability mask once; empty on failure (fail-closed)."""
    global _reliability_mask_cache
    if _reliability_mask_cache is None:
        try:
            _reliability_mask_cache = load_reliability_mask()
        except (OSError, ValueError):
            _reliability_mask_cache = {}
    return _reliability_mask_cache


def create_blueprint(db_path, state_token: str, state_provider, webhook_db_path=None):
    bp = Blueprint("paper_execution", __name__)

    def authorized() -> bool:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return False
        return hmac.compare_digest(auth[7:], state_token)

    def require_auth():
        if not authorized():
            return jsonify({"error": "unauthorized"}), 401
        return None

    def _unknown_fields(body: dict, allowed: set) -> list[str]:
        return sorted(set(body) - allowed)

    def _determine_mode(action: str, very_high: bool, symbol: str | None = None) -> str:
        if very_high and auto_mode_allowed(action, symbol):
            return "AUTO_IF_VERY_HIGH_PAPER"
        return "APPROVAL_REQUIRED"

    def _validate_experiment(conn, experiment_id, symbol, action):
        row = conn.execute("SELECT * FROM pe_experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            return None, "EXPERIMENT_NOT_FOUND"
        if row["status"] != "ACTIVE":
            return None, "EXPERIMENT_NOT_ACTIVE"
        if symbol not in tracked_symbols(conn, experiment_id):
            return None, "SYMBOL_NOT_TRACKED"
        if action not in {a.strip() for a in (row["allowed_actions"] or "").split(",")} and action != "set_bracket":
            return None, "ACTION_NOT_ALLOWED"
        now = _now_iso()
        if row["start_at"] and now < row["start_at"]:
            return None, "BEFORE_START"
        if row["end_at"] and now > row["end_at"]:
            return None, "AFTER_END"
        return row, None

    def _load_state(symbol, position_ref=None, instrument_ref=None):
        try:
            return state_provider(db_path, symbol, position_ref=position_ref, instrument_ref=instrument_ref)
        except TypeError:
            return state_provider(db_path, symbol)

    def _reconstruct(action, symbol, position_ref=None, instrument_ref=None):
        state = _load_state(symbol, position_ref, instrument_ref)
        evidence = reconstruct_evidence(state, symbol, action)
        if evidence is None:
            return None, None
        return evaluate_very_high(evidence, action), evidence

    def _evidence_roots(evidence, result):
        return [{
            "root": "server_reconstructed",
            "present": True,
            "raw_fields": {
                "evidence": evidence,
                "missing_roots": result["missing_roots"],
                "vetoes": result["vetoes"],
                "policy_sha256": frozen_policy_hash(),
                "corrections_v11_sha256": frozen_corrections_hash(),
                "corrections_v12_sha256": frozen_corrections_v12_hash(),
            },
            "missing_evidence": [],
            "contradictions": [],
            "veto": False,
        }]

    @bp.route("/paper/health", methods=["GET"])
    def health():
        readiness = getattr(state_provider, "readiness", lambda: {})()
        return jsonify(health_summary(db_path, provider_readiness=readiness))

    @bp.route("/paper/experiments/<int:experiment_id>", methods=["GET"])
    def get_experiment(experiment_id):
        err = require_auth()
        if err:
            return err
        conn = connect(db_path)
        row = conn.execute("SELECT * FROM pe_experiments WHERE id=?", (experiment_id,)).fetchone()
        if row is None:
            conn.close()
            return jsonify({"error": "not found"}), 404
        cash = conn.execute(
            "SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        conn.close()
        payload = dict(row)
        payload["live_cash"] = float(cash["cash"]) if cash else None
        return jsonify(payload)

    @bp.route("/paper/proposals", methods=["POST"])
    def create():
        err = require_auth()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        unknown = _unknown_fields(body, CREATE_ALLOWED)
        if unknown:
            return jsonify({"error": "unknown fields", "fields": unknown}), 400
        action = body.get("action")
        symbol = (body.get("symbol") or "").upper()
        experiment_id = body.get("experiment_id")
        idempotency_key = body.get("idempotency_key") or str(uuid.uuid4())
        if not action or not symbol or experiment_id is None:
            return jsonify({"error": "action, symbol and experiment_id are required"}), 400
        if action in {"add", "partial_reduce", "close", "roll"} and (
            body.get("position_ref") is None or body.get("instrument_ref") is None
        ):
            return jsonify({"error": "position_ref and instrument_ref are required for this action"}), 400

        stop_price = body.get("stop_price")
        target_price = body.get("target_price")
        if action == "set_bracket":
            if body.get("position_ref") is None:
                return jsonify({"error": "position_ref (ticker) is required for set_bracket"}), 400
            if stop_price in (None, "") and target_price in (None, ""):
                return jsonify({"error": "at least one of stop_price or target_price is required"}), 400
            for name, value in (("stop_price", stop_price), ("target_price", target_price)):
                if value in (None, ""):
                    continue
                try:
                    if float(value) <= 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return jsonify({"error": f"{name} must be a positive number"}), 400

        conn = connect(db_path)
        experiment, exp_err = _validate_experiment(conn, experiment_id, symbol, action)
        if exp_err:
            conn.close()
            return jsonify({"error": exp_err}), 409

        # set_bracket is a protective order, not a capital action: it bypasses
        # the evidence-root reconstruction and the eligibility/floor gates, and
        # is always APPROVAL_REQUIRED (never auto). The bracket is only set
        # when the human approves (§ see _decision_endpoint).
        if action == "set_bracket":
            conn.close()
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_WINDOW_SECONDS)).isoformat()
            conn = connect(db_path)
            proposal_id = create_proposal(
                conn, experiment_id=experiment_id, idempotency_key=idempotency_key,
                action="set_bracket", mode="APPROVAL_REQUIRED", symbol=symbol,
                policy_sha256=frozen_policy_hash(),
                time_sensitive_reason=body.get("time_sensitive_reason") or "protective stop/target",
                very_high=False, very_high_missing_roots=[],
                expires_at=expires_at, cancel_condition="stale_underlying",
                evidence_roots=[],
                position_ref=body.get("position_ref"), instrument_ref=body.get("instrument_ref"),
                stop_price=_num_or_none(stop_price), target_price=_num_or_none(target_price),
            )
            conn.close()
            return jsonify({"proposal_id": proposal_id, "very_high": False,
                            "mode": "APPROVAL_REQUIRED", "missing_roots": [], "vetoes": []}), 201

        # §5 eligibility gate (non-anchor only; the anchor AMC is always eligible).
        if symbol != ANCHOR_SYMBOL and not asset_eligible(_eligibility_mask(), symbol):
            conn.close()
            return jsonify({"error": "ASSET_NOT_ELIGIBLE"}), 409

        # §2 R2 (drift): while AMC is already below the floor, block non-AMC adds.
        if symbol != ANCHOR_SYMBOL and action in {"open", "add"}:
            valuation = paper_portfolio_value(conn, experiment_id)
            if amc_floor_breached(valuation["amc_value"], valuation["total_value"], 0.0):
                conn.close()
                return jsonify({"error": "AMC_FLOOR_WOULD_BREACH"}), 409
        conn.close()

        position_ref = body.get("position_ref")
        instrument_ref = body.get("instrument_ref")
        result, evidence = _reconstruct(action, symbol, position_ref, instrument_ref)
        if evidence is None:
            return jsonify({"error": "no authoritative state; proposal blocked"}), 409
        very_high = bool(result["very_high"])
        mode = _determine_mode(action, very_high, symbol)
        expires_at = (datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_WINDOW_SECONDS)).isoformat()

        conn = connect(db_path)
        proposal_id = create_proposal(
            conn, experiment_id=experiment_id, idempotency_key=idempotency_key,
            action=action, mode=mode, symbol=symbol, policy_sha256=frozen_policy_hash(),
            time_sensitive_reason=body.get("time_sensitive_reason"),
            very_high=very_high, very_high_missing_roots=result["missing_roots"],
            expires_at=expires_at, cancel_condition="stale_underlying",
            evidence_roots=_evidence_roots(evidence, result),
            position_ref=position_ref, instrument_ref=instrument_ref,
        )
        conn.close()
        return jsonify({
            "proposal_id": proposal_id, "very_high": very_high, "mode": mode,
            "missing_roots": result["missing_roots"], "vetoes": result["vetoes"],
        }), 201

    @bp.route("/paper/proposals", methods=["GET"])
    def list_proposals():
        err = require_auth()
        if err:
            return err
        conn = connect(db_path)
        rows = conn.execute("SELECT * FROM pe_order_proposals ORDER BY id").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    @bp.route("/paper/proposals/<int:proposal_id>", methods=["GET"])
    def get_proposal(proposal_id):
        err = require_auth()
        if err:
            return err
        conn = connect(db_path)
        row = conn.execute("SELECT * FROM pe_order_proposals WHERE id=?", (proposal_id,)).fetchone()
        conn.close()
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))

    def _decision_endpoint(proposal_id, to_status, decision):
        err = require_auth()
        if err:
            return err
        conn = connect(db_path)
        row = conn.execute("SELECT * FROM pe_order_proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            conn.close()
            return jsonify({"error": "not found"}), 404
        if to_status == "APPROVED" and row["expires_at"] and _now_iso() > row["expires_at"]:
            conn.close()
            return jsonify({"error": "approval window expired"}), 409
        apply_bracket = to_status == "APPROVED" and row["action"] == "set_bracket"
        if apply_bracket:
            check = _bracket_check(conn, row)
            if not check["ok"]:
                conn.close()
                return jsonify({"error": check["reason"]}), 409
        try:
            out = transition(conn, proposal_id, to_status, actor="user",
                             expected_from="PENDING_APPROVAL")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            conn.close()
            return jsonify({"error": type(exc).__name__, "detail": str(exc)}), 409
        record_user_decision(conn, proposal_id, decision)
        if apply_bracket:
            applied = _apply_approved_bracket(conn, row)
            out["bracket_id"] = applied.get("bracket_id")
        conn.close()
        return jsonify(out)

    @bp.route("/paper/proposals/<int:proposal_id>/approve", methods=["POST"])
    def approve(proposal_id):
        return _decision_endpoint(proposal_id, "APPROVED", "APPROVE")

    @bp.route("/paper/proposals/<int:proposal_id>/reject", methods=["POST"])
    def reject(proposal_id):
        return _decision_endpoint(proposal_id, "REJECTED", "REJECT")

    @bp.route("/paper/proposals/<int:proposal_id>/cancel", methods=["POST"])
    def cancel(proposal_id):
        return _decision_endpoint(proposal_id, "CANCELLED", "CANCEL_AUTO")

    @bp.route("/paper/proposals/<int:proposal_id>/modify", methods=["POST"])
    def modify(proposal_id):
        err = require_auth()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        unknown = _unknown_fields(body, MODIFY_ALLOWED)
        if unknown:
            return jsonify({"error": "unknown fields", "fields": unknown}), 400
        conn = connect(db_path)
        original = conn.execute("SELECT * FROM pe_order_proposals WHERE id=?", (proposal_id,)).fetchone()
        if original is None:
            conn.close()
            return jsonify({"error": "not found"}), 404
        action = body.get("action") or original["action"]
        position_ref = body.get("position_ref", original["position_ref"])
        instrument_ref = body.get("instrument_ref", original["instrument_ref"])
        result, evidence = _reconstruct(action, original["symbol"], position_ref, instrument_ref)
        if evidence is None:
            conn.close()
            return jsonify({"error": "no authoritative state; proposal blocked"}), 409
        very_high = bool(result["very_high"])
        new_key = body.get("idempotency_key") or f"{original['idempotency_key']}-v{original['version'] + 1}"
        out = modify_proposal_transactional(
            conn, proposal_id, new_action=action, new_idempotency_key=new_key,
            policy_sha256=frozen_policy_hash(), time_sensitive_reason=body.get("time_sensitive_reason"),
            very_high=very_high, missing_roots=result["missing_roots"],
            expires_at=(datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_WINDOW_SECONDS)).isoformat(),
            cancel_condition="stale_underlying",
            position_ref=position_ref, instrument_ref=instrument_ref,
            stop_price=_num_or_none(body.get("stop_price")),
            target_price=_num_or_none(body.get("target_price")),
        )
        conn.close()
        if not out["ok"]:
            return jsonify({"error": out["reason"]}), 409
        return jsonify({**out, "very_high": very_high, "mode": _determine_mode(action, very_high, original["symbol"])}), 201

    @bp.route("/paper/experiments/<int:experiment_id>/kill-switch", methods=["POST"])
    def kill_switch(experiment_id):
        err = require_auth()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        unknown = _unknown_fields(body, {"scope", "position_ref", "enabled"})
        if unknown:
            return jsonify({"error": "unknown fields", "fields": unknown}), 400
        scope = body.get("scope")
        position_ref = body.get("position_ref")
        enabled = body.get("enabled")
        if scope not in ("GLOBAL", "POSITION"):
            return jsonify({"error": "scope must be GLOBAL or POSITION"}), 400
        if scope == "POSITION" and (position_ref is None or str(position_ref) == ""):
            return jsonify({"error": "position_ref is required for POSITION scope"}), 400
        if not isinstance(enabled, bool):
            return jsonify({"error": "enabled must be a boolean"}), 400
        conn = connect(db_path)
        try:
            experiment = conn.execute("SELECT id FROM pe_experiments WHERE id=?", (experiment_id,)).fetchone()
            if experiment is None:
                return jsonify({"error": "experiment not found"}), 404
            set_kill_switch(conn, experiment_id, scope, position_ref, enabled)
        finally:
            conn.close()
        return jsonify({
            "experiment_id": experiment_id, "scope": scope,
            "position_ref": position_ref, "enabled": enabled,
        }), 200

    @bp.route("/paper/experiments/<int:experiment_id>/symbols", methods=["POST"])
    def join_symbol(experiment_id):
        err = require_auth()
        if err:
            return err
        if webhook_db_path is None:
            return jsonify({"error": "webhook_db_path not configured"}), 500
        body = request.get_json(silent=True) or {}
        unknown = _unknown_fields(body, {"symbol"})
        if unknown:
            return jsonify({"error": "unknown fields", "fields": unknown}), 400
        symbol = (body.get("symbol") or "").strip().upper()
        if not symbol:
            return jsonify({"error": "symbol is required"}), 400
        result = join_symbol_if_ready(db_path, webhook_db_path, experiment_id, symbol)
        status = result.get("status")
        if status == "JOINED":
            return jsonify(result), 201
        if status == "ALREADY_TRACKED":
            return jsonify(result), 200
        if status == "BLOCKED" and result.get("blocker") == "EXPERIMENT_NOT_FOUND":
            return jsonify(result), 404
        return jsonify(result), 409

    @bp.route("/paper/brackets", methods=["POST"])
    def create_bracket():
        err = require_auth()
        if err:
            return err
        clean, val_err = validate_bracket_payload(request.get_json(silent=True) or {})
        if val_err:
            return jsonify({"error": val_err}), 400
        conn = connect(db_path)
        experiment = conn.execute(
            "SELECT status FROM pe_experiments WHERE id=?", (clean["experiment_id"],)
        ).fetchone()
        if experiment is None:
            conn.close()
            return jsonify({"error": "EXPERIMENT_NOT_FOUND"}), 404
        if experiment["status"] != "ACTIVE":
            conn.close()
            return jsonify({"error": "EXPERIMENT_NOT_ACTIVE"}), 409
        pos = conn.execute(
            "SELECT symbol, instrument_type, quantity FROM pe_paper_positions "
            "WHERE experiment_id=? AND ticker=?",
            (clean["experiment_id"], clean["ticker"]),
        ).fetchone()
        if pos is None or float(pos["quantity"] or 0.0) == 0.0:
            conn.close()
            return jsonify({"error": "PAPER_POSITION_NOT_FOUND"}), 409
        direction = "LONG" if float(pos["quantity"]) > 0 else "SHORT"
        if not validate_side(direction, clean["stop_price"], clean["target_price"]):
            conn.close()
            return jsonify({"error": "BRACKET_SIDE_INVALID"}), 400
        bracket_id = upsert_bracket(
            conn, experiment_id=clean["experiment_id"], symbol=pos["symbol"],
            ticker=clean["ticker"], instrument_type=str(pos["instrument_type"] or "SHARE").upper(),
            direction=direction, stop_price=clean["stop_price"],
            target_price=clean["target_price"], created_by=clean["created_by"],
        )
        conn.close()
        return jsonify({"bracket_id": bracket_id, "ticker": clean["ticker"],
                        "direction": direction}), 201

    @bp.route("/paper/brackets", methods=["GET"])
    def list_brackets():
        err = require_auth()
        if err:
            return err
        experiment_id = request.args.get("experiment_id", type=int)
        conn = connect(db_path)
        rows = list_active_brackets(conn, experiment_id=experiment_id)
        conn.close()
        return jsonify(rows)

    @bp.route("/paper/brackets/<int:bracket_id>", methods=["DELETE"])
    def delete_bracket(bracket_id):
        err = require_auth()
        if err:
            return err
        conn = connect(db_path)
        ok = cancel_bracket(conn, bracket_id)
        conn.close()
        if not ok:
            return jsonify({"error": "bracket not found or not active"}), 404
        return jsonify({"bracket_id": bracket_id, "status": "CANCELLED"}), 200

    @bp.route("/paper/reports", methods=["GET"])
    def reports():
        err = require_auth()
        if err:
            return err
        conn = connect(db_path)
        rows = conn.execute("SELECT * FROM pe_daily_reports ORDER BY report_date").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])

    return bp
