#!/usr/bin/env python3
"""Freeze v1 discovery entry target cutoffs without the position-replay gate.

Entry-only scope: freezes the six predeclared v1 target definitions on
DISCOVERY entry paths and applies them unchanged to HOLDOUT entry paths. It
never emits position-management artifacts, and it fails closed on the artifact
and entry-coverage gates only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_calibration_stage import (  # noqa: E402
    CalibrationStageBlocked,
    run_entry_freeze_stage,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path,
                        default=ROOT / "reports" / "options_dna_expansion")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_entry_freeze_stage(args.path, output=args.output)
    except CalibrationStageBlocked as exc:
        print(json.dumps({"status": "BLOCKED_BY_ENTRY_GATE", "reason": str(exc)}, indent=2))
        return 3
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
