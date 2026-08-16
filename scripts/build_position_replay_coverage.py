#!/usr/bin/env python3
"""Fetch, assemble and score the multi-asset position-replay coverage study.

Without --fetch this command is read-only and prints the plan. With --fetch it
acquires CALL/PUT x 14/30-DTE option bars (reusing already-fetched CALL/14
bars), then (network-free) builds exact-entry position episodes per asset and
reports per-asset, per-cell coverage against the frozen >=20 discovery / >=10
holdout episode minima.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import MassiveResearchClient, read_replay_anchors, write_csv, write_json  # noqa: E402
from options_dna_position_replay import build_position_episode_ledgers  # noqa: E402
from options_dna_position_replay_acquisition import acquire_position_replay  # noqa: E402
from scripts.assemble_options_dna_ledger import load_option_bars, load_underlying_bars  # noqa: E402

MIN_DISCOVERY = 20
MIN_HOLDOUT = 10
CELLS = ("CALL/14", "CALL/30", "PUT/14", "PUT/30")


def _read_csv(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path,
                        default=ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" / "replay")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports" / "options_dna_replication" / "position_replay")
    parser.add_argument("--bars-dir", type=Path,
                        default=ROOT / "reports" / "options_dna_replication" / "bars")
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()

    manifest_path = args.output / "manifest.json"
    anchors_path = args.output / "anchor_plan.csv"
    if not manifest_path.exists() or not anchors_path.exists():
        raise SystemExit("run scripts/plan_position_replay_coverage.py first")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    if args.fetch:
        anchors = _read_csv(anchors_path)
        result = acquire_position_replay(
            anchors, client=MassiveResearchClient(), output=args.output, bars_dir=args.bars_dir,
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
                "reference": result.reference_requests, "option_bars": result.bar_requests,
            },
            "cache_hits": {
                "reference": result.reference_cache_hits, "option_bars": result.bar_cache_hits,
            },
        })
        write_json(manifest_path, manifest)
        print(json.dumps(manifest, indent=2, sort_keys=True))
        print("NEXT (network-free): re-run without --fetch to assemble + score")
        return 2 if failures else 0

    cohort_path = args.output / "cohort_ledger.csv"
    if not cohort_path.exists():
        raise SystemExit("cohort ledger missing; run with --fetch first")
    cohort = _read_csv(cohort_path)

    # Option bars indexed by ticker (load once, shared across assets).
    option_bars_by_ticker: dict[str, list[dict]] = {}
    for row in cohort:
        ticker = row["ticker"]
        if ticker not in option_bars_by_ticker:
            option_bars_by_ticker[ticker] = load_option_bars(args.bars_dir / Path(row["bars_file"]).name)

    episodes: list[dict] = []
    all_rejections: list[dict] = []
    assets = sorted({row["symbol"] for row in cohort})
    for symbol in assets:
        symbol_cohort = [row for row in cohort if row["symbol"] == symbol]
        underlying = load_underlying_bars(args.replay_dir / f"{symbol}_events_15m.csv.gz")
        full_anchors = read_replay_anchors(args.replay_dir / f"{symbol}_events_15m.csv.gz", timeframe_minutes=15)
        result = build_position_episode_ledgers(
            symbol_cohort, full_anchors, option_bars_by_ticker, underlying,
            max_calendar_days=21,
        )
        for ep in result["episodes"]:
            ep["symbol"] = symbol
            episodes.append(ep)
        all_rejections.extend(result["rejections"])

    write_csv(args.output / "position_episode_ledger.csv", episodes)

    # Coverage: episodes per (asset, partition, contract_type, dte_target).
    cell_counts: dict[tuple, int] = defaultdict(int)
    for ep in episodes:
        key = (ep["symbol"], ep["partition"], ep["contract_type"], str(ep["dte_target"]))
        cell_counts[key] += 1

    coverage_rows = []
    for asset in assets:
        for ctype in ("CALL", "PUT"):
            for dte in ("14", "30"):
                disc = cell_counts[(asset, "DISCOVERY", ctype, dte)]
                hold = cell_counts[(asset, "HOLDOUT", ctype, dte)]
                coverage_rows.append({
                    "symbol": asset, "cell": f"{ctype}/{dte}",
                    "discovery_episodes": disc, "holdout_episodes": hold,
                    "discovery_ok": disc >= MIN_DISCOVERY, "holdout_ok": hold >= MIN_HOLDOUT,
                    "cell_pass": disc >= MIN_DISCOVERY and hold >= MIN_HOLDOUT,
                })
    write_csv(args.output / "coverage_by_cell.csv", coverage_rows)

    rejection_counts = Counter(rej.get("reason") for rej in all_rejections)
    passing_cells = [r for r in coverage_rows if r["cell_pass"]]
    report = {
        "research_only": True,
        "episodes": len(episodes),
        "rejections": len(all_rejections),
        "rejection_reasons": dict(rejection_counts),
        "min_discovery_episodes": MIN_DISCOVERY,
        "min_holdout_episodes": MIN_HOLDOUT,
        "cells": {
            f"{r['symbol']}:{r['cell']}": {
                "discovery_episodes": r["discovery_episodes"],
                "holdout_episodes": r["holdout_episodes"],
                "pass": r["cell_pass"],
            }
            for r in coverage_rows
        },
        "passing_cells": [f"{r['symbol']}:{r['cell']}" for r in passing_cells],
        "passing_cell_count": len(passing_cells),
        "total_cells": len(coverage_rows),
    }
    write_json(args.output / "coverage_report.json", report)
    print(json.dumps({
        "episodes": len(episodes),
        "rejections": len(all_rejections),
        "passing_cells": report["passing_cells"],
        "passing_cell_count": len(passing_cells),
        "total_cells": len(coverage_rows),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
