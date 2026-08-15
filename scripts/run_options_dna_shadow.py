#!/usr/bin/env python3
"""Evaluate one provider-neutral Options DNA shadow input and journal it."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_guidance import read_bundle  # noqa: E402
from options_dna_shadow_runner import run_shadow_once  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        bundle = read_bundle(args.bundle)
        observed_at = args.observed_at or datetime.now(timezone.utc).isoformat()
        args.db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(args.db) as connection:
            result = run_shadow_once(
                connection, payload, bundle, observed_at_utc=observed_at,
            )
    except (OSError, ValueError, json.JSONDecodeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "SHADOW_REJECTED", "reason": str(exc)}, indent=2))
        return 2
    print(json.dumps({"status": "SHADOW_RECORDED", **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
