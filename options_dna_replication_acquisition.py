"""Resumable, multi-asset acquisition for the Options DNA external replication.

Provider access is injected. This module neither reads credentials nor runs
unless called by the explicit DeepSeek ``--fetch`` workflow. It acquires the
CALL/14 nearest-regular-strike cohort for each of the eight non-AMC assets,
reusing the existing reference/bar caches under the replication report dir.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from options_dna_dataset import write_json
from options_dna_research import select_contract_cohort


@dataclass(frozen=True)
class ReplicationAcquisitionResult:
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


def select_call14_contract(contracts: list[dict], *, spot: float,
                           anchor_date: str) -> dict | None:
    """Select the single CALL/14 nearest-regular-strike contract for an anchor."""
    selected = select_contract_cohort(
        contracts, spot=spot, anchor_date=anchor_date,
        dte_targets=(14,), moneyness_targets=(0.0,),
        fallback_to_nearest_strike=True,
    )
    calls = [row for row in selected if str(row.get("contract_type")) == "CALL"]
    if not calls:
        return None
    return min(calls, key=lambda row: (abs(float(row["dte"]) - 14), row["expiration"], row["strike"]))


def acquire_replication(
    anchors: list[dict], *, client, output: str | Path,
    dte_target: int = 14, history_days_before: int = 7, outcome_days_after: int = 21,
) -> ReplicationAcquisitionResult:
    """Acquire the CALL/14 cohort for every replication anchor, multi-asset."""
    output = Path(output)
    contracts_dir = output / "contracts"
    bars_dir = output / "bars"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    bars_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    candidates: list[dict] = []
    reference_requests = reference_cache_hits = 0

    contracts_by_key: dict[tuple[str, str], list[dict]] = {}
    keys = sorted({(row["symbol"], row["session_date"]) for row in anchors})
    for symbol, session_date in keys:
        cache_path = contracts_dir / f"{symbol}_{session_date}.json"
        try:
            if cache_path.exists():
                payload = _read_json(cache_path)
                contracts = payload["contracts"]
                reference_cache_hits += 1
            else:
                contracts = client.contracts_as_of(
                    symbol=symbol, anchor_date=session_date, max_dte=dte_target + 3,
                )
                reference_requests += 1
                write_json(cache_path, {
                    "symbol": symbol, "session_date": session_date, "contracts": contracts,
                })
            contracts_by_key[(symbol, session_date)] = contracts
        except Exception as exc:
            failures.append({
                "symbol": symbol, "session_date": session_date, "stage": "contracts",
                "error": str(exc)[:300],
            })

    for anchor in anchors:
        symbol = str(anchor.get("symbol") or "")
        contracts = contracts_by_key.get((symbol, anchor["session_date"]))
        if contracts is None:
            continue
        contract = select_call14_contract(
            contracts, spot=float(anchor["spot"]), anchor_date=anchor["session_date"],
        )
        if contract is None:
            failures.append({
                "anchor_id": anchor["anchor_id"], "symbol": symbol, "stage": "selection",
                "error": "no CALL/14 regular contract within DTE tolerance",
            })
            continue
        candidates.append(dict(anchor, **contract))

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
        row["decision_available_utc"], row["symbol"], row["ticker"],
    ))
    return ReplicationAcquisitionResult(
        cohort_rows=tuple(acquired),
        failures=tuple(failures),
        reference_requests=reference_requests,
        reference_cache_hits=reference_cache_hits,
        bar_requests=bar_requests,
        bar_cache_hits=bar_cache_hits,
        unique_tickers=len(windows),
    )
