"""Reference implementation of the DNA position insight library.

Research-only: pure functions over the documented API fields. Nothing here
reads a database, a network, or any field outside the documented contract
(see reports/DNA_POSITION_VOCABULARY_RESEARCH.md §2).

Used by test_dna_insight_library.py to prove that every rule selects only
from supplied facts and produces deterministic output.
"""

from __future__ import annotations

# --- vocabulary (mirrors ui/dna_dashboard.html) --------------------------
BROKEN = ["FAILED", "FAIL", "MODERATE FAIL", "STRONG FAIL", "CATASTROPHIC FAIL"]
STRESSED = ["FAIL TEST"]
STRETCH = ["PREMIUM", "PEAK", "MANAGE"]
BUILDING = ["EXPANSION", "IGNITION", "STRONG START", "CAMPAIGN START",
            "FIRE ADD", "ADD", "RELOAD", "ACCUMULATE", "ACCUMULATION"]
REPAIR = ["RELOAD", "RECOVERY", "RECOVERY WATCH"]

TIERS = [
    ("backbone", ["D", "W"]),
    ("owner", ["180", "240"]),
    ("confirm", ["60", "120"]),
    ("timing", ["15", "30"]),
    ("micro", ["3", "5"]),
]

CAMPAIGN_CONDITIONS = (
    "broken", "weakening", "expanding", "repairing", "constructive", "uncertain",
)
TF_RELATIONSHIPS = (
    "weakness propagating", "weakness contained", "multi-TF confirmation",
    "higher-TF intact", "conflicting evidence",
)
INTENTS = (
    "hold", "wait", "protect", "reduce", "close / stand aside",
    "add after confirmation", "consider roll", "monitor time decay",
)
INSTRUMENTS = (
    "shares", "long call", "long put",
    "short shares", "short call", "short put", "multi-leg option",
)

# Closed vocabulary from finra_short.short_activity. Elevated/high short-volume
# ratio marks a crowded short side — squeeze risk for an open short position.
SHORT_PRESSURE_RISK = {"ELEVATED", "HIGH"}


def tone(phase) -> str:
    p = (phase or "").upper()
    if p in BROKEN or p in STRESSED:
        return "neg"
    if p in STRETCH:
        return "warn"
    if p in BUILDING:
        return "pos"
    return "neu"


def _read_tier(states, tfs):
    rows = [s for s in states if s.get("timeframe") in tfs]
    if not rows:
        return None
    rank = {"neg": 3, "warn": 2, "pos": 1, "neu": 0}
    return max(rows, key=lambda s: rank[tone(s.get("phase"))])


def _tier_tones(states):
    out = {}
    for key, tfs in TIERS:
        lead = _read_tier(states, tfs)
        out[key] = tone(lead.get("phase")) if lead else "none"
    return out


def campaign_condition(states) -> str:
    """Deterministic precedence (research doc §3.3):
    broken > weakening > expanding > repairing > constructive > uncertain."""
    states = states or []
    t = _tier_tones(states)
    if "neg" in (t["backbone"], t["owner"], t["confirm"]):
        return "broken"
    if any(t[k] == "warn" for k in t) or any(s.get("exhaustion_warning") for s in states):
        return "weakening"
    if t["owner"] == "pos":
        return "expanding"
    if any((s.get("recent_event") or "").upper() in REPAIR for s in states):
        return "repairing"
    if (t["confirm"] == "pos" or t["timing"] == "pos") and t["owner"] != "neg":
        return "constructive"
    return "uncertain"


def tf_relationship(states):
    """Deterministic precedence (research doc §3.4). Returns None when no
    classified tone is present (the modifier is then simply not applied)."""
    states = states or []
    t = _tier_tones(states)
    upper = ("backbone", "owner", "confirm")
    lower = ("timing", "micro")
    classified = {k: v for k, v in t.items() if v in ("neg", "warn", "pos")}
    if not classified:
        return None
    upper_neg = any(t[k] == "neg" for k in upper)
    lower_weak = any(t[k] in ("neg", "warn") for k in lower)
    upper_pos = any(t[k] == "pos" for k in ("backbone", "owner"))
    has_pos = any(v == "pos" for v in classified.values())
    has_neg = any(v == "neg" for v in classified.values())
    n_pos = sum(1 for v in classified.values() if v == "pos")

    if has_pos and has_neg:
        return "conflicting evidence"
    if upper_neg:
        return "weakness propagating"
    if lower_weak:
        return "weakness contained"
    if n_pos >= 2:
        return "multi-TF confirmation"
    if upper_pos:
        return "higher-TF intact"
    return None  # a single isolated tone describes no cross-timeframe relationship


def _days_since(iso, now_ms=None):
    import datetime
    s = str(iso).replace(" ", "T")
    if not s.endswith("Z"):
        s += "Z"
    try:
        dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.datetime.now(datetime.timezone.utc)
    return (now - dt).days


def _dte(expiration):
    if not expiration:
        return None
    import datetime
    try:
        d = datetime.date.fromisoformat(str(expiration)[:10])
    except ValueError:
        return None
    today = datetime.date.today()
    return (d - today).days


def holding_state(holding, instrument):
    """Composite holding state from documented fields only.

    `total_return_pct` is long-convention (positive = price above entry), as
    produced by /positions/<id>/valuation. For short instruments the sign is
    inverted: a negative long-convention return means the short is winning.
    Moneyness (ITM/OTM) is a contract-level fact and is recorded unchanged;
    the short-side interpretation (ITM = assignment risk) lives in the §7
    modifiers.
    """
    holding = holding or {}
    is_short = instrument.startswith("short")
    hs = {"profitable": None, "moneyness": None, "dte_pressure": None, "age": None}
    pct = holding.get("total_return_pct")
    if pct is not None:
        hs["profitable"] = (pct <= 0) if is_short else (pct >= 0)
    if instrument in ("long call", "long put", "short call", "short put"):
        itm = holding.get("itm")
        if itm is True:
            hs["moneyness"] = "ITM"
        elif itm is False:
            hs["moneyness"] = "OTM"
        dte = _dte(holding.get("expiration"))
        if dte is not None:
            hs["dte_pressure"] = "high" if dte <= 10 else ("medium" if dte <= 21 else "low")
    days = _days_since(holding.get("first_entry")) if holding.get("first_entry") else None
    if days is not None:
        hs["age"] = "mature" if days >= 21 else "new"
    return hs


# campaign × instrument -> default intent (research doc §6)
_COMPOSITION = {
    "shares": {
        "broken": "protect", "weakening": "protect", "repairing": "hold",
        "expanding": "add after confirmation", "constructive": "hold", "uncertain": "wait",
    },
    "long call": {
        "broken": "close / stand aside", "weakening": "reduce", "repairing": "hold",
        "expanding": "consider roll", "constructive": "hold", "uncertain": "monitor time decay",
    },
    "long put": {
        "broken": "hold", "weakening": "hold", "repairing": "reduce",
        "expanding": "close / stand aside", "constructive": "reduce", "uncertain": "monitor time decay",
    },
    "short shares": {
        "broken": "hold", "weakening": "hold", "repairing": "reduce",
        "expanding": "protect", "constructive": "protect", "uncertain": "wait",
    },
    "short call": {
        "broken": "hold", "weakening": "hold", "repairing": "reduce",
        "expanding": "protect", "constructive": "protect", "uncertain": "monitor time decay",
    },
    "short put": {
        "broken": "protect", "weakening": "protect", "repairing": "hold",
        "expanding": "hold", "constructive": "hold", "uncertain": "monitor time decay",
    },
    "multi-leg option": {
        "broken": "wait", "weakening": "wait", "repairing": "wait",
        "expanding": "wait", "constructive": "wait", "uncertain": "wait",
    },
}


# --- copy (wording pass 2026-08: specific, not a fill-in-the-blank) ---------
# Each structural clause names the instrument + condition so swapping two rows
# stops making sense. Grounded only in §2 fields; no Greeks, no confidence.

_ACTION_PHRASE = {
    "hold": "hold",
    "wait": "wait for the next classified event",
    "protect": "protect the position",
    "reduce": "scale down",
    "close / stand aside": "exit the position",
    "add after confirmation": "add only after the next event confirms",
    "consider roll": "consider rolling",
    "monitor time decay": "monitor time decay",
}

_STRUCTURE_WHY = {
    "shares": {
        "broken": "a broken campaign puts open shares at downside risk, not at an entry",
        "weakening": "momentum is rolling over under open shares, so tightening the stop matters more than chasing",
        "repairing": "a recovery is rebuilding the structure, so an early add is premature",
        "expanding": "a building campaign supports shares",
        "constructive": "lower tiers are supportive but the campaign tier is still unconfirmed",
        "uncertain": "there is no dominant reading to act on",
    },
    "long call": {
        "broken": "a broken campaign works against a long call — decay now compounds the loss",
        "weakening": "a weakening structure and time decay both work against a long call",
        "repairing": "a repair is underway, but decay still sets the clock on a long call",
        "expanding": "an expanding campaign supports a long call",
        "constructive": "the setup is constructive but unproven, leaving decay as the only pressure",
        "uncertain": "with no structural edge, time decay is the only live factor on a long call",
    },
    "long put": {
        "broken": "a broken campaign is doing its job as downside protection for a long put",
        "weakening": "a weakening structure supports a long put",
        "repairing": "a repair is underway against a long put, so the downside thesis is fading",
        "expanding": "an expanding campaign invalidates the downside thesis behind a long put",
        "constructive": "a constructive setup argues against a long put",
        "uncertain": "with no structural edge, decay is the only live factor on a long put",
    },
    "short shares": {
        "broken": "a broken campaign is working for the short",
        "weakening": "a weakening structure is working for the short",
        "repairing": "a recovery is moving against the short",
        "expanding": "an expanding campaign is moving against the short",
        "constructive": "a constructive setup is building against the short",
        "uncertain": "there is no dominant reading on the short",
    },
    "short call": {
        "broken": "decay and falling price both work for a short call",
        "weakening": "decay and a rolling-over structure both work for a short call",
        "repairing": "a recovery raises assignment risk on a short call",
        "expanding": "rising price brings assignment risk on a short call",
        "constructive": "a constructive setup raises assignment risk on a short call",
        "uncertain": "with no structural edge, decay is the only live factor on a short call",
    },
    "short put": {
        "broken": "falling price brings assignment risk on a short put",
        "weakening": "a weakening structure raises assignment risk on a short put",
        "repairing": "a recovery is working for a short put",
        "expanding": "an expanding campaign is working for a short put",
        "constructive": "a constructive setup supports a short put",
        "uncertain": "with no structural edge, decay is the only live factor on a short put",
    },
    "multi-leg option": {
        "broken": "multi-leg net exposure is not computable from the manual model",
        "weakening": "multi-leg net exposure is not computable from the manual model",
        "repairing": "multi-leg net exposure is not computable from the manual model",
        "expanding": "multi-leg net exposure is not computable from the manual model",
        "constructive": "multi-leg net exposure is not computable from the manual model",
        "uncertain": "multi-leg net exposure is not computable from the manual model",
    },
}


def _conclusion(instrument, condition, intent):
    why = _STRUCTURE_WHY.get(instrument, _STRUCTURE_WHY["multi-leg option"])[condition]
    action = _ACTION_PHRASE[intent]
    return f"{why.capitalize()}; {action}."


def _evidence_phrases(hs, instrument):
    """Human phrases for the holding facts, no raw field names."""
    is_short = instrument.startswith("short")
    phrases = []
    if hs.get("profitable") is True:
        phrases.append("the short is winning" if is_short else "up on the position")
    elif hs.get("profitable") is False:
        phrases.append("the short is losing" if is_short else "down on the position")
    moneyness = hs.get("moneyness")
    if moneyness == "ITM":
        phrases.append("in the money")
    elif moneyness == "OTM":
        phrases.append("out of the money")
    dte = hs.get("dte_pressure")
    if dte == "high":
        phrases.append("near expiry")
    elif dte == "medium":
        phrases.append("moderate time left")
    elif dte == "low":
        phrases.append("comfortable time left")
    age = hs.get("age")
    if age == "mature":
        phrases.append("held a while")
    elif age == "new":
        phrases.append("recently opened")
    return phrases


def _apply_modifiers(intent, instrument, condition, hs, relationship, short_activity=None):
    """§7: holding-state and tf-relationship modifiers refine the default intent.

    Short instruments mirror the long-side modifiers a second time: the risk
    conditions are expanding/constructive (price moving against the short), the
    favorable conditions are broken/weakening, and "profitable" already means
    the short is winning (see holding_state). An optional ``short_activity``
    (FINRA short-volume ratio verdict) adds squeeze-risk de-risking for shorts.
    """
    is_short = instrument.startswith("short")
    is_option = instrument in ("long call", "long put", "short call", "short put")
    risk_conditions = ("expanding", "constructive") if is_short else ("broken",)

    # Option DTE pressure dominates unless the structure already demands a
    # protective action. Near expiry a long option loses time value fastest,
    # while a short option is near max profit and is monitored to decide when
    # to cover.
    if is_option and hs["dte_pressure"] == "high" and condition not in risk_conditions:
        return "monitor time decay"

    if is_short:
        # A winning short meeting a risk condition -> lock gains by covering part.
        if hs["profitable"] is True and condition in ("expanding", "constructive") \
                and intent == "protect":
            return "reduce"
        # A losing short meeting a risk condition on shares -> cap downside.
        if hs["profitable"] is False and condition == "expanding" \
                and instrument == "short shares":
            return "protect"
        # Bullish confirmation threatens shorts -> escalate hold to protect/reduce.
        if relationship in ("higher-TF intact", "multi-TF confirmation") \
                and intent == "hold" and instrument in ("short shares", "short call"):
            return "protect" if instrument == "short shares" else "reduce"
        # Bearish confirmation supports the short -> promote wait to hold.
        if relationship == "weakness propagating" and intent == "wait" \
                and instrument == "short shares":
            return "hold"
        # Crowded short activity (FINRA short-volume ratio) is squeeze risk for
        # any open short: the short side is getting crowded, so de-risk one step
        # regardless of the campaign read. Never overrides an existing reduce/
        # close/monitor intent.
        if (short_activity or "").upper() in SHORT_PRESSURE_RISK:
            if intent in ("hold", "wait"):
                return "protect" if instrument == "short shares" else "reduce"
            if intent == "protect":
                return "reduce"
        return intent

    # profitable + broken/weakening -> lock gains (reduce) instead of protect.
    if hs["profitable"] is True and condition in ("broken", "weakening") \
            and instrument in ("shares", "long call") and intent == "protect":
        return "reduce"
    # at a loss + broken -> cap downside (protect).
    if hs["profitable"] is False and condition == "broken" and instrument == "shares":
        return "protect"
    # weakness propagating escalates hold -> protect/reduce (longs only; a
    # long put benefits from weakness and must not be de-risked on it).
    if relationship == "weakness propagating" and intent == "hold" \
            and instrument in ("shares", "long call"):
        return "protect" if instrument == "shares" else "reduce"
    # higher-TF intact / multi-TF confirmation supports holding longs.
    if relationship in ("higher-TF intact", "multi-TF confirmation") \
            and intent == "wait" and instrument == "shares":
        return "hold"
    return intent


def compose(states, holding, instrument, required_fields=None, short_activity=None):
    """Full deterministic pipeline -> output record (research doc §9).

    `required_fields` (optional) declares the exact field names the caller
    supplied; used by tests to prove fact-only selection. The function itself
    reads only the documented keys.

    `short_activity` (optional) is the FINRA short-volume-ratio verdict
    (LOW/NORMAL/ELEVATED/HIGH/NO_DATA); for short instruments an ELEVATED/HIGH
    read de-risks the position (squeeze risk). Absent, the modifier is skipped.
    """
    states = states or []
    condition = campaign_condition(states)
    relationship = tf_relationship(states)
    hs = holding_state(holding, instrument)
    if instrument not in _COMPOSITION:
        instrument = "multi-leg option"

    # no-basis guard: an intent requires a readable campaign condition or a
    # holding fact; with neither, emit no-basis instead of fabricating.
    has_structure = bool(states)
    has_holding = any(v is not None for v in hs.values())
    if not has_structure and not has_holding:
        return {
            "status_label": "No basis",
            "conclusion": "Not enough recorded facts to produce position guidance.",
            "evidence": [],
            "decision_change": "a DNA reading or a position fact is recorded",
            "prohibited": [],
            "confidence": "no-basis",
            "navigation_intent": "wait",
        }

    base = _COMPOSITION[instrument][condition]
    intent = _apply_modifiers(base, instrument, condition, hs, relationship,
                              short_activity=short_activity)
    evidence = _evidence_phrases(hs, instrument) or ["no holding facts recorded"]
    squeeze = (short_activity or "").upper() in SHORT_PRESSURE_RISK
    if squeeze and instrument.startswith("short"):
        evidence.append("crowded short activity (FINRA short-volume ratio) adds squeeze risk")
    return {
        "navigation_intent": intent,
        "campaign_condition": condition,
        "tf_relationship": relationship,
        "holding_state": hs,
        "status_label": intent,
        "conclusion": _conclusion(instrument, condition, intent),
        "evidence": evidence,
        "decision_change": "documented per rule row",
        "prohibited": [],
        "confidence": "structural" if has_structure else "mechanical",
    }
