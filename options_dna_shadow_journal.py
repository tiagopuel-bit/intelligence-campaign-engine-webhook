"""Append-only SQLite journal and acceptance metrics for Options DNA shadowing."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone

from options_dna_guidance import ALLOWED_LABELS, FUTURE_TOKENS


def _timestamp(value: object) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _future_fact_paths(value: object, prefix: str = "") -> list[str]:
    paths = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if any(token in str(key).lower() for token in FUTURE_TOKENS):
                paths.append(path)
            paths.extend(_future_fact_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_future_fact_paths(child, f"{prefix}[{index}]"))
    return paths


def ensure_shadow_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS options_dna_shadow_observations (
            shadow_event_id TEXT PRIMARY KEY,
            observation_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            contract_ticker TEXT NOT NULL,
            decision_available_utc TEXT NOT NULL,
            observed_at_utc TEXT NOT NULL,
            gate TEXT NOT NULL,
            navigation_scope TEXT,
            calibration_version TEXT,
            bundle_hash TEXT,
            fact_signature TEXT NOT NULL,
            state_signature TEXT,
            primary_label TEXT,
            labels_json TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE INDEX IF NOT EXISTS idx_options_dna_shadow_contract_time
        ON options_dna_shadow_observations(contract_ticker, observed_at_utc)
    """)
    columns = {
        row[1] for row in connection.execute(
            "PRAGMA table_info(options_dna_shadow_observations)"
        ).fetchall()
    }
    if "state_signature" not in columns:
        connection.execute(
            "ALTER TABLE options_dna_shadow_observations ADD COLUMN state_signature TEXT"
        )
    connection.commit()


def record_shadow_observation(
    connection: sqlite3.Connection, observation: dict, *, observed_at_utc: str,
) -> dict:
    """Record one materially new shadow state; identical repeats are deduped."""
    ensure_shadow_schema(connection)
    observed = _timestamp(observed_at_utc).isoformat()
    decision = _timestamp(observation.get("decision_available_utc"))
    if _timestamp(observed_at_utc) < decision:
        raise ValueError("shadow observation cannot be recorded before its decision time")
    required = (
        "observation_id", "symbol", "contract_ticker", "decision_available_utc",
        "gate", "fact_signature",
    )
    if any(not observation.get(field) for field in required):
        raise ValueError("shadow observation is missing required identity fields")
    labels = list(observation.get("candidate_labels") or [])
    label_names = [str(item.get("label")) for item in labels]
    if any(label not in ALLOWED_LABELS for label in label_names):
        raise ValueError("shadow observation contains an unsupported advisory label")
    if observation["gate"] != "READY_FOR_SHADOW_RULES" and labels:
        raise ValueError("gated observation cannot contain advisory labels")
    if labels and not observation.get("bundle_hash"):
        raise ValueError("labeled observation requires a frozen bundle hash")
    if labels and observation.get("rule_evaluation_status") != "EVALUATED_SHADOW_ONLY":
        raise ValueError("labeled observation requires completed shadow rule evaluation")
    allowed_label_fields = {
        "label", "rule_id", "rationale_code", "scope", "priority", "evidence_paths",
    }
    if any(set(item) - allowed_label_fields for item in labels):
        raise ValueError("advisory labels cannot contain price, quantity, or order fields")
    primary = observation.get("primary_advisory")
    primary_label = primary.get("label") if isinstance(primary, dict) else None
    if primary_label is not None and primary_label not in label_names:
        raise ValueError("primary advisory must be one of the candidate labels")
    leaked = _future_fact_paths(observation.get("facts") or {})
    if leaked:
        raise ValueError(f"future outcome facts prohibited in shadow journal: {leaked!r}")

    material = {
        "observation_id": observation["observation_id"],
        "fact_signature": observation["fact_signature"],
        "gate": observation["gate"],
        "navigation_scope": observation.get("navigation_scope"),
        "calibration_version": observation.get("calibration_version"),
        "bundle_hash": observation.get("bundle_hash"),
        "labels": labels,
        "primary_label": primary_label,
    }
    state_signature = _hash(material)
    event_id = _hash({"state_signature": state_signature, "observed_at_utc": observed})
    prior = connection.execute(
        "SELECT COALESCE(state_signature, shadow_event_id), observed_at_utc "
        "FROM options_dna_shadow_observations "
        "WHERE contract_ticker = ? ORDER BY observed_at_utc DESC, rowid DESC LIMIT 1",
        (str(observation["contract_ticker"]).upper(),),
    ).fetchone()
    if prior and prior[0] == state_signature:
        return {"inserted": False, "shadow_event_id": event_id, "reason": "UNCHANGED"}
    if prior and _timestamp(observed) < _timestamp(prior[1]):
        raise ValueError("out-of-order shadow observation")

    connection.execute("""
        INSERT OR IGNORE INTO options_dna_shadow_observations (
            shadow_event_id, observation_id, symbol, contract_ticker,
            decision_available_utc, observed_at_utc, gate, navigation_scope,
            calibration_version, bundle_hash, fact_signature, primary_label,
            state_signature, labels_json, payload_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        event_id, observation["observation_id"], str(observation["symbol"]).upper(),
        str(observation["contract_ticker"]).upper(), observation["decision_available_utc"],
        observed, observation["gate"], observation.get("navigation_scope"),
        observation.get("calibration_version"), observation.get("bundle_hash"),
        observation["fact_signature"], primary_label, state_signature,
        json.dumps(labels, sort_keys=True), json.dumps(observation, sort_keys=True, default=str),
    ))
    inserted = connection.execute("SELECT changes()").fetchone()[0] == 1
    connection.commit()
    return {"inserted": inserted, "shadow_event_id": event_id, "reason": "MATERIAL_CHANGE"}


def _sequence_metrics(rows: list[tuple]) -> tuple[int, int]:
    """Count material state transitions and one-step advisory reversals."""
    material_states = [
        (row[3], row[4], row[5], row[6], row[7])
        for row in rows
    ]
    transitions = sum(
        first != second for first, second in zip(material_states, material_states[1:])
    )
    labels = []
    for row in rows:
        label = row[6]
        if not labels or labels[-1] != label:
            labels.append(label)
    reversals = sum(
        1 for first, middle, last in zip(labels, labels[1:], labels[2:])
        if first is not None and first == last and middle != first
    )
    return transitions, reversals


def shadow_summary(connection: sqlite3.Connection) -> dict:
    ensure_shadow_schema(connection)
    rows = connection.execute("""
        SELECT contract_ticker, decision_available_utc, observed_at_utc, gate,
               navigation_scope, fact_signature, primary_label, labels_json
        FROM options_dna_shadow_observations
        ORDER BY contract_ticker, observed_at_utc, rowid
    """).fetchall()
    gates = Counter(row[3] for row in rows)
    labels = Counter(row[6] for row in rows if row[6])
    by_contract = defaultdict(list)
    for row in rows:
        by_contract[row[0]].append(row)
    sequence_metrics = [_sequence_metrics(items) for items in by_contract.values()]
    transitions = sum(item[0] for item in sequence_metrics)
    reversals = sum(item[1] for item in sequence_metrics)
    observed_times = [_timestamp(row[2]) for row in rows]
    calendar_days = (
        (max(observed_times).date() - min(observed_times).date()).days + 1
        if observed_times else 0
    )
    return {
        "observations": len(rows),
        "contracts": len(by_contract),
        "unique_decisions": len({(row[0], row[1]) for row in rows}),
        "calendar_days": calendar_days,
        "transitions": transitions,
        "one_step_reversals": reversals,
        "gates": dict(sorted(gates.items())),
        "primary_labels": dict(sorted(labels.items())),
    }


def _shadow_cell(payload_json: str) -> str:
    """Return the frozen contract-type/DTE cell carried by the observation."""
    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return "UNKNOWN:-1"
    contract = (payload.get("facts") or {}).get("contract") or {}
    contract_type = str(contract.get("contract_type") or "UNKNOWN").upper()
    try:
        dte_target = int(contract.get("dte_target"))
    except (TypeError, ValueError):
        dte_target = -1
    if contract_type not in {"CALL", "PUT"} or dte_target < 0:
        return "UNKNOWN:-1"
    return f"{contract_type}:{dte_target}"


def shadow_cell_summary(connection: sqlite3.Connection) -> dict[str, dict]:
    """Summarize shadow behavior independently for every frozen cohort cell."""
    ensure_shadow_schema(connection)
    rows = connection.execute("""
        SELECT contract_ticker, decision_available_utc, observed_at_utc, gate,
               navigation_scope, fact_signature, primary_label, labels_json,
               payload_json
        FROM options_dna_shadow_observations
        ORDER BY observed_at_utc, rowid
    """).fetchall()
    grouped = defaultdict(list)
    for row in rows:
        grouped[_shadow_cell(row[8])].append(row)

    result = {}
    for cell, items in sorted(grouped.items()):
        gates = Counter(row[3] for row in items)
        labels = Counter(row[6] for row in items if row[6])
        by_contract = defaultdict(list)
        for row in items:
            by_contract[row[0]].append(row)
        sequence_metrics = [_sequence_metrics(sequence) for sequence in by_contract.values()]
        transitions = sum(item[0] for item in sequence_metrics)
        reversals = sum(item[1] for item in sequence_metrics)
        observed_times = [_timestamp(row[2]) for row in items]
        calendar_days = (
            (max(observed_times).date() - min(observed_times).date()).days + 1
            if observed_times else 0
        )
        result[cell] = {
            "observations": len(items),
            "contracts": len(by_contract),
            "unique_decisions": len({(row[0], row[1]) for row in items}),
            "calendar_days": calendar_days,
            "transitions": transitions,
            "one_step_reversals": reversals,
            "gates": dict(sorted(gates.items())),
            "primary_labels": dict(sorted(labels.items())),
        }
    return result


def assess_shadow_readiness(
    connection: sqlite3.Connection, *, min_unique_decisions: int,
    min_calendar_days: int, min_labeled_observations: int,
    max_ineligible_fraction: float, max_reversal_fraction: float,
) -> dict:
    """Evaluate explicitly supplied shadow gates; no defaults are improvised."""
    summary = shadow_summary(connection)
    observations = summary["observations"]
    ready_gate = summary["gates"].get("READY_FOR_SHADOW_RULES", 0)
    labeled = sum(summary["primary_labels"].values())
    transitions = summary["transitions"]
    ineligible_fraction = 1.0 - ready_gate / observations if observations else 1.0
    reversal_fraction = summary["one_step_reversals"] / transitions if transitions else 0.0
    checks = {
        "unique_decisions": summary["unique_decisions"] >= min_unique_decisions,
        "calendar_days": summary["calendar_days"] >= min_calendar_days,
        "labeled_observations": labeled >= min_labeled_observations,
        "ineligible_fraction": ineligible_fraction <= max_ineligible_fraction,
        "reversal_fraction": reversal_fraction <= max_reversal_fraction,
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "ineligible_fraction": ineligible_fraction,
        "reversal_fraction": reversal_fraction,
        "summary": summary,
    }


def assess_shadow_promotion_readiness(
    connection: sqlite3.Connection, *, required_cells: list[str],
    min_contracts_per_cell: int, min_unique_decisions_per_cell: int,
    min_calendar_days_per_cell: int, min_transitions_per_cell: int,
    min_labeled_observations_per_cell: int, max_ineligible_fraction_per_cell: float,
    max_reversal_fraction_per_cell: float,
) -> dict:
    """Apply explicit promotion gates to each required cohort independently."""
    if not required_cells:
        raise ValueError("required_cells cannot be empty")
    summaries = shadow_cell_summary(connection)
    cells = {}
    for cell in required_cells:
        summary = summaries.get(cell, {
            "observations": 0, "contracts": 0, "unique_decisions": 0,
            "calendar_days": 0, "transitions": 0, "one_step_reversals": 0,
            "gates": {}, "primary_labels": {},
        })
        observations = summary["observations"]
        ready_gate = summary["gates"].get("READY_FOR_SHADOW_RULES", 0)
        labeled = sum(summary["primary_labels"].values())
        transitions = summary["transitions"]
        ineligible_fraction = 1.0 - ready_gate / observations if observations else 1.0
        reversal_fraction = (
            summary["one_step_reversals"] / transitions if transitions else 0.0
        )
        checks = {
            "contracts": summary["contracts"] >= min_contracts_per_cell,
            "unique_decisions": (
                summary["unique_decisions"] >= min_unique_decisions_per_cell
            ),
            "calendar_days": summary["calendar_days"] >= min_calendar_days_per_cell,
            "transitions": summary["transitions"] >= min_transitions_per_cell,
            "labeled_observations": (
                labeled >= min_labeled_observations_per_cell
            ),
            "ineligible_fraction": (
                ineligible_fraction <= max_ineligible_fraction_per_cell
            ),
            "reversal_fraction": (
                reversal_fraction <= max_reversal_fraction_per_cell
            ),
        }
        cells[cell] = {
            "ready": all(checks.values()), "checks": checks,
            "ineligible_fraction": ineligible_fraction,
            "reversal_fraction": reversal_fraction, "summary": summary,
        }
    return {
        "ready": all(item["ready"] for item in cells.values()),
        "required_cells": list(required_cells),
        "cells": cells,
        "unclassified": summaries.get("UNKNOWN:-1"),
    }
