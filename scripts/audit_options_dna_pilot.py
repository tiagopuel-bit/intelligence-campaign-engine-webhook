#!/usr/bin/env python3
"""Audit an Options DNA pilot directory without fetching or calibrating."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_acceptance import audit_pilot_directory  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path", nargs="?", type=Path,
        default=ROOT / "reports" / "options_dna_pilot",
    )
    parser.add_argument(
        "--require-calibration-coverage", action="store_true",
        help="exit 3 when review passes but frozen cell minimums do not",
    )
    args = parser.parse_args()
    report = audit_pilot_directory(args.path)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if report.status == "READY_FOR_REVIEW":
        if args.require_calibration_coverage and not report.calibration_coverage_ready:
            return 3
        return 0
    return 2 if report.status == "INCOMPLETE_ACQUISITION" else 1


if __name__ == "__main__":
    raise SystemExit(main())
