#!/usr/bin/env python3
"""Execute the frozen AMC Options DNA expansion through the Massive client.

Without --fetch this command is read-only and prints the plan. Provider access
is reserved for the explicit DeepSeek execution environment.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import MassiveResearchClient, write_csv, write_json  # noqa: E402
from options_dna_expansion import acquire_expansion  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "reports" / "options_dna_expansion",
    )
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    manifest_path = args.output / "manifest.json"
    anchors_path = args.output / "anchor_plan.csv"
    if not manifest_path.exists() or not anchors_path.exists():
        raise SystemExit("run scripts/plan_options_dna_expansion.py first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not args.fetch:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    with anchors_path.open(encoding="utf-8", newline="") as handle:
        anchors = list(csv.DictReader(handle))
    result = acquire_expansion(
        anchors,
        client=MassiveResearchClient(),
        output=args.output,
        dte_targets=(14, 30),
    )
    cohort_rows = list(result.cohort_rows)
    failures = list(result.failures)
    write_csv(args.output / "cohort_ledger.csv", cohort_rows)
    write_json(args.output / "failures.json", failures)
    manifest.update({
        "status": "FETCHED_WITH_FAILURES" if failures else "FETCHED",
        "cohort_count": len(cohort_rows),
        "failure_count": len(failures),
        "unique_ticker_count": result.unique_tickers,
        "request_counts": {
            "reference": result.reference_requests,
            "option_bars": result.bar_requests,
        },
        "cache_hits": {
            "reference": result.reference_cache_hits,
            "option_bars": result.bar_cache_hits,
        },
    })
    write_json(manifest_path, manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    print(
        "NEXT (network-free): python3 scripts/assemble_options_dna_ledger.py "
        f"--output {args.output}"
    )
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
