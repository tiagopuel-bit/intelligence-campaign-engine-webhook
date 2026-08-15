"""Build a causal, coverage-aware catalyst ledger for Options DNA research.

This module is deliberately network-free.  A provider/collector must supply a
bounded SEC filing corpus plus an explicit coverage declaration.  Missing or
partial coverage is recorded as ``SOURCE_UNAVAILABLE`` and is never converted
to an inactive catalyst state.
"""
from __future__ import annotations

from datetime import datetime, timezone

from options_dna_catalyst import catalyst_context_at


MODES = ("PUBLIC_ACCEPTANCE", "OPERATIONAL_SEEN")


def _utc(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _coverage_status(coverage: object, decision_available_utc: str) -> tuple[bool, str]:
    if not isinstance(coverage, dict):
        return False, "COVERAGE_NOT_DECLARED"
    if coverage.get("complete") is not True:
        return False, "COVERAGE_NOT_COMPLETE"
    start = _utc(coverage.get("start_utc"))
    end = _utc(coverage.get("end_utc"))
    decision = _utc(decision_available_utc)
    if start is None or end is None or decision is None or start > end:
        return False, "COVERAGE_BOUNDS_INVALID"
    if decision < start or decision > end:
        return False, "DECISION_OUTSIDE_COVERAGE"
    return True, "COVERED"


def _flat_row(anchor: dict, *, mode: str, source_status: str, reason: str,
              context: dict | None, source: str | None, as_of_utc: str | None) -> dict:
    context = context or {}
    return {
        "anchor_id": anchor.get("anchor_id"),
        "partition": anchor.get("partition"),
        "event_family": anchor.get("event_family"),
        "signal_bar_open_utc": anchor.get("signal_bar_open_utc"),
        "decision_available_utc": anchor.get("decision_available_utc"),
        "mode": mode,
        "source_status": source_status,
        "source_reason": reason,
        "source": source,
        "source_as_of_utc": as_of_utc,
        "active": context.get("active") if context else None,
        "filing_count": context.get("filing_count") if context else None,
        "severity": context.get("severity") if context else None,
        "base_form": context.get("base_form") if context else None,
        "category": context.get("category") if context else None,
        "age_hours": context.get("age_hours") if context else None,
        "capacity_only": context.get("capacity_only") if context else None,
        "available_at_utc": context.get("available_at_utc") if context else None,
        "accession": context.get("accession") if context else None,
        # Kept explicit in the research ledger: catalysts never own direction.
        "direction_claim": None,
    }


def build_catalyst_ledger(
    anchors: list[dict], source_payload: dict, *, active_window_hours: int = 72,
    modes: tuple[str, ...] = MODES,
) -> list[dict]:
    """Return two causal clock scenarios per anchor when requested.

    ``source_payload`` contract::

        {
          "source": "sec-submissions-and-archives",
          "as_of_utc": "...",
          "coverage": {
            "PUBLIC_ACCEPTANCE": {"complete": true, "start_utc": "...", "end_utc": "..."},
            "OPERATIONAL_SEEN": {"complete": true, "start_utc": "...", "end_utc": "..."}
          },
          "filings": [...]
        }

    A historical backfill will usually cover ``PUBLIC_ACCEPTANCE`` only.
    ``OPERATIONAL_SEEN`` must be declared complete only for periods in which a
    real collector was running; reconstructed poll times are forbidden.
    """
    if not isinstance(source_payload, dict):
        raise ValueError("source payload must be an object")
    filings = source_payload.get("filings")
    if not isinstance(filings, list):
        raise ValueError("source payload filings must be a list")
    coverage_by_mode = source_payload.get("coverage")
    if not isinstance(coverage_by_mode, dict):
        coverage_by_mode = {}

    normalized_modes = tuple(str(mode).strip().upper() for mode in modes)
    if not normalized_modes or any(mode not in MODES for mode in normalized_modes):
        raise ValueError("unsupported catalyst clock mode")
    rows: list[dict] = []
    for anchor in anchors:
        decision = anchor.get("decision_available_utc")
        if _utc(decision) is None:
            raise ValueError(f"invalid decision timestamp for anchor {anchor.get('anchor_id')}")
        for mode in normalized_modes:
            covered, reason = _coverage_status(coverage_by_mode.get(mode), str(decision))
            if not covered:
                rows.append(_flat_row(
                    anchor, mode=mode, source_status="SOURCE_UNAVAILABLE",
                    reason=reason, context=None, source=source_payload.get("source"),
                    as_of_utc=source_payload.get("as_of_utc"),
                ))
                continue
            context = catalyst_context_at(
                filings, str(decision), mode=mode,
                active_window_hours=active_window_hours,
            )
            rows.append(_flat_row(
                anchor, mode=mode,
                source_status="ACTIVE" if context["active"] else "INACTIVE",
                reason="COVERED", context=context,
                source=source_payload.get("source"),
                as_of_utc=source_payload.get("as_of_utc"),
            ))
    return rows
