#!/usr/bin/env python3
"""Cleanup helper for test-symbol rows in the alerts DB.

Reviewable by design: defaults to DRY-RUN (prints matching rows, mutates
nothing). Requires an explicit --apply to change anything, and supports two
mutations:

  remove   DELETE the matching rows (default when --apply is given).
  tag      UPDATE symbol to a "TEST_" prefix instead of deleting, so rows are
           retained but visibly excluded from real-symbol queries.

Never run --apply against the live store without explicit go-ahead.

Usage:
  python3 cleanup_test_symbols.py                     # dry-run
  python3 cleanup_test_symbols.py --apply             # remove test rows
  python3 cleanup_test_symbols.py --apply --mode tag  # tag instead of remove
  python3 cleanup_test_symbols.py --symbol XYZ        # add an extra symbol
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "dna_alerts.db"

# Explicit allowlist (not a LIKE -- avoids matching a real symbol by accident).
TEST_SYMBOLS = {"PUBTEST", "TEST", "TEST2", "TEST_PING"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually mutate the DB (default is dry-run)")
    ap.add_argument("--mode", choices=["remove", "tag"], default="remove")
    ap.add_argument("--symbol", action="append", default=[],
                    help="extra symbol(s) to treat as test")
    ap.add_argument("--db", type=Path, default=DB_PATH)
    args = ap.parse_args()

    symbols = TEST_SYMBOLS | set(args.symbol)
    placeholders = ",".join("?" for _ in symbols)
    params = tuple(sorted(symbols))

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 2

    conn = sqlite3.connect(f"file:{args.db}?mode={'rw' if args.apply else 'ro'}", uri=True)
    conn.row_factory = sqlite3.Row

    matches = conn.execute(
        f"SELECT id, symbol, timeframe, bar_event, received_at FROM alerts "
        f"WHERE symbol IN ({placeholders}) ORDER BY id", params).fetchall()

    print(f"DB: {args.db}")
    print(f"Mode: {'APPLY ' + args.mode.upper() if args.apply else 'DRY-RUN'}")
    print(f"Matching symbols: {sorted(symbols)}")
    print(f"Matched rows: {len(matches)}")
    for r in matches:
        print(f"  id={r['id']} symbol={r['symbol']!r} tf={r['timeframe']} "
              f"event={r['bar_event']!r} at={r['received_at']}")

    if not args.apply:
        print("\nDRY-RUN: no changes made. Re-run with --apply to mutate.")
        conn.close()
        return 0

    if args.mode == "remove":
        conn.execute(
            f"DELETE FROM alerts WHERE symbol IN ({placeholders})", params)
    else:  # tag
        # Prefix the symbol so test rows are retained but clearly marked.
        for r in matches:
            conn.execute(
                "UPDATE alerts SET symbol=? WHERE id=?",
                (f"TEST_{r['symbol']}", r["id"]))
    conn.commit()
    print(f"\nAPPLIED {args.mode.upper()}: {len(matches)} rows affected.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
