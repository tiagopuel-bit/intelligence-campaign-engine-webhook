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


def init_db(db_path: str | Path) -> None:
    schema = (ROOT / "paper_execution" / "schema_v1.sql").read_text(encoding="utf-8")
    conn = connect(db_path)
    try:
        conn.executescript(schema)
        _ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()
