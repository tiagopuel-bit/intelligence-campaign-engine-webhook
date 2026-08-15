"""Leakage-resistant outcome and threshold calibration for Options DNA research.

This module fits transparent one-feature rules on DISCOVERY rows only. It is
not a live guidance engine and intentionally contains no default HOT, WEAK, or
EXIT thresholds. Rows sharing an underlying anchor receive equal total weight
so one market event cannot dominate because more contracts were sampled.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass


class InsufficientEvidence(ValueError):
    """Independent-anchor coverage is too small to calibrate honestly."""


@dataclass(frozen=True)
class ThresholdRule:
    target: str
    feature: str
    operator: str
    threshold: float
    discovery_groups: int
    triggered_groups: int
    weighted_precision: float
    weighted_recall: float
    weighted_coverage: float
    lift: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class OutcomeCondition:
    """One discovery-quantile condition in a future-path outcome label."""

    field: str
    operator: str
    quantile: float


@dataclass(frozen=True)
class FrozenOutcomeCutoff:
    field: str
    operator: str
    quantile: float
    threshold: float


@dataclass(frozen=True)
class FrozenOutcomeCell:
    cell_values: tuple[object, ...]
    discovery_groups: int
    cutoffs: tuple[FrozenOutcomeCutoff, ...]


@dataclass(frozen=True)
class FrozenOutcomeDefinition:
    """Outcome semantics frozen on DISCOVERY and reusable unchanged on HOLDOUT."""

    name: str
    source_partition: str
    cell_fields: tuple[str, ...]
    group_field: str
    cells: tuple[FrozenOutcomeCell, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _finite(value: object) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, str):
        try:
            return math.isfinite(float(value.strip()))
        except (TypeError, ValueError):
            return False
    return False


def _label(value: object) -> bool:
    if value is True or value == 1:
        return True
    if value is False or value == 0:
        return False
    raise ValueError(f"target must be boolean/0/1, got {value!r}")


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty values")
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _weighted_rows(rows: list[dict], group_field: str) -> list[tuple[dict, float]]:
    counts: dict[str, int] = {}
    for row in rows:
        group = str(row[group_field])
        counts[group] = counts.get(group, 0) + 1
    return [(row, 1.0 / counts[str(row[group_field])]) for row in rows]


def _fires(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == "<=":
        return value <= threshold
    raise ValueError(f"operator must be >= or <=, got {operator!r}")


def freeze_quantile_outcome(
    rows: list[dict], *, name: str, conditions: tuple[OutcomeCondition, ...],
    cell_fields: tuple[str, ...] = ("contract_type", "dte_target", "moneyness_target"),
    group_field: str = "anchor_id", min_discovery_groups_per_cell: int = 20,
) -> FrozenOutcomeDefinition:
    """Freeze path-outcome cutoffs using DISCOVERY rows only.

    Cells keep CALL/PUT and maturity/moneyness regimes comparable. Exactly one
    row per independent anchor and cell is required; otherwise a denser contract
    sample could silently influence the outcome definition.
    """
    if not name:
        raise ValueError("outcome name is required")
    if not conditions:
        raise ValueError("at least one outcome condition is required")
    for condition in conditions:
        if condition.operator not in (">=", "<="):
            raise ValueError(f"operator must be >= or <=, got {condition.operator!r}")
        if not 0.0 <= condition.quantile <= 1.0:
            raise ValueError(f"quantile must be within [0, 1], got {condition.quantile!r}")

    discovery = [row for row in rows if row.get("partition") == "DISCOVERY"]
    by_cell: dict[tuple[object, ...], list[dict]] = {}
    for row in discovery:
        required = (*cell_fields, group_field, *(condition.field for condition in conditions))
        if any(field not in row for field in required):
            continue
        if any(not _finite(row[condition.field]) for condition in conditions):
            continue
        cell = tuple(row[field] for field in cell_fields)
        by_cell.setdefault(cell, []).append(row)
    if not by_cell:
        raise InsufficientEvidence("no usable discovery outcome cells")

    frozen_cells: list[FrozenOutcomeCell] = []
    for cell, cell_rows in sorted(by_cell.items(), key=lambda item: repr(item[0])):
        groups = [str(row[group_field]) for row in cell_rows]
        if len(groups) != len(set(groups)):
            raise ValueError(
                f"duplicate {group_field} within outcome cell {cell!r}; aggregate or select "
                "one contract before freezing"
            )
        if len(groups) < min_discovery_groups_per_cell:
            raise InsufficientEvidence(
                f"need {min_discovery_groups_per_cell} independent discovery anchors in "
                f"outcome cell {cell!r}; found {len(groups)}"
            )
        cutoffs = tuple(
            FrozenOutcomeCutoff(
                field=condition.field,
                operator=condition.operator,
                quantile=condition.quantile,
                threshold=_quantile(
                    [float(row[condition.field]) for row in cell_rows], condition.quantile
                ),
            )
            for condition in conditions
        )
        frozen_cells.append(FrozenOutcomeCell(
            cell_values=cell,
            discovery_groups=len(groups),
            cutoffs=cutoffs,
        ))
    return FrozenOutcomeDefinition(
        name=name,
        source_partition="DISCOVERY",
        cell_fields=cell_fields,
        group_field=group_field,
        cells=tuple(frozen_cells),
    )


def apply_frozen_outcome(
    definition: FrozenOutcomeDefinition, rows: list[dict],
) -> list[dict]:
    """Apply immutable discovery cutoffs; absent cells/values remain explicit."""
    cell_lookup = {cell.cell_values: cell for cell in definition.cells}
    labeled: list[dict] = []
    for source in rows:
        row = dict(source)
        if any(field not in row for field in definition.cell_fields):
            row[definition.name] = None
            row[f"{definition.name}_status"] = "UNSCORED_MISSING_CELL"
            labeled.append(row)
            continue
        cell_key = tuple(row[field] for field in definition.cell_fields)
        cell = cell_lookup.get(cell_key)
        if cell is None:
            row[definition.name] = None
            row[f"{definition.name}_status"] = "UNSCORED_UNFROZEN_CELL"
            labeled.append(row)
            continue
        if any(cutoff.field not in row or not _finite(row[cutoff.field]) for cutoff in cell.cutoffs):
            row[definition.name] = None
            row[f"{definition.name}_status"] = "UNSCORED_MISSING_VALUE"
            labeled.append(row)
            continue
        row[definition.name] = all(
            _fires(float(row[cutoff.field]), cutoff.operator, cutoff.threshold)
            for cutoff in cell.cutoffs
        )
        row[f"{definition.name}_status"] = "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        labeled.append(row)
    return labeled


def _metrics(
    rows: list[dict], *, target: str, feature: str, operator: str,
    threshold: float, group_field: str,
) -> dict:
    weighted = _weighted_rows(rows, group_field)
    total = sum(weight for _row, weight in weighted)
    positives = sum(weight for row, weight in weighted if _label(row[target]))
    triggered = [
        (row, weight) for row, weight in weighted
        if _fires(float(row[feature]), operator, threshold)
    ]
    trigger_weight = sum(weight for _row, weight in triggered)
    true_weight = sum(weight for row, weight in triggered if _label(row[target]))
    base_rate = positives / total if total else 0.0
    precision = true_weight / trigger_weight if trigger_weight else 0.0
    return {
        "precision": precision,
        "recall": true_weight / positives if positives else 0.0,
        "coverage": trigger_weight / total if total else 0.0,
        "lift": precision / base_rate if base_rate else 0.0,
        "triggered_groups": len({str(row[group_field]) for row, _weight in triggered}),
    }


def fit_threshold_rules(
    rows: list[dict], *, target: str, features: tuple[str, ...],
    group_field: str = "anchor_id", min_discovery_groups: int = 20,
    min_positive_groups: int = 5, min_trigger_groups: int = 5,
    quantiles: tuple[float, ...] = (0.20, 0.35, 0.50, 0.65, 0.80),
) -> list[ThresholdRule]:
    """Fit candidates on discovery only; holdout values are never read."""
    discovery = [row for row in rows if row.get("partition") == "DISCOVERY"]
    groups = {str(row[group_field]) for row in discovery}
    positive_groups = {str(row[group_field]) for row in discovery if _label(row[target])}
    if len(groups) < min_discovery_groups:
        raise InsufficientEvidence(
            f"need {min_discovery_groups} independent discovery anchors; found {len(groups)}"
        )
    if len(positive_groups) < min_positive_groups:
        raise InsufficientEvidence(
            f"need {min_positive_groups} positive discovery anchors; found {len(positive_groups)}"
        )

    rules: list[ThresholdRule] = []
    for feature in features:
        usable = [
            row for row in discovery
            if feature in row and _finite(row[feature]) and target in row and group_field in row
        ]
        if len({str(row[group_field]) for row in usable}) < min_discovery_groups:
            continue
        thresholds = sorted({_quantile([float(row[feature]) for row in usable], q) for q in quantiles})
        for operator in (">=", "<="):
            candidates = []
            for threshold in thresholds:
                metric = _metrics(
                    usable, target=target, feature=feature, operator=operator,
                    threshold=threshold, group_field=group_field,
                )
                if metric["triggered_groups"] >= min_trigger_groups:
                    candidates.append((threshold, metric))
            if not candidates:
                continue
            threshold, metric = max(
                candidates,
                key=lambda item: (
                    item[1]["lift"], item[1]["precision"], item[1]["recall"],
                    item[1]["coverage"], -abs(item[0]),
                ),
            )
            rules.append(ThresholdRule(
                target=target,
                feature=feature,
                operator=operator,
                threshold=threshold,
                discovery_groups=len(groups),
                triggered_groups=metric["triggered_groups"],
                weighted_precision=metric["precision"],
                weighted_recall=metric["recall"],
                weighted_coverage=metric["coverage"],
                lift=metric["lift"],
            ))
    return sorted(rules, key=lambda r: (-r.lift, -r.weighted_precision, r.feature, r.operator))


def evaluate_frozen_rule(
    rule: ThresholdRule, rows: list[dict], *, group_field: str = "anchor_id",
    min_holdout_groups: int = 10,
) -> dict:
    """Evaluate a frozen rule on holdout without selecting a new cutoff."""
    holdout = [
        row for row in rows
        if row.get("partition") == "HOLDOUT"
        and rule.feature in row and _finite(row[rule.feature])
    ]
    groups = {str(row[group_field]) for row in holdout}
    if len(groups) < min_holdout_groups:
        raise InsufficientEvidence(
            f"need {min_holdout_groups} independent holdout anchors; found {len(groups)}"
        )
    metric = _metrics(
        holdout, target=rule.target, feature=rule.feature,
        operator=rule.operator, threshold=rule.threshold, group_field=group_field,
    )
    return {
        "target": rule.target,
        "feature": rule.feature,
        "operator": rule.operator,
        "threshold": rule.threshold,
        "holdout_groups": len(groups),
        "triggered_groups": metric["triggered_groups"],
        "weighted_precision": metric["precision"],
        "weighted_recall": metric["recall"],
        "weighted_coverage": metric["coverage"],
        "lift": metric["lift"],
    }
