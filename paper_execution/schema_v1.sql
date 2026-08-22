-- AMC paper execution experiment — schema v1 (PAPER_ONLY)
-- Append-only lifecycle: pe_proposal_events is authoritative; current_status
-- columns are denormalized for efficient reads only.

PRAGMA foreign_keys = ON;

-- One experiment (goal contract). User-supplied goal fields are NOT NULL and
-- must be approved before P0 passes.
CREATE TABLE IF NOT EXISTS pe_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    start_at TEXT NOT NULL,                -- America/Los_Angeles aware ISO
    end_at TEXT NOT NULL,
    starting_cash REAL NOT NULL,
    starting_value_method TEXT NOT NULL,
    target_value_jan2027 REAL NOT NULL,    -- user-supplied
    target_return_pct REAL,                -- derived, frozen
    max_drawdown_pct REAL NOT NULL,        -- user-supplied
    max_amc_exposure REAL NOT NULL,        -- user-supplied
    max_exposure_per_option_expiry REAL NOT NULL, -- user-supplied
    deposit_policy TEXT NOT NULL,          -- PROHIBITED | TRACKED_SEPARATE
    allowed_actions TEXT NOT NULL,         -- comma list
    benchmark_symbol TEXT NOT NULL,
    benchmark_success_criteria TEXT NOT NULL,
    min_observation_count INTEGER NOT NULL,
    max_daily_paper_loss REAL NOT NULL,
    max_orders_per_day INTEGER NOT NULL,
    max_consecutive_failed_proposals INTEGER NOT NULL,
    milestones_json TEXT NOT NULL,          -- Silver/Gold/Premium/Diamond target values
    amc_target_floor_pct REAL NOT NULL,     -- strategic AMC floor (e.g. 30)
    confidence_status TEXT NOT NULL DEFAULT 'INTACT'
        CHECK(confidence_status IN ('INTACT','CONFIDENCE_WITHDRAWN','DECISION_REQUIRED','DISAGREEMENT')),
    auto_mode TEXT NOT NULL DEFAULT 'APPROVAL_REQUIRED'
        CHECK(auto_mode IN ('ADVISORY_ONLY','APPROVAL_REQUIRED','AUTO_IF_VERY_HIGH_PAPER','PROTECTION_ONLY_PAPER')),
    auto_enabled_global INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    contract_sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- Immutable starting holdings snapshot (valued under the declared method).
CREATE TABLE IF NOT EXISTS pe_starting_holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    instrument_type TEXT NOT NULL CHECK(instrument_type IN ('SHARE','CALL','PUT')),
    ticker TEXT,
    strike REAL,
    expiration TEXT,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    market_value REAL NOT NULL,
    frozen_at TEXT NOT NULL
);

-- Tracked symbols for a multi-asset experiment (anchor symbol stays on
-- pe_experiments.symbol for the existing single-symbol validation path).
CREATE TABLE IF NOT EXISTS pe_experiment_symbols (
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    symbol TEXT NOT NULL,
    PRIMARY KEY (experiment_id, symbol)
);

-- Order proposals. idempotency_key is unique per experiment.
CREATE TABLE IF NOT EXISTS pe_order_proposals (
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
);

-- Evidence snapshot per proposal (named roots + raw causal fields + missing).
CREATE TABLE IF NOT EXISTS pe_proposal_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES pe_order_proposals(id),
    root TEXT NOT NULL,                     -- underlying_dna | contract_response | execution_quality | portfolio_risk | catalyst
    present INTEGER NOT NULL,
    raw_fields TEXT NOT NULL,               -- JSON of causal fields only
    missing_evidence TEXT,                  -- JSON list
    contradictions TEXT,                    -- JSON list
    veto INTEGER NOT NULL DEFAULT 0
);

-- Append-only lifecycle events. The authoritative history.
CREATE TABLE IF NOT EXISTS pe_proposal_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES pe_order_proposals(id),
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,                    -- system | user | revalidation
    reason TEXT,
    UNIQUE(proposal_id, id)
);

-- Paper orders (one per leg for rolls).
CREATE TABLE IF NOT EXISTS pe_paper_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES pe_order_proposals(id),
    leg_index INTEGER NOT NULL DEFAULT 0,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('buy_to_open','buy_to_close','sell_to_open','sell_to_close')),
    quantity REAL NOT NULL,
    price_reference TEXT,                    -- declared bar-close model (NULL for unscorable)
    price_source TEXT,
    bar_time TEXT,
    status TEXT NOT NULL,                   -- PENDING | FILLED | PARTIALLY_FILLED | UNFILLED | EXPIRED_UNFILLED | UNSCORABLE_EXECUTION_DATA
    created_at TEXT NOT NULL
);

-- Paper fills (append-only).
CREATE TABLE IF NOT EXISTS pe_paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id INTEGER NOT NULL REFERENCES pe_paper_orders(id),
    fill_price REAL,
    fill_quantity REAL,
    fill_time TEXT NOT NULL,
    model_note TEXT NOT NULL
);

-- User decisions and overrides.
CREATE TABLE IF NOT EXISTS pe_user_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES pe_order_proposals(id),
    decision TEXT NOT NULL CHECK(decision IN ('APPROVE','MODIFY','REJECT','CANCEL_AUTO','CANCEL_GLOBAL','CANCEL_POSITION')),
    at TEXT NOT NULL,
    notes TEXT,
    modification TEXT                       -- JSON of the modified proposal
);

-- Outcome snapshots (later observed prices; never rewritten).
CREATE TABLE IF NOT EXISTS pe_outcome_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id INTEGER NOT NULL REFERENCES pe_order_proposals(id),
    order_id INTEGER REFERENCES pe_paper_orders(id),
    observed_price REAL,
    observed_at TEXT NOT NULL,
    source TEXT NOT NULL
);

-- Daily portfolio reports.
CREATE TABLE IF NOT EXISTS pe_daily_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    report_date TEXT NOT NULL,
    portfolio_value REAL NOT NULL,
    market_performance_pnl REAL NOT NULL,
    external_flow REAL NOT NULL,
    drawdown_pct REAL,
    progress_vs_target REAL,
    progress_vs_baseline REAL,
    target_pace_risk_exceeded INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL,
    UNIQUE(experiment_id, report_date)
);

-- Auto switches (global + per position). Disabled switch wins over any timer.
-- position_ref is '' for GLOBAL so the UNIQUE constraint holds (SQLite treats
-- NULL as distinct and would otherwise allow duplicate global switches).
CREATE TABLE IF NOT EXISTS pe_auto_switches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    scope TEXT NOT NULL CHECK(scope IN ('GLOBAL','POSITION','SYMBOL')),
    position_ref TEXT NOT NULL DEFAULT '',
    auto_enabled INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL,
    UNIQUE(experiment_id, scope, position_ref)
);

CREATE INDEX IF NOT EXISTS idx_proposals_status ON pe_order_proposals(current_status, expires_at);
CREATE INDEX IF NOT EXISTS idx_events_proposal ON pe_proposal_events(proposal_id, id);

-- Paper portfolio ledger (simulated). Never touches the live/manual positions.
CREATE TABLE IF NOT EXISTS pe_paper_cash (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    cash REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(experiment_id)
);

CREATE TABLE IF NOT EXISTS pe_paper_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    symbol TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    ticker TEXT,
    quantity REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(experiment_id, ticker, instrument_type)
);

-- Manual cash-ledger correction, deliberately separate from the evidence-
-- driven proposal path. Exists for cases the automated pipeline structurally
-- cannot handle -- most commonly a contract that has already expired, so no
-- live pricing evidence can ever exist for it again (found 2026-08-22: an
-- AMC option leg genuinely closed at a real price, but /paper/proposals
-- correctly refused "no authoritative state" since the expired contract has
-- no fresh option_heartbeats). This table is the append-only audit trail --
-- every adjustment needs a human-readable reason, and rows are never
-- updated or deleted, only added.
CREATE TABLE IF NOT EXISTS pe_cash_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    position_ref INTEGER,
    instrument_ref INTEGER,
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

-- Position-side counterpart to pe_cash_adjustments -- same discipline,
-- append-only audit trail, never updated or deleted. Only ever adjusts an
-- EXISTING pe_paper_positions row (position-adjustment's route enforces
-- this); never creates a new one, since that would be a genuine new open
-- and must go through the real /paper/proposals evidence path instead.
CREATE TABLE IF NOT EXISTS pe_position_adjustments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    ticker TEXT NOT NULL,
    instrument_type TEXT NOT NULL,
    quantity_delta REAL NOT NULL,
    reason TEXT NOT NULL,
    position_ref INTEGER,
    instrument_ref INTEGER,
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL
);

-- Per-position protective bracket (stop-loss + take-profit). Pre-registered
-- standing orders: the runner fires them on a price crossing WITHOUT the
-- 600-second approval window. At most one ACTIVE bracket per paper position;
-- upsert supersedes the active bracket, historical rows are preserved.
CREATE TABLE IF NOT EXISTS pe_position_brackets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id INTEGER NOT NULL REFERENCES pe_experiments(id),
    symbol TEXT NOT NULL,
    ticker TEXT NOT NULL,
    instrument_type TEXT NOT NULL DEFAULT 'SHARE',
    direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
    stop_price REAL,
    target_price REAL,
    status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','TRIGGERED','CANCELLED')),
    created_by TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    triggered_at TEXT,
    triggered_side TEXT CHECK(triggered_side IN ('STOP','TARGET')),
    trigger_price REAL,
    fill_price REAL,
    fill_note TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_brackets_one_active
    ON pe_position_brackets(experiment_id, ticker) WHERE status='ACTIVE';
