"""Idempotent SQLite initialization and migration for the paper execution experiment."""
from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_columns(conn) -> None:
    """Add columns added after the first schema version, idempotently."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(pe_order_proposals)")}
    if "parent_proposal_id" not in existing:
        conn.execute(
            "ALTER TABLE pe_order_proposals ADD COLUMN parent_proposal_id INTEGER "
            "REFERENCES pe_order_proposals(id)"
        )
    if "version" not in existing:
        conn.execute("ALTER TABLE pe_order_proposals ADD COLUMN version INTEGER NOT NULL DEFAULT 1")
    if "position_ref" not in existing:
        conn.execute("ALTER TABLE pe_order_proposals ADD COLUMN position_ref TEXT")
    if "instrument_ref" not in existing:
        conn.execute("ALTER TABLE pe_order_proposals ADD COLUMN instrument_ref TEXT")
    order_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pe_paper_orders)")}
    if "price_source" not in order_columns:
        conn.execute("ALTER TABLE pe_paper_orders ADD COLUMN price_source TEXT")
    if "bar_time" not in order_columns:
        conn.execute("ALTER TABLE pe_paper_orders ADD COLUMN bar_time TEXT")
    _ensure_symbol_scope(conn)
    _ensure_set_bracket(conn)


def _ensure_set_bracket(conn) -> None:
    """Data-preserving migration: widen the proposal action CHECK to include
    ``set_bracket`` and add ``stop_price``/``target_price`` columns.

    Older DBs CHECK(action IN (...,'roll')); SQLite cannot alter a CHECK in
    place, so the table is rebuilt with the wider constraint plus the two price
    columns. Existing rows are copied unchanged (prices NULL). Foreign keys are
    briefly disabled because pe_order_proposals is referenced by child tables.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='pe_order_proposals'"
    ).fetchone()
    if row is None:
        return
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(pe_order_proposals)")}
    if "set_bracket" in (row["sql"] or "") and "stop_price" in columns and "target_price" in columns:
        return

    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("ALTER TABLE pe_order_proposals RENAME TO pe_order_proposals_old")
        conn.execute("""
            CREATE TABLE pe_order_proposals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
                idempotency_key TEXT NOT NULL,
                parent_proposal_id INTEGER REFERENCES pe_order_proposals(id),
                version INTEGER NOT NULL DEFAULT 1,
                policy_version INTEGER NOT NULL,
                policy_sha256 TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('hold','open','add','partial_reduce','close','roll','set_bracket')),
                mode TEXT NOT NULL CHECK(mode IN ('ADVISORY_ONLY','APPROVAL_REQUIRED','AUTO_IF_VERY_HIGH_PAPER','PROTECTION_ONLY_PAPER')),
                symbol TEXT NOT NULL,
                position_ref TEXT,
                instrument_ref TEXT,
                time_sensitive_reason TEXT,
                very_high INTEGER NOT NULL DEFAULT 0,
                very_high_missing_roots TEXT,
                status TEXT NOT NULL,
                current_status TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                cancel_condition TEXT NOT NULL,
                created_at TEXT NOT NULL,
                stop_price REAL,
                target_price REAL,
                UNIQUE(experiment_id, idempotency_key)
            )
        """)
        conn.execute("""
            INSERT INTO pe_order_proposals (
                id, experiment_id, idempotency_key, parent_proposal_id, version,
                policy_version, policy_sha256, action, mode, symbol, position_ref,
                instrument_ref, time_sensitive_reason, very_high, very_high_missing_roots,
                status, current_status, expires_at, cancel_condition, created_at,
                stop_price, target_price
            )
            SELECT id, experiment_id, idempotency_key, parent_proposal_id, version,
                policy_version, policy_sha256, action, mode, symbol, position_ref,
                instrument_ref, time_sensitive_reason, very_high, very_high_missing_roots,
                status, current_status, expires_at, cancel_condition, created_at,
                NULL, NULL
            FROM pe_order_proposals_old
        """)
        conn.execute("DROP TABLE pe_order_proposals_old")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_proposals_status ON pe_order_proposals(current_status, expires_at)")
    finally:
        conn.execute("PRAGMA foreign_keys=ON")


def _ensure_symbol_scope(conn) -> None:
    """Data-preserving migration: allow scope='SYMBOL' on pe_auto_switches.

    Older DBs were created with CHECK(scope IN ('GLOBAL','POSITION')); SQLite
    cannot alter a CHECK in place, so the table is rebuilt with the wider
    constraint. Existing GLOBAL/POSITION rows are copied unchanged.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='pe_auto_switches'"
    ).fetchone()
    if row is None or "SYMBOL" in (row["sql"] or ""):
        return
    conn.execute("ALTER TABLE pe_auto_switches RENAME TO pe_auto_switches_old")
    conn.execute("""
        CREATE TABLE pe_auto_switches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
            scope TEXT NOT NULL CHECK(scope IN ('GLOBAL','POSITION','SYMBOL')),
            position_ref TEXT NOT NULL DEFAULT '',
            auto_enabled INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL,
            UNIQUE(experiment_id, scope, position_ref)
        )
    """)
    conn.execute("INSERT INTO pe_auto_switches SELECT * FROM pe_auto_switches_old")
    conn.execute("DROP TABLE pe_auto_switches_old")


def init_db(db_path: str | Path) -> None:
    schema = (ROOT / "paper_execution" / "schema_v1.sql").read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(schema)
        _ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()
