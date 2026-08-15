#!/usr/bin/env python3
"""Evaluate the frozen candidate against the assembled multi-asset replication.

Reads the replication cohort/component/target artifacts, applies the frozen AMC
CONFIRMATION_FAILURE and EARLY_PREMIUM_CONFIRMATION CALL/14 cutoffs unchanged,
and reports per-asset + asset-balanced pooled results against the frozen
acceptance gates. No thresholds are fit; no provider calls.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_replication import build_replication_rows, evaluate_replication  # noqa: E402
from options_dna_targets import build_window_target_matrix  # noqa: E402


def _read_csv(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _frozen_cutoffs(definitions_path: Path, targets: tuple[str, ...],
                    cell: tuple[str, str, str]) -> dict[str, tuple]:
    definitions = json.loads(definitions_path.read_text(encoding="utf-8"))
    result: dict[str, tuple] = {}
    for definition in definitions["definitions"]:
        if definition.get("name") not in targets:
            continue
        for c in definition.get("cells", []):
            if tuple(c.get("cell_values", [])) != cell:
                continue
            result[definition["name"]] = tuple(
                (cutoff["field"], cutoff["operator"], float(cutoff["threshold"]))
                for cutoff in c.get("cutoffs", [])
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "options_dna_replication")
    parser.add_argument("--definitions", type=Path,
                        default=ROOT / "reports" / "options_dna_expansion" /
                                "entry_calibration_v1" / "target_definitions_v1.json")
    parser.add_argument("--assets", nargs="*", default=None)
    args = parser.parse_args()

    out = args.output
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assets = tuple(args.assets or manifest.get("assets", []))
    if not assets:
        parser.error("no assets; pass --assets or set manifest assets")

    cohort = _read_csv(out / "cohort_ledger.csv")
    component = _read_csv(out / "component_ledger.csv.gz")
    window_rows = _read_csv(out / "forward_outcome_windows.csv")
    matrix = build_window_target_matrix(window_rows)
    cutoffs = _frozen_cutoffs(
        args.definitions,
        ("CONFIRMATION_FAILURE", "EARLY_PREMIUM_CONFIRMATION"),
        ("CALL", "14", "0.0"),
    )
    rows = build_replication_rows(cohort, component, matrix, cutoffs)
    report = evaluate_replication(rows, symbols=assets)
    (out / "replication_evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    print(json.dumps({
        "assets": len(assets),
        "scored_rows": len(rows),
        "passing_assets": report["passing_assets"],
        "pooled_pass": report["pooled_pass"],
        "replication_status": report["replication_status"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
