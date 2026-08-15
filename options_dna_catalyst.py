"""Causal SEC catalyst context for Options DNA research and shadow mode."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


_EASTERN = ZoneInfo("America/New_York")
_SEVERITY = {"INFO": 1, "MEDIUM": 2, "HIGH": 3}


def _timestamp(value: object, *, sec_eastern_if_naive: bool = False) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if text.isdigit() and len(text) == 14:
            parsed = datetime.strptime(text, "%Y%m%d%H%M%S")
            return parsed.replace(tzinfo=_EASTERN).astimezone(timezone.utc)
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_EASTERN if sec_eastern_if_naive else timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def catalyst_context_at(
    filings: list[dict], decision_available_utc: str, *,
    mode: str = "OPERATIONAL_SEEN", active_window_hours: int = 72,
) -> dict:
    """Return filing context available at a decision timestamp.

    PUBLIC_ACCEPTANCE is a historical research scenario using the SEC-provided
    acceptance clock. OPERATIONAL_SEEN models actual system availability and
    excludes seed records, which were discovered during initialization rather
    than as live alerts.
    """
    normalized_mode = mode.strip().upper()
    if normalized_mode not in {"PUBLIC_ACCEPTANCE", "OPERATIONAL_SEEN"}:
        raise ValueError("mode must be PUBLIC_ACCEPTANCE or OPERATIONAL_SEEN")
    decision = _timestamp(decision_available_utc)
    if decision is None:
        raise ValueError("invalid decision timestamp")

    available = []
    for filing in filings:
        if normalized_mode == "OPERATIONAL_SEEN":
            if bool(filing.get("seed_record")):
                continue
            observed = _timestamp(filing.get("first_seen_at"))
        else:
            observed = _timestamp(filing.get("acceptance_time"), sec_eastern_if_naive=True)
        if observed is None or observed > decision:
            continue
        age_hours = (decision - observed).total_seconds() / 3600.0
        if age_hours > active_window_hours:
            continue
        available.append((filing, observed, age_hours))

    if not available:
        return {
            "mode": normalized_mode,
            "active": False,
            "filing_count": 0,
            "severity": None,
            "base_form": None,
            "category": None,
            "age_hours": None,
            "capacity_only": False,
            "direction_claim": None,
        }

    filing, observed, age_hours = max(
        available,
        key=lambda item: (_SEVERITY.get(str(item[0].get("severity")).upper(), 0), item[1]),
    )
    base_form = str(filing.get("base_form") or "").upper() or None
    return {
        "mode": normalized_mode,
        "active": True,
        "filing_count": len(available),
        "severity": str(filing.get("severity") or "").upper() or None,
        "base_form": base_form,
        "category": filing.get("category"),
        "age_hours": age_hours,
        "capacity_only": base_form == "S-3",
        # A filing changes urgency/context. Direction must come from market and
        # underlying DNA evidence, never from the filing category alone.
        "direction_claim": None,
        "available_at_utc": observed.isoformat(),
        "accession": filing.get("accession"),
    }


def join_anchor_catalysts(
    anchors: list[dict], filings: list[dict], *, mode: str,
    active_window_hours: int = 72,
) -> list[dict]:
    return [
        dict(
            anchor,
            catalyst=catalyst_context_at(
                filings,
                anchor["decision_available_utc"],
                mode=mode,
                active_window_hours=active_window_hours,
            ),
        )
        for anchor in anchors
    ]
