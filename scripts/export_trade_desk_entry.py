#!/usr/bin/env python3
"""Read-only export helper for the Paper Trade Desk Log.

Prints a pre-filled entry skeleton for one proposal so whoever is logging a
decision does not retype data already in the DB. This tool is read-only: it
opens the paper DB in ``mode=ro``, performs no writes, never runs as part of
any deploy or scheduled process, and does not import paper_execution.

Usage:
    python3 scripts/export_trade_desk_entry.py <proposal_id> [--db PATH]
"""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "paper_execution" / "paper.db"

EVIDENCE_ORDER = (
    "underlying_dna", "contract_response", "execution_quality",
    "portfolio_risk", "catalyst",
)


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _cell(value: object) -> str:
    return str(value) if value not in (None, "") else ""


def _evidence_line(rows) -> str:
    present = {row["root"]: bool(row["present"]) for row in rows}
    veto = {row["root"] for row in rows if row["veto"]}
    parts = []
    for root in EVIDENCE_ORDER:
        if root in present:
            mark = "✅" if present[root] else "❌"
            if root in veto:
                mark += " ⛔veto"
            parts.append(f"{root.replace('_', ' ')} {mark}")
    if not parts:
        return "(no evidence snapshot)"
    return " · ".join(parts)


def build_skeleton(conn, proposal_id: int, *, db_path: Path = DEFAULT_DB) -> str:
    proposal = conn.execute(
        "SELECT * FROM pe_order_proposals WHERE id = ?", (proposal_id,)
    ).fetchone()
    if proposal is None:
        return f"proposal #{proposal_id}: NOT FOUND in {db_path}"

    evidence = conn.execute(
        "SELECT root, present, veto FROM pe_proposal_evidence WHERE proposal_id = ? "
        "ORDER BY id", (proposal_id,)
    ).fetchall()

    decision_rows = conn.execute(
        "SELECT decision, at, notes FROM pe_user_decisions WHERE proposal_id = ? "
        "ORDER BY id", (proposal_id,)
    ).fetchall()

    last_event = conn.execute(
        "SELECT to_status, at, actor, reason FROM pe_proposal_events "
        "WHERE proposal_id = ? ORDER BY id DESC LIMIT 1", (proposal_id,)
    ).fetchone()

    fills = conn.execute(
        "SELECT f.fill_price, f.fill_time FROM pe_paper_fills f "
        "JOIN pe_paper_orders o ON o.id = f.order_id "
        "WHERE o.proposal_id = ? ORDER BY f.id", (proposal_id,)
    ).fetchall()

    lines = []
    position_ref = _cell(proposal["position_ref"]) or "?"
    instrument_ref = _cell(proposal["instrument_ref"]) or "?"
    lines.append(
        f"## {_cell(proposal['created_at'])} — {_cell(proposal['symbol'])} — "
        f"proposal #{proposal_id} ({proposal['action']}, "
        f"position_ref={position_ref}, instrument_ref={instrument_ref})"
    )
    lines.append("")
    trigger = _cell(proposal["time_sensitive_reason"])
    lines.append(f"**Trigger:** {trigger if trigger else '(auto-generated — fill in)'}")
    very_high = bool(proposal["very_high"])
    lines.append(
        f"**Evidence roots:** {_evidence_line(evidence)} → very_high={str(very_high).lower()}"
    )
    if proposal["very_high_missing_roots"]:
        lines.append(f"**Missing roots:** {proposal['very_high_missing_roots']}")
    lines.append("**Discussion:** (fill in — DNA read and reasoning)")
    decision_text = "; ".join(
        f"{row['decision']} at {row['at']}" + (f" ({row['notes']})" if row["notes"] else "")
        for row in decision_rows
    )
    if decision_text:
        lines.append(f"**Decision:** {decision_text}")
    else:
        lines.append(
            f"**Decision:** (fill in — current_status={_cell(proposal['current_status'])})"
        )
    if fills:
        fill_text = "; ".join(
            f"fill ${row['fill_price']} at {row['fill_time']}" for row in fills
        )
        lines.append(f"**Outcome:** {fill_text}")
    else:
        lines.append("**Outcome:** (fill in — unknown if not yet observed)")
    lines.append("**Logged by:** (fill in)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal_id", type=int)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    if not args.db.exists():
        parser.error(f"db not found: {args.db}")
    conn = _connect_readonly(args.db)
    try:
        print(build_skeleton(conn, args.proposal_id, db_path=args.db))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
