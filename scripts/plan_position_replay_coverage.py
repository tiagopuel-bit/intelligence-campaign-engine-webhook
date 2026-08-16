#!/usr/bin/env python3
"""Plan the multi-asset position-replay coverage sample (no provider calls).

Samples deterministic, chronologically-sealed entry-origin anchors
(ENTRY_FORMING + CONTINUATION only) for the eight non-AMC assets, at 15
discovery + 8 holdout per family per asset (30 discovery / 16 holdout per
asset), enough to test the frozen >=20 discovery / >=10 holdout episode minima
against realistic exact-execution yield.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import EVENT_FAMILIES, read_replay_anchors, write_csv, write_json  # noqa: E402

ASSETS = ("SPY", "TSLA", "GME", "U", "RBLX", "PYPL", "LULU", "VALE")
ENTRY_FAMILIES = ("ENTRY_FORMING", "CONTINUATION")
DISCOVERY_PER_FAMILY = 15
HOLDOUT_PER_FAMILY = 8
HOLDOUT_START = "2026-02-01"


def _evenly_spaced(rows: list[dict], count: int) -> list[dict]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[index] for index in indices]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path,
                        default=ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" / "replay")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports" / "options_dna_replication" / "position_replay")
    parser.add_argument("--holdout-start", default=HOLDOUT_START)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    cutoff = date.fromisoformat(args.holdout_start)
    all_rows: list[dict] = []
    per_asset: dict[str, Counter] = {}
    for symbol in ASSETS:
        anchors = read_replay_anchors(args.replay_dir / f"{symbol}_events_15m.csv.gz", timeframe_minutes=15)
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for anchor in sorted(anchors, key=lambda row: row["decision_available_utc"]):
            if anchor["event_family"] not in ENTRY_FAMILIES:
                continue
            partition = "HOLDOUT" if date.fromisoformat(anchor["session_date"]) >= cutoff else "DISCOVERY"
            groups[(partition, anchor["event_family"])].append(anchor)
        sampled: list[dict] = []
        for partition, count in (("DISCOVERY", DISCOVERY_PER_FAMILY), ("HOLDOUT", HOLDOUT_PER_FAMILY)):
            for family in ENTRY_FAMILIES:
                for row in _evenly_spaced(groups[(partition, family)], count):
                    sampled.append(dict(row, partition=partition))
        sampled.sort(key=lambda row: row["decision_available_utc"])
        for index, row in enumerate(sampled, start=1):
            row["symbol"] = symbol
            row["anchor_id"] = f"{symbol}-PR-{index:04d}"
        per_asset[symbol] = Counter((row["partition"], row["event_family"]) for row in sampled)
        all_rows.extend(sampled)

    all_rows.sort(key=lambda row: (row["decision_available_utc"], row["symbol"]))
    write_csv(args.output / "anchor_plan.csv", all_rows)
    unique_dates = {row["session_date"] for row in all_rows}
    unique_pairs = {(row["symbol"], row["session_date"]) for row in all_rows}
    manifest = {
        "status": "PLAN_ONLY",
        "purpose": "multi-asset position-replay coverage; entry-origin anchors only",
        "assets": list(ASSETS),
        "cells": ["CALL/14", "CALL/30", "PUT/14", "PUT/30"],
        "holdout_start": args.holdout_start,
        "anchor_count": len(all_rows),
        "discovery_per_family": DISCOVERY_PER_FAMILY,
        "holdout_per_family": HOLDOUT_PER_FAMILY,
        "anchors_by_asset": {
            symbol: {f"{p}:{f}": n for (p, f), n in sorted(counts.items())}
            for symbol, counts in per_asset.items()
        },
        "unique_session_dates": len(unique_dates),
        "unique_symbol_session_pairs": len(unique_pairs),
        "no_provider_request_during_plan": True,
    }
    write_json(args.output / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
