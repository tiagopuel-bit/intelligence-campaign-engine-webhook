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
    create_proposal,
    frozen_corrections_hash,
    frozen_corrections_v12_hash,
    frozen_policy_hash,
    modify_proposal_transactional,
    record_user_decision,
    set_kill_switch,
    tracked_symbols,
    transition,
)

CREATE_ALLOWED = {"action", "symbol", "experiment_id", "idempotency_key", "time_sensitive_reason",
                  "position_ref", "instrument_ref"}
MODIFY_ALLOWED = {"action", "idempotency_key", "time_sensitive_reason", "position_ref", "instrument_ref"}

APPROVAL_WINDOW_SECONDS = 600


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def create_blueprint(db_path, state_token: str, state_provider):
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

    def _determine_mode(action: str, very_high: bool) -> str:
        if very_high and auto_mode_allowed(action):
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
        if action not in {a.strip() for a in (row["allowed_actions"] or "").split(",")}:
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
        conn.close()
        if row is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(dict(row))

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

        conn = connect(db_path)
        experiment, exp_err = _validate_experiment(conn, experiment_id, symbol, action)
        if exp_err:
            conn.close()
            return jsonify({"error": exp_err}), 409

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
        mode = _determine_mode(action, very_high)
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
        try:
            out = transition(conn, proposal_id, to_status, actor="user",
                             expected_from="PENDING_APPROVAL")
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            conn.close()
            return jsonify({"error": type(exc).__name__, "detail": str(exc)}), 409
        record_user_decision(conn, proposal_id, decision)
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
        )
        conn.close()
        if not out["ok"]:
            return jsonify({"error": out["reason"]}), 409
        return jsonify({**out, "very_high": very_high, "mode": _determine_mode(action, very_high)}), 201

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
