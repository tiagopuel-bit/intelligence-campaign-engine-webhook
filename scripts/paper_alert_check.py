#!/usr/bin/env python3
"""Read-only poll for meaningful Portfolio Challenge events.

Meaningful = a new VERY_HIGH proposal awaiting approval, or a proposal that
just transitioned to PAPER_EXECUTED. Everything else (blockers, low-confidence
observations, routine status) is silent by design -- this feeds a phone push
notification and must not become noise.

Never writes to any Railway/paper_execution state. Only reads
/paper/proposals and /paper/health, and keeps its own local "what have we
already notified about" cursor in runtime/.paper_alert_state.json (gitignored,
local-only).

Usage: python3 scripts/paper_alert_check.py
Prints one JSON object to stdout: {"events": [{"type": ..., "message": ...}, ...]}
Empty "events" means nothing new -- the caller should stay silent.
"""
import json
import os
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent.parent
ENV_FILE = HERE / "runtime" / ".env"
STATE_FILE = HERE / "runtime" / ".paper_alert_state.json"
BASE_URL = "https://dna-tradingview-webhook-production.up.railway.app"


def load_token():
    if not ENV_FILE.exists():
        print(json.dumps({"error": f"missing {ENV_FILE}"}))
        sys.exit(1)
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line.startswith("STATE_API_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    print(json.dumps({"error": "STATE_API_TOKEN not found in runtime/.env"}))
    sys.exit(1)


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {"max_proposal_id_seen": 0, "notified_executed_ids": []}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def main():
    token = load_token()
    headers = {"Authorization": f"Bearer {token}"}
    state = load_state()
    events = []

    try:
        resp = requests.get(f"{BASE_URL}/paper/proposals", headers=headers, timeout=15)
        resp.raise_for_status()
        proposals = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"error": f"fetch failed: {exc}", "events": []}))
        return

    max_id_seen = state.get("max_proposal_id_seen", 0)
    notified_executed = set(state.get("notified_executed_ids", []))
    new_max_id = max_id_seen

    for p in proposals:
        pid = p.get("id")
        if pid is None:
            continue
        new_max_id = max(new_max_id, pid)

        # New VERY_HIGH proposal awaiting a decision, not seen before.
        if pid > max_id_seen and p.get("status") == "PENDING_APPROVAL" and bool(p.get("very_high")):
            events.append({
                "type": "new_very_high_proposal",
                "message": f"Proposal #{pid}: {p.get('action')} {p.get('symbol')} — VERY_HIGH, awaiting your decision.",
            })

        # A proposal that actually executed, not previously notified.
        if p.get("status") == "PAPER_EXECUTED" and pid not in notified_executed:
            events.append({
                "type": "paper_executed",
                "message": f"Proposal #{pid}: {p.get('action')} {p.get('symbol')} — paper-executed.",
            })
            notified_executed.add(pid)

    state["max_proposal_id_seen"] = new_max_id
    state["notified_executed_ids"] = sorted(notified_executed)
    save_state(state)

    print(json.dumps({"events": events}))


if __name__ == "__main__":
    main()
