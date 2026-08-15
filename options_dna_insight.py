"""Research-only contract-specific insight library (Options DNA).

Maps causal evidence — underlying DNA, option premium activity, liquidity /
unchanged prints, DTE, campaign pressure and catalyst risk — into an advisory
navigation action. This module is an unvalidated EXPERIMENTAL heuristic: it
never issues an order, never repeats visible position facts as an insight, and
never reads future outcomes. Actions are research vocabulary only.
"""
from __future__ import annotations

import math

ACTIONS = ("WATCH", "MANAGE", "PROTECT", "REDUCE", "CLOSE", "ROLL")

# Causal thresholds (pre-registered, not fitted).
DTE_PRESSURE_DAYS = 10
ROLL_MIN_DTE_DAYS = 21
PREMIUM_SPIKE_RETURN = 0.25
PREMIUM_SPIKE_VOLUME_RATIO = 3.0
ACTIVE_PRINT_EPSILON = 1e-9


def _finite(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _insight(action: str, code: str, evidence: list[str], change_condition: str,
             confidence: str) -> dict:
    return {
        "action": action,
        "rationale_code": code,
        "evidence": evidence,
        "decision_change_condition": change_condition,
        "confidence": confidence,
    }


def contract_insight(observation: dict) -> dict:
    """Return {action, rationale_code, evidence, decision_change_condition,
    confidence} for one contract observation.

    The decision is deterministic and causal; precedence is (1) catalyst veto,
    (2) broken campaign, (3) deep-ITM roll, (4) DTE pressure, (5) weakening,
    (6) unchanged/illiquid, (7) conflicting evidence, (8) constructive,
    (9) fallback WATCH.
    """
    underlying = observation.get("underlying") or {}
    contract = observation.get("contract") or {}
    catalyst = observation.get("catalyst") or {}
    position = observation.get("position") or {}

    campaign = str(underlying.get("campaign_tone") or "neu").lower()
    upper_neg = bool(underlying.get("upper_neg", False))
    exhaustion = bool(underlying.get("exhaustion_warning", False))
    sec_veto = bool(catalyst.get("sec_veto", False))
    sec_active = bool(catalyst.get("sec_active", False))
    unchanged = bool(contract.get("unchanged_print", False))
    dte = _finite(contract.get("dte"))
    itm = contract.get("itm")
    premium = _finite(contract.get("premium_return"))
    volume = _finite(contract.get("volume_ratio"))
    has_position = bool(position.get("exists", False))

    # 1. Catalyst veto: a high-severity offering is an independent risk flag.
    if sec_veto:
        action = "PROTECT" if has_position else "WATCH"
        return _insight(
            action, "SEC_OFFERING_VETO",
            ["high-severity SEC offering/dilution filing is active"],
            "the filing ages out of the active window or is otherwise resolved",
            "structural",
        )

    # 2. Broken campaign: upper-tier failure under a position.
    if upper_neg or campaign == "neg":
        action = "CLOSE" if has_position else "WATCH"
        return _insight(
            action, "CAMPAIGN_BROKEN",
            ["upper-tier FAIL/FAIL-TEST evidence on a deciding timeframe"],
            "a RELOAD or STRONG START fires on a deciding tier",
            "structural",
        )

    # 3. Deep-ITM premium spike in a constructive campaign -> consider roll.
    spike = (premium is not None and premium > PREMIUM_SPIKE_RETURN) or \
            (volume is not None and volume > PREMIUM_SPIKE_VOLUME_RATIO)
    if itm is True and campaign == "pos" and spike and dte is not None and dte > ROLL_MIN_DTE_DAYS:
        return _insight(
            "ROLL", "DEEP_ITM_PREMIUM_SPIKE",
            ["in the money", "constructive campaign", "premium/volume spike", "room on the clock"],
            "a PEAK/MANAGE event fires, or DTE drops under the roll floor",
            "mechanical",
        )

    # 4. DTE pressure on an OTM contract.
    if dte is not None and dte <= DTE_PRESSURE_DAYS and itm is False:
        action = "CLOSE" if has_position else "WATCH"
        return _insight(
            action, "DTE_PRESSURE_OTM",
            ["out of the money", "under ~10 days to expiration"],
            "the underlying crosses the strike, or the position is closed",
            "mechanical",
        )

    # 5. Weakening / distributing campaign.
    if campaign == "warn" or exhaustion:
        action = "REDUCE" if has_position else "WATCH"
        return _insight(
            action, "CAMPAIGN_WEAKENING",
            ["PEAK/MANAGE/EXHAUSTION evidence on the campaign"],
            "the campaign repairs (RELOAD) or breaks (FAIL)",
            "structural",
        )

    # 6. Unchanged / illiquid print: no inference.
    if unchanged:
        return _insight(
            "WATCH", "UNCHANGED_ILLIQUID_PRINT",
            ["contract showed a zero-return / no-volume print"],
            "an active print appears and a direction is observable",
            "no-basis",
        )

    # 7. Conflicting evidence: constructive DNA but a declining premium.
    if campaign == "pos" and premium is not None and premium < -ACTIVE_PRINT_EPSILON:
        return _insight(
            "WATCH", "CONFLICTING_EVIDENCE",
            ["constructive campaign", "contract premium is not confirming"],
            "premium confirms (positive) or the campaign turns",
            "inferred",
        )

    # 8. Constructive campaign with a responsive contract.
    if campaign == "pos" and premium is not None and premium > ACTIVE_PRINT_EPSILON:
        return _insight(
            "MANAGE", "CONSTRUCTIVE_RESPONSIVE",
            ["constructive campaign", "contract premium is actively responding"],
            "a PEAK/FAIL event fires on a deciding tier",
            "structural",
        )

    # 9. Fallback.
    return _insight(
        "WATCH", "NO_CLEAR_SIGNAL",
        [],
        "any classified event fires or an active print appears",
        "no-basis",
    )
