#!/usr/bin/env python3
"""Plan or acquire a bounded AMC Options DNA calibration dataset.

The default is plan-only and performs no network calls.  Use --fetch only in
an authorized environment that already has MASSIVE_API_KEY configured.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import (  # noqa: E402
    MassiveResearchClient,
    build_cohort_rows,
    read_replay_anchors,
    select_anchor_sample,
    source_sha256,
    write_csv,
    write_json,
)


def parse_args() -> argparse.Namespace:
    default_replay = (
        ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" /
        "replay" / "AMC_events_15m.csv.gz"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path, default=default_replay)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "options_dna_pilot")
    parser.add_argument("--holdout-start", default="2026-02-01")
    parser.add_argument("--per-family-partition", type=int, default=2)
    parser.add_argument("--fetch", action="store_true", help="perform rate-limited provider requests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    anchors = read_replay_anchors(args.replay, timeframe_minutes=15)
    sample = select_anchor_sample(
        anchors,
        holdout_start=args.holdout_start,
        per_family_partition=args.per_family_partition,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "anchor_plan.csv", sample)
    manifest = {
        "status": "PLAN_ONLY" if not args.fetch else "FETCHING",
        "symbol": "AMC",
        "timeframe": "15m",
        "raw_replay": str(args.replay),
        "raw_replay_sha256": source_sha256(args.replay),
        "holdout_start": args.holdout_start,
        "anchor_count": len(sample),
        "anchor_family_counts": {},
        "contract_design": {
            "types": ["CALL", "PUT"],
            "dte_targets": [14, 30, 60],
            "moneyness_targets": [0.0],
            "bar_timeframe": "15m",
            "history_days_before": 7,
            "outcome_days_after": 21,
        },
        "causal_note": "DNA event is available at decision_available_utc; outcomes start after it.",
        "provider": "Massive Options Basic aggregates/reference; no Greeks, IV, OI or quotes claimed.",
    }
    for row in sample:
        key = f'{row["partition"]}:{row["event_family"]}'
        manifest["anchor_family_counts"][key] = manifest["anchor_family_counts"].get(key, 0) + 1

    if not args.fetch:
        write_json(args.output / "manifest.json", manifest)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        return 0

    client = MassiveResearchClient()
    cohort_rows: list[dict] = []
    bars_dir = args.output / "bars"
    bars_dir.mkdir(exist_ok=True)
    failures: list[dict] = []
    for anchor in sample:
        try:
            contracts = client.contracts_as_of(
                symbol="AMC", anchor_date=anchor["session_date"], max_dte=63,
            )
            cohort = build_cohort_rows(anchor, contracts)
        except Exception as exc:  # recorded per anchor so a long free-plan run can resume
            failures.append({"anchor_id": anchor["anchor_id"], "stage": "contracts", "error": str(exc)[:300]})
            continue
        for row in cohort:
            start = date.fromisoformat(row["session_date"]) - timedelta(days=7)
            expiry = date.fromisoformat(row["expiration"])
            end = min(expiry, date.fromisoformat(row["session_date"]) + timedelta(days=21))
            target = bars_dir / f'{row["ticker"].replace(":", "_")}.json'
            try:
                if target.exists():
                    bars = json.loads(target.read_text(encoding="utf-8"))["bars"]
                    cached = True
                else:
                    bars = client.option_bars(
                        row["ticker"], start_date=start.isoformat(), end_date=end.isoformat(),
                    )
                    write_json(target, {"ticker": row["ticker"], "bars": bars})
                    cached = False
                cohort_rows.append(dict(
                    row,
                    bar_count=len(bars),
                    bars_file=str(target.relative_to(args.output)),
                    cached=cached,
                ))
            except Exception as exc:
                failures.append({
                    "anchor_id": anchor["anchor_id"], "ticker": row.get("ticker"),
                    "stage": "bars", "error": str(exc)[:300],
                })

    write_csv(args.output / "cohort_ledger.csv", cohort_rows)
    write_json(args.output / "failures.json", failures)
    manifest.update({
        "status": "FETCHED_WITH_FAILURES" if failures else "FETCHED",
        "cohort_count": len(cohort_rows),
        "failure_count": len(failures),
    })
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
