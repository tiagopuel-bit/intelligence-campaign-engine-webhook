"""Frozen advisory-rule bundles for Options DNA shadow evaluation.

Rules are transparent conjunctions over causal facts. This module cannot fit a
rule, read future outcomes, or issue an order. Production use is intentionally
out of scope; accepted bundles are shadow-only until separately promoted.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path


ALLOWED_LABELS = {
    "ENTRY_WINDOW_FORMING",
    "PREMIUM_CONFIRMING",
    "PREMIUM_NOT_CONFIRMING",
    "MANAGE_ATTENTION",
    "PROTECT_ATTENTION",
    "EXIT_RISK_ELEVATED",
}
ALLOWED_SCOPES = {"OBSERVE_ENTRY", "MANAGE_OPEN_LONG_PREMIUM", "BOTH"}
ALLOWED_OPERATORS = {"==", "!=", ">=", "<=", "in", "not_in", "is_true", "is_false"}
ALLOWED_ROOTS = {"underlying", "contract", "catalyst", "position"}
FUTURE_TOKENS = {
    "mfe", "mae", "terminal_return", "bars_to_peak", "bars_to_trough",
    "peak_before_trough", "giveback", "gain_retention", "next_bar_open",
    "decision_to_next_open_gap",
}
IMPERATIVE_TOKENS = {"BUY", "SELL", "CLOSE", "ROLL", "EXERCISE"}
LABEL_SCOPE_RULES = {
    "ENTRY_WINDOW_FORMING": {"OBSERVE_ENTRY"},
    "PREMIUM_CONFIRMING": {"OBSERVE_ENTRY", "MANAGE_OPEN_LONG_PREMIUM", "BOTH"},
    "PREMIUM_NOT_CONFIRMING": {"OBSERVE_ENTRY", "MANAGE_OPEN_LONG_PREMIUM", "BOTH"},
    "MANAGE_ATTENTION": {"MANAGE_OPEN_LONG_PREMIUM"},
    "PROTECT_ATTENTION": {"MANAGE_OPEN_LONG_PREMIUM"},
    "EXIT_RISK_ELEVATED": {"MANAGE_OPEN_LONG_PREMIUM"},
}
LABEL_PRECEDENCE = {
    "EXIT_RISK_ELEVATED": 60,
    "PROTECT_ATTENTION": 50,
    "MANAGE_ATTENTION": 40,
    "PREMIUM_NOT_CONFIRMING": 30,
    "ENTRY_WINDOW_FORMING": 20,
    "PREMIUM_CONFIRMING": 10,
}


class InvalidCalibrationBundle(ValueError):
    pass


@dataclass(frozen=True)
class RuleCondition:
    path: str
    operator: str
    value: object = None


@dataclass(frozen=True)
class CellEvidence:
    contract_type: str
    dte_target: int
    discovery_groups: int
    holdout_groups: int
    discovery_lift: float
    holdout_lift: float


@dataclass(frozen=True)
class AdvisoryRule:
    rule_id: str
    label: str
    scope: str
    conditions: tuple[RuleCondition, ...]
    evidence: tuple[CellEvidence, ...]
    rationale_code: str
    priority: int = 0


@dataclass(frozen=True)
class FrozenGuidanceBundle:
    version: str
    status: str
    source_manifest_sha256: str
    discovery_end_utc: str
    holdout_start_utc: str
    required_cells: tuple[tuple[str, int], ...]
    rules: tuple[AdvisoryRule, ...]

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def bundle_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _finite(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def validate_bundle(
    bundle: FrozenGuidanceBundle, *, min_discovery_groups: int = 20,
    min_holdout_groups: int = 10,
) -> None:
    if bundle.status != "FROZEN_SHADOW_ONLY":
        raise InvalidCalibrationBundle("bundle status must be FROZEN_SHADOW_ONLY")
    if not bundle.version or not bundle.source_manifest_sha256:
        raise InvalidCalibrationBundle("version and source manifest hash are required")
    if len(bundle.source_manifest_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in bundle.source_manifest_sha256.lower()
    ):
        raise InvalidCalibrationBundle("source manifest hash must be SHA-256 hex")
    if bundle.discovery_end_utc >= bundle.holdout_start_utc:
        raise InvalidCalibrationBundle("discovery must end before holdout starts")
    if not bundle.rules:
        raise InvalidCalibrationBundle("bundle must contain at least one rule")
    required_cells = set(bundle.required_cells)
    if not required_cells or any(
        contract_type not in {"CALL", "PUT"} or dte not in {14, 30}
        for contract_type, dte in required_cells
    ):
        raise InvalidCalibrationBundle("required contract cells are invalid")
    rule_ids: set[str] = set()
    for rule in bundle.rules:
        if not rule.rule_id or rule.rule_id in rule_ids:
            raise InvalidCalibrationBundle("rule IDs must be non-empty and unique")
        rule_ids.add(rule.rule_id)
        if rule.label not in ALLOWED_LABELS:
            raise InvalidCalibrationBundle(f"unsupported advisory label: {rule.label}")
        if any(token in rule.label.upper().split("_") for token in IMPERATIVE_TOKENS):
            raise InvalidCalibrationBundle("imperative order language is prohibited")
        if rule.scope not in ALLOWED_SCOPES:
            raise InvalidCalibrationBundle(f"unsupported rule scope: {rule.scope}")
        if rule.scope not in LABEL_SCOPE_RULES[rule.label]:
            raise InvalidCalibrationBundle(
                f"label {rule.label} is incompatible with scope {rule.scope}"
            )
        if not rule.conditions:
            raise InvalidCalibrationBundle(f"rule {rule.rule_id} has no conditions")
        causal_roots = set()
        for condition in rule.conditions:
            root, separator, _remainder = condition.path.partition(".")
            if not separator or root not in ALLOWED_ROOTS:
                raise InvalidCalibrationBundle(f"unsupported fact path: {condition.path}")
            lower_path = condition.path.lower()
            if any(token in lower_path for token in FUTURE_TOKENS):
                raise InvalidCalibrationBundle(f"future outcome path prohibited: {condition.path}")
            if condition.operator not in ALLOWED_OPERATORS:
                raise InvalidCalibrationBundle(f"unsupported operator: {condition.operator}")
            causal_roots.add(root)
        if not causal_roots.intersection({"underlying", "contract"}):
            raise InvalidCalibrationBundle(
                f"rule {rule.rule_id} cannot infer direction from catalyst/position alone"
            )
        if not rule.evidence:
            raise InvalidCalibrationBundle(f"rule {rule.rule_id} has no cell evidence")
        type_filter = None
        dte_filter = None
        for condition in rule.conditions:
            values = (
                set(condition.value) if condition.operator == "in" and isinstance(condition.value, (list, tuple, set))
                else {condition.value} if condition.operator == "==" else None
            )
            if condition.path == "contract.contract_type" and values is not None:
                type_filter = {str(value).upper() for value in values}
            if condition.path == "contract.dte_target" and values is not None:
                dte_filter = {int(value) for value in values}
        applicable_cells = {
            cell for cell in required_cells
            if (type_filter is None or cell[0] in type_filter)
            and (dte_filter is None or cell[1] in dte_filter)
        }
        evidence_cells = {(item.contract_type, item.dte_target) for item in rule.evidence}
        missing_cells = applicable_cells - evidence_cells
        if missing_cells:
            raise InvalidCalibrationBundle(
                f"rule {rule.rule_id} lacks validation evidence for {sorted(missing_cells)!r}"
            )
        for evidence in rule.evidence:
            if evidence.contract_type not in {"CALL", "PUT"} or evidence.dte_target not in {14, 30}:
                raise InvalidCalibrationBundle("unsupported validation cell")
            if evidence.discovery_groups < min_discovery_groups:
                raise InvalidCalibrationBundle("discovery cell minimum not met")
            if evidence.holdout_groups < min_holdout_groups:
                raise InvalidCalibrationBundle("holdout cell minimum not met")
            if not (_finite(evidence.discovery_lift) and _finite(evidence.holdout_lift)):
                raise InvalidCalibrationBundle("cell lift must be finite")
            if evidence.discovery_lift <= 1.0 or evidence.holdout_lift <= 1.0:
                raise InvalidCalibrationBundle("rule direction did not preserve positive lift")


def _resolve(facts: dict, path: str) -> object:
    value: object = facts
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _matches(actual: object, condition: RuleCondition) -> bool:
    operator = condition.operator
    expected = condition.value
    if operator == "is_true":
        return actual is True
    if operator == "is_false":
        return actual is False
    if operator == "==":
        return actual == expected
    if operator == "!=":
        return actual != expected
    if operator == "in":
        return actual in expected if isinstance(expected, (tuple, list, set)) else False
    if operator == "not_in":
        return actual not in expected if isinstance(expected, (tuple, list, set)) else False
    if not (_finite(actual) and _finite(expected)):
        return False
    return float(actual) >= float(expected) if operator == ">=" else float(actual) <= float(expected)


def apply_shadow_bundle(observation: dict, bundle: FrozenGuidanceBundle) -> dict:
    """Return candidate advisory labels only when every shadow gate is valid."""
    validate_bundle(bundle)
    result = dict(observation)
    result["candidate_labels"] = []
    result["bundle_hash"] = bundle.bundle_hash
    if observation.get("gate") != "READY_FOR_SHADOW_RULES":
        result["rule_evaluation_status"] = "SKIPPED_OBSERVATION_GATE"
        return result
    if observation.get("calibration_version") != bundle.version:
        result["rule_evaluation_status"] = "SKIPPED_VERSION_MISMATCH"
        return result

    facts = observation.get("facts") or {}
    position_scope = observation.get("navigation_scope")
    matched = []
    for rule in sorted(bundle.rules, key=lambda item: (-item.priority, item.rule_id)):
        if rule.scope != "BOTH" and rule.scope != position_scope:
            continue
        if all(_matches(_resolve(facts, condition.path), condition) for condition in rule.conditions):
            matched.append({
                "label": rule.label,
                "rule_id": rule.rule_id,
                "rationale_code": rule.rationale_code,
                "scope": rule.scope,
                "priority": rule.priority,
                "evidence_paths": [condition.path for condition in rule.conditions],
            })
    result["candidate_labels"] = matched
    result["primary_advisory"] = (
        max(
            matched,
            key=lambda item: (LABEL_PRECEDENCE[item["label"]], item["priority"], item["rule_id"]),
        )
        if matched else None
    )
    result["rule_evaluation_status"] = "EVALUATED_SHADOW_ONLY"
    return result


def bundle_from_dict(payload: dict) -> FrozenGuidanceBundle:
    """Rebuild and validate a frozen bundle from a JSON-compatible object."""
    try:
        rules = tuple(
            AdvisoryRule(
                rule_id=row["rule_id"],
                label=row["label"],
                scope=row["scope"],
                conditions=tuple(RuleCondition(**condition) for condition in row["conditions"]),
                evidence=tuple(CellEvidence(**evidence) for evidence in row["evidence"]),
                rationale_code=row["rationale_code"],
                priority=int(row.get("priority", 0)),
            )
            for row in payload["rules"]
        )
        bundle = FrozenGuidanceBundle(
            version=payload["version"],
            status=payload["status"],
            source_manifest_sha256=payload["source_manifest_sha256"],
            discovery_end_utc=payload["discovery_end_utc"],
            holdout_start_utc=payload["holdout_start_utc"],
            required_cells=tuple(
                (str(contract_type), int(dte))
                for contract_type, dte in payload["required_cells"]
            ),
            rules=rules,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCalibrationBundle(f"invalid bundle payload: {exc}") from None
    validate_bundle(bundle)
    return bundle


def write_bundle(path: str | Path, bundle: FrozenGuidanceBundle) -> None:
    validate_bundle(bundle)
    payload = {"bundle": bundle.to_dict(), "bundle_hash": bundle.bundle_hash}
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_bundle(path: str | Path) -> FrozenGuidanceBundle:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        bundle = bundle_from_dict(payload["bundle"])
        expected_hash = payload["bundle_hash"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise InvalidCalibrationBundle(f"cannot read bundle: {exc}") from None
    if bundle.bundle_hash != expected_hash:
        raise InvalidCalibrationBundle("bundle content hash mismatch")
    return bundle
