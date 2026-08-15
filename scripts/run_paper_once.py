#!/usr/bin/env python3
"""One-shot paper runner (intended for a Railway scheduled service).

Revalidates user-approved and due auto proposals through the independently
gated atomic claim and fresh authoritative state, then executes a real paper
fill. Without a wired authoritative cloud provider the runner reports
BLOCKED_NO_AUTHORITATIVE_CLOUD_PROVIDER and does not substitute delayed prices.

Usage:
    python scripts/run_paper_once.py --db /data/paper.db --webhook-db /data/dna_alerts.db
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from paper_execution import db  # noqa: E402
from paper_execution.cloud_state import cloud_state_provider  # noqa: E402
from paper_execution.runner import run_once  # noqa: E402


def _provider_from_file(path: str):
    snapshot = json.loads(Path(path).read_text(encoding="utf-8"))

    def provider(db_path, symbol):
        return snapshot.get(symbol)
    return provider


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=ROOT / "paper_execution" / "paper.db")
    parser.add_argument("--webhook-db", type=str, default=None,
                        help="canonical webhook alert/position DB (production provider)")
    parser.add_argument("--state", type=str, default=None,
                        help="test-only synthetic authoritative-state JSON (not for production)")
    args = parser.parse_args()

    db.init_db(args.db)

    if args.webhook_db:
        provider = cloud_state_provider(args.webhook_db)
    elif args.state:
        provider = _provider_from_file(args.state)
    else:
        print(json.dumps({
            "status": "BLOCKED_NO_AUTHORITATIVE_CLOUD_PROVIDER",
            "reason": "no --webhook-db (production) or --state (test-only) supplied",
        }, indent=2))
        return 1

    results = run_once(args.db, provider)
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
