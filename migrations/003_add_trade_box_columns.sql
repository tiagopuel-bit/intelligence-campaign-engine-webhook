-- Migration 003: add Trade Box zone columns to the `alerts` table.
--
-- Non-destructive: nullable, no DEFAULT, so existing rows keep their data and
-- simply read NULL for the new columns. Safe to run on a live DB without data
-- loss.
--
-- Purpose: store the additive Trade Box zone values emitted by Pine v12.6.21's
-- webhook payload (active_trade, active_entry, active_stop, active_target,
-- active_trade_source, active_trade_open_pct) so the landing-page chart can
-- draw the open position's entry/stop/target zones on price.
--
-- NOTE: webhook_receiver.init_db() also applies these idempotently at startup
-- (via PRAGMA table_info + ALTER), so this file is documentation + a manual
-- fallback. SQLite has no `ADD COLUMN IF NOT EXISTS`; verify before re-running:
--     PRAGMA table_info(alerts);
ALTER TABLE alerts ADD COLUMN active_trade INTEGER;
ALTER TABLE alerts ADD COLUMN active_entry REAL;
ALTER TABLE alerts ADD COLUMN active_stop REAL;
ALTER TABLE alerts ADD COLUMN active_target REAL;
ALTER TABLE alerts ADD COLUMN active_trade_source TEXT;
ALTER TABLE alerts ADD COLUMN active_trade_open_pct REAL;
