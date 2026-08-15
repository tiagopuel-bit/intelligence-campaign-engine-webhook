"""Historical candidate-rule stage after immutable target freezing."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from options_dna_calibration import InsufficientEvidence
from options_dna_rule_search import (
    active_print_cell_summary,
    audit_active_print_sensitivity,
    audit_counter_targets,
    audit_liquidity_sensitivity,
    collapse_by_triggered_fingerprint,
    evaluate_frozen_candidates,
    reject_tautological_candidates,
    search_discovery_candidates,
)


class RuleStageBlocked(RuntimeError):
    pass


ENTRY_TARGET_SEARCH_PLAN = (
    ("EARLY_PREMIUM_CONFIRMATION", "OBSERVE_ENTRY", "anchor_id"),
    ("CONFIRMATION_FAILURE", "OBSERVE_ENTRY", "anchor_id"),
    ("RETAINED_EXPANSION", "OBSERVE_ENTRY", "anchor_id"),
)
ENTRY_COUNTER_TARGETS = {
    "EARLY_PREMIUM_CONFIRMATION": ("CONFIRMATION_FAILURE",),
    "CONFIRMATION_FAILURE": ("EARLY_PREMIUM_CONFIRMATION",),
    "RETAINED_EXPANSION": ("CONFIRMATION_FAILURE",),
}


TARGET_SEARCH_PLAN = (
    ("EARLY_PREMIUM_CONFIRMATION", "OBSERVE_ENTRY", "anchor_id"),
    ("CONFIRMATION_FAILURE", "OBSERVE_ENTRY", "anchor_id"),
    ("RETAINED_EXPANSION", "OBSERVE_ENTRY", "anchor_id"),
    ("CONFIRMATION_FAILURE", "MANAGE_OPEN_LONG_PREMIUM", "episode_id"),
    ("GIVEBACK_AFTER_EXPANSION", "MANAGE_OPEN_LONG_PREMIUM", "episode_id"),
    ("PERSISTENT_PREMIUM_DAMAGE", "MANAGE_OPEN_LONG_PREMIUM", "episode_id"),
    ("RUNAWAY_CONTINUATION", "MANAGE_OPEN_LONG_PREMIUM", "episode_id"),
)
COUNTER_TARGETS = {
    "EARLY_PREMIUM_CONFIRMATION": ("CONFIRMATION_FAILURE",),
    "CONFIRMATION_FAILURE": ("EARLY_PREMIUM_CONFIRMATION",),
    "RETAINED_EXPANSION": ("CONFIRMATION_FAILURE",),
    "GIVEBACK_AFTER_EXPANSION": ("RUNAWAY_CONTINUATION",),
    "PERSISTENT_PREMIUM_DAMAGE": ("RUNAWAY_CONTINUATION",),
    "RUNAWAY_CONTINUATION": ("GIVEBACK_AFTER_EXPANSION", "PERSISTENT_PREMIUM_DAMAGE"),
}


def _read_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _join(causal: list[dict], labels: list[dict], identity: tuple[str, ...]) -> list[dict]:
    label_index = {}
    for row in labels:
        key = tuple(row.get(field) for field in identity)
        if key in label_index:
            raise RuleStageBlocked(f"duplicate label identity {key!r}")
        label_index[key] = row
    output = []
    for row in causal:
        key = tuple(row.get(field) for field in identity)
        if key not in label_index:
            raise RuleStageBlocked(f"label missing for causal identity {key!r}")
        output.append(dict(row, **label_index[key]))
    if len(output) != len(label_index):
        raise RuleStageBlocked("causal/label identity sets differ")
    return output


def run_rule_stage(root: str | Path, *, calibration: str | Path | None = None,
                   output: str | Path | None = None) -> dict:
    root = Path(root)
    calibration = Path(calibration) if calibration is not None else root / "calibration_v1"
    calibration_manifest_path = calibration / "manifest.json"
    if not calibration_manifest_path.exists():
        raise RuleStageBlocked("target-freeze manifest missing")
    freeze_manifest = json.loads(calibration_manifest_path.read_text(encoding="utf-8"))
    if freeze_manifest.get("stage") != "TARGET_FREEZE_ONLY" or freeze_manifest.get("rules_fitted") is not False:
        raise RuleStageBlocked("invalid target-freeze stage state")

    source_paths = {
        "cohort": root / "cohort_ledger.csv",
        "component": root / "component_ledger.csv.gz",
        "entry_target": root / "future_target_matrix.csv",
        "entry_catalyst": root / "catalyst_ledger.csv",
        "position_snapshot": root / "position_snapshot_ledger.csv.gz",
        "position_target": root / "position_future_target_matrix.csv",
        "position_catalyst": root / "position_catalyst_ledger.csv",
        "manifest": root / "manifest.json",
    }
    for name, expected in freeze_manifest.get("input_sha256", {}).items():
        path = source_paths.get(name)
        if path is None or not path.exists() or _hash(path) != expected:
            raise RuleStageBlocked(f"freeze input changed after target definition: {name}")

    entry = _join(
        _read_gz(calibration / "entry_causal.csv.gz"),
        _read_gz(calibration / "entry_future_labels.csv.gz"),
        ("anchor_id", "ticker"),
    )
    position = _join(
        _read_gz(calibration / "position_causal.csv.gz"),
        _read_gz(calibration / "position_future_labels.csv.gz"),
        ("snapshot_id",),
    )
    results = []
    validations = []
    counter_audits = []
    for target, scope, group_field in TARGET_SEARCH_PLAN:
        dataset = entry if scope == "OBSERVE_ENTRY" else position
        try:
            candidates = search_discovery_candidates(
                dataset, target=target, scope=scope, group_field=group_field,
            )
            checked = evaluate_frozen_candidates(candidates, dataset)
            validations.extend(checked)
            target_counters = audit_counter_targets(
                checked, dataset, counter_targets=COUNTER_TARGETS,
            )
            counter_audits.extend(target_counters)
            results.append({
                "target": target, "scope": scope, "status": "EVALUATED_UNCHANGED_HOLDOUT",
                "candidates": len(candidates),
                "preserved": sum(
                    item.validation_status == "HOLDOUT_ROBUST_DIRECTION_PRESERVED" for item in checked
                ),
                "countertarget_clear": len({
                    item.candidate_id for item in target_counters
                    if item.audit_status == "COUNTERTARGET_CLEAR"
                }),
            })
        except InsufficientEvidence as exc:
            results.append({
                "target": target, "scope": scope,
                "status": "INSUFFICIENT_EVIDENCE", "reason": str(exc),
                "candidates": 0, "preserved": 0,
            })

    destination = Path(output) if output is not None else root / "rule_search_v1"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "candidate_validations.json").write_text(
        json.dumps([item.to_dict() for item in validations], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "countertarget_audit.json").write_text(
        json.dumps([item.to_dict() for item in counter_audits], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "stage": "HISTORICAL_CANDIDATE_VALIDATION",
        "status": "RESEARCH_ONLY_NO_GUIDANCE",
        "holdout_used_for_selection": False,
        "candidate_conditions_frozen_on": "DISCOVERY",
        "entry_rows": len(entry), "position_rows": len(position),
        "searches": results,
        "validated_candidates": len(validations),
        "direction_preserved_candidates": sum(
            item.validation_status == "HOLDOUT_ROBUST_DIRECTION_PRESERVED" for item in validations
        ),
        "countertarget_clear_audits": sum(
            item.audit_status == "COUNTERTARGET_CLEAR" for item in counter_audits
        ),
        "ambiguous_countertarget_rejections": sum(
            item.audit_status == "AMBIGUOUS_COUNTERTARGET_REJECTED" for item in counter_audits
        ),
        "target_freeze_manifest_sha256": _hash(calibration_manifest_path),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return manifest


def run_entry_rule_search_stage(root: str | Path, *, calibration: str | Path | None = None,
                                output: str | Path | None = None) -> dict:
    """Entry-only candidate search after the entry target freeze.

    Searches only the three predeclared entry scopes, selects candidate
    conditions on DISCOVERY, evaluates them unchanged on HOLDOUT, and applies the
    countertarget and active-print/liquidity-sensitivity audits. Position-
    management targets are out of scope and never searched.
    """
    root = Path(root)
    calibration = Path(calibration) if calibration is not None else root / "entry_calibration_v1"
    freeze_manifest_path = calibration / "manifest.json"
    if not freeze_manifest_path.exists():
        raise RuleStageBlocked("entry target-freeze manifest missing")
    freeze_manifest = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    if freeze_manifest.get("stage") != "ENTRY_TARGET_FREEZE_ONLY" or freeze_manifest.get("rules_fitted") is not False:
        raise RuleStageBlocked("invalid entry target-freeze stage state")

    source_paths = {
        "cohort": root / "cohort_ledger.csv",
        "component": root / "component_ledger.csv.gz",
        "entry_target": root / "future_target_matrix.csv",
        "entry_catalyst": root / "catalyst_ledger.csv",
        "manifest": root / "manifest.json",
    }
    for name, expected in freeze_manifest.get("input_sha256", {}).items():
        path = source_paths.get(name)
        if path is None or not path.exists() or _hash(path) != expected:
            raise RuleStageBlocked(f"entry freeze input changed after target definition: {name}")

    entry = _join(
        _read_gz(calibration / "entry_causal.csv.gz"),
        _read_gz(calibration / "entry_future_labels.csv.gz"),
        ("anchor_id", "ticker"),
    )
    target_definitions = json.loads(
        (calibration / "target_definitions_v1.json").read_text(encoding="utf-8")
    )
    definitions_by_name = {
        item["name"]: item for item in target_definitions.get("definitions", [])
    }

    validations, counter_audits, liquidity_audits = [], [], []
    all_candidates = []
    results = []
    for target, scope, group_field in ENTRY_TARGET_SEARCH_PLAN:
        try:
            candidates = search_discovery_candidates(
                entry, target=target, scope=scope, group_field=group_field,
            )
            all_candidates.extend(candidates)
            checked = evaluate_frozen_candidates(candidates, entry)
            validations.extend(checked)
            counters = audit_counter_targets(
                checked, entry, counter_targets=ENTRY_COUNTER_TARGETS,
            )
            counter_audits.extend(counters)
            liquidity = audit_liquidity_sensitivity(candidates, definitions_by_name)
            liquidity_audits.extend(liquidity)
            results.append({
                "target": target, "scope": scope, "status": "EVALUATED_UNCHANGED_HOLDOUT",
                "candidates": len(candidates),
                "preserved": sum(
                    item.validation_status == "HOLDOUT_ROBUST_DIRECTION_PRESERVED"
                    for item in checked
                ),
                "countertarget_clear": len({
                    item.candidate_id for item in counters
                    if item.audit_status == "COUNTERTARGET_CLEAR"
                }),
                "liquidity_sensitive": sum(
                    item.audit_status == "LIQUIDITY_SENSITIVE" for item in liquidity
                ),
            })
        except InsufficientEvidence as exc:
            results.append({
                "target": target, "scope": scope, "status": "INSUFFICIENT_EVIDENCE",
                "reason": str(exc), "candidates": 0, "preserved": 0,
                "countertarget_clear": 0, "liquidity_sensitive": 0,
            })

    # --- Checkpoint B correction: methodology over the raw candidate list ---
    tautological = reject_tautological_candidates(all_candidates, entry)
    tautological_ids = {item.candidate_id for item in tautological}
    cell_summaries = active_print_cell_summary(
        entry, tuple(target for target, _scope, _gf in ENTRY_TARGET_SEARCH_PLAN),
    )
    validations_by_id = {item.candidate.candidate_id: item for item in validations}
    active_print_audits = audit_active_print_sensitivity(
        all_candidates, entry, validations_by_id=validations_by_id,
        definitions=definitions_by_name,
    )
    active_print_by_id = {item.candidate_id: item for item in active_print_audits}

    # A supported family must be direction-preserved, countertarget-clear,
    # non-tautological, and active-print-supported.
    counter_clear_ids = {
        item.candidate_id for item in counter_audits
        if item.audit_status == "COUNTERTARGET_CLEAR"
    }
    preserved_ids = {
        item.candidate.candidate_id for item in validations
        if item.validation_status == "HOLDOUT_ROBUST_DIRECTION_PRESERVED"
    }
    supported = [
        item for item in all_candidates
        if item.candidate_id in preserved_ids
        and item.candidate_id in counter_clear_ids
        and item.candidate_id not in tautological_ids
        and active_print_by_id.get(item.candidate_id) is not None
        and active_print_by_id[item.candidate_id].audit_status == "ACTIVE_PRINT_SUPPORTED"
    ]
    families = collapse_by_triggered_fingerprint(supported, entry)
    unique_holdout_fingerprints = len(families)
    supported_families = []
    for key in sorted(families, key=lambda k: (-len(k[4]), sorted(k[4]), k[1], k[2])):
        target, ctype, dte, disc_fp, hold_fp = key
        members = families[key]
        rep = members[0]
        ap = active_print_by_id.get(rep.candidate_id)
        supported_families.append({
            "family_id": "FAM-" + rep.candidate_id[len("CAND-"):],
            "target": target,
            "contract_type": ctype,
            "dte_target": dte,
            "discovery_full_sample_triggers": len(disc_fp),
            "holdout_full_sample_triggers": len(hold_fp),
            "holdout_active_print_triggers": (
                ap.holdout_active_triggered_groups if ap is not None else None
            ),
            "candidate_ids": sorted(m.candidate_id for m in members),
            "conditions": [
                {"feature": c.feature, "operator": c.operator, "threshold": c.threshold}
                for c in rep.conditions
            ],
        })

    destination = Path(output) if output is not None else root / "entry_rule_search_v1"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "candidate_validations.json").write_text(
        json.dumps([item.to_dict() for item in validations], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "countertarget_audit.json").write_text(
        json.dumps([item.to_dict() for item in counter_audits], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "liquidity_sensitivity_audit.json").write_text(
        json.dumps([item.to_dict() for item in liquidity_audits], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "active_print_cell_summary.json").write_text(
        json.dumps([item.to_dict() for item in cell_summaries], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "active_print_audit.json").write_text(
        json.dumps([item.to_dict() for item in active_print_audits], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "tautological_rejections.json").write_text(
        json.dumps([asdict(item) for item in tautological], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (destination / "supported_signal_families.json").write_text(
        json.dumps(supported_families, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "stage": "ENTRY_CANDIDATE_VALIDATION_CORRECTED",
        "scope": "OBSERVE_ENTRY",
        "status": "RESEARCH_ONLY_NO_GUIDANCE",
        "research_only": True,
        "rules_fitted": False,
        "guidance_emitted": False,
        "position_management_status": "BLOCKED_INSUFFICIENT_REPLAY_COVERAGE",
        "holdout_used_for_candidate_generation": False,
        "holdout_used_for_validation": True,
        "holdout_used_for_promotion": False,
        "candidate_conditions_frozen_on": "DISCOVERY",
        "finding_status": "HISTORICAL_RESEARCH_FINDING_NEEDS_EXTERNAL_REPLICATION",
        "shadow_eligible": False,
        "entry_rows": len(entry),
        "searches": results,
        "original_candidate_count": len(all_candidates),
        "validated_candidates": len(validations),
        "direction_preserved_candidates": len(preserved_ids),
        "countertarget_clear_audits": len(counter_clear_ids),
        "tautological_rejections": len(tautological),
        "active_print_supported_candidates": sum(
            item.audit_status == "ACTIVE_PRINT_SUPPORTED" for item in active_print_audits
        ),
        "active_print_insufficient_coverage_candidates": sum(
            item.audit_status == "INSUFFICIENT_ACTIVE_PRINT_COVERAGE" for item in active_print_audits
        ),
        "active_print_liquidity_sensitive_candidates": sum(
            item.audit_status == "LIQUIDITY_SENSITIVE" for item in active_print_audits
        ),
        "supported_candidates": len(supported),
        "unique_supported_signal_families": unique_holdout_fingerprints,
        "target_freeze_manifest_sha256": _hash(freeze_manifest_path),
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return manifest
