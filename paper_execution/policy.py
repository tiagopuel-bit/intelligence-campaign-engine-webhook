"""Reference-only policy loading and lifecycle validation for the paper experiment.

P0 design stage: these are deterministic helpers used by tests. No timers, APIs,
scheduler, UI or broker path exist here.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PAPER_ONLY_MODES = frozenset({
    "ADVISORY_ONLY", "APPROVAL_REQUIRED", "AUTO_IF_VERY_HIGH_PAPER", "PROTECTION_ONLY_PAPER",
})
FORBIDDEN_LIVE_MODES = frozenset({"LIVE", "AUTO_IF_HIGH_LIVE", "PAPER_LIVE", "BROKER"})

# Append-only lifecycle. The event ledger is authoritative.
ALLOWED_TRANSITIONS = frozenset({
    ("DRAFT", "PENDING_APPROVAL"),
    ("PENDING_APPROVAL", "APPROVED"),
    ("PENDING_APPROVAL", "REJECTED"),
    ("PENDING_APPROVAL", "CANCELLED"),
    ("PENDING_APPROVAL", "EXPIRED"),
    ("PENDING_APPROVAL", "REVALIDATING"),
    ("REVALIDATING", "PAPER_EXECUTED"),
    ("REVALIDATING", "CANCELLED_REVALIDATION"),
    ("APPROVED", "REVALIDATING"),
    ("PAPER_EXECUTED", "PARTIALLY_FILLED"),
    ("PAPER_EXECUTED", "FILLED"),
    ("PAPER_EXECUTED", "UNFILLED"),
    ("PAPER_EXECUTED", "UNSCORABLE_EXECUTION_DATA"),
    ("PAPER_EXECUTED", "EXPIRED_UNFILLED"),
})

# Future/outcome fragments that must never appear in proposal generation inputs.
FUTURE_FRAGMENTS = (
    "mfe", "mae", "terminal_return", "bars_to_peak", "bars_to_trough",
    "gain_retention", "forward_outcome", "future_labels", "giveback",
)


def load_policy(path: str | Path | None = None) -> dict:
    target = Path(path) if path is not None else ROOT / "paper_execution" / "policy_v1.json"
    return json.loads(target.read_text(encoding="utf-8"))


def validate_transition(from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in ALLOWED_TRANSITIONS


def paper_only(policy: dict) -> bool:
    modes = set(policy.get("allowed_modes", []))
    return bool(modes) and modes <= PAPER_ONLY_MODES and not (modes & FORBIDDEN_LIVE_MODES)


def has_future_fragments(value: object) -> bool:
    text = json.dumps(value, sort_keys=True, default=str).lower()
    return any(fragment in text for fragment in FUTURE_FRAGMENTS)
