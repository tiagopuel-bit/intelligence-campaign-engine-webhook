#!/usr/bin/env python3
"""Create the network-free AMC Options DNA calibration expansion plan."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import (  # noqa: E402
    read_replay_anchors,
    select_anchor_sample_by_partition,
    source_sha256,
    write_csv,
    write_json,
)
from options_dna_shadow_acceptance import (  # noqa: E402
    SHADOW_ACCEPTANCE_CRITERIA_V1,
    criteria_from_dict,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replay", type=Path,
        default=ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" /
                "replay" / "AMC_events_15m.csv.gz",
    )
    parser.add_argument(
        "--output", type=Path,
        default=ROOT / "reports" / "options_dna_expansion",
    )
    parser.add_argument("--holdout-start", default="2026-02-01")
    parser.add_argument("--discovery-per-family", type=int, default=15)
    parser.add_argument("--holdout-per-family", type=int, default=8)
    args = parser.parse_args()

    anchors = read_replay_anchors(args.replay, timeframe_minutes=15)
    sample = select_anchor_sample_by_partition(
        anchors,
        holdout_start=args.holdout_start,
        per_family={
            "DISCOVERY": args.discovery_per_family,
            "HOLDOUT": args.holdout_per_family,
        },
    )
    args.output.mkdir(parents=True, exist_ok=True)
    write_csv(args.output / "anchor_plan.csv", sample)
    criteria_path = args.output / "shadow_acceptance_criteria_v1.json"
    write_json(criteria_path, SHADOW_ACCEPTANCE_CRITERIA_V1)
    criteria = criteria_from_dict(SHADOW_ACCEPTANCE_CRITERIA_V1)
    counts: dict[str, int] = {}
    dates: dict[str, set[str]] = {"DISCOVERY": set(), "HOLDOUT": set()}
    for row in sample:
        key = f'{row["partition"]}:{row["event_family"]}'
        counts[key] = counts.get(key, 0) + 1
        dates[row["partition"]].add(row["session_date"])
    manifest = {
        "status": "PLAN_ONLY",
        "purpose": "calibration expansion; no thresholds selected",
        "symbol": "AMC",
        "timeframe": "15m",
        "raw_replay": str(args.replay),
        "raw_replay_sha256": source_sha256(args.replay),
        "holdout_start": args.holdout_start,
        "anchor_count": len(sample),
        "anchor_family_counts": counts,
        "unique_session_dates": {key: len(value) for key, value in dates.items()},
        "contract_design": {
            "types": ["CALL", "PUT"],
            "dte_targets": [14, 30],
            "moneyness_target": 0.0,
            "selection": "nearest regular 100-share strike when ±7.5% ATM is unavailable",
            "record_actual_fields": [
                "moneyness_pct", "moneyness_distance_pct", "moneyness_band",
                "selection_policy",
            ],
            "bar_timeframe": "15m",
        },
        "acceptance_targets": {
            "discovery_independent_exact_signal_anchors_per_contract_cell": 20,
            "holdout_independent_exact_signal_anchors_per_contract_cell": 10,
            "cell_fields": ["contract_type", "dte_target"],
            "event_family_balance_report_required": True,
            "no_fill": True,
        },
        "catalyst_design": {
            "required": True,
            "required_modes": ["PUBLIC_ACCEPTANCE"],
            "optional_modes": ["OPERATIONAL_SEEN"],
            "active_window_hours": 72,
            "coverage_rule": "missing SEC coverage is unavailable, never inactive",
            "operational_clock_rule": "genuine first_seen_at only; reconstruction forbidden",
        },
        "target_design": {
            "required": True,
            "version": 1,
            "windows": ["H1", "D1", "D3", "D5", "D10"],
            "status": "hypotheses frozen before expansion; numeric cutoffs not fitted",
            "right_censored_rule": "status retained; numeric calibration fields blank",
            "future_only": True,
        },
        "position_replay_design": {
            "required": True,
            "entry_origins": ["ENTRY_FORMING", "CONTINUATION"],
            "execution_model": "exact next option bar open",
            "max_calendar_days": 21,
            "discovery_independent_episodes_per_cell": 20,
            "holdout_independent_episodes_per_cell": 10,
            "cell_fields": ["contract_type", "dte_target"],
            "cost_model": "none; no spread, fees, slippage, sizing, exercise or assignment",
            "snapshot_rule": "same contract at exact later DNA signal bars; no fill",
        },
        "shadow_acceptance_design": {
            "required": True,
            "criteria_file": criteria_path.name,
            "criteria_file_sha256": hashlib.sha256(criteria_path.read_bytes()).hexdigest(),
            "criteria_hash": criteria.criteria_hash,
            "frozen_before_expansion_results": True,
        },
        "provider_execution_owner": "DeepSeek; shared Massive free-plan limiter",
    }
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
