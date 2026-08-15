"""Promote historically robust candidates into a shadow-only advisory bundle."""
from __future__ import annotations

import hashlib
from pathlib import Path

from options_dna_guidance import (
    AdvisoryRule,
    CellEvidence,
    FrozenGuidanceBundle,
    RuleCondition,
    validate_bundle,
)
from options_dna_rule_search import CandidateValidation, CounterTargetAudit
from options_dna_rule_search import FrozenCandidate, SearchCondition


TARGET_LABELS = {
    ("EARLY_PREMIUM_CONFIRMATION", "OBSERVE_ENTRY"): "PREMIUM_CONFIRMING",
    ("CONFIRMATION_FAILURE", "OBSERVE_ENTRY"): "PREMIUM_NOT_CONFIRMING",
    ("RETAINED_EXPANSION", "OBSERVE_ENTRY"): "PREMIUM_CONFIRMING",
    ("CONFIRMATION_FAILURE", "MANAGE_OPEN_LONG_PREMIUM"): "PREMIUM_NOT_CONFIRMING",
    ("GIVEBACK_AFTER_EXPANSION", "MANAGE_OPEN_LONG_PREMIUM"): "MANAGE_ATTENTION",
    ("PERSISTENT_PREMIUM_DAMAGE", "MANAGE_OPEN_LONG_PREMIUM"): "PROTECT_ATTENTION",
    ("RUNAWAY_CONTINUATION", "MANAGE_OPEN_LONG_PREMIUM"): "PREMIUM_CONFIRMING",
}


def _manifest_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle_path(feature: str) -> str:
    root, separator, remainder = feature.partition("__")
    if not separator or root not in {"underlying", "contract", "catalyst", "position"}:
        raise ValueError(f"cannot map feature to bundle fact path: {feature}")
    return f"{root}.{remainder}"


def _label_for(validation: CandidateValidation) -> str:
    candidate = validation.candidate
    label = TARGET_LABELS[(candidate.target, candidate.scope)]
    if candidate.target == "EARLY_PREMIUM_CONFIRMATION" and any(
        condition.feature == "underlying__event_family"
        and condition.operator == "==" and condition.threshold == "ENTRY_FORMING"
        for condition in candidate.conditions
    ):
        return "ENTRY_WINDOW_FORMING"
    if candidate.target == "PERSISTENT_PREMIUM_DAMAGE" and any(
        condition.feature == "underlying__event_family"
        and condition.operator == "==" and condition.threshold == "THESIS_PRESSURE"
        for condition in candidate.conditions
    ):
        return "EXIT_RISK_ELEVATED"
    return label


def build_shadow_bundle(
    validations: list[CandidateValidation], counter_audits: list[CounterTargetAudit], *,
    source_manifest_path: str | Path, discovery_end_utc: str,
    holdout_start_utc: str, version: str = "options-dna-v1",
    max_discovery_rank: int = 3,
) -> FrozenGuidanceBundle:
    """Build an immutable shadow bundle from preregistered robust candidates."""
    audit_by_candidate: dict[str, list[CounterTargetAudit]] = {}
    for audit in counter_audits:
        audit_by_candidate.setdefault(audit.candidate_id, []).append(audit)
    promotable = []
    for validation in validations:
        candidate = validation.candidate
        audits = audit_by_candidate.get(candidate.candidate_id, [])
        if candidate.discovery_rank > max_discovery_rank:
            continue
        if validation.validation_status != "HOLDOUT_ROBUST_DIRECTION_PRESERVED":
            continue
        if not audits or any(audit.audit_status != "COUNTERTARGET_CLEAR" for audit in audits):
            continue
        promotable.append(validation)
    if not promotable:
        raise ValueError("no candidate passed robust holdout and countertarget gates")

    rules = []
    for validation in promotable:
        candidate = validation.candidate
        conditions = [
            RuleCondition(_bundle_path(condition.feature), condition.operator, condition.threshold)
            for condition in candidate.conditions
        ]
        conditions.extend((
            RuleCondition("contract.contract_type", "==", candidate.contract_type),
            RuleCondition("contract.dte_target", "==", int(candidate.dte_target)),
        ))
        rules.append(AdvisoryRule(
            rule_id=f"{candidate.candidate_id}-{candidate.target.lower()}",
            label=_label_for(validation), scope=candidate.scope,
            conditions=tuple(conditions),
            evidence=(CellEvidence(
                contract_type=candidate.contract_type,
                dte_target=int(candidate.dte_target),
                discovery_groups=candidate.discovery_groups,
                holdout_groups=validation.holdout_groups,
                discovery_lift=candidate.discovery_lift,
                holdout_lift=validation.holdout_lift,
            ),),
            rationale_code=candidate.target,
            priority=max(0, max_discovery_rank - candidate.discovery_rank + 1),
        ))
    bundle = FrozenGuidanceBundle(
        version=version, status="FROZEN_SHADOW_ONLY",
        source_manifest_sha256=_manifest_hash(Path(source_manifest_path)),
        discovery_end_utc=discovery_end_utc,
        holdout_start_utc=holdout_start_utc,
        required_cells=(("CALL", 14), ("CALL", 30), ("PUT", 14), ("PUT", 30)),
        rules=tuple(sorted(rules, key=lambda rule: rule.rule_id)),
    )
    validate_bundle(bundle)
    return bundle


def validation_from_dict(payload: dict) -> CandidateValidation:
    candidate_payload = payload["candidate"]
    candidate = FrozenCandidate(
        **{
            **candidate_payload,
            "conditions": tuple(
                SearchCondition(**condition) for condition in candidate_payload["conditions"]
            ),
        }
    )
    return CandidateValidation(**{**payload, "candidate": candidate})


def counter_audit_from_dict(payload: dict) -> CounterTargetAudit:
    return CounterTargetAudit(**payload)
