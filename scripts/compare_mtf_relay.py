#!/usr/bin/env python3
"""Compare native DNA alerts vs MTF-relay alerts in the local database.

Reads `alerts` (native, source of truth) and `alerts_relay` (the relay running
alongside), keys each by (symbol, timeframe, bar_time), and prints the parity
report per the five comparison points. Read-only; no provider calls.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mtf_relay_compare import compare_alerts  # noqa: E402


def _rows(db_path: str, table: str) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        f"SELECT symbol, timeframe, bar_time, bar_event, phase, health, close, session FROM {table}"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "dna_alerts.db"))
    parser.add_argument("--close-tolerance", type=float, default=0.0)
    args = parser.parse_args()

    native = _rows(args.db, "alerts")
    relay = _rows(args.db, "alerts_relay")
    report = compare_alerts(native, relay, close_tolerance=args.close_tolerance)
    import json
    print(json.dumps(report.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
