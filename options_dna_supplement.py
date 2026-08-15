"""Deterministic coverage-only supplement for the Options DNA expansion."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date


SUPPLEMENT_FAMILIES = {"ENTRY_FORMING", "CONTINUATION"}


@dataclass(frozen=True)
class SupplementPlan:
    added_rows: tuple[dict, ...]
    combined_rows: tuple[dict, ...]
    added_counts: dict[str, int]
    base_anchor_sha256: str
    supplement_anchor_sha256: str
    combined_anchor_sha256: str
    selection_rule: str

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["added_rows"] = list(self.added_rows)
        payload["combined_rows"] = list(self.combined_rows)
        return payload


def _rows_hash(rows: list[dict]) -> str:
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _evenly_spaced(rows: list[dict], count: int) -> list[dict]:
    if count <= 0 or not rows:
        return []
    if len(rows) < count:
        raise ValueError(f"supplement pool has {len(rows)} rows; {count} required")
    if count == 1:
        return [rows[len(rows) // 2]]
    indexes = [round(index * (len(rows) - 1) / (count - 1)) for index in range(count)]
    return [rows[index] for index in indexes]


def build_supplement_plan(
    replay_anchors: list[dict], base_rows: list[dict], *, holdout_start: str,
    discovery_per_family: int = 20, holdout_per_family: int = 15,
) -> SupplementPlan:
    """Add unused entry/continuation anchors without inspecting option results."""
    cutoff = date.fromisoformat(holdout_start)
    base_keys = {
        (str(row.get("signal_bar_open_utc")), str(row.get("event_family")))
        for row in base_rows
    }
    if len(base_keys) != len(base_rows):
        raise ValueError("base anchor plan contains duplicate event identities")
    groups = defaultdict(list)
    for row in sorted(replay_anchors, key=lambda item: item["decision_available_utc"]):
        family = str(row.get("event_family"))
        key = (str(row.get("signal_bar_open_utc")), family)
        if family not in SUPPLEMENT_FAMILIES or key in base_keys:
            continue
        partition = (
            "HOLDOUT" if date.fromisoformat(str(row["session_date"])) >= cutoff
            else "DISCOVERY"
        )
        groups[(partition, family)].append(dict(row, partition=partition))

    selected = []
    for partition, count in (
        ("DISCOVERY", discovery_per_family), ("HOLDOUT", holdout_per_family),
    ):
        for family in ("ENTRY_FORMING", "CONTINUATION"):
            selected.extend(_evenly_spaced(groups[(partition, family)], count))
    selected.sort(key=lambda item: item["decision_available_utc"])
    for index, row in enumerate(selected, start=1):
        row["anchor_id"] = f"AMC15SUP-{index:03d}"
        row["supplement_reason"] = "POSITION_REPLAY_COVERAGE_ONLY"

    combined = [dict(row) for row in base_rows] + selected
    combined.sort(key=lambda item: item["decision_available_utc"])
    identities = [
        (row["signal_bar_open_utc"], row["event_family"]) for row in combined
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("supplement overlaps base or duplicates an event")
    ids = [str(row.get("anchor_id") or "") for row in combined]
    if not all(ids) or len(ids) != len(set(ids)):
        raise ValueError("combined anchor IDs must be non-empty and unique")
    counts = Counter(f'{row["partition"]}:{row["event_family"]}' for row in selected)
    return SupplementPlan(
        added_rows=tuple(selected), combined_rows=tuple(combined),
        added_counts=dict(sorted(counts.items())),
        base_anchor_sha256=_rows_hash(base_rows),
        supplement_anchor_sha256=_rows_hash(selected),
        combined_anchor_sha256=_rows_hash(combined),
        selection_rule=(
            "unused ENTRY_FORMING/CONTINUATION events, evenly spaced within the "
            f"unchanged {holdout_start} chronological partitions; no option availability "
            "or future outcome used for selection"
        ),
    )
