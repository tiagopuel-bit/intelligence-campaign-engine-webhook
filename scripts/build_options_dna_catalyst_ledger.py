#!/usr/bin/env python3
"""Build a network-free, coverage-aware SEC catalyst ledger for Options DNA."""
from __future__ import annotations

import argparse
import csv
import json
import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_catalyst_ledger import build_catalyst_ledger  # noqa: E402
from options_dna_dataset import write_csv, write_json  # noqa: E402


def _read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--anchors", type=Path, required=True)
    parser.add_argument("--filings", type=Path, required=True,
                        help="bounded filing corpus with explicit clock coverage")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", default="catalyst",
                        help="safe output prefix (default: catalyst)")
    parser.add_argument("--active-window-hours", type=int, default=72)
    args = parser.parse_args()
    if args.active_window_hours <= 0:
        parser.error("--active-window-hours must be positive")
    if re.fullmatch(r"[a-z][a-z0-9_]*", args.prefix) is None:
        parser.error("--prefix must contain lowercase letters, digits, and underscores")

    anchors = _read_csv(args.anchors)
    payload = json.loads(args.filings.read_text(encoding="utf-8"))
    rows = build_catalyst_ledger(
        anchors, payload, active_window_hours=args.active_window_hours,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / f"{args.prefix}_ledger.csv", rows)
    counts: dict[str, int] = {}
    for row in rows:
        key = f'{row["mode"]}:{row["source_status"]}'
        counts[key] = counts.get(key, 0) + 1
    write_json(args.output / f"{args.prefix}_manifest.json", {
        "contract_version": 1,
        "network_used": False,
        "anchor_count": len(anchors),
        "ledger_rows": len(rows),
        "active_window_hours": args.active_window_hours,
        "status_counts": counts,
        "source": payload.get("source"),
        "source_as_of_utc": payload.get("as_of_utc"),
        "coverage": payload.get("coverage", {}),
    })
    print(json.dumps({"anchor_count": len(anchors), "rows": len(rows), "status_counts": counts}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
