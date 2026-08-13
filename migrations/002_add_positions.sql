-- Positions tracking (beta) -- manual entry/exit log, not broker-connected.
-- Two-table design: `positions` is the trade idea/campaign the user is
-- tracking (one per open thesis); `position_instruments` is each actual
-- leg against it (shares, or a specific option contract) so adds, rolls,
-- and partial closes are all representable without mutating history.

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL CHECK(direction IN ('LONG','SHORT')),
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    -- Which DNA read the idea came from, if any -- purely descriptive,
    -- never re-derived or validated against the live alerts table.
    origin_timeframe TEXT,
    origin_event TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS position_instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL REFERENCES positions(id) ON DELETE CASCADE,
    instrument_type TEXT NOT NULL CHECK(instrument_type IN ('SHARE','CALL','PUT')),
    strike REAL,          -- NULL for SHARE
    expiration TEXT,      -- NULL for SHARE, ISO date otherwise
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    entry_time TEXT NOT NULL,
    exit_price REAL,
    exit_time TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','CLOSED','ROLLED')),
    -- A roll closes one instrument row and opens a new one, linked both
    -- ways, so "what did this position use to be" stays queryable instead
    -- of overwriting the old strike/expiration in place.
    rolled_from_id INTEGER REFERENCES position_instruments(id),
    rolled_to_id INTEGER REFERENCES position_instruments(id),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol_status ON positions(symbol, status);
CREATE INDEX IF NOT EXISTS idx_instruments_position ON position_instruments(position_id);
