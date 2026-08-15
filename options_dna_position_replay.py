"""Causal simulated long-premium episodes for position-navigation research.

Episodes begin only when an option aggregate exists exactly at the underlying
decision timestamp; its open is the executable research proxy.  The same
contract is then observed at later audited DNA event bars.  Causal position
snapshots and future path outcomes are returned separately.

This is not a trade simulator: it models no spread, fill improvement, fees,
slippage, exercise, assignment, sizing, or user behavior and emits no orders.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from options_dna import component_ledger
from options_dna_research import forward_long_premium_path_until


ENTRY_ORIGINS = {"ENTRY_FORMING", "CONTINUATION"}
TIME_WINDOWS = (("H1", 4), ("D1", 26), ("D3", 78), ("D5", 130), ("D10", 260))
COMPONENT_FIELDS = (
    "ready", "quality_reasons", "bar_time", "matched_bars", "activity_ratio",
    "option_return", "underlying_directional_return", "rolling_beta",
    "relative_response_residual", "relative_response_z", "volume_ratio",
    "transaction_ratio", "range_expansion", "close_location",
    "vwap_distance_pct", "drawdown_from_high_pct", "dte", "moneyness_pct",
    "intrinsic_value", "extrinsic_value_observed",
)
PATH_FIELDS = (
    "observed_bars", "decision_close", "next_bar_open",
    "decision_to_next_open_gap_pct", "mfe_pct", "mae_pct",
    "terminal_return_pct", "bars_to_peak", "bars_to_trough",
    "peak_to_terminal_giveback_pct", "gain_retention",
    "decision_close_mfe_pct", "decision_close_mae_pct", "peak_before_trough",
)


def _dt(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _ms(value: object) -> int:
    return int(_dt(value).timestamp() * 1000)


def _episode_id(anchor_id: str, ticker: str) -> str:
    digest = hashlib.sha256(f"{anchor_id}|{ticker}".encode("utf-8")).hexdigest()[:16]
    return f"OPT-LONG-{digest}"


def build_position_episode_ledgers(
    cohort_rows: list[dict], full_event_anchors: list[dict],
    option_bars_by_ticker: dict[str, list[dict]], underlying_bars: list[dict], *,
    max_calendar_days: int = 21, entry_origins: set[str] | None = None,
) -> dict:
    """Return episodes, causal snapshots, future windows, and rejections."""
    if max_calendar_days <= 0:
        raise ValueError("max_calendar_days must be positive")
    origins = ENTRY_ORIGINS if entry_origins is None else set(entry_origins)
    under_by_t = {int(bar["t"]): index for index, bar in enumerate(underlying_bars)}
    anchors = sorted(full_event_anchors, key=lambda row: row["decision_available_utc"])
    episodes: list[dict] = []
    snapshots: list[dict] = []
    outcomes: list[dict] = []
    rejections: list[dict] = []

    for cohort in cohort_rows:
        if cohort.get("event_family") not in origins:
            continue
        anchor_id = str(cohort.get("anchor_id") or "")
        ticker = str(cohort.get("ticker") or "")
        bars = option_bars_by_ticker.get(ticker)
        if not anchor_id or not ticker or not isinstance(bars, list):
            rejections.append({
                "anchor_id": anchor_id, "ticker": ticker,
                "reason": "OPTION_BAR_SOURCE_MISSING",
            })
            continue
        bars = sorted(bars, key=lambda bar: int(bar["t"]))
        option_by_t = {int(bar["t"]): (index, bar) for index, bar in enumerate(bars)}
        signal_ms = _ms(cohort["signal_bar_open_utc"])
        decision_ms = _ms(cohort["decision_available_utc"])
        if signal_ms not in option_by_t:
            rejections.append({
                "anchor_id": anchor_id, "ticker": ticker,
                "reason": "ENTRY_SIGNAL_BAR_ABSENT",
            })
            continue
        execution = option_by_t.get(decision_ms)
        if execution is None:
            rejections.append({
                "anchor_id": anchor_id, "ticker": ticker,
                "reason": "EXACT_NEXT_BAR_OPEN_ABSENT",
            })
            continue
        entry_option_index, entry_bar = execution
        entry_price = float(entry_bar["o"])
        if entry_price <= 0:
            rejections.append({
                "anchor_id": anchor_id, "ticker": ticker,
                "reason": "ENTRY_PRICE_INVALID",
            })
            continue
        if signal_ms not in under_by_t:
            rejections.append({
                "anchor_id": anchor_id, "ticker": ticker,
                "reason": "UNDERLYING_ENTRY_BAR_ABSENT",
            })
            continue

        episode_id = _episode_id(anchor_id, ticker)
        entry_decision = _dt(cohort["decision_available_utc"])
        expiry = datetime.fromisoformat(str(cohort["expiration"])).date()
        episode_end = min(
            entry_decision + timedelta(days=max_calendar_days),
            datetime.combine(expiry, datetime.max.time(), tzinfo=timezone.utc),
        )
        episodes.append({
            "episode_id": episode_id, "entry_anchor_id": anchor_id,
            "ticker": ticker, "contract_type": cohort.get("contract_type"),
            "strike": cohort.get("strike"), "expiration": cohort.get("expiration"),
            "dte_target": cohort.get("dte_target"),
            "moneyness_target": cohort.get("moneyness_target"),
            "partition": cohort.get("partition"),
            "entry_event_family": cohort.get("event_family"),
            "entry_signal_bar_open_utc": cohort.get("signal_bar_open_utc"),
            "entry_decision_available_utc": cohort.get("decision_available_utc"),
            "entry_execution_bar_open_utc": datetime.fromtimestamp(
                decision_ms / 1000, tz=timezone.utc,
            ).isoformat(),
            "entry_price": entry_price,
            "execution_status": "EXACT_NEXT_BAR_OPEN",
            "research_scope": "SIMULATED_LONG_PREMIUM_NO_COST_MODEL",
            "episode_end_utc": episode_end.isoformat(),
        })

        for sequence, anchor in enumerate(anchors, start=1):
            snapshot_decision = _dt(anchor["decision_available_utc"])
            if snapshot_decision <= entry_decision or snapshot_decision > episode_end:
                continue
            snapshot_signal_ms = _ms(anchor["signal_bar_open_utc"])
            if snapshot_signal_ms not in under_by_t:
                continue
            snapshot_option = option_by_t.get(snapshot_signal_ms)
            if snapshot_option is None:
                # No fill: absence is retained as a quality rejection rather
                # than moving the observation to a later option print.
                rejections.append({
                    "episode_id": episode_id,
                    "snapshot_signal_bar_open_utc": anchor["signal_bar_open_utc"],
                    "ticker": ticker, "reason": "SNAPSHOT_SIGNAL_BAR_ABSENT",
                })
                continue
            option_index, option_bar = snapshot_option
            current_premium = float(option_bar["c"])
            under_index = under_by_t[snapshot_signal_ms]
            causal = component_ledger(
                [bar for bar in bars if int(bar["t"]) <= snapshot_signal_ms],
                underlying_bars[:under_index + 1],
                contract_type=str(cohort["contract_type"]),
                strike=float(cohort["strike"]), expiration=str(cohort["expiration"]),
            )
            snapshot_id = f"{episode_id}:{snapshot_signal_ms}"
            base = {
                "snapshot_id": snapshot_id, "episode_id": episode_id,
                "entry_anchor_id": anchor_id, "ticker": ticker,
                "partition": cohort.get("partition"),
                "contract_type": cohort.get("contract_type"),
                "strike": cohort.get("strike"), "expiration": cohort.get("expiration"),
                "dte_target": cohort.get("dte_target"),
                "moneyness_target": cohort.get("moneyness_target"),
                "snapshot_sequence": sequence,
                "snapshot_event_family": anchor.get("event_family"),
                "snapshot_events": anchor.get("events"),
                "snapshot_signal_bar_open_utc": anchor.get("signal_bar_open_utc"),
                "snapshot_decision_available_utc": anchor.get("decision_available_utc"),
                "underlying_spot": anchor.get("spot"),
                "campaign_health": anchor.get("campaign_health"),
                "phase_confidence": anchor.get("phase_confidence"),
                "weakness_count": anchor.get("weakness_count"),
                "entry_price": entry_price, "current_premium": current_premium,
                "unrealized_pnl_pct": (current_premium / entry_price - 1.0) * 100.0,
                "held_underlying_bars": under_index - under_by_t[signal_ms],
                "navigation_scope": "MANAGE_OPEN_LONG_PREMIUM",
                "simulation_limitations": "NO_SPREAD_NO_FEES_NO_SLIPPAGE_NO_SIZE",
            }
            snapshots.append(dict(
                base,
                **{
                    f"contract__{field}": (
                        "|".join(causal.get(field, []))
                        if field == "quality_reasons" else causal.get(field)
                    )
                    for field in COMPONENT_FIELDS
                },
            ))

            for window, bars_forward in TIME_WINDOWS:
                desired_index = under_index + bars_forward
                cutoff_index = min(desired_index, len(underlying_bars) - 1)
                cutoff_ms = int(underlying_bars[cutoff_index]["t"])
                underlying_truncated = cutoff_index < desired_index
                expiry_before_cutoff = expiry < datetime.fromtimestamp(
                    cutoff_ms / 1000, tz=timezone.utc,
                ).date()
                censor_reason = (
                    "UNDERLYING_DATA_END" if underlying_truncated
                    else "CONTRACT_EXPIRY" if expiry_before_cutoff else None
                )
                try:
                    path = forward_long_premium_path_until(bars, option_index, cutoff_ms)
                    if path.get("observed_bars", 0) == 0:
                        outcome_status = "UNSCORED_NO_POST_SNAPSHOT_PRINT"
                    elif censor_reason:
                        outcome_status = "SCORED_RIGHT_CENSORED"
                    else:
                        outcome_status = "SCORED_WINDOW"
                except (ValueError, IndexError):
                    path = {}
                    outcome_status = "UNSCORED_INVALID_PATH"
                outcomes.append(dict(
                    {key: base[key] for key in (
                        "snapshot_id", "episode_id", "entry_anchor_id", "ticker",
                        "partition", "contract_type", "dte_target", "moneyness_target",
                        "snapshot_event_family", "snapshot_signal_bar_open_utc",
                        "snapshot_decision_available_utc",
                    )},
                    window=window, underlying_bars_forward=bars_forward,
                    cutoff_time_ms=cutoff_ms, censor_reason=censor_reason,
                    outcome_status=outcome_status,
                    **{field: path.get(field) for field in PATH_FIELDS},
                ))

    return {
        "episodes": episodes,
        "snapshots": snapshots,
        "outcomes": outcomes,
        "rejections": rejections,
    }
