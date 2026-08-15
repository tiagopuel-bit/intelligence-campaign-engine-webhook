#!/usr/bin/env python3
"""Pre-register the multi-asset external replication anchor plan (no provider calls).

Selects a deterministic, chronologically-sealed CALL/14 anchor plan for the eight
non-AMC assets from the already-audited underlying 15m replays. This stage reads
only existing underlying ledgers and never fetches option chains or bars.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from options_dna_dataset import EVENT_FAMILIES, read_replay_anchors, write_csv, write_json  # noqa: E402

REPLICATION_ASSETS = ("SPY", "TSLA", "GME", "U", "RBLX", "PYPL", "LULU", "VALE")

# Frozen candidate under replication (unchanged from Checkpoint B).
FROZEN_CANDIDATE = {
    "target": "CONFIRMATION_FAILURE",
    "scope": "OBSERVE_ENTRY",
    "contract_type": "CALL",
    "dte_target": "14",
    "moneyness_policy": "nearest regular 100-share strike when ±7.5% ATM is unavailable",
    "conditions": [
        {"feature": "contract__close_location", "operator": "<=", "threshold": 0.33333333333333354},
        {"feature": "underlying__campaign_health", "operator": "<=", "threshold": 31.600000000000005},
    ],
    "active_print_definition": "non-zero causal contract__option_return (epsilon 1e-9)",
    "execution_clock": "exact next option-bar open; no shifted or synthetic fill",
}


def _evenly_spaced(rows: list[dict], count: int) -> list[dict]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[index] for index in indices]


def select_asset_anchors(anchors: list[dict], *, holdout_start: str,
                         discovery_per_family: int, holdout_per_family: int,
                         symbol: str) -> list[dict]:
    cutoff = date.fromisoformat(holdout_start)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for anchor in sorted(anchors, key=lambda row: row["decision_available_utc"]):
        partition = "HOLDOUT" if date.fromisoformat(anchor["session_date"]) >= cutoff else "DISCOVERY"
        groups[(partition, anchor["event_family"])].append(anchor)
    sampled: list[dict] = []
    for partition, count in (("DISCOVERY", discovery_per_family), ("HOLDOUT", holdout_per_family)):
        for family, _members in EVENT_FAMILIES:
            for row in _evenly_spaced(groups[(partition, family)], count):
                sampled.append(dict(row, partition=partition))
    sampled.sort(key=lambda row: row["decision_available_utc"])
    for index, row in enumerate(sampled, start=1):
        row["symbol"] = symbol
        row["anchor_id"] = f"{symbol}-{index:04d}"
    return sampled


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay-dir", type=Path,
                        default=ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" / "replay")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "options_dna_replication")
    parser.add_argument("--holdout-start", default="2026-02-01")
    parser.add_argument("--discovery-per-family", type=int, default=8)
    parser.add_argument("--holdout-per-family", type=int, default=4)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict] = []
    source_hashes: dict[str, str] = {}
    per_asset_counts: dict[str, Counter] = {}
    for symbol in REPLICATION_ASSETS:
        replay_path = args.replay_dir / f"{symbol}_events_15m.csv.gz"
        source_hashes[symbol] = _sha256_bytes(replay_path.read_bytes())
        anchors = read_replay_anchors(replay_path, timeframe_minutes=15)
        sampled = select_asset_anchors(
            anchors, holdout_start=args.holdout_start,
            discovery_per_family=args.discovery_per_family,
            holdout_per_family=args.holdout_per_family, symbol=symbol,
        )
        per_asset_counts[symbol] = Counter(
            (row["partition"], row["event_family"]) for row in sampled
        )
        all_rows.extend(sampled)

    all_rows.sort(key=lambda row: (row["decision_available_utc"], row["symbol"]))
    write_csv(args.output / "anchor_plan.csv", all_rows)

    criteria_path = args.output / "acceptance_criteria_v1.json"
    criteria = json.loads(criteria_path.read_text(encoding="utf-8")) \
        if criteria_path.exists() else {}

    manifest = {
        "status": "R0_PLAN_ONLY",
        "purpose": "multi-asset external replication; no thresholds fit, no outcomes read",
        "candidate": FROZEN_CANDIDATE,
        "candidate_sha256": _sha256_bytes(
            json.dumps(FROZEN_CANDIDATE, sort_keys=True).encode("utf-8")
        ),
        "assets": list(REPLICATION_ASSETS),
        "cell": {"contract_type": "CALL", "dte_target": "14"},
        "holdout_start": args.holdout_start,
        "anchor_count": len(all_rows),
        "anchor_counts_by_asset": {
            symbol: {f"{p}:{f}": n for (p, f), n in sorted(counts.items())}
            for symbol, counts in per_asset_counts.items()
        },
        "source_replay_sha256": source_hashes,
        "acceptance_criteria_file": criteria_path.name,
        "acceptance_criteria_sha256": _sha256_bytes(criteria_path.read_bytes()) if criteria_path.exists() else None,
        "amc_provenance_only": True,
    }
    write_json(args.output / "manifest.json", manifest)

    # Request-budget preview (no provider call; estimates from the plan only).
    unique_session_dates = {row["session_date"] for row in all_rows}
    budget = {
        "planned_anchors": len(all_rows),
        "unique_session_dates": len(unique_session_dates),
        "expected_reference_requests": len(unique_session_dates),
        "expected_option_bar_requests_upper_bound": len(all_rows),
        "expected_total_requests_upper_bound": len(unique_session_dates) + len(all_rows),
        "rate_limit": "5 requests/minute (shared Massive free-plan limiter)",
        "estimated_minutes_upper_bound": round((len(unique_session_dates) + len(all_rows)) * 12 / 60, 1),
        "history_note": "audited 15m replay covers 2024-08-12 -> 2026-08-11 for every asset",
        "no_provider_request_during_r0": True,
    }
    write_json(args.output / "request_budget.json", budget)

    print(json.dumps({
        "anchors": len(all_rows),
        "by_asset": {symbol: sum(counts.values()) for symbol, counts in per_asset_counts.items()},
        "unique_session_dates": len(unique_session_dates),
        "candidate_sha256": manifest["candidate_sha256"],
        "acceptance_criteria_sha256": manifest["acceptance_criteria_sha256"],
        "expected_total_requests_upper_bound": budget["expected_total_requests_upper_bound"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
