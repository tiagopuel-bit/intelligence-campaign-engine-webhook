"""Discovery-only transparent conjunction search for Options DNA research.

Candidates are selected and frozen using DISCOVERY only, then evaluated
unchanged on HOLDOUT.  The module emits validation records, not guidance rules
or orders.  Required evidence roots prevent catalyst/P&L-only direction claims.
"""
from __future__ import annotations

import hashlib
import itertools
import math
import random
from dataclasses import asdict, dataclass

from options_dna_calibration import InsufficientEvidence


@dataclass(frozen=True)
class NumericFeatureSpec:
    feature: str
    operators: tuple[str, ...]
    quantiles: tuple[float, ...] = (0.20, 0.35, 0.65, 0.80)


@dataclass(frozen=True)
class SearchCondition:
    feature: str
    operator: str
    threshold: object


@dataclass(frozen=True)
class FrozenCandidate:
    candidate_id: str
    target: str
    scope: str
    contract_type: str
    dte_target: str
    group_field: str
    discovery_rank: int
    conditions: tuple[SearchCondition, ...]
    discovery_groups: int
    discovery_triggered_groups: int
    discovery_precision: float
    discovery_recall: float
    discovery_coverage: float
    discovery_lift: float


@dataclass(frozen=True)
class CandidateValidation:
    candidate: FrozenCandidate
    holdout_groups: int
    holdout_triggered_groups: int
    holdout_precision: float
    holdout_recall: float
    holdout_coverage: float
    holdout_lift: float
    holdout_lift_ci_low: float
    holdout_lift_ci_high: float
    bootstrap_probability_lift_above_one: float
    validation_status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CounterTargetAudit:
    candidate_id: str
    target: str
    counter_target: str
    scope: str
    holdout_groups: int
    counter_triggered_groups: int
    counter_precision: float
    counter_lift: float
    audit_status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LiquiditySensitivityAudit:
    candidate_id: str
    target: str
    contract_type: str
    dte_target: str
    near_zero_fields: tuple[str, ...]
    audit_status: str

    def to_dict(self) -> dict:
        return asdict(self)


ENTRY_FEATURES = (
    NumericFeatureSpec("underlying__campaign_health", (">=", "<=")),
    NumericFeatureSpec("underlying__phase_confidence", (">=", "<=")),
    NumericFeatureSpec("underlying__weakness_count", (">=", "<=")),
    NumericFeatureSpec("contract__relative_response_z", (">=", "<=")),
    NumericFeatureSpec("contract__volume_ratio", (">=",)),
    NumericFeatureSpec("contract__range_expansion", (">=",)),
    NumericFeatureSpec("contract__close_location", (">=", "<=")),
    NumericFeatureSpec("contract__drawdown_from_high_pct", (">=", "<=")),
    NumericFeatureSpec("contract__activity_ratio", (">=",)),
)
POSITION_FEATURES = ENTRY_FEATURES + (
    NumericFeatureSpec("position__unrealized_pnl_pct", (">=", "<=")),
    NumericFeatureSpec("position__held_underlying_bars", (">=",)),
)
ALLOWED_EVENT_FAMILIES = (
    "ENTRY_FORMING", "CONTINUATION", "RISK_OR_EXHAUSTION", "THESIS_PRESSURE",
)


def _number(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _boolean(value: object) -> bool:
    if value is True or value == 1 or str(value).lower() == "true":
        return True
    if value is False or value == 0 or str(value).lower() == "false":
        return False
    raise ValueError(f"target is not boolean: {value!r}")


def _quantile(values: list[float], q: float) -> float:
    values = sorted(values)
    position = (len(values) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction


def _root(feature: str) -> str:
    return feature.split("__", 1)[0]


def _fires(row: dict, condition: SearchCondition) -> bool:
    actual = row.get(condition.feature)
    if condition.operator == "==":
        if isinstance(condition.threshold, bool):
            try:
                return _boolean(actual) is condition.threshold
            except ValueError:
                return False
        return actual is condition.threshold or actual == condition.threshold
    number = _number(actual)
    threshold = _number(condition.threshold)
    if number is None or threshold is None:
        return False
    return number >= threshold if condition.operator == ">=" else number <= threshold


def _metrics(rows: list[dict], *, target: str, group_field: str,
             conditions: tuple[SearchCondition, ...]) -> dict:
    group_counts: dict[str, int] = {}
    for row in rows:
        group = str(row[group_field])
        group_counts[group] = group_counts.get(group, 0) + 1
    weighted = [(row, 1.0 / group_counts[str(row[group_field])]) for row in rows]
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
    return {
        "groups": len(group_counts),
        "triggered_groups": len({str(row[group_field]) for row, _weight in triggered}),
        "precision": precision,
        "recall": true_weight / positive if positive else 0.0,
        "coverage": trigger_weight / total if total else 0.0,
        "lift": precision / base_rate if base_rate else 0.0,
    }


def _bootstrap_lift(
    rows: list[dict], *, target: str, group_field: str,
    conditions: tuple[SearchCondition, ...], seed_text: str,
    samples: int,
) -> tuple[float, float, float]:
    if samples < 100:
        raise ValueError("bootstrap samples must be at least 100")
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row[group_field]), []).append(row)
    keys = sorted(grouped)
    if not keys:
        return 0.0, 0.0, 0.0
    seed = int(hashlib.sha256(seed_text.encode("utf-8")).hexdigest()[:16], 16)
    rng = random.Random(seed)
    lifts = []
    for _ in range(samples):
        sampled = []
        for sample_index in range(len(keys)):
            source_key = keys[rng.randrange(len(keys))]
            for source in grouped[source_key]:
                row = dict(source)
                row["__bootstrap_group"] = f"B{sample_index}"
                sampled.append(row)
        lifts.append(_metrics(
            sampled, target=target, group_field="__bootstrap_group",
            conditions=conditions,
        )["lift"])
    lifts.sort()
    low = lifts[math.floor((samples - 1) * 0.10)]
    high = lifts[math.ceil((samples - 1) * 0.90)]
    probability = sum(value > 1.0 for value in lifts) / samples
    return low, high, probability


def _condition_pool(rows: list[dict], specs: tuple[NumericFeatureSpec, ...]) -> dict[str, list[SearchCondition]]:
    pool: dict[str, list[SearchCondition]] = {}
    for spec in specs:
        values = [_number(row.get(spec.feature)) for row in rows]
        clean = [value for value in values if value is not None]
        if not clean:
            continue
        thresholds = sorted({_quantile(clean, q) for q in spec.quantiles})
        pool[spec.feature] = [
            SearchCondition(spec.feature, operator, threshold)
            for operator in spec.operators for threshold in thresholds
        ]
    observed_families = {str(row.get("underlying__event_family")) for row in rows}
    families = [family for family in ALLOWED_EVENT_FAMILIES if family in observed_families]
    if families:
        pool["underlying__event_family"] = [
            SearchCondition("underlying__event_family", "==", family)
            for family in families
        ]
    return pool


def _candidate_id(target: str, scope: str, ctype: str, dte: str,
                  conditions: tuple[SearchCondition, ...]) -> str:
    def value_text(value: object) -> str:
        number = _number(value)
        return f"{number:.12g}" if number is not None else str(value)
    raw = "|".join([
        target, scope, ctype, dte,
        *(f"{c.feature}{c.operator}{value_text(c.threshold)}" for c in conditions),
    ])
    return "CAND-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def search_discovery_candidates(
    rows: list[dict], *, target: str, scope: str,
    group_field: str, feature_specs: tuple[NumericFeatureSpec, ...] | None = None,
    min_discovery_groups: int = 20, min_positive_groups: int = 5,
    min_trigger_groups: int = 5, max_per_cell: int = 20,
) -> list[FrozenCandidate]:
    """Freeze top discovery candidates per CALL/PUT × DTE cell."""
    if scope not in {"OBSERVE_ENTRY", "MANAGE_OPEN_LONG_PREMIUM"}:
        raise ValueError("unsupported scope")
    specs = feature_specs or (ENTRY_FEATURES if scope == "OBSERVE_ENTRY" else POSITION_FEATURES)
    required_roots = {"underlying", "contract"}
    if scope == "MANAGE_OPEN_LONG_PREMIUM":
        required_roots.add("position")
    candidates: list[FrozenCandidate] = []
    cells = sorted({
        (str(row.get("contract_type")), str(row.get("dte_target")))
        for row in rows if row.get("partition") == "DISCOVERY"
    })
    for ctype, dte in cells:
        discovery = [
            row for row in rows
            if row.get("partition") == "DISCOVERY"
            and str(row.get("contract_type")) == ctype
            and str(row.get("dte_target")) == dte
            and target in row and row.get(group_field) not in (None, "")
            and row.get(f"{target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        ]
        groups = {str(row[group_field]) for row in discovery}
        positive_groups = {str(row[group_field]) for row in discovery if _boolean(row[target])}
        if len(groups) < min_discovery_groups:
            raise InsufficientEvidence(
                f"{ctype}/{dte}: need {min_discovery_groups} discovery groups; found {len(groups)}"
            )
        if len(positive_groups) < min_positive_groups:
            raise InsufficientEvidence(
                f"{ctype}/{dte}: need {min_positive_groups} positive groups; found {len(positive_groups)}"
            )
        pool = _condition_pool(discovery, specs)
        by_root: dict[str, list[SearchCondition]] = {}
        for feature, conditions in pool.items():
            by_root.setdefault(_root(feature), []).extend(conditions)
        if any(root not in by_root for root in required_roots):
            raise InsufficientEvidence(f"{ctype}/{dte}: required causal feature root missing")

        base_sets = itertools.product(*(by_root[root] for root in sorted(required_roots)))
        scored = []
        for base in base_sets:
            if len({condition.feature for condition in base}) != len(base):
                continue
            variants = [tuple(sorted(base, key=lambda item: item.feature))]
            # Catalyst is an optional urgency/context modifier. It is never a
            # required directional root and is not inferred from outcomes.
            if any("catalyst__active" in row for row in discovery):
                variants.extend(
                    tuple(sorted((*base, SearchCondition("catalyst__active", "==", active)),
                                 key=lambda item: item.feature))
                    for active in (True, False)
                )
            for conditions in variants:
                metric = _metrics(
                    discovery, target=target, group_field=group_field,
                    conditions=conditions,
                )
                if metric["triggered_groups"] < min_trigger_groups:
                    continue
                scored.append((conditions, metric))
        scored.sort(key=lambda item: (
            -item[1]["lift"], -item[1]["precision"], -item[1]["recall"],
            -item[1]["coverage"], repr(item[0]),
        ))
        seen_signatures = set()
        for conditions, metric in scored:
            signature = tuple((c.feature, c.operator) for c in conditions)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            candidates.append(FrozenCandidate(
                candidate_id=_candidate_id(target, scope, ctype, dte, conditions),
                target=target, scope=scope, contract_type=ctype, dte_target=dte,
                group_field=group_field, discovery_rank=len(seen_signatures),
                conditions=conditions,
                discovery_groups=len(groups),
                discovery_triggered_groups=metric["triggered_groups"],
                discovery_precision=metric["precision"],
                discovery_recall=metric["recall"],
                discovery_coverage=metric["coverage"],
                discovery_lift=metric["lift"],
            ))
            if len(seen_signatures) >= max_per_cell:
                break
    return candidates


def evaluate_frozen_candidates(
    candidates: list[FrozenCandidate], rows: list[dict], *,
    min_holdout_groups: int = 10, min_trigger_groups: int = 3,
    bootstrap_samples: int = 1000,
) -> list[CandidateValidation]:
    """Evaluate the discovery-selected candidate list unchanged on HOLDOUT."""
    validations = []
    for candidate in candidates:
        holdout = [
            row for row in rows
            if row.get("partition") == "HOLDOUT"
            and str(row.get("contract_type")) == candidate.contract_type
            and str(row.get("dte_target")) == candidate.dte_target
            and candidate.target in row and row.get(candidate.group_field) not in (None, "")
            and row.get(f"{candidate.target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        ]
        groups = {str(row[candidate.group_field]) for row in holdout}
        if len(groups) < min_holdout_groups:
            raise InsufficientEvidence(
                f"{candidate.contract_type}/{candidate.dte_target}: need "
                f"{min_holdout_groups} holdout groups; found {len(groups)}"
            )
        metric = _metrics(
            holdout, target=candidate.target, group_field=candidate.group_field,
            conditions=candidate.conditions,
        )
        lift_low, lift_high, lift_probability = _bootstrap_lift(
            holdout, target=candidate.target, group_field=candidate.group_field,
            conditions=candidate.conditions, seed_text=candidate.candidate_id,
            samples=bootstrap_samples,
        )
        status = (
            "HOLDOUT_ROBUST_DIRECTION_PRESERVED"
            if candidate.discovery_lift > 1.0 and metric["lift"] > 1.0
            and metric["triggered_groups"] >= min_trigger_groups
            and lift_low > 1.0
            else "HOLDOUT_REJECTED"
        )
        validations.append(CandidateValidation(
            candidate=candidate, holdout_groups=len(groups),
            holdout_triggered_groups=metric["triggered_groups"],
            holdout_precision=metric["precision"], holdout_recall=metric["recall"],
            holdout_coverage=metric["coverage"], holdout_lift=metric["lift"],
            holdout_lift_ci_low=lift_low, holdout_lift_ci_high=lift_high,
            bootstrap_probability_lift_above_one=lift_probability,
            validation_status=status,
        ))
    return validations


def audit_counter_targets(
    validations: list[CandidateValidation], rows: list[dict], *,
    counter_targets: dict[str, tuple[str, ...]], min_holdout_groups: int = 10,
) -> list[CounterTargetAudit]:
    """Reject ambiguous candidates that also enrich an opposing future path."""
    audits: list[CounterTargetAudit] = []
    for validation in validations:
        candidate = validation.candidate
        for counter_target in counter_targets.get(candidate.target, ()):
            holdout = [
                row for row in rows
                if row.get("partition") == "HOLDOUT"
                and str(row.get("contract_type")) == candidate.contract_type
                and str(row.get("dte_target")) == candidate.dte_target
                and row.get(f"{counter_target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
                and row.get(candidate.group_field) not in (None, "")
            ]
            groups = {str(row[candidate.group_field]) for row in holdout}
            if len(groups) < min_holdout_groups:
                audits.append(CounterTargetAudit(
                    candidate.candidate_id, candidate.target, counter_target,
                    candidate.scope, len(groups), 0, 0.0, 0.0,
                    "INSUFFICIENT_COUNTERTARGET_COVERAGE",
                ))
                continue
            metric = _metrics(
                holdout, target=counter_target, group_field=candidate.group_field,
                conditions=candidate.conditions,
            )
            clear = (
                validation.validation_status == "HOLDOUT_ROBUST_DIRECTION_PRESERVED"
                and metric["lift"] <= 1.0
                and metric["precision"] < validation.holdout_precision
            )
            audits.append(CounterTargetAudit(
                candidate.candidate_id, candidate.target, counter_target,
                candidate.scope, len(groups), metric["triggered_groups"],
                metric["precision"], metric["lift"],
                "COUNTERTARGET_CLEAR" if clear else "AMBIGUOUS_COUNTERTARGET_REJECTED",
            ))
    return audits


def audit_liquidity_sensitivity(
    candidates: list[FrozenCandidate], definitions: dict[str, dict], *,
    epsilon: float = 1e-9,
) -> list[LiquiditySensitivityAudit]:
    """Flag candidates whose frozen target cutoff is zero in their cell.

    A frozen DISCOVERY quantile cutoff equal to zero means the outcome condition
    fires for an unchanged print — no movement, which for a sparse contract is
    liquidity, not confirmation. A candidate predicting such a target in such a
    cell is liquidity-sensitive and is labeled, never silently treated as
    meaningful confirmation.
    """
    audits: list[LiquiditySensitivityAudit] = []
    for candidate in candidates:
        definition = definitions.get(candidate.target)
        near_zero: tuple[str, ...] = ()
        if definition is not None:
            for cell in definition.get("cells", []):
                if tuple(cell.get("cell_values", [])) != (
                    candidate.contract_type, candidate.dte_target, "0.0",
                ):
                    continue
                near_zero = tuple(
                    str(cutoff.get("field")) for cutoff in cell.get("cutoffs", [])
                    if abs(float(cutoff.get("threshold"))) <= epsilon
                )
                break
        audits.append(LiquiditySensitivityAudit(
            candidate_id=candidate.candidate_id, target=candidate.target,
            contract_type=candidate.contract_type, dte_target=candidate.dte_target,
            near_zero_fields=near_zero,
            audit_status="LIQUIDITY_SENSITIVE" if near_zero else "ACTIVE_PRINT_SUPPORTED",
        ))
    return audits


# --- Checkpoint B correction: causal active-print sensitivity ----------------

def _active_print(row: dict) -> bool:
    """True when the contract actually moved: a non-zero close-to-close return.

    A zero (or missing) return is an unchanged/zero-return print — the premium
    did not move, which for a sparse contract is liquidity rather than
    confirmation. Volume is deliberately not the discriminator here: every
    eligible signal bar records volume, so only the return captures whether the
    contract actually responded.
    """
    ret = _number(row.get("contract__option_return"))
    return ret is not None and abs(ret) > 1e-9


@dataclass(frozen=True)
class ActivePrintCellSummary:
    target: str
    partition: str
    contract_type: str
    dte_target: str
    scored_groups: int
    positive_groups: int
    base_rate: float | None
    rows: int
    unchanged_print_rows: int
    unchanged_print_incidence: float | None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ActivePrintAudit:
    candidate_id: str
    target: str
    contract_type: str
    dte_target: str
    discovery_active_groups: int
    holdout_active_groups: int
    holdout_active_triggered_groups: int
    full_holdout_lift: float
    active_holdout_lift: float | None
    zero_cutoff_fields: tuple[str, ...]
    audit_status: str

    def to_dict(self) -> dict:
        return asdict(self)


def active_print_cell_summary(
    rows: list[dict], targets: tuple[str, ...], *, group_field: str = "anchor_id",
) -> list[ActivePrintCellSummary]:
    """Publish partition × contract-cell base rates and unchanged-print incidence."""
    summaries: list[ActivePrintCellSummary] = []
    for target in targets:
        for partition in ("DISCOVERY", "HOLDOUT"):
            cells = sorted({
                (str(row.get("contract_type")), str(row.get("dte_target")))
                for row in rows if row.get("partition") == partition
            })
            for ctype, dte in cells:
                cell_rows = [
                    row for row in rows
                    if row.get("partition") == partition
                    and str(row.get("contract_type")) == ctype
                    and str(row.get("dte_target")) == dte
                    and row.get(f"{target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
                ]
                if not cell_rows:
                    continue
                scored = {str(row[group_field]) for row in cell_rows}
                positive = {str(row[group_field]) for row in cell_rows if _boolean(row.get(target))}
                unchanged = sum(1 for row in cell_rows if not _active_print(row))
                summaries.append(ActivePrintCellSummary(
                    target=target, partition=partition, contract_type=ctype, dte_target=dte,
                    scored_groups=len(scored), positive_groups=len(positive),
                    base_rate=(len(positive) / len(scored)) if scored else None,
                    rows=len(cell_rows), unchanged_print_rows=unchanged,
                    unchanged_print_incidence=(unchanged / len(cell_rows)) if cell_rows else None,
                ))
    return summaries


def audit_active_print_sensitivity(
    candidates: list[FrozenCandidate], rows: list[dict], *,
    validations_by_id: dict[str, "CandidateValidation"] | None = None,
    definitions: dict[str, dict] | None = None,
    group_field: str = "anchor_id", min_discovery_groups: int = 20,
    min_holdout_groups: int = 10, min_trigger_groups: int = 3,
) -> list[ActivePrintAudit]:
    """Re-evaluate each candidate on a deterministic active-print slice.

    A candidate only survives as ACTIVE_PRINT_SUPPORTED when its apparent
    enrichment persists on the active-print slice and that slice still meets the
    frozen group/trigger minima. Otherwise it is LIQUIDITY_SENSITIVE (enrichment
    disappears once inactive prints are removed) or
    INSUFFICIENT_ACTIVE_PRINT_COVERAGE (too few active groups to judge).
    """
    definitions = definitions or {}
    audits: list[ActivePrintAudit] = []
    for candidate in candidates:
        discovery = [
            row for row in rows
            if row.get("partition") == "DISCOVERY"
            and str(row.get("contract_type")) == candidate.contract_type
            and str(row.get("dte_target")) == candidate.dte_target
            and row.get(f"{candidate.target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        ]
        holdout = [
            row for row in rows
            if row.get("partition") == "HOLDOUT"
            and str(row.get("contract_type")) == candidate.contract_type
            and str(row.get("dte_target")) == candidate.dte_target
            and row.get(f"{candidate.target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
        ]
        discovery_active = [row for row in discovery if _active_print(row)]
        holdout_active = [row for row in holdout if _active_print(row)]
        discovery_active_groups = {str(row[group_field]) for row in discovery_active}
        holdout_active_groups = {str(row[group_field]) for row in holdout_active}
        holdout_active_triggered = {
            str(row[group_field]) for row in holdout_active
            if all(_fires(row, condition) for condition in candidate.conditions)
        }

        zero_fields: tuple[str, ...] = ()
        definition = definitions.get(candidate.target)
        if definition is not None:
            for cell in definition.get("cells", []):
                if tuple(cell.get("cell_values", [])) != (
                    candidate.contract_type, candidate.dte_target, "0.0",
                ):
                    continue
                zero_fields = tuple(
                    str(cutoff.get("field")) for cutoff in cell.get("cutoffs", [])
                    if abs(float(cutoff.get("threshold"))) <= 1e-9
                )
                break

        validation = (validations_by_id or {}).get(candidate.candidate_id)
        full_holdout_lift = validation.holdout_lift if validation is not None else 0.0

        if (len(discovery_active_groups) < min_discovery_groups
                or len(holdout_active_groups) < min_holdout_groups
                or len(holdout_active_triggered) < min_trigger_groups):
            status = "INSUFFICIENT_ACTIVE_PRINT_COVERAGE"
            active_lift = None
        else:
            metric = _metrics(
                holdout_active, target=candidate.target, group_field=group_field,
                conditions=candidate.conditions,
            )
            active_lift = metric["lift"]
            status = "ACTIVE_PRINT_SUPPORTED" if active_lift > 1.0 else "LIQUIDITY_SENSITIVE"

        audits.append(ActivePrintAudit(
            candidate_id=candidate.candidate_id, target=candidate.target,
            contract_type=candidate.contract_type, dte_target=candidate.dte_target,
            discovery_active_groups=len(discovery_active_groups),
            holdout_active_groups=len(holdout_active_groups),
            holdout_active_triggered_groups=len(holdout_active_triggered),
            full_holdout_lift=full_holdout_lift,
            active_holdout_lift=active_lift,
            zero_cutoff_fields=zero_fields,
            audit_status=status,
        ))
    return audits


def _triggered_fingerprint(rows: list[dict], conditions: tuple[SearchCondition, ...],
                           group_field: str, partition: str) -> frozenset[str]:
    return frozenset(
        str(row[group_field]) for row in rows
        if row.get("partition") == partition
        and all(_fires(row, condition) for condition in conditions)
    )


def collapse_by_triggered_fingerprint(
    candidates: list[FrozenCandidate], rows: list[dict], *, group_field: str = "anchor_id",
) -> dict[tuple[object, ...], list[FrozenCandidate]]:
    """Group candidates by cell-scoped triggered independent-anchor fingerprints.

    The fingerprint is scoped to the candidate's exact contract type, DTE and
    target, and only counts scored rows (SCORED_FROZEN_DISCOVERY_CUTOFFS). The
    collapse key includes the cell identity so two candidates that fire on the
    same anchors in different cells or targets remain distinct signal families.
    """
    families: dict[tuple[object, ...], list[FrozenCandidate]] = {}
    for candidate in candidates:
        def fingerprint(partition: str) -> frozenset[str]:
            return frozenset(
                str(row[group_field]) for row in rows
                if row.get("partition") == partition
                and str(row.get("contract_type")) == candidate.contract_type
                and str(row.get("dte_target")) == candidate.dte_target
                and row.get(f"{candidate.target}_status") == "SCORED_FROZEN_DISCOVERY_CUTOFFS"
                and all(_fires(row, condition) for condition in candidate.conditions)
            )
        key = (
            candidate.target, candidate.contract_type, candidate.dte_target,
            fingerprint("DISCOVERY"), fingerprint("HOLDOUT"),
        )
        families.setdefault(key, []).append(candidate)
    return families


def reject_tautological_candidates(
    candidates: list[FrozenCandidate], rows: list[dict], *, group_field: str = "anchor_id",
) -> list[FrozenCandidate]:
    """Reject candidates whose contract condition provides no discrimination.

    A required evidence root must change which anchors fire. Over bars where the
    contract feature is actually defined, removing a tautological contract
    condition (e.g. close_location <= 1, close_location >= 0, range_expansion
    >= 0) leaves the same triggered discovery groups, so it cannot satisfy the
    contract-evidence requirement.
    """
    rejected: list[FrozenCandidate] = []
    for candidate in candidates:
        contract_conditions = [c for c in candidate.conditions if _root(c.feature) == "contract"]
        if not contract_conditions:
            continue
        discovery = [
            row for row in rows
            if row.get("partition") == "DISCOVERY"
            and str(row.get("contract_type")) == candidate.contract_type
            and str(row.get("dte_target")) == candidate.dte_target
        ]
        for contract in contract_conditions:
            defined = [row for row in discovery if _number(row.get(contract.feature)) is not None]
            if not defined:
                continue
            base = {str(row[group_field]) for row in defined if all(_fires(row, c) for c in candidate.conditions)}
            without = [c for c in candidate.conditions if c.feature != contract.feature]
            without_triggered = {str(row[group_field]) for row in defined if all(_fires(row, c) for c in without)}
            if without_triggered == base:
                rejected.append(candidate)
                break
    return rejected
