#!/usr/bin/env python3
"""Plan or apply the frozen position-coverage supplement without provider calls."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import read_replay_anchors, write_csv, write_json  # noqa: E402
from options_dna_supplement import build_supplement_plan  # noqa: E402


def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "reports" / "options_dna_expansion",
    )
    parser.add_argument("--discovery-per-family", type=int, default=20)
    parser.add_argument("--holdout-per-family", type=int, default=15)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    manifest_path = args.output / "manifest.json"
    anchor_path = args.output / "anchor_plan.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in {"FETCHED", "FETCHED_WITH_FAILURES", "VERIFIED"}:
        raise SystemExit("base expansion must be fetched and assembled before supplement planning")
    base_rows = _read_csv(anchor_path)
    if any(str(row.get("anchor_id", "")).startswith("AMC15SUP-") for row in base_rows):
        raise SystemExit("supplement already applied; refusing to select again")
    replay = read_replay_anchors(manifest["raw_replay"], timeframe_minutes=15)
    plan = build_supplement_plan(
        replay, base_rows, holdout_start=manifest["holdout_start"],
        discovery_per_family=args.discovery_per_family,
        holdout_per_family=args.holdout_per_family,
    )
    summary = {
        "status": "SUPPLEMENT_FROZEN_NOT_APPLIED" if not args.apply else "SUPPLEMENT_PLAN_ONLY",
        "base_anchors": len(base_rows), "added_anchors": len(plan.added_rows),
        "combined_anchors": len(plan.combined_rows),
        "added_counts": plan.added_counts,
        "base_anchor_sha256": plan.base_anchor_sha256,
        "supplement_anchor_sha256": plan.supplement_anchor_sha256,
        "combined_anchor_sha256": plan.combined_anchor_sha256,
        "selection_rule": plan.selection_rule,
    }
    if args.apply:
        backup = args.output / "anchor_plan_base_v1.csv"
        if backup.exists():
            raise SystemExit("base anchor backup already exists; refusing to overwrite")
        write_csv(backup, base_rows)
        write_csv(anchor_path, list(plan.combined_rows))
        family_counts = Counter(
            f'{row["partition"]}:{row["event_family"]}' for row in plan.combined_rows
        )
        dates = defaultdict(set)
        for row in plan.combined_rows:
            dates[row["partition"]].add(row["session_date"])
        manifest.update({
            "status": "SUPPLEMENT_PLAN_ONLY",
            "anchor_count": len(plan.combined_rows),
            "anchor_family_counts": dict(sorted(family_counts.items())),
            "unique_session_dates": {
                partition: len(values) for partition, values in sorted(dates.items())
            },
            "supplemental_design": {
                **summary,
                "base_anchor_file": backup.name,
                "frozen_before_supplement_fetch": True,
                "execution_model_unchanged": "exact next option bar open; no fill",
                "contract_design_unchanged": True,
            },
        })
        write_json(manifest_path, manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
