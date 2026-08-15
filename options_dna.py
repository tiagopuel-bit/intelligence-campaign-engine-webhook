"""Causal Options DNA component ledger from synchronized OHLCV bars.

This module intentionally emits neither entry/exit guidance nor a combined
heat score. Missing option bars are never forward-filled.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import mean, pstdev


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def _log_return(current, previous):
    if not (_finite(current) and _finite(previous)) or current <= 0 or previous <= 0:
        return None
    return math.log(float(current) / float(previous))


def _prior_mean(values):
    clean = [float(v) for v in values if _finite(v)]
    return mean(clean) if clean else None


def _ratio(current, baseline):
    if not (_finite(current) and _finite(baseline)) or baseline <= 0:
        return None
    return float(current) / float(baseline)


def _rolling_beta(xs, ys):
    """OLS beta of y on x with an intercept, or None without variance."""
    pairs = [(float(x), float(y)) for x, y in zip(xs, ys) if _finite(x) and _finite(y)]
    if len(pairs) < 3:
        return None
    xbar = mean(x for x, _ in pairs)
    ybar = mean(y for _, y in pairs)
    variance = sum((x - xbar) ** 2 for x, _ in pairs)
    if variance <= 1e-18:
        return None
    return sum((x - xbar) * (y - ybar) for x, y in pairs) / variance


def align_bars(option_bars: list[dict], underlying_bars: list[dict]) -> list[tuple[dict, dict]]:
    """Return exact timestamp matches, ascending, without filling gaps."""
    option_by_t = {int(b["t"]): b for b in option_bars if "t" in b}
    underlying_by_t = {int(b["t"]): b for b in underlying_bars if "t" in b}
    return [
        (option_by_t[t], underlying_by_t[t])
        for t in sorted(option_by_t.keys() & underlying_by_t.keys())
    ]


def component_ledger(
    option_bars: list[dict],
    underlying_bars: list[dict],
    *,
    contract_type: str,
    strike: float,
    expiration: str,
    lookback: int = 20,
    min_history: int = 12,
    min_activity_ratio: float = 0.50,
) -> dict:
    """Return the latest causal Options DNA evidence components.

    Baselines use matched observations strictly before the active bar. The
    active bar can be described but never participates in its own baseline.
    """
    ctype = (contract_type or "").strip().upper()
    reasons: list[str] = []
    if ctype not in {"CALL", "PUT"}:
        reasons.append("invalid contract type")
    if not _finite(strike) or float(strike) <= 0:
        reasons.append("invalid strike")
    try:
        expiry = datetime.strptime(expiration, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        expiry = None
        reasons.append("invalid expiration")

    matched = align_bars(option_bars, underlying_bars)
    if len(matched) < min_history + 1:
        reasons.append("insufficient matched history")
    if not matched:
        return {"ready": False, "quality_reasons": sorted(set(reasons)), "matched_bars": 0}

    current_option, current_underlying = matched[-1]
    current_t = int(current_option["t"])
    underlying_window = [b for b in underlying_bars if int(b.get("t", -1)) <= current_t][-lookback:]
    activity_ratio = len(matched[-lookback:]) / len(underlying_window) if underlying_window else 0.0
    if activity_ratio < min_activity_ratio:
        reasons.append("sparse option activity")

    history = matched[:-1][-lookback:]
    series = matched[-(lookback + 1):]
    if not all(_finite(current_option.get(k)) for k in ("o", "h", "l", "c", "v")):
        reasons.append("invalid option OHLCV")
    if not _finite(current_underlying.get("c")) or current_underlying.get("c", 0) <= 0:
        reasons.append("invalid underlying close")

    sign = 1.0 if ctype == "CALL" else -1.0
    option_return = _log_return(current_option.get("c"), history[-1][0].get("c")) if history else None
    underlying_return_raw = _log_return(current_underlying.get("c"), history[-1][1].get("c")) if history else None
    directional_return = sign * underlying_return_raw if underlying_return_raw is not None else None

    prior_x, prior_y = [], []
    for previous, active in zip(series[:-2], series[1:-1]):
        option_ret = _log_return(active[0].get("c"), previous[0].get("c"))
        underlying_ret = _log_return(active[1].get("c"), previous[1].get("c"))
        prior_x.append(sign * underlying_ret if underlying_ret is not None else None)
        prior_y.append(option_ret)
    beta = _rolling_beta(prior_x, prior_y)
    if beta is None:
        reasons.append("zero or insufficient underlying variance")
    residual = option_return - beta * directional_return if None not in (option_return, beta, directional_return) else None
    prior_residuals = [
        y - beta * x for x, y in zip(prior_x, prior_y)
        if beta is not None and _finite(x) and _finite(y)
    ]
    residual_sd = pstdev(prior_residuals) if len(prior_residuals) >= 2 else 0.0
    residual_z = (
        (residual - mean(prior_residuals)) / residual_sd
        if residual is not None and prior_residuals and residual_sd > 1e-18 else None
    )

    prior_option = [pair[0] for pair in history]
    volume_ratio = _ratio(current_option.get("v"), _prior_mean([b.get("v") for b in prior_option]))
    transaction_ratio = _ratio(current_option.get("n"), _prior_mean([b.get("n") for b in prior_option]))
    current_range = (
        float(current_option["h"]) - float(current_option["l"])
        if _finite(current_option.get("h")) and _finite(current_option.get("l")) else None
    )
    prior_ranges = [
        float(b["h"]) - float(b["l"])
        for b in prior_option if _finite(b.get("h")) and _finite(b.get("l"))
    ]
    range_expansion = _ratio(current_range, _prior_mean(prior_ranges))
    close_location = (
        (float(current_option["c"]) - float(current_option["l"])) / current_range
        if _finite(current_range) and current_range > 0 and _finite(current_option.get("c")) else None
    )
    vwap_distance_pct = (
        (float(current_option["c"]) / float(current_option["vw"]) - 1.0) * 100.0
        if _finite(current_option.get("c")) and _finite(current_option.get("vw")) and current_option["vw"] > 0 else None
    )
    prior_high = max((float(b["h"]) for b in prior_option if _finite(b.get("h"))), default=None)
    drawdown = (
        max(0.0, (prior_high - float(current_option["c"])) / prior_high * 100.0)
        if prior_high and _finite(current_option.get("c")) else None
    )

    underlying_close = float(current_underlying["c"]) if _finite(current_underlying.get("c")) else None
    strike_value = float(strike) if _finite(strike) else None
    intrinsic = None
    moneyness = None
    if underlying_close is not None and strike_value is not None and strike_value > 0:
        intrinsic = max(0.0, underlying_close - strike_value) if ctype == "CALL" else max(0.0, strike_value - underlying_close)
        moneyness = sign * (underlying_close - strike_value) / strike_value * 100.0
    option_close = float(current_option["c"]) if _finite(current_option.get("c")) else None
    extrinsic = max(0.0, option_close - intrinsic) if option_close is not None and intrinsic is not None else None
    dte = max(0, (expiry.date() - datetime.fromtimestamp(current_t / 1000, tz=timezone.utc).date()).days) if expiry else None

    return {
        "ready": not reasons,
        "quality_reasons": sorted(set(reasons)),
        "bar_time": current_t,
        "matched_bars": len(matched),
        "activity_ratio": activity_ratio,
        "option_return": option_return,
        "underlying_directional_return": directional_return,
        "rolling_beta": beta,
        "relative_response_residual": residual,
        "relative_response_z": residual_z,
        "volume_ratio": volume_ratio,
        "transaction_ratio": transaction_ratio,
        "range_expansion": range_expansion,
        "close_location": close_location,
        "vwap_distance_pct": vwap_distance_pct,
        "drawdown_from_high_pct": drawdown,
        "dte": dte,
        "moneyness_pct": moneyness,
        "intrinsic_value": intrinsic,
        "extrinsic_value_observed": extrinsic,
    }

