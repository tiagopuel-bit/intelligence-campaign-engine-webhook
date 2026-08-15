"""Deterministic acceptance gate for Options DNA historical-cohort artifacts.

This module audits provider outputs; it does not fetch data, fit thresholds, or
emit navigation. Missing artifacts are reported as incomplete rather than
silently accepted. Sparse option bars are preserved exactly as observed.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
from itertools import product
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_ARTIFACTS = (
    "cohort_ledger.csv",
    "component_ledger.csv.gz",
    "forward_outcomes.csv",
    "forward_outcome_windows.csv",
    "coverage_by_cell.csv",
    "quality_rejections.csv",
    "failures.json",
    "DEEPSEEK_EXECUTION_REPORT.md",
)

REQUIRED_COMPONENT_FIELDS = {
    "anchor_id", "ticker", "signal_bar_exists", "coverage_at", "ready",
    "matched_bars", "activity_ratio", "quality_reasons",
}
REQUIRED_OUTCOME_FIELDS = {
    "anchor_id", "ticker", "signal_bar_exists", "coverage_at", "observed_bars",
    "outcome_status", "right_censored", "decision_close", "next_bar_open",
    "decision_to_next_open_gap_pct", "mfe_pct", "mae_pct",
    "terminal_return_pct", "bars_to_peak", "bars_to_trough",
    "peak_to_terminal_giveback_pct", "gain_retention",
    "decision_close_mfe_pct", "decision_close_mae_pct", "peak_before_trough",
}
REQUIRED_WINDOW_OUTCOME_FIELDS = REQUIRED_OUTCOME_FIELDS | {
    "window", "underlying_bars_forward", "cutoff_time_ms", "censor_reason",
}
REQUIRED_CATALYST_FIELDS = {
    "anchor_id", "partition", "event_family", "signal_bar_open_utc",
    "decision_available_utc", "mode", "source_status", "source_reason",
    "active", "filing_count", "severity", "base_form", "category",
    "age_hours", "capacity_only", "available_at_utc", "accession",
    "direction_claim",
}
FUTURE_ONLY_FIELDS = REQUIRED_OUTCOME_FIELDS - {
    "anchor_id", "ticker", "signal_bar_exists", "coverage_at",
}


@dataclass(frozen=True)
class AcceptanceIssue:
    severity: str
    code: str
    detail: str


@dataclass(frozen=True)
class AcceptanceReport:
    status: str
    ready_for_review: bool
    anchor_count: int
    cohort_count: int
    unique_tickers: int
    bar_files: int
    calibration_coverage_ready: bool
    calibration_cell_counts: tuple[dict, ...]
    position_replay_coverage_ready: bool
    position_replay_cell_counts: tuple[dict, ...]
    issues: tuple[AcceptanceIssue, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _read_csv(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _finite(value: object) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def audit_bar_payload(path: Path, *, expected_ticker: str | None = None) -> list[AcceptanceIssue]:
    issues: list[AcceptanceIssue] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [AcceptanceIssue("ERROR", "BAR_JSON_INVALID", f"{path.name}: {exc}")]
    if expected_ticker and payload.get("ticker") != expected_ticker:
        issues.append(AcceptanceIssue(
            "ERROR", "BAR_TICKER_MISMATCH",
            f"{path.name}: expected {expected_ticker}, found {payload.get('ticker')}",
        ))
    bars = payload.get("bars")
    if not isinstance(bars, list):
        return issues + [AcceptanceIssue("ERROR", "BAR_LIST_MISSING", path.name)]
    prior_t = None
    for index, bar in enumerate(bars):
        label = f"{path.name}[{index}]"
        if not isinstance(bar, dict):
            issues.append(AcceptanceIssue("ERROR", "BAR_NOT_OBJECT", label))
            continue
        if any(key not in bar or not _finite(bar.get(key)) for key in ("t", "o", "h", "l", "c", "v")):
            issues.append(AcceptanceIssue("ERROR", "BAR_OHLCV_INVALID", label))
            continue
        t = int(float(bar["t"]))
        o, h, low, close, volume = (float(bar[key]) for key in ("o", "h", "l", "c", "v"))
        if prior_t is not None and t <= prior_t:
            issues.append(AcceptanceIssue("ERROR", "BAR_TIME_NOT_STRICT", label))
        prior_t = t
        if t % 900_000 != 0:
            issues.append(AcceptanceIssue("ERROR", "BAR_OFF_15M_GRID", label))
        if low <= 0 or min(o, close) < low or max(o, close) > h or volume < 0:
            issues.append(AcceptanceIssue("ERROR", "BAR_GEOMETRY_INVALID", label))
        if "n" in bar and (not _finite(bar["n"]) or float(bar["n"]) < 0):
            issues.append(AcceptanceIssue("ERROR", "BAR_TRANSACTION_COUNT_INVALID", label))
        if "vw" in bar and (not _finite(bar["vw"]) or float(bar["vw"]) <= 0):
            issues.append(AcceptanceIssue("ERROR", "BAR_VWAP_INVALID", label))
    return issues


def audit_pilot_directory(root: str | Path) -> AcceptanceReport:
    root = Path(root)
    issues: list[AcceptanceIssue] = []
    manifest_path = root / "manifest.json"
    anchor_path = root / "anchor_plan.csv"
    if not manifest_path.exists() or not anchor_path.exists():
        missing = [p.name for p in (manifest_path, anchor_path) if not p.exists()]
        issues.append(AcceptanceIssue("ERROR", "PLAN_ARTIFACT_MISSING", ", ".join(missing)))
        return AcceptanceReport(
            "INCOMPLETE_ACQUISITION", False, 0, 0, 0, 0,
            False, tuple(), False, tuple(), tuple(issues),
        )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    anchors = _read_csv(anchor_path)
    anchor_ids = [row.get("anchor_id", "") for row in anchors]
    if len(anchor_ids) != len(set(anchor_ids)) or any(not value for value in anchor_ids):
        issues.append(AcceptanceIssue("ERROR", "ANCHOR_ID_INVALID", "anchor IDs must be non-empty and unique"))
    if manifest.get("anchor_count") != len(anchors):
        issues.append(AcceptanceIssue(
            "ERROR", "ANCHOR_COUNT_MISMATCH",
            f"manifest={manifest.get('anchor_count')} ledger={len(anchors)}",
        ))

    required_artifacts = list(REQUIRED_ARTIFACTS)
    catalyst_design = manifest.get("catalyst_design")
    if isinstance(catalyst_design, dict) and catalyst_design.get("required") is True:
        required_artifacts.extend(("catalyst_ledger.csv", "catalyst_manifest.json"))
    target_design = manifest.get("target_design")
    if isinstance(target_design, dict) and target_design.get("required") is True:
        required_artifacts.extend(("future_target_matrix.csv", "target_hypotheses_v1.json"))
    position_design = manifest.get("position_replay_design")
    if isinstance(position_design, dict) and position_design.get("required") is True:
        required_artifacts.extend((
            "position_episode_ledger.csv", "position_snapshot_ledger.csv.gz",
            "position_snapshot_anchor_plan.csv",
            "position_snapshot_outcome_windows.csv", "position_snapshot_rejections.csv",
            "position_future_target_matrix.csv", "position_replay_manifest.json",
            "position_catalyst_ledger.csv", "position_catalyst_manifest.json",
        ))
    shadow_design = manifest.get("shadow_acceptance_design")
    if isinstance(shadow_design, dict) and shadow_design.get("required") is True:
        required_artifacts.append(str(
            shadow_design.get("criteria_file") or "shadow_acceptance_criteria_v1.json"
        ))
    missing_artifacts = [name for name in required_artifacts if not (root / name).exists()]
    if manifest.get("status") not in {"FETCHED", "FETCHED_WITH_FAILURES", "VERIFIED"}:
        issues.append(AcceptanceIssue(
            "INFO", "ACQUISITION_NOT_FINAL", f"manifest status={manifest.get('status')}",
        ))
    for name in missing_artifacts:
        issues.append(AcceptanceIssue("INFO", "REQUIRED_ARTIFACT_PENDING", name))

    if isinstance(shadow_design, dict) and shadow_design.get("required") is True:
        criteria_name = str(
            shadow_design.get("criteria_file") or "shadow_acceptance_criteria_v1.json"
        )
        criteria_path = root / criteria_name
        if criteria_path.exists():
            actual_hash = hashlib.sha256(criteria_path.read_bytes()).hexdigest()
            expected_hash = shadow_design.get("criteria_file_sha256")
            if expected_hash != actual_hash:
                issues.append(AcceptanceIssue(
                    "ERROR", "SHADOW_CRITERIA_HASH_MISMATCH",
                    f"manifest={expected_hash} actual={actual_hash}",
                ))

    bars_dir = root / "bars"
    bar_files = sorted(bars_dir.glob("*.json")) if bars_dir.exists() else []
    for path in bar_files:
        issues.extend(audit_bar_payload(path))

    cohort_path = root / "cohort_ledger.csv"
    cohort = _read_csv(cohort_path) if cohort_path.exists() and cohort_path.stat().st_size else []
    unique_tickers = {row.get("ticker", "") for row in cohort if row.get("ticker")}
    if cohort:
        required = {
            "anchor_id", "partition", "event_family", "decision_available_utc", "ticker",
            "contract_type", "dte_target", "moneyness_target", "bar_count", "bars_file",
        }
        missing_columns = sorted(required - set(cohort[0]))
        if missing_columns:
            issues.append(AcceptanceIssue("ERROR", "COHORT_COLUMNS_MISSING", ", ".join(missing_columns)))
        seen_identity: set[tuple] = set()
        planned_anchors = set(anchor_ids)
        for row in cohort:
            identity = tuple(row.get(field) for field in (
                "anchor_id", "contract_type", "dte_target", "moneyness_target",
            ))
            if identity in seen_identity:
                issues.append(AcceptanceIssue("ERROR", "COHORT_CELL_DUPLICATE", repr(identity)))
            seen_identity.add(identity)
            if row.get("anchor_id") not in planned_anchors:
                issues.append(AcceptanceIssue("ERROR", "COHORT_ANCHOR_UNKNOWN", str(row.get("anchor_id"))))
            bars_file = root / str(row.get("bars_file", ""))
            if not bars_file.is_file():
                issues.append(AcceptanceIssue("ERROR", "COHORT_BAR_FILE_MISSING", str(bars_file)))
                continue
            issues.extend(audit_bar_payload(bars_file, expected_ticker=row.get("ticker")))
            try:
                payload = json.loads(bars_file.read_text(encoding="utf-8"))
                bars = payload["bars"]
                if int(row.get("bar_count", -1)) != len(bars):
                    issues.append(AcceptanceIssue(
                        "ERROR", "COHORT_BAR_COUNT_MISMATCH",
                        f"{row.get('ticker')}: ledger={row.get('bar_count')} file={len(bars)}",
                    ))
                signal_ms = _utc_ms(row["signal_bar_open_utc"])
                decision_ms = _utc_ms(row["decision_available_utc"])
                timestamps = {int(bar["t"]) for bar in bars}
                if signal_ms not in timestamps:
                    issues.append(AcceptanceIssue("WARN", "SIGNAL_BAR_ABSENT", repr(identity)))
                if not any(timestamp >= decision_ms for timestamp in timestamps):
                    issues.append(AcceptanceIssue("WARN", "NO_POST_DECISION_BAR", repr(identity)))
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(AcceptanceIssue("ERROR", "COHORT_CAUSAL_AUDIT_FAILED", f"{identity!r}: {exc}"))

    component_path = root / "component_ledger.csv.gz"
    outcome_path = root / "forward_outcomes.csv"
    window_outcome_path = root / "forward_outcome_windows.csv"
    components = _read_csv(component_path) if component_path.exists() and component_path.stat().st_size else []
    outcomes = _read_csv(outcome_path) if outcome_path.exists() and outcome_path.stat().st_size else []
    window_outcomes = (
        _read_csv(window_outcome_path)
        if window_outcome_path.exists() and window_outcome_path.stat().st_size else []
    )
    if component_path.exists():
        component_fields = set(components[0]) if components else set()
        missing = sorted(REQUIRED_COMPONENT_FIELDS - component_fields)
        if missing:
            issues.append(AcceptanceIssue("ERROR", "COMPONENT_COLUMNS_MISSING", ", ".join(missing)))
        leaked = sorted(FUTURE_ONLY_FIELDS & component_fields)
        if leaked:
            issues.append(AcceptanceIssue("ERROR", "FUTURE_FIELDS_IN_CAUSAL_LEDGER", ", ".join(leaked)))
        if cohort and len(components) != len(cohort):
            issues.append(AcceptanceIssue(
                "ERROR", "COMPONENT_ROW_COUNT_MISMATCH",
                f"cohort={len(cohort)} component={len(components)}",
            ))
    if outcome_path.exists():
        outcome_fields = set(outcomes[0]) if outcomes else set()
        missing = sorted(REQUIRED_OUTCOME_FIELDS - outcome_fields)
        if missing:
            issues.append(AcceptanceIssue("ERROR", "OUTCOME_COLUMNS_MISSING", ", ".join(missing)))
        if cohort and len(outcomes) != len(cohort):
            issues.append(AcceptanceIssue(
                "ERROR", "OUTCOME_ROW_COUNT_MISMATCH",
                f"cohort={len(cohort)} outcome={len(outcomes)}",
            ))
        for row in outcomes:
            signal_exists = _truthy(row.get("signal_bar_exists"))
            try:
                coverage_at = int(row.get("coverage_at", -1))
                observed = int(row.get("observed_bars", -1))
            except (TypeError, ValueError):
                issues.append(AcceptanceIssue(
                    "ERROR", "OUTCOME_CAUSAL_FIELDS_INVALID",
                    f"{row.get('anchor_id')} {row.get('ticker')}",
                ))
                continue
            if coverage_at != int(signal_exists):
                issues.append(AcceptanceIssue(
                    "ERROR", "SIGNAL_COVERAGE_INCONSISTENT",
                    f"{row.get('anchor_id')} {row.get('ticker')}: exists={signal_exists} at={coverage_at}",
                ))
            if not signal_exists and (
                observed != 0 or row.get("decision_close") not in (None, "")
                or row.get("next_bar_open") not in (None, "")
                or row.get("right_censored") not in (None, "")
                or row.get("outcome_status") != "UNSCORED_SIGNAL_BAR_ABSENT"
            ):
                issues.append(AcceptanceIssue(
                    "ERROR", "MISSING_SIGNAL_WAS_SHIFTED",
                    f"{row.get('anchor_id')} {row.get('ticker')}",
                ))
    if window_outcome_path.exists():
        window_fields = set(window_outcomes[0]) if window_outcomes else set()
        missing = sorted(REQUIRED_WINDOW_OUTCOME_FIELDS - window_fields)
        if missing:
            issues.append(AcceptanceIssue(
                "ERROR", "WINDOW_OUTCOME_COLUMNS_MISSING", ", ".join(missing),
            ))
        expected_windows = {"H1", "D1", "D3", "D5", "D10"}
        if cohort and len(window_outcomes) != len(cohort) * len(expected_windows):
            issues.append(AcceptanceIssue(
                "ERROR", "WINDOW_OUTCOME_ROW_COUNT_MISMATCH",
                f"cohort={len(cohort)} windows={len(window_outcomes)}",
            ))
        identities: dict[tuple[str, str], set[str]] = {}
        for row in window_outcomes:
            key = (str(row.get("anchor_id")), str(row.get("ticker")))
            identities.setdefault(key, set()).add(str(row.get("window")))
            signal_exists = _truthy(row.get("signal_bar_exists"))
            if not signal_exists and (
                row.get("observed_bars") not in (None, "", "0")
                or row.get("next_bar_open") not in (None, "")
                or row.get("outcome_status") != "UNSCORED_SIGNAL_BAR_ABSENT"
            ):
                issues.append(AcceptanceIssue(
                    "ERROR", "WINDOW_MISSING_SIGNAL_WAS_SHIFTED", repr(key),
                ))
        for key, windows in identities.items():
            if windows != expected_windows:
                issues.append(AcceptanceIssue(
                    "ERROR", "WINDOW_SET_INCOMPLETE", f"{key!r}: {sorted(windows)!r}",
                ))

    catalyst_path = root / "catalyst_ledger.csv"
    catalyst_rows = (
        _read_csv(catalyst_path)
        if catalyst_path.exists() and catalyst_path.stat().st_size else []
    )
    if catalyst_path.exists():
        catalyst_fields = set(catalyst_rows[0]) if catalyst_rows else set()
        missing = sorted(REQUIRED_CATALYST_FIELDS - catalyst_fields)
        if missing:
            issues.append(AcceptanceIssue(
                "ERROR", "CATALYST_COLUMNS_MISSING", ", ".join(missing),
            ))
        identities: set[tuple[str, str]] = set()
        planned_anchors = set(anchor_ids)
        for row in catalyst_rows:
            identity = (str(row.get("anchor_id")), str(row.get("mode")))
            if identity in identities:
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_IDENTITY_DUPLICATE", repr(identity),
                ))
            identities.add(identity)
            if identity[0] not in planned_anchors:
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_ANCHOR_UNKNOWN", identity[0],
                ))
            if identity[1] not in {"PUBLIC_ACCEPTANCE", "OPERATIONAL_SEEN"}:
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_MODE_INVALID", repr(identity),
                ))
            status = str(row.get("source_status"))
            if status not in {"ACTIVE", "INACTIVE", "SOURCE_UNAVAILABLE"}:
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_SOURCE_STATUS_INVALID", repr(identity),
                ))
            if row.get("direction_claim") not in (None, ""):
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_DIRECTION_CLAIM_FORBIDDEN", repr(identity),
                ))
            if status == "ACTIVE" and (
                not _truthy(row.get("active"))
                or row.get("available_at_utc") in (None, "")
                or row.get("accession") in (None, "")
            ):
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_ACTIVE_EVIDENCE_INVALID", repr(identity),
                ))
            if status == "INACTIVE" and _truthy(row.get("active")):
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_INACTIVE_CONTRADICTION", repr(identity),
                ))

        if isinstance(catalyst_design, dict) and catalyst_design.get("required") is True:
            required_modes = tuple(catalyst_design.get("required_modes") or ())
            if not required_modes:
                issues.append(AcceptanceIssue(
                    "ERROR", "CATALYST_REQUIRED_MODES_MISSING", "manifest catalyst_design",
                ))
            for mode in required_modes:
                expected = {(anchor_id, str(mode)) for anchor_id in anchor_ids}
                missing_identities = sorted(expected - identities)
                if missing_identities:
                    issues.append(AcceptanceIssue(
                        "ERROR", "CATALYST_REQUIRED_ROWS_MISSING",
                        f"{mode}: {len(missing_identities)} anchor(s)",
                    ))
                unavailable = [
                    row for row in catalyst_rows
                    if row.get("mode") == mode
                    and row.get("source_status") == "SOURCE_UNAVAILABLE"
                ]
                if unavailable:
                    issues.append(AcceptanceIssue(
                        "ERROR", "CATALYST_REQUIRED_COVERAGE_UNAVAILABLE",
                        f"{mode}: {len(unavailable)} anchor(s)",
                    ))

    target_matrix_path = root / "future_target_matrix.csv"
    target_rows = (
        _read_csv(target_matrix_path)
        if target_matrix_path.exists() and target_matrix_path.stat().st_size else []
    )
    if target_matrix_path.exists():
        target_fields = set(target_rows[0]) if target_rows else set()
        base_fields = {"anchor_id", "ticker", "partition", "contract_type", "dte_target"}
        missing = sorted(base_fields - target_fields)
        expected_windows = {"H1", "D1", "D3", "D5", "D10"}
        for window in expected_windows:
            missing.extend(sorted({
                f"{window}__status", f"{window}__complete",
                f"{window}__mfe_pct", f"{window}__mae_pct",
                f"{window}__terminal_return_pct",
            } - target_fields))
        if missing:
            issues.append(AcceptanceIssue(
                "ERROR", "TARGET_MATRIX_COLUMNS_MISSING", ", ".join(sorted(set(missing))),
            ))
        identities = [(row.get("anchor_id"), row.get("ticker")) for row in target_rows]
        if len(identities) != len(set(identities)):
            issues.append(AcceptanceIssue(
                "ERROR", "TARGET_MATRIX_IDENTITY_DUPLICATE", "anchor_id + ticker",
            ))
        if cohort and len(target_rows) != len(cohort):
            issues.append(AcceptanceIssue(
                "ERROR", "TARGET_MATRIX_ROW_COUNT_MISMATCH",
                f"cohort={len(cohort)} target={len(target_rows)}",
            ))
        for row in target_rows:
            for window in expected_windows:
                status = row.get(f"{window}__status")
                complete = _truthy(row.get(f"{window}__complete"))
                if complete != (status == "SCORED_WINDOW"):
                    issues.append(AcceptanceIssue(
                        "ERROR", "TARGET_COMPLETE_STATUS_INCONSISTENT",
                        f"{row.get('anchor_id')} {row.get('ticker')} {window}",
                    ))
                if not complete and any(
                    row.get(f"{window}__{field}") not in (None, "")
                    for field in ("mfe_pct", "mae_pct", "terminal_return_pct")
                ):
                    issues.append(AcceptanceIssue(
                        "ERROR", "CENSORED_TARGET_VALUE_LEAK",
                        f"{row.get('anchor_id')} {row.get('ticker')} {window}",
                    ))

    hypotheses_path = root / "target_hypotheses_v1.json"
    if hypotheses_path.exists():
        try:
            hypotheses = json.loads(hypotheses_path.read_text(encoding="utf-8"))
            if hypotheses.get("future_only") is not True:
                issues.append(AcceptanceIssue(
                    "ERROR", "TARGET_HYPOTHESES_NOT_FUTURE_ONLY", hypotheses_path.name,
                ))
            if hypotheses.get("status") != "HYPOTHESES_ONLY_NOT_CALIBRATED":
                issues.append(AcceptanceIssue(
                    "ERROR", "TARGET_HYPOTHESES_STATUS_INVALID", str(hypotheses.get("status")),
                ))
        except (OSError, ValueError, TypeError) as exc:
            issues.append(AcceptanceIssue(
                "ERROR", "TARGET_HYPOTHESES_INVALID", str(exc),
            ))

    position_episode_path = root / "position_episode_ledger.csv"
    position_snapshot_path = root / "position_snapshot_ledger.csv.gz"
    position_outcome_path = root / "position_snapshot_outcome_windows.csv"
    position_target_path = root / "position_future_target_matrix.csv"
    position_catalyst_path = root / "position_catalyst_ledger.csv"
    position_episodes = (
        _read_csv(position_episode_path)
        if position_episode_path.exists() and position_episode_path.stat().st_size else []
    )
    position_snapshots = (
        _read_csv(position_snapshot_path)
        if position_snapshot_path.exists() and position_snapshot_path.stat().st_size else []
    )
    position_outcomes = (
        _read_csv(position_outcome_path)
        if position_outcome_path.exists() and position_outcome_path.stat().st_size else []
    )
    position_targets = (
        _read_csv(position_target_path)
        if position_target_path.exists() and position_target_path.stat().st_size else []
    )
    position_catalysts = (
        _read_csv(position_catalyst_path)
        if position_catalyst_path.exists() and position_catalyst_path.stat().st_size else []
    )
    position_counts: list[dict] = []
    position_ready = False
    if position_episode_path.exists():
        episode_fields = set(position_episodes[0]) if position_episodes else set()
        missing = sorted({
            "episode_id", "entry_anchor_id", "ticker", "contract_type", "dte_target",
            "partition", "entry_decision_available_utc", "entry_execution_bar_open_utc",
            "entry_price", "execution_status", "research_scope",
        } - episode_fields)
        if missing:
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_EPISODE_COLUMNS_MISSING", ", ".join(missing),
            ))
        episode_ids = [row.get("episode_id") for row in position_episodes]
        if len(episode_ids) != len(set(episode_ids)) or any(not value for value in episode_ids):
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_EPISODE_ID_INVALID", "episode IDs must be unique",
            ))
        for row in position_episodes:
            if row.get("execution_status") != "EXACT_NEXT_BAR_OPEN":
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_ENTRY_EXECUTION_NOT_EXACT", str(row.get("episode_id")),
                ))
            try:
                if _utc_ms(row["entry_execution_bar_open_utc"]) != _utc_ms(row["entry_decision_available_utc"]):
                    raise ValueError("execution timestamp differs from decision")
                if not _finite(row.get("entry_price")) or float(row["entry_price"]) <= 0:
                    raise ValueError("entry price invalid")
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_ENTRY_CAUSAL_INVALID",
                    f"{row.get('episode_id')}: {exc}",
                ))

        snapshot_fields = set(position_snapshots[0]) if position_snapshots else set()
        missing = sorted({
            "snapshot_id", "episode_id", "snapshot_signal_bar_open_utc",
            "snapshot_decision_available_utc", "navigation_scope", "entry_price",
            "current_premium", "unrealized_pnl_pct", "contract__ready",
        } - snapshot_fields)
        if missing:
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_SNAPSHOT_COLUMNS_MISSING", ", ".join(missing),
            ))
        snapshot_ids = [row.get("snapshot_id") for row in position_snapshots]
        if len(snapshot_ids) != len(set(snapshot_ids)) or any(not value for value in snapshot_ids):
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_SNAPSHOT_ID_INVALID", "snapshot IDs must be unique",
            ))
        known_episodes = set(episode_ids)
        forbidden_fragments = (
            "mfe", "mae", "terminal_return", "bars_to_peak", "bars_to_trough",
            "peak_before_trough", "giveback", "gain_retention", "next_bar_open",
        )
        leaked = sorted(
            field for field in snapshot_fields
            if any(fragment in field.lower() for fragment in forbidden_fragments)
        )
        if leaked:
            issues.append(AcceptanceIssue(
                "ERROR", "FUTURE_FIELDS_IN_POSITION_SNAPSHOT", ", ".join(leaked),
            ))
        entry_times = {
            row.get("episode_id"): row.get("entry_decision_available_utc")
            for row in position_episodes
        }
        for row in position_snapshots:
            if row.get("episode_id") not in known_episodes:
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_SNAPSHOT_EPISODE_UNKNOWN", str(row.get("snapshot_id")),
                ))
            if row.get("navigation_scope") != "MANAGE_OPEN_LONG_PREMIUM":
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_SNAPSHOT_SCOPE_INVALID", str(row.get("snapshot_id")),
                ))
            try:
                if _utc_ms(row["snapshot_decision_available_utc"]) <= _utc_ms(entry_times[row["episode_id"]]):
                    raise ValueError("snapshot does not follow entry")
            except (KeyError, TypeError, ValueError) as exc:
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_SNAPSHOT_TIME_INVALID",
                    f"{row.get('snapshot_id')}: {exc}",
                ))

        expected_windows = {"H1", "D1", "D3", "D5", "D10"}
        outcome_sets: dict[str, set[str]] = {}
        for row in position_outcomes:
            snapshot_id = str(row.get("snapshot_id"))
            outcome_sets.setdefault(snapshot_id, set()).add(str(row.get("window")))
        if position_snapshots and len(position_outcomes) != len(position_snapshots) * 5:
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_OUTCOME_ROW_COUNT_MISMATCH",
                f"snapshots={len(position_snapshots)} outcomes={len(position_outcomes)}",
            ))
        for snapshot_id in snapshot_ids:
            if outcome_sets.get(str(snapshot_id), set()) != expected_windows:
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_OUTCOME_WINDOW_SET_INCOMPLETE", str(snapshot_id),
                ))
        target_ids = [row.get("snapshot_id") for row in position_targets]
        if position_snapshots and set(target_ids) != set(snapshot_ids):
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_TARGET_IDENTITY_MISMATCH",
                f"snapshots={len(set(snapshot_ids))} targets={len(set(target_ids))}",
            ))
        if len(target_ids) != len(set(target_ids)):
            issues.append(AcceptanceIssue(
                "ERROR", "POSITION_TARGET_IDENTITY_DUPLICATE", "snapshot_id",
            ))
        if position_catalyst_path.exists() or (
            isinstance(position_design, dict) and position_design.get("required") is True
        ):
            public_position_catalysts = [
                row for row in position_catalysts if row.get("mode") == "PUBLIC_ACCEPTANCE"
            ]
            catalyst_ids = [row.get("anchor_id") for row in public_position_catalysts]
            if position_snapshots and set(catalyst_ids) != set(snapshot_ids):
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_CATALYST_IDENTITY_MISMATCH",
                    f"snapshots={len(set(snapshot_ids))} catalysts={len(set(catalyst_ids))}",
                ))
            unavailable_position_catalysts = [
                row for row in public_position_catalysts
                if row.get("source_status") == "SOURCE_UNAVAILABLE"
            ]
            if unavailable_position_catalysts:
                issues.append(AcceptanceIssue(
                    "ERROR", "POSITION_CATALYST_COVERAGE_UNAVAILABLE",
                    f"PUBLIC_ACCEPTANCE: {len(unavailable_position_catalysts)} snapshot(s)",
                ))

        if isinstance(position_design, dict) and position_design.get("required") is True:
            minima = {
                "DISCOVERY": int(position_design.get("discovery_independent_episodes_per_cell", 0)),
                "HOLDOUT": int(position_design.get("holdout_independent_episodes_per_cell", 0)),
            }
            types = tuple(manifest.get("contract_design", {}).get("types") or ())
            dtes = tuple(str(value) for value in manifest.get("contract_design", {}).get("dte_targets") or ())
            ready_episode_ids = {
                row.get("episode_id") for row in position_snapshots
                if _truthy(row.get("contract__ready"))
            }
            groups: dict[tuple[str, str, str], set[str]] = {}
            for row in position_episodes:
                if row.get("episode_id") not in ready_episode_ids:
                    continue
                key = (str(row.get("partition")), str(row.get("contract_type")), str(row.get("dte_target")))
                groups.setdefault(key, set()).add(str(row.get("episode_id")))
            position_ready = all(value > 0 for value in minima.values())
            for partition in ("DISCOVERY", "HOLDOUT"):
                for ctype, dte in product(types, dtes):
                    count = len(groups.get((partition, str(ctype), str(dte)), set()))
                    required = minima[partition]
                    passed = count >= required
                    position_counts.append({
                        "partition": partition, "contract_type": str(ctype),
                        "dte_target": str(dte), "independent_ready_episodes": count,
                        "required": required, "passed": passed,
                    })
                    if not passed:
                        position_ready = False
                        issues.append(AcceptanceIssue(
                            "WARN", "POSITION_REPLAY_CELL_DEFICIT",
                            f"{partition} {ctype} {dte}: {count}/{required}",
                        ))

    calibration_counts: list[dict] = []
    calibration_ready = False
    targets = manifest.get("acceptance_targets")
    if isinstance(targets, dict) and components:
        cell_fields = tuple(targets.get("cell_fields") or ())
        types = tuple(manifest.get("contract_design", {}).get("types") or ())
        dtes = tuple(manifest.get("contract_design", {}).get("dte_targets") or ())
        supported_values = {
            "contract_type": types,
            "dte_target": tuple(str(value) for value in dtes),
        }
        if not cell_fields or any(field not in supported_values for field in cell_fields):
            issues.append(AcceptanceIssue(
                "ERROR", "CALIBRATION_CELL_FIELDS_INVALID", repr(cell_fields),
            ))
        else:
            minima = {
                "DISCOVERY": int(targets.get(
                    "discovery_independent_exact_signal_anchors_per_contract_cell", 0,
                )),
                "HOLDOUT": int(targets.get(
                    "holdout_independent_exact_signal_anchors_per_contract_cell", 0,
                )),
            }
            ready_groups: dict[tuple[str, tuple[str, ...]], set[str]] = {}
            for row in components:
                if not (_truthy(row.get("ready")) and _truthy(row.get("signal_bar_exists"))):
                    continue
                partition = str(row.get("partition"))
                cell = tuple(str(row.get(field)) for field in cell_fields)
                ready_groups.setdefault((partition, cell), set()).add(str(row.get("anchor_id")))
            calibration_ready = all(value > 0 for value in minima.values())
            value_axes = [supported_values[field] for field in cell_fields]
            for partition in ("DISCOVERY", "HOLDOUT"):
                for raw_cell in product(*value_axes):
                    cell = tuple(str(value) for value in raw_cell)
                    count = len(ready_groups.get((partition, cell), set()))
                    required = minima[partition]
                    passed = count >= required
                    calibration_counts.append({
                        "partition": partition,
                        **{field: value for field, value in zip(cell_fields, cell)},
                        "independent_exact_signal_anchors": count,
                        "required": required,
                        "passed": passed,
                    })
                    if not passed:
                        calibration_ready = False
                        issues.append(AcceptanceIssue(
                            "WARN", "CALIBRATION_CELL_DEFICIT",
                            f"{partition} {dict(zip(cell_fields, cell))}: {count}/{required}",
                        ))

    errors = [issue for issue in issues if issue.severity == "ERROR"]
    acquisition_complete = not missing_artifacts and manifest.get("status") in {
        "FETCHED", "FETCHED_WITH_FAILURES", "VERIFIED",
    }
    ready = acquisition_complete and bool(cohort) and not errors
    status = "READY_FOR_REVIEW" if ready else (
        "REJECTED" if acquisition_complete and errors else "INCOMPLETE_ACQUISITION"
    )
    return AcceptanceReport(
        status=status,
        ready_for_review=ready,
        anchor_count=len(anchors),
        cohort_count=len(cohort),
        unique_tickers=len(unique_tickers),
        bar_files=len(bar_files),
        calibration_coverage_ready=calibration_ready,
        calibration_cell_counts=tuple(calibration_counts),
        position_replay_coverage_ready=position_ready,
        position_replay_cell_counts=tuple(position_counts),
        issues=tuple(issues),
    )
