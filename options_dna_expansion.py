"""Resumable, request-efficient acquisition for the Options DNA expansion.

Provider access is injected. This module neither reads credentials nor runs
unless called by the explicit DeepSeek `--fetch` workflow.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from options_dna_dataset import build_cohort_rows, write_json


@dataclass(frozen=True)
class ExpansionAcquisitionResult:
    cohort_rows: tuple[dict, ...]
    failures: tuple[dict, ...]
    reference_requests: int
    reference_cache_hits: int
    bar_requests: int
    bar_cache_hits: int
    unique_tickers: int

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["cohort_rows"] = list(self.cohort_rows)
        payload["failures"] = list(self.failures)
        return payload


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bar_cache_covers(payload: dict, start_date: str, end_date: str) -> bool:
    return (
        isinstance(payload.get("bars"), list)
        and str(payload.get("start_date", "")) <= start_date
        and str(payload.get("end_date", "")) >= end_date
    )


def acquire_expansion(
    anchors: list[dict], *, client, output: str | Path,
    dte_targets: tuple[int, ...] = (14, 30), history_days_before: int = 7,
    outcome_days_after: int = 21,
) -> ExpansionAcquisitionResult:
    """Acquire expansion rows with date-chain and union-window ticker caches."""
    output = Path(output)
    contracts_dir = output / "contracts"
    bars_dir = output / "bars"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    bars_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    candidates: list[dict] = []
    reference_requests = reference_cache_hits = 0

    contracts_by_date: dict[str, list[dict]] = {}
    for session_date in sorted({row["session_date"] for row in anchors}):
        cache_path = contracts_dir / f"{session_date}.json"
        try:
            if cache_path.exists():
                payload = _read_json(cache_path)
                contracts = payload["contracts"]
                reference_cache_hits += 1
            else:
                contracts = client.contracts_as_of(
                    symbol="AMC", anchor_date=session_date, max_dte=max(dte_targets) + 3,
                )
                reference_requests += 1
                write_json(cache_path, {"session_date": session_date, "contracts": contracts})
            contracts_by_date[session_date] = contracts
        except Exception as exc:
            failures.append({
                "session_date": session_date, "stage": "contracts", "error": str(exc)[:300],
            })

    for anchor in anchors:
        contracts = contracts_by_date.get(anchor["session_date"])
        if contracts is None:
            continue
        cohort = build_cohort_rows(
            anchor, contracts, dte_targets=dte_targets, moneyness_targets=(0.0,),
            fallback_to_nearest_strike=True,
        )
        if not cohort:
            failures.append({
                "anchor_id": anchor["anchor_id"], "stage": "selection",
                "error": "no regular contract within DTE tolerance",
            })
        candidates.extend(cohort)

    windows: dict[str, dict] = defaultdict(lambda: {"rows": [], "starts": [], "ends": []})
    for row in candidates:
        anchor_date = date.fromisoformat(row["session_date"])
        expiry = date.fromisoformat(row["expiration"])
        start = anchor_date - timedelta(days=history_days_before)
        end = min(expiry, anchor_date + timedelta(days=outcome_days_after))
        bucket = windows[row["ticker"]]
        bucket["rows"].append(row)
        bucket["starts"].append(start)
        bucket["ends"].append(end)

    acquired: list[dict] = []
    bar_requests = bar_cache_hits = 0
    for ticker in sorted(windows):
        bucket = windows[ticker]
        start = min(bucket["starts"]).isoformat()
        end = max(bucket["ends"]).isoformat()
        cache_path = bars_dir / f'{ticker.replace(":", "_")}.json'
        cached = False
        try:
            payload = _read_json(cache_path) if cache_path.exists() else {}
            if _bar_cache_covers(payload, start, end):
                bars = payload["bars"]
                cached = True
                bar_cache_hits += 1
            else:
                bars = client.option_bars(ticker, start_date=start, end_date=end)
                bar_requests += 1
                write_json(cache_path, {
                    "ticker": ticker, "start_date": start, "end_date": end, "bars": bars,
                })
            for row in bucket["rows"]:
                acquired.append(dict(
                    row,
                    bar_count=len(bars),
                    bars_file=str(cache_path.relative_to(output)),
                    cached=cached,
                    cache_start_date=start,
                    cache_end_date=end,
                ))
        except Exception as exc:
            failures.append({
                "ticker": ticker, "stage": "bars", "start_date": start,
                "end_date": end, "error": str(exc)[:300],
            })

    acquired.sort(key=lambda row: (
        row["decision_available_utc"], row["contract_type"],
        int(row["dte_target"]), row["ticker"],
    ))
    return ExpansionAcquisitionResult(
        cohort_rows=tuple(acquired),
        failures=tuple(failures),
        reference_requests=reference_requests,
        reference_cache_hits=reference_cache_hits,
        bar_requests=bar_requests,
        bar_cache_hits=bar_cache_hits,
        unique_tickers=len(windows),
    )
