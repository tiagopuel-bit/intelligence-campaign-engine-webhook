"""Research-only acquisition plan for synchronized Options DNA cohorts.

This module deliberately stops short of producing guidance.  It selects
causal anchor bars from the audited underlying replay and describes/fetches a
small, deterministic option cohort around each anchor.  Provider credentials
are read from the environment and are never written to an artifact.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

from massive_ohlc import api_key, limiter
from massive_options import BASE_URL, UpstreamError, _shape_bars
from options_dna_research import select_contract_cohort


EVENT_COLUMNS = (
    "Event: STRONG START",
    "Event: CAMPAIGN START",
    "Event: IGNITION",
    "Event: ADD",
    "Event: RELOAD",
    "Event: MANAGE",
    "Event: PEAK",
    "Event: FAIL (any severity)",
    "Event: FAIL TEST",
)

# A bar can contain more than one event.  Pressure/veto evidence owns the
# classification, followed by risk, continuation and formation.
EVENT_FAMILIES = (
    ("THESIS_PRESSURE", ("FAIL (any severity)", "FAIL TEST")),
    ("RISK_OR_EXHAUSTION", ("PEAK", "MANAGE")),
    ("CONTINUATION", ("ADD", "RELOAD")),
    ("ENTRY_FORMING", ("IGNITION", "CAMPAIGN START", "STRONG START")),
)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _family(events: tuple[str, ...]) -> str | None:
    present = set(events)
    for family, members in EVENT_FAMILIES:
        if present.intersection(members):
            return family
    return None


def source_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_replay_anchors(path: str | Path, *, timeframe_minutes: int) -> list[dict]:
    """Read event-bearing bars from an audited replay CSV/CSV.GZ.

    The event is available only at the end of its bar.  Both timestamps are
    retained so later code cannot accidentally score the signal at bar open.
    """
    opener = gzip.open if str(path).endswith(".gz") else open
    anchors: list[dict] = []
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            events = tuple(
                column.removeprefix("Event: ")
                for column in EVENT_COLUMNS if _truthy(row.get(column))
            )
            family = _family(events)
            if family is None:
                continue
            opened = _parse_utc(row["t_utc"])
            available = opened + timedelta(minutes=timeframe_minutes)
            anchors.append({
                "signal_bar_open_utc": opened.isoformat(),
                "decision_available_utc": available.isoformat(),
                "session_date": opened.date().isoformat(),
                "spot": float(row["close"]),
                "event_family": family,
                "events": "|".join(events),
                "campaign_health": _optional_float(row.get("campaignHealth")),
                "phase_confidence": _optional_float(row.get("phaseConfidence")),
                "weakness_count": _optional_float(row.get("weaknessCount")),
            })
    return anchors


def _optional_float(value: object) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _evenly_spaced(rows: list[dict], count: int) -> list[dict]:
    if count <= 0 or not rows:
        return []
    if len(rows) <= count:
        return rows
    if count == 1:
        return [rows[len(rows) // 2]]
    indices = [round(i * (len(rows) - 1) / (count - 1)) for i in range(count)]
    return [rows[index] for index in indices]


def select_anchor_sample(
    anchors: list[dict], *, holdout_start: str, per_family_partition: int = 2,
) -> list[dict]:
    """Return deterministic, time-distributed discovery and holdout anchors."""
    cutoff = date.fromisoformat(holdout_start)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for anchor in sorted(anchors, key=lambda row: row["decision_available_utc"]):
        partition = "HOLDOUT" if date.fromisoformat(anchor["session_date"]) >= cutoff else "DISCOVERY"
        groups[(partition, anchor["event_family"])].append(anchor)

    sampled: list[dict] = []
    for partition in ("DISCOVERY", "HOLDOUT"):
        for family, _members in EVENT_FAMILIES:
            for row in _evenly_spaced(groups[(partition, family)], per_family_partition):
                sampled.append(dict(row, partition=partition))
    sampled.sort(key=lambda row: row["decision_available_utc"])
    for index, row in enumerate(sampled, start=1):
        row["anchor_id"] = f"AMC15-{index:03d}"
    return sampled


def select_anchor_sample_by_partition(
    anchors: list[dict], *, holdout_start: str, per_family: dict[str, int],
) -> list[dict]:
    """Select unequal discovery/holdout counts without changing the time seal."""
    cutoff = date.fromisoformat(holdout_start)
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for anchor in sorted(anchors, key=lambda row: row["decision_available_utc"]):
        partition = "HOLDOUT" if date.fromisoformat(anchor["session_date"]) >= cutoff else "DISCOVERY"
        groups[(partition, anchor["event_family"])].append(anchor)

    sampled: list[dict] = []
    for partition in ("DISCOVERY", "HOLDOUT"):
        count = int(per_family.get(partition, 0))
        for family, _members in EVENT_FAMILIES:
            for row in _evenly_spaced(groups[(partition, family)], count):
                sampled.append(dict(row, partition=partition))
    sampled.sort(key=lambda row: row["decision_available_utc"])
    for index, row in enumerate(sampled, start=1):
        row["anchor_id"] = f"AMC15X-{index:03d}"
    return sampled


class MassiveResearchClient:
    """Small authenticated client sharing the production free-plan limiter."""

    def __init__(self, key: str | None = None) -> None:
        self.key = key if key is not None else api_key()
        if not self.key:
            raise UpstreamError(503, "Massive API key not configured")

    def _get(self, url: str, params: dict) -> list[dict]:
        rows: list[dict] = []
        for attempt in range(4):
            limiter.wait()
            response = requests.get(url, params=params, timeout=30)
            if response.status_code == 429:
                retry = response.headers.get("Retry-After", "60")
                import time
                try:
                    time.sleep(min(65.0, max(1.0, float(retry))))
                except ValueError:
                    time.sleep(60.0)
                continue
            if response.status_code != 200:
                raise UpstreamError(response.status_code, response.text[:300])
            payload = response.json()
            rows.extend(payload.get("results", []))
            next_url = payload.get("next_url")
            if not next_url:
                return rows
            url = next_url
            params = {"apiKey": self.key}
        raise UpstreamError(429, "rate limited after retries")

    def contracts_as_of(self, *, symbol: str, anchor_date: str, max_dte: int) -> list[dict]:
        start = date.fromisoformat(anchor_date)
        end = start + timedelta(days=max_dte)
        return self._get(
            f"{BASE_URL}/v3/reference/options/contracts",
            {
                "underlying_ticker": symbol,
                "as_of": anchor_date,
                "expired": "false",
                "expiration_date.gte": anchor_date,
                "expiration_date.lte": end.isoformat(),
                "sort": "expiration_date",
                "order": "asc",
                "limit": "1000",
                "apiKey": self.key,
            },
        )

    def option_bars(
        self, ticker: str, *, start_date: str, end_date: str,
        multiplier: int = 15, timespan: str = "minute",
    ) -> list[dict]:
        rows = self._get(
            f"{BASE_URL}/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{start_date}/{end_date}",
            {"adjusted": "true", "sort": "asc", "limit": "50000", "apiKey": self.key},
        )
        return _shape_bars(rows)


def build_cohort_rows(
    anchor: dict, contracts: list[dict], *, dte_targets=(14, 30, 60),
    moneyness_targets=(0.0,), fallback_to_nearest_strike: bool = False,
) -> list[dict]:
    selected = select_contract_cohort(
        contracts,
        spot=anchor["spot"],
        anchor_date=anchor["session_date"],
        dte_targets=dte_targets,
        moneyness_targets=moneyness_targets,
        fallback_to_nearest_strike=fallback_to_nearest_strike,
    )
    return [dict(anchor, **contract) for contract in selected]


def write_json(path: str | Path, payload: object) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: str | Path, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    fields = list(rows[0])
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
