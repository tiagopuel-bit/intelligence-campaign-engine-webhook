#!/usr/bin/env python3
"""Report live-shadow readiness from a frozen bundle and frozen criteria."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_guidance import read_bundle  # noqa: E402
from options_dna_shadow_acceptance import (  # noqa: E402
    build_shadow_acceptance_report,
    criteria_from_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--criteria", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        bundle = read_bundle(args.bundle)
        criteria = criteria_from_dict(
            json.loads(args.criteria.read_text(encoding="utf-8"))
        )
        with sqlite3.connect(args.db) as connection:
            report = build_shadow_acceptance_report(connection, bundle, criteria)
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "SHADOW_REPORT_REJECTED", "reason": str(exc)}, indent=2))
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["ready"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
