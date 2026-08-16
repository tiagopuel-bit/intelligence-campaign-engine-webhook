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
INSTRUMENTS = ("shares", "long call", "long put", "multi-leg option")


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
    """Composite holding state from documented fields only."""
    holding = holding or {}
    hs = {"profitable": None, "moneyness": None, "dte_pressure": None, "age": None}
    pct = holding.get("total_return_pct")
    if pct is not None:
        hs["profitable"] = pct >= 0
    if instrument in ("long call", "long put"):
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
    "multi-leg option": {
        "broken": "wait", "weakening": "wait", "repairing": "wait",
        "expanding": "wait", "constructive": "wait", "uncertain": "wait",
    },
}


def _apply_modifiers(intent, instrument, condition, hs, relationship):
    """§7: holding-state and tf-relationship modifiers refine the default intent."""
    # Option DTE pressure dominates unless the structure is broken.
    if instrument in ("long call", "long put") and hs["dte_pressure"] == "high" \
            and condition != "broken":
        return "monitor time decay"
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


def compose(states, holding, instrument, required_fields=None):
    """Full deterministic pipeline -> output record (research doc §9).

    `required_fields` (optional) declares the exact field names the caller
    supplied; used by tests to prove fact-only selection. The function itself
    reads only the documented keys.
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
    intent = _apply_modifiers(base, instrument, condition, hs, relationship)
    return {
        "navigation_intent": intent,
        "campaign_condition": condition,
        "tf_relationship": relationship,
        "holding_state": hs,
        "status_label": intent,
        "conclusion": f"{instrument} in a {condition} campaign -> {intent}",
        "evidence": [k for k, v in hs.items() if v is not None] or ["no holding facts"],
        "decision_change": "documented per rule row",
        "prohibited": [],
        "confidence": "structural" if has_structure else "mechanical",
    }
