"""Versioned multi-horizon research targets for Options DNA calibration.

All fields produced here are future-only.  They must never be merged into a
live component, guidance observation, webhook state, or Asset Page payload.
Only fully observed ``SCORED_WINDOW`` paths receive numeric calibration fields;
right-censored paths retain status metadata but cannot set a cutoff.
"""
from __future__ import annotations

from dataclasses import dataclass

from options_dna_calibration import OutcomeCondition, freeze_quantile_outcome


WINDOWS = ("H1", "D1", "D3", "D5", "D10")
PATH_FIELDS = (
    "mfe_pct", "mae_pct", "terminal_return_pct", "bars_to_peak",
    "bars_to_trough", "peak_to_terminal_giveback_pct", "gain_retention",
    "decision_close_mfe_pct", "decision_close_mae_pct",
)


@dataclass(frozen=True)
class TargetHypothesis:
    name: str
    purpose: str
    conditions: tuple[OutcomeCondition, ...]


# These are pre-data hypotheses, not validated navigation. Quantiles are
# resolved separately inside comparable discovery cells and then held fixed.
TARGET_HYPOTHESES_V1 = (
    TargetHypothesis(
        "EARLY_PREMIUM_CONFIRMATION",
        "Strong first-hour expression that remains constructive through D1.",
        (
            OutcomeCondition("H1__mfe_pct", ">=", 0.65),
            OutcomeCondition("H1__mae_pct", ">=", 0.35),
            OutcomeCondition("D1__terminal_return_pct", ">=", 0.50),
        ),
    ),
    TargetHypothesis(
        "CONFIRMATION_FAILURE",
        "Little early upside followed by adverse D1 premium path.",
        (
            OutcomeCondition("H1__mfe_pct", "<=", 0.35),
            OutcomeCondition("D1__mae_pct", "<=", 0.35),
            OutcomeCondition("D1__terminal_return_pct", "<=", 0.35),
        ),
    ),
    TargetHypothesis(
        "RETAINED_EXPANSION",
        "A D1 impulse whose premium remains retained through D3.",
        (
            OutcomeCondition("D1__mfe_pct", ">=", 0.65),
            OutcomeCondition("D3__gain_retention", ">=", 0.65),
            OutcomeCondition("D3__terminal_return_pct", ">=", 0.50),
        ),
    ),
    TargetHypothesis(
        "GIVEBACK_AFTER_EXPANSION",
        "A strong D1 impulse followed by material peak-to-D3 giveback.",
        (
            OutcomeCondition("D1__mfe_pct", ">=", 0.65),
            OutcomeCondition("D3__peak_to_terminal_giveback_pct", "<=", 0.35),
        ),
    ),
    TargetHypothesis(
        "PERSISTENT_PREMIUM_DAMAGE",
        "Weak terminal premium at both D3 and D5 rather than a brief cooldown.",
        (
            OutcomeCondition("D3__terminal_return_pct", "<=", 0.35),
            OutcomeCondition("D5__terminal_return_pct", "<=", 0.35),
            OutcomeCondition("D5__mae_pct", "<=", 0.35),
        ),
    ),
    TargetHypothesis(
        "RUNAWAY_CONTINUATION",
        "Rare extended path used to test when a peak is continuation, not exit.",
        (
            OutcomeCondition("D3__mfe_pct", ">=", 0.80),
            OutcomeCondition("D5__mfe_pct", ">=", 0.80),
            OutcomeCondition("D5__gain_retention", ">=", 0.65),
        ),
    ),
)


def _number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_matrix(
    window_rows: list[dict], *, identity_field: str, static_fields: tuple[str, ...],
) -> list[dict]:
    by_identity: dict[tuple[str, str], dict] = {}
    seen: set[tuple[str, str, str]] = set()
    prior_cutoff: dict[tuple[str, str], int] = {}
    order = {name: index for index, name in enumerate(WINDOWS)}
    for source in sorted(
        window_rows,
        key=lambda row: (
            str(row.get(identity_field)), str(row.get("ticker")),
            order.get(str(row.get("window")), 999),
        ),
    ):
        anchor_id, ticker, window = (
            str(source.get(identity_field, "")), str(source.get("ticker", "")),
            str(source.get("window", "")),
        )
        if not anchor_id or not ticker or window not in WINDOWS:
            raise ValueError("target row has invalid anchor/ticker/window identity")
        row_identity = (anchor_id, ticker, window)
        if row_identity in seen:
            raise ValueError(f"duplicate target window {row_identity!r}")
        seen.add(row_identity)
        identity = (anchor_id, ticker)
        cutoff = int(float(source.get("cutoff_time_ms") or 0))
        if cutoff and cutoff < prior_cutoff.get(identity, 0):
            raise ValueError(f"non-monotonic cutoff for {identity!r}")
        if cutoff:
            prior_cutoff[identity] = cutoff

        target = by_identity.setdefault(identity, {
            key: source.get(key) for key in static_fields
        })
        status = str(source.get("outcome_status") or "")
        target[f"{window}__status"] = status
        target[f"{window}__censor_reason"] = source.get("censor_reason")
        target[f"{window}__complete"] = status == "SCORED_WINDOW"
        target[f"{window}__observed_bars"] = source.get("observed_bars")
        target[f"{window}__cutoff_time_ms"] = source.get("cutoff_time_ms")
        for field in PATH_FIELDS:
            # Preserve the anti-censoring boundary directly in the matrix.
            target[f"{window}__{field}"] = (
                _number(source.get(field)) if status == "SCORED_WINDOW" else None
            )

    output = []
    for identity, row in sorted(by_identity.items()):
        present = {window for window in WINDOWS if f"{window}__status" in row}
        if present != set(WINDOWS):
            raise ValueError(f"incomplete target window set for {identity!r}: {sorted(present)!r}")
        output.append(row)
    return output


def build_window_target_matrix(window_rows: list[dict]) -> list[dict]:
    """Pivot one row per window into one future-only row per contract anchor."""
    return _build_matrix(
        window_rows, identity_field="anchor_id", static_fields=(
            "anchor_id", "ticker", "contract_type", "strike", "expiration",
            "dte_target", "moneyness_target", "partition", "event_family",
            "decision_available_utc", "signal_bar_open_utc", "moneyness_pct", "dte",
        ),
    )


def build_position_window_target_matrix(window_rows: list[dict]) -> list[dict]:
    """Pivot future paths for later same-contract position snapshots."""
    return _build_matrix(
        window_rows, identity_field="snapshot_id", static_fields=(
            "snapshot_id", "episode_id", "entry_anchor_id", "ticker",
            "partition", "contract_type", "dte_target", "moneyness_target",
            "snapshot_event_family", "snapshot_signal_bar_open_utc",
            "snapshot_decision_available_utc",
        ),
    )


def freeze_target_hypotheses(
    matrix_rows: list[dict], *, min_discovery_groups_per_cell: int = 20,
) -> list:
    """Freeze every v1 target definition on discovery-only complete paths."""
    return [
        freeze_quantile_outcome(
            matrix_rows, name=hypothesis.name,
            conditions=hypothesis.conditions,
            min_discovery_groups_per_cell=min_discovery_groups_per_cell,
        )
        for hypothesis in TARGET_HYPOTHESES_V1
    ]
