"""
Connects the webhook receiver's live state to decision_engine.py -- now with
TWO modes, closing the full loop for both single-timeframe checks and the
real multi-timeframe synthesis:

    Pine alert() -> webhook_receiver.py -> /state_all/<symbol> ->
    THIS SCRIPT -> list[CampaignState] -> synthesize_multi_timeframe_decision()
    -> ONE real recommendation, not per-timeframe boxes

Position data (including current_stop, needed for trailing-stop suggestions)
is NOT tracked by the receiver -- that stays here, in a small local config,
same principle as always: only the person knows what they actually hold.

Usage:
    python3 poll_and_recommend.py AMC                        # multi-TF synthesis (recommended)
    python3 poll_and_recommend.py AMC --timeframe 240         # single-timeframe only
    python3 poll_and_recommend.py AMC --receiver https://railway.app --token $STATE_API_TOKEN
"""
from __future__ import annotations
import sys
import os
import argparse
import requests
from datetime import date

from decision_engine import (
    CampaignState, Phase, Momentum, Position, SharePosition, OptionLeg,
    build_recommendations, print_recs, synthesize_multi_timeframe_decision,
    suggest_trailing_stop,
)

PHASE_MAP = {
    "WAIT": Phase.WAIT,
    "START TEST": Phase.WAIT,
    "IGNITION TEST": Phase.WAIT,
    "FAIL TEST": Phase.WAIT,
    "RESOLVING": Phase.WAIT,
    "RESET": Phase.WAIT,
    "RELOAD": Phase.RECOVERY,
    "RECOVERY WATCH": Phase.RECOVERY,
    "FAILED": Phase.FAILURE,
    "PEAK": Phase.DISTRIBUTION,
    "PREMIUM": Phase.DISTRIBUTION,
    "FIRE ADD": Phase.EXPANSION,
    "MANAGE": Phase.EXPANSION,
    "EXPANSION": Phase.EXPANSION,
    "IGNITION": Phase.IGNITION,
    "ACCUMULATION": Phase.ACCUMULATE,
    "STRONG START": Phase.ACCUMULATE,
    "CAMPAIGN START": Phase.ACCUMULATE,
}

MOMENTUM_MAP = {
    "STRONG": Momentum.STRONG,
    "BUILDING": Momentum.BUILDING,
    "WEAK": Momentum.WEAK,
    "OFF": Momentum.FADING,
}

BULLISH_SUPPORT_EVENTS = ("STRONG START", "RELOAD", "ADD", "FIRE ADD", "MANAGE", "CAMPAIGN START")


def _headers(token: str | None) -> dict:
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def fetch_state(receiver_url: str, symbol: str, timeframe: str, token: str | None = None) -> dict | None:
    resp = requests.get(f"{receiver_url}/state/{symbol}/{timeframe}", timeout=5, headers=_headers(token))
    if resp.status_code == 404:
        print(f"No alerts recorded yet for {symbol}/{timeframe}. "
              f"Make sure the Pine script's webhook is pointed at this receiver and has fired at least once.")
        return None
    resp.raise_for_status()
    return resp.json()


def fetch_all_states(receiver_url: str, symbol: str, token: str | None = None) -> list[dict]:
    resp = requests.get(f"{receiver_url}/state_all/{symbol}", timeout=5, headers=_headers(token))
    if resp.status_code == 404:
        print(f"No alerts recorded yet for {symbol} on any timeframe. "
              f"Make sure the Pine script's webhook is pointed at this receiver and has fired at least once.")
        return []
    resp.raise_for_status()
    return resp.json()["states"]


def build_campaign_state(data: dict) -> CampaignState:
    raw_phase = data.get("phase", "WAIT")
    raw_momentum = data.get("momentum", "OFF")
    phase = PHASE_MAP.get(raw_phase)
    momentum = MOMENTUM_MAP.get(raw_momentum)
    if phase is None:
        print(f"WARNING: unmapped phase '{raw_phase}' from receiver ({data.get('timeframe')}) -- defaulting to WAIT.")
        phase = Phase.WAIT
    if momentum is None:
        print(f"WARNING: unmapped momentum '{raw_momentum}' from receiver ({data.get('timeframe')}) -- defaulting to FADING.")
        momentum = Momentum.FADING

    recent_event = data.get("recent_event") or ""
    support_price = data.get("close") if recent_event in BULLISH_SUPPORT_EVENTS else None

    return CampaignState(
        symbol=data["symbol"],
        timeframe=data["timeframe"],
        phase=phase,
        health=data.get("health") or 0,
        confidence=data.get("confidence") or 0,
        momentum=momentum,
        recent_event=recent_event,
        exhaustion_warning=bool(data.get("exhaustion_warning")),
        rsi=data.get("rsi"),
        ema21_distance_atr=data.get("ema21_distance_atr"),
        signal_bar_extension_label=data.get("signal_bar_extension_label"),
        next_event_after_signal=data.get("next_event_after_signal"),
        recent_support_price=support_price,
    )


def load_position() -> Position:
    return Position(
        shares=None,
        options=[],
        current_stop=None,
    )


def main():
    parser = argparse.ArgumentParser(description="Poll the DNA webhook receiver and get real recommendations.")
    parser.add_argument("symbol")
    parser.add_argument("--timeframe", default=None, help="Single-timeframe mode. Omit for multi-TF synthesis.")
    parser.add_argument("--receiver", default="http://localhost:5000")
    parser.add_argument("--price", type=float, default=None, help="Current price for strike selection")
    parser.add_argument("--token", default=os.environ.get("STATE_API_TOKEN"), help="STATE_API_TOKEN for authenticated reads (falls back to STATE_API_TOKEN env)")
    args = parser.parse_args()

    position = load_position()
    token = args.token or None

    if args.timeframe:
        data = fetch_state(args.receiver, args.symbol, args.timeframe, token=token)
        if data is None:
            sys.exit(1)
        print(f"=== Live state for {args.symbol}/{args.timeframe} (single-timeframe mode) ===")
        print(f"Phase: {data.get('phase')} | Health: {data.get('health')}% | Confidence: {data.get('confidence')}%")
        print(f"Recent event: {data.get('recent_event')} | Momentum: {data.get('momentum')}")
        print()
        state = build_campaign_state(data)
        current_price = args.price or data.get("close")
        recs = build_recommendations(state, position, current_price=current_price)
        print_recs(f"Recommendations for {args.symbol}/{args.timeframe}", recs)
        return

    raw_states = fetch_all_states(args.receiver, args.symbol, token=token)
    if not raw_states:
        sys.exit(1)

    print(f"=== Live multi-timeframe state for {args.symbol} ({len(raw_states)} timeframes reporting) ===")
    states = []
    for d in raw_states:
        print(f"  {d['timeframe']:>5}: phase={d.get('phase')}, recent_event={d.get('recent_event')}, close={d.get('close')}")
        states.append(build_campaign_state(d))
    print()

    current_price = args.price or (raw_states[0].get("close") if raw_states else None)

    synthesis = synthesize_multi_timeframe_decision(states, position, current_price=current_price)
    print(f"=== SYNTHESIZED DECISION ===")
    print(f"{synthesis.action}")
    print(f"{synthesis.reason}")
    print()

    if position.current_stop is not None and current_price is not None:
        trail_rec = suggest_trailing_stop(states, position, current_price)
        if trail_rec:
            print(f"=== TRAILING STOP SUGGESTION ===")
            print(f"{trail_rec.action}")
            print(f"{trail_rec.reason}")
        else:
            print("(No trailing-stop suggestion right now.)")


if __name__ == "__main__":
    main()
