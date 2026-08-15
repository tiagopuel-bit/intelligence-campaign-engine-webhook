#!/usr/bin/env python3
"""Build simulated-position causal/future ledgers from acquired option bars."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import read_replay_anchors, write_csv, write_json  # noqa: E402
from options_dna_position_replay import build_position_episode_ledgers  # noqa: E402
from options_dna_targets import build_position_window_target_matrix  # noqa: E402
from scripts.assemble_options_dna_ledger import load_option_bars, load_underlying_bars  # noqa: E402


def _write_gzip(path: Path, rows: list[dict]) -> None:
    if not rows:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("")
        return
    fields = list(rows[0])
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path,
                        default=ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" /
                                "replay" / "AMC_events_15m.csv.gz")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports" / "options_dna_expansion")
    parser.add_argument("--max-calendar-days", type=int, default=21)
    args = parser.parse_args()
    cohort_path = args.output / "cohort_ledger.csv"
    if not cohort_path.exists():
        parser.error(f"missing {cohort_path}")
    with cohort_path.open("r", encoding="utf-8", newline="") as handle:
        cohort = list(csv.DictReader(handle))
    option_bars = {
        row["ticker"]: load_option_bars(args.output / row["bars_file"])
        for row in cohort
    }
    anchors = read_replay_anchors(args.replay, timeframe_minutes=15)
    underlying = load_underlying_bars(args.replay)
    result = build_position_episode_ledgers(
        cohort, anchors, option_bars, underlying,
        max_calendar_days=args.max_calendar_days,
    )
    write_csv(args.output / "position_episode_ledger.csv", result["episodes"])
    _write_gzip(args.output / "position_snapshot_ledger.csv.gz", result["snapshots"])
    snapshot_anchors = [
        {
            "anchor_id": row["snapshot_id"], "partition": row["partition"],
            "event_family": row["snapshot_event_family"],
            "signal_bar_open_utc": row["snapshot_signal_bar_open_utc"],
            "decision_available_utc": row["snapshot_decision_available_utc"],
        }
        for row in result["snapshots"]
    ]
    write_csv(args.output / "position_snapshot_anchor_plan.csv", snapshot_anchors)
    write_csv(args.output / "position_snapshot_outcome_windows.csv", result["outcomes"])
    position_targets = build_position_window_target_matrix(result["outcomes"])
    write_csv(args.output / "position_future_target_matrix.csv", position_targets)
    write_csv(args.output / "position_snapshot_rejections.csv", result["rejections"])
    summary = {
        "research_only": True,
        "execution_model": "exact next option bar open",
        "cost_model": "none",
        "max_calendar_days": args.max_calendar_days,
        "episodes": len(result["episodes"]),
        "snapshots": len(result["snapshots"]),
        "outcome_windows": len(result["outcomes"]),
        "future_target_rows": len(position_targets),
        "rejections": len(result["rejections"]),
    }
    write_json(args.output / "position_replay_manifest.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
