# Task Packet — Positions Tracking DB (beta)

**Requested by:** Tiago, 2026-08-12. **For:** DeepSeek.
**Schema already drafted:** `migrations/002_add_positions.sql` — read that first, don't redesign the tables, just review and flag if something's actually wrong.

## Goal

A manual position log Tiago can add to / edit / test against — beta quality, not broker-connected. This is the Phase 3 concept from `DNA_Asset_Landing_Page_Spec_v1.md`, being built early because Tiago wants to see it now for structure purposes, not because Phase 3 is unblocked.

## Design (already decided, don't relitigate)

Two tables, not one:
- `positions` — the trade idea itself (symbol, direction, opened/closed, which DNA read it came from — descriptive only, never re-validated).
- `position_instruments` — each actual leg against it: shares, or a specific option contract (strike/expiration/quantity/entry/exit). Multiple rows per position support adds, and rolls are modeled as closing one instrument row and opening a new one linked both ways (`rolled_from_id`/`rolled_to_id`) — never overwrite strike/expiration in place, or the history of what the position used to be is lost.

This mirrors how the real Trade Box in Pine already thinks about a position (`activeExtensionCount`, `activeTradeSource` changing on ADD/roll) — same shape, just persisted instead of ephemeral.

## API surface needed (Flask, same file/module conventions as `massive_ohlc.py`)

- `POST /positions` — create `{symbol, direction, origin_timeframe, origin_event, notes, instrument: {type, strike, expiration, quantity, entry_price, entry_time}}`
- `GET /positions?symbol=&status=` — list
- `GET /positions/<id>` — full detail: the position + all its instruments + a joined "DNA context" block (most recent alert per timeframe for that symbol where `received_at >= opened_at` — reuse the exact query pattern already in `get_state_all()`, don't build a new one)
- `POST /positions/<id>/instruments` — add a leg (new add, or the "opened" half of a roll)
- `PATCH /positions/<id>/instruments/<iid>` — close/update a leg (`exit_price`, `exit_time`, `status`)
- `PATCH /positions/<id>` — update `status`/`closed_at`/`notes`

All gated by the existing `state_is_authorized()` — same as every other endpoint, no new auth model needed. This is a personal beta tool, not a public write API, so reusing the existing token gate for writes too is the right call, not a shortcut.

## How this ties to the OHLC work you're already on

Your `/ohlc/<symbol>/<timeframe>` bars use epoch-ms `t`. `entry_time`/`exit_time` here are ISO strings (matching the existing `alerts.received_at` convention) — the frontend converts ISO→ms trivially for chart-marker alignment, so don't add a second timestamp format to reconcile. Just flagging so nobody "fixes" this into a mismatch.

## Explicitly not in scope for this packet

- Any actual chart rendering — frontend work, stays with Claude Code once this + OHLC both exist.
- Broker integration of any kind — this stays manual-entry only.
- Automatic position creation from DNA events — a human logs it, the system never opens anything, same rule as everywhere else in this project.

## What to report back

Real `POST`/`GET` responses against a test position, not a description of the schema working.
