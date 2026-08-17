"""Deterministic, causal proposal-eligibility and revalidation engine (PAPER_ONLY).

Pure functions over causal evidence. No I/O, no broker path, no future-outcome
access. Thresholds reflect policy_corrections_v1.2.json; policy_v1.json and
policy_corrections_v1.1.json remain provenance.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from paper_execution.portfolio import ANCHOR_SYMBOL

LIVE_FRESHNESS_MAX_MINUTES = 2
MIN_MATCHED_HISTORY_BARS = 12
MIN_ACTIVITY_RATIO = 0.50
ACTIVE_PRINT_EPSILON = 1e-9
VERY_HIGH_AUTO_ACTIONS = ("partial_reduce", "close")
# Auto-entry (open/add) is AMC-only per PORTFOLIO_MULTI_ASSET_SPEC §11 Option B:
# the anchor can deploy new exposure unattended when VERY_HIGH passes; every
# other symbol stays manual-only. See auto_mode_allowed().
AUTO_ENTRY_ACTIONS = ("open", "add")

LIVE_SOURCES = frozenset({"live", "live_webhook", "live_contract_bar", "heartbeat"})
DELAYED_SOURCES = frozenset({"delayed", "massive", "delayed_provider_bar"})

CLOSE_REDUCE_TRIGGERS = {
    "close": frozenset({"DRAW_DOWN_PROTECTION", "CAMPAIGN_BREAK", "CONFIDENCE_WITHDRAWN",
                        "TIME_DECAY_EXPIRY", "USER_DIRECTED"}),
    "partial_reduce": frozenset({"DRAW_DOWN_PROTECTION", "EXPOSURE_CAP", "USER_DIRECTED"}),
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _finite_number(value: object) -> float | None:
    """Fail-closed numeric parse: None for missing, malformed or non-finite."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _age_minutes(bar_time: object, now: datetime | None = None) -> float | None:
    if bar_time in (None, ""):
        return None
    now = now or _now_utc()
    try:
        if isinstance(bar_time, bool):
            return None
        if isinstance(bar_time, (int, float)):
            if not math.isfinite(float(bar_time)):
                return None
            dt = datetime.fromtimestamp(float(bar_time) / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(bar_time).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return (now - dt.astimezone(timezone.utc)).total_seconds() / 60.0


def _freshness_class(bar_time: object, source: object) -> str:
    """LIVE | DELAYED | STALE | FUTURE | NONE | UNKNOWN.

    Source is matched against explicit allowlists. An unknown source is UNKNOWN
    (never silently treated as live or delayed)."""
    src = str(source or "").strip().lower()
    if src in ("", "none", "null"):
        return "NONE"
    if src in DELAYED_SOURCES:
        return "DELAYED"
    if src not in LIVE_SOURCES:
        return "UNKNOWN"
    age = _age_minutes(bar_time)
    if age is None:
        return "NONE"
    if age < 0:
        return "FUTURE"
    if age <= LIVE_FRESHNESS_MAX_MINUTES:
        return "LIVE"
    return "STALE"


def _root_underlying_dna(evidence: dict) -> bool:
    d = evidence.get("underlying_dna") or {}
    confirm = d.get("confirm_tone")
    timing = d.get("timing_tone")
    named_agreement = confirm is not None and confirm == timing and confirm in ("pos", "neg")
    no_conflict = not d.get("upper_neg", False)
    live = _freshness_class(d.get("bar_time"), d.get("source")) == "LIVE"
    return bool(named_agreement and no_conflict and live)


def _root_contract_response(evidence: dict) -> bool:
    c = evidence.get("contract_response") or {}
    ret = _finite_number(c.get("option_return"))
    active = ret is not None and abs(ret) > ACTIVE_PRINT_EPSILON
    matched = _finite_number(c.get("matched_bars"))
    history = matched is not None and matched >= MIN_MATCHED_HISTORY_BARS
    activity = _finite_number(c.get("activity_ratio"))
    activity_ok = activity is not None and activity >= MIN_ACTIVITY_RATIO
    no_missing = not c.get("missing_bar", False)
    no_unchanged = not c.get("unchanged_print", False)
    live = _freshness_class(c.get("bar_time"), c.get("source")) == "LIVE"
    return bool(active and history and activity_ok and no_missing and no_unchanged and live)


def _root_execution_quality(evidence: dict) -> bool:
    q = evidence.get("execution_quality") or {}
    live = _freshness_class(q.get("bar_time"), q.get("source")) == "LIVE"
    priced = _finite_number(q.get("price_reference")) is not None
    no_stale = not q.get("stale", False)
    return bool(live and priced and no_stale)


def _action_direction_compatible(evidence: dict, action: str) -> bool:
    p = evidence.get("portfolio_risk") or {}
    if action in ("close", "partial_reduce"):
        if not p.get("position_exists", False):
            return False
        direction = str(p.get("direction") or "").upper()
        side = str(p.get("side") or "").lower()
        if direction == "LONG" and "sell" not in side:
            return False
        if direction == "SHORT" and "buy" not in side:
            return False
    return True


def _trigger_compatible(evidence: dict, action: str) -> bool:
    if action not in CLOSE_REDUCE_TRIGGERS:
        return True
    trigger = (evidence.get("portfolio_risk") or {}).get("trigger")
    return trigger is not None and str(trigger).upper() in CLOSE_REDUCE_TRIGGERS[action]


def _root_portfolio_risk(evidence: dict, action: str) -> bool:
    p = evidence.get("portfolio_risk") or {}
    if not _action_direction_compatible(evidence, action):
        return False
    if not _trigger_compatible(evidence, action):
        return False
    return bool(
        p.get("exposure_ok", True)
        and not p.get("duplicate", False)
        and not p.get("conflict", False)
        and p.get("daily_loss_ok", True)
    )


def auto_mode_allowed(action: str, symbol: str | None = None) -> bool:
    """Risk-reducing actions are always auto-eligible; entries (open/add) are
    auto-eligible only for the AMC anchor. Other symbols stay manual-only."""
    if action in VERY_HIGH_AUTO_ACTIONS:
        return True
    if action in AUTO_ENTRY_ACTIONS:
        return (symbol or "").upper() == ANCHOR_SYMBOL
    return False


def evaluate_very_high(evidence: dict, action: str) -> dict:
    roots = {
        "underlying_dna": _root_underlying_dna(evidence),
        "contract_response": _root_contract_response(evidence),
        "execution_quality": _root_execution_quality(evidence),
        "portfolio_risk": _root_portfolio_risk(evidence, action),
    }
    vetoes: list[str] = []
    if evidence.get("catalyst", {}).get("sec_veto", False):
        vetoes.append("SEC_CATALYST_VETO")
    if evidence.get("stale_underlying", False):
        vetoes.append("STALE_UNDERLYING")
    if evidence.get("stale_option_quote", False):
        vetoes.append("BLOCKED_STALE_OPTION_QUOTE")
    for spec in ("underlying_dna", "contract_response", "execution_quality"):
        e = evidence.get(spec) or {}
        cls = _freshness_class(e.get("bar_time"), e.get("source"))
        if cls == "UNKNOWN":
            vetoes.append("UNKNOWN_SOURCE")
        elif cls == "DELAYED":
            vetoes.append("DELAYED_PROVIDER_BAR")
        elif cls == "FUTURE":
            vetoes.append("FUTURE_TIMESTAMP")
        elif cls == "NONE":
            vetoes.append("NO_LIVE_CONTRACT_SOURCE")
    missing = [name for name, ok in roots.items() if not ok]
    return {
        "very_high": not missing and not vetoes,
        "missing_roots": missing,
        "vetoes": list(dict.fromkeys(vetoes)),
    }


def revalidate(action: str, current_evidence: dict) -> dict:
    result = evaluate_very_high(current_evidence, action)
    if result["very_high"]:
        return {"status": "VALID", "result": result}
    return {
        "status": "INVALID",
        "reason": "missing=" + ",".join(result["missing_roots"])
                  + " vetoes=" + ",".join(result["vetoes"]),
        "result": result,
    }
