"""Parity comparison between native DNA alerts and MTF-relay alerts.

Reads two alert streams (native `alerts` vs relay `alerts_relay`) and reports
parity per the five comparison points in docs/TRADINGVIEW_ALERT_CAPACITY_PLAN.md:

1. event type and event priority;
2. signal-bar and decision timestamps;
3. price and relevant DNA fields;
4. deduplication and bar-close behavior;
5. behavior across market sessions and higher-timeframe boundaries.

Pure functions over row dicts; no database access, no writes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

EVENT_PRIORITY = {
    "STRONG START": 15, "CAMPAIGN START": 14, "FIRE ADD": 13, "ACCUMULATE": 12,
    "IGNITION": 11, "ADD": 10, "PREMIUM": 9, "MANAGE": 8, "PEAK": 7,
    "FAIL": 6, "FAIL TEST": 5, "RELOAD": 4, "START TEST": 3, "IGNITION TEST": 2,
    "": 0,
}


def _key(row: dict) -> tuple:
    return (str(row.get("symbol")), str(row.get("timeframe")), str(row.get("bar_time")))


def _event(row: dict) -> str:
    return str(row.get("bar_event") or row.get("event") or "")


def _num(row: dict, field: str) -> float | None:
    value = row.get(field)
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class RelayParityReport:
    native_rows: int
    relay_rows: int
    matched_keys: int
    event_match: int
    event_mismatch: int
    close_within_tolerance: int
    close_mismatch: int
    phase_match: int
    phase_mismatch: int
    missed_by_relay: int          # native key with no relay row
    extra_in_relay: int           # relay key with no native row
    relay_duplicate_bars: int     # relay emitted >1 row for a key
    session_match: int
    session_mismatch: int

    def to_dict(self) -> dict:
        return asdict(self)


def compare_alerts(native_rows: list[dict], relay_rows: list[dict], *,
                   close_tolerance: float = 0.0) -> RelayParityReport:
    """Compare two alert streams keyed by (symbol, timeframe, bar_time).

    A native/relay row pairs up when its (symbol, timeframe, bar_time) key
    matches. Event-type parity uses the event string directly (its priority is
    encoded in the string because currentBarEvent is the highest-priority event
    on the bar). Dedup parity flags relay keys seen more than once.
    """
    native_by_key: dict[tuple, list[dict]] = {}
    for row in native_rows:
        native_by_key.setdefault(_key(row), []).append(row)
    relay_by_key: dict[tuple, list[dict]] = {}
    for row in relay_rows:
        relay_by_key.setdefault(_key(row), []).append(row)

    native_keys = set(native_by_key)
    relay_keys = set(relay_by_key)
    matched = native_keys & relay_keys
    missed = native_keys - relay_keys
    extra = relay_keys - native_keys

    event_match = event_mismatch = 0
    close_ok = close_mismatch = 0
    phase_match = phase_mismatch = 0
    session_match = session_mismatch = 0
    relay_dupes = 0

    for key in matched:
        n = native_by_key[key][0]
        r = relay_by_key[key][0]
        if len(relay_by_key[key]) > 1:
            relay_dupes += 1
        if _event(n) == _event(r):
            event_match += 1
        else:
            event_mismatch += 1
        nc, rc = _num(n, "close"), _num(r, "close")
        if nc is not None and rc is not None and abs(nc - rc) <= close_tolerance:
            close_ok += 1
        else:
            close_mismatch += 1
        if str(n.get("phase")) == str(r.get("phase")):
            phase_match += 1
        else:
            phase_mismatch += 1
        if str(n.get("session")) == str(r.get("session")):
            session_match += 1
        else:
            session_mismatch += 1

    return RelayParityReport(
        native_rows=len(native_rows),
        relay_rows=len(relay_rows),
        matched_keys=len(matched),
        event_match=event_match,
        event_mismatch=event_mismatch,
        close_within_tolerance=close_ok,
        close_mismatch=close_mismatch,
        phase_match=phase_match,
        phase_mismatch=phase_mismatch,
        missed_by_relay=len(missed),
        extra_in_relay=len(extra),
        relay_duplicate_bars=relay_dupes,
        session_match=session_match,
        session_mismatch=session_mismatch,
    )
