"""
Position-Aware Recommendation Layer -- Prototype v0.1
=======================================================
Takes (a) campaign state from the CIF engine dashboard and (b) a position,
and produces a position-specific recommendation -- the "layer 2/3" gap
identified in the platform brainstorm: existing signals are position-blind,
everyone sees the same PEAK/FAIL/MANAGE label regardless of what they hold.

THIS IS RULE-BASED, TRANSPARENT, AND EXPLICITLY NOT INVESTMENT ADVICE.
Every rule is stated in plain text so it can be inspected, argued with, and
changed -- nothing here is a black box, and nothing here is a recommendation
to actually place a trade. It's a decision-logic prototype only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from datetime import date


class Phase(Enum):
    WAIT = "WAIT"
    ACCUMULATE = "ACCUMULATE"
    IGNITION = "IGNITION"
    EXPANSION = "EXPANSION"
    DISTRIBUTION = "DISTRIBUTION"  # peak/topping behavior
    FAILURE = "FAILURE"
    RECOVERY = "RECOVERY"


class Momentum(Enum):
    FADING = "FADING"
    WEAK = "WEAK"
    BUILDING = "BUILDING"
    STRONG = "STRONG"


@dataclass
class CampaignState:
    """Snapshot of the CIF engine dashboard for one symbol/timeframe."""
    symbol: str
    timeframe: str
    phase: Phase
    health: int          # 0-100
    confidence: int       # 0-100
    momentum: Momentum
    recent_event: str = ""   # e.g. "PEAK", "FAIL TEST", "MANAGE"
    trend: str = "up"        # "up" / "down" / "sideways" -- underlying price trend
    exhaustion_warning: bool = False  # leading bearish-divergence flag, independent of lagging phase/health
    bars_since_reload: int | None = None  # for the RELOAD clean/messy post-entry rule (Roadmap #21)
    # Validated entry-extension fields (Roadmap, Aug 6 2026 signal-strength study,
    # 591 real STRONG START/RELOAD events across AMC/GME/ARB). health/confidence
    # above were TESTED AND REJECTED as entry-quality discriminators -- flat,
    # non-monotonic, the "strong" combo (health>=60 & confidence>=60) actually
    # underperformed. These three fields ARE validated -- optional because not
    # every dashboard read will have them, but real logic below depends on them
    # being populated when available.
    rsi: float | None = None                 # RSI at the moment of the signal
    ema21_distance_atr: float | None = None   # (close - EMA21) / ATR at the signal
    ema21_slope: float | None = None          # raw EMA21 slope value at the signal
    # Path-clarity fields (Roadmap, Aug 6 2026 sequence-path study -- the
    # strongest signal found this session). signal_bar_extension_label is
    # FROZEN at the moment a STRONG START/RELOAD fires (from assess_entry_extension
    # at that bar) -- does not update as later bars change rsi/ema21_distance_atr
    # above, which describe whatever recent_event currently is. next_event_after_signal
    # is the next real event that fired after that signal, once known -- None
    # while still waiting.
    signal_bar_extension_label: str | None = None   # "FRESH" / "EXTENDED" / "UNKNOWN", frozen at signal time
    next_event_after_signal: str | None = None       # e.g. "ADD", "MANAGE", "FAIL TEST" -- None if not yet known
    recent_support_price: float | None = None        # close price at this timeframe's most recent bullish signal event (STRONG START/RELOAD/ADD/MANAGE) -- the real, structural basis for trailing-stop suggestions below, not a guess
    recent_resistance_price: float | None = None     # close price at this timeframe's most recent stretch-family event (PEAK/MANAGE/PREMIUM) -- the structural basis for target suggestions (TP/SL spec §2), mirror of recent_support_price


@dataclass
class SharePosition:
    shares: int
    cost_basis: float


@dataclass
class OptionLeg:
    kind: str          # "long_call" / "short_call" (covered call)
    strike: float
    expiry: date
    contracts: int
    entry_price: float = 0.0
    is_leaps: bool = False   # >365 DTE at entry, or explicitly tagged


@dataclass
class Position:
    shares: SharePosition | None = None
    options: list[OptionLeg] = field(default_factory=list)
    current_stop: float | None = None  # where the person's actual stop sits right now, same manual-entry principle as shares/cost_basis -- the receiver has no way to know this, only the person does


@dataclass
class Recommendation:
    holding: str
    action: str
    reason: str
    review_in: str
    confidence_in_call: str  # engine's own confidence in this specific piece of advice, not a promise
    order: "OrderProposal | None" = None


@dataclass
class OrderProposal:
    """A fully-specified, not-yet-submitted order. Nothing here is ever sent
    anywhere automatically -- this is what would be shown to the person for
    explicit per-order approval before anything touches a broker API."""
    side: str            # "sell_to_open" / "buy_to_close" / "sell" / "buy"
    instrument: str       # "covered_call" / "long_call" / "shares"
    symbol: str
    qty: int
    strike: float | None = None
    expiry: date | None = None
    order_type: str = "limit"
    limit_price: float | None = None
    est_premium_or_cost: float | None = None
    rationale: str = ""


def campaign_state_from_dashboard(symbol: str, timeframe: str, *, phase: str, confidence: int,
                                   health: int, momentum: str, status: str = "", action: str = "",
                                   recent_event: str = "", trend: str = "up",
                                   exhaustion_warning: bool = False,
                                   bars_since_reload: int | None = None) -> CampaignState:
    """Build a CampaignState directly from what's visible on the v12.6.5 TradingView
    dashboard panel (CAMPAIGN/PHASE/CONFIDENCE/HEALTH/MOMENTUM/STATUS/ACTION), so
    every run is grounded in an actual screen reading instead of a hand-picked example.

    Manual bridge, not a live feed -- you read the panel, type the fields in, this
    maps them consistently every time instead of ad hoc. v12.6.5's PHASE/MOMENTUM
    vocabulary isn't documented anywhere (the Bible covers v12.4's phase machine,
    not v12.6.5's dashboard labels), so this mapping is a best-effort guess at the
    correspondence -- flagged, not hidden.
    """
    phase_map = {
        "WAIT": Phase.WAIT, "ACCUMULATION": Phase.ACCUMULATE, "ACCUMULATE": Phase.ACCUMULATE,
        "IGNITION": Phase.IGNITION, "EXPANSION": Phase.EXPANSION,
        "DISTRIBUTION": Phase.DISTRIBUTION, "PEAK": Phase.DISTRIBUTION,
        "FAILED": Phase.FAILURE, "FAILURE": Phase.FAILURE, "FAIL TEST": Phase.FAILURE,
        "CATASTROPHIC FAIL": Phase.FAILURE,
        "RECOVERY": Phase.RECOVERY, "RECOVERY WATCH": Phase.RECOVERY,
        # These real v12.6.6 phase labels don't have a clean 1:1 in the simplified
        # Phase enum -- mapped to the closest behavioral equivalent rather than
        # silently defaulting to WAIT, which was actively misleading (a FAIL TEST
        # defaulting to WAIT looks like nothing's wrong when something clearly is).
        "START TEST": Phase.IGNITION, "IGNITION TEST": Phase.IGNITION,
        "RELOAD": Phase.EXPANSION, "RESOLVING": Phase.WAIT,
        "STRONG START": Phase.IGNITION, "CAMPAIGN START": Phase.IGNITION,
        "FIRE ADD": Phase.EXPANSION, "MANAGE": Phase.EXPANSION, "PREMIUM": Phase.EXPANSION,
        "RESET": Phase.FAILURE,
    }
    momentum_map = {
        "STRONG": Momentum.STRONG, "BUILDING": Momentum.BUILDING,
        "WEAK": Momentum.WEAK, "FADING": Momentum.FADING,
    }
    mapped_phase = phase_map.get(phase.upper().strip(), Phase.WAIT)
    mapped_momentum = momentum_map.get(momentum.upper().strip(), Momentum.WEAK)
    if phase.upper().strip() not in phase_map:
        print(f"  [bridge warning] unrecognized phase label '{phase}' -- defaulted to WAIT, check mapping")
    if momentum.upper().strip() not in momentum_map:
        print(f"  [bridge warning] unrecognized momentum label '{momentum}' -- defaulted to WEAK, check mapping")
    return CampaignState(symbol=symbol, timeframe=timeframe, phase=mapped_phase, health=health,
                          confidence=confidence, momentum=mapped_momentum, recent_event=recent_event,
                          trend=trend, exhaustion_warning=exhaustion_warning, bars_since_reload=bars_since_reload)


def choose_covered_call_strike(current_price: float, state: CampaignState) -> tuple[float, date, str]:
    """Very rough OTM-distance heuristic -- wider OTM buffer when campaign is
    still healthy (don't want to get called away during real strength),
    tighter/more aggressive premium harvest when campaign is weakening.
    Real version would use delta targets off the actual chain, not % offsets."""
    if state.phase in HEALTHY_PHASES and state.momentum in (Momentum.BUILDING, Momentum.STRONG):
        otm_pct, dte_target, note = 0.25, 45, "wide OTM buffer -- campaign still accelerating, avoid getting called away"
    elif state.phase in WEAK_PHASES:
        otm_pct, dte_target, note = 0.08, 21, "tighter strike, shorter duration -- harvesting premium while structure is weak"
    else:
        otm_pct, dte_target, note = 0.15, 30, "moderate OTM buffer -- neutral read"
    strike = round(current_price * (1 + otm_pct), 2)
    expiry = date.today().fromordinal(date.today().toordinal() + dte_target)
    return strike, expiry, note


HEALTHY_PHASES = {Phase.IGNITION, Phase.EXPANSION, Phase.ACCUMULATE}
WEAK_PHASES = {Phase.DISTRIBUTION, Phase.FAILURE}


def days_to_expiry(expiry: date, as_of: date) -> int:
    return (expiry - as_of).days


def assess_entry_extension(state: CampaignState) -> tuple[str, str]:
    """Real, validated entry-quality check (Roadmap, Aug 6 2026 -- 591 real
    STRONG START/RELOAD events across AMC/GME/ARB, 15-bar forward window).

    Tested and REJECTED as discriminators: health, confidence, campaignScore,
    volume ratio, Bollinger width, MACD histogram, distance from EMA50/EMA200,
    bbExpanding, and sequence-context (recent fail nearby, ATR settling
    beforehand) -- all flat or non-monotonic.

    Tested and VALIDATED: RSI, EMA21 slope, and distance from EMA21 all
    measure the same underlying thing -- is this signal chasing an already-
    extended move -- and all three agree in the same direction. Combined
    filter (RSI<65 AND distance-from-EMA21<1.0 ATR): kept group 42.3% clean-
    runup rate / +2.00% avg 15-bar return (n=456) vs excluded group 34.1% /
    lower (n=135). Real, modest, cross-asset -- not a guarantee, a genuine tilt.

    Returns (label, reasoning). Label is "FRESH", "EXTENDED", or "UNKNOWN" if
    the required fields weren't populated on this CampaignState.
    """
    if state.rsi is None or state.ema21_distance_atr is None:
        return "UNKNOWN", "RSI/EMA21-distance not provided on this state -- extension quality can't be assessed."

    rsi_extended = state.rsi >= 65
    distance_extended = state.ema21_distance_atr >= 1.0
    slope_extended = state.ema21_slope is not None and state.ema21_slope > 0.5  # threshold from the "strong up-slope" bucket that underperformed

    flags = []
    if rsi_extended:
        flags.append(f"RSI {state.rsi:.0f} (>=65 band showed 20% clean-runup rate vs 40-43% for lower bands)")
    if distance_extended:
        flags.append(f"{state.ema21_distance_atr:.1f} ATR above EMA21 (>=1.0 ATR band showed 34.6% clean-runup rate vs 42.5% for 0-1 ATR)")
    if slope_extended:
        flags.append(f"EMA21 slope {state.ema21_slope:.2f} (steep up-slope band showed the WORST clean-runup rate of any bucket tested, 33.3%)")

    if flags:
        return "EXTENDED", "Chasing an already-extended move: " + "; ".join(flags) + ". Validated data says this tilts toward weaker follow-through, not a hard stop."
    return "FRESH", f"Not extended (RSI {state.rsi:.0f}, {state.ema21_distance_atr:.1f} ATR from EMA21) -- the validated 'kept' population that showed 42.3% clean-runup rate / +2.00% avg 15-bar return."


def recommend_no_position(state: CampaignState) -> Recommendation:
    """REDESIGNED (Aug 6, 2026) per explicit direction: the entry decision does
    NOT happen at STRONG START/RELOAD itself. Confirmation (the next real event)
    is the actual entry trigger -- the engine watches, then looks for an entry
    once confirmed, rather than entering on the original signal and hoping.
    Three states: WATCHING (signal fired, no confirmation yet) -> ENTER (next
    event was a continuation -- ADD/FIRE ADD/MANAGE) -> STAND ASIDE (next event
    was FAIL TEST -- confirmation failed, no second chance on this signal)."""
    if state.phase in HEALTHY_PHASES and state.momentum in (Momentum.BUILDING, Momentum.STRONG):
        recent_signal = state.recent_event in ("STRONG START", "RELOAD")
        still_watching = recent_signal or (state.signal_bar_extension_label is not None and state.next_event_after_signal is None)

        if still_watching:
            extension_label, extension_reason = assess_entry_extension(state)
            return Recommendation(
                holding="No position",
                action="WATCHING -- confirmation pending, do not enter yet",
                reason=(f"{state.recent_event} fired. Per validated research: the strongest signal found this "
                        f"session is what happens NEXT, not the signal itself, so entry is deliberately withheld "
                        f"here. Entry condition so far: {extension_reason} Waiting for the next event -- "
                        f"ADD/MANAGE confirms and triggers entry, FAIL TEST invalidates this signal."),
                review_in="Next event",
                confidence_in_call="low -- deliberately withheld until confirmation arrives, not a weak read",
            )

        if state.next_event_after_signal is not None:
            extension_label = state.signal_bar_extension_label or "UNKNOWN"
            is_fail_test = state.next_event_after_signal == "FAIL TEST"
            is_continuation = state.next_event_after_signal in ("ADD", "FIRE ADD", "MANAGE")

            if is_continuation:
                combo_rate = "70.7%" if extension_label == "FRESH" else ("58.2%" if extension_label == "EXTENDED" else "~58-70%")
                return Recommendation(
                    holding="No position",
                    action=f"ENTER -- confirmation received ({state.next_event_after_signal})",
                    reason=(f"{state.next_event_after_signal} fired as the next event after the original signal -- "
                            f"this confirmation IS the entry trigger, not the Start/Reload itself. Validated combined "
                            f"rate for this exact path (entry condition {extension_label} + confirmed continuation): "
                            f"{combo_rate} clean-runup rate, vs 40.4% unconditional baseline across all signals."),
                    review_in="Immediately -- act on this or the window closes",
                    confidence_in_call="moderate-high -- strongest validated signal this session, 591-event sample",
                )
            if is_fail_test:
                combo_rate = "14.7%" if extension_label == "FRESH" else ("10.3%" if extension_label == "EXTENDED" else "~10-15%")
                return Recommendation(
                    holding="No position",
                    action="STAND ASIDE -- confirmation failed",
                    reason=(f"FAIL TEST fired as the next event -- confirmation failed. Validated combined rate "
                            f"for this exact path: only {combo_rate} clean-runup rate. This signal doesn't get a "
                            f"second chance -- wait for a fresh STRONG START/RELOAD, not a bounce on this one."),
                    review_in="Next fresh STRONG START/RELOAD",
                    confidence_in_call="moderate-high -- strongest validated signal this session, 591-event sample",
                )

        return Recommendation(
            holding="No position",
            action="WATCH -- no fresh Start/Reload to confirm off of yet",
            reason=f"{state.phase.value} phase, momentum {state.momentum.value}, but no recent STRONG START/RELOAD in play.",
            review_in="Next STRONG START/RELOAD event",
            confidence_in_call="low",
        )
    if state.phase in WEAK_PHASES:
        return Recommendation(
            holding="No position",
            action="STAND ASIDE",
            reason=f"{state.phase.value} phase -- structurally not a place to initiate.",
            review_in="Next campaign-state change",
            confidence_in_call="moderate",
        )
    return Recommendation(
        holding="No position", action="NO ACTION", reason="No clear edge either direction right now.",
        review_in="Next campaign-state change", confidence_in_call="low",
    )


def recommend_shares(state: CampaignState, pos: SharePosition, current_price: float | None = None) -> Recommendation:
    """Should you hold, trim, or consider covered calls against these shares?"""
    if state.exhaustion_warning and state.phase in HEALTHY_PHASES and state.momentum in (Momentum.BUILDING, Momentum.STRONG) and state.health >= 70:
        # This is the new branch: lagging phase/health still say "strong", but the
        # leading divergence signal (tested: +25-32% edge over base rate, ~13-15 bar
        # lead time) says the move may be exhausting. Downgrade from "hold, wait" to
        # "consider selling calls / don't add" WITHOUT waiting for a confirmed PEAK.
        order = None
        note = ""
        if current_price:
            strike, expiry, note = choose_covered_call_strike(current_price, state)
            contracts = pos.shares // 100
            if contracts >= 1:
                order = OrderProposal(
                    side="sell_to_open", instrument="covered_call", symbol=state.symbol,
                    qty=contracts, strike=strike, expiry=expiry, order_type="limit",
                    rationale=f"Early exhaustion signal, not a confirmed top yet. {note}",
                )
        return Recommendation(
            holding=f"{pos.shares} shares",
            action="EARLY WARNING -- consider covered calls now, don't wait for confirmed PEAK",
            reason=(f"Phase/health still read strong ({state.phase.value}, health {state.health}%), but a leading "
                    f"bearish-divergence signal has fired. Backtested on this symbol's history: this signal "
                    f"precedes a PEAK/FAIL label ~13-15 bars ahead on average, with a real (if modest-sample) edge "
                    f"over chance. This is NOT a confirmed reversal -- treat as 'reduce conviction', not 'the top is in.'"),
            review_in="1-3 sessions -- confirm or clear quickly",
            confidence_in_call="low-moderate -- leading signal, small sample (n=27-52 in backtest), unconfirmed",
            order=order,
        )
    if state.phase in HEALTHY_PHASES and state.momentum in (Momentum.BUILDING, Momentum.STRONG) and state.health >= 70:
        return Recommendation(
            holding=f"{pos.shares} shares",
            action="HOLD -- do not sell covered calls yet",
            reason=(f"{state.phase.value} with health {state.health}% and {state.momentum.value.lower()} momentum. "
                    f"Selling calls now caps upside during what the engine reads as an accelerating phase -- "
                    f"the foregone upside is estimated to outweigh the premium at this point in the cycle."),
            review_in="3-5 sessions, or on next MANAGE/PEAK event",
            confidence_in_call="moderate -- depends on your actual upside target vs. strike you'd sell",
            order=None,
        )
    if state.phase in WEAK_PHASES or state.recent_event in ("PEAK", "FAIL", "FAIL TEST"):
        order = None
        note = ""
        if current_price:
            strike, expiry, note = choose_covered_call_strike(current_price, state)
            contracts = pos.shares // 100
            if contracts >= 1:
                order = OrderProposal(
                    side="sell_to_open", instrument="covered_call", symbol=state.symbol,
                    qty=contracts, strike=strike, expiry=expiry, order_type="limit",
                    rationale=note,
                )
        return Recommendation(
            holding=f"{pos.shares} shares",
            action="COVERED CALLS BECOME ATTRACTIVE",
            reason=(f"{state.phase.value or state.recent_event} suggests upside is decelerating or reversing. "
                    f"Harvesting premium here has a better risk/reward than holding uncapped exposure through "
                    f"a phase the engine already reads as weakening." + (f" Proposed: {note}." if note else "")),
            review_in="Reassess if a fresh IGNITION/STRONG START prints",
            confidence_in_call="moderate",
            order=order,
        )
    return Recommendation(
        holding=f"{pos.shares} shares", action="HOLD -- neutral",
        reason=f"{state.phase.value}, health {state.health}%: no strong signal either way on covered calls.",
        review_in="Next campaign-state change", confidence_in_call="low",
        order=None,
    )


def choose_roll_strike(current_price: float, old_strike: float, state: CampaignState) -> tuple[float, str]:
    """Decide whether a roll should keep, raise, or lower the strike.
    A pure time-roll (same strike) only makes sense if the option is still
    reasonably close to the money. Deep ITM should roll the strike up toward
    current price to reduce cost/extrinsic bleed; the opposite for OTM."""
    moneyness = (current_price - old_strike) / current_price  # >0 = ITM for a call
    if moneyness > 0.20:
        new_strike = round(current_price * 0.90, 2)
        note = (f"Old strike ${old_strike} is {moneyness:.0%} ITM vs current ${current_price} -- "
                f"rolling same-strike would carry a lot of costly intrinsic value forward. "
                f"Proposing strike raised to ${new_strike} to reduce cost while keeping ITM exposure.")
    elif moneyness < -0.10:
        new_strike = round(current_price * 0.98, 2)
        note = (f"Old strike ${old_strike} is OTM vs current ${current_price} -- "
                f"proposing strike lowered to ${new_strike}, closer to the money.")
    else:
        new_strike = old_strike
        note = f"Old strike ${old_strike} is reasonably close to current price ${current_price} -- keeping strike, pure time roll."
    return new_strike, note


def recommend_option_leg(state: CampaignState, leg: OptionLeg, as_of: date, current_price: float | None = None) -> Recommendation:
    dte = days_to_expiry(leg.expiry, as_of)
    label = f"{leg.contracts}x {'LEAPS' if leg.is_leaps else 'call'} ${leg.strike} exp {leg.expiry.isoformat()}"

    if leg.kind == "long_call":
        if leg.is_leaps:
            if state.phase in WEAK_PHASES and state.health < 30:
                return Recommendation(
                    holding=label, action="STRUCTURAL CONCERN -- reassess thesis",
                    reason=f"{state.phase.value} with health {state.health}% is a real break in campaign structure, "
                           f"not routine noise. LEAPS thesis warrants a fresh look, not automatic rolling.",
                    review_in="Immediately",
                    confidence_in_call="moderate",
                    order=None,
                )
            # Deliberate exception: exhaustion_warning is NOT applied here. The
            # backtested lead time (~13-15 bars, i.e. days at 2H/4H) is short
            # relative to a multi-year LEAPS thesis -- reacting to it would mean
            # trading noise on a position sized for structural moves. Flagged
            # explicitly rather than silently ignoring the signal.
            note = " (exhaustion signal present but not actionable at LEAPS horizon)" if state.exhaustion_warning else ""
            return Recommendation(
                holding=label, action="HOLD -- no immediate action" + note,
                reason=f"Campaign structure intact ({state.phase.value}, health {state.health}%). "
                       f"Long-dated LEAPS don't need reaction to short-term phase noise"
                       + (f", including the current exhaustion signal (short lead time, not LEAPS-relevant)." if state.exhaustion_warning else "."),
                review_in="Monthly, or on a FAILURE-phase transition",
                confidence_in_call="moderate",
                order=None,
            )
        # shorter-dated long call
        if dte <= 21:
            order = None
            if current_price:
                new_expiry = date.today().fromordinal(leg.expiry.toordinal() + 45)
                new_strike, strike_note = choose_roll_strike(current_price, leg.strike, state)
                order = OrderProposal(
                    side="roll", instrument="long_call", symbol=state.symbol,
                    qty=leg.contracts, strike=new_strike, expiry=new_expiry, order_type="limit",
                    rationale=f"Roll from {leg.expiry.isoformat()} ({dte} DTE) out to ~{new_expiry.isoformat()}. {strike_note}",
                )
            return Recommendation(
                holding=label, action="REDUCE EXPIRATION RISK -- consider rolling out in time",
                reason=f"Only {dte} days to expiry. Theta decay accelerates from here regardless of campaign health; "
                       f"this is a time-risk call, not a directional one.",
                review_in="This week",
                confidence_in_call="moderate-high (mechanical, less dependent on campaign read)",
                order=order,
            )
        if state.exhaustion_warning and state.phase in HEALTHY_PHASES and state.momentum in (Momentum.BUILDING, Momentum.STRONG):
            # Enough DTE that time isn't the issue, but the leading signal says
            # reduce conviction before phase/health confirm it.
            return Recommendation(
                holding=label, action="CONSIDER TAKING PARTIAL PROFIT / TIGHTENING RISK",
                reason=f"{dte} DTE isn't urgent by time, but an exhaustion (bearish divergence) signal has fired "
                       f"while {state.phase.value}/{state.momentum.value} still read strong. Backtested edge is "
                       f"real but modest (~13-15 bar lead, small sample) -- treat as a reason to trim size or set "
                       f"a tighter mental stop, not to exit outright.",
                review_in="1-3 sessions",
                confidence_in_call="low-moderate -- leading signal, unconfirmed",
                order=None,
            )
        if state.phase in HEALTHY_PHASES and state.momentum in (Momentum.BUILDING, Momentum.STRONG):
            return Recommendation(
                holding=label, action="HOLD",
                reason=f"{dte} DTE is not urgent, and {state.phase.value}/{state.momentum.value} supports staying in the trade.",
                review_in="On next MANAGE/PEAK event or inside 21 DTE",
                confidence_in_call="moderate",
            )
        return Recommendation(
            holding=label, action="MONITOR CLOSELY -- structure weakening",
            reason=f"{state.phase.value}, momentum {state.momentum.value}. Not urgent by time, but by structure.",
            review_in="Next 2-3 sessions",
            confidence_in_call="low-moderate",
        )

    if leg.kind == "short_call":  # covered call already sold
        if state.exhaustion_warning and state.phase in HEALTHY_PHASES and state.momentum == Momentum.STRONG and state.health >= 75:
            return Recommendation(
                holding=label, action="HOLD SHORT CALL -- do not buy back",
                reason=f"Phase/momentum read as reaccelerating ({state.phase.value}, STRONG), which would normally "
                       f"argue for buying back the short call. But an exhaustion (bearish divergence) signal is "
                       f"active at the same time, which contradicts the reacceleration read. Given the conflict, "
                       f"defaulting to the more conservative action (hold the short, don't spend to buy it back).",
                review_in="1-3 sessions -- see which signal resolves first",
                confidence_in_call="low -- conflicting signals, genuinely uncertain",
                order=None,
            )
        if state.phase in HEALTHY_PHASES and state.momentum == Momentum.STRONG and state.health >= 75:
            return Recommendation(
                holding=label, action="CONSIDER BUYING BACK",
                reason=f"Campaign reaccelerating ({state.phase.value}, health {state.health}%, momentum STRONG) -- "
                       f"the short call is now capping upside during renewed strength.",
                review_in="Immediately, weigh buyback cost vs. remaining premium",
                confidence_in_call="moderate",
            )
        if dte <= 7 and state.phase not in WEAK_PHASES:
            return Recommendation(
                holding=label, action="LET DECAY / MANAGE AT EXPIRY",
                reason=f"{dte} DTE, no structural weakness -- limited reason to act before expiration.",
                review_in="At expiry",
                confidence_in_call="moderate-high",
            )
        return Recommendation(
            holding=label, action="HOLD SHORT CALL",
            reason=f"No strong signal to close early given {state.phase.value}/{state.momentum.value}.",
            review_in="Next campaign-state change",
            confidence_in_call="low-moderate",
        )

    return Recommendation(holding=label, action="NO RULE MATCHED", reason="Unhandled leg type.",
                           review_in="n/a", confidence_in_call="n/a")


def choose_add_strike(current_price: float) -> tuple[float, date]:
    """User preference: add into strikes near/slightly below current price (not
    far OTM lottery tickets) with a longer-dated expiry, since this is a
    conviction add, not a quick trade. Rounds to nearest $0.50 -- matches the
    $2-$2.50 range the person described at a ~$2.82 current price."""
    raw = current_price * 0.80
    strike = round(raw * 2) / 2  # nearest $0.50
    expiry = date.today().fromordinal(date.today().toordinal() + 135)  # ~4.5 months out
    return strike, expiry


def recommend_add_exposure(state: CampaignState, position: Position, current_price: float | None = None) -> Recommendation | None:
    """Fires ONLY on a fresh IGNITION or STRONG START event -- per explicit
    instruction, NOT on 'health/momentum has been fine for a while' or any
    softer trigger. Sizing scales with confidence x health, per explicit
    instruction -- NOTE this base formula uses confidence/health, which were
    TESTED AND REJECTED as entry-quality discriminators (Roadmap, Aug 6 2026).
    Left in place per the original explicit sizing instruction, but the
    validated extension check below (RSI/EMA21 distance/slope) is now layered
    on top as a real, evidence-based adjustment -- not a replacement for the
    stated sizing rule, an addition to it."""
    if state.recent_event not in ("IGNITION", "STRONG START"):
        return None

    existing_calls = sum(leg.contracts for leg in position.options if leg.kind == "long_call")
    if existing_calls == 0:
        return None

    scale_factor = (state.confidence / 100) * (state.health / 100)
    base_add = existing_calls * 0.25  # add up to ~25% of current call count at max confidence*health
    add_contracts = max(1, round(base_add * scale_factor))

    extension_label, extension_reason = assess_entry_extension(state)
    extension_note = ""
    if extension_label == "EXTENDED":
        add_contracts = max(1, round(add_contracts * 0.5))
        extension_note = f" CAUTION -- {extension_reason} Sizing halved from the base formula's result to reflect this."
    elif extension_label == "FRESH":
        extension_note = f" {extension_reason}"

    order = None
    rationale = ""
    if current_price:
        strike, expiry = choose_add_strike(current_price)
        rationale = (f"Sizing: {existing_calls} existing call contracts x 25% base x "
                     f"(confidence {state.confidence}% * health {state.health}% = {scale_factor:.0%} factor) "
                     f"= {add_contracts} contracts{' (halved for extension)' if extension_label == 'EXTENDED' else ''}. "
                     f"Strike/expiry chosen near-the-money, longer-dated, "
                     f"per stated preference for conviction adds rather than far-OTM lottery tickets.")
        order = OrderProposal(
            side="buy", instrument="long_call", symbol=state.symbol,
            qty=add_contracts, strike=strike, expiry=expiry, order_type="limit",
            rationale=rationale,
        )
    return Recommendation(
        holding=f"NEW: add exposure ({existing_calls} existing call contracts)",
        action=f"FRESH {state.recent_event} -- consider adding {add_contracts}x calls",
        reason=(f"Trigger fired: {state.recent_event} is a confirmed-strength event, not routine noise. "
                f"This is the only condition that fires this recommendation -- ongoing 'health has been fine' "
                f"does NOT trigger an add, per your stated rule." + extension_note),
        review_in="Immediately -- this event-based trigger doesn't persist, act or let it pass",
        confidence_in_call=("moderate -- event-triggered AND extension-checked (validated signal)" if extension_label != "UNKNOWN"
                             else "moderate -- event-triggered, but sizing formula itself is untested/unvalidated"),
        order=order,
    )


def assess_path_clarity(state: CampaignState) -> Recommendation | None:
    """Real-time path-clarity check (Roadmap, Aug 6 2026 -- the strongest
    signal found in this session's research). NOT a pre-entry filter --
    this watches what happens immediately AFTER a STRONG START/RELOAD.

    Validated on 591 real events, next-6-events traced:
      Next event = FAIL TEST: 73.3% of eventually-not-clean paths showed this
        as the very next event, vs only 17.2% of eventually-clean paths.
      Combined with entry-extension (assess_entry_extension, frozen at signal
        time -- see signal_bar_extension_label):
          FRESH entry + next=continuation (ADD/MANAGE): 70.7% clean-runup rate
          FRESH entry + next=FAIL TEST:                 14.7%
          EXTENDED entry + next=continuation:            58.2%
          EXTENDED entry + next=FAIL TEST:               10.3%
      (baseline across all signals, no filtering: 40.4%)
      Timing does NOT matter -- tested, null result -- it's whether FAIL TEST
      is the next event at all, not how fast it arrives.

    Fires only when there's something to say: state.next_event_after_signal
    must be populated. Returns None while still waiting (no premature call)."""
    if state.next_event_after_signal is None:
        return None
    if state.signal_bar_extension_label is None:
        state_label = "UNKNOWN"
    else:
        state_label = state.signal_bar_extension_label

    is_fail_test = state.next_event_after_signal in ("FAIL TEST",)
    is_continuation = state.next_event_after_signal in ("ADD", "FIRE ADD", "MANAGE")

    if is_fail_test:
        combo_rate = "14.7%" if state_label == "FRESH" else ("10.3%" if state_label == "EXTENDED" else "~15-20%")
        return Recommendation(
            holding="Recently-entered STRONG START/RELOAD position",
            action="EARLY WARNING -- immediate re-test, path is unclear",
            reason=(f"A FAIL TEST fired as the very next event after this signal -- the strongest single "
                    f"predictor found this session. Combined with entry condition ({state_label}): validated "
                    f"clean-runup rate for this exact combination is {combo_rate}, vs 40.4% baseline. "
                    f"This is real-time evidence, not a guess -- worth treating as a genuine early-warning, "
                    f"not routine noise."),
            review_in="Immediately",
            confidence_in_call="moderate-high -- strongest validated signal this session, 591-event sample",
        )
    if is_continuation:
        combo_rate = "70.7%" if state_label == "FRESH" else ("58.2%" if state_label == "EXTENDED" else "~58-70%")
        return Recommendation(
            holding="Recently-entered STRONG START/RELOAD position",
            action="CONFIRMED -- path looks clear",
            reason=(f"{state.next_event_after_signal} fired as the next event after this signal -- real-time "
                    f"confirmation the campaign is building, not stalling. Combined with entry condition "
                    f"({state_label}): validated clean-runup rate for this combination is {combo_rate}, "
                    f"vs 40.4% baseline."),
            review_in="Next campaign-state change",
            confidence_in_call="moderate-high -- strongest validated signal this session, 591-event sample",
        )
    return None


def check_reload_quality(state: CampaignState) -> Recommendation | None:
    """Post-entry RELOAD management rule (Roadmap #21). NOT an entry filter --
    tested and rejected as one (health>=50 looked promising on 1H/2H, reversed
    on 3H, neutral on 4H). What DOES hold up across all four timeframes: a
    RELOAD followed by a FAIL TEST/FAIL within ~12 bars ('messy') performs
    meaningfully worse than one that isn't ('clean') -- e.g. on 4H, messy
    RELOADs averaged -8.45% over the next 20 bars vs clean RELOADs' +4.17%.
    This only fires if you're already holding a position from around a RELOAD
    and a fail-type event shows up shortly after -- it's an early-cut signal,
    not a reason to avoid entering on a fresh RELOAD in the first place."""
    if state.bars_since_reload is None or state.bars_since_reload > 12:
        return None
    if state.recent_event in ("FAIL", "FAIL TEST", "CATASTROPHIC FAIL"):
        return Recommendation(
            holding="RELOAD-based position",
            action="EARLY CUT SIGNAL -- messy RELOAD pattern",
            reason=(f"A {state.recent_event} fired only {state.bars_since_reload} bars after the RELOAD this position "
                    f"was likely entered on. Backtested across 1H/2H/3H/4H: this 'messy RELOAD' pattern precedes "
                    f"meaningfully worse forward returns than a 'clean' RELOAD (no fail within ~12 bars) -- on 4H, "
                    f"messy RELOADs averaged -8.45% over the next 20 bars vs +4.17% for clean ones. This is a reason "
                    f"to cut faster than you would on an ordinary, isolated FAIL TEST."),
            review_in="Immediately",
            confidence_in_call="moderate -- consistent pattern across 4 timeframes, but no real-time entry predictor exists yet",
        )
    return None


def synthesize_multi_timeframe_decision(states: list[CampaignState], position: Position, current_price: float | None = None) -> Recommendation:
    """THE real fix for 'one trade, not N independent per-timeframe boxes'
    (explicit direction, Aug 8 2026). Pine cannot do this -- each chart is an
    isolated script instance with no way to see another chart's state. This
    is where the actual single decision has to live.

    Takes every currently-tracked timeframe for a symbol (from
    webhook_receiver.py's /state_all/<symbol> endpoint) and produces ONE
    recommendation -- not Pine's hardcoded 3-anchor ladder (a real platform
    constraint, not a design choice), the genuine full picture across
    however many timeframes are actually reporting.

    Uses the exact same validated logic as the Pine cross-TF work:
    - Entry: count timeframes showing a CONFIRMED signal (next event after
      a STRONG START/RELOAD was a continuation -- ADD/FIRE ADD/MANAGE).
      3+ aligned = real entry signal (Roadmap Aug 6-7 2026 validation).
    - Exit: count timeframes showing an active, unrescued FAIL (recent_event
      is a FAIL type with no RELOAD since). 3+ aligned = real exit signal
      (Roadmap Aug 7 2026, cross-asset validated).

    HONEST SCOPE LIMIT: this reads the CURRENT snapshot each timeframe last
    reported, not a full replay of each timeframe's own state machine --
    less complete than what a real backtest could check, but genuinely more
    complete than Pine's fixed 3-anchor limit, and it's real, working code
    today, not a future promise."""
    if not states:
        return Recommendation(
            holding="Unknown", action="NO DATA",
            reason="No timeframes reporting for this symbol yet -- webhook hasn't received any alerts.",
            review_in="Once alerts start arriving", confidence_in_call="none",
        )

    total_tfs = len(states)
    confirmed_count = sum(1 for s in states if s.next_event_after_signal in ("ADD", "FIRE ADD", "MANAGE"))
    fail_types = ("FAIL", "FAIL TEST", "CATASTROPHIC FAIL", "MODERATE FAIL", "STRONG FAIL")
    unrescued_fail_count = sum(1 for s in states if s.recent_event in fail_types)

    tf_list = ", ".join(f"{s.timeframe}" for s in states)
    threshold = 3 if total_tfs >= 4 else max(2, total_tfs - 1)  # scales down honestly for symbols with fewer timeframes reporting

    if unrescued_fail_count >= threshold:
        return Recommendation(
            holding="Multi-timeframe synthesis", action="EXIT SIGNAL -- cross-TF weakness confirmed",
            reason=(f"{unrescued_fail_count} of {total_tfs} tracked timeframes ({tf_list}) show an active, "
                    f"unrescued FAIL right now. This is the real, cross-asset-validated exit pattern -- "
                    f"AMC -2.10%/68% negative, ARB -1.36%/81% negative (Roadmap Aug 7 2026)."),
            review_in="Immediately", confidence_in_call="moderate-high -- validated cross-asset",
        )
    if confirmed_count >= threshold:
        return Recommendation(
            holding="Multi-timeframe synthesis", action="ENTRY SIGNAL -- cross-TF confirmation",
            reason=(f"{confirmed_count} of {total_tfs} tracked timeframes ({tf_list}) show confirmed "
                    f"continuation after a Strong Start/Reload. Validated: 39.5% vs 26.8% clean-runup rate "
                    f"for genuinely aligned vs isolated ADD-type signals (Roadmap Aug 7 2026)."),
            review_in="Immediately -- act on this or the window closes", confidence_in_call="moderate-high -- validated cross-asset",
        )
    return Recommendation(
        holding="Multi-timeframe synthesis", action="NO SYNTHESIZED SIGNAL",
        reason=(f"Checked {total_tfs} timeframes ({tf_list}): {confirmed_count} confirmed entries, "
                f"{unrescued_fail_count} unrescued fails -- neither reaches the {threshold}-timeframe "
                f"alignment threshold. No real, validated signal right now."),
        review_in="Next timeframe state change", confidence_in_call="low",
    )


def suggest_trailing_stop(states: list[CampaignState], position: Position, current_price: float) -> Recommendation | None:
    """Real, structural trailing-stop suggestion -- explicit direction, Aug 8
    2026: 'watch the recent lower levels on multi TF... suggest move SL
    higher if trend develops and remains strong instead of closing it.'

    Only fires when there's an actual position to trail (position.current_stop
    must be set -- otherwise there's nothing to compare against) AND the
    synthesized multi-TF picture is NOT currently showing an exit signal
    (trailing only makes sense while the trend is genuinely still healthy --
    if cross-TF weakness has already fired, that's an exit call, not a trail
    call, and takes priority).

    Method: each timeframe's recent_support_price is the real price level of
    its own most recent bullish signal (Strong Start/Reload/Add/Manage) --
    not a guess, a real structural level the engine already tracked. Only
    levels BELOW current price are usable (a level above price isn't a valid
    stop reference -- it's already been passed). Among valid levels, suggest
    the HIGHEST one below price -- the tightest defensible support, not the
    deepest. Never suggests moving a stop DOWN -- that's not what trailing
    means, and this function won't do it even if a lower support level
    computes as 'valid' by the above rule alone."""
    if position.current_stop is None:
        return None
    if not states:
        return None

    synthesis = synthesize_multi_timeframe_decision(states, position, current_price)
    if synthesis.action.startswith("EXIT SIGNAL"):
        return None  # weakness already confirmed -- this is an exit call, not a trail call

    valid_levels = [s.recent_support_price for s in states if s.recent_support_price is not None and s.recent_support_price < current_price]
    if not valid_levels:
        return None

    best_level = max(valid_levels)  # tightest defensible support below price
    if best_level <= position.current_stop:
        return None  # would move the stop DOWN or sideways -- never suggest that, trailing only goes one direction

    tfs_supporting = [s.timeframe for s in states if s.recent_support_price == best_level]
    return Recommendation(
        holding="Open position -- trailing stop opportunity",
        action=f"CONSIDER RAISING STOP to ${best_level:.4f}",
        reason=(f"Trend remains healthy (no cross-TF exit signal active). Recent support at ${best_level:.4f} "
                f"comes from timeframe(s) {', '.join(tfs_supporting)}'s own most recent bullish signal -- a real "
                f"structural level, not an arbitrary trail distance. Current stop: ${position.current_stop:.4f}. "
                f"This is an option to lock in more of the move, not a requirement -- closing entirely remains valid too."),
        review_in="Next timeframe state change",
        confidence_in_call="moderate -- structural, but a single support level can still fail",
    )


def build_recommendations(state: CampaignState, position: Position, as_of: date = None, current_price: float | None = None) -> list[Recommendation]:
    as_of = as_of or date.today()
    recs = []
    if position.shares is None and not position.options:
        recs.append(recommend_no_position(state))
        return recs
    if position.shares:
        recs.append(recommend_shares(state, position.shares, current_price))
    for leg in position.options:
        recs.append(recommend_option_leg(state, leg, as_of, current_price))
    add_rec = recommend_add_exposure(state, position, current_price)
    if add_rec:
        recs.append(add_rec)
    reload_rec = check_reload_quality(state)
    if reload_rec:
        recs.append(reload_rec)
    path_clarity_rec = assess_path_clarity(state)
    if path_clarity_rec:
        recs.append(path_clarity_rec)
    return recs


def print_recs(title: str, recs: list[Recommendation]):
    print(f"\n=== {title} ===")
    for r in recs:
        print(f"  [{r.holding}]")
        print(f"    Action:      {r.action}")
        print(f"    Reason:      {r.reason}")
        print(f"    Review in:   {r.review_in}")
        print(f"    Call confidence: {r.confidence_in_call}")
        if r.order:
            o = r.order
            print(f"    >> PROPOSED ORDER (requires your explicit approval before anything is submitted):")
            print(f"       {o.side.upper()} {o.qty}x {o.instrument} {o.symbol}"
                  + (f" ${o.strike} exp {o.expiry.isoformat()}" if o.strike else ""))
            print(f"       Type: {o.order_type}" + (f", limit {o.limit_price}" if o.limit_price else " (price TBD from live chain)"))
            print(f"       Why this strike/expiry: {o.rationale}")


if __name__ == "__main__":
    # Live AMC 4H state, built via the dashboard bridge from the actual Aug 1 2026
    # screenshot readout (v12.6.5): PHASE EXPANSION, CONFIDENCE 71%, HEALTH 83%,
    # MOMENTUM BUILDING, STATUS ACTIVE, ACTION BUILD.
    amc_state = campaign_state_from_dashboard(
        "AMC", "4H", phase="EXPANSION", confidence=71, health=83, momentum="BUILDING",
        status="ACTIVE", action="BUILD",
    )
    today = date(2026, 8, 1)
    current_price = 2.82  # from live chart

    # Case 1: no position
    print_recs("Case 1: No AMC position", build_recommendations(amc_state, Position()))

    # Case 2: 2,000 shares only (healthy state -> no order, hold)
    print_recs("Case 2: 2,000 shares, no options (healthy state)",
                build_recommendations(amc_state, Position(shares=SharePosition(2000, 2.10)), current_price=current_price))

    # Case 2b: same shares, but a weaker/PEAK state -> should propose a covered call order
    weak_state = CampaignState(symbol="AMC", timeframe="4H", phase=Phase.DISTRIBUTION, health=42,
                                confidence=55, momentum=Momentum.WEAK, recent_event="PEAK", trend="down")
    print_recs("Case 2b: same 2,000 shares, but campaign has turned (PEAK/DISTRIBUTION)",
                build_recommendations(weak_state, Position(shares=SharePosition(2000, 2.10)), current_price=current_price))

    # Case 3: short-dated ITM calls only -> should propose a roll order
    short_call_pos = Position(options=[OptionLeg("long_call", strike=2.00, expiry=date(2026, 8, 21), contracts=10, is_leaps=False)])
    print_recs("Case 3: short-dated ITM long calls (Aug 21 exp, 19 DTE)",
                build_recommendations(amc_state, short_call_pos, as_of=today, current_price=current_price))

    # Case 2c: same healthy state as Case 2, but exhaustion_warning fires --
    # this is the actual behavior change requested: act on the edge, not just
    # the lagging PEAK/FAIL label.
    amc_state_exhausted = campaign_state_from_dashboard(
        "AMC", "4H", phase="EXPANSION", confidence=71, health=83, momentum="BUILDING",
        status="ACTIVE", action="BUILD", exhaustion_warning=True,
    )
    print_recs("Case 2c: same 2,000 shares, same healthy dashboard, but exhaustion_warning=True",
                build_recommendations(amc_state_exhausted, Position(shares=SharePosition(2000, 2.10)), current_price=current_price))

    # Case 4: 2028 LEAPS only
    leaps_pos = Position(options=[OptionLeg("long_call", strike=2.50, expiry=date(2028, 1, 19), contracts=10, is_leaps=True)])
    print_recs("Case 4: 2028 LEAPS calls", build_recommendations(amc_state, leaps_pos, as_of=today, current_price=current_price))

    # Case 5: your actual rough shape -- half stock, half ITM options -- roll + covered call question
    mixed_pos = Position(
        shares=SharePosition(1000, 2.10),
        options=[
            OptionLeg("long_call", strike=2.00, expiry=date(2027, 1, 15), contracts=10, is_leaps=True),
        ],
    )
    print_recs("Case 5: half shares / half ITM LEAPS calls (your rough shape)",
                build_recommendations(amc_state, mixed_pos, as_of=today, current_price=current_price))

    # Case 6: LEAPS with exhaustion_warning -- should explicitly note it's not actionable at this horizon
    print_recs("Case 6: LEAPS, exhaustion_warning=True (should be flagged, not acted on)",
                build_recommendations(amc_state_exhausted, leaps_pos, as_of=today, current_price=current_price))

    # Case 7: longer-dated (not near-expiry) long call, exhaustion_warning=True -- should trim/tighten, not roll
    longer_call_pos = Position(options=[OptionLeg("long_call", strike=2.20, expiry=date(2026, 12, 18), contracts=10, is_leaps=False)])
    print_recs("Case 7: longer-dated call (not near expiry), exhaustion_warning=True",
                build_recommendations(amc_state_exhausted, longer_call_pos, as_of=today, current_price=current_price))

    # Case 8: an already-open covered call, campaign reaccelerating (STRONG) but exhaustion_warning also True
    short_call_pos = Position(options=[OptionLeg("short_call", strike=3.50, expiry=date(2026, 9, 18), contracts=10)])
    strong_and_exhausted = campaign_state_from_dashboard(
        "AMC", "4H", phase="EXPANSION", confidence=80, health=85, momentum="STRONG",
        exhaustion_warning=True,
    )
    print_recs("Case 8: open covered call, momentum STRONG + exhaustion_warning=True (conflicting signals)",
                build_recommendations(strong_and_exhausted, short_call_pos, as_of=today, current_price=current_price))
