"""Audited causal/future joins for Options DNA calibration only.

The returned ``joined`` rows deliberately contain future targets and therefore
must never cross into shadow observations, webhook state, or the Asset Page.
The companion ``causal`` rows are checked for future-field leakage first.
"""
from __future__ import annotations

from options_dna_calibration import apply_frozen_outcome
from options_dna_targets import TARGET_HYPOTHESES_V1, freeze_target_hypotheses


FUTURE_FRAGMENTS = (
    "mfe", "mae", "terminal_return", "bars_to_peak", "bars_to_trough",
    "peak_before_trough", "giveback", "gain_retention", "next_bar_open",
    "decision_to_next_open_gap", "cutoff_time",
)
REQUIRED_CELLS = {("CALL", "14", "0.0"), ("CALL", "30", "0.0"),
                  ("PUT", "14", "0.0"), ("PUT", "30", "0.0")}


def _truthy(value: object) -> bool:
    return value is True or value == 1 or str(value).strip().lower() in {"true", "yes", "1"}


def _unique(rows: list[dict], fields: tuple[str, ...], label: str) -> dict[tuple, dict]:
    output = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in fields)
        if any(not value for value in key):
            raise ValueError(f"{label} has incomplete identity {key!r}")
        if key in output:
            raise ValueError(f"duplicate {label} identity {key!r}")
        output[key] = row
    return output


def _assert_causal(row: dict) -> None:
    leaked = sorted(
        field for field in row
        if any(fragment in field.lower() for fragment in FUTURE_FRAGMENTS)
    )
    if leaked:
        raise ValueError(f"future fields in causal calibration row: {leaked!r}")


def _catalyst_index(rows: list[dict], *, mode: str) -> dict[tuple, dict]:
    selected = [row for row in rows if row.get("mode") == mode]
    return _unique(selected, ("anchor_id",), f"{mode} catalyst")


def build_entry_calibration_dataset(
    cohort_rows: list[dict], component_rows: list[dict], target_rows: list[dict],
    catalyst_rows: list[dict], *, catalyst_mode: str = "PUBLIC_ACCEPTANCE",
) -> dict:
    """Join isolated-entry causal facts to future targets with strict identity."""
    components = _unique(component_rows, ("anchor_id", "ticker"), "component")
    targets = _unique(target_rows, ("anchor_id", "ticker"), "entry target")
    catalysts = _catalyst_index(catalyst_rows, mode=catalyst_mode)
    causal_rows, future_rows, joined_rows = [], [], []
    for cohort in cohort_rows:
        key = (str(cohort.get("anchor_id", "")), str(cohort.get("ticker", "")))
        if key not in components or key not in targets:
            raise ValueError(f"entry calibration dependency missing for {key!r}")
        catalyst = catalysts.get((key[0],))
        if catalyst is None or catalyst.get("source_status") == "SOURCE_UNAVAILABLE":
            raise ValueError(f"covered catalyst context missing for anchor {key[0]}")
        component = components[key]
        causal = {
            "anchor_id": key[0], "ticker": key[1],
            "partition": cohort.get("partition"),
            "contract_type": cohort.get("contract_type"),
            "dte_target": str(cohort.get("dte_target")),
            "moneyness_target": str(cohort.get("moneyness_target")),
            "decision_available_utc": cohort.get("decision_available_utc"),
            "navigation_scope": "OBSERVE_ENTRY",
            "calibration_eligible": (
                _truthy(component.get("ready"))
                and _truthy(component.get("signal_bar_exists", True))
            ),
            "underlying__event_family": cohort.get("event_family"),
            "underlying__events": cohort.get("events"),
            "underlying__campaign_health": cohort.get("campaign_health"),
            "underlying__phase_confidence": cohort.get("phase_confidence"),
            "underlying__weakness_count": cohort.get("weakness_count"),
            **{
                f"contract__{field}": value for field, value in component.items()
                if field not in {
                    "anchor_id", "ticker", "partition", "contract_type", "dte_target",
                    "moneyness_target", "decision_available_utc", "signal_bar_open_utc",
                }
            },
            **{
                f"catalyst__{field}": value for field, value in catalyst.items()
                if field not in {"anchor_id", "partition", "event_family"}
            },
        }
        _assert_causal(causal)
        future = dict(targets[key])
        causal_rows.append(causal)
        future_rows.append(future)
        joined_rows.append(dict(causal, **future, research_only_future_joined=True))
    return {"causal": causal_rows, "future": future_rows, "joined": joined_rows}


def build_position_calibration_dataset(
    snapshot_rows: list[dict], target_rows: list[dict], catalyst_rows: list[dict],
    *, catalyst_mode: str = "PUBLIC_ACCEPTANCE",
) -> dict:
    """Join same-contract causal position snapshots to future targets."""
    targets = _unique(target_rows, ("snapshot_id",), "position target")
    catalysts = _catalyst_index(catalyst_rows, mode=catalyst_mode)
    causal_rows, future_rows, joined_rows = [], [], []
    for snapshot in snapshot_rows:
        snapshot_id = str(snapshot.get("snapshot_id", ""))
        if (snapshot_id,) not in targets or (snapshot_id,) not in catalysts:
            raise ValueError(f"position calibration dependency missing for {snapshot_id!r}")
        catalyst = catalysts[(snapshot_id,)]
        if catalyst.get("source_status") == "SOURCE_UNAVAILABLE":
            raise ValueError(f"covered catalyst context missing for snapshot {snapshot_id}")
        causal = {
            "snapshot_id": snapshot_id,
            "anchor_id": snapshot_id,
            "episode_id": snapshot.get("episode_id"),
            "ticker": snapshot.get("ticker"), "partition": snapshot.get("partition"),
            "contract_type": snapshot.get("contract_type"),
            "dte_target": str(snapshot.get("dte_target")),
            "moneyness_target": str(snapshot.get("moneyness_target")),
            "decision_available_utc": snapshot.get("snapshot_decision_available_utc"),
            "navigation_scope": "MANAGE_OPEN_LONG_PREMIUM",
            "calibration_eligible": _truthy(snapshot.get("contract__ready")),
            "underlying__event_family": snapshot.get("snapshot_event_family"),
            "underlying__events": snapshot.get("snapshot_events"),
            "underlying__spot": snapshot.get("underlying_spot"),
            "underlying__campaign_health": snapshot.get("campaign_health"),
            "underlying__phase_confidence": snapshot.get("phase_confidence"),
            "underlying__weakness_count": snapshot.get("weakness_count"),
            "position__entry_price": snapshot.get("entry_price"),
            "position__current_premium": snapshot.get("current_premium"),
            "position__unrealized_pnl_pct": snapshot.get("unrealized_pnl_pct"),
            "position__held_underlying_bars": snapshot.get("held_underlying_bars"),
            **{
                field: value for field, value in snapshot.items()
                if field.startswith("contract__")
            },
            **{
                f"catalyst__{field}": value for field, value in catalyst.items()
                if field not in {"anchor_id", "partition", "event_family"}
            },
        }
        _assert_causal(causal)
        future = dict(targets[(snapshot_id,)])
        causal_rows.append(causal)
        future_rows.append(future)
        joined_rows.append(dict(causal, **future, research_only_future_joined=True))
    return {"causal": causal_rows, "future": future_rows, "joined": joined_rows}


def freeze_and_apply_v1_targets(
    entry_joined_rows: list[dict], position_joined_rows: list[dict], *,
    min_discovery_groups_per_cell: int = 20,
) -> dict:
    """Freeze on independent entry anchors; apply unchanged to position rows."""
    definitions = freeze_target_hypotheses(
        entry_joined_rows,
        min_discovery_groups_per_cell=min_discovery_groups_per_cell,
    )
    for definition in definitions:
        cells = {
            tuple(str(value) for value in cell.cell_values)
            for cell in definition.cells
        }
        missing = REQUIRED_CELLS - cells
        if missing:
            raise ValueError(f"target {definition.name} missing frozen cells {sorted(missing)!r}")
    entry_labeled = [dict(row) for row in entry_joined_rows]
    position_labeled = [dict(row) for row in position_joined_rows]
    for definition in definitions:
        entry_labeled = apply_frozen_outcome(definition, entry_labeled)
        position_labeled = apply_frozen_outcome(definition, position_labeled)
    return {
        "definitions": definitions,
        "entry_labeled": entry_labeled,
        "position_labeled": position_labeled,
        "hypothesis_names": [item.name for item in TARGET_HYPOTHESES_V1],
    }
