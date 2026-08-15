#!/usr/bin/env python3
"""Build the future-only multi-window target matrix; never fit guidance."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import write_csv, write_json  # noqa: E402
from options_dna_targets import (  # noqa: E402
    TARGET_HYPOTHESES_V1,
    WINDOWS,
    build_window_target_matrix,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path,
                        default=ROOT / "reports" / "options_dna_expansion")
    args = parser.parse_args()
    source = args.path / "forward_outcome_windows.csv"
    if not source.exists():
        parser.error(f"missing {source}")
    with source.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    matrix = build_window_target_matrix(rows)
    write_csv(args.path / "future_target_matrix.csv", matrix)
    complete = {
        window: sum(bool(row[f"{window}__complete"]) for row in matrix)
        for window in WINDOWS
    }
    write_json(args.path / "target_hypotheses_v1.json", {
        "version": 1,
        "status": "HYPOTHESES_ONLY_NOT_CALIBRATED",
        "future_only": True,
        "contract_rows": len(matrix),
        "complete_windows": complete,
        "hypotheses": [
            {
                "name": item.name, "purpose": item.purpose,
                "conditions": [condition.__dict__ for condition in item.conditions],
            }
            for item in TARGET_HYPOTHESES_V1
        ],
    })
    print(json.dumps({"contract_rows": len(matrix), "complete_windows": complete}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
