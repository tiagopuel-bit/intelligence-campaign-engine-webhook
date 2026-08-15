#!/usr/bin/env python3
"""Assemble the Options DNA AMC 15m pilot evidence ledger (research-only).

Reads the fetched cohort ledger + per-contract bars and the audited underlying
replay, joins every option bar to the identical underlying 15m bar-open
timestamp, evaluates the causal component ledger at each anchor's
decision_available_utc bar, and records research-only forward outcomes that
begin after that bar (never at signal_bar_open_utc).

Writes only beneath reports/options_dna_pilot/. No provider calls; no
credential handling.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import options_dna  # noqa: E402
from options_dna_research import (  # noqa: E402
    forward_long_premium_path_outcome,
    forward_long_premium_path_until,
)

HORIZON_BARS = 21 * 26  # ~21 trading days of 15m RTH bars
OUTCOME_FIELDS = (
    "outcome_status", "right_censored", "observed_bars", "decision_close", "next_bar_open",
    "decision_to_next_open_gap_pct", "mfe_pct", "mae_pct",
    "terminal_return_pct", "bars_to_peak", "bars_to_trough",
    "peak_to_terminal_giveback_pct", "gain_retention",
    "decision_close_mfe_pct", "decision_close_mae_pct", "peak_before_trough",
)
TIME_WINDOWS = (
    ("H1", 4),
    ("D1", 26),
    ("D3", 78),
    ("D5", 130),
    ("D10", 260),
)


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def load_underlying_bars(replay_path: Path) -> list[dict]:
    opener = gzip.open if str(replay_path).endswith(".gz") else open
    bars: list[dict] = []
    with opener(replay_path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            t_ms = _to_ms(_parse_utc(row["t_utc"]))
            bars.append({
                "t": t_ms,
                "o": float(row["open"]),
                "h": float(row["high"]),
                "l": float(row["low"]),
                "c": float(row["close"]),
                "v": float(row["Volume"]),
            })
    return bars


def load_option_bars(bars_path: Path) -> list[dict]:
    payload = json.loads(bars_path.read_text(encoding="utf-8"))
    return payload["bars"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replay", type=Path,
                        default=ROOT.parent / "_deepseek_expanded_rerun_stage" / "audited_output" /
                                "replay" / "AMC_events_15m.csv.gz")
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "options_dna_pilot")
    args = parser.parse_args()

    out = args.output
    with (out / "cohort_ledger.csv").open(encoding="utf-8", newline="") as handle:
        cohort = list(csv.DictReader(handle))
    underlying = load_underlying_bars(args.replay)
    underlying_by_t = {b["t"]: b for b in underlying}

    component_rows: list[dict] = []
    outcome_rows: list[dict] = []
    window_rows: list[dict] = []
    rejections: list[dict] = []
    cell: dict = defaultdict(lambda: {"anchors": set(), "contracts": 0, "ready": 0, "matched": [], "censored": 0})

    for row in cohort:
        ticker = row["ticker"]
        decision_ms = _to_ms(_parse_utc(row["decision_available_utc"]))
        signal_ms = _to_ms(_parse_utc(row["signal_bar_open_utc"]))
        option_bars = load_option_bars(out / row["bars_file"])

        # The DNA event is known when its source bar closes at decision_ms. In
        # aggregate data that bar is identified by its open at signal_ms. If
        # the option did not trade on that exact bar, do not move the decision
        # to the next printed option bar.
        option_times = {int(b["t"]) for b in option_bars}
        signal_idx = next((i for i, b in enumerate(option_bars) if int(b["t"]) == signal_ms), None)
        signal_exists = signal_idx is not None
        left_censored = not any(int(b["t"]) <= signal_ms for b in option_bars)

        # Full underlying history is required so activity_ratio measures option
        # sparsity against the actual underlying bars, not an already-matched
        # subset that would make the ratio mechanically equal to one.
        hist_option = [b for b in option_bars if int(b["t"]) <= signal_ms]
        hist_under = [b for b in underlying if int(b["t"]) <= signal_ms]

        matched_all = sorted({int(b["t"]) for b in option_bars} & set(underlying_by_t))
        before = sum(1 for t in matched_all if t < signal_ms)
        at = int(signal_ms in matched_all)
        after = sum(1 for t in matched_all if t > signal_ms)

        if signal_exists:
            ledger = options_dna.component_ledger(
                hist_option, hist_under,
                contract_type=row["contract_type"], strike=float(row["strike"]),
                expiration=row["expiration"],
            )
        else:
            ledger = {
                "ready": False,
                "quality_reasons": ["signal option bar absent"],
                "matched_bars": len(options_dna.align_bars(hist_option, hist_under)),
                "activity_ratio": None,
            }

        outcome = {"outcome_status": "UNSCORED_SIGNAL_BAR_ABSENT"}
        if signal_idx is not None:
            try:
                outcome = forward_long_premium_path_outcome(option_bars, signal_idx, HORIZON_BARS)
                if outcome.get("observed_bars", 0) == 0:
                    outcome["outcome_status"] = "UNSCORED_NO_POST_SIGNAL_BAR"
                elif outcome.get("right_censored"):
                    outcome["outcome_status"] = "SCORED_RIGHT_CENSORED"
                else:
                    outcome["outcome_status"] = "SCORED_COMPLETE_HORIZON"
            except (ValueError, IndexError):
                outcome = {
                    "outcome_status": "UNSCORED_INVALID_PATH",
                    "right_censored": None,
                    "observed_bars": 0,
                }

        base = {
            "anchor_id": row["anchor_id"], "ticker": ticker, "contract_type": row["contract_type"],
            "strike": row["strike"], "expiration": row["expiration"],
            "dte_target": row["dte_target"], "moneyness_target": row["moneyness_target"],
            "partition": row["partition"], "event_family": row["event_family"],
            "decision_available_utc": row["decision_available_utc"],
            "signal_bar_open_utc": row["signal_bar_open_utc"],
            "coverage_before": before, "coverage_at": at, "coverage_after": after,
            "left_censored": left_censored, "signal_bar_exists": signal_exists,
            "bar_count": int(row["bar_count"]),
        }
        for optional_field in (
            "selection_policy", "moneyness_band", "moneyness_distance_pct",
            "moneyness_pct", "dte",
        ):
            if optional_field in row:
                base[optional_field] = row[optional_field]
        component_rows.append(dict(base, ready=ledger["ready"],
                                   matched_bars=ledger["matched_bars"],
                                   activity_ratio=ledger["activity_ratio"],
                                   quality_reasons="|".join(ledger["quality_reasons"]),
                                   **{k: v for k, v in ledger.items()
                                      if k not in ("ready", "matched_bars", "activity_ratio", "quality_reasons")}))
        outcome_rows.append(dict(
            base,
            **{
                field: outcome.get(
                    field,
                    0 if field == "observed_bars" else None,
                )
                for field in OUTCOME_FIELDS
            },
        ))
        signal_under_idx = next(
            (i for i, bar in enumerate(underlying) if int(bar["t"]) == signal_ms), None,
        )
        for window_name, underlying_bars_forward in TIME_WINDOWS:
            window_outcome = {"outcome_status": "UNSCORED_SIGNAL_BAR_ABSENT"}
            cutoff_ms = None
            censor_reason = None
            right_censored = None
            if signal_under_idx is not None:
                desired_index = signal_under_idx + underlying_bars_forward
                cutoff_index = min(desired_index, len(underlying) - 1)
                cutoff_ms = int(underlying[cutoff_index]["t"])
                underlying_truncated = cutoff_index < desired_index
                expiry_before_cutoff = datetime.fromisoformat(row["expiration"]).date() < \
                    datetime.fromtimestamp(cutoff_ms / 1000, tz=timezone.utc).date()
                right_censored = underlying_truncated or expiry_before_cutoff
                censor_reason = (
                    "UNDERLYING_DATA_END" if underlying_truncated
                    else "CONTRACT_EXPIRY" if expiry_before_cutoff else None
                )
                if signal_idx is not None:
                    try:
                        window_outcome = forward_long_premium_path_until(
                            option_bars, signal_idx, cutoff_ms,
                        )
                        if window_outcome.get("observed_bars", 0) == 0:
                            window_outcome["outcome_status"] = "UNSCORED_NO_POST_SIGNAL_PRINT"
                        elif right_censored:
                            window_outcome["outcome_status"] = "SCORED_RIGHT_CENSORED"
                        else:
                            window_outcome["outcome_status"] = "SCORED_WINDOW"
                    except (ValueError, IndexError):
                        window_outcome = {
                            "outcome_status": "UNSCORED_INVALID_PATH", "observed_bars": 0,
                        }
            window_rows.append(dict(
                base,
                window=window_name,
                underlying_bars_forward=underlying_bars_forward,
                cutoff_time_ms=cutoff_ms,
                censor_reason=censor_reason,
                right_censored=right_censored,
                **{
                    field: window_outcome.get(field)
                    for field in OUTCOME_FIELDS
                    if field not in {"outcome_status", "right_censored"}
                },
                outcome_status=window_outcome.get("outcome_status"),
            ))
        for reason in ledger["quality_reasons"]:
            rejections.append({"anchor_id": row["anchor_id"], "ticker": ticker,
                               "contract_type": row["contract_type"], "dte_target": row["dte_target"],
                               "reason": reason})
        cell[(row["partition"], row["event_family"], row["contract_type"], row["dte_target"])]["anchors"].add(row["anchor_id"])
        cell[(row["partition"], row["event_family"], row["contract_type"], row["dte_target"])]["contracts"] += 1
        if ledger["ready"]:
            cell[(row["partition"], row["event_family"], row["contract_type"], row["dte_target"])]["ready"] += 1
        cell[(row["partition"], row["event_family"], row["contract_type"], row["dte_target"])]["matched"].append(ledger["matched_bars"])
        if left_censored or outcome.get("right_censored"):
            cell[(row["partition"], row["event_family"], row["contract_type"], row["dte_target"])]["censored"] += 1

    _write_gz(out / "component_ledger.csv.gz", component_rows)
    _write_csv(out / "forward_outcomes.csv", outcome_rows)
    _write_csv(out / "forward_outcome_windows.csv", window_rows)
    _write_csv(out / "quality_rejections.csv", rejections)

    coverage_rows = []
    for key in sorted(cell):
        partition, family, ctype, dte = key
        c = cell[key]
        matched = c["matched"]
        coverage_rows.append({
            "partition": partition, "event_family": family, "contract_type": ctype, "dte_target": dte,
            "anchors": len(c["anchors"]), "contracts": c["contracts"], "ready": c["ready"],
            "matched_bars_min": min(matched) if matched else None,
            "matched_bars_max": max(matched) if matched else None,
            "censored": c["censored"],
        })
    _write_csv(out / "coverage_by_cell.csv", coverage_rows)

    print(json.dumps({"component_rows": len(component_rows), "outcome_rows": len(outcome_rows),
                      "window_outcome_rows": len(window_rows),
                      "rejection_rows": len(rejections), "coverage_cells": len(coverage_rows)},
                     indent=2))
    return 0


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_gz(path: Path, rows: list[dict]) -> None:
    import gzip as _gzip
    if not rows:
        with _gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
            handle.write("")
        return
    fields = list(rows[0])
    with _gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
