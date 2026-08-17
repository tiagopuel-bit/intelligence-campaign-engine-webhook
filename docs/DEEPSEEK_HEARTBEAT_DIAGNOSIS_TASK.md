# Urgent diagnostic — underlying/option heartbeat tables, live check

**For:** DeepSeek, right now, market is open. Read-only diagnostic, not a
build task.

## Why

`/paper/health` has shown `BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT` +
`BLOCKED_NO_FRESH_OPTION_HEARTBEAT` (x4) continuously since before market
open, still blocked 5.5 hours into Monday's session, even though AMC's
regular DNA alerts are clearly flowing (`live_webhook` count rising).
`_record_price_heartbeat()` in `webhook_receiver.py` shows these two
tables are populated by a **separate payload shape**
(`kind: "UNDERLYING_HEARTBEAT"` / `"OPTION_HEARTBEAT"`), not by the
regular DNA event alerts — and `/state_all/AMC`'s tracked ladder has no
1-minute timeframe at all. Strong signal this was simply never wired up
in TradingView, but needs confirming against the real DB.

## What to check (live Railway DB, over SSH — same access as tonight)

```sql
SELECT COUNT(*), MAX(bar_time), MAX(received_at) FROM underlying_heartbeats WHERE symbol='AMC';
SELECT COUNT(*), MAX(bar_time), MAX(received_at) FROM option_heartbeats;
```

Report back exactly:
1. Row counts — zero (never wired) vs. non-zero-but-stale (was working,
   now stopped)?
2. If non-zero, the most recent `received_at` — how long ago?
3. If zero, confirm nothing in the `alerts` table has ever carried
   `kind: "UNDERLYING_HEARTBEAT"` either (in case it's landing somewhere
   unexpected instead of being rejected).

## Boundary

Read-only. No schema/code changes, no writes, no activation. Just the
real numbers — this is purely to tell Tiago whether he needs to create
new TradingView alerts (zero rows ever) or debug an existing one that
stopped (non-zero, stale).
