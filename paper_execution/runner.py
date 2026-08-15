"""One-shot paper runner and aggregate health summary (PAPER_ONLY).

run_once() drives two explicit paths: user-approved proposals (claimed
immediately) and auto proposals (claimed only after their approval deadline).
Both paths rebuild authoritative evidence, enforce every safety gate through
revalidation, and execute a real paper fill (orders + fills), never a
status-only transition. With no authoritative state the proposal cancels
honestly rather than substituting a delayed Massive close.
"""
from __future__ import annotations

from datetime import datetime, timezone

from paper_execution.db import connect
from paper_execution.engine import revalidate
from paper_execution.fill import simulate_order
from paper_execution.state import reconstruct_evidence, reconstruct_legs
from paper_execution.store import (
    claim_approved_proposal,
    claim_due_proposal,
    due_proposals,
    list_approved_proposals,
    record_order_and_fills,
    apply_paper_fill_ledger,
    transition,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _process(conn, db_path, proposal, state_provider, actor) -> dict:
    try:
        state = state_provider(
            db_path, proposal["symbol"], position_ref=proposal.get("position_ref"),
            instrument_ref=proposal.get("instrument_ref"),
        )
    except TypeError:
        state = state_provider(db_path, proposal["symbol"])
    evidence = reconstruct_evidence(state, proposal["symbol"], proposal["action"])
    if evidence is None:
        reason = "NO_AUTHORITATIVE_STATE"
        transition(conn, proposal["id"], "CANCELLED_REVALIDATION",
                   actor=actor, reason=reason, expected_from="REVALIDATING")
        return {"proposal_id": proposal["id"], "status": "CANCELLED_REVALIDATION",
                "reason": reason}
    state_position = (state or {}).get("position") or {}
    if proposal.get("position_ref") is not None and str(state_position.get("position_ref")) != str(proposal["position_ref"]):
        reason = "POSITION_REF_MISMATCH"
        transition(conn, proposal["id"], "CANCELLED_REVALIDATION", actor=actor,
                   reason=reason, expected_from="REVALIDATING")
        return {"proposal_id": proposal["id"], "status": "CANCELLED_REVALIDATION", "reason": reason}
    if proposal.get("instrument_ref") is not None and str(state_position.get("instrument_ref")) != str(proposal["instrument_ref"]):
        reason = "INSTRUMENT_REF_MISMATCH"
        transition(conn, proposal["id"], "CANCELLED_REVALIDATION", actor=actor,
                   reason=reason, expected_from="REVALIDATING")
        return {"proposal_id": proposal["id"], "status": "CANCELLED_REVALIDATION", "reason": reason}
    verdict = revalidate(proposal["action"], evidence)
    if verdict["status"] != "VALID":
        transition(conn, proposal["id"], "CANCELLED_REVALIDATION",
                   actor=actor, reason=verdict["reason"], expected_from="REVALIDATING")
        return {"proposal_id": proposal["id"], "status": "CANCELLED_REVALIDATION",
                "reason": verdict["reason"]}

    legs, instrument_type = reconstruct_legs(state, proposal["symbol"], proposal["action"])
    order_result = simulate_order(legs or [], instrument_type=instrument_type or "SHARE")
    price_source = evidence["execution_quality"].get("source")
    try:
        transition(conn, proposal["id"], "PAPER_EXECUTED", actor=actor,
                   reason="revalidation_valid", expected_from="REVALIDATING", commit=False)
        outcome = record_order_and_fills(
            conn, proposal["id"], legs or [], order_result,
            price_source=price_source,
            bar_time=evidence["execution_quality"].get("bar_time"),
            model_note="conservative causal bar-close paper model (no bid/ask)",
        )
        apply_paper_fill_ledger(conn, proposal, legs or [], order_result)
        transition(conn, proposal["id"], outcome, actor=actor, reason="paper_fill",
                   expected_from="PAPER_EXECUTED", commit=True)
    except Exception:
        conn.rollback()
        raise
    return {"proposal_id": proposal["id"], "status": outcome}


def run_once(db_path, state_provider, *, now_iso: str | None = None, actor: str = "runner") -> list[dict]:
    now_iso = now_iso or _now_iso()
    conn = connect(db_path)
    try:
        results = []
        # 1. user-approved path (immediate claim).
        for proposal in list_approved_proposals(conn):
            claim = claim_approved_proposal(conn, proposal["id"], actor=actor)
            if not claim["claimed"]:
                results.append({"proposal_id": proposal["id"], "status": "SKIPPED",
                                "reason": claim["reason"]})
                continue
            results.append(_process(conn, db_path, proposal, state_provider, actor))
        # 2. automatic path (only after the approval deadline).
        for proposal in due_proposals(conn, now_iso):
            claim = claim_due_proposal(conn, proposal["id"], now_iso, actor=actor)
            if not claim["claimed"]:
                results.append({"proposal_id": proposal["id"], "status": "SKIPPED",
                                "reason": claim["reason"]})
                continue
            results.append(_process(conn, db_path, proposal, state_provider, actor))
        return results
    finally:
        conn.close()


def health_summary(db_path, provider_readiness: dict | None = None) -> dict:
    """Aggregate paper-runner readiness. No secrets, no token, no balances."""
    conn = connect(db_path)
    try:
        experiments = conn.execute("SELECT COUNT(*) n FROM pe_experiments").fetchone()["n"]
        pending = conn.execute(
            "SELECT COUNT(*) n FROM pe_order_proposals WHERE current_status='PENDING_APPROVAL'"
        ).fetchone()["n"]
        approved = conn.execute(
            "SELECT COUNT(*) n FROM pe_order_proposals WHERE current_status='APPROVED'"
        ).fetchone()["n"]
        executed = conn.execute(
            "SELECT COUNT(*) n FROM pe_order_proposals WHERE current_status IN ('PAPER_EXECUTED','FILLED','PARTIALLY_FILLED','UNFILLED')"
        ).fetchone()["n"]
        global_off = conn.execute(
            "SELECT COUNT(*) n FROM pe_auto_switches WHERE scope='GLOBAL' AND auto_enabled=0"
        ).fetchone()["n"]
        active = conn.execute(
            "SELECT id FROM pe_experiments WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        readiness = provider_readiness or {}
        blockers = list(readiness.get("blockers") or [])
        if not readiness:
            blockers.append("BLOCKED_NO_AUTHORITATIVE_PROVIDER_STATUS")
        provider_ready = readiness.get("authoritative_provider_ready") is True
        runner_ready = provider_ready and active is not None and global_off == 0
        return {
            "status": "ok",
            "paper_only": True,
            "experiments": experiments,
            "pending_proposals": pending,
            "approved_proposals": approved,
            "paper_executed_proposals": executed,
            "global_auto_disabled": global_off > 0,
            "active_experiment_id": active["id"] if active else None,
            "authoritative_provider_ready": provider_ready,
            "runner_ready": runner_ready,
            "blockers": blockers,
        }
    finally:
        conn.close()
