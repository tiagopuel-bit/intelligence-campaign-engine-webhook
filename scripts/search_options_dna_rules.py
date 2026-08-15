#!/usr/bin/env python3
"""Search transparent candidates on discovery; test unchanged on holdout."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_rule_stage import RuleStageBlocked, run_rule_stage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path,
                        default=ROOT / "reports" / "options_dna_expansion")
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = run_rule_stage(
            args.path, calibration=args.calibration, output=args.output,
        )
    except RuleStageBlocked as exc:
        print(json.dumps({"status": "BLOCKED_BY_TARGET_FREEZE_GATE", "reason": str(exc)}, indent=2))
        return 3
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
