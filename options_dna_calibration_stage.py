"""Hard-gated target-freeze stage for Options DNA historical calibration."""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from options_dna_acceptance import audit_pilot_directory
from options_dna_calibration import apply_frozen_outcome
from options_dna_calibration_dataset import (
    REQUIRED_CELLS,
    build_entry_calibration_dataset,
    build_position_calibration_dataset,
    freeze_and_apply_v1_targets,
)
from options_dna_targets import TARGET_HYPOTHESES_V1, freeze_target_hypotheses


class CalibrationStageBlocked(RuntimeError):
    pass


def _read_csv(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_gz(path: Path, rows: list[dict]) -> None:
    if not rows:
        with gzip.open(path, "wt", encoding="utf-8") as handle:
            handle.write("")
        return
    fields = list(rows[0])
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _future_labeled(rows: list[dict], hypothesis_names: list[str]) -> list[dict]:
    identity_fields = (
        "anchor_id", "snapshot_id", "episode_id", "ticker", "partition",
        "contract_type", "dte_target", "moneyness_target",
    )
    output = []
    for row in rows:
        selected = {field: row.get(field) for field in identity_fields if field in row}
        for name in hypothesis_names:
            selected[name] = row.get(name)
            selected[f"{name}_status"] = row.get(f"{name}_status")
        output.append(selected)
    return output


def run_target_freeze_stage(root: str | Path, *, output: str | Path | None = None) -> dict:
    root = Path(root)
    report = audit_pilot_directory(root)
    blockers = []
    if report.status != "READY_FOR_REVIEW":
        blockers.append(f"artifact gate={report.status}")
    if not report.calibration_coverage_ready:
        blockers.append("entry calibration cell coverage not ready")
    if not report.position_replay_coverage_ready:
        blockers.append("position replay cell coverage not ready")
    if blockers:
        raise CalibrationStageBlocked("; ".join(blockers))

    paths = {
        "cohort": root / "cohort_ledger.csv",
        "component": root / "component_ledger.csv.gz",
        "entry_target": root / "future_target_matrix.csv",
        "entry_catalyst": root / "catalyst_ledger.csv",
        "position_snapshot": root / "position_snapshot_ledger.csv.gz",
        "position_target": root / "position_future_target_matrix.csv",
        "position_catalyst": root / "position_catalyst_ledger.csv",
        "manifest": root / "manifest.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise CalibrationStageBlocked(f"freeze inputs missing: {missing!r}")

    entry = build_entry_calibration_dataset(
        _read_csv(paths["cohort"]), _read_csv(paths["component"]),
        _read_csv(paths["entry_target"]), _read_csv(paths["entry_catalyst"]),
    )
    position = build_position_calibration_dataset(
        _read_csv(paths["position_snapshot"]), _read_csv(paths["position_target"]),
        _read_csv(paths["position_catalyst"]),
    )
    entry_pairs = [
        (causal, future) for causal, future in zip(entry["causal"], entry["future"])
        if causal.get("calibration_eligible") is True
    ]
    position_pairs = [
        (causal, future) for causal, future in zip(position["causal"], position["future"])
        if causal.get("calibration_eligible") is True
    ]
    entry_causal = [pair[0] for pair in entry_pairs]
    entry_future = [pair[1] for pair in entry_pairs]
    position_causal = [pair[0] for pair in position_pairs]
    position_future = [pair[1] for pair in position_pairs]
    frozen = freeze_and_apply_v1_targets(entry_future, position_future)

    destination = Path(output) if output is not None else root / "calibration_v1"
    destination.mkdir(parents=True, exist_ok=True)
    _write_gz(destination / "entry_causal.csv.gz", entry_causal)
    _write_gz(destination / "position_causal.csv.gz", position_causal)
    _write_gz(
        destination / "entry_future_labels.csv.gz",
        _future_labeled(frozen["entry_labeled"], frozen["hypothesis_names"]),
    )
    _write_gz(
        destination / "position_future_labels.csv.gz",
        _future_labeled(frozen["position_labeled"], frozen["hypothesis_names"]),
    )
    (destination / "target_definitions_v1.json").write_text(
        json.dumps({
            "version": 1, "status": "FROZEN_DISCOVERY_TARGETS_RESEARCH_ONLY",
            "definitions": [asdict(definition) for definition in frozen["definitions"]],
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "stage": "TARGET_FREEZE_ONLY",
        "research_only": True,
        "rules_fitted": False,
        "guidance_emitted": False,
        "entry_rows": len(entry_causal),
        "position_rows": len(position_causal),
        "entry_ineligible_excluded": len(entry["causal"]) - len(entry_causal),
        "position_ineligible_excluded": len(position["causal"]) - len(position_causal),
        "hypotheses": frozen["hypothesis_names"],
        "input_sha256": {name: _sha256(path) for name, path in paths.items()},
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return manifest


def run_entry_freeze_stage(root: str | Path, *, output: str | Path | None = None) -> dict:
    """Entry-only target freeze. Gates on artifacts + entry cell coverage only.

    The position-replay gate is deliberately NOT checked: open-position
    management is out of scope for this research track, and the stage emits no
    position artifacts. It freezes the six predeclared v1 target definitions on
    DISCOVERY entry paths and applies them unchanged to HOLDOUT entry paths.
    """
    root = Path(root)
    report = audit_pilot_directory(root)
    blockers = []
    if report.status != "READY_FOR_REVIEW":
        blockers.append(f"artifact gate={report.status}")
    if not report.calibration_coverage_ready:
        blockers.append("entry calibration cell coverage not ready")
    if blockers:
        raise CalibrationStageBlocked("; ".join(blockers))

    paths = {
        "cohort": root / "cohort_ledger.csv",
        "component": root / "component_ledger.csv.gz",
        "entry_target": root / "future_target_matrix.csv",
        "entry_catalyst": root / "catalyst_ledger.csv",
        "manifest": root / "manifest.json",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise CalibrationStageBlocked(f"freeze inputs missing: {missing!r}")

    entry = build_entry_calibration_dataset(
        _read_csv(paths["cohort"]), _read_csv(paths["component"]),
        _read_csv(paths["entry_target"]), _read_csv(paths["entry_catalyst"]),
    )
    entry_pairs = [
        (causal, future) for causal, future in zip(entry["causal"], entry["future"])
        if causal.get("calibration_eligible") is True
    ]
    entry_causal = [pair[0] for pair in entry_pairs]
    entry_future = [pair[1] for pair in entry_pairs]

    definitions = freeze_target_hypotheses(entry_future, min_discovery_groups_per_cell=20)
    for definition in definitions:
        cells = {tuple(str(value) for value in cell.cell_values) for cell in definition.cells}
        missing_cells = REQUIRED_CELLS - cells
        if missing_cells:
            raise ValueError(
                f"target {definition.name} missing frozen cells {sorted(missing_cells)!r}"
            )

    entry_labeled = [dict(row) for row in entry_future]
    for definition in definitions:
        entry_labeled = apply_frozen_outcome(definition, entry_labeled)

    destination = Path(output) if output is not None else root / "entry_calibration_v1"
    destination.mkdir(parents=True, exist_ok=True)
    _write_gz(destination / "entry_causal.csv.gz", entry_causal)
    _write_gz(
        destination / "entry_future_labels.csv.gz",
        _future_labeled(entry_labeled, [item.name for item in TARGET_HYPOTHESES_V1]),
    )
    (destination / "target_definitions_v1.json").write_text(
        json.dumps({
            "version": 1,
            "status": "FROZEN_DISCOVERY_TARGETS_RESEARCH_ONLY",
            "scope": "OBSERVE_ENTRY",
            "definitions": [asdict(definition) for definition in definitions],
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "stage": "ENTRY_TARGET_FREEZE_ONLY",
        "scope": "OBSERVE_ENTRY",
        "research_only": True,
        "rules_fitted": False,
        "guidance_emitted": False,
        "position_management_status": "BLOCKED_INSUFFICIENT_REPLAY_COVERAGE",
        "entry_rows": len(entry_causal),
        "entry_ineligible_excluded": len(entry["causal"]) - len(entry_causal),
        "hypotheses": [item.name for item in TARGET_HYPOTHESES_V1],
        "input_sha256": {name: _sha256(path) for name, path in paths.items()},
    }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8",
    )
    return manifest
