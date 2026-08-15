"""Multi-asset external replication evaluation for the frozen AMC entry finding.

Evaluates the frozen CALL/14 ``CONFIRMATION_FAILURE`` candidate and its four
pre-registered controls against assembled per-asset ledgers, then reports
per-asset and asset-balanced pooled results against the frozen acceptance
gates. No thresholds are fit and no outcome is read during selection: this
module only evaluates a rule that was frozen before any replication outcome.

Rows are assembled ledger rows (``contract__*`` / ``underlying__*`` features)
already labeled by ``apply_frozen_outcome`` with the AMC-frozen target cutoffs.
"""
from __future__ import annotations

import hashlib
import math
import random
from dataclasses import asdict, dataclass

from options_dna_rule_search import (
    SearchCondition,
    _active_print,
    _boolean,
    _number,
)

TARGET = "CONFIRMATION_FAILURE"
COUNTERTARGET = "EARLY_PREMIUM_CONFIRMATION"
CONTRACT_TYPE = "CALL"
DTE_TARGET = "14"
SCORED_STATUS = "SCORED_FROZEN_DISCOVERY_CUTOFFS"

FROZEN_CONDITIONS = (
    SearchCondition("contract__close_location", "<=", 0.33333333333333354),
    SearchCondition("underlying__campaign_health", "<=", 31.600000000000005),
)

CONTROLS = (
    ("unconditional_cell_base_rate", ()),
    ("active_print_only_base_rate", ()),
    (
        "underlying_only",
        (SearchCondition("underlying__campaign_health", "<=", 31.600000000000005),),
    ),
    (
        "contract_only",
        (SearchCondition("contract__close_location", "<=", 0.33333333333333354),),
    ),
)


@dataclass(frozen=True)
class RuleMetric:
    groups: int
    triggered_groups: int
    base_rate: float
    precision: float
    recall: float
    coverage: float
    lift: float

    def to_dict(self) -> dict:
        return asdict(self)


def _fires(row: dict, condition: SearchCondition) -> bool:
    actual = row.get(condition.feature)
    number = _number(actual)
    threshold = _number(condition.threshold)
    if number is None or threshold is None:
        return False
    return number >= threshold if condition.operator == ">=" else number <= threshold


def _metric(rows: list[dict], *, target: str, group_field: str,
            conditions: tuple[SearchCondition, ...]) -> RuleMetric:
    counts: dict[str, int] = {}
    for row in rows:
        group = str(row[group_field])
        counts[group] = counts.get(group, 0) + 1
    weighted = [(row, 1.0 / counts[str(row[group_field])]) for row in rows]
    total = sum(weight for _row, weight in weighted)
    positive = sum(weight for row, weight in weighted if _boolean(row[target]))
    triggered = [
        (row, weight) for row, weight in weighted
        if all(_fires(row, condition) for condition in conditions)
    ]
    trigger_weight = sum(weight for _row, weight in triggered)
    true_weight = sum(weight for row, weight in triggered if _boolean(row[target]))
    base_rate = positive / total if total else 0.0
    precision = true_weight / trigger_weight if trigger_weight else 0.0
    return RuleMetric(
        groups=len(counts),
        triggered_groups=len({str(row[group_field]) for row, _weight in triggered}),
        base_rate=base_rate,
        precision=precision,
        recall=true_weight / positive if positive else 0.0,
        coverage=trigger_weight / total if total else 0.0,
        lift=precision / base_rate if base_rate else 0.0,
    )


def _scored(rows: list[dict], *, target: str, partition: str | None = None) -> list[dict]:
    return [
        row for row in rows
        if row.get("contract_type") == CONTRACT_TYPE
        and str(row.get("dte_target")) == DTE_TARGET
        and row.get(f"{target}_status") == SCORED_STATUS
        and (partition is None or row.get("partition") == partition)
    ]


def _symbol(row: dict) -> str:
    return str(row.get("symbol") or row.get("ticker") or "")


@dataclass(frozen=True)
class AssetResult:
    symbol: str
    discovery_scored_groups: int
    holdout_scored_groups: int
    holdout_active_triggered_groups: int
    holdout_positive_groups: int
    holdout_candidate: RuleMetric
    holdout_active_candidate: RuleMetric | None
    controls: dict[str, RuleMetric]
    direction_preserved: bool
    active_direction_preserved: bool
    control_superior: bool
    counter_clear: bool
    asset_passes: bool

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["holdout_active_candidate"] = (
            self.holdout_active_candidate.to_dict()
            if self.holdout_active_candidate else None
        )
        return payload


def _asset_balanced(*metrics: RuleMetric) -> dict:
    present = [m for m in metrics if m is not None]
    if not present:
        return {"base_rate": 0.0, "precision": 0.0, "lift": 0.0,
                "coverage": 0.0, "groups": 0, "triggered_groups": 0}
    base_rate = sum(m.base_rate for m in present) / len(present)
    precision = sum(m.precision for m in present) / len(present)
    return {
        "base_rate": base_rate,
        "precision": precision,
        "lift": precision / base_rate if base_rate else 0.0,
        "coverage": sum(m.coverage for m in present) / len(present),
        "groups": sum(m.groups for m in present),
        "triggered_groups": sum(m.triggered_groups for m in present),
    }


def evaluate_replication(
    rows: list[dict], *, symbols: tuple[str, ...],
    group_field: str = "anchor_id",
    min_discovery_groups: int = 20,
    min_holdout_groups: int = 10,
    min_active_trigger_groups: int = 3,
    min_positive_holdout: int = 2,
    max_single_asset_weight: float = 0.4,
    min_assets_with_direction: int = 5,
    bootstrap_samples: int = 1000,
) -> dict:
    """Evaluate the frozen candidate + controls per asset and pooled."""
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        by_symbol.setdefault(_symbol(row), []).append(row)

    asset_results: dict[str, AssetResult] = {}
    for symbol in symbols:
        asset_rows = by_symbol.get(symbol, [])
        discovery = _scored(asset_rows, target=TARGET, partition="DISCOVERY")
        holdout = _scored(asset_rows, target=TARGET, partition="HOLDOUT")
        holdout_active = [row for row in holdout if _active_print(row)]

        discovery_groups = {str(row[group_field]) for row in discovery}
        holdout_groups = {str(row[group_field]) for row in holdout}

        holdout_candidate = _metric(
            holdout, target=TARGET, group_field=group_field, conditions=FROZEN_CONDITIONS,
        )
        holdout_active_candidate = _metric(
            holdout_active, target=TARGET, group_field=group_field, conditions=FROZEN_CONDITIONS,
        ) if holdout_active else None

        active_triggered = {
            str(row[group_field]) for row in holdout_active
            if all(_fires(row, condition) for condition in FROZEN_CONDITIONS)
        }
        positive_groups = {
            str(row[group_field]) for row in holdout if _boolean(row[TARGET])
        }

        controls: dict[str, RuleMetric] = {}
        for name, conditions in CONTROLS:
            scope = holdout_active if name == "active_print_only_base_rate" else holdout
            controls[name] = _metric(
                scope, target=TARGET, group_field=group_field, conditions=conditions,
            )

        direction_preserved = (
            len(holdout_groups) >= min_holdout_groups
            and holdout_candidate.lift > 1.0
        )
        active_direction_preserved = bool(
            holdout_active_candidate and holdout_active_candidate.lift > 1.0
        )
        control_superior = (
            holdout_candidate.lift > controls["underlying_only"].lift
            and holdout_candidate.lift > controls["contract_only"].lift
            and holdout_candidate.precision > controls["underlying_only"].precision
            and holdout_candidate.precision > controls["contract_only"].precision
            and holdout_candidate.lift > controls["unconditional_cell_base_rate"].lift
        )

        counter_holdout = _scored(asset_rows, target=COUNTERTARGET, partition="HOLDOUT")
        counter = _metric(
            counter_holdout, target=COUNTERTARGET, group_field=group_field,
            conditions=FROZEN_CONDITIONS,
        )
        counter_clear = (
            counter.lift <= 1.0 and counter.precision < holdout_candidate.precision
        )

        asset_passes = (
            len(discovery_groups) >= min_discovery_groups
            and len(holdout_groups) >= min_holdout_groups
            and len(active_triggered) >= min_active_trigger_groups
            and len(positive_groups) >= min_positive_holdout
            and direction_preserved
            and active_direction_preserved
            and control_superior
            and counter_clear
        )
        asset_results[symbol] = AssetResult(
            symbol=symbol,
            discovery_scored_groups=len(discovery_groups),
            holdout_scored_groups=len(holdout_groups),
            holdout_active_triggered_groups=len(active_triggered),
            holdout_positive_groups=len(positive_groups),
            holdout_candidate=holdout_candidate,
            holdout_active_candidate=holdout_active_candidate,
            controls=controls,
            direction_preserved=direction_preserved,
            active_direction_preserved=active_direction_preserved,
            control_superior=control_superior,
            counter_clear=counter_clear,
            asset_passes=asset_passes,
        )

    passing_assets = [s for s in symbols if asset_results[s].asset_passes]
    per_asset_direction = sum(
        1 for s in symbols if asset_results[s].direction_preserved
    )

    holdout_by_symbol: dict[str, list[dict]] = {}
    for symbol in symbols:
        holdout_by_symbol[symbol] = _scored(
            by_symbol.get(symbol, []), target=TARGET, partition="HOLDOUT",
        )
    active_by_symbol = {
        symbol: [row for row in holdout_by_symbol[symbol] if _active_print(row)]
        for symbol in symbols
    }
    candidate_metrics = {
        symbol: _metric(rows_, target=TARGET, group_field=group_field,
                        conditions=FROZEN_CONDITIONS)
        for symbol, rows_ in holdout_by_symbol.items()
    }
    active_candidate_metrics = {
        symbol: _metric(rows_, target=TARGET, group_field=group_field,
                        conditions=FROZEN_CONDITIONS)
        for symbol, rows_ in active_by_symbol.items() if rows_
    }
    pooled = _asset_balanced(*candidate_metrics.values())
    pooled_active = _asset_balanced(*active_candidate_metrics.values())

    lift_ci = _asset_cluster_bootstrap_lift(
        candidate_metrics, symbols=symbols, seed_text="options_dna_replication_pooled",
        samples=bootstrap_samples,
    )

    weights = {s: 1.0 / len(symbols) for s in symbols}
    max_weight = max(weights.values())

    pooled_pass = (
        per_asset_direction >= min_assets_with_direction
        and max_weight <= max_single_asset_weight
        and lift_ci[0] > 1.0
        and pooled["lift"] > 1.0
    )
    promotion_forbidden = len(passing_assets) < math.ceil(len(symbols) / 2)

    return {
        "target": TARGET,
        "countertarget": COUNTERTARGET,
        "contract_type": CONTRACT_TYPE,
        "dte_target": DTE_TARGET,
        "assets": list(symbols),
        "per_asset": {s: asset_results[s].to_dict() for s in symbols},
        "passing_assets": passing_assets,
        "assets_with_direction": per_asset_direction,
        "pooled": pooled,
        "pooled_active_print": pooled_active,
        "pooled_lift_ci": {"low": lift_ci[0], "high": lift_ci[1],
                           "prob_above_one": lift_ci[2]},
        "max_single_asset_weight": max_weight,
        "pooled_pass": pooled_pass,
        "promotion_forbidden": promotion_forbidden,
        "replication_status": (
            "EXTERNAL_REPLICATION_PASS"
            if pooled_pass and not promotion_forbidden
            else "EXTERNAL_REPLICATION_NOT_CONFIRMED"
        ),
    }


def _apply_cutoffs(matrix_row: dict, cutoffs: tuple[tuple[str, str, float], ...],
                   target: str) -> tuple[bool | None, str]:
    if any(field not in matrix_row for field, _op, _thr in cutoffs):
        return None, "UNSCORED_MISSING_CELL"
    values: dict[str, float] = {}
    for field, _operator, _threshold in cutoffs:
        value = _number(matrix_row.get(field))
        if value is None:
            return None, "UNSCORED_MISSING_VALUE"
        values[field] = value
    label = all(
        values[field] >= threshold if operator == ">=" else values[field] <= threshold
        for field, operator, threshold in cutoffs
    )
    return label, SCORED_STATUS


def build_replication_rows(
    cohort_rows: list[dict], component_rows: list[dict],
    target_matrix_rows: list[dict],
    target_cutoffs: dict[str, tuple[tuple[str, str, float], ...]],
) -> list[dict]:
    """Join cohort + component + frozen target labels into evaluation rows."""
    component_by = {str(row.get("anchor_id")): row for row in component_rows}
    target_by = {str(row.get("anchor_id")): row for row in target_matrix_rows}
    rows: list[dict] = []
    for cohort in cohort_rows:
        anchor = str(cohort.get("anchor_id") or "")
        component = component_by.get(anchor)
        target_row = target_by.get(anchor)
        if component is None or target_row is None:
            continue
        row = {
            "symbol": cohort.get("symbol") or cohort.get("ticker"),
            "anchor_id": anchor,
            "partition": cohort.get("partition"),
            "contract_type": cohort.get("contract_type"),
            "dte_target": str(cohort.get("dte_target")),
            "underlying__campaign_health": _number(cohort.get("campaign_health")),
            "underlying__event_family": cohort.get("event_family"),
            "contract__close_location": _number(component.get("close_location")),
            "contract__option_return": _number(component.get("option_return")),
        }
        for target, cutoffs in target_cutoffs.items():
            label, status = _apply_cutoffs(target_row, cutoffs, target)
            row[target] = label
            row[f"{target}_status"] = status
        rows.append(row)
    return rows


def _asset_cluster_bootstrap_lift(
    metrics_by_symbol: dict[str, RuleMetric], *, symbols: tuple[str, ...],
    seed_text: str, samples: int,
) -> tuple[float, float, float]:
    if samples < 100:
        raise ValueError("bootstrap samples must be at least 100")
    if not metrics_by_symbol:
        return 0.0, 0.0, 0.0
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    lifts: list[float] = []
    for _ in range(samples):
        sampled = [metrics_by_symbol[rng.choice(symbols)] for _ in symbols]
        lifts.append(_asset_balanced(*sampled)["lift"])
    lifts.sort()
    low = lifts[math.floor((samples - 1) * 0.10)]
    high = lifts[math.ceil((samples - 1) * 0.90)]
    probability = sum(value > 1.0 for value in lifts) / samples
    return low, high, probability
