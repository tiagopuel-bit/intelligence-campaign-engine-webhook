"""Historical cohort and forward-target helpers for Options DNA research.

These helpers are deliberately separate from the causal live feature ledger:
forward outcomes contain future information and must never enter live guidance.
"""
from __future__ import annotations

from datetime import date, datetime


def _as_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _directional_moneyness(contract_type: str, spot: float, strike: float) -> float:
    sign = 1.0 if contract_type == "CALL" else -1.0
    return sign * (spot - strike) / strike * 100.0


def select_contract_cohort(
    contracts: list[dict],
    *,
    spot: float,
    anchor_date,
    dte_targets=(7, 14, 30, 60, 90),
    moneyness_targets=(-10.0, 0.0, 10.0),
    dte_tolerance_days: int = 3,
    moneyness_tolerance_pct: float = 7.5,
    fallback_to_nearest_strike: bool = False,
) -> list[dict]:
    """Select deterministic standard contracts for balanced research cells.

    Positive direction-aware moneyness is ITM for both calls and puts. Adjusted
    contracts/additional deliverables are excluded from the first calibration.
    """
    anchor = _as_date(anchor_date)
    candidates = []
    for raw in contracts:
        ctype = str(raw.get("contract_type") or "").upper()
        if ctype not in {"CALL", "PUT"}:
            continue
        if raw.get("additional_underlyings"):
            continue
        if float(raw.get("shares_per_contract") or 100) != 100:
            continue
        try:
            strike = float(raw["strike"] if "strike" in raw else raw["strike_price"])
            expiry = _as_date(raw["expiration"] if "expiration" in raw else raw["expiration_date"])
        except (KeyError, TypeError, ValueError):
            continue
        dte = (expiry - anchor).days
        if strike <= 0 or dte < 0:
            continue
        candidates.append({
            "ticker": raw.get("ticker"),
            "contract_type": ctype,
            "strike": strike,
            "expiration": expiry.isoformat(),
            "dte": dte,
            "moneyness_pct": _directional_moneyness(ctype, float(spot), strike),
        })

    selected = []
    for ctype in ("CALL", "PUT"):
        typed = [c for c in candidates if c["contract_type"] == ctype]
        for dte_target in dte_targets:
            for money_target in moneyness_targets:
                eligible = [
                    c for c in typed
                    if abs(c["dte"] - dte_target) <= dte_tolerance_days
                    and abs(c["moneyness_pct"] - money_target) <= moneyness_tolerance_pct
                ]
                selection_policy = "WITHIN_TOLERANCE"
                if not eligible and fallback_to_nearest_strike:
                    eligible = [
                        c for c in typed
                        if abs(c["dte"] - dte_target) <= dte_tolerance_days
                    ]
                    selection_policy = "NEAREST_REGULAR_STRIKE"
                if not eligible:
                    continue
                chosen = min(eligible, key=lambda c: (
                    abs(c["dte"] - dte_target),
                    abs(c["moneyness_pct"] - money_target),
                    c["expiration"], c["strike"], c.get("ticker") or "",
                ))
                distance = abs(chosen["moneyness_pct"] - money_target)
                band = (
                    "NEAR_ATM" if abs(chosen["moneyness_pct"]) <= 7.5
                    else "MODERATE" if abs(chosen["moneyness_pct"]) <= 20.0
                    else "FAR"
                )
                selected.append(dict(
                    chosen,
                    dte_target=dte_target,
                    moneyness_target=money_target,
                    moneyness_distance_pct=distance,
                    moneyness_band=band,
                    selection_policy=selection_policy,
                ))
    return selected


def forward_long_premium_outcome(bars: list[dict], index: int, horizon_bars: int) -> dict:
    """Return research-only long-premium outcomes after one candidate bar."""
    if index < 0 or index >= len(bars) or horizon_bars < 1:
        raise ValueError("invalid candidate index or horizon")
    entry = float(bars[index]["c"])
    if entry <= 0:
        raise ValueError("candidate close must be positive")
    future = bars[index + 1:index + 1 + horizon_bars]
    if not future:
        return {"right_censored": True, "observed_bars": 0}
    returns = [(float(bar["c"]) / entry - 1.0) * 100.0 for bar in future]
    best = max(range(len(returns)), key=returns.__getitem__)
    mfe = returns[best]
    terminal = returns[-1]
    return {
        "right_censored": len(future) < horizon_bars,
        "observed_bars": len(future),
        "mfe_pct": mfe,
        "mae_pct": min(returns),
        "terminal_return_pct": terminal,
        "bars_to_peak": best + 1,
        "gain_retention": terminal / mfe if mfe > 0 else None,
    }


def forward_long_premium_path_outcome(bars: list[dict], index: int, horizon_bars: int) -> dict:
    """Research-only path outcome using the first post-signal bar open.

    The candidate event is known at its bar close. The first actionable proxy
    is therefore the next bar's open, never the signal bar's open. Future highs
    and lows measure excursions so a fast squeeze or intrabar premium drain is
    not hidden by closing-price-only outcomes.
    """
    if index < 0 or index >= len(bars) or horizon_bars < 1:
        raise ValueError("invalid candidate index or horizon")
    future = bars[index + 1:index + 1 + horizon_bars]
    result = _path_outcome(float(bars[index]["c"]), future)
    result["right_censored"] = len(future) < horizon_bars
    return result


def forward_long_premium_path_until(
    bars: list[dict], index: int, cutoff_time_ms: int,
) -> dict:
    """Path outcome through an external causal trading-clock cutoff.

    The caller derives the cutoff from the underlying bar calendar. Missing
    option prints remain missing and do not extend the window.
    """
    if index < 0 or index >= len(bars):
        raise ValueError("invalid candidate index")
    signal_time = int(bars[index]["t"])
    cutoff = int(cutoff_time_ms)
    if cutoff <= signal_time:
        raise ValueError("cutoff must follow the signal bar")
    future = [
        bar for bar in bars[index + 1:]
        if signal_time < int(bar["t"]) <= cutoff
    ]
    return _path_outcome(float(bars[index]["c"]), future)


def _path_outcome(decision_close: float, future: list[dict]) -> dict:
    if decision_close <= 0:
        raise ValueError("candidate close must be positive")
    if not future:
        return {"observed_bars": 0}

    next_open = float(future[0].get("o", future[0]["c"]))
    if next_open <= 0:
        raise ValueError("next bar open must be positive")
    highs = [float(bar.get("h", bar["c"])) for bar in future]
    lows = [float(bar.get("l", bar["c"])) for bar in future]
    closes = [float(bar["c"]) for bar in future]
    if any(value <= 0 for value in highs + lows + closes):
        raise ValueError("future option prices must be positive")

    peak_index = max(range(len(highs)), key=highs.__getitem__)
    trough_index = min(range(len(lows)), key=lows.__getitem__)
    peak = highs[peak_index]
    trough = lows[trough_index]
    terminal = closes[-1]
    mfe = (peak / next_open - 1.0) * 100.0
    mae = (trough / next_open - 1.0) * 100.0
    terminal_return = (terminal / next_open - 1.0) * 100.0
    decision_mfe = (peak / decision_close - 1.0) * 100.0
    decision_mae = (trough / decision_close - 1.0) * 100.0
    return {
        "observed_bars": len(future),
        "decision_close": decision_close,
        "next_bar_open": next_open,
        "decision_to_next_open_gap_pct": (next_open / decision_close - 1.0) * 100.0,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "terminal_return_pct": terminal_return,
        "bars_to_peak": peak_index + 1,
        "bars_to_trough": trough_index + 1,
        "peak_to_terminal_giveback_pct": (terminal / peak - 1.0) * 100.0,
        "gain_retention": terminal_return / mfe if mfe > 0 else None,
        "decision_close_mfe_pct": decision_mfe,
        "decision_close_mae_pct": decision_mae,
        "peak_before_trough": peak_index < trough_index,
    }
