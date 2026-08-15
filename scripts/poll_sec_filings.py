#!/usr/bin/env python3
"""One-shot SEC filing poll for the DNA Asset Page.

Cloud-only: runs on Railway against the persistent volume DB. Deterministic and
idempotent — the first run seeds existing filings silently; later runs emit
only newly-seen accessions. Exits nonzero on configuration or upstream failure
so a scheduler can observe it.

Usage:
    python scripts/poll_sec_filings.py --symbol AMC --once
    python scripts/poll_sec_filings.py --once            # defaults to AMC

Required env: SEC_USER_AGENT (a real contact, e.g. "DNA Campaign Engine <admin@domain>").

Recommended Railway scheduling: run this command on a five-minute cadence via
Railway's cron/service scheduler in the same environment as the webhook app
(so it shares the volume and env vars). This script does not deploy or mutate
Railway services.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sec_filings  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Poll SEC EDGAR for watched AMC filings")
    parser.add_argument("--symbol", default="AMC", help="symbol to poll (default AMC)")
    parser.add_argument("--once", action="store_true", help="run one deterministic poll and exit")
    args = parser.parse_args(argv)

    symbol = (args.symbol or "AMC").strip().upper()
    db_path = sec_filings.resolve_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Ensure the two tables exist before the first poll (fresh volumes).
    import sqlite3
    conn = sqlite3.connect(str(db_path), timeout=30)
    sec_filings.ensure_schema(conn)
    conn.commit()
    conn.close()

    result = sec_filings.poll_symbol(db_path, symbol)

    summary = {
        "symbol": result["symbol"],
        "cik": result["cik"],
        "configured": result["configured"],
        "seeded": result["seeded"],
        "new_count": len(result["new_filings"]),
        "recent_count": len(result["recent_filings"]),
        "new_filings": [
            {
                "form": f["form"],
                "category": f["category"],
                "severity": f["severity"],
                "filing_date": f["filing_date"],
                "filing_url": f["filing_url"],
            }
            for f in result["new_filings"]
        ],
        "errors": result["errors"],
        "last_polled_at": result["last_polled_at"],
        "last_success_at": result["last_success_at"],
    }
    print(json.dumps(summary, indent=2))

    if result["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
