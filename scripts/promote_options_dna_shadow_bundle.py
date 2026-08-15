#!/usr/bin/env python3
"""Promote only robust, countertarget-clear candidates to shadow-only rules."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_guidance import write_bundle  # noqa: E402
from options_dna_promotion import (  # noqa: E402
    build_shadow_bundle,
    counter_audit_from_dict,
    validation_from_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path,
                        default=ROOT / "reports" / "options_dna_expansion")
    parser.add_argument("--rule-search", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    search = args.rule_search or args.path / "rule_search_v1"
    try:
        search_manifest = json.loads((search / "manifest.json").read_text(encoding="utf-8"))
        if search_manifest.get("stage") != "HISTORICAL_CANDIDATE_VALIDATION":
            raise ValueError("candidate-validation stage missing")
        validations = [
            validation_from_dict(row)
            for row in json.loads((search / "candidate_validations.json").read_text(encoding="utf-8"))
        ]
        audits = [
            counter_audit_from_dict(row)
            for row in json.loads((search / "countertarget_audit.json").read_text(encoding="utf-8"))
        ]
        manifest = json.loads((args.path / "manifest.json").read_text(encoding="utf-8"))
        with (args.path / "anchor_plan.csv").open("r", encoding="utf-8", newline="") as handle:
            anchors = list(csv.DictReader(handle))
        discovery_times = [
            row["decision_available_utc"] for row in anchors if row["partition"] == "DISCOVERY"
        ]
        if not discovery_times:
            raise ValueError("discovery anchors missing")
        holdout_start = str(manifest["holdout_start"]) + "T00:00:00Z"
        bundle = build_shadow_bundle(
            validations, audits, source_manifest_path=args.path / "manifest.json",
            discovery_end_utc=max(discovery_times), holdout_start_utc=holdout_start,
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "NO_SHADOW_BUNDLE", "reason": str(exc)}, indent=2))
        return 3
    output = args.output or args.path / "shadow_bundle_v1.json"
    write_bundle(output, bundle)
    print(json.dumps({
        "status": "FROZEN_SHADOW_ONLY", "rules": len(bundle.rules),
        "bundle_hash": bundle.bundle_hash, "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
