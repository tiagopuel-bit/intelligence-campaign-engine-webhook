"""DNA-suggested protective brackets (stop/target) — advisory producer.

Turns the DNA state read (``recent_support_price`` / ``recent_resistance_price``
per timeframe, plus an option's own series) into ordinary ``set_bracket``
proposals. A suggestion is created through the same ``create_proposal`` path as
a manually-specified bracket: ``set_bracket``, ``mode=APPROVAL_REQUIRED``,
`PENDING_APPROVAL` → human approval → ``upsert_bracket``. **Nothing here ever
auto-sets or auto-raises a bracket** and ``set_bracket`` is not in
``VERY_HIGH_AUTO_ACTIONS``. The trigger/fill path (``bracket_decision`` /
``apply_bracket_trigger``) is untouched and stays LIVE-only / fail-closed —
this module only decides whether a *suggestion* is generated.

Discipline (per reports/TP_SL_RECOMMENDATION_SPEC.md and
reports/OPTION_NATIVE_TPSL_SPEC.md, build authorized 2026-08-17/18):

- Stop = tightest ``recent_support_price`` below current price (raise-only for
  trailing); refused while a cross-TF ``EXIT SIGNAL`` is active.
- Target = nearest stretch-event close above current price
  (``recent_resistance_price``), else position breakeven, else an R:R fallback
  at the validated Trade Box multiple ``k=2.2``.
- Option-native levels come from the option's own close series (≥ 30-bar floor,
  20-bar lookback); DELAYED Massive data is allowed as a fallback and labeled
  ``DELAYED``, never silently presented as live.
- A suggested stop is clamped so a single stop-out loss never exceeds
  ``single_contract_max_pct`` (15%) of total portfolio value, in the position's
  own notional terms.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from decision_engine import (
    CampaignState,
    Phase,
    Momentum,
    Position,
    synthesize_multi_timeframe_decision,
)
from paper_execution.db import connect
from paper_execution.portfolio import paper_portfolio_value
from paper_execution.store import create_proposal, frozen_policy_hash

# --- declared constants (reviewed in the TP/SL specs) ----------------------
TARGET_RR = 2.2                 # validated Trade Box 2.2:1 constant (Bible Vol VI §3)
MIN_HISTORY_OPTION = 30         # option-native floor: fewer bars -> no suggestion
OPTION_LOOKBACK = 20            # option-native window (matches component_ledger)
SINGLE_CONTRACT_MAX_PCT = 0.15  # 15% of TPV = max single stop-out loss
MATERIAL_CHANGE_PCT = 0.005     # ≥0.5% move required to re-propose a trailing level
MAX_OUTSTANDING_PER_EXPERIMENT = 3
APPROVAL_WINDOW_SECONDS = 600

SUPPORT_EVENTS = ("STRONG START", "RELOAD", "ADD", "FIRE ADD", "MANAGE", "CAMPAIGN START")
STRETCH_EVENTS = ("PEAK", "MANAGE", "PREMIUM")
FAIL_EVENTS = ("FAIL", "FAIL TEST", "CATASTROPHIC FAIL", "MODERATE FAIL", "STRONG FAIL")

# Mirrors poll_and_recommend.build_campaign_state (kept in sync).
_PHASE_MAP = {
    "WAIT": Phase.WAIT, "START TEST": Phase.WAIT, "IGNITION TEST": Phase.WAIT,
    "FAIL TEST": Phase.WAIT, "RESOLVING": Phase.WAIT, "RESET": Phase.WAIT,
    "RELOAD": Phase.RECOVERY, "RECOVERY WATCH": Phase.RECOVERY,
    "FAILED": Phase.FAILURE, "PEAK": Phase.DISTRIBUTION, "PREMIUM": Phase.DISTRIBUTION,
    "FIRE ADD": Phase.EXPANSION, "MANAGE": Phase.EXPANSION, "EXPANSION": Phase.EXPANSION,
    "IGNITION": Phase.IGNITION, "ACCUMULATION": Phase.ACCUMULATE,
    "STRONG START": Phase.ACCUMULATE, "CAMPAIGN START": Phase.ACCUMULATE,
}
_MOMENTUM_MAP = {"STRONG": Momentum.STRONG, "BUILDING": Momentum.BUILDING,
                 "WEAK": Momentum.WEAK, "OFF": Momentum.FADING}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- state loading (webhook DB -> CampaignState list) ----------------------

def load_campaign_states(webhook_db_path: str | Path, symbol: str,
                         hidden_timeframes=("1", "3")) -> list[CampaignState]:
    """Latest alert per timeframe -> CampaignState, mirroring /state_all.

    ``recent_event`` / support / resistance use the **true last real event**
    (most recent non-empty ``bar_event`` and the close at that bar) among
    ``source='live_webhook'`` rows only -- ``backfill_replay`` reconstructions
    never fired a real TradingView alert and must never be presented as a
    confirmed event (mirrors ``webhook_receiver._last_real_event``).
    ``hidden_timeframes`` drops the live-only micro rungs (1m heartbeat
    relay and 3m), same as the dashboard.
    """
    conn = sqlite3.connect(str(webhook_db_path))
    conn.row_factory = sqlite3.Row
    try:
        tfs = [r["timeframe"] for r in conn.execute(
            "SELECT DISTINCT timeframe FROM alerts WHERE symbol=?", (symbol,)
        ).fetchall() if r["timeframe"] not in hidden_timeframes]
        states = []
        for tf in tfs:
            latest = conn.execute(
                "SELECT * FROM alerts WHERE symbol=? AND timeframe=? "
                "ORDER BY CAST(bar_time AS INTEGER) DESC, id DESC LIMIT 1",
                (symbol, tf),
            ).fetchone()
            if latest is None:
                continue
            watch = conn.execute(
                "SELECT * FROM watch_state WHERE symbol=? AND timeframe=?",
                (symbol, tf),
            ).fetchone()
            last_event = conn.execute(
                "SELECT bar_event, bar_time, close FROM alerts WHERE symbol=? AND timeframe=? "
                "AND bar_event IS NOT NULL AND bar_event != '' AND source IN ('live_webhook','live_relay') "
                "ORDER BY CAST(bar_time AS INTEGER) DESC, id DESC LIMIT 1",
                (symbol, tf),
            ).fetchone()
            states.append(_to_campaign_state(symbol, tf, latest, watch, last_event))
        return states
    finally:
        conn.close()


def _to_campaign_state(symbol: str, tf: str, latest, watch, last_event=None) -> CampaignState:
    raw_phase = latest["phase"] or "WAIT"
    raw_momentum = latest["momentum"] or "OFF"
    phase = _PHASE_MAP.get(raw_phase.upper(), Phase.WAIT)
    momentum = _MOMENTUM_MAP.get((raw_momentum or "").upper(), Momentum.FADING)
    # No fallback to latest["bar_event"] here: latest is fetched without a
    # source filter, so falling back to it would leak a backfill_replay
    # event right back in whenever it happens to be the most recent row --
    # exactly the fabrication load_campaign_states's source filter exists
    # to prevent. last_event is None means no live-confirmed event, full stop.
    recent_event = (last_event["bar_event"] if last_event is not None else "").upper()
    event_close = last_event["close"] if last_event is not None else None
    if event_close is None:
        event_close = latest["close"]
    return CampaignState(
        symbol=symbol, timeframe=tf, phase=phase, momentum=momentum,
        health=latest["health"] or 0, confidence=latest["confidence"] or 0,
        recent_event=recent_event,
        exhaustion_warning=bool(latest["exhaustion_warning"]),
        rsi=latest["rsi"], ema21_distance_atr=latest["ema21_distance_atr"],
        signal_bar_extension_label=(watch["signal_extension_label"] if watch else None),
        next_event_after_signal=(watch["next_event_after_signal"] if watch else None),
        recent_support_price=event_close if recent_event in SUPPORT_EVENTS else None,
        recent_resistance_price=event_close if recent_event in STRETCH_EVENTS else None,
    )


def exit_signal_active(states: list[CampaignState]) -> bool:
    """Cross-TF exit-signal gate (decision_engine synthesis, same priority rule
    as suggest_trailing_stop)."""
    if not states:
        return False
    synthesis = synthesize_multi_timeframe_decision(states, Position(shares=None, options=[], current_stop=None))
    return synthesis.action.startswith("EXIT SIGNAL")


# --- pure level computation ------------------------------------------------

def support_levels(states, current_price):
    return [(s.timeframe, s.recent_support_price) for s in states
            if s.recent_support_price is not None and s.recent_support_price < current_price]


def resistance_levels(states, current_price):
    return [(s.timeframe, s.recent_resistance_price) for s in states
            if s.recent_resistance_price is not None and s.recent_resistance_price > current_price]


def tightest_support(states, current_price):
    """Highest valid support below price (tightest defensible) + its timeframes."""
    levels = support_levels(states, current_price)
    if not levels:
        return None, []
    best = max(level for _, level in levels)
    return best, [tf for tf, level in levels if level == best]


def nearest_resistance(states, current_price):
    """Lowest valid resistance above price (nearest stretch level) + its timeframes."""
    levels = resistance_levels(states, current_price)
    if not levels:
        return None, []
    best = min(level for _, level in levels)
    return best, [tf for tf, level in levels if level == best]


def cap_clamp_stop(stop: float, current_price: float, qty: float, tpv: float,
                   contracts_mult: float = 1.0) -> float:
    """Clamp a stop so a single stop-out loss <= 15% x TPV (own notional)."""
    notional = qty * current_price * contracts_mult
    if notional <= 0 or tpv <= 0:
        return stop
    max_distance = (SINGLE_CONTRACT_MAX_PCT * tpv) / notional
    floor = current_price - max_distance
    return max(stop, floor)


def option_native_levels(closes, current_price, *, min_history=MIN_HISTORY_OPTION,
                         lookback=OPTION_LOOKBACK):
    """Option support/resistance from the option's own close series.

    Returns (support, resistance, sufficient, reason). ``sufficient=False``
    below the 30-bar floor → callers fail closed with
    ``NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY``.
    """
    clean = [float(c) for c in closes if c is not None]
    if len(clean) < min_history:
        return None, None, False, "insufficient option history"
    window = clean[-lookback:]
    support = min(window) if min(window) < current_price else None
    resistance = max(window) if max(window) > current_price else None
    return support, resistance, True, "ok"


def target_price(states, current_price, breakeven=None, stop=None):
    """Target: nearest resistance -> breakeven -> R:R (k=2.2). Returns
    (target, source) or (None, None) when nothing computable."""
    res, _ = nearest_resistance(states, current_price)
    if res is not None:
        return res, "resistance"
    if breakeven is not None and breakeven > current_price:
        return breakeven, "breakeven"
    if stop is not None and stop < current_price:
        return current_price + TARGET_RR * (current_price - stop), "rr_2.2"
    return None, None


# --- suggestion builders ---------------------------------------------------

def suggest_initial_share(states, current_price, *, qty, tpv, breakeven=None,
                          exit_signal=False):
    """Initial stop + target from underlying structural levels."""
    if exit_signal:
        return None
    stop, stop_tfs = tightest_support(states, current_price)
    if stop is None:
        return None  # no fresh support anywhere -> no bracket (fail-closed)
    if qty and tpv:
        stop = cap_clamp_stop(stop, current_price, qty, tpv, contracts_mult=1.0)
    target, target_src = target_price(states, current_price, breakeven, stop)
    if target is None:
        return None
    tf_note = ", ".join(stop_tfs) if stop_tfs else "?"
    return {
        "kind": "INITIAL", "stop_price": stop, "target_price": target,
        "stop_tfs": stop_tfs, "target_src": target_src,
        "reason": (f"Initial bracket: stop ${stop:.4f} is the tightest recent "
                   f"support below ${current_price:.4f} ({tf_note}'s most recent "
                   f"bullish signal); target ${target:.4f} from {target_src}. "
                   f"Approve to protect the position."),
    }


def suggest_initial_option(closes, current_price, *, qty, tpv, breakeven=None,
                           freshness="DELAYED"):
    """Initial stop + target from the option's own series (option-native)."""
    support, resistance, sufficient, reason = option_native_levels(closes, current_price)
    if not sufficient:
        return {"kind": "INITIAL_OPTION", "outcome": "NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY",
                "reason": f"No suggestion: {reason} ({len([c for c in closes if c is not None])} bars < {MIN_HISTORY_OPTION})."}
    if support is None:
        return None
    stop = support
    if qty and tpv:
        stop = cap_clamp_stop(stop, current_price, qty, tpv, contracts_mult=100.0)
    target, target_src = target_price([], current_price, breakeven, stop)
    if resistance is not None:
        target, target_src = resistance, "option_resistance"
    return {
        "kind": "INITIAL_OPTION", "stop_price": stop, "target_price": target,
        "stop_tfs": [], "target_src": target_src,
        "freshness": freshness,
        "reason": (f"Option-native bracket ({freshness}): stop ${stop:.4f} from the "
                   f"option's own recent low; target ${target:.4f} from "
                   f"{target_src}. Approve to protect the position."),
    }


def suggest_trailing_stop_update(states, current_price, current_stop, *,
                                 exit_signal=False):
    """Raise-only stop update; None when no higher support or an exit signal."""
    if exit_signal or current_stop is None:
        return None
    stop, stop_tfs = tightest_support(states, current_price)
    if stop is None or stop <= current_stop:
        return None
    return {"kind": "TRAILING_STOP", "stop_price": stop, "target_price": None,
            "stop_tfs": stop_tfs,
            "reason": (f"Trailing stop: raise to ${stop:.4f} (recent support on "
                       f"{', '.join(stop_tfs) or '?'}) while trend stays healthy.")}


def suggest_trailing_target_update(states, current_price, current_target, *,
                                   breakeven=None):
    """Raise-only target update; None when no higher resistance level."""
    if current_target is None:
        return None
    res, res_tfs = nearest_resistance(states, current_price)
    if res is None or res <= current_target:
        return None
    return {"kind": "TRAILING_TARGET", "target_price": res, "stop_price": None,
            "target_src": "resistance", "stop_tfs": res_tfs,
            "reason": (f"Trailing target: raise to ${res:.4f} (stretch level on "
                       f"{', '.join(res_tfs) or '?'}) as the campaign develops.")}


# --- on-tick trigger + proposal creation -----------------------------------

def _material_change(active, suggested_stop, suggested_target):
    if active is None:
        return True
    old_stop = active.get("stop_price")
    old_target = active.get("target_price")
    if suggested_stop is not None and old_stop is not None:
        if abs(suggested_stop - old_stop) / old_stop >= MATERIAL_CHANGE_PCT:
            return True
    if suggested_target is not None and old_target is not None:
        if abs(suggested_target - old_target) / old_target >= MATERIAL_CHANGE_PCT:
            return True
    return False


def _outstanding_brackets(conn, experiment_id, ticker):
    rows = conn.execute(
        "SELECT 1 FROM pe_order_proposals WHERE experiment_id=? AND symbol=? AND action='set_bracket' "
        "AND current_status IN ('PENDING_APPROVAL','APPROVED') AND position_ref=? LIMIT 1",
        (experiment_id, ticker, ticker),
    ).fetchone()
    return rows is not None


def _outstanding_count(conn, experiment_id):
    return conn.execute(
        "SELECT COUNT(*) n FROM pe_order_proposals WHERE experiment_id=? AND action='set_bracket' "
        "AND current_status IN ('PENDING_APPROVAL','APPROVED')",
        (experiment_id,),
    ).fetchone()["n"]


def _suggest_for_position(conn, experiment_id, ticker, instrument_type, qty,
                          tpv, states, current_price, active_bracket, breakeven,
                          option_closes, option_freshness):
    """One position -> one set_bracket proposal (or None)."""
    if active_bracket is None:
        # initial suggestion (share vs option path)
        if instrument_type in ("CALL", "PUT"):
            if option_closes is None:
                return None  # no option history source at all
            suggestion = suggest_initial_option(
                option_closes, current_price, qty=qty, tpv=tpv,
                breakeven=breakeven, freshness=option_freshness)
            if suggestion is None:
                return None
            if suggestion.get("outcome"):
                return suggestion  # fail-closed "insufficient history" note
        else:
            suggestion = suggest_initial_share(
                states, current_price, qty=qty, tpv=tpv, breakeven=breakeven,
                exit_signal=exit_signal_active(states))
            if suggestion is None:
                return None
    else:
        # trailing updates — raise-only, symmetric for stop and target.
        stop_upd = suggest_trailing_stop_update(
            states, current_price, active_bracket.get("stop_price"),
            exit_signal=exit_signal_active(states))
        target_upd = suggest_trailing_target_update(
            states, current_price, active_bracket.get("target_price"),
            breakeven=breakeven)
        if stop_upd is None and target_upd is None:
            return None
        stop = stop_upd["stop_price"] if stop_upd else active_bracket.get("stop_price")
        target = target_upd["target_price"] if target_upd else active_bracket.get("target_price")
        if not _material_change(active_bracket, stop, target):
            return None
        kind = "TRAILING_STOP" if stop_upd else "TRAILING_TARGET"
        suggestion = {
            "kind": kind, "stop_price": stop, "target_price": target,
            "stop_tfs": (stop_upd or target_upd).get("stop_tfs") or [],
            "target_src": (target_upd or {}).get("target_src") or "resistance",
            "reason": (stop_upd or target_upd)["reason"],
        }
    return suggestion


def maybe_suggest_brackets(paper_db_path, webhook_db_path, *,
                           price_provider=None, option_closes=None,
                           option_freshness="DELAYED", breakevens=None,
                           now_iso=None) -> list[dict]:
    """On-tick: create set_bracket proposals for open positions without
    protection or with a trailing opportunity. Fail-closed: no ACTIVE
    experiment, no suggestion. Proposal creation reuses create_proposal.

    ``price_provider(symbol, ticker)`` -> {close, ...} | None (the live
    heartbeat path, e.g. ``cloud_state_provider.latest_close``). Without it,
    share prices fall back to the most recent state close. Option positions
    without a live option price fail closed to no suggestion.
    """
    now_iso = now_iso or _now_iso()
    conn = connect(paper_db_path)
    try:
        active = conn.execute(
            "SELECT id FROM pe_experiments WHERE status='ACTIVE' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not active:
            return []
        experiment_id = active["id"]
        tpv = paper_portfolio_value(conn, experiment_id)["total_value"]
        if _outstanding_count(conn, experiment_id) >= MAX_OUTSTANDING_PER_EXPERIMENT:
            return []
        positions = conn.execute(
            "SELECT ticker, symbol, instrument_type, quantity FROM pe_paper_positions "
            "WHERE experiment_id=? AND quantity != 0 ORDER BY ticker",
            (experiment_id,),
        ).fetchall()

        states_by_symbol: dict[str, list[CampaignState]] = {}
        results = []
        day = now_iso[:10].replace("-", "")
        for pos in positions:
            ticker = str(pos["ticker"])
            symbol = str(pos["symbol"])
            instrument_type = str(pos["instrument_type"] or "SHARE").upper()
            qty = abs(float(pos["quantity"] or 0.0))
            if qty == 0:
                continue
            if _outstanding_brackets(conn, experiment_id, ticker):
                continue
            active_bracket = conn.execute(
                "SELECT stop_price, target_price FROM pe_position_brackets "
                "WHERE experiment_id=? AND ticker=? AND status='ACTIVE' LIMIT 1",
                (experiment_id, ticker),
            ).fetchone()
            if symbol not in states_by_symbol:
                states_by_symbol[symbol] = load_campaign_states(webhook_db_path, symbol)
            states = states_by_symbol[symbol]

            current_price = None
            if price_provider is not None:
                info = price_provider(symbol, ticker)
                current_price = (info or {}).get("close")
            if current_price is None:
                continue  # no live price -> fail closed (never invent a price)

            breakeven = (breakevens or {}).get(ticker)
            closes = (option_closes or {}).get(ticker)
            suggestion = _suggest_for_position(
                conn, experiment_id, ticker, instrument_type, qty, tpv, states,
                current_price, active_bracket, breakeven, closes, option_freshness)
            if suggestion is None:
                continue
            if suggestion.get("outcome"):
                results.append({"ticker": ticker, **suggestion})
                continue
            stop = suggestion.get("stop_price")
            target = suggestion.get("target_price")
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_WINDOW_SECONDS)).isoformat()
            proposal_id = create_proposal(
                conn, experiment_id=experiment_id,
                idempotency_key=f"dna_bracket_{ticker}_{suggestion['kind']}_{day}",
                action="set_bracket", mode="APPROVAL_REQUIRED", symbol=symbol,
                policy_sha256=frozen_policy_hash(),
                time_sensitive_reason=suggestion["reason"],
                very_high=False, very_high_missing_roots=[],
                expires_at=expires_at, cancel_condition="stale_underlying",
                evidence_roots=[], position_ref=ticker,
                stop_price=stop, target_price=target,
            )
            results.append({"ticker": ticker, "proposal_id": proposal_id,
                            "kind": suggestion["kind"], "stop_price": stop,
                            "target_price": target,
                            "reason": suggestion["reason"]})
        return results
    finally:
        conn.close()
